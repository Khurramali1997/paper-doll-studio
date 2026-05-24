"""Deterministic garment post-processing pipeline for paper doll assets.

Operates on compiled garment PNGs — no fabric texture is needed because the
garment already has its own artwork. Depth is derived from the body silhouette
distance transform (the same proxy used by the reference-pack generator).

Zero neural inference. All operations are pure OpenCV / numpy geometry.
Same inputs always produce the same outputs.

All tunable parameters are in PIPELINE_CONFIG at the top of this file.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Configuration — every tunable parameter lives here, never hardcoded below
# ---------------------------------------------------------------------------
PIPELINE_CONFIG: dict = {
    # Warp
    "warp_strength": 0.35,           # Normal-field displacement multiplier (0=none, 1=max)
    # Depth lighting
    "depth_blur_sigma": 40,          # Gaussian sigma for depth mask smoothing (px)
    # Morphological feathering
    "feather_size": 6,               # Feather radius on mask edges (px)
    # Lineart outline
    "outline_thickness": 1,          # Outline stroke width (px)
    "outline_color_bgr": [20, 20, 20],  # Outline color (BGR)
    # Seam drawing
    "seam_dash_on": 6,               # Drawn pixels per dash segment
    "seam_dash_off": 4,              # Skipped pixels per dash gap
    "seam_darken": 0.60,             # Seam color: multiply fabric sample by this
    # Contour simplification
    "contour_epsilon": 2.0,          # Douglas-Peucker epsilon (px)
    # Pipeline behavior
    "save_intermediates": True,      # Write intermediate images for inspection
    "manifest_path": "asset_manifest.json",  # Manifest registry file path
    # Semantic annotation
    "base_rig_dir": None,            # Path to base_rig/ — enables mask geometry checks
    "rig_anchors": None,             # Pre-loaded anchor dict from rig.json
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_mask(src) -> np.ndarray:
    """Return a uint8 binary (0 or 255) single-channel mask."""
    if isinstance(src, np.ndarray):
        img = src.copy()
    else:
        img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"Cannot read mask: {src}")

    if img.ndim == 2:
        gray = img
    elif img.shape[2] == 4:
        gray = img[:, :, 3]
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
    return binary


def _load_garment(src) -> tuple[np.ndarray, np.ndarray]:
    """
    Load a garment PNG and return (bgr, alpha) as uint8 arrays.

    The garment is a paper doll asset — it already carries its own artwork.
    No tiling or external texture is needed.
    """
    if isinstance(src, np.ndarray):
        img = src.copy()
    else:
        img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"Cannot read garment: {src}")

    if img.ndim == 2:
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        alpha = np.full(img.shape[:2], 255, dtype=np.uint8)
    elif img.shape[2] == 3:
        bgr = img
        alpha = np.full(img.shape[:2], 255, dtype=np.uint8)
    else:  # 4 channels
        bgr = img[:, :, :3]
        alpha = img[:, :, 3]

    return bgr, alpha


def _compute_normal_field(mask_bin: np.ndarray):
    """
    Compute the inward-pointing normal field via distance transform gradient.

    Returns (dist, norm_x, norm_y):
      dist   – float32 distance from nearest boundary (0 at edge, max at center)
      norm_x – float32 x-component of unit normal (points toward interior)
      norm_y – float32 y-component of unit normal (points toward interior)
    """
    dist = cv2.distanceTransform(mask_bin, cv2.DIST_L2, cv2.DIST_MASK_PRECISE).astype(np.float32)
    grad_x = cv2.Sobel(dist, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(dist, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(grad_x ** 2 + grad_y ** 2) + 1e-8
    return dist, grad_x / mag, grad_y / mag


def _row_width_profile(mask_bin: np.ndarray) -> np.ndarray:
    """
    Scan each row of the mask and return a float32 taper curve, shape (H,), in [0, 1].
    Narrow rows (neck, waist) are near 0; wide rows (shoulders, hips) are near 1.
    """
    widths = np.sum(mask_bin > 0, axis=1).astype(np.float32)
    peak = max(float(widths.max()), 1.0)
    return widths / peak


def _warp_fabric(
    fabric: np.ndarray,
    mask_bin: np.ndarray,
    dist: np.ndarray,
    norm_x: np.ndarray,
    norm_y: np.ndarray,
    row_taper: np.ndarray,
    warp_strength: float,
) -> np.ndarray:
    """
    Replace centroid-based cv2.remap displacement with the normal-field warp.
    Displacement at each pixel is proportional to its distance from the boundary,
    scaled by warp_strength and modulated per-row by the body taper curve.
    """
    H, W = mask_bin.shape
    grid_x, grid_y = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))

    disp_scale = dist * warp_strength * row_taper[:, np.newaxis]  # (H, W)
    map_x = (grid_x + norm_x * disp_scale).astype(np.float32)
    map_y = (grid_y + norm_y * disp_scale).astype(np.float32)

    return cv2.remap(fabric, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def _apply_depth_lighting(
    fabric: np.ndarray,
    depth_mask: Optional[np.ndarray],
    mask_bin: np.ndarray,
    sigma: float,
) -> np.ndarray:
    """
    Multiply a smooth depth gradient onto the fabric as a lighting layer.
    Near = bright, far = dark. Falls back to a centroid-distance proxy when
    no depth mask is supplied.
    """
    H, W = mask_bin.shape

    if depth_mask is not None:
        d = depth_mask.astype(np.float32) / 255.0
        if d.ndim == 3:
            d = d[:, :, 0]
        ksize = int(sigma * 6) | 1
        light = cv2.GaussianBlur(d, (ksize, ksize), sigmaX=sigma, sigmaY=sigma)
    else:
        M = cv2.moments(mask_bin)
        cx = M["m10"] / M["m00"] if M["m00"] > 0 else W / 2.0
        cy = M["m01"] / M["m00"] if M["m00"] > 0 else H / 2.0
        ys, xs = np.mgrid[0:H, 0:W]
        dist_c = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2).astype(np.float32)
        max_d = max(float(dist_c.max()), 1.0)
        light = 1.0 - (dist_c / max_d) * 0.45

    light = np.clip(light, 0.0, 1.0)
    lit = np.empty_like(fabric)
    for c in range(fabric.shape[2]):
        lit[:, :, c] = (fabric[:, :, c] * light).clip(0, 255).astype(np.uint8)
    return lit


def _feather_mask_alpha(mask_bin: np.ndarray, feather_size: int) -> np.ndarray:
    """Return a float32 alpha map in [0, 1] with morphologically feathered edges."""
    if feather_size < 1:
        return (mask_bin > 0).astype(np.float32)
    ksize = feather_size * 4 + 1
    blurred = cv2.GaussianBlur(
        mask_bin.astype(np.float32), (ksize, ksize),
        sigmaX=feather_size, sigmaY=feather_size,
    )
    peak = float(blurred.max())
    return (blurred / peak).clip(0.0, 1.0) if peak > 0 else blurred


def _extract_contours(mask_bin: np.ndarray, epsilon: float) -> list:
    """Extract and Douglas-Peucker-simplify the largest external contour."""
    contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)
    simplified = cv2.approxPolyDP(largest, epsilon, closed=True)
    return simplified[:, 0, :].tolist()


def _draw_outline(rgba: np.ndarray, mask_bin: np.ndarray, thickness: int, color_bgr: list) -> np.ndarray:
    """Draw a lineart outline at the mask contour using cv2.drawContours."""
    contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return rgba
    out = rgba.copy()
    b, g, r = int(color_bgr[0]), int(color_bgr[1]), int(color_bgr[2])
    for cnt in contours:
        cv2.drawContours(out, [cnt], -1, (b, g, r, 255), thickness)
    return out


def _build_seam_skeleton(mask_bin: np.ndarray):
    """
    Compute a single-pixel-wide seam skeleton from the mask boundary.

    Skeletonizes the boundary zone via cv2.ximgproc.thinning when available;
    falls back to morphological erosion otherwise.

    Returns (seam_zone, skeleton) as uint8 binary arrays.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dilated = cv2.dilate(mask_bin, kernel, iterations=2)
    eroded = cv2.erode(mask_bin, kernel, iterations=2)
    seam_zone = cv2.bitwise_xor(dilated, eroded)

    try:
        skeleton = cv2.ximgproc.thinning(seam_zone, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN)
    except AttributeError:
        k2 = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        skeleton = cv2.erode(seam_zone, k2, iterations=1)

    return seam_zone, skeleton


