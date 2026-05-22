"""Garment Fit / Conformation pipeline orchestrator.

Pipeline:
   1. Validate that user-confirmed anchors are provided (no auto-inference)
   2. Map confirmed garment anchors to canonical rig anchors
   3. Warp garment into rig space (piecewise affine with fallback)
   4. Validate fit against category-specific allowed region
   5. Emit fitted garment asset, fit report, and sidecar anchors.json
"""

import os
import json
from PIL import Image

from compiler.garment_anchors import (
    STABLE_ANCHORS,
    REQUIRED_CONFIRMED_ANCHORS,
    CATEGORY_ANCHOR_MAP,
)
from compiler.category_registry import FITTING_METHOD_CATEGORIES
from compiler.warp_fit import fit_garment_piecewise, fit_garment_affine
from compiler.fit_validation import validate_fit

FIT_THUMBNAIL_SIZE = (256, 256)
ANCHORS_SIDECAR = "anchors.json"


def _load_garment_anchors(rig_config, category):
    """Load canonical garment anchors for a category from rig config."""
    cat = category.lower()
    ga = rig_config.get("garment_anchors", {})
    if cat in ga:
        return ga[cat]

    for key in ga:
        if key == cat or key.startswith(cat) or cat.startswith(key):
            return ga[key]

    return rig_config.get("anchors", {})


def _filter_stable_anchors(garment_anchors, rig_anchors, category):
    """Filter confirmed anchor dicts to the stable set for *category*."""
    cat = category.lower()
    stable = STABLE_ANCHORS.get(cat, [])
    if not stable:
        stable = list(garment_anchors.keys())

    filtered_garment = {k: garment_anchors[k] for k in stable if k in garment_anchors}
    filtered_rig = {k: rig_anchors[k] for k in stable if k in rig_anchors}
    stable_names = [n for n in stable if n in filtered_garment and n in filtered_rig]

    return filtered_garment, filtered_rig, stable_names


