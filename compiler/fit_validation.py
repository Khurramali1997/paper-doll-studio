"""Silhouette conformity validation and fit metrics for warped garments."""

import os
import math
from PIL import Image, ImageChops


def extract_alpha(image):
    """Get binary alpha mask (255 for opaque, 0 for transparent)."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")
    return alpha.point(lambda p: 255 if p > 10 else 0)


def silhouette_intersection(mask_a, mask_b):
    """Count of pixels where both masks are non-transparent."""
    both = ImageChops.darker(mask_a, mask_b)
    return sum(1 for p in both.tobytes() if p > 10)


def silhouette_union(mask_a, mask_b):
    """Count of pixels where either mask is non-transparent."""
    s = ImageChops.screen(mask_a, mask_b)
    return sum(1 for p in s.tobytes() if p > 10)


def silhouette_iou(warped_alpha, body_alpha):
    """Intersection over Union between garment alpha and body silhouette.

    Returns float in [0, 1] where 1 = perfect overlap.
    """
    intersection = silhouette_intersection(warped_alpha, body_alpha)
    union = silhouette_union(warped_alpha, body_alpha)
    if union == 0:
        return 0.0
    return intersection / union


def silhouette_precision(warped_alpha, body_alpha):
    """Fraction of garment pixels that fall within the body silhouette."""
    intersection = silhouette_intersection(warped_alpha, body_alpha)
    garment_total = sum(1 for p in warped_alpha.tobytes() if p > 10)
    if garment_total == 0:
        return 0.0
    return intersection / garment_total


def silhouette_recall(warped_alpha, body_alpha):
    """Fraction of body silhouette covered by the garment."""
    intersection = silhouette_intersection(warped_alpha, body_alpha)
    body_total = sum(1 for p in body_alpha.tobytes() if p > 10)
    if body_total == 0:
        return 0.0
    return intersection / body_total


def compute_edge_map(alpha_mask):
    """Compute edge distance map using Manhattan approximation.

    For each pixel, returns approximate distance to nearest edge.
    Lower values = closer to garment boundary.
    """
    w, h = alpha_mask.size
    data = list(alpha_mask.tobytes())
    dist = [999999] * (w * h)
    nearest = [-1] * (w * h)

    for y in range(h):
        for x in range(w):
            idx = y * w + x
            if data[idx] > 10:
                dist[idx] = 0
                nearest[idx] = idx

    for y in range(h):
        for x in range(w):
            idx = y * w + x
            if dist[idx] > 0:
                d = dist[idx]
                n = nearest[idx]
                if x > 0 and dist[idx - 1] + 1 < d:
                    d = dist[idx - 1] + 1
                    n = nearest[idx - 1]
                if y > 0 and dist[idx - w] + 1 < d:
                    d = dist[idx - w] + 1
                    n = nearest[idx - w]
                dist[idx] = d
                nearest[idx] = n

    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            idx = y * w + x
            if dist[idx] > 0:
                d = dist[idx]
                n = nearest[idx]
                if x < w - 1 and dist[idx + 1] + 1 < d:
                    d = dist[idx + 1] + 1
                    n = nearest[idx + 1]
                if y < h - 1 and dist[idx + w] + 1 < d:
                    d = dist[idx + w] + 1
                    n = nearest[idx + w]
                dist[idx] = d
                nearest[idx] = n

    return dist, nearest


def silhouette_chamfer_distance(warped_alpha, body_alpha, max_dist=50):
    """Compute chamfer distance between garment and body edges.

    Lower values = better fit. Returns average boundary distance.
    """
    garment_edges = compute_edge_map(warped_alpha)
    body_edges = compute_edge_map(body_alpha)
    garment_dist, _ = garment_edges
    body_dist, _ = body_edges

    w, h = warped_alpha.size
    garment_edge_pixels = 0
    total_garment_dist = 0

    for y in range(h):
        for x in range(w):
            idx = y * w + x
            if garment_dist[idx] == 0:
                garment_edge_pixels += 1
                d = body_dist[idx]
                if d < max_dist:
                    total_garment_dist += d
                else:
                    total_garment_dist += max_dist

    if garment_edge_pixels == 0:
        return float("inf")

    return total_garment_dist / garment_edge_pixels


def validate_fit(warped_image, region_path, category=None, garment_anchors=None):
    """Validate how well the warped garment conforms to a reference region.

    The reference region should be a category-specific *allowed region*
    (e.g. ``dress_allowed_region.png``) rather than the full body
    silhouette.  If the category-specific mask is not provided, fall
    back to a generic body silhouette.

    Returns dict with fit metrics and pass/fail assessment.
    """
    result = {
        "valid": True,
        "fit_quality": "good",
        "iou": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "chamfer_distance": 0.0,
        "garment_pixels": 0,
        "region_pixels": 0,
        "region_path": region_path or "",
        "warnings": [],
        "errors": [],
    }

    if not region_path or not os.path.exists(region_path):
        result["warnings"].append("Reference region not found; skipping fit validation")
        return result

    garment_alpha = extract_alpha(warped_image)
    garment_pixels = sum(1 for p in garment_alpha.tobytes() if p > 10)
    result["garment_pixels"] = garment_pixels

    if garment_pixels == 0:
        result["valid"] = False
        result["errors"].append("Warped garment is fully transparent")
        result["fit_quality"] = "invalid"
        return result

    ref = Image.open(region_path).convert("RGBA")
    region_alpha = extract_alpha(ref)
    region_pixels = sum(1 for p in region_alpha.tobytes() if p > 10)
    result["region_pixels"] = region_pixels

    result["iou"] = round(silhouette_iou(garment_alpha, region_alpha), 4)
    result["precision"] = round(silhouette_precision(garment_alpha, region_alpha), 4)
    result["recall"] = round(silhouette_recall(garment_alpha, region_alpha), 4)
    result["chamfer_distance"] = round(
        silhouette_chamfer_distance(garment_alpha, region_alpha), 2,
    )

    if result["iou"] < 0.12:
        result["valid"] = False
        result["errors"].append(
            f"IoU too low ({result['iou']:.3f}) against reference region. "
            "Garment does not conform to allowed area."
        )
        result["fit_quality"] = "poor"
    elif result["iou"] < 0.30:
        result["warnings"].append(
            f"Low IoU ({result['iou']:.3f}) against reference region. "
            "Garment may not fit well."
        )
        result["fit_quality"] = "marginal"
    elif result["iou"] >= 0.55:
        result["fit_quality"] = "excellent"

    if result["precision"] < 0.4:
        result["warnings"].append(
            f"Low precision ({result['precision']:.3f}): large garment "
            "portions extend beyond reference region."
        )

    if result["recall"] < 0.3:
        result["warnings"].append(
            f"Low recall ({result['recall']:.3f}): garment does not cover "
            "enough of the reference region."
        )

    return result
