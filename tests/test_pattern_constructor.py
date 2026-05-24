"""Pytest tests for compiler/pattern_constructor.py.

Run from the project root:
    venv/bin/python -m pytest tests/test_pattern_constructor.py -v
"""

import numpy as np
import pytest

BASE_RIG = "base_rig"

SOLID_MATERIAL = {"type": "solid", "color": "#cc3366", "texture_arr": None}
NO_EFFECTS = {"edge_stroke": False, "inner_shadow": False, "highlight": False}
ALL_EFFECTS = {"edge_stroke": True, "inner_shadow": True, "highlight": True}
NO_TRANSFORM = {}


def _run(recipe, transform=None, effects=None, material=None):
    from compiler.pattern_constructor import construct_pattern
    return construct_pattern(
        recipe,
        BASE_RIG,
        material=material or SOLID_MATERIAL,
        effects=effects or NO_EFFECTS,
        transform=transform or NO_TRANSFORM,
    )


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------

def test_recipe_non_empty_alpha():
    r = _run("bodice")
    assert r["image_rgba"][:, :, 3].any(), "Bodice alpha channel is entirely zero"


def test_output_canvas_size():
    r = _run("bodice")
    assert r["image_rgba"].shape == (768, 768, 4), f"Unexpected shape: {r['image_rgba'].shape}"


def test_all_recipes_produce_output():
    from compiler.pattern_constructor import RECIPES
    for name in RECIPES:
        r = _run(name)
        assert r["image_rgba"][:, :, 3].any(), f"Recipe {name!r} produced empty alpha"
        assert r["area_px"] > 0, f"Recipe {name!r} has zero area"


# ---------------------------------------------------------------------------
# Transform operations
# ---------------------------------------------------------------------------

def test_expand_y_increases_coverage():
    r0 = _run("bodice", transform={"expand_y": 0})
    r1 = _run("bodice", transform={"expand_y": 20})
    assert r1["area_px"] > r0["area_px"], "expand_y=20 did not increase coverage"


def test_expand_x_increases_coverage():
    r0 = _run("bodice", transform={"expand_x": 0})
    r1 = _run("bodice", transform={"expand_x": 20})
    assert r1["area_px"] > r0["area_px"], "expand_x=20 did not increase coverage"


def test_dilate_increases_coverage():
    r0 = _run("bodice", transform={"dilate_px": 0})
    r1 = _run("bodice", transform={"dilate_px": 8})
    assert r1["area_px"] > r0["area_px"]


def test_erode_decreases_coverage():
    r0 = _run("bodice", transform={"erode_px": 0})
    r1 = _run("bodice", transform={"erode_px": 8})
    assert r1["area_px"] < r0["area_px"]


# ---------------------------------------------------------------------------
# Flare geometry
# ---------------------------------------------------------------------------

def test_flared_dress_wider_at_hem_than_waist():
    from compiler.pattern_constructor import build_mask_from_recipe, _load_rig_anchors
    anchors = _load_rig_anchors(BASE_RIG)
    mask, _ = build_mask_from_recipe("simple_flared_dress", BASE_RIG, rig_anchors=anchors)

    active_rows = np.where(mask.any(axis=1))[0]
    assert len(active_rows) > 0

    y_min, y_max = int(active_rows.min()), int(active_rows.max())
    y_mid = (y_min + y_max) // 2

    # Measure width at waist (mid-point) and at hem (bottom quarter)
    hem_start = y_max - (y_max - y_mid) // 4
    hem_rows = [mask[y] for y in range(hem_start, y_max + 1) if mask[y].any()]
    waist_rows = [mask[y] for y in range(y_mid - 10, y_mid + 10) if mask[y].any()]

    def avg_width(rows):
        if not rows:
            return 0
        return np.mean([r.sum() // 255 for r in rows])

    assert avg_width(hem_rows) > avg_width(waist_rows), \
        "Flared dress hem not wider than waist"


# ---------------------------------------------------------------------------
# Forbidden masks
# ---------------------------------------------------------------------------

def test_face_anchor_not_in_bodice():
    r = _run("bodice")
    # Face anchor is at approximately (384, 180) in the 768×768 canvas
    alpha_at_face = r["image_rgba"][180, 384, 3]
    assert alpha_at_face == 0, \
        f"Bodice has non-zero alpha ({alpha_at_face}) at face anchor (384, 180)"


def test_forbidden_region_removes_pixels():
    from compiler.pattern_constructor import load_mask, build_mask_from_recipe
    mask, _ = build_mask_from_recipe("bodice", BASE_RIG)
    face = load_mask("face_forbidden_region", BASE_RIG)
    overlap = int(np.count_nonzero(mask & face))
    assert overlap == 0, f"Bodice overlaps face forbidden region by {overlap}px"


# ---------------------------------------------------------------------------
# Metadata output
# ---------------------------------------------------------------------------

def test_contour_points_emitted():
    r = _run("bodice")
    assert len(r["contour_points"]) > 0, "No contour points returned"
    assert all(len(pt) == 2 for pt in r["contour_points"]), "Contour points should be [x, y]"


def test_bounding_box_emitted():
    r = _run("bodice")
    bb = r["bounding_box"]
    assert len(bb) == 4, "Bounding box should be [x, y, w, h]"
    x, y, w, h = bb
    assert all(v > 0 for v in [x, y, w, h]), f"Bounding box has zero component: {bb}"


def test_operations_log_non_empty():
    r = _run("bodice")
    assert len(r["operations"]) > 0


def test_category_matches_recipe():
    from compiler.pattern_constructor import RECIPES
    for name, spec in RECIPES.items():
        r = _run(name)
        assert r["category"] == spec["category"]


# ---------------------------------------------------------------------------
# Effects (smoke — just verify no crash and alpha preserved)
# ---------------------------------------------------------------------------

def test_effects_do_not_remove_mask():
    r = _run("bodice", effects=ALL_EFFECTS)
    assert r["image_rgba"][:, :, 3].any(), "Effects stripped all alpha"


# ---------------------------------------------------------------------------
# Unknown recipe
# ---------------------------------------------------------------------------

def test_unknown_recipe_raises():
    from compiler.pattern_constructor import construct_pattern
    with pytest.raises(ValueError, match="Unknown recipe"):
        construct_pattern(
            "nonexistent_xyz", BASE_RIG,
            material=SOLID_MATERIAL, effects=NO_EFFECTS, transform={},
        )
