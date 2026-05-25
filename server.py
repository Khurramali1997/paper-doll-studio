#!/usr/bin/env python3
"""Paper Doll Studio — Backend API Server.

Serves static files and provides the POST /api/compile-asset endpoint
so that the frontend's Process button invokes the full Python compiler pipeline.
"""

import os
import sys
import json
import tempfile
import re
import uuid
from pathlib import Path

import mimetypes

from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from compiler.category_registry import ALL_CATEGORIES
from compiler.compiler import AssetCompiler
from compiler.guide_templates import build_guides_zip
from compiler.rig_autodetect import detect_anchors, build_rig
from compiler.reference_pack import build_reference_pack, build_reference_channels
from compiler.ai_segmenter import process as ai_process
from compiler.cleanup_assist import propose_lane_c_mask
from compiler.stencil_pipeline import run_pipeline as _run_stencil_pipeline, PIPELINE_CONFIG as _STENCIL_DEFAULTS
from compiler.coreml_bridge import CoreMLRequest, coreml_status, run_generation
from compiler.layerdiffuse_bridge import (
    LayerDiffuseRequest,
    layerdiffuse_status,
    normalize_request as normalize_layerdiffuse_request,
    run_generation as run_layerdiffuse_generation,
)

import io as _io
import json as _json
import base64 as _base64
from PIL import Image as _PILImage
import cv2
import numpy as np

BASE_RIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "base_rig")

