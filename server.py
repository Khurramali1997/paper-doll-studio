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
from pathlib import Path

import mimetypes

from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from compiler.category_registry import ALL_CATEGORIES
from compiler.compiler import AssetCompiler
from compiler.guide_templates import build_guides_zip
from compiler.rig_autodetect import detect_anchors, build_rig
from compiler.reference_pack import build_reference_pack
from compiler.ai_segmenter import process as ai_process
from compiler.cleanup_assist import propose_lane_c_mask

import io as _io
import json as _json
import base64 as _base64
from PIL import Image as _PILImage

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
