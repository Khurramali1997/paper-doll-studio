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
    return pipe


def _canny_image(img: Image.Image) -> Image.Image:
    import cv2
    import numpy as np
    arr = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    return Image.fromarray(edges).convert("RGB")


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
    fast: bool = Form(True),
    feather: int = Form(8),
    controlnet: bool = Form(False),
    controlnet_model: str = Form("lllyasviel/control_v11p_sd15_canny"),
    controlnet_scale: float = Form(0.5),
    model_repo: str = Form(DEFAULT_MODEL_REPO),
    device: str = Form("auto"),
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
):
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")

    job_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = {"cancel": cancel_event, "queue": queue, "loop": loop}

    image_bytes = await image.read()
    mask_bytes = await mask.read()
    resolved_device = choose_device(device)
    actual_steps = min(steps, 12) if fast else steps

    def run():
        try:
            if controlnet:
                with _pipe_lock:
                    pipe = _load_controlnet_pipe(model_repo, resolved_device, controlnet_model)
            else:
                ensure_pipe(model_repo, resolved_device)
                pipe = _pipe

            size = (width, height)
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize(size, Image.Resampling.LANCZOS)
            msk = Image.open(io.BytesIO(mask_bytes)).convert("L").resize(size, Image.Resampling.LANCZOS)
            if feather > 0:
                msk = msk.filter(ImageFilter.GaussianBlur(radius=feather))

            control_img = _canny_image(img) if controlnet else None
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
                width=width,
                height=height,
                num_inference_steps=actual_steps,
                guidance_scale=guidance_scale,
                strength=max(0.0, min(1.0, strength)),
                generator=generator,
                callback_on_step_end=on_step,
            )
            if controlnet:
                call_kwargs["control_image"] = control_img
                call_kwargs["controlnet_conditioning_scale"] = controlnet_scale

            result_img = pipe(**call_kwargs).images[0]

            if cancel_event.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "cancelled"})
                return

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
