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
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from compiler.category_registry import ALL_CATEGORIES
from compiler.compiler import AssetCompiler
from compiler.guide_templates import build_guides_zip
from compiler.rig_autodetect import detect_anchors, build_rig
from compiler.reference_pack import build_reference_pack, build_reference_channels
from compiler.ai_segmenter import process as ai_process
from compiler.cleanup_assist import propose_lane_c_mask
from compiler.stencil_pipeline import run_pipeline as _run_stencil_pipeline, PIPELINE_CONFIG as _STENCIL_DEFAULTS
from compiler.inpaint_bridge import (
    InpaintRequest,
    inpaint_status,
    run_generation as run_inpaint_generation,
    ensure_worker,
    submit_to_worker,
    cancel_worker_job,
    _worker_base_url,
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




@app.get("/api/inpaint/status")
async def inpaint_status_endpoint():
    return JSONResponse(inpaint_status())


@app.post("/api/inpaint/generate")
async def inpaint_generate_endpoint(
    prompt: str = Form(...),
    negative_prompt: str = Form(""),
    seed: int = Form(93),
    steps: int = Form(20),
    guidance_scale: float = Form(7.0),
    strength: float = Form(1.0),
    width: int = Form(512),
    height: int = Form(512),
    fast: bool = Form(True),
    feather: int = Form(8),
    controlnet: bool = Form(False),
    controlnet_model: str = Form("lllyasviel/control_v11p_sd15_openpose"),
    controlnet_scale: float = Form(0.5),
    model_repo: str = Form(""),
    device: str = Form("auto"),
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
):
    """Submit an inpaint job to the warm worker. Returns {job_id} for SSE streaming."""
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")

    resolved_repo = model_repo.strip() or os.environ.get("PAPERDOLL_INPAINT_MODEL_REPO", "Sanster/anything-4.0-inpainting")

    try:
        with tempfile.TemporaryDirectory(prefix="paperdoll_inpaint_") as tmp:
            tmp_path = Path(tmp)
            image_path = tmp_path / "body_composite.png"
            mask_path = tmp_path / "garment_mask.png"
            image_path.write_bytes(await image.read())
            mask_path.write_bytes(await mask.read())

            req = InpaintRequest(
                prompt=prompt,
                negative_prompt=negative_prompt.strip(),
                seed=seed,
                steps=steps,
                guidance_scale=guidance_scale,
                strength=max(0.0, min(1.0, strength)),
                width=width,
                height=height,
                fast=fast,
                feather=feather,
                controlnet=controlnet,
                controlnet_model=controlnet_model,
                controlnet_scale=controlnet_scale,
                model_repo=resolved_repo,
                device=device,
                image=image_path,
                mask=mask_path,
            )

            # Start the worker if needed (blocks until healthy, up to 120 s).
            await ensure_worker(model_repo=resolved_repo, device=device)
            job_id = await submit_to_worker(req)
            return JSONResponse({"job_id": job_id})

    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"Inpaint submission failed: {e}")


@app.get("/api/inpaint/progress/{job_id}")
async def inpaint_progress_endpoint(job_id: str):
    """Proxy SSE progress stream from the warm worker to the browser."""
    import httpx

    async def forward():
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                async with c.stream("GET", f"{_worker_base_url()}/progress/{job_id}") as r:
                    async for chunk in r.aiter_bytes():
                        yield chunk
        except Exception as exc:
            import json
            yield f'data: {json.dumps({"type": "error", "message": str(exc)})}\n\n'

    return StreamingResponse(
        forward(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/inpaint/cancel/{job_id}")
async def inpaint_cancel_endpoint(job_id: str):
    """Signal the worker to cancel a running job."""
    await cancel_worker_job(job_id)
    return JSONResponse({"ok": True})


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