def _draw_seam_lines(rgba: np.ndarray, skeleton: np.ndarray, cfg: dict) -> np.ndarray:
    """
    Draw 1 px dashed seam stitching marks on the rgba canvas.
    Color is sampled from the fabric at each point, multiplied by seam_darken.
    """
    dash_on = int(cfg["seam_dash_on"])
    dash_off = int(cfg["seam_dash_off"])
    darken = float(cfg["seam_darken"])
    period = dash_on + dash_off

    ys, xs = np.where(skeleton > 0)
    out = rgba.copy()
    for i, (y, x) in enumerate(zip(ys, xs)):
        if i % period < dash_on:
            out[y, x, 0] = int(out[y, x, 0] * darken)
            out[y, x, 1] = int(out[y, x, 1] * darken)
            out[y, x, 2] = int(out[y, x, 2] * darken)
    return out


def _boolean_op(a: np.ndarray, b: np.ndarray, mode: str) -> np.ndarray:
    """Boolean mask operation. mode: 'subtract' | 'and' | 'xor'."""
    if mode == "subtract":
        return cv2.bitwise_and(a, cv2.bitwise_not(b))
    if mode == "and":
        return cv2.bitwise_and(a, b)
    if mode == "xor":
        return cv2.bitwise_xor(a, b)
    raise ValueError(f"Unknown boolean mode: {mode!r}")


