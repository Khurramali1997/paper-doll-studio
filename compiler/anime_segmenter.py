"""SkyTNT isnet-anime ONNX foreground segmenter.

Auto-downloads `isnet_anime.onnx` (~170 MB, HuggingFace skytnt/anime-seg)
on first call. Returns None gracefully on any error — missing onnxruntime,
download failure, or inference error.
"""

import os
import urllib.request
from typing import Optional

import numpy as np
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
MODEL_PATH = os.path.join(MODELS_DIR, "isnet-anime_1024.onnx")
MODEL_URL = "https://huggingface.co/skytnt/anime-seg/resolve/main/isnet-anime_1024.onnx"

_INPUT_SIZE = 1024
_session = None  # cached ONNX session


def ensure_model() -> Optional[str]:
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"Downloading isnet-anime model → {MODEL_PATH} (one-time, ~170 MB)…")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        return MODEL_PATH
    except Exception as e:
        print(f"anime_segmenter: download failed: {e}")
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        return None


def _get_session():
    global _session
    if _session is not None:
        return _session
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    path = ensure_model()
    if path is None:
        return None
    try:
        _session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        return _session
    except Exception as e:
        print(f"anime_segmenter: session load failed: {e}")
        return None


def segment_anime_foreground(image: Image.Image) -> Optional[np.ndarray]:
    """Return a uint8 binary mask (0/255) at the input resolution, or None."""
    session = _get_session()
    if session is None:
        return None

    orig_w, orig_h = image.size
    try:
        resized = image.convert("RGB").resize(
            (_INPUT_SIZE, _INPUT_SIZE), Image.Resampling.BICUBIC
        )
        arr = np.array(resized, dtype=np.float32) / 255.0
        arr = arr.transpose(2, 0, 1)[None, ...]  # NCHW float32

        input_name = session.get_inputs()[0].name
        output = session.run(None, {input_name: arr})[0]

        mask = np.squeeze(output)
        if mask.ndim == 3:
            mask = mask[0]

        binary = (mask > 0.5).astype(np.uint8) * 255
        result = Image.fromarray(binary, mode="L").resize(
            (orig_w, orig_h), Image.Resampling.NEAREST
        )
        return np.array(result, dtype=np.uint8)
    except Exception as e:
        print(f"anime_segmenter: inference failed: {e}")
        return None
