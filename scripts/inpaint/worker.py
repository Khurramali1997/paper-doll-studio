#!/usr/bin/env python3
"""Persistent inpaint worker — loads the model once and serves inference via HTTP.

Run manually or let the bridge start it:
  python scripts/inpaint/worker.py [--port 7863] [--model-repo ...] [--device auto]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional

import torch
from diffusers import DPMSolverMultistepScheduler, StableDiffusionInpaintPipeline
from PIL import Image, ImageFilter
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse


DEFAULT_MODEL_REPO = "Sanster/anything-4.0-inpainting"
DEFAULT_NEGATIVE = (
    "low quality, blurry, deformed, extra limbs, body paint, skin tight "
    "bodysuit, naked, watermark, text, logo, multiple people, bad anatomy, "
    "worst quality, normal quality"
)

# Slot-aware scaffold around the user's prompt. The positive snippet is
# prepended, the negative snippet is appended to the user's negative prompt.
# Keep entries tight — they bias generation toward the requested garment only.
SLOT_SCAFFOLDS = {
    "topwear": (
        "upper-body garment only, shirt or top or jacket, ",
        ", pants, trousers, skirt, shoes, hat",
    ),
    "bottomwear": (
        "lower-body garment only, pants or skirt or shorts, ",
        ", shirt, top, jacket, hat, shoes",
    ),
    "headwear": (
        "head accessory only, hat or cap or hood, ",
        ", shirt, pants, shoes, full body, hair replacement",
    ),
    "neckwear": (
        "neck accessory only, scarf or necklace or collar, ",
        ", shirt, pants, shoes, hat",
    ),
    "handwear": (
        "hand accessory only, gloves or bracelets, ",
        ", shirt, pants, shoes, hat",
    ),
    "legwear": (
        "leg accessory only, stockings or socks or leggings, ",
        ", shirt, jacket, pants, shoes, hat",
    ),
    "footwear": (
        "footwear only, shoes or boots or sandals, ",
        ", shirt, pants, hat, full body",
    ),
}


def _smooth_painted_mask(mask_u8):
    """Close 1-px brush holes without changing the painted geometry.

    A 3x3 morphological close fills hairline gaps inside a brush stroke; the
    operation cannot shrink the masked area. We deliberately do not drop
    disconnected components — users may legitimately paint multiple separate
    regions (e.g. sleeves on both arms).
    """
    import cv2
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel, iterations=1)

# ── global model state ────────────────────────────────────────────────────────
_pipe: Optional[StableDiffusionInpaintPipeline] = None
_loaded_repo: Optional[str] = None
_loaded_device: Optional[str] = None
_pipe_lock = threading.Lock()

# job_id -> {cancel: threading.Event, queue: asyncio.Queue, loop: asyncio loop}
_jobs: Dict[str, dict] = {}


def choose_device(name: str) -> str:
    if name != "auto":
        return name
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _build_pipe(model_repo: str, device: str) -> StableDiffusionInpaintPipeline:
    dtype = torch.float16 if device == "cuda" else torch.float32
    pipe = StableDiffusionInpaintPipeline.from_pretrained(
        model_repo, torch_dtype=dtype, safety_checker=None,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True,
    )
    pipe = pipe.to(device)
    if device == "mps":
        pipe.enable_attention_slicing()
        pipe.enable_vae_slicing()
    return pipe


def ensure_pipe(model_repo: str, device: str):
    global _pipe, _loaded_repo, _loaded_device
    with _pipe_lock:
        if _pipe is None or _loaded_repo != model_repo or _loaded_device != device:
            _pipe = _build_pipe(model_repo, device)
            _loaded_repo = model_repo
            _loaded_device = device


def _load_controlnet_pipe(model_repo: str, device: str, controlnet_model: str):
    """Return a ControlNetInpaintPipeline; requires diffusers>=0.26."""
    from diffusers import ControlNetModel, StableDiffusionControlNetInpaintPipeline
    dtype = torch.float16 if device == "cuda" else torch.float32
    cn = ControlNetModel.from_pretrained(controlnet_model, torch_dtype=dtype)
    pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
        model_repo, controlnet=cn, torch_dtype=dtype, safety_checker=None,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True,
    )
    pipe = pipe.to(device)
    if device == "mps":
        pipe.enable_attention_slicing()
        pipe.enable_vae_slicing()
    return pipe


def _control_image(img: Image.Image) -> Image.Image:
    """Return a Canny edge map for control_v11p_sd15_canny conditioning."""
    import cv2
    import numpy as np
    arr = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    return Image.fromarray(edges).convert("RGB")


# IP-Adapter (style reference conditioning) — h94/IP-Adapter basic variant for
# SD 1.5. Adds ~44 MB adapter weights plus CLIP-ViT-H image encoder (~1.3 GB
# in fp16, ~2.5 GB in fp32). The cached pipe carries `_ip_loaded = True` once
# the adapter has been attached; subsequent calls just toggle scale.
IP_ADAPTER_REPO = "h94/IP-Adapter"
IP_ADAPTER_SUBFOLDER = "models"
IP_ADAPTER_WEIGHT = "ip-adapter_sd15.safetensors"


def _ensure_ip_adapter(pipe) -> None:
    """Attach IP-Adapter weights to the pipe in-place. No-op if already loaded."""
    if getattr(pipe, "_ip_loaded", False):
        return
    pipe.load_ip_adapter(
        IP_ADAPTER_REPO,
        subfolder=IP_ADAPTER_SUBFOLDER,
        weight_name=IP_ADAPTER_WEIGHT,
    )
    pipe._ip_loaded = True


# Upscaler choices. Lanczos is the zero-dep default; RealESRGAN-anime
# preserves cel-shaded lineart better at the cost of an extra ~70 MB model
# load and a few seconds per upscale on M-series MPS.
REALESRGAN_ANIME_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/"
    "v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
)
_realesrgan_anime = None


def _ensure_realesrgan_anime(device: str):
    """Lazy-load the RealESRGAN-anime 6B upsampler. Raises ImportError if the
    [upscale] extras aren't installed."""
    global _realesrgan_anime
    if _realesrgan_anime is not None:
        return _realesrgan_anime
    try:
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
    except ImportError as exc:
        raise ImportError(
            "RealESRGAN dependencies not installed. "
            "Run: pip install 'paperdoll-studio[upscale]'"
        ) from exc

    arch = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64,
        num_block=6, num_grow_ch=32, scale=4,
    )
    _realesrgan_anime = RealESRGANer(
        scale=4,
        model_path=REALESRGAN_ANIME_URL,
        model=arch,
        tile=0,
        tile_pad=10,
        pre_pad=0,
        half=False,  # fp16 is CUDA-only in basicsr; MPS/CPU need fp32
        device=device if device in ("cuda", "mps", "cpu") else "cpu",
    )
    return _realesrgan_anime


