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

_DEFAULT_CKPT = "24yearsold/l2d_sam_iter2"
_DEFAULT_WEIGHTS_NAME = "checkpoint-18000.pt"
_model_cache: dict = {}


def _load_model(ckpt: str, device: str):
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
