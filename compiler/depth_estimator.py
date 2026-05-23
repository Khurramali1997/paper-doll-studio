"""Monocular depth estimation via ONNX (Depth Anything V2 Small).

Auto-downloads the ONNX model on first use to ``models/depth_anything_v2_vits.onnx``.
Subsequent calls reuse the cached file.

Input: any PIL Image (RGB or RGBA). Alpha-only silhouettes work but produce
flatter depth — for best results pass a body composite with skin/clothing
texture.

Output: a single-channel uint8 depth map at the input image's resolution,
where brighter pixels are interpreted as closer to the camera (this matches
ControlNet-Depth conventions).
"""

import os
import urllib.request
from typing import Optional

import numpy as np
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
DEPTH_MODEL_PATH = os.path.join(MODELS_DIR, "depth_anything_v2_vits.onnx")
DEPTH_MODEL_URL = (
    "https://huggingface.co/onnx-community/depth-anything-v2-small/"
    "resolve/main/onnx/model.onnx"
)
DEPTH_INPUT_SIZE = 518  # the size Depth Anything V2 was trained on


def ensure_model() -> str:
    """Download the depth model on first use; return its path."""
    if os.path.exists(DEPTH_MODEL_PATH):
        return DEPTH_MODEL_PATH
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"Downloading depth model → {DEPTH_MODEL_PATH} (one-time, ~50 MB)…")
    urllib.request.urlretrieve(DEPTH_MODEL_URL, DEPTH_MODEL_PATH)
    return DEPTH_MODEL_PATH


def _preprocess(image: Image.Image) -> np.ndarray:
    """Resize to model input, normalize to ImageNet stats, return NCHW float32."""
    rgb = image.convert("RGB").resize(
        (DEPTH_INPUT_SIZE, DEPTH_INPUT_SIZE), Image.Resampling.BICUBIC
    )
    arr = np.array(rgb, dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    arr = (arr - mean) / std
    arr = arr.transpose(2, 0, 1)[None, ...]  # → 1, 3, H, W
    return arr.astype(np.float32)


def estimate_depth(image: Image.Image) -> Optional[np.ndarray]:
    """Return a uint8 depth map at the input image's resolution, or None."""
    try:
        import onnxruntime as ort
    except ImportError:
        return None

    try:
        model_path = ensure_model()
    except Exception as e:
        print(f"depth: model download failed: {e}")
        return None

    try:
        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        input_name = session.get_inputs()[0].name
        inp = _preprocess(image)
        out = session.run(None, {input_name: inp})[0]
    except Exception as e:
        print(f"depth: inference failed: {e}")
        return None

    # Output shape is typically (1, H, W) or (1, 1, H, W). Squeeze to (H, W).
    depth = np.squeeze(out)
    if depth.ndim != 2:
        return None

    # Normalize to [0, 255]. Depth Anything outputs disparity-like values
    # (higher = closer), already in the convention ControlNet-Depth expects.
    d_min, d_max = float(depth.min()), float(depth.max())
    if d_max - d_min < 1e-6:
        depth_norm = np.zeros_like(depth, dtype=np.uint8)
    else:
        depth_norm = ((depth - d_min) / (d_max - d_min) * 255).astype(np.uint8)

    # Resize back to the original image dimensions.
    out_img = Image.fromarray(depth_norm, mode="L").resize(image.size, Image.Resampling.BICUBIC)
    return np.array(out_img, dtype=np.uint8)
