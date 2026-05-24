"""AI-powered background removal + clothing isolation via rembg.

Two thin wrappers around `rembg`:

- :func:`remove_background` — keeps the dressed character, drops the
  background. Useful when the source image has a complex (non-flat)
  background that the chroma key can't handle.
- :func:`isolate_clothing` — keeps clothing only, drops body + background.
  This is what converts an AI-generated "dressed character" image into the
  garment-only PNG that paperdoll's wardrobe layer pipeline consumes.

rembg sessions are cached at module level so the underlying ONNX model
loads exactly once per server process. Model files (~85 MB each) are
auto-downloaded by rembg to ``~/.u2net/`` on first call and reused
thereafter.
"""

import io
from typing import Dict, Optional

from PIL import Image

MODEL_BG_REMOVE = "u2net"
MODEL_CLOTHING_ISOLATE = "u2net_cloth_seg"

_sessions: Dict[str, object] = {}


def _session(model_name: str):
    """Return a cached rembg session for *model_name*, creating it lazily."""
    if model_name not in _sessions:
        from rembg import new_session
        _sessions[model_name] = new_session(model_name)
    return _sessions[model_name]


def _run(image: Image.Image, model_name: str) -> Image.Image:
    from rembg import remove
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    out = remove(buf.getvalue(), session=_session(model_name))
    return Image.open(io.BytesIO(out)).convert("RGBA")


def remove_background(image: Image.Image) -> Image.Image:
    """Strip background, keep dressed character (RGBA, transparent bg)."""
    return _run(image, MODEL_BG_REMOVE)


def isolate_clothing(image: Image.Image) -> Image.Image:
    """Keep clothing only; drop body and background (RGBA, transparent elsewhere)."""
    return _run(image, MODEL_CLOTHING_ISOLATE)


def process(image: Image.Image, mode: str) -> Image.Image:
    """Dispatch helper. ``mode`` is ``"bg-remove"`` or ``"clothing-isolate"``."""
    if mode == "bg-remove":
        return remove_background(image)
    if mode == "clothing-isolate":
        return isolate_clothing(image)
    raise ValueError(f"unknown mode: {mode!r}")


def cached_models() -> Optional[Dict[str, str]]:
    """Diagnostic: which models have been loaded into the session cache."""
    return {k: type(v).__name__ for k, v in _sessions.items()}
