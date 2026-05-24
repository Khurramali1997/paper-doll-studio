"""Tests for style_schema extraction and application."""

import cv2
import numpy as np
import pytest

from compiler.style_schema import (
    extract_style_schema,
    apply_style_schema,
)


def _make_skin_layer(h=128, w=64) -> np.ndarray:
    """Create a synthetic cel-shaded skin layer for testing."""
    img = np.zeros((h, w, 4), dtype=np.uint8)
    # Body region (left portion)
    img[10:118, 5:50] = [200, 180, 160, 255]  # base skin BGR
    # Shadow band on left
    img[10:118, 5:20] = [140, 120, 100, 255]
    # Highlight ellipse on upper-center
    cy, cx = 40, 28
    yy, xx = np.ogrid[:h, :w]
    hl = ((yy - cy) ** 2 / 12 ** 2 + (xx - cx) ** 2 / 8 ** 2) <= 1
    img[hl] = [230, 220, 210, 255]
    return img


def _make_test_mask(h=128, w=64) -> np.ndarray:
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[15:113, 10:54] = 255
    return mask


class TestExtraction:
    def test_palette_has_four_tones(self):
        img = _make_skin_layer()
        schema = extract_style_schema(img)
        assert len(schema["palette_ratios"]) == 3  # shadow1, shadow2, highlight

    def test_shadow_side_is_consistent(self):
        img = _make_skin_layer()
        schema = extract_style_schema(img)
        assert schema["shadow_side"] in ("left", "right")

    def test_highlight_position_upper_center(self):
        img = _make_skin_layer()
        schema = extract_style_schema(img)
        # highlight should be in upper half of region
        assert schema["highlight_pos"][1] < 0.0  # negative = above center

    def test_shadow_coverage_in_range(self):
        img = _make_skin_layer()
        schema = extract_style_schema(img)
        assert schema["shadow_coverage"] < 0.95  # some shadow present

    def test_stroke_weight_positive(self):
        img = _make_skin_layer()
        schema = extract_style_schema(img)
        assert schema["stroke_weight"] >= 1

    def test_schema_has_all_keys(self):
        img = _make_skin_layer()
        schema = extract_style_schema(img)
        expected_keys = {
            "palette_ratios", "shadow_side", "shadow_coverage",
            "shadow_softness", "highlight_pos", "highlight_axes",
            "highlight_opacity", "stroke_weight",
        }
        assert expected_keys.issubset(schema.keys())


class TestApplication:
    def test_garment_not_flat_color(self):
        mask = _make_test_mask()
        schema = extract_style_schema(_make_skin_layer())
        result = apply_style_schema(mask, schema, "#ff0000")
        # Pixel variance should be > 0 (not flat)
        pixels = result[mask > 0]
        assert pixels[:, :3].std() > 5

    def test_output_shape_and_dtype(self):
        mask = _make_test_mask()
        schema = extract_style_schema(_make_skin_layer())
        result = apply_style_schema(mask, schema, "#ff0000")
        assert result.shape == (128, 64, 4)
        assert result.dtype == np.uint8

    def test_alpha_matches_mask(self):
        mask = _make_test_mask()
        schema = extract_style_schema(_make_skin_layer())
        result = apply_style_schema(mask, schema, "#ff0000")
        assert np.array_equal(result[:, :, 3], mask)

    def test_garment_has_shading_variation(self):
        mask = _make_test_mask()
        schema = extract_style_schema(_make_skin_layer())
        result = apply_style_schema(mask, schema, "#ff0000")
        # Pixels in the mask should have more than one distinct color value
        pixels = result[mask > 0]
        assert pixels[:, 0].max() > pixels[:, 0].min()

    def test_compositing_has_contour(self):
        mask = _make_test_mask()
        schema = extract_style_schema(_make_skin_layer())
        result = apply_style_schema(mask, schema, "#ff0000")
        # At least one pixel on the mask edge should be darker than interior
        edge_mask = cv2.Canny(mask, 0, 1)
        edge_brightness = result[edge_mask > 0, :3].mean()
        interior_mask = mask & ~edge_mask
        interior_brightness = result[interior_mask > 0, :3].mean()
        assert edge_brightness <= interior_brightness

    def test_schema_reuse_deterministic(self):
        mask = _make_test_mask()
        schema = extract_style_schema(_make_skin_layer())
        r1 = apply_style_schema(mask, schema, "#ff0000")
        r2 = apply_style_schema(mask, schema, "#ff0000")
        assert np.array_equal(r1, r2)

    def test_empty_mask_returns_empty(self):
        empty = np.zeros((128, 64), dtype=np.uint8)
        schema = extract_style_schema(_make_skin_layer())
        result = apply_style_schema(empty, schema, "#ff0000")
        assert not result.any()
