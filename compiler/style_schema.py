"""Style schema extraction and application for cel-shaded garments.

Extracts the character's cel-shading language from naked skeleton skin layers
and applies it to generated garments — zero models, all CV operations.

Flow
----
extract_style_schema(skin_layer_img) → schema dict
  Palette:      k-means k=4 on HSV → base, shadow1, shadow2, highlight
  Shadow geom:  luminance threshold → coverage %, side, edge softness
  Highlight:    bright-pixel threshold → ellipse fit → position, size
  Lineart:      Canny + distance transform → mean stroke width

apply_style_schema(mask, schema, target_color) → RGBA ndarray
  1. Remap target_color through palette_ratios → 4 tones
  2. Base fill → shadow multiply → highlight screen → contour stroke
"""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Palette extraction (k-means k=4 on HSV)
# ---------------------------------------------------------------------------

def _sample_skin_pixels(img: np.ndarray) -> np.ndarray:
    """Return HSV pixels from non-transparent / non-white regions."""
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3]
        mask = alpha > 10
        bgr = img[:, :, :3]
    elif img.ndim == 3 and img.shape[2] == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mask = gray > 5
        bgr = img
    else:
        raise ValueError(f"Unsupported image shape: {img.shape}")

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return hsv[mask]


def _extract_palette(hsv_pixels: np.ndarray) -> Dict:
    """K-means k=4 on HSV pixels → sorted by value (brightness)."""
    if len(hsv_pixels) < 10:
        return {
            "shadow1": {"sat_delta": 0.08, "val_ratio": 0.70},
            "shadow2": {"sat_delta": 0.12, "val_ratio": 0.50},
            "highlight": {"sat_delta": -0.15, "val_ratio": 1.15},
        }

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(
        hsv_pixels.astype(np.float32), 4, None, criteria, 10, cv2.KMEANS_PP_CENTERS
    )

    vals = centers[:, 2]  # (K, 3) → hue, sat, val
    order = np.argsort(vals)  # 0=darkest, 3=brightest

    def _ratio(idx: int, base_idx: int) -> Dict:
        """Compute sat_delta and val_ratio relative to base."""
        base_h, base_s, base_v = centers[base_idx]
        h, s, v = centers[idx]
        return {
            "sat_delta": float(s - base_s),
            "val_ratio": float(v / base_v) if base_v > 0 else 1.0,
        }

    base_idx = order[2]   # 2nd brightest = base color
    return {
        "shadow1":    _ratio(order[1], base_idx),
        "shadow2":    _ratio(order[0], base_idx),
        "highlight":  _ratio(order[3], base_idx),
    }


# ---------------------------------------------------------------------------
# Shadow band geometry
# ---------------------------------------------------------------------------

def _extract_shadow_geom(img: np.ndarray, base_val: float) -> Dict:
    """Measure shadow coverage, side, and edge softness from dark pixels."""
    if img.ndim == 3 and img.shape[2] == 4:
        bgr = img[:, :, :3]
    else:
        bgr = img[:, :, :3]

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    thresh = int(base_val * 0.60)

    _, shadow_mask = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY_INV)
    # Keep only non-zero pixels from original
    orig_mask = gray > 5
    shadow_mask = cv2.bitwise_and(shadow_mask, orig_mask.astype(np.uint8) * 255)

    total_px = int(orig_mask.sum())
    shadow_px = int(shadow_mask.astype(bool).sum())
    coverage = shadow_px / max(total_px, 1)

    # Determine which side shadows fall on (left or right of center)
    moments = cv2.moments(shadow_mask)
    if moments["m00"] > 0:
        cx = moments["m10"] / moments["m00"]
        side = "left" if cx < w / 2 else "right"
    else:
        side = "left"

    # Edge softness: blur shadow, measure transition width
    blurred = cv2.GaussianBlur(shadow_mask.astype(np.float32), (0, 0), 3)
    soft_edge = blurred > 127
    transition = cv2.bitwise_xor(
        soft_edge.astype(np.uint8) * 255,
        shadow_mask,
    )
    softness = (float(cv2.mean(transition)[0]) / 255.0 * 10) if transition.sum() > 0 else 2.0
    softness = max(0.5, min(softness, 8.0))

    return {
        "side": side,
        "coverage": round(coverage, 3),
        "softness": round(softness, 1),
    }


# ---------------------------------------------------------------------------
# Highlight shape
# ---------------------------------------------------------------------------

