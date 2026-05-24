"""Rule-based Danbooru tag vocabulary mapping from garment geometry.

Primary path: pure geometric inference from DeepFashion2-style landmarks.
Always runs deterministically — no model needed.

Optional WD14 path: place `models/wd14_moat_tagger.onnx` manually to
enable ONNX-based tag prediction. No auto-download; reserved for future
integration. The geometric path is used in all current cases.
"""

from typing import Dict, List, Optional
import numpy as np

DANBOORU_GARMENT_TAGS: Dict[str, List[str]] = {
    "dress": ["dress", "gown"],
    "top": ["shirt", "top"],
    "topwear": ["shirt", "top"],
    "shirt": ["shirt"],
    "blouse": ["blouse"],
    "tshirt": ["t-shirt"],
    "tank": ["tank_top", "camisole"],
    "camisole": ["camisole"],
    "outerwear": ["jacket", "coat"],
    "jacket": ["jacket"],
    "coat": ["coat"],
    "vest": ["vest"],
    "hoodie": ["hoodie", "sweater"],
    "sweater": ["sweater"],
    "skirt": ["skirt"],
    "miniskirt": ["skirt", "miniskirt"],
    "pants": ["pants", "trousers"],
    "jeans": ["jeans"],
    "shorts": ["shorts"],
    "legwear": ["pantyhose", "stockings"],
    "shoe": ["shoes", "footwear"],
    "socks": ["socks"],
}

# (predicate(dy), tag) — dy = neckline.y - neck_anchor.y
# Positive dy means neckline is BELOW the neck anchor (lower cut).
_NECKLINE_RULES = [
    (lambda dy: dy > 50,  "off_shoulder"),
    (lambda dy: dy < -15, "turtleneck"),
    (lambda dy: dy > 20,  "v_neck"),
    (lambda dy: True,     "round_neck"),
]

# (predicate(delta, arm_len), tag) — delta = sleeve_end.y - shoulder.y
_SLEEVE_RULES = [
    (lambda d, arm: d <= 20,          "sleeveless"),
    (lambda d, arm: d <= arm * 0.20,  "cap_sleeve"),
    (lambda d, arm: d <= arm * 0.40,  "short"),
    (lambda d, arm: d <= arm * 0.70,  "elbow"),
    (lambda d, arm: True,             "long"),
]

# Reference arm length in rig px (shoulder→wrist ≈ half of shoulder→ankle)
_RIG_ARM_LENGTH = 240


def get_danbooru_hints(
    label: str,
    landmarks: Dict[str, Dict],
    mask_bin: Optional[np.ndarray] = None,
    rig_anchors: Optional[Dict] = None,
) -> Dict:
    lbl = label.lower().split("_")[0]
    category_tags = DANBOORU_GARMENT_TAGS.get(lbl, [lbl])

    # --- Neckline type ---
    neckline_type = "unknown"
    if "neckline" in landmarks:
        nl_y = landmarks["neckline"]["y"]
        neck_y = int(rig_anchors["neck"][1]) if rig_anchors and "neck" in rig_anchors else nl_y
        dy = nl_y - neck_y
        for pred, tag in _NECKLINE_RULES:
            if pred(dy):
                neckline_type = tag
                break

    # --- Sleeve length ---
    sleeve_length = "unknown"
    sleeve_lm = landmarks.get("left_sleeve_end") or landmarks.get("right_sleeve_end")
    shoulder_lm = landmarks.get("left_shoulder") or landmarks.get("right_shoulder")
    if sleeve_lm and shoulder_lm:
        delta = sleeve_lm["y"] - shoulder_lm["y"]
        arm_len = _RIG_ARM_LENGTH
        if rig_anchors:
            sh_y = shoulder_lm["y"]
            ankle = rig_anchors.get("ankle_left") or rig_anchors.get("ankle_right")
            if ankle:
                arm_len = max(100, int(ankle[1]) - int(sh_y)) // 2
        for pred, tag in _SLEEVE_RULES:
            if pred(delta, arm_len):
                sleeve_length = tag
                break
    elif not sleeve_lm and lbl in {"tank", "camisole", "vest"}:
        sleeve_length = "sleeveless"

    # --- Silhouette ---
    silhouette = "unknown"
    if mask_bin is not None:
        silhouette = _infer_silhouette(mask_bin, landmarks, rig_anchors)

    return {
        "category_tags": category_tags,
        "neckline_type": neckline_type,
        "sleeve_length": sleeve_length,
        "silhouette": silhouette,
    }


def _infer_silhouette(
    mask_bin: np.ndarray,
    landmarks: Dict,
    rig_anchors: Optional[Dict],
) -> str:
    rows, cols = np.where(mask_bin > 0)
    if len(rows) == 0:
        return "unknown"

    def _row_width(y: int) -> int:
        at = cols[rows == y]
        return int(at.max() - at.min()) if len(at) > 1 else 0

    # Determine waist row
    waist_y = None
    if "waistline_left" in landmarks and "waistline_right" in landmarks:
        waist_y = (landmarks["waistline_left"]["y"] + landmarks["waistline_right"]["y"]) // 2
    elif rig_anchors and "waist_left" in rig_anchors:
        waist_y = int(rig_anchors["waist_left"][1])
    if waist_y is None:
        waist_y = int(rows.min() + (rows.max() - rows.min()) * 0.4)

    hem_y = landmarks.get("center_hem", {}).get("y", int(rows.max()))

    waist_w = _row_width(waist_y)
    hem_w = _row_width(hem_y)
    if waist_w == 0 or hem_w == 0:
        return "unknown"

    ratio = hem_w / waist_w
    if ratio > 1.25:
        return "a_line"
    if ratio < 0.85:
        return "pencil"
    return "straight"
