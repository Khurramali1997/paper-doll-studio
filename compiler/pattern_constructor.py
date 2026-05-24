"""Deterministic mask-to-garment constructor for paper-doll assets.

Builds garment patterns from rig anchor coordinates + semantic construction hints,
not from raw mask fragments. Pipeline:
  1. Load rig anchors + garment_anchors from base_rig/rig.json
  2. Derive semantic hints from garment_schema + danbooru_mapper (or reuse if supplied)
  3. Build explicit polygon envelope from anchor positions + hints
  4. Clip envelope to body_silhouette
  5. Subtract forbidden regions (face, hair, any detected faces/hands)
  6. Apply user transforms, material fill, effects

Public API
----------
construct_pattern(recipe_name, base_rig_dir, material, effects, transform, rig_anchors, semantic)
    Full pipeline. Returns dict with image_rgba, contour_points, bounding_box,
    area_px, coverage_pct, operations, warnings, recipe, category.

build_mask_from_recipe(recipe_name, base_rig_dir, transform_overrides, rig_anchors, semantic)
    Mask-only pipeline. Returns (mask_bin, operations_log).
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Recipe definitions
# ---------------------------------------------------------------------------

RECIPES: Dict[str, Dict] = {
    "bodice": {
        "category": "topwear",
        "subtract": ["face_forbidden_region"],
    },
    "tight_top": {
        "category": "topwear",
        "subtract": ["face_forbidden_region"],
        "erode_px": 2,
    },
    "tight_dress": {
        "category": "dress",
        "subtract": ["face_forbidden_region"],
        "erode_px": 4,
    },
    "leggings": {
        "category": "legwear",
        "subtract": ["face_forbidden_region"],
    },
    "stockings": {
        "category": "legwear",
        "subtract": ["face_forbidden_region"],
        "erode_px": 3,
    },
    "gloves": {
        "category": "handwear",
        "subtract": ["torso_region", "leg_region", "face_forbidden_region"],
    },
    "bodycon_dress": {
        "category": "dress",
        "subtract": ["face_forbidden_region"],
        "erode_px": 6,
    },
    "simple_flared_dress": {
        "category": "dress",
        "subtract": ["face_forbidden_region"],
        "flare_px": 60,
    },
}

# Per-recipe semantic construction hints — recipe intent overrides uncertain detection
RECIPE_HINTS: Dict[str, Dict] = {
    "bodice":              {"neckline_type": "round_neck",  "sleeve_length": "sleeveless", "silhouette": "straight"},
    "tight_top":           {"neckline_type": "round_neck",  "sleeve_length": "short",      "silhouette": "straight"},
    "tight_dress":         {"neckline_type": "round_neck",  "sleeve_length": "sleeveless", "silhouette": "pencil"},
    "leggings":            {"neckline_type": None,           "sleeve_length": None,          "silhouette": "straight"},
    "stockings":           {"neckline_type": None,           "sleeve_length": None,          "silhouette": "straight"},
    "gloves":              {"neckline_type": None,           "sleeve_length": None,          "silhouette": None},
    "bodycon_dress":       {"neckline_type": "round_neck",  "sleeve_length": "sleeveless", "silhouette": "pencil"},
    "simple_flared_dress": {"neckline_type": "round_neck",  "sleeve_length": "sleeveless", "silhouette": "a_line"},
}

MASK_ALIASES: Dict[str, str] = {
    "body_silhouette":        "body_silhouette.png",
    "topwear_allowed_region": "topwear_allowed_region.png",
    "top_allowed_region":     "top_allowed_region.png",
    "dress_allowed_region":   "dress_allowed_region.png",
    "dress_region":           "dress_region.png",
    "legwear_allowed_region": "legwear_allowed_region.png",
    "outerwear_allowed_region": "outerwear_allowed_region.png",
    "pants_allowed_region":   "pants_allowed_region.png",
    "skirt_allowed_region":   "skirt_allowed_region.png",
    "shoe_allowed_region":    "shoe_allowed_region.png",
    "face_forbidden_region":  "face_forbidden_region.png",
    "hair_forbidden_region":  "hair_forbidden_region.png",
    "torso_region":           "torso_region.png",
    "leg_region":             "leg_region.png",
    "shoe_region":            "shoe_region.png",
}

# ---------------------------------------------------------------------------
# Mask loading
# ---------------------------------------------------------------------------

def load_mask(name: str, base_rig_dir: str) -> np.ndarray:
    """Load a named mask from base_rig/masks/ and return as binary uint8 (0/255)."""
    filename = MASK_ALIASES.get(name, name if name.endswith(".png") else f"{name}.png")
    path = os.path.join(base_rig_dir, "masks", filename)
    if not os.path.exists(path):
        raise ValueError(f"Mask not found: {path!r}")
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Could not read mask: {path!r}")
    if img.ndim == 2:
        gray = img
    elif img.shape[2] == 4:
        gray = img[:, :, 3]
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
    return binary


# ---------------------------------------------------------------------------
# Boolean operations
# ---------------------------------------------------------------------------

def intersect_masks(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return cv2.bitwise_and(a, b)


def subtract_mask(base: np.ndarray, sub: np.ndarray) -> np.ndarray:
    return cv2.bitwise_and(base, cv2.bitwise_not(sub))


def union_masks(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return cv2.bitwise_or(a, b)


# ---------------------------------------------------------------------------
# Morphological operations
# ---------------------------------------------------------------------------

def dilate_mask(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    return cv2.dilate(mask, kernel, iterations=1)


def erode_mask(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    return cv2.erode(mask, kernel, iterations=1)


def smooth_mask(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.copy()
    sigma = max(px, 1)
    blurred = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma)
    _, result = cv2.threshold(blurred, 127, 255, cv2.THRESH_BINARY)
    return result.astype(np.uint8)


def expand_x(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.copy()
    kernel = np.ones((1, 2 * px + 1), np.uint8)
    return cv2.dilate(mask, kernel, iterations=1)


def expand_y(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.copy()
    kernel = np.ones((2 * px + 1, 1), np.uint8)
    return cv2.dilate(mask, kernel, iterations=1)


def flare_lower(
    mask: np.ndarray,
    flare_px: int,
    rig_anchors: Optional[Dict] = None,
) -> np.ndarray:
    """Progressively widen the mask below the waist, proportional to row depth."""
    if flare_px <= 0:
        return mask.copy()
    H, W = mask.shape
    active_rows = np.where(mask.any(axis=1))[0]
    if len(active_rows) == 0:
        return mask.copy()
    y_min, y_max = int(active_rows.min()), int(active_rows.max())

    if rig_anchors and "waist_left" in rig_anchors:
        waist_y = int(rig_anchors["waist_left"][1])
    else:
        waist_y = int(y_min + (y_max - y_min) * 0.40)

    result = mask.copy()
    span = max(y_max - waist_y, 1)
    for y in range(max(waist_y, 0), y_max + 1):
        if not mask[y].any():
            continue
        t = (y - waist_y) / span
        px = int(flare_px * t)
        if px > 0:
            k = np.ones((1, 2 * px + 1), np.uint8)
            row_expanded = cv2.dilate(mask[y:y + 1], k, iterations=1)
            result[y] = np.maximum(result[y], row_expanded.reshape(W))
    return np.clip(result, 0, 255).astype(np.uint8)


def taper_waist(
    mask: np.ndarray,
    taper_px: int,
    rig_anchors: Optional[Dict] = None,
) -> np.ndarray:
    """Horizontally erode a band around the waist row to pull the silhouette inward."""
    if taper_px <= 0:
        return mask.copy()
    H, W = mask.shape
    active_rows = np.where(mask.any(axis=1))[0]
    if len(active_rows) == 0:
        return mask.copy()
    y_min, y_max = int(active_rows.min()), int(active_rows.max())

    if rig_anchors and "waist_left" in rig_anchors:
        waist_y = int(rig_anchors["waist_left"][1])
    else:
        waist_y = int(y_min + (y_max - y_min) * 0.40)

    band = 40
    y_start = max(waist_y - band, 0)
    y_end = min(waist_y + band, H)

    result = mask.copy()
    for y in range(y_start, y_end):
        if not mask[y].any():
            continue
        t = 1.0 - abs(y - waist_y) / band
        local_px = max(1, int(taper_px * t))
        local_k = np.ones((1, 2 * local_px + 1), np.uint8)
        eroded_row = cv2.erode(mask[y:y + 1], local_k, iterations=1)
        result[y] = eroded_row[0]
    return result


def clip_to_canvas(mask: np.ndarray) -> np.ndarray:
    return np.clip(mask, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Contour / geometry
# ---------------------------------------------------------------------------

def extract_contour_points(mask: np.ndarray, epsilon: float = 2.0) -> List[List[int]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)
    simplified = cv2.approxPolyDP(largest, epsilon, closed=True)
    return simplified[:, 0, :].tolist()


def get_bounding_box(mask: np.ndarray) -> List[int]:
    x, y, w, h = cv2.boundingRect(mask)
    return [int(x), int(y), int(w), int(h)]


def coverage_stats(mask: np.ndarray) -> Dict:
    area = int(np.count_nonzero(mask))
    total = mask.shape[0] * mask.shape[1]
    return {"area_px": area, "coverage_pct": round(area / total, 4)}


# ---------------------------------------------------------------------------
# Color parsing
# ---------------------------------------------------------------------------

def _parse_hex(color_hex: str) -> Tuple[int, int, int]:
    h = color_hex.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------------------------
# Material fills
# ---------------------------------------------------------------------------

def fill_solid(mask: np.ndarray, color_hex: str) -> np.ndarray:
    r, g, b = _parse_hex(color_hex)
    H, W = mask.shape
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[:, :, 0] = b
    rgba[:, :, 1] = g
    rgba[:, :, 2] = r
    rgba[:, :, 3] = mask
    return rgba


def fill_texture(mask: np.ndarray, texture_arr: np.ndarray) -> np.ndarray:
    H, W = mask.shape
    th, tw = texture_arr.shape[:2]
    tiles_y = int(np.ceil(H / th))
    tiles_x = int(np.ceil(W / tw))
    tiled = np.tile(texture_arr, (tiles_y, tiles_x, 1))[:H, :W]
    if tiled.shape[2] == 3:
        tiled = cv2.cvtColor(tiled, cv2.COLOR_BGR2BGRA)
    result = tiled.copy()
    result[:, :, 3] = cv2.bitwise_and(result[:, :, 3], mask)
    return result


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------

def apply_edge_stroke(
    rgba: np.ndarray,
    mask: np.ndarray,
    thickness: int = 2,
    color_hex: str = "#1a1a1a",
) -> np.ndarray:
    r, g, b = _parse_hex(color_hex)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = rgba.copy()
    cv2.drawContours(result, contours, -1, (b, g, r, 255), thickness)
    return result


def apply_inner_shadow(
    rgba: np.ndarray,
    mask: np.ndarray,
    sigma: float = 8.0,
    opacity: float = 0.35,
) -> np.ndarray:
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5).astype(np.float32)
    shadow = np.clip(1.0 - dist / (sigma * 3.0), 0.0, 1.0) * opacity
    result = rgba.copy().astype(np.float32)
    mask_bool = mask > 0
    for c in range(3):
        result[:, :, c] = np.where(mask_bool, result[:, :, c] * (1.0 - shadow), result[:, :, c])
    return result.clip(0, 255).astype(np.uint8)


def apply_highlight(
    rgba: np.ndarray,
    mask: np.ndarray,
    intensity: float = 0.25,
) -> np.ndarray:
    H, W = mask.shape
    gradient = np.linspace(intensity, 0.0, H, dtype=np.float32)[:, np.newaxis]
    result = rgba.copy().astype(np.float32)
    mask_bool = mask > 0
    for c in range(3):
        result[:, :, c] = np.where(
            mask_bool,
            np.clip(result[:, :, c] + gradient * 255.0, 0, 255),
            result[:, :, c],
        )
    return result.clip(0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Rig loading
# ---------------------------------------------------------------------------

def _load_rig_anchors(base_rig_dir: str) -> Optional[Dict]:
    """Return just the anchors sub-dict from rig.json."""
    path = os.path.join(base_rig_dir, "rig.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f).get("anchors")
    except Exception:
        return None


def _load_full_rig(base_rig_dir: str) -> Dict:
    """Return the full rig.json dict (anchors + garment_anchors)."""
    path = os.path.join(base_rig_dir, "rig.json")
    if not os.path.exists(path):
        return {"anchors": {}, "garment_anchors": {}}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {"anchors": {}, "garment_anchors": {}}


def _pt(anchors: Dict, key: str, default: Tuple[int, int]) -> Tuple[int, int]:
    """Return anchor point as (x, y) int tuple, falling back to default."""
    if key in anchors:
        v = anchors[key]
        return (int(v[0]), int(v[1]))
    return default


# ---------------------------------------------------------------------------
# Semantic construction hints
# ---------------------------------------------------------------------------

def _get_semantic_hints(
    recipe_name: str,
    category: str,
    rough_mask: np.ndarray,
    rig_anchors: Optional[Dict],
    semantic: Optional[Dict] = None,
) -> Dict:
    """Merge recipe defaults with semantic layer construction hints.

    Recipe RECIPE_HINTS take priority — they encode explicit garment intent.
    Semantic detection only fills in hints that are left as None.
    """
    hints: Dict = dict(RECIPE_HINTS.get(recipe_name, {}))

    if semantic:
        db = semantic.get("danbooru", {})
        for key in ("neckline_type", "sleeve_length", "silhouette"):
            if hints.get(key) is None and db.get(key) not in (None, "unknown"):
                hints[key] = db[key]
        lm = semantic.get("deepfashion2", {}).get("landmarks", {})
        if lm:
            hints["_landmarks"] = lm
    else:
        try:
            from compiler.garment_schema import extract_landmarks
            from compiler.danbooru_mapper import get_danbooru_hints
            lm = extract_landmarks(rough_mask, category, rig_anchors=rig_anchors)
            db = get_danbooru_hints(category, lm, rough_mask, rig_anchors)
            for key in ("neckline_type", "sleeve_length", "silhouette"):
                if hints.get(key) is None and db.get(key) not in (None, "unknown"):
                    hints[key] = db[key]
            if lm:
                hints["_landmarks"] = lm
        except Exception:
            pass

    return hints


# ---------------------------------------------------------------------------
# Envelope construction
# ---------------------------------------------------------------------------

def _apply_neckline_cutout(
    mask: np.ndarray,
    neckline_type: Optional[str],
    neck_x: int,
    neck_y: int,
) -> np.ndarray:
    """Subtract a neckline-shaped region from the mask."""
    if not neckline_type or neckline_type == "turtleneck":
        return mask
    cutout = np.zeros_like(mask)
    if neckline_type == "v_neck":
        pts = np.array([
            [neck_x - 45, neck_y],
            [neck_x + 45, neck_y],
            [neck_x, neck_y + 65],
        ], dtype=np.int32)
        cv2.fillPoly(cutout, [pts], 255)
    elif neckline_type == "off_shoulder":
        cv2.rectangle(cutout,
                      (neck_x - 130, neck_y - 50), (neck_x + 130, neck_y + 15),
                      255, -1)
    else:  # round_neck (default for unknown)
        cv2.ellipse(cutout, (neck_x, neck_y + 12), (38, 32), 0, 0, 360, 255, -1)
    return subtract_mask(mask, cutout)


def _build_garment_envelope(
    recipe_name: str,
    category: str,
    ga: Dict,
    ra: Dict,
    hints: Dict,
    H: int = 768,
    W: int = 768,
) -> np.ndarray:
    """Fill a polygon envelope from rig anchor positions + semantic hints.

    The envelope covers the intended garment region generously; subsequent
    intersection with body_silhouette provides accurate body-aligned clipping.
    Contours, segmentation masks, and local mask fragments are NOT used here —
    rig anchor coordinates are the authoritative geometry.
    """
    mask = np.zeros((H, W), dtype=np.uint8)
    neckline_type = hints.get("neckline_type", "round_neck")
    sleeve_length  = hints.get("sleeve_length",  "sleeveless")
    silhouette     = hints.get("silhouette",      "straight")

    if category in ("topwear", "top"):
        neck_x, neck_y = _pt(ga, "neck",           (W // 2,        int(H * 0.235)))
        ls_x,   ls_y   = _pt(ga, "left_shoulder",  (int(W * 0.395), int(H * 0.326)))
        rs_x,   rs_y   = _pt(ga, "right_shoulder", (int(W * 0.615), int(H * 0.326)))
        wl_x,   wl_y   = _pt(ga, "waist_left",     (int(W * 0.414), int(H * 0.547)))
        wr_x,   wr_y   = _pt(ga, "waist_right",    (int(W * 0.581), int(H * 0.547)))

        arm_drop = arm_ext = 0
        if sleeve_length == "cap_sleeve":
            arm_drop, arm_ext = 30, 15
        elif sleeve_length == "short":
            arm_drop, arm_ext = 70, 25
        elif sleeve_length == "elbow":
            arm_drop = int((_pt(ra, "knee_left", (0, int(H * 0.703)))[1] - ls_y) * 0.4)
            arm_ext = 25
        elif sleeve_length == "long":
            arm_drop = int((_pt(ra, "ankle_left", (0, int(H * 0.859)))[1] - ls_y) * 0.45)
            arm_ext = 20

        pts: List = [
            [ls_x - 5,        ls_y],
            [neck_x - 28,     neck_y + 8],
            [neck_x,          neck_y],
            [neck_x + 28,     neck_y + 8],
            [rs_x + 5,        rs_y],
            [wr_x,            wr_y],
            [wl_x,            wl_y],
        ]
        if arm_drop > 0 or arm_ext > 0:
            pts.insert(0, [ls_x - arm_ext, ls_y + arm_drop])
            pts.insert(6, [rs_x + arm_ext, rs_y + arm_drop])

        cv2.fillPoly(mask, [np.array(pts, dtype=np.int32)], 255)
        mask = _apply_neckline_cutout(mask, neckline_type, neck_x, neck_y)

    elif category == "outerwear":
        neck_x, neck_y = _pt(ga, "neck",           (W // 2,        int(H * 0.235)))
        ls_x,   ls_y   = _pt(ga, "left_shoulder",  (int(W * 0.395), int(H * 0.326)))
        rs_x,   rs_y   = _pt(ga, "right_shoulder", (int(W * 0.615), int(H * 0.326)))
        hl_x,   hl_y   = _pt(ga, "hip_left",  _pt(ra, "hip_left",  (int(W * 0.390), int(H * 0.573))))
        hr_x,   hr_y   = _pt(ga, "hip_right", _pt(ra, "hip_right", (int(W * 0.609), int(H * 0.573))))

        pts = np.array([
            [ls_x - 20,   ls_y + 60],
            [ls_x - 5,    ls_y],
            [neck_x - 28, neck_y + 8],
            [neck_x,      neck_y],
            [neck_x + 28, neck_y + 8],
            [rs_x + 5,    rs_y],
            [rs_x + 20,   rs_y + 60],
            [hr_x,        hr_y],
            [hl_x,        hl_y],
        ], dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
        mask = _apply_neckline_cutout(mask, neckline_type, neck_x, neck_y)

    elif category == "dress":
        neck_x, neck_y = _pt(ga, "neck", (W // 2, int(H * 0.235)))
        # Dresses often use strap anchors instead of full shoulders
        sl_x, sl_y = _pt(ga, "strap_left",
                          _pt(ga, "left_shoulder",  (int(W * 0.449), int(H * 0.273))))
        sr_x, sr_y = _pt(ga, "strap_right",
                          _pt(ga, "right_shoulder", (int(W * 0.551), int(H * 0.273))))
        wl_x, wl_y = _pt(ga, "waist_left",  (int(W * 0.414), int(H * 0.547)))
        wr_x, wr_y = _pt(ga, "waist_right", (int(W * 0.581), int(H * 0.547)))
        hl_x, hl_y = _pt(ga, "hem_left",  (int(W * 0.365), int(H * 0.807)))
        hr_x, hr_y = _pt(ga, "hem_right", (int(W * 0.635), int(H * 0.807)))

        hem_extra = 0
        if silhouette == "a_line" or "flared" in recipe_name:
            hem_extra = 30
        elif silhouette == "pencil":
            # Narrow hem toward waist width
            hl_x = wl_x + 8
            hr_x = wr_x - 8

        pts = np.array([
            [sl_x - 8,          sl_y],
            [neck_x - 22,       neck_y + 6],
            [neck_x,            neck_y],
            [neck_x + 22,       neck_y + 6],
            [sr_x + 8,          sr_y],
            [wr_x,              wr_y],
            [hr_x + hem_extra,  hr_y],
            [hl_x - hem_extra,  hl_y],
            [wl_x,              wl_y],
        ], dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
        mask = _apply_neckline_cutout(mask, neckline_type, neck_x, neck_y)

    elif category in ("legwear", "pants"):
        wl_x, wl_y = _pt(ga, "waist_left",  (int(W * 0.414), int(H * 0.547)))
        wr_x, wr_y = _pt(ga, "waist_right", (int(W * 0.581), int(H * 0.547)))
        hl_x, hl_y = _pt(ga, "hip_left",  _pt(ra, "hip_left",  (int(W * 0.390), int(H * 0.573))))
        hr_x, hr_y = _pt(ga, "hip_right", _pt(ra, "hip_right", (int(W * 0.609), int(H * 0.573))))
        kl_x, kl_y = _pt(ga, "knee_left",  _pt(ra, "knee_left",  (int(W * 0.385), int(H * 0.703))))
        kr_x, kr_y = _pt(ga, "knee_right", _pt(ra, "knee_right", (int(W * 0.615), int(H * 0.703))))
        al_x, al_y = _pt(ra, "ankle_left",  (int(W * 0.390), int(H * 0.859)))
        ar_x, ar_y = _pt(ra, "ankle_right", (int(W * 0.609), int(H * 0.859)))

        cx = (wl_x + wr_x) // 2
        crotch_y = hl_y + 5

        left_pts = np.array([
            [wl_x,      wl_y],  [cx,         wl_y],
            [cx,         crotch_y], [hl_x,   hl_y],
            [kl_x,      kl_y],  [al_x,       al_y],
            [al_x + 22, al_y],  [kl_x + 22,  kl_y],
            [hl_x + 22, hl_y],  [cx,         crotch_y],
        ], dtype=np.int32)
        right_pts = np.array([
            [cx,         wl_y],   [wr_x,     wl_y],
            [hr_x - 22, hr_y],   [kr_x - 22, kr_y],
            [ar_x - 22, ar_y],   [ar_x,      ar_y],
            [kr_x,      kr_y],   [hr_x,      hr_y],
            [cx,         crotch_y],
        ], dtype=np.int32)
        cv2.fillPoly(mask, [left_pts],  255)
        cv2.fillPoly(mask, [right_pts], 255)

    elif category == "handwear":
        ls_x, ls_y = _pt(ra, "left_shoulder",  (int(W * 0.395), int(H * 0.326)))
        rs_x, rs_y = _pt(ra, "right_shoulder", (int(W * 0.615), int(H * 0.326)))
        al_x, al_y = _pt(ra, "ankle_left",  (int(W * 0.390), int(H * 0.859)))
        ar_x, ar_y = _pt(ra, "ankle_right", (int(W * 0.609), int(H * 0.859)))

        arm_w = 28
        left_pts = np.array([
            [ls_x - arm_w,    ls_y], [ls_x + arm_w // 2, ls_y],
            [al_x + arm_w // 2, al_y], [al_x - arm_w, al_y],
        ], dtype=np.int32)
        right_pts = np.array([
            [rs_x - arm_w // 2, rs_y], [rs_x + arm_w,    rs_y],
            [ar_x + arm_w,      ar_y], [ar_x - arm_w // 2, ar_y],
        ], dtype=np.int32)
        cv2.fillPoly(mask, [left_pts],  255)
        cv2.fillPoly(mask, [right_pts], 255)

    return mask


def _forbidden_from_detections(semantic: Dict, H: int, W: int) -> np.ndarray:
    """Build forbidden mask from anime_detector bounding boxes in a semantic result."""
    mask = np.zeros((H, W), dtype=np.uint8)
    for region_type in ("faces", "hands"):
        for det in semantic.get("forbidden_regions", {}).get(region_type, []):
            bbox = det.get("bbox", [])
            if len(bbox) == 4:
                x, y, w, h = (int(v) for v in bbox)
                cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
    return mask


def _body_slice_envelope(
    body_sil: np.ndarray,
    top_y: int,
    bottom_y: int,
    H: int,
    W: int,
) -> np.ndarray:
    """Clip body_silhouette to the horizontal band [top_y, bottom_y].

    The body silhouette is the authoritative pixel-level character shape.
    The anchor Y positions tell us which part of that shape belongs to each
    garment zone. The result follows the real body contour — not an abstract
    coordinate polygon.
    """
    band = np.zeros((H, W), dtype=np.uint8)
    band[max(0, top_y):min(H, bottom_y)] = 255
    return intersect_masks(body_sil, band)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# Map recipe category to garment_anchors key in rig.json
_GA_CATEGORY_KEY: Dict[str, str] = {
    "topwear":   "topwear",
    "top":       "top",
    "dress":     "dress",
    "legwear":   "legwear",
    "pants":     "pants",
    "outerwear": "outerwear",
    "handwear":  "topwear",  # fallback — arm area anchors come from ra directly
}

# Category mask used as authoritative garment geometry (the contour/envelope base).
# Rig anchor polygons are fallback only — when this mask is missing or empty.
_CATEGORY_MASK: Dict[str, str] = {
    "topwear":   "topwear_allowed_region",
    "top":       "top_allowed_region",
    "dress":     "dress_allowed_region",
    "legwear":   "legwear_allowed_region",
    "pants":     "pants_allowed_region",
    "outerwear": "outerwear_allowed_region",
    "handwear":  "body_silhouette",  # no dedicated mask; subtraction defines the arm area
}

# Keep legacy alias used in _get_semantic_hints
_ROUGH_MASK_FOR_CATEGORY = _CATEGORY_MASK


def build_mask_from_recipe(
    recipe_name: str,
    base_rig_dir: str,
    transform_overrides: Optional[Dict] = None,
    rig_anchors: Optional[Dict] = None,
    semantic: Optional[Dict] = None,
    body_silhouette_arr: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, List[str]]:
    """Build garment mask from body_silhouette contour + semantic modifications.

    Correct construction order:
      1. Load rig.json anchors (positional references only, not shape sources)
      2. Load body_silhouette — the authoritative pixel-accurate character shape
         Slice it vertically using anchor Y positions to isolate the garment zone.
         Fallback: anchor polygon when body_silhouette is missing.
      3. Derive semantic hints (recipe defaults override uncertain detection)
      4. Apply semantic modifications to the body-contour slice:
           neckline cutout — anchor gives WHERE, Danbooru gives WHAT TYPE
      5. Subtract forbidden regions (face, recipe-specific)
      6. Apply user transforms (erode/dilate/expand/smooth/flare/taper)

    The body_silhouette drives shape. Anchors are Y-range and cutout-position
    references. Semantic hints say what kind of neckline/hem to carve out.
    """
    if recipe_name not in RECIPES:
        raise ValueError(f"Unknown recipe: {recipe_name!r}. Available: {list(RECIPES)}")

    recipe   = RECIPES[recipe_name]
    category = recipe["category"]
    ops: List[str] = []
    overrides = transform_overrides or {}

    # 1. Load rig data — anchors are positional references, not geometry sources
    rig_data = _load_full_rig(base_rig_dir)
    ra = rig_data.get("anchors", {})
    if rig_anchors is not None:
        ra = rig_anchors
    ga_all = rig_data.get("garment_anchors", {})
    ga_key  = _GA_CATEGORY_KEY.get(category, category)
    ga      = ga_all.get(ga_key, {})
    H = W = 768
    ops.append(f"rig:anchors={len(ra)} garment_anchors={len(ga)}")

    # 2. Body silhouette IS the authoritative character contour.
    #    Caller may supply a live-generated array (from the uploaded PSD);
    #    fall back to the static file on disk only when none is provided.
    try:
        if body_silhouette_arr is not None:
            body_sil = body_silhouette_arr
            ops.append("body_sil:from_upload")
        else:
            body_sil = load_mask("body_silhouette", base_rig_dir)

        if category in ("topwear", "top"):
            top_y    = _pt(ga, "neck", (W // 2, int(H * 0.235)))[1]
            bottom_y = _pt(ga, "waist_left", (int(W * 0.414), int(H * 0.547)))[1] + 15

        elif category == "outerwear":
            top_y    = _pt(ga, "neck", (W // 2, int(H * 0.235)))[1]
            bottom_y = _pt(ga, "hip_left",
                           _pt(ra, "hip_left", (int(W * 0.390), int(H * 0.573))))[1] + 20

        elif category == "dress":
            neck_y   = _pt(ga, "neck", (W // 2, int(H * 0.235)))[1]
            strap_y  = _pt(ga, "strap_left", (int(W * 0.449), int(H * 0.273)))[1]
            top_y    = min(neck_y, strap_y)
            bottom_y = _pt(ga, "hem_left", (int(W * 0.365), int(H * 0.807)))[1] + 20

        elif category in ("legwear", "pants"):
            top_y    = _pt(ga, "waist_left", (int(W * 0.414), int(H * 0.547)))[1] - 10
            bottom_y = _pt(ra, "ankle_left", (int(W * 0.390), int(H * 0.859)))[1] + 20

        elif category == "handwear":
            # Full body slice — recipe subtractions (torso, leg, face) carve out arm area
            top_y, bottom_y = 0, H

        else:
            top_y, bottom_y = 0, H

        mask = _body_slice_envelope(body_sil, top_y, bottom_y, H, W)
        ops.append(f"body_slice:{category}(y={top_y}-{bottom_y},nonempty={mask.any()})")

    except ValueError:
        # Fallback: no body_silhouette on disk → build from rig anchor polygon
        hints_fb = dict(RECIPE_HINTS.get(recipe_name, {}))
        body_sil = np.zeros((H, W), dtype=np.uint8)
        ga_key2 = _GA_CATEGORY_KEY.get(category, category)
        ga_fb   = ga_all.get(ga_key2, {})
        mask = _build_garment_envelope(recipe_name, category, ga_fb, ra, hints_fb, H, W)
        ops.append(f"body_slice:anchor_fallback({category},nonempty={mask.any()})")

    # 3. Semantic hints (recipe RECIPE_HINTS take priority; detection fills None slots)
    hints = _get_semantic_hints(recipe_name, category, mask, ra, semantic=semantic)
    ops.append(
        f"hints:neckline={hints.get('neckline_type')} "
        f"sleeve={hints.get('sleeve_length')} "
        f"silhouette={hints.get('silhouette')}"
    )

    # 4. Apply semantic modifications to the body-contour slice.
    #    Neckline cutout: Danbooru says WHAT type, neck anchor says WHERE.
    neckline_type = hints.get("neckline_type")
    if neckline_type and category in ("topwear", "top", "dress", "outerwear"):
        neck_x, neck_y = _pt(ga, "neck", (W // 2, int(H * 0.235)))
        mask = _apply_neckline_cutout(mask, neckline_type, neck_x, neck_y)
        ops.append(f"neckline:{neckline_type}@({neck_x},{neck_y})")

    # 5. Subtract forbidden regions
    for sub_name in recipe.get("subtract", []):
        try:
            sub = load_mask(sub_name, base_rig_dir)
            mask = subtract_mask(mask, sub)
            ops.append(f"subtract:{sub_name}")
        except ValueError:
            ops.append(f"skip_subtract:{sub_name}(not found)")

    if semantic:
        det_mask = _forbidden_from_detections(semantic, H, W)
        if det_mask.any():
            mask = subtract_mask(mask, det_mask)
            ops.append("subtract:detected_forbidden_regions")

    # 6. Geometric transforms: erode → dilate → expand_x → expand_y → smooth → flare → taper
    def _px(key: str) -> int:
        return int(overrides.get(key, recipe.get(key, 0)))

    if _px("erode_px") > 0:
        mask = erode_mask(mask, _px("erode_px"))
        ops.append(f"erode:{_px('erode_px')}px")

    if _px("dilate_px") > 0:
        mask = dilate_mask(mask, _px("dilate_px"))
        ops.append(f"dilate:{_px('dilate_px')}px")

    if _px("expand_x") > 0:
        mask = expand_x(mask, _px("expand_x"))
        ops.append(f"expand_x:{_px('expand_x')}px")

    if _px("expand_y") > 0:
        mask = expand_y(mask, _px("expand_y"))
        ops.append(f"expand_y:{_px('expand_y')}px")

    if _px("smooth_px") > 0:
        mask = smooth_mask(mask, _px("smooth_px"))
        ops.append(f"smooth:{_px('smooth_px')}px")

    if _px("flare_px") > 0:
        mask = flare_lower(mask, _px("flare_px"), ra)
        ops.append(f"flare:{_px('flare_px')}px")

    if _px("taper_px") > 0:
        mask = taper_waist(mask, _px("taper_px"), ra)
        ops.append(f"taper:{_px('taper_px')}px")

    mask = clip_to_canvas(mask)
    return mask, ops


def construct_pattern(
    recipe_name: str,
    base_rig_dir: str,
    material: Dict,
    effects: Dict,
    transform: Dict,
    rig_anchors: Optional[Dict] = None,
    semantic: Optional[Dict] = None,
    body_silhouette_arr: Optional[np.ndarray] = None,
) -> Dict:
    """Full pipeline: recipe → rendered BGRA asset.

    Parameters
    ----------
    recipe_name  : one of RECIPES.keys()
    base_rig_dir : path to base_rig/
    material     : {"type": "solid"|"texture", "color": "#hex", "texture_arr": ndarray|None}
    effects      : {"edge_stroke": bool, "inner_shadow": bool, "highlight": bool}
    transform    : {"expand_x": int, "expand_y": int, "dilate_px": int, "erode_px": int,
                    "smooth_px": int, "flare_px": int, "taper_px": int}
    rig_anchors  : optional override for rig anchor positions
    semantic     : optional pre-computed semantic_layer.annotate() result to reuse

    Returns
    -------
    dict: image_rgba, contour_points, bounding_box, area_px, coverage_pct,
          operations, warnings, recipe, category
    """
    if rig_anchors is None:
        rig_anchors = _load_rig_anchors(base_rig_dir)

    if recipe_name not in RECIPES:
        raise ValueError(f"Unknown recipe: {recipe_name!r}. Available: {list(RECIPES)}")

    warnings: List[str] = []
    mask, ops = build_mask_from_recipe(
        recipe_name, base_rig_dir,
        transform_overrides=transform,
        rig_anchors=rig_anchors,
        semantic=semantic,
        body_silhouette_arr=body_silhouette_arr,
    )

    if not mask.any():
        warnings.append("Mask is empty after operations — check recipe and base_rig_dir.")

    mat_type    = material.get("type", "solid")
    color       = material.get("color", "#ffffff")
    texture_arr = material.get("texture_arr")

    if mat_type == "texture" and texture_arr is not None:
        rgba = fill_texture(mask, texture_arr)
        ops.append("fill:texture")
    else:
        rgba = fill_solid(mask, color)
        ops.append(f"fill:solid({color})")

    if effects.get("inner_shadow", False):
        rgba = apply_inner_shadow(rgba, mask)
        ops.append("effect:inner_shadow")

    if effects.get("highlight", False):
        rgba = apply_highlight(rgba, mask)
        ops.append("effect:highlight")

    if effects.get("edge_stroke", False):
        rgba = apply_edge_stroke(rgba, mask)
        ops.append("effect:edge_stroke")

    stats    = coverage_stats(mask)
    category = RECIPES[recipe_name]["category"]

    return {
        "image_rgba":     rgba,
        "contour_points": extract_contour_points(mask),
        "bounding_box":   get_bounding_box(mask),
        "area_px":        stats["area_px"],
        "coverage_pct":   stats["coverage_pct"],
        "operations":     ops,
        "warnings":       warnings,
        "recipe":         recipe_name,
        "category":       category,
    }
