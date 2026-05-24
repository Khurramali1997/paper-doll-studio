"""DeepFashion2-compatible garment landmark vocabulary and geometric extraction.

All landmarks are expressed in the paper doll's 768×768 canvas coordinate space.
No neural model — purely geometric, derived from mask contour extremes + rig anchors.
"""

from typing import Dict, List, Optional
import numpy as np

# DeepFashion2 category IDs (1-indexed, matching the original paper taxonomy)
DF2_CATEGORY_MAP: Dict[str, int] = {
    "tshirt": 1,        # short_sleeve_top
    "top": 2,           # long_sleeve_top
    "topwear": 2,
    "shirt": 2,
    "blouse": 2,
    "hoodie": 2,
    "sweater": 2,
    "tank": 6,          # sling
    "camisole": 6,
    "vest": 5,
    "outerwear": 4,     # long_sleeve_outwear
    "jacket": 4,
    "coat": 4,
    "shorts": 7,
    "pants": 8,         # trousers
    "trousers": 8,
    "jeans": 8,
    "legwear": 8,
    "skirt": 9,
    "dress": 11,        # long_sleeve_dress (conservative default)
    "gown": 11,
}

# Per-category ordered landmark names
CATEGORY_LANDMARKS: Dict[str, List[str]] = {
    "tops": [
        "neckline", "left_shoulder", "right_shoulder",
        "left_sleeve_end", "right_sleeve_end",
        "waistline_left", "waistline_right",
    ],
    "dress": [
        "neckline", "left_shoulder", "right_shoulder",
        "left_sleeve_end", "right_sleeve_end",
        "waistline_left", "waistline_right",
        "left_hem", "right_hem", "center_hem",
    ],
    "skirt": ["waistline_left", "waistline_right", "left_hem", "right_hem", "center_hem"],
    "pants": ["waistline_left", "waistline_right", "left_ankle_end", "right_ankle_end"],
}

_TOPS = {"top", "topwear", "shirt", "blouse", "tshirt", "tank", "camisole", "vest", "hoodie", "sweater", "outerwear", "jacket", "coat"}
_DRESS = {"dress", "gown"}
_SKIRT = {"skirt"}
_PANTS = {"pants", "trousers", "jeans", "shorts", "legwear"}


def _category_group(label: str) -> str:
    lbl = label.lower().split("_")[0]
    if lbl in _TOPS:
        return "tops"
    if lbl in _DRESS:
        return "dress"
    if lbl in _SKIRT:
        return "skirt"
    if lbl in _PANTS:
        return "pants"
    return "tops"


def _lm(x: int, y: int, confidence: float = 1.0, source: str = "contour") -> Dict:
    return {"x": x, "y": y, "confidence": confidence, "source": source}


def extract_landmarks(
    mask_bin: np.ndarray,
    label: str,
    rig_anchors: Optional[Dict] = None,
) -> Dict[str, Dict]:
    """Extract garment landmarks geometrically from the mask + rig anchors."""
    rows, cols = np.where(mask_bin > 0)
    if len(rows) == 0:
        return {}

    y_min, y_max = int(rows.min()), int(rows.max())
    height_range = max(y_max - y_min, 1)
    landmarks: Dict[str, Dict] = {}

    # neckline — topmost occupied row, centred
    top_cols = cols[rows == y_min]
    landmarks["neckline"] = _lm(int(top_cols.mean()), y_min)

    # center_hem — bottommost occupied row, centred
    bottom_cols = cols[rows == y_max]
    landmarks["center_hem"] = _lm(int(bottom_cols.mean()), y_max)

    # left_hem / right_hem — extremes in bottom 20% of height range
    bot_cutoff = y_max - max(1, int(height_range * 0.20))
    bot_mask = rows >= bot_cutoff
    if bot_mask.any():
        bc, br = cols[bot_mask], rows[bot_mask]
        li, ri = int(bc.argmin()), int(bc.argmax())
        landmarks["left_hem"] = _lm(int(bc[li]), int(br[li]))
        landmarks["right_hem"] = _lm(int(bc[ri]), int(br[ri]))

    # left_sleeve_end / right_sleeve_end — extremes in top 5-40% of height range
    sl_top = y_min + max(5, int(height_range * 0.05))
    sl_bot = y_min + int(height_range * 0.40)
    sl_mask = (rows >= sl_top) & (rows <= sl_bot)
    if sl_mask.any():
        sc, sr = cols[sl_mask], rows[sl_mask]
        li, ri = int(sc.argmin()), int(sc.argmax())
        landmarks["left_sleeve_end"] = _lm(int(sc[li]), int(sr[li]))
        landmarks["right_sleeve_end"] = _lm(int(sc[ri]), int(sr[ri]))

    # shoulder — rig anchors first, then contour approximation
    for side, anchor_key, sleeve_key in [
        ("left", "left_shoulder", "left_sleeve_end"),
        ("right", "right_shoulder", "right_sleeve_end"),
    ]:
        key = f"{side}_shoulder"
        if rig_anchors and anchor_key in rig_anchors:
            p = rig_anchors[anchor_key]
            landmarks[key] = _lm(int(p[0]), int(p[1]), 0.9, "rig_anchor")
        elif sleeve_key in landmarks:
            sl = landmarks[sleeve_key]
            landmarks[key] = _lm(sl["x"], int(y_min + height_range * 0.15), 0.5, "contour")

    # waistline — rig anchors only (geometry alone is not reliable)
    for anchor_key, lm_key in [("waist_left", "waistline_left"), ("waist_right", "waistline_right")]:
        if rig_anchors and anchor_key in rig_anchors:
            p = rig_anchors[anchor_key]
            landmarks[lm_key] = _lm(int(p[0]), int(p[1]), 0.9, "rig_anchor")

    # ankle ends for pants — bottommost points per half
    if _category_group(label) == "pants":
        mid_x = int(cols.mean())
        for side, half_mask in [("left", cols < mid_x), ("right", cols >= mid_x)]:
            if half_mask.any():
                hr = rows[half_mask]
                hc = cols[half_mask]
                landmarks[f"{side}_ankle_end"] = _lm(int(hc.mean()), int(hr.max()))

    # Restrict to landmarks relevant for this category
    group = _category_group(label)
    relevant = set(CATEGORY_LANDMARKS.get(group, CATEGORY_LANDMARKS["tops"]))
    return {k: v for k, v in landmarks.items() if k in relevant}