def _upscale(pil_img: Image.Image, target_size: tuple[int, int], upscaler: str, device: str) -> Image.Image:
    """Upscale to target_size. Falls back to Lanczos on any RealESRGAN error
    so a failed upscale never blocks a successful inpaint."""
    if pil_img.size == target_size:
        return pil_img
    if upscaler == "realesrgan-anime":
        try:
            import numpy as np
            upsampler = _ensure_realesrgan_anime(device)
            sr, _ = upsampler.enhance(np.array(pil_img.convert("RGB")), outscale=4)
            sr_pil = Image.fromarray(sr)
            if sr_pil.size != target_size:
                sr_pil = sr_pil.resize(target_size, Image.Resampling.LANCZOS)
            return sr_pil
        except ImportError as exc:
            print(f"[inpaint] RealESRGAN unavailable, falling back to Lanczos: {exc}", flush=True)
        except Exception as exc:
            print(f"[inpaint] RealESRGAN failed ({exc}), falling back to Lanczos", flush=True)
    return pil_img.resize(target_size, Image.Resampling.LANCZOS)


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True, "model": _loaded_repo, "device": _loaded_device}


@app.post("/generate")
async def generate(
    prompt: str = Form(...),
    negative_prompt: str = Form(DEFAULT_NEGATIVE),
    seed: int = Form(93),
    steps: int = Form(20),
    guidance_scale: float = Form(7.0),
    strength: float = Form(1.0),
    width: int = Form(512),
    height: int = Form(512),
    target_width: int = Form(0),
    target_height: int = Form(0),
    fast: bool = Form(True),
    feather: int = Form(8),
    dilate: int = Form(6),
    mask_smooth: bool = Form(True),
    garment_slot: Optional[str] = Form(None),
    crop_output: bool = Form(False),
    upscaler: str = Form("lanczos"),
    controlnet: bool = Form(False),
    controlnet_model: str = Form("lllyasviel/control_v11p_sd15_canny"),
    controlnet_scale: float = Form(0.5),
    ip_adapter: bool = Form(False),
    ip_scale: float = Form(0.6),
    model_repo: str = Form(DEFAULT_MODEL_REPO),
    device: str = Form("auto"),
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
    ip_reference: Optional[UploadFile] = File(None),
):
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")

    if controlnet and ip_adapter:
        raise HTTPException(
            400,
            "ControlNet and IP-Adapter cannot be enabled together — peak memory "
            "would exceed the 16 GB M-series budget. Pick one.",
        )

    if garment_slot and garment_slot in SLOT_SCAFFOLDS:
        pos_snip, neg_snip = SLOT_SCAFFOLDS[garment_slot]
        prompt = pos_snip + prompt
        negative_prompt = (negative_prompt or "") + neg_snip

    job_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = {"cancel": cancel_event, "queue": queue, "loop": loop}

    image_bytes = await image.read()
    mask_bytes = await mask.read()
    ip_reference_bytes = await ip_reference.read() if ip_reference is not None else None
    resolved_device = choose_device(device)
    actual_steps = min(steps, 12) if fast else steps

    # Diffusion is pinned to SD 1.5's native resolution. Anything coming in at
    # a larger canvas is shrunk for inference and upscaled on the way out.
    INFERENCE_SIZE = (512, 512)
    final_size = (
        target_width or width or INFERENCE_SIZE[0],
        target_height or height or INFERENCE_SIZE[1],
    )

    def run():
        try:
            if controlnet:
                with _pipe_lock:
                    pipe = _load_controlnet_pipe(model_repo, resolved_device, controlnet_model)
            else:
                ensure_pipe(model_repo, resolved_device)
                pipe = _pipe

            # Activate IP-Adapter only when both the toggle is on AND we have a
            # reference image. Without a reference, the adapter has nothing to
            # condition on — diffusers either zero-fills (wasted CLIP-Vision
            # forward pass) or errors depending on version. Either way, no-op.
            ip_active = bool(ip_adapter and ip_reference_bytes)
            if ip_active:
                with _pipe_lock:
                    _ensure_ip_adapter(pipe)
                pipe.set_ip_adapter_scale(ip_scale)
            elif getattr(pipe, "_ip_loaded", False):
                # IP-Adapter weights stay resident, but mute their effect.
                pipe.set_ip_adapter_scale(0.0)

            size = INFERENCE_SIZE
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize(size, Image.Resampling.LANCZOS)
            msk = Image.open(io.BytesIO(mask_bytes)).convert("L").resize(size, Image.Resampling.LANCZOS)
            import cv2
            import numpy as np
            msk_np = np.array(msk)
            if mask_smooth:
                msk_np = _smooth_painted_mask(msk_np)
            # Snapshot the user's intended garment shape BEFORE dilation —
            # used as alpha for crop_output so the cutout follows the
            # painted/SAM boundary, not the dilated latent-context boundary.
            crop_alpha_np = msk_np.copy() if crop_output else None
            if dilate > 0:
                kernel = cv2.getStructuringElement(
                    cv2.MORPH_ELLIPSE, (dilate * 2 + 1, dilate * 2 + 1)
                )
                msk_np = cv2.dilate(msk_np, kernel)
            msk = Image.fromarray(msk_np)
            if feather > 0:
                msk = msk.filter(ImageFilter.GaussianBlur(radius=feather))

            # Quick sanity check on the final mask — easy to spot from logs if
            # we ever again ship a regression that nukes the painted area.
            final_painted = int((np.array(msk) > 127).sum())
            print(
                f"[inpaint job {job_id[:8]}] mask {size[0]}x{size[1]} "
                f"painted_px={final_painted} smooth={mask_smooth} "
                f"dilate={dilate} feather={feather} strength={strength} "
                f"slot={garment_slot or '-'} "
                f"ip={ip_active} target={final_size[0]}x{final_size[1]}",
                flush=True,
            )

            control_img = _control_image(img) if controlnet else None
            ip_ref_img = None
            if ip_active:
                ip_ref_img = Image.open(io.BytesIO(ip_reference_bytes)).convert("RGB")
            generator = torch.Generator(device="cpu").manual_seed(seed)

            def on_step(step_pipe, step_index, timestep, callback_kwargs):
                if cancel_event.is_set():
                    step_pipe._interrupt = True
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "progress", "step": step_index + 1, "total": actual_steps},
                )
                return callback_kwargs

            call_kwargs = dict(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image=img,
                mask_image=msk,
                width=INFERENCE_SIZE[0],
                height=INFERENCE_SIZE[1],
                num_inference_steps=actual_steps,
                guidance_scale=guidance_scale,
                strength=max(0.0, min(1.0, strength)),
                generator=generator,
                padding_mask_crop=32,
                callback_on_step_end=on_step,
            )
            if controlnet:
                call_kwargs["control_image"] = control_img
                call_kwargs["controlnet_conditioning_scale"] = controlnet_scale
            if ip_active and ip_ref_img is not None:
                call_kwargs["ip_adapter_image"] = ip_ref_img

            result_img = pipe(**call_kwargs).images[0]

            if cancel_event.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "cancelled"})
                return

            # Diffusion ran at 512 — upscale back to the caller's target dims
            # so the result drops into the canvas at the right occupancy.
            # Lanczos by default; RealESRGAN-anime when the user opts in.
            result_img = _upscale(result_img, final_size, upscaler, resolved_device)

            # For per-garment refinement: instead of returning the full
            # naked-body composite (which the frontend would have to re-SAM
            # to extract this slot's cutout), return a canvas-sized RGBA with
            # the garment opaque and everything else transparent. Frontend
            # alpha-composites over the previous preview locally.
            if crop_output and crop_alpha_np is not None:
                alpha_img = Image.fromarray(crop_alpha_np, mode="L")
                if alpha_img.size != final_size:
                    alpha_img = alpha_img.resize(final_size, Image.Resampling.LANCZOS)
                # Soften the alpha edge a touch so the cutout doesn't show a
                # hard cutline when alpha-composited onto the preview.
                alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=1.5))
                rgba = result_img.convert("RGBA")
                rgba.putalpha(alpha_img)
                result_img = rgba

            out_dir = Path("public") / "assets" / "inpaint_generated"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"inpaint_{seed}_{uuid.uuid4().hex[:8]}.png"
            result_img.save(out_path)

            image_b64 = base64.b64encode(out_path.read_bytes()).decode("ascii")
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "result",
                "image_b64": image_b64,
                "image_path": str(out_path),
                "metadata": {
                    "prompt": prompt,
                    "seed": seed,
                    "steps": actual_steps,
                    "fast": fast,
                    "model_repo": model_repo,
                    "controlnet": controlnet,
                    "ip_adapter": ip_active,
                    "inference_size": list(INFERENCE_SIZE),
                    "output_size": list(final_size),
                    "crop_output": bool(crop_output),
                    "garment_slot": garment_slot,
                    "upscaler": upscaler,
                },
            })
        except Exception as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "message": str(exc)}
            )

    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.get("/progress/{job_id}")
async def progress_stream(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")
    queue = _jobs[job_id]["queue"]

    async def event_gen():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=300.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("result", "error", "cancelled"):
                    break
        except asyncio.TimeoutError:
            yield f'data: {json.dumps({"type": "error", "message": "Generation timed out"})}\n\n'
        finally:
            _jobs.pop(job_id, None)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/cancel/{job_id}")
async def cancel_job(job_id: str):
    if job_id in _jobs:
        _jobs[job_id]["cancel"].set()
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7863)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model-repo", default=DEFAULT_MODEL_REPO)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    resolved = choose_device(args.device)
    print(f"Loading {args.model_repo!r} on {resolved}…", flush=True)
    ensure_pipe(args.model_repo, resolved)
    print("Worker ready.", flush=True)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