def _composite_over(dst: np.ndarray, src: np.ndarray) -> np.ndarray:
    """Porter-Duff 'over' alpha composite of src on top of dst. Both RGBA uint8."""
    d = dst.astype(np.float32) / 255.0
    s = src.astype(np.float32) / 255.0
    sa = s[:, :, 3:4]
    da = d[:, :, 3:4]
    out_a = sa + da * (1.0 - sa)
    out_rgb = np.where(
        out_a > 0,
        (s[:, :, :3] * sa + d[:, :, :3] * da * (1.0 - sa)) / (out_a + 1e-8),
        0.0,
    )
    return (np.concatenate([out_rgb, out_a], axis=2) * 255).clip(0, 255).astype(np.uint8)


def _save(path: str, img: np.ndarray) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


def _write_manifest_entry(entry: dict, manifest_path: str) -> None:
    p = Path(manifest_path)
    records: list = []
    if p.exists():
        try:
            with open(p) as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append(entry)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(records, f, indent=2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_single_layer(
    garment,
    stencil_mask=None,
    depth_map: Optional[np.ndarray] = None,
    label: str = "garment",
    config: Optional[dict] = None,
    out_dir: str = ".",
    layer_index: int = 0,
) -> dict:
    """
    Run the full pipeline for one garment asset.

    Parameters
    ----------
    garment      : path-like or np.ndarray — the compiled garment PNG (RGBA).
                   Its own pixel data is used directly; no external texture needed.
    stencil_mask : optional path-like or np.ndarray — a separate binary mask
                   that defines the warp boundary region. When None, the garment's
                   own alpha channel is used as the mask.
    depth_map    : optional uint8 grayscale or RGB array — body depth image
                   (brighter = closer to camera). Caller should supply this from
                   the already-generated reference-pack depth channel. When None
                   the pipeline falls back to a centroid-distance proxy.
    label        : semantic label for the asset manifest
    config       : parameter overrides (merged onto PIPELINE_CONFIG defaults)
    out_dir      : root output directory
    layer_index  : index in a multi-layer run (for naming intermediates)

    Returns
    -------
    dict:
        rgba         – np.ndarray RGBA uint8 (H, W, 4)
        contour_pts  – list of [x, y] simplified contour points
        bbox         – [x, y, w, h]
        paths        – dict mapping intermediate names to saved file paths
        label        – str
    """
    cfg = {**PIPELINE_CONFIG, **(config or {})}
    out = Path(out_dir)
    inter = out / "intermediates" / f"layer_{layer_index}"
    paths: dict = {}

    # Step 1 — load garment; derive mask from its alpha unless a stencil is given
    bgr, garment_alpha = _load_garment(garment)
    H, W = bgr.shape[:2]

    if stencil_mask is not None:
        mask_bin = _load_mask(stencil_mask)
    else:
        _, mask_bin = cv2.threshold(garment_alpha, 127, 255, cv2.THRESH_BINARY)

    if cfg["save_intermediates"]:
        p = str(inter / "mask_binary.png")
        _save(p, mask_bin)
        paths["mask_binary"] = p
        p = str(inter / "garment_source.png")
        src_rgba = np.dstack([bgr, garment_alpha])
        _save(p, src_rgba)
        paths["garment_source"] = p

    # Step 2 — contour normal field (distance transform → gradient)
    dist, norm_x, norm_y = _compute_normal_field(mask_bin)

    if cfg["save_intermediates"]:
        peak = float(dist.max()) if dist.max() > 0 else 1.0
        p = str(inter / "dist_field.png")
        _save(p, (dist / peak * 255).astype(np.uint8))
        paths["dist_field"] = p
        p = str(inter / "normal_x.png")
        _save(p, ((norm_x + 1.0) / 2.0 * 255).astype(np.uint8))
        paths["normal_x"] = p
        p = str(inter / "normal_y.png")
        _save(p, ((norm_y + 1.0) / 2.0 * 255).astype(np.uint8))
        paths["normal_y"] = p

    # Step 3 — per-row mask width profile (body taper curve)
    row_taper = _row_width_profile(mask_bin)

    # Step 4 — normal-driven warp on garment pixels, modulated by taper
    warped = _warp_fabric(bgr, mask_bin, dist, norm_x, norm_y, row_taper, float(cfg["warp_strength"]))

    if cfg["save_intermediates"]:
        p = str(inter / "garment_warped.png")
        _save(p, warped)
        paths["garment_warped"] = p

    # Step 5 — depth lighting from the pre-computed depth map
    lit = _apply_depth_lighting(warped, depth_map, mask_bin, float(cfg["depth_blur_sigma"]))

    if cfg["save_intermediates"]:
        p = str(inter / "garment_lit.png")
        _save(p, lit)
        paths["garment_lit"] = p

    # Step 6 — feathered alpha (combines garment alpha with stencil boundary feather)
    boundary_alpha = _feather_mask_alpha(mask_bin, int(cfg["feather_size"]))
    # Respect original garment alpha: multiply by the feathered stencil boundary
    combined_alpha = (garment_alpha / 255.0) * boundary_alpha

    # Compose RGBA
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[:, :, :3] = lit
    rgba[:, :, 3] = (combined_alpha * 255).clip(0, 255).astype(np.uint8)

    # Step 7 — lineart outline via drawContours
    rgba = _draw_outline(rgba, mask_bin, int(cfg["outline_thickness"]), cfg["outline_color_bgr"])

    # Step 8 — seam skeleton → dashed seam line drawing
    seam_zone, skeleton = _build_seam_skeleton(mask_bin)

    if cfg["save_intermediates"]:
        p = str(inter / "seam_zone.png")
        _save(p, seam_zone)
        paths["seam_zone"] = p
        p = str(inter / "seam_skeleton.png")
        _save(p, skeleton)
        paths["seam_skeleton"] = p

    rgba = _draw_seam_lines(rgba, skeleton, cfg)

    # Extract contour points and bounding box for manifest
    contour_pts = _extract_contours(mask_bin, float(cfg["contour_epsilon"]))
    x, y, bw, bh = cv2.boundingRect(mask_bin)

    # Save final layer PNG
    layer_path = str(out / f"layer_{layer_index}_{label}.png")
    _save(layer_path, rgba)
    paths["result"] = layer_path

    # Step 9 — semantic annotation (graceful; never blocks the pipeline)
    semantic: dict = {}
    try:
        from compiler.semantic_layer import annotate as _semantic_annotate
        semantic = _semantic_annotate(
            garment_rgba=rgba,
            mask_bin=mask_bin,
            label=label,
            rig_anchors=cfg.get("rig_anchors"),
            base_rig_dir=cfg.get("base_rig_dir"),
        )
    except Exception:
        pass

    return {
        "rgba": rgba,
        "contour_pts": contour_pts,
        "bbox": [int(x), int(y), int(bw), int(bh)],
        "paths": paths,
        "label": label,
        "semantic": semantic,
    }


def run_pipeline(
    garments: list,
    stencil_masks: Optional[list] = None,
    depth_map: Optional[np.ndarray] = None,
    label: str = "garment",
    config: Optional[dict] = None,
    out_dir: str = ".",
) -> dict:
    """
    Run the deterministic garment post-processing pipeline.

    Garments are given in depth order: index 0 = deepest (rendered first, behind),
    last index = shallowest (rendered on top). Porter-Duff 'over' composite is
    applied in that order.

    Parameters
    ----------
    garments      : list of garment PNG paths or np.ndarray RGBA arrays.
                    Each garment's own pixel data is used — no external texture.
    stencil_masks : optional list of mask paths or arrays, parallel to garments.
                    When None (or shorter than garments), the garment's alpha is
                    used as its own mask.
    depth_map     : optional uint8 array — the body depth image already generated
                    by the reference-pack pipeline (brighter = closer to camera).
                    When None the depth-lighting step uses a centroid proxy.
    label         : base semantic label for the asset manifest
    config        : parameter overrides (merged onto PIPELINE_CONFIG)
    out_dir       : root output directory; subdirs are created automatically

    Returns
    -------
    dict:
        asset_id       – str UUID
        layers         – list of per-layer result dicts
        composite_rgba – np.ndarray RGBA uint8 — merged result
        composite_path – str path to saved composite PNG
        manifest_entry – dict ready to append to asset_manifest.json
    """
    cfg = {**PIPELINE_CONFIG, **(config or {})}
    out = Path(out_dir)
    asset_id = str(uuid.uuid4())

    layers = []
    for i, garment in enumerate(garments):
        layer_label = f"{label}_{i}" if len(garments) > 1 else label
        mask = stencil_masks[i] if stencil_masks and i < len(stencil_masks) else None
        result = process_single_layer(
            garment=garment,
            stencil_mask=mask,
            depth_map=depth_map,
            label=layer_label,
            config=cfg,
            out_dir=str(out),
            layer_index=i,
        )
        layers.append(result)

    # Multi-layer composite: deepest first, shallowest last
    H, W = layers[0]["rgba"].shape[:2]
    composite = np.zeros((H, W, 4), dtype=np.uint8)
    for layer in layers:
        composite = _composite_over(composite, layer["rgba"])

    composite_path = str(out / "composite.png")
    _save(composite_path, composite)

    manifest_entry = {
        "asset_id": asset_id,
        "source_garments": [
            str(g) if not isinstance(g, np.ndarray) else "<ndarray>"
            for g in garments
        ],
        "semantic_label": label,
        "contour_points": layers[0]["contour_pts"] if layers else [],
        "bounding_box": layers[0]["bbox"] if layers else [0, 0, 0, 0],
        "output_path": composite_path,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "layer_count": len(layers),
        "layer_paths": [layer["paths"].get("result", "") for layer in layers],
        "semantic": layers[0].get("semantic", {}) if layers else {},
    }

    _write_manifest_entry(manifest_entry, cfg["manifest_path"])

    return {
        "asset_id": asset_id,
        "layers": layers,
        "composite_rgba": composite,
        "composite_path": composite_path,
        "manifest_entry": manifest_entry,
    }