def _extract_highlight(img: np.ndarray, base_val: float) -> Dict:
    """Fit ellipse to bright pixels, measure position relative to centroid."""
    if img.ndim == 3 and img.shape[2] == 4:
        bgr = img[:, :, :3]
    else:
        bgr = img[:, :, :3]

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    thresh = int(base_val * 1.15)

    _, bright_mask = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
    orig_mask = gray > 5
    bright_mask = cv2.bitwise_and(bright_mask, orig_mask.astype(np.uint8) * 255)

    # Opacity: average brightness of highlight pixels
    bright_px = gray[bright_mask > 0]
    opacity = float(bright_px.mean() / 255.0) if len(bright_px) > 0 else 0.6

    # Contour centroid (body center)
    moments = cv2.moments(orig_mask.astype(np.uint8) * 255)
    if moments["m00"] > 0:
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
    else:
        cx, cy = gray.shape[1] / 2, gray.shape[0] / 2

    # Fit ellipse to highlight
    contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours and len(contours[0]) >= 5:
        ellipse = cv2.fitEllipse(contours[0])
        (ex, ey), (ma, Ma), _ = ellipse
        rel_pos = ((ex - cx) / max(gray.shape[1], 1),
                   (ey - cy) / max(gray.shape[0], 1))
        axes = [int(ma / 2), int(Ma / 2)]
    else:
        rel_pos = (0.0, -0.15)
        axes = [12, 6]

    return {
        "relative_pos": [round(rel_pos[0], 3), round(rel_pos[1], 3)],
        "axes": axes,
        "opacity": round(opacity, 2),
    }


# ---------------------------------------------------------------------------
# Lineart weight
# ---------------------------------------------------------------------------

def _extract_stroke_weight(img: np.ndarray) -> int:
    """Measure mean stroke width from Canny edges on the skin region."""
    if img.ndim == 3 and img.shape[2] == 4:
        mask = (img[:, :, 3] > 10).astype(np.uint8) * 255
        bgr = img[:, :, :3]
    else:
        gray_base = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mask = (gray_base > 5).astype(np.uint8) * 255
        bgr = img

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    edges = cv2.bitwise_and(edges, mask)

    if edges.sum() == 0:
        return 2

    dist = cv2.distanceTransform(255 - edges, cv2.DIST_L2, 3)
    stroke_px = dist[edges > 0]
    if len(stroke_px) == 0:
        return 2

    mean_dist = float(stroke_px.mean())
    return max(1, int(round(mean_dist * 2)))


# ---------------------------------------------------------------------------
# Schema extraction (public)
# ---------------------------------------------------------------------------

def extract_style_schema(skin_image: np.ndarray) -> Dict:
    """Extract cel-shading schema from a skin/wear layer image.

    Args:
        skin_image: BGRA or BGR ndarray of a skin layer (arm, torso, leg, etc.)

    Returns:
        Dict with keys: palette_ratios, shadow_side, shadow_coverage,
        shadow_softness, highlight_pos, highlight_axes, highlight_opacity,
        stroke_weight.
    """
    hsv_pixels = _sample_skin_pixels(skin_image)
    palette = _extract_palette(hsv_pixels)

    # Base value for thresholding
    if len(hsv_pixels) > 0:
        base_val = float(np.median(hsv_pixels[:, 2]))
    else:
        base_val = 180.0

    shadow = _extract_shadow_geom(skin_image, base_val)
    highlight = _extract_highlight(skin_image, base_val)
    stroke = _extract_stroke_weight(skin_image)

    return {
        "palette_ratios": palette,
        "shadow_side": shadow["side"],
        "shadow_coverage": shadow["coverage"],
        "shadow_softness": shadow["softness"],
        "highlight_pos": highlight["relative_pos"],
        "highlight_axes": highlight["axes"],
        "highlight_opacity": highlight["opacity"],
        "stroke_weight": stroke,
    }


# ---------------------------------------------------------------------------
# Schema application
# ---------------------------------------------------------------------------

