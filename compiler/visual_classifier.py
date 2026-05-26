"""Garment slot classifier using WD tagger + bodytags_v3 tag→class map.

Predicts which wardrobe slot a garment image belongs to by:
1. Running WD tagger to get Danbooru tags with confidences
2. Scoring each garment class by summing tag confidences
3. Mapping the winning class to a wardrobe slot

Requires the [tagger] optional extra: pip install paperdoll-studio[tagger]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

_BODYTAGS_PATH = Path(__file__).parent / "bodytags_v3.json"

# Only these see-through classes matter for garment classification
_GARMENT_CLASSES = {"topwear", "bottomwear", "legwear", "footwear", "handwear", "headwear"}

# Map see-through class → app wardrobe slot
# bottomwear is ambiguous (pants/skirt/dress) — callers check is_ambiguous
_CLASS_TO_SLOT: dict[str, str] = {
    "topwear": "topwear",
    "bottomwear": "bottomwear",
    "legwear": "legwear",
    "footwear": "shoes",
    "handwear": "handwear",
    "headwear": "accessory",
}

# Cache: tag_string → garment_class (built once from bodytags_v3.json)
_tag_to_class: dict[str, str] | None = None


def _build_tag_index() -> dict[str, str]:
    data: dict[str, list[str]] = json.loads(_BODYTAGS_PATH.read_text())
    index: dict[str, str] = {}
    for cls, tags in data.items():
        if cls not in _GARMENT_CLASSES:
            continue
        for tag in tags:
            # normalise to space-separated (tagger returns underscored)
            index[tag] = cls
            index[tag.replace("_", " ")] = cls
    return index


def _tag_index() -> dict[str, str]:
    global _tag_to_class
    if _tag_to_class is None:
        _tag_to_class = _build_tag_index()
    return _tag_to_class


def classify_garment(
    pil_image: "PILImage",
    model_type: str = "swinv2",
    device: str = "cpu",
    gen_threshold: float = 0.35,
) -> dict:
    """Classify a garment image into a wardrobe slot.

    Returns:
        {
          "slot": str,          # wardrobe slot name ("topwear", "shoes", …)
          "raw_class": str,     # see-through class name
          "confidence": float,  # normalised [0–1] score
          "is_ambiguous": bool, # True when class maps to multiple possible slots
          "scores": dict,       # raw per-class scores for debugging
        }
    Raises ImportError if tagger deps aren't installed.
    """
    try:
        from compiler.wdv3_tagger import apply_wdv3_tagger
    except ImportError as exc:
        raise ImportError(
            "WD tagger dependencies not installed. "
            "Run: pip install timm pandas huggingface-hub"
        ) from exc

    _, _, _, _, general = apply_wdv3_tagger(
        pil_image,
        model_type=model_type,
        device=device,
        gen_threshold=gen_threshold,
        char_threshold=0.9,
    )

    index = _tag_index()
    scores: dict[str, float] = {}
    for tag, (conf, _idx) in general.items():
        cls = index.get(tag) or index.get(tag.replace("_", " "))
        if cls:
            scores[cls] = scores.get(cls, 0.0) + float(conf)

    if not scores:
        return {
            "slot": "topwear",
            "raw_class": "topwear",
            "confidence": 0.0,
            "is_ambiguous": False,
            "scores": scores,
        }

    best_class = max(scores, key=scores.__getitem__)
    total = sum(scores.values())
    confidence = scores[best_class] / total if total > 0 else 0.0

    return {
        "slot": _CLASS_TO_SLOT.get(best_class, "topwear"),
        "raw_class": best_class,
        "confidence": round(confidence, 3),
        "is_ambiguous": best_class == "bottomwear",
        "scores": {k: round(v, 3) for k, v in scores.items()},
    }
