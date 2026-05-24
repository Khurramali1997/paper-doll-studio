"""CV-assisted cleanup proposals for Lane C clothed-guide assets.

This module is intentionally non-generative: it proposes an editable alpha mask
from the provided source artwork using local image processing only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class CleanupAssistResult:
    proposal: Image.Image
    alpha: Image.Image
    stats: dict[str, Any]


def _clip_strength(style_strength: float | int | str | None) -> float:
    try:
        value = float(style_strength)
    except (TypeError, ValueError):
        value = 0.35
    return max(0.0, min(1.0, value))


def _alpha_mask(image: Image.Image | None, size: tuple[int, int]) -> np.ndarray | None:
    if image is None:
        return None
    rgba = image.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    return np.array(rgba, dtype=np.uint8)[:, :, 3] > 10


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    out = np.zeros(mask.shape, dtype=bool)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= min_area:
            out[labels == label] = True
    return out


def _fill_tiny_holes(mask: np.ndarray, max_area: int) -> np.ndarray:
    inv = ~mask
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        inv.astype(np.uint8), connectivity=8
    )
    out = mask.copy()
    h, w = mask.shape
    for label in range(1, count):
        x = stats[label, cv2.CC_STAT_LEFT]
        y = stats[label, cv2.CC_STAT_TOP]
        cw = stats[label, cv2.CC_STAT_WIDTH]
        ch = stats[label, cv2.CC_STAT_HEIGHT]
        touches_edge = x == 0 or y == 0 or x + cw >= w or y + ch >= h
        if not touches_edge and stats[label, cv2.CC_STAT_AREA] <= max_area:
            out[labels == label] = True
    return out


def propose_lane_c_mask(
    source: Image.Image,
    *,
    category: str = "",
    style_strength: float = 0.35,
    current_mask: Image.Image | None = None,
    bg_removed: Image.Image | None = None,
) -> CleanupAssistResult:
    """Return a stylized garment mask proposal for a clothed guide source.

    ``style_strength`` is conservative at 0.0 and aggressive at 1.0. Conservative
    settings preserve more colored pixels, dark outlines, and semi-transparent
    edges; aggressive settings remove more low-saturation/skin-like residue.
    """

    strength = _clip_strength(style_strength)
    rgba_img = source.convert("RGBA")
    rgba = np.array(rgba_img, dtype=np.uint8)
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    h, w = alpha.shape
    total = max(1, h * w)

    visible = alpha > 10
    if visible.mean() > 0.985:
        visible = np.ones((h, w), dtype=bool)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    lum = (
        0.2126 * rgb[:, :, 0].astype(np.float32)
        + 0.7152 * rgb[:, :, 1].astype(np.float32)
        + 0.0722 * rgb[:, :, 2].astype(np.float32)
    )

    max_rgb = rgb.max(axis=2)
    min_rgb = rgb.min(axis=2)
    neutral = (max_rgb - min_rgb) <= (16 + int(10 * strength))
    light_bg = (val >= (244 - int(24 * strength))) & neutral
    near_white = (rgb[:, :, 0] > 238) & (rgb[:, :, 1] > 238) & (rgb[:, :, 2] > 238)
    background = light_bg | near_white | (alpha <= 10)

    dark_line = visible & (lum < (72 + int(18 * (1.0 - strength)))) & (val < 150)
    saturated_color = visible & (sat > (34 + int(28 * strength))) & (val < 250)
    colored_ink = visible & (sat > 18) & ~background

    candidate = visible & ~background & (colored_ink | saturated_color | dark_line)

    # Remove common exposed-skin guide residue more strongly as the user moves
    # toward aggressive. Dark outlines are protected separately.
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    skin_like = (
        (r > 120)
        & (g > 70)
        & (b > 45)
        & (r > g + 8)
        & (g > b + 5)
        & ((r - b) > 22)
        & (hue < 26)
        & (sat < (118 + int(40 * strength)))
    )
    if strength >= 0.25:
        candidate &= ~(skin_like & ~dark_line)

    bg_mask = _alpha_mask(bg_removed, (w, h))
    if bg_mask is not None:
        candidate = candidate & (bg_mask | dark_line | saturated_color)

    kernel = np.ones((3, 3), dtype=np.uint8)
    if strength < 0.5:
        candidate = cv2.morphologyEx(candidate.astype(np.uint8), cv2.MORPH_CLOSE, kernel).astype(bool)
        candidate |= dark_line
    else:
        candidate = cv2.morphologyEx(candidate.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)
        candidate |= dark_line & cv2.dilate(candidate.astype(np.uint8), kernel, iterations=1).astype(bool)

    min_area = max(8, int(total * (0.00025 + 0.0015 * strength)))
    before_components = candidate.copy()
    candidate = _remove_small_components(candidate, min_area)
    if not candidate.any() and before_components.any():
        candidate = _remove_small_components(before_components, 1)

    candidate = _fill_tiny_holes(candidate, max(8, int(total * 0.0007)))

    source_visible_count = int(visible.sum())
    candidate_count = int(candidate.sum())
    if source_visible_count and candidate_count / source_visible_count < 0.015:
        # Keep Lane C proposals editable and non-destructive by avoiding a
        # nearly empty mask when the heuristic over-cleans.
        fallback = visible & ~background
        fallback |= dark_line | saturated_color
        fallback = _remove_small_components(fallback, max(4, min_area // 2))
        if fallback.sum() > candidate_count:
            candidate = fallback
            candidate_count = int(candidate.sum())

    out_alpha = np.where(candidate, alpha, 0).astype(np.uint8)
    if int(alpha.max()) == 255 and int(alpha.min()) == 255:
        out_alpha[candidate] = 255

    out_rgba = rgba.copy()
    out_rgba[:, :, 3] = out_alpha

    protected_count = int(dark_line.sum())
    kept_protected = int((dark_line & candidate).sum())
    edge_score = 1.0 if protected_count == 0 else kept_protected / protected_count

    current_diff_coverage = None
    current = _alpha_mask(current_mask, (w, h))
    if current is not None:
        diff = np.logical_xor(current, candidate)
        current_diff_coverage = float(diff.sum() / total)

    removed_count = max(0, source_visible_count - candidate_count)
    coverage = float(candidate_count / total)
    removed_coverage = 0.0 if source_visible_count == 0 else float(removed_count / source_visible_count)
    flags = {
        "empty": candidate_count < 128 or coverage < 0.002,
        "overclean": source_visible_count > 0 and candidate_count / source_visible_count < 0.08,
        "coverage_drop": removed_coverage > 0.82,
        "body_background_likely": coverage > 0.7 or (visible.mean() > 0.95 and removed_coverage < 0.08),
        "outline_damage": edge_score < 0.82,
    }
    if current_diff_coverage is not None:
        flags["proposal_diff"] = current_diff_coverage > 0.35

    stats: dict[str, Any] = {
        "backend": "cv",
        "category": category,
        "style_strength": strength,
        "source_visible_pixels": source_visible_count,
        "visible_pixels": candidate_count,
        "removed_pixels": removed_count,
        "coverage": coverage,
        "removed_coverage": removed_coverage,
        "edge_preservation_score": float(edge_score),
        "current_diff_coverage": current_diff_coverage,
        "warnings": flags,
    }
    return CleanupAssistResult(
        proposal=Image.fromarray(out_rgba, mode="RGBA"),
        alpha=Image.fromarray(out_alpha, mode="L"),
        stats=stats,
    )