def _remap_color(hex_color: str, palette: Dict) -> Dict[str, Tuple[int, ...]]:
    """Remap a target hex color through palette ratios → BGR tuples."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)

    # Convert to HSV
    rgb_arr = np.uint8([[[b, g, r]]])  # OpenCV: BGR
    hsv = cv2.cvtColor(rgb_arr, cv2.COLOR_BGR2HSV)[0, 0]
    base_h, base_s, base_v = int(hsv[0]), int(hsv[1]), int(hsv[2])

    def _tone(key: str) -> Tuple[int, ...]:
        ratios = palette[key]
        s = max(0, min(255, int(base_s + ratios["sat_delta"] * 255)))
        v = max(0, min(255, int(base_v * ratios["val_ratio"])))
        color = cv2.cvtColor(
            np.uint8([[[base_h, s, v]]]), cv2.COLOR_HSV2BGR
        )[0, 0]
        return (int(color[0]), int(color[1]), int(color[2]))

    return {
        "base":       (b, g, r),
        "shadow1":    _tone("shadow1"),
        "shadow2":    _tone("shadow2"),
        "highlight":  _tone("highlight"),
    }


def apply_style_schema(
    mask: np.ndarray,
    schema: Dict,
    target_color: str,
) -> np.ndarray:
    """Apply cel-shading schema to a garment mask.

    Args:
        mask:       uint8 binary mask (0/255), shape (H, W)
        schema:     style schema dict from extract_style_schema()
        target_color: hex color string e.g. "#ff0000"

    Returns:
        BGRA uint8 ndarray with shading applied.
    """
    H, W = mask.shape
    if not mask.any():
        return np.zeros((H, W, 4), dtype=np.uint8)

    palette = schema.get("palette_ratios", {})
    tones = _remap_color(target_color, palette)
    result = np.zeros((H, W, 4), dtype=np.uint8)

    # 1. Base fill
    b, g, r = tones["base"]
    result[mask > 0] = (b, g, r, 255)

    # 2. Shadow band
    shadow_side = schema.get("shadow_side", "left")
    shadow_cov = schema.get("shadow_coverage", 0.25)
    shadow_soft = schema.get("shadow_softness", 2.0)

    rows, cols = np.where(mask > 0)
    if len(rows) > 0:
        y_min, y_max = int(rows.min()), int(rows.max())
        x_min, x_max = int(cols.min()), int(cols.max())
        mid_x = (x_min + x_max) // 2

        shadow_mask = np.zeros((H, W), dtype=np.uint8)
        if shadow_side == "left":
            shadow_mask[:, :mid_x] = 255
        else:
            shadow_mask[:, mid_x:] = 255
        shadow_mask = cv2.bitwise_and(shadow_mask, mask)

        # Narrow shadow band by coverage
        band_mask = np.zeros((H, W), dtype=np.uint8)
        shadow_region = np.where(shadow_mask > 0)
        if len(shadow_region[0]) > 0:
            # Take only the fraction defined by coverage
            shadow_cols = shadow_region[1]
            if shadow_side == "left":
                boundary = int(mid_x * (1.0 - shadow_cov))
                band_mask[shadow_region[0], shadow_cols] = np.where(
                    shadow_cols >= boundary, np.uint8(255), np.uint8(0)
                )
            else:
                boundary = int(mid_x + (W - mid_x) * shadow_cov)
                band_mask[shadow_region[0], shadow_cols] = np.where(
                    shadow_cols <= boundary, np.uint8(255), np.uint8(0)
                )
            band_mask = cv2.bitwise_and(band_mask, mask)

        if shadow_soft > 0.5:
            blurred = cv2.GaussianBlur(
                band_mask.astype(np.float32), (0, 0), shadow_soft
            )
            band_mask = blurred

        sb, sg, sr = tones["shadow1"]
        for c in range(3):
            result[:, :, c] = np.where(
                band_mask > 0,
                (result[:, :, c].astype(np.float32) * [sb, sg, sr][c] / 255.0).astype(np.uint8),
                result[:, :, c],
            )

    # 3. Highlight ellipse
    hl_pos = schema.get("highlight_pos", [0.0, -0.15])
    hl_axes = schema.get("highlight_axes", [12, 6])
    hl_opacity = schema.get("highlight_opacity", 0.6)

    if len(rows) > 0:
        cy = (y_min + y_max) // 2
        cx = (x_min + x_max) // 2
        ex = int(cx + hl_pos[0] * (x_max - x_min))
        ey = int(cy + hl_pos[1] * (y_max - y_min))

        hl_mask = np.zeros((H, W), dtype=np.uint8)
        cv2.ellipse(hl_mask, (ex, ey), (hl_axes[0], hl_axes[1]), 0, 0, 360, 255, -1)
        hl_mask = cv2.bitwise_and(hl_mask, mask)

        if hl_mask.any():
            hb, hg, hr = tones["highlight"]
            for c in range(3):
                result[:, :, c] = np.where(
                    hl_mask > 0,
                    np.clip(
                        result[:, :, c].astype(np.float32)
                        + (np.array([hb, hg, hr])[c] - result[:, :, c].astype(np.float32))
                        * hl_opacity,
                        0, 255
                    ).astype(np.uint8),
                    result[:, :, c],
                )

    # 4. Contour stroke
    stroke_w = schema.get("stroke_weight", 2)
    if stroke_w > 0 and mask.any():
        contour_mask = np.zeros((H, W), dtype=np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(contour_mask, contours, -1, 255, stroke_w)
        contour_mask = cv2.bitwise_and(contour_mask, mask)

        if contour_mask.any():
            # Lineart color: near-black (sample from input edges if available)
            lineart_color = (20, 20, 20, 255)
            for c in range(3):
                result[:, :, c] = np.where(
                    contour_mask > 0,
                    lineart_color[c],
                    result[:, :, c],
                )

    result[:, :, 3] = mask
    return result