app = FastAPI(title="Paper Doll Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

compiler = AssetCompiler()

OUTPUT_SUBDIR = os.path.join("public", "assets", "compiled")


def _slugify(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


@app.post("/api/compile-asset")
async def compile_asset(
    image: UploadFile = File(...),
    category: str = Form(...),
    display_name: str = Form(...),
    asset_id: str = Form(None),
    fit_method: str = Form("piecewise"),
    confirmed_anchors: str = Form(None),
    x_offset: float = Form(0.0),
    y_offset: float = Form(0.0),
    scale: float = Form(1.0),
    remove_bg: bool = Form(True),
    chromakey_color: str = Form("#ffffff"),
    chromakey_tolerance: int = Form(40),
    force_chromakey: bool = Form(False),
    crop_to_allowed_region: bool = Form(False),
    auto_clean_face: bool = Form(False),
    cleanup_metadata: str = Form(None),
):
    if not image.filename:
        raise HTTPException(400, "No image file provided")

    if category.lower() not in set(ALL_CATEGORIES):
        raise HTTPException(400, f"Invalid category '{category}'")

    if asset_id is None:
        asset_id = f"{category}_{_slugify(display_name)}"

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            content = await image.read()
            tmp.write(content)
            tmp_path = tmp.name

        anchors_dict = None
        if confirmed_anchors:
            try:
                anchors_dict = json.loads(confirmed_anchors)
                if not isinstance(anchors_dict, dict):
                    anchors_dict = None
            except json.JSONDecodeError:
                pass

        options = {
            "x_offset": x_offset,
            "y_offset": y_offset,
            "scale": scale,
            "remove_bg": remove_bg,
            "chromakey_color": chromakey_color,
            "chromakey_tolerance": chromakey_tolerance,
            "force_chromakey": force_chromakey,
            "crop_to_allowed_region": crop_to_allowed_region,
            "auto_clean_face": auto_clean_face,
            "asset_id": asset_id,
            "display_name": display_name,
            "fit_method": fit_method,
        }
        if anchors_dict:
            options["confirmed_anchors"] = anchors_dict
        if cleanup_metadata:
            try:
                cleanup_dict = json.loads(cleanup_metadata)
                if isinstance(cleanup_dict, dict):
                    options["cleanup"] = cleanup_dict
            except json.JSONDecodeError:
                pass

        metadata = compiler.compile_asset(tmp_path, category, options)

        pack_dir = os.path.join(OUTPUT_SUBDIR, category, asset_id)
        preview_relative = os.path.join(pack_dir, "preview.png")
        metadata_relative = os.path.join(pack_dir, "metadata.json")
        manifest_relative = os.path.join("public", "assets", "wardrobe_manifest.json")

        preview_stages = {
            "raw": os.path.join(pack_dir, "preview_raw.png"),
            "cleaned": os.path.join(pack_dir, "preview_cleaned.png"),
            "fitted": os.path.join(pack_dir, "preview_fitted.png"),
            "final": preview_relative,
        }

        return {
            "success": True,
            "asset_id": asset_id,
            "display_name": display_name,
            "category": category,
            "layers": metadata.get("layers", []),
            "preview_path": preview_relative,
            "preview_stages": preview_stages,
            "metadata_path": metadata_relative,
            "manifest_path": manifest_relative,
            "fit_report": metadata.get("fit", {}).get("report", {}),
            "fit_applied": metadata.get("fit", {}).get("applied", False),
            "validation_report": metadata.get("validation_report", {}),
            "source_metadata": metadata.get("source_metadata", {}),
        }

    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Compilation failed: {e}")
    finally:
        if "tmp_path" in locals():
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


@app.post("/api/rig-autodetect")
async def rig_autodetect(
    image: UploadFile = File(...),
    pose: str = Form("front_standing_v1"),
    body_archetype: str = Form("autodetected_v1"),
):
    if not image.filename:
        raise HTTPException(400, "No image file provided")
    try:
        content = await image.read()
        img = _PILImage.open(_io.BytesIO(content))
        anchors = detect_anchors(img)
        rig = build_rig(
            anchors,
            canvas=(img.width, img.height),
            pose=pose,
            body_archetype=body_archetype,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Autodetect failed: {e}")
    return JSONResponse(
        rig,
        headers={"Content-Disposition": 'attachment; filename="rig_auto.json"'},
    )


@app.post("/api/reference-pack")
async def reference_pack(
    image: UploadFile = File(...),
    body: Optional[UploadFile] = File(None),
):
    """Build the ControlNet/AI conditioning pack.

    Form fields:
      image: silhouette PNG (binary mask, filter-safe). Required.
      body:  optional body composite (face + clothing, no anatomy) used as
             input for MediaPipe pose + ONNX depth. Without it, pose falls
             back to rig.json anchors and depth falls back to a distance-
             transform proxy.
    """
    if not image.filename:
        raise HTTPException(400, "No silhouette image provided")
    try:
        sil = _PILImage.open(_io.BytesIO(await image.read()))
        body_img = _PILImage.open(_io.BytesIO(await body.read())) if (body and body.filename) else None
        anchors = None
        rig_path = os.path.join(BASE_RIG_DIR, "rig.json")
        if os.path.exists(rig_path):
            try:
                with open(rig_path) as f:
                    anchors = _json.load(f).get("anchors")
            except Exception:
                anchors = None
        data = build_reference_pack(sil, anchors=anchors, body_composite=body_img)
    except Exception as e:
        raise HTTPException(500, f"Reference pack failed: {e}")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="reference_pack.zip"'},
    )


@app.post("/api/reference-channels")
async def reference_channels(
    image: UploadFile = File(...),
    body: Optional[UploadFile] = File(None),
):
    """Return the raw reference pack channels as base64 PNGs."""
    if not image.filename:
        raise HTTPException(400, "No silhouette image provided")
    try:
        sil = _PILImage.open(_io.BytesIO(await image.read()))
        body_img = _PILImage.open(_io.BytesIO(await body.read())) if (body and body.filename) else None
        anchors = None
        rig_path = os.path.join(BASE_RIG_DIR, "rig.json")
        if os.path.exists(rig_path):
            try:
                with open(rig_path) as f:
                    anchors = _json.load(f).get("anchors")
            except Exception:
                anchors = None
        channels = build_reference_channels(sil, anchors=anchors, body_composite=body_img)
    except Exception as e:
        raise HTTPException(500, f"Reference channels failed: {e}")

    out = {}
    for name, img in channels:
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        out[name] = _base64.b64encode(buf.getvalue()).decode("ascii")
    return JSONResponse(out)


@app.post("/api/ai-process")
async def ai_process_endpoint(
    image: UploadFile = File(...),
    mode: str = Form(...),  # "bg-remove" | "clothing-isolate"
):
    """Apply rembg-based background removal or clothing isolation.

    On first call per server process for each mode, rembg downloads the
    underlying ONNX model (~85 MB) to ~/.u2net/. Subsequent calls reuse
    the cached session.
    """
    if mode not in {"bg-remove", "clothing-isolate"}:
        raise HTTPException(400, f"invalid mode: {mode!r}")
    if not image.filename:
        raise HTTPException(400, "No image file provided")
    try:
        content = await image.read()
        src = _PILImage.open(_io.BytesIO(content))
        result = ai_process(src, mode)
    except Exception as e:
        raise HTTPException(500, f"AI processing failed: {e}")
    buf = _io.BytesIO()
    result.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/coreml/status")
async def coreml_status_endpoint():
    """Report whether a local Core ML generation backend is configured."""
    return JSONResponse(coreml_status())


def _parse_controlnet_models(raw: str) -> List[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [part.strip() for part in raw.split(",") if part.strip()]


def _save_pil_png(img: _PILImage.Image, path: str):
    img.save(path, format="PNG")
    return Path(path)


@app.post("/api/coreml/generate")
async def coreml_generate_endpoint(
    prompt: str = Form(...),
    negative_prompt: str = Form(""),
    seed: int = Form(93),
    steps: int = Form(28),
    guidance_scale: float = Form(7.0),
    compute_unit: str = Form("CPU_AND_NE"),
    model_version: str = Form("runwayml/stable-diffusion-v1-5"),
    mode: str = Form("txt2img"),
    controlnet_models: str = Form(""),
    enable_openpose: str = Form("true"),
    enable_depth: str = Form("true"),
    image: Optional[UploadFile] = File(None),
    mask: Optional[UploadFile] = File(None),
    silhouette: Optional[UploadFile] = File(None),
    body: Optional[UploadFile] = File(None),
):
    """Run a configured local Core ML generation command.

    The default backend is Apple's ``python_coreml_stable_diffusion.pipeline``
    for txt2img/ControlNet. Inpaint is supported through
    PAPERDOLL_COREML_COMMAND_TEMPLATE so a Swift/CoreML runner can be swapped
    in without changing this API.
    """
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")
    if mode not in {"txt2img", "image2image", "inpaint"}:
        raise HTTPException(400, f"Unsupported Core ML mode: {mode!r}")

    try:
        with tempfile.TemporaryDirectory(prefix="paperdoll_coreml_") as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "inputs"
            output_dir = tmp_path / "outputs"
            input_dir.mkdir(parents=True, exist_ok=True)

            init_path = None
            mask_path = None
            body_img = None
            sil_img = None

            if image and image.filename:
                init_path = input_dir / "init_image.png"
                init_path.write_bytes(await image.read())

            if mask and mask.filename:
                mask_path = input_dir / "mask.png"
                mask_path.write_bytes(await mask.read())

            if body and body.filename:
                body_img = _PILImage.open(_io.BytesIO(await body.read())).convert("RGB")
                if init_path is None:
                    init_path = _save_pil_png(body_img, str(input_dir / "body_composite.png"))

            if silhouette and silhouette.filename:
                sil_img = _PILImage.open(_io.BytesIO(await silhouette.read())).convert("RGBA")
                if mask_path is None and mode == "inpaint":
                    mask_path = _save_pil_png(sil_img, str(input_dir / "inpaint_mask.png"))

            control_models = _parse_controlnet_models(controlnet_models)
            control_inputs: List[Path] = []
            inferred_control_models: List[str] = []
            if sil_img is not None and (
                enable_openpose.lower() == "true" or enable_depth.lower() == "true"
            ):
                anchors = None
                rig_path = os.path.join(BASE_RIG_DIR, "rig.json")
                if os.path.exists(rig_path):
                    try:
                        with open(rig_path) as f:
                            anchors = _json.load(f).get("anchors")
                    except Exception:
                        anchors = None

                channels = dict(build_reference_channels(sil_img, anchors=anchors, body_composite=body_img))
                if enable_openpose.lower() == "true" and "pose.png" in channels:
                    path = input_dir / "control_openpose.png"
                    channels["pose.png"].save(path, "PNG")
                    control_inputs.append(path)
                    inferred_control_models.append("lllyasviel/sd-controlnet-openpose")
                if enable_depth.lower() == "true" and "depth.png" in channels:
                    path = input_dir / "control_depth.png"
                    channels["depth.png"].save(path, "PNG")
                    control_inputs.append(path)
                    inferred_control_models.append("lllyasviel/sd-controlnet-depth")

            if not control_models:
                control_models = inferred_control_models

            req = CoreMLRequest(
                prompt=prompt,
                negative_prompt=negative_prompt.strip(),
                seed=seed,
                steps=steps,
                guidance_scale=guidance_scale,
                compute_unit=compute_unit,
                model_version=model_version,
                mode=mode,
                init_image=init_path,
                mask_image=mask_path,
                controlnet_models=control_models,
                controlnet_inputs=control_inputs,
            )
            result = run_generation(req, output_dir)
            generated_dir = Path("public") / "assets" / "coreml_generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            generated_name = f"coreml_{seed}_{uuid.uuid4().hex[:8]}.png"
            generated_path = generated_dir / generated_name
            generated_path.write_bytes(_base64.b64decode(result["image_b64"]))
            return JSONResponse({
                "success": True,
                "image_b64": result["image_b64"],
                "image_path": str(generated_path),
                "metadata": {
                    "prompt": prompt,
                    "negative_prompt": req.negative_prompt,
                    "seed": seed,
                    "steps": steps,
                    "guidance_scale": guidance_scale,
                    "compute_unit": compute_unit,
                    "model_version": model_version,
                    "mode": mode,
                    "controlnet_models": control_models,
                    "controlnet_inputs": [p.name for p in control_inputs],
                    "backend": coreml_status(),
                    "stdout_tail": result.get("stdout_tail", ""),
                    "stderr_tail": result.get("stderr_tail", ""),
                },
            })
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"Core ML generation failed: {e}")


@app.get("/api/layerdiffuse/status")
async def layerdiffuse_status_endpoint():
    """Report whether the local LayerDiffuse backend is configured."""
    return JSONResponse(layerdiffuse_status())


@app.post("/api/layerdiffuse/generate")
async def layerdiffuse_generate_endpoint(
    prompt: str = Form(...),
    negative_prompt: str = Form(""),
    mode: str = Form("bg2fg"),
    speed_preset: str = Form("normal"),
    seed: int = Form(93),
    steps: int = Form(24),
    guidance_scale: float = Form(7.0),
    width: int = Form(512),
    height: int = Form(512),
    model: str = Form(""),
    device: str = Form("auto"),
    background: Optional[UploadFile] = File(None),
    mask: Optional[UploadFile] = File(None),
):
    """Generate a transparent PNG layer with LayerDiffuse."""
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")
    if mode not in {"fg_only", "bg2fg"}:
        raise HTTPException(400, f"Unsupported LayerDiffuse mode: {mode!r}")
    if speed_preset not in {"normal", "lcm"}:
        raise HTTPException(400, f"Unsupported LayerDiffuse speed preset: {speed_preset!r}")

    try:
        with tempfile.TemporaryDirectory(prefix="paperdoll_layerdiffuse_") as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "inputs"
            input_dir.mkdir(parents=True, exist_ok=True)
            bg_path = None
            mask_path = None

            if background and background.filename:
                bg_path = input_dir / "background.png"
                bg_path.write_bytes(await background.read())
            if mask and mask.filename:
                mask_path = input_dir / "mask.png"
                mask_path.write_bytes(await mask.read())

            if mode == "bg2fg" and bg_path is None:
                raise HTTPException(400, "background image is required for bg2fg")

            generated_dir = Path("public") / "assets" / "layerdiffuse_generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            generated_name = f"layerdiffuse_{seed}_{uuid.uuid4().hex[:8]}.png"
            generated_path = generated_dir / generated_name

            req = LayerDiffuseRequest(
                prompt=prompt,
                negative_prompt=negative_prompt.strip(),
                mode=mode,
                speed_preset=speed_preset,
                seed=seed,
                steps=steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                model=model.strip() or os.environ.get("PAPERDOLL_LAYERDIFFUSE_MODEL", "digiplay/Juggernaut_final"),
                device=device,
                background=bg_path,
                mask=mask_path,
            )
            effective_req = normalize_layerdiffuse_request(req)
            result = run_layerdiffuse_generation(effective_req, generated_path)
            return JSONResponse({
                "success": True,
                "image_b64": result["image_b64"],
                "image_path": result["image_path"],
                "metadata": {
                    "prompt": prompt,
                    "negative_prompt": effective_req.negative_prompt,
                    "mode": effective_req.mode,
                    "speed_preset": effective_req.speed_preset,
                    "seed": effective_req.seed,
                    "steps": effective_req.steps,
                    "guidance_scale": effective_req.guidance_scale,
                    "width": effective_req.width,
                    "height": effective_req.height,
                    "model": effective_req.model,
                    "device": effective_req.device,
                    "backend": layerdiffuse_status(),
                    "stdout_tail": result.get("stdout_tail", ""),
                    "stderr_tail": result.get("stderr_tail", ""),
                },
            })
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"LayerDiffuse generation failed: {e}")


@app.post("/api/cleanup-assist/lane-c")
async def cleanup_assist_lane_c(
    image: UploadFile = File(...),
    category: str = Form(""),
    style_strength: float = Form(0.35),
    current_mask: Optional[UploadFile] = File(None),
    use_bg_remove: bool = Form(False),
):
    """Return a local CV mask proposal for Lane C clothed guide cleanup.

    This endpoint is proposal-only. It does not generate artwork and does not
    expose the disabled AI clothing isolation mode.
    """
    if not image.filename:
        raise HTTPException(400, "No image file provided")
    try:
        src = _PILImage.open(_io.BytesIO(await image.read())).convert("RGBA")
        current = None
        if current_mask and current_mask.filename:
            current = _PILImage.open(_io.BytesIO(await current_mask.read())).convert("RGBA")

        bg_removed = None
        if use_bg_remove:
            try:
                bg_removed = ai_process(src, "bg-remove")
            except Exception:
                bg_removed = None

        result = propose_lane_c_mask(
            src,
            category=category,
            style_strength=style_strength,
            current_mask=current,
            bg_removed=bg_removed,
        )
    except Exception as e:
        raise HTTPException(500, f"Cleanup assist failed: {e}")

    proposal_buf = _io.BytesIO()
    alpha_buf = _io.BytesIO()
    result.proposal.save(proposal_buf, format="PNG")
    result.alpha.save(alpha_buf, format="PNG")
    return JSONResponse({
        "success": True,
        "proposal_png": _base64.b64encode(proposal_buf.getvalue()).decode("ascii"),
        "alpha_png": _base64.b64encode(alpha_buf.getvalue()).decode("ascii"),
        "stats": result.stats,
    })


@app.post("/api/stencil-pipeline")
async def stencil_pipeline_endpoint(
    garments: List[UploadFile] = File(...),
    stencil_masks: List[UploadFile] = File(None),
    label: str = Form("garment"),
    config_override: str = Form(None),
):
    """Run the deterministic garment post-processing pipeline.

    Accepts one or more compiled garment PNGs (RGBA, in depth order: first =
    deepest). Stencil masks are optional — when omitted the garment's own alpha
    is used as the mask boundary.

    Depth is auto-generated from the body silhouette using the same
    distance-transform proxy that the reference-pack generator uses. No depth
    upload is needed.

    Returns base64-encoded RGBA PNGs for each layer and the composite, plus
    the asset manifest entry.
    """
    if not garments:
        raise HTTPException(400, "At least one garment file required")

    cfg_overrides = {}
    if config_override:
        try:
            parsed = json.loads(config_override)
            if isinstance(parsed, dict):
                cfg_overrides = parsed
        except json.JSONDecodeError:
            pass

    try:
        garment_arrays = []
        for gf in garments:
            content = await gf.read()
            arr = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
            if arr is None:
                raise HTTPException(400, f"Cannot decode garment: {gf.filename}")
            garment_arrays.append(arr)

        mask_arrays = []
        if stencil_masks:
            for mf in stencil_masks:
                if not mf.filename:
                    continue
                content = await mf.read()
                arr = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
                if arr is not None:
                    mask_arrays.append(arr)

        # Auto-generate depth from the body silhouette using the existing
        # reference-pack make_depth function — same proxy already used for guides.
        depth_arr: Optional[np.ndarray] = None
        try:
            from compiler.reference_pack import make_depth as _make_depth
            sil_path = os.path.join(BASE_RIG_DIR, "masks", "body_silhouette.png")
            if os.path.exists(sil_path):
                sil_pil = _PILImage.open(sil_path).convert("RGB")
                depth_pil = _make_depth(sil_pil)
                buf = _io.BytesIO()
                depth_pil.save(buf, format="PNG")
                depth_arr = cv2.imdecode(
                    np.frombuffer(buf.getvalue(), np.uint8), cv2.IMREAD_GRAYSCALE
                )
        except Exception:
            depth_arr = None  # centroid-distance fallback is fine

        # Load rig anchors for semantic annotation
        rig_anchors = None
        try:
            rig_json_path = os.path.join(BASE_RIG_DIR, "rig.json")
            if os.path.exists(rig_json_path):
                import json as _json
                with open(rig_json_path) as _f:
                    rig_anchors = _json.load(_f).get("anchors")
        except Exception:
            pass

        with tempfile.TemporaryDirectory(prefix="stencil_pipeline_") as tmp_dir:
            manifest_path = os.path.join(
                "public", "assets", "fabric_pipeline", "asset_manifest.json"
            )
            cfg = {
                **_STENCIL_DEFAULTS,
                **cfg_overrides,
                "manifest_path": manifest_path,
                "save_intermediates": bool(cfg_overrides.get("save_intermediates", False)),
                "base_rig_dir": BASE_RIG_DIR,
                "rig_anchors": rig_anchors,
            }

            result = _run_stencil_pipeline(
                garments=garment_arrays,
                stencil_masks=mask_arrays or None,
                depth_map=depth_arr,
                label=label,
                config=cfg,
                out_dir=tmp_dir,
            )

            _, comp_buf = cv2.imencode(".png", result["composite_rgba"])
            composite_b64 = _base64.b64encode(comp_buf.tobytes()).decode("ascii")

            layer_images = []
            for layer in result["layers"]:
                _, lbuf = cv2.imencode(".png", layer["rgba"])
                layer_images.append({
                    "label": layer["label"],
                    "image_b64": _base64.b64encode(lbuf.tobytes()).decode("ascii"),
                    "bbox": layer["bbox"],
                    "contour_point_count": len(layer["contour_pts"]),
                    "semantic": layer.get("semantic", {}),
                })

        return {
            "success": True,
            "asset_id": result["asset_id"],
            "composite_b64": composite_b64,
            "layer_images": layer_images,
            "manifest_entry": result["manifest_entry"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Stencil pipeline failed: {e}")


@app.post("/api/construct-pattern")
async def construct_pattern_endpoint(
    recipe: str = Form(...),
    color: str = Form("#ffffff"),
    texture: Optional[UploadFile] = File(None),
    body_silhouette: Optional[UploadFile] = File(None),
    body_composite: Optional[UploadFile] = File(None),
    skin_composite: Optional[UploadFile] = File(None),
    expand_x: int = Form(0),
    expand_y: int = Form(0),
    dilate_px: int = Form(0),
    erode_px: int = Form(0),
    smooth_px: int = Form(2),
    flare_px: int = Form(0),
    taper_px: int = Form(0),
    edge_stroke: str = Form("true"),
    inner_shadow: str = Form("true"),
    highlight: str = Form("false"),
    semantic_json: str = Form(""),  # optional: pre-computed semantic_layer result
    anchors_json: str = Form(""),  # optional: explicit anchor points from PSD _anchor_* layers
):
    from compiler.pattern_constructor import construct_pattern, RECIPES
    if recipe not in RECIPES:
        raise HTTPException(400, f"Unknown recipe: {recipe!r}")

    texture_arr = None
    if texture and texture.filename:
        raw = await texture.read()
        arr = np.frombuffer(raw, np.uint8)
        texture_arr = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)

    body_silhouette_arr = None
    if body_silhouette and body_silhouette.filename:
        raw = await body_silhouette.read()
        arr = np.frombuffer(raw, np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if decoded is not None:
            # Convert to binary mask: any non-transparent pixel → 255
            if decoded.ndim == 3 and decoded.shape[2] == 4:
                body_silhouette_arr = np.where(decoded[:, :, 3] > 10, np.uint8(255), np.uint8(0))
            else:
                gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY) if decoded.ndim == 3 else decoded
                body_silhouette_arr = np.where(gray > 10, np.uint8(255), np.uint8(0))

    # Generate depth map from body silhouette for volumetric lighting
    depth_arr = None
    if body_silhouette_arr is not None:
        try:
            from compiler.reference_pack import make_depth as _make_depth
            sil_pil = _PILImage.fromarray(body_silhouette_arr, mode="L")
            sil_rgb = sil_pil.convert("RGB")
            depth_pil = _make_depth(sil_rgb)
            depth_arr = np.array(depth_pil.convert("L"), dtype=np.uint8)
        except Exception as e:
            print(f"depth_map: generation failed: {e}")

    if body_silhouette_arr is None:
        raise HTTPException(400, "No PSD loaded — load a character before using the Digital Tailor")

    # Derive anchors — priority: explicit markers from PSD > DWPose inference.
    derived_anchors = None
    if anchors_json.strip():
        try:
            parsed = json.loads(anchors_json)
            if isinstance(parsed, dict) and len(parsed) > 0:
                derived_anchors = {k: (int(v[0]), int(v[1])) for k, v in parsed.items()}
                print(f"derive_anchors: {len(derived_anchors)} from PSD _anchor_* layers")
        except Exception as e:
            print(f"derive_anchors: failed to parse anchors_json: {e}")
    if derived_anchors is None and body_silhouette_arr is not None and body_composite and body_composite.filename:
        try:
            from compiler.dwpose_estimator import estimate_pose
            raw = await body_composite.read()
            arr = np.frombuffer(raw, np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                composite_pil = _PILImage.fromarray(rgb, mode="RGB")
                kps = estimate_pose(composite_pil, body_silhouette_arr)
                if kps:
                    derived_anchors = kps
                    print(f"derive_anchors: DWPose returned {len(kps)} keypoints")
        except Exception as e:
            print(f"derive_anchors: DWPose failed, falling back to rig.json: {e}")

    # Extract cel-shading style schema from skin composite (naked skeleton layers).
    style_schema = None
    if skin_composite and skin_composite.filename:
        try:
            from compiler.style_schema import extract_style_schema
            raw = await skin_composite.read()
            arr = np.frombuffer(raw, np.uint8)
            decoded = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            if decoded is not None:
                style_schema = extract_style_schema(decoded)
                print(f"style_schema: extracted {len(style_schema)} keys")
        except Exception as e:
            print(f"style_schema: extraction failed: {e}")

    rig_anchors = None
    rig_path = os.path.join(BASE_RIG_DIR, "rig.json")
    if os.path.exists(rig_path):
        with open(rig_path) as f:
            rig_anchors = json.load(f).get("anchors")

    semantic = None
    if semantic_json:
        try:
            semantic = json.loads(semantic_json)
        except Exception:
            pass

    material = {"type": "texture" if texture_arr is not None else "solid",
                "color": color, "texture_arr": texture_arr}
    effects = {
        "edge_stroke": edge_stroke.lower() == "true",
        "inner_shadow": inner_shadow.lower() == "true",
        "highlight": highlight.lower() == "true",
    }
    transform = {
        "expand_x": expand_x, "expand_y": expand_y,
        "dilate_px": dilate_px, "erode_px": erode_px,
        "smooth_px": smooth_px, "flare_px": flare_px, "taper_px": taper_px,
    }

    try:
        result = construct_pattern(
            recipe, BASE_RIG_DIR,
            material=material, effects=effects, transform=transform,
            rig_anchors=rig_anchors, semantic=semantic,
            body_silhouette_arr=body_silhouette_arr,
            derived_anchors=derived_anchors,
            style_schema=style_schema,
            depth_arr=depth_arr,
        )
    except Exception as e:
        raise HTTPException(500, f"Pattern construction failed: {e}")

    ok, buf = cv2.imencode(".png", result["image_rgba"])
    if not ok:
        raise HTTPException(500, "PNG encode failed")
    image_b64 = _base64.b64encode(buf.tobytes()).decode()

    return JSONResponse({
        "success": True,
        "image_b64": image_b64,
        "pattern": {
            "type": "pattern",
            "recipe": result["recipe"],
            "category": result["category"],
            "operations": result["operations"],
            "material": {"type": material["type"], "color": color},
            "effects": effects,
            "contour_points": result["contour_points"],
            "bounding_box": result["bounding_box"],
            "area_px": result["area_px"],
            "coverage_pct": result["coverage_pct"],
            "warnings": result["warnings"],
        },
    })


@app.get("/api/guide-templates.zip")
async def guide_templates_zip():
    try:
        data = build_guides_zip(BASE_RIG_DIR)
    except Exception as e:
        raise HTTPException(500, f"Failed to render guide templates: {e}")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="paperdoll_guides.zip"'},
    )


@app.get("/{full_path:path}")
async def serve_static(full_path: str):
    """Serve static files for all non-API routes."""
    if not full_path:
        full_path = "index.html"
    if os.path.isdir(full_path):
        index = os.path.join(full_path, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        return JSONResponse({"error": "Directory listing not supported"}, status_code=404)
    if os.path.exists(full_path):
        content_type, _ = mimetypes.guess_type(full_path)
        return FileResponse(full_path, media_type=content_type or "application/octet-stream")
    return JSONResponse({"error": "Not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