def _save_anchors(path, confirmed_anchors, rig_anchors, anchor_names):
    """Write the *confirmed* anchor set to a sidecar JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "garment_anchors": confirmed_anchors,
            "rig_anchors_used": rig_anchors,
            "anchor_names_used": anchor_names,
            "confirmed": True,
        }, f, indent=2)


def fit_garment(input_image_path, rig_config, category, output_dir=None, options=None):
    """Run the garment fitting pipeline with REQUIRED user-confirmed anchors.

    **No automatic anchor inference.**  If ``confirmed_anchors`` are not
    provided, fitting fails immediately.  This prevents unstable silhouette-
    derived positions from silently driving the warp.

    Args:
        input_image_path: path to normalized garment PNG
        rig_config: rig.json dict
        category: garment category (dress, topwear, …)
        output_dir: if set, writes fitted result + thumbnail + overlay + report
        options: dict with overrides:
            - confirmed_anchors: **required** dict of {name: [x, y]}
            - method: "piecewise" (default) or "affine"
            - blend_radius: int (default 20)
            - validate: bool (default True)
            - allowed_region_path: str — category-specific region mask
            - body_silhouette_path: str — fallback region mask
            - asset_id: str (default "fitted_garment")

    Returns:
        dict with fitted_image, garment_anchors, rig_anchors_used,
        fit_report, fitted bool, output_paths, anchors_saved_to.
    """
    if options is None:
        options = {}

    method = options.get("method", "piecewise")
    blend_radius = options.get("blend_radius", 20)
    should_validate = options.get("validate", True)

    result = {
        "fitted_image": None,
        "garment_anchors": {},
        "rig_anchors_used": {},
        "fit_report": {},
        "fitted": False,
        "output_paths": {},
    }

    # ── Fail fast: confirmed anchors are REQUIRED ──────────────────────────
    confirmed_anchors = options.get("confirmed_anchors")
    if not confirmed_anchors:
        result["fit_report"] = {
            "valid": False,
            "errors": [
                "Fitting requires user-confirmed anchors. "
                "No confirmed_anchors provided — refusing to run."
            ],
            "fit_quality": "invalid",
        }
        return result

    img = Image.open(input_image_path).convert("RGBA")
    result["fitted_image"] = img

    rig_anchors_all = _load_garment_anchors(rig_config, category)

    # ── Filter to stable anchors for this category ─────────────────────────
    garment_anchors, rig_anchors, stable_names = _filter_stable_anchors(
        confirmed_anchors, rig_anchors_all, category
    )
    result["garment_anchors"] = garment_anchors
    result["rig_anchors_used"] = rig_anchors

    if not stable_names:
        result["fit_report"] = {
            "valid": False,
            "errors": [
                "No stable anchors available after filtering "
                f"category '{category}'. Confirmed: {list(confirmed_anchors.keys())}, "
                f"Stable set: {STABLE_ANCHORS.get(category.lower(), [])}"
            ],
            "fit_quality": "invalid",
        }
        return result

    # ── Check category-specific required confirmed anchors ─────────────────
    required = REQUIRED_CONFIRMED_ANCHORS.get(category.lower(), [])
    missing = [n for n in required if n not in garment_anchors]
    if missing:
        result["fit_report"] = {
            "valid": False,
            "errors": [
                f"Missing required confirmed anchors for '{category}': "
                f"{', '.join(missing)}. "
                "Please place these anchors via the anchor editor."
            ],
            "fit_quality": "invalid",
            "missing_anchors": missing,
        }
        return result

    # ── Warp ───────────────────────────────────────────────────────────────
    if method == "piecewise" and category.lower() in FITTING_METHOD_CATEGORIES:
        warped = fit_garment_piecewise(
            img, garment_anchors, rig_anchors, category,
            blend_radius=blend_radius,
        )
    else:
        warped = fit_garment_affine(
            img, garment_anchors, rig_anchors, stable_names,
        )

    result["fitted_image"] = warped
    result["fitted"] = True

    # ── Resolve region paths (used for validation AND overlay) ─────────────
    allowed_region_path = options.get("allowed_region_path")
    body_silhouette_path = options.get("body_silhouette_path")

    if not allowed_region_path:
        masks_dir = os.path.join(
            os.path.dirname(os.path.dirname(input_image_path)),
            "base_rig", "masks",
        )
        allowed_region_path = os.path.join(
            masks_dir, f"{category.lower()}_allowed_region.png",
        )
        if not os.path.exists(allowed_region_path):
            allowed_region_path = None

    if not body_silhouette_path:
        masks_dir = os.path.join(
            os.path.dirname(os.path.dirname(input_image_path)),
            "base_rig", "masks",
        )
        body_silhouette_path = os.path.join(masks_dir, "body_silhouette.png")
        if not os.path.exists(body_silhouette_path):
            body_silhouette_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(input_image_path))),
                "base_rig", "masks", "body_silhouette.png",
            )

    region_path = allowed_region_path or body_silhouette_path

    # ── Validate: prefer category-specific allowed region ──────────────────
    if should_validate:
        fit_report = validate_fit(
            warped, region_path,
            category=category,
            garment_anchors=garment_anchors,
        )
        result["fit_report"] = fit_report

    # ── Save outputs ───────────────────────────────────────────────────────
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        asset_id = options.get("asset_id", "fitted_garment")

        fitted_path = os.path.join(output_dir, f"{asset_id}_fitted.png")
        warped.save(fitted_path, "PNG")
        result["output_paths"]["fitted"] = fitted_path

        thumbnail = warped.resize(FIT_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        thumb_path = os.path.join(output_dir, f"{asset_id}_thumb.png")
        thumbnail.save(thumb_path, "PNG")
        result["output_paths"]["thumbnail"] = thumb_path

        overlay = Image.new("RGBA", warped.size, (0, 0, 0, 0))
        if region_path and os.path.exists(region_path):
            sil = Image.open(region_path).convert("RGBA")
            sil_rgba = Image.new("RGBA", sil.size, (0, 0, 0, 0))
            sil_rgba.paste(sil, (0, 0), sil)
            overlay = Image.alpha_composite(overlay, sil_rgba)

        overlay = Image.alpha_composite(overlay, warped)
        overlay_path = os.path.join(output_dir, f"{asset_id}_overlay.png")
        overlay.save(overlay_path, "PNG")
        result["output_paths"]["overlay"] = overlay_path

        report_path = os.path.join(output_dir, f"{asset_id}_fit_report.json")
        with open(report_path, "w") as f:
            json.dump(result.get("fit_report", {}), f, indent=2)
        result["output_paths"]["report"] = report_path

        # Save confirmed anchors sidecar (never inferred ones)
        sidecar_path = os.path.join(output_dir, ANCHORS_SIDECAR)
        _save_anchors(
            sidecar_path,
            garment_anchors,
            rig_anchors,
            stable_names,
        )
        result["output_paths"]["anchors"] = sidecar_path
        result["anchors_saved_to"] = sidecar_path

    return result
