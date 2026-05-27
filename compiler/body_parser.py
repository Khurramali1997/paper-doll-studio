"""Dynamic body region mask extraction using SemanticSam.

Loads the fine-tuned SAM checkpoint (24yearsold/l2d_sam_iter2 on HF) and runs
inference on the naked body reference image, returning one binary mask per
body-part class. These masks replace the pre-baked *_allowed_region.png files
and work for any character pose/body type.

Requires the [sam] optional extra:  pip install paperdoll-studio[sam]
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

# 19 body-part classes SemanticSam was trained on (order == model output index)
BODY_PARTS = [
    "hair", "headwear", "face", "eyes", "eyewear",
    "ears", "earwear", "nose", "mouth", "neck",
    "neckwear", "topwear", "handwear", "bottomwear", "legwear",
    "footwear", "tail", "wings", "objects",
]

# Subset of BODY_PARTS that represent garment regions usable as wardrobe assets.
GARMENT_PARTS = (
    "headwear", "neckwear", "topwear", "handwear",
    "bottomwear", "legwear", "footwear",
)

_DEFAULT_CKPT = "24yearsold/l2d_sam_iter2"
_DEFAULT_WEIGHTS_NAME = "checkpoint-18000.pt"
_model_cache: dict = {}


def _resolve_device(device: str) -> str:
    """Map 'auto' to the best available torch device, leave concrete names alone."""
    if device != "auto":
        return device
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _load_model(ckpt: str, device: str):
    device = _resolve_device(device)
    cache_key = (ckpt, device)
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    try:
        import torch
        from compiler.see_through.semanticsam import SemanticSam
        from compiler.see_through.torch_utils_shim import init_model_from_pretrained
    except ImportError as exc:
        raise ImportError(
            "SAM dependencies not installed. "
            "Run: pip install torch accelerate huggingface-hub einops"
        ) from exc

    download_from_hf = not Path(ckpt).exists()
    model: SemanticSam = init_model_from_pretrained(
        pretrained_model_name_or_path=ckpt,
        module_cls=SemanticSam,
        download_from_hf=download_from_hf,
        model_args=dict(class_num=19),
        weights_name=_DEFAULT_WEIGHTS_NAME,
    )
    model.eval()
    if device != "cpu":
        model = model.to(device=device)

    _model_cache[cache_key] = model
    return model


def parse_body_regions(
    pil_image: "PILImage",
    ckpt: str = _DEFAULT_CKPT,
    device: str = "cpu",
    threshold: float = 0.0,
) -> dict[str, "PILImage"]:
    """Run SemanticSam on a naked body image and return per-class binary masks.

    Returns dict: body-part name → L-mode PIL.Image (255=present, 0=absent),
    same pixel dimensions as the input image.
    """
    try:
        import torch
        import numpy as np
    except ImportError as exc:
        raise ImportError("torch/numpy required for body parsing") from exc

    model = _load_model(ckpt, device)
    img_np = np.array(pil_image.convert("RGB"))

    with torch.inference_mode():
        preds = model.inference(img_np)[0]
        masks_np = (preds > threshold).to(device="cpu", dtype=torch.uint8).numpy()

    from PIL import Image as _PIL
    result: dict[str, _PIL.Image] = {}
    for idx, part_name in enumerate(BODY_PARTS):
        if idx >= masks_np.shape[0]:
            break
        result[part_name] = _PIL.fromarray(masks_np[idx] * 255, mode="L")

    return result


def _smooth_mask(mask_u8):
    """Close 1-px holes, drop speckle, soften the alpha cutline.

    Operates on a uint8 numpy array (0 or 255). Returns smoothed uint8 array.
    Uses cv2 which is already a hard dependency of the inpaint stack.
    """
    import cv2
    import numpy as np
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel, iterations=1)
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel, iterations=1)
    # Light blur softens the alpha cutline without making RGB look washed out.
    blurred = cv2.GaussianBlur(opened, (0, 0), sigmaX=1.5)
    return np.clip(blurred, 0, 255).astype(np.uint8)


def extract_all_classes(
    pil_image: "PILImage",
    ckpt: str = _DEFAULT_CKPT,
    device: str = "cpu",
    threshold: float = 0.0,
    smooth: bool = True,
    min_pixels: int = 50,
) -> dict[str, "PILImage"]:
    """Run SemanticSam and return RGBA cutouts for every detected class.

    Same SAM inference as extract_garments, but returns all 19 body-part
    classes (not just the garment subset). Used by the PNG-import bootstrap
    flow that turns a flat character image into a layered paper doll.
    """
    try:
        import torch
        import numpy as np
    except ImportError as exc:
        raise ImportError("torch/numpy required for class extraction") from exc

    model = _load_model(ckpt, device)
    rgb_np = np.array(pil_image.convert("RGB"))

    with torch.inference_mode():
        preds = model.inference(rgb_np)[0]
        masks_np = (preds > threshold).to(device="cpu", dtype=torch.uint8).numpy()

    from PIL import Image as _PIL
    result: dict[str, _PIL.Image] = {}
    for idx, part_name in enumerate(BODY_PARTS):
        if idx >= masks_np.shape[0]:
            break
        mask_u8 = (masks_np[idx] * 255).astype(np.uint8)
        if smooth:
            mask_u8 = _smooth_mask(mask_u8)
        if int((mask_u8 > 0).sum()) < min_pixels:
            continue
        rgba = np.dstack([rgb_np, mask_u8])
        result[part_name] = _PIL.fromarray(rgba, mode="RGBA")

    return result


def extract_garments(
    pil_image: "PILImage",
    ckpt: str = _DEFAULT_CKPT,
    device: str = "cpu",
    threshold: float = 0.0,
    smooth: bool = True,
    min_pixels: int = 200,
) -> dict[str, "PILImage"]:
    """Run SemanticSam on a clothed image and return RGBA garment cutouts.

    For each garment class present in the image, returns an RGBA PIL.Image at
    the same dimensions as the input: original pixels where the SAM mask is
    on, transparent elsewhere. Empty classes (and classes below ``min_pixels``,
    which are almost always SAM noise) are dropped from the result.
    """
    try:
        import torch
        import numpy as np
    except ImportError as exc:
        raise ImportError("torch/numpy required for garment extraction") from exc

    model = _load_model(ckpt, device)
    rgb_np = np.array(pil_image.convert("RGB"))

    with torch.inference_mode():
        preds = model.inference(rgb_np)[0]
        masks_np = (preds > threshold).to(device="cpu", dtype=torch.uint8).numpy()

    from PIL import Image as _PIL
    result: dict[str, _PIL.Image] = {}
    for part_name in GARMENT_PARTS:
        idx = BODY_PARTS.index(part_name)
        if idx >= masks_np.shape[0]:
            continue
        mask_u8 = (masks_np[idx] * 255).astype(np.uint8)
        if smooth:
            mask_u8 = _smooth_mask(mask_u8)
        if int((mask_u8 > 0).sum()) < min_pixels:
            continue
        rgba = np.dstack([rgb_np, mask_u8])
        result[part_name] = _PIL.fromarray(rgba, mode="RGBA")

    return result
