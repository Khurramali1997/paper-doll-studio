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

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from compiler.category_registry import ALL_CATEGORIES
from compiler.compiler import AssetCompiler

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
