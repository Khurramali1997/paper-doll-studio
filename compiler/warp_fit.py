"""Anchor-based garment warping to conform garments to rig body."""

import numpy as np
from PIL import Image
from compiler.category_registry import (
    UPPER_BODY_CATEGORIES,
    LOWER_BODY_CATEGORIES,
)


def estimate_affine_matrix(src_points, dst_points):
    """Estimate least-squares affine transform mapping dst->src.

    Returns (a, b, c, d, e, f) suitable for PIL Image.transform AFFINE.
    For each pixel (x_dst, y_dst) in destination:
        x_src = a * x_dst + b * y_dst + c
        y_src = d * x_dst + e * y_dst + f

    Args:
        src_points: list of [x, y] in source (garment) image
        dst_points: list of [x, y] in destination (rig) image
    """
    n = len(src_points)
    if n < 3:
        return None

    A = np.zeros((n * 2, 6))
    b = np.zeros(n * 2)
    for i, (s, d) in enumerate(zip(src_points, dst_points)):
        A[2 * i] = [d[0], d[1], 1, 0, 0, 0]
        A[2 * i + 1] = [0, 0, 0, d[0], d[1], 1]
        b[2 * i] = s[0]
        b[2 * i + 1] = s[1]

    params, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    return tuple(params.tolist())


def apply_affine_warp(image, matrix, target_size):
    """Apply affine warp to image using PIL transform.

    Args:
        image: PIL RGBA Image
        matrix: (a, b, c, d, e, f) for PIL Image.transform AFFINE
        target_size: (width, height) of output
    """
    if matrix is None:
        return image.resize(target_size, Image.Resampling.BILINEAR)

    a, b, c, d, e, f = matrix
    return image.transform(
        target_size,
        Image.Transform.AFFINE,
        (a, b, c, d, e, f),
        resample=Image.Resampling.BILINEAR,
    )


def fit_garment_affine(image, garment_anchors, rig_anchors, anchor_names):
    """Fit garment to rig using a single affine transform.

    Args:
        image: PIL RGBA Image of the garment
        garment_anchors: dict of {name: [x, y]} detected on garment
        rig_anchors: dict of {name: [x, y]} from rig
        anchor_names: list of anchor names to use for fitting

    Returns:
        PIL RGBA Image of the warped garment
    """
    src_pts = []
    dst_pts = []
    for name in anchor_names:
        if name in garment_anchors and name in rig_anchors:
            src_pts.append(garment_anchors[name])
            dst_pts.append(rig_anchors[name])

    if len(src_pts) < 3:
        return image

    matrix = estimate_affine_matrix(src_pts, dst_pts)
    target_size = image.size
    return apply_affine_warp(image, matrix, target_size)


def _find_split_y(category, garment_anchors, rig_anchors):
    """Determine vertical split point for piecewise warp."""
    waist_src = None
    waist_dst = None

    for name in ["waist_left", "waist_right", "hip_left"]:
        if name in garment_anchors:
            waist_src = garment_anchors[name][1]
        if name in rig_anchors:
            waist_dst = rig_anchors[name][1]

    if waist_src is None and waist_dst is None:
        return None, None

    if waist_src is None:
        waist_src = waist_dst
    if waist_dst is None:
        waist_dst = waist_src

    return waist_src, waist_dst


def fit_garment_piecewise(image, garment_anchors, rig_anchors, category, blend_radius=20):
    """Fit garment with separate upper/lower affine transforms.

    Splits the garment at the waist line. Upper anchors control neck/shoulder
    region. Lower anchors control hip/hem region. A smooth blend at the waist
    transition prevents seams.

    Returns:
        PIL RGBA Image of the piecewise-warped garment
    """
    # Piecewise candidates: categories that span both upper and lower body
    categories_piecewise_upper = UPPER_BODY_CATEGORIES | {"dress", "outerwear"}
    categories_piecewise_lower = LOWER_BODY_CATEGORIES | {"dress", "outerwear"}

    cat = category.lower()
    has_upper = cat in categories_piecewise_upper
    has_lower = cat in categories_piecewise_lower

    if not has_upper or not has_lower:
        anchor_names = []
        if cat in UPPER_BODY_CATEGORIES | {"dress"}:
            anchor_names = ["neck", "left_shoulder", "right_shoulder",
                            "waist_left", "waist_right", "hip_left", "hip_right"]
            if "hem_left" in garment_anchors and "hem_left" in rig_anchors:
                anchor_names += ["hem_left", "hem_right"]
        elif cat in LOWER_BODY_CATEGORIES:
            anchor_names = ["waist_left", "waist_right", "hip_left", "hip_right",
                            "hem_left", "hem_right"]
            if "knee_left" in garment_anchors and "knee_left" in rig_anchors:
                anchor_names += ["knee_left", "knee_right"]

        return fit_garment_affine(image, garment_anchors, rig_anchors, anchor_names)

    waist_src_y, waist_dst_y = _find_split_y(category, garment_anchors, rig_anchors)
    if waist_src_y is None or waist_dst_y is None:
        return fit_garment_affine(
            image, garment_anchors, rig_anchors,
            list(garment_anchors.keys())
        )

    # For dress/outerwear, the stable set includes strap and bust anchors.
    # Build upper list from what's available in garment_anchors.
    upper_candidates = ["neck", "strap_left", "strap_right",
                        "bust_left", "bust_right",
                        "left_shoulder", "right_shoulder",
                        "waist_left", "waist_right"]
    upper_anchors = [n for n in upper_candidates if n in garment_anchors and n in rig_anchors]

    lower_candidates = ["waist_left", "waist_right",
                        "hip_left", "hip_right",
                        "hem_left", "hem_right"]
    lower_anchors = [n for n in lower_candidates if n in garment_anchors and n in rig_anchors]
    if "knee_left" in garment_anchors and "knee_left" in rig_anchors:
        lower_anchors += ["knee_left", "knee_right"]
    if "ankle_left" in garment_anchors and "ankle_left" in rig_anchors:
        lower_anchors += ["ankle_left", "ankle_right"]

    upper_img = fit_garment_affine(image, garment_anchors, rig_anchors, upper_anchors)
    lower_img = fit_garment_affine(image, garment_anchors, rig_anchors, lower_anchors)

    w, h = image.size
    blend_start = max(0, waist_dst_y - blend_radius)
    blend_end = min(h, waist_dst_y + blend_radius)
    blend_range = blend_end - blend_start

    mask_arr = np.zeros((h, w), dtype=np.uint8)

    if blend_start > 0:
        mask_arr[:blend_start, :] = 255

    if blend_range > 0:
        for y in range(blend_start, blend_end):
            t = (y - blend_start) / blend_range
            t = max(0.0, min(1.0, t))
            val = int(255 * (1.0 - t))
            mask_arr[y, :] = val

    blend_mask = Image.fromarray(mask_arr, mode="L")
    result = Image.composite(upper_img, lower_img, blend_mask)
    return result
