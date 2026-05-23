"""Tests for the silhouette-based rig autodetect.

The autodetect is a draft generator — outputs are expected to be hand-reviewed.
These tests catch regressions in the proportional placement and structural
output, not pixel-exact correctness.
"""

import json
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from PIL import Image

from compiler.rig_autodetect import (
    ANATOMICAL_Y_FRACTIONS,
    build_rig,
    detect_anchors,
)


SILHOUETTE = os.path.join(PROJECT_ROOT, "base_rig", "masks", "body_silhouette.png")
REFERENCE_RIG = os.path.join(PROJECT_ROOT, "base_rig", "rig.json")


class TestRigAutodetect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = Image.open(SILHOUETTE)
        cls.anchors = detect_anchors(cls.img)
        with open(REFERENCE_RIG) as f:
            cls.reference = json.load(f)

    def test_all_canonical_anchors_present(self):
        expected = {
            "neck",
            "left_shoulder", "right_shoulder",
            "strap_left", "strap_right",
            "bust_left", "bust_right",
            "waist_left", "waist_right",
            "hip_left", "hip_right",
            "knee_left", "knee_right",
            "ankle_left", "ankle_right",
            "hem_left", "hem_right",
        }
        self.assertEqual(set(self.anchors.keys()), expected)

    def test_y_values_match_reference_within_5px(self):
        """Anatomical fractions are calibrated to this reference rig; Y should match."""
        ref = self.reference["anchors"]
        for name in ("neck", "left_shoulder", "right_shoulder",
                     "bust_left", "waist_left", "hip_left",
                     "knee_left", "ankle_left", "hem_left"):
            with self.subTest(anchor=name):
                self.assertLessEqual(
                    abs(self.anchors[name][1] - ref[name][1]),
                    5,
                    f"{name} Y drifted",
                )

    def test_x_values_draft_within_60px(self):
        """X values are silhouette-edge approximations; allow draft tolerance."""
        ref = self.reference["anchors"]
        for name in self.anchors:
            if name not in ref:
                continue
            with self.subTest(anchor=name):
                self.assertLessEqual(
                    abs(self.anchors[name][0] - ref[name][0]),
                    60,
                    f"{name} X drifted beyond draft tolerance",
                )

    def test_left_right_symmetry_around_canvas_center(self):
        """Left/right pairs should be roughly mirrored around x ≈ canvas/2."""
        canvas_w = self.img.width
        for base in ("shoulder", "bust", "waist", "hip", "knee", "ankle", "hem", "strap"):
            left_key = f"left_{base}" if base == "shoulder" else f"{base}_left"
            right_key = f"right_{base}" if base == "shoulder" else f"{base}_right"
            with self.subTest(pair=base):
                lx = self.anchors[left_key][0]
                rx = self.anchors[right_key][0]
                mid = (lx + rx) / 2
                self.assertAlmostEqual(mid, canvas_w / 2, delta=15)

    def test_monotonic_y_top_to_bottom(self):
        """Anatomical anchors should run head→foot top-to-bottom."""
        order = ["neck", "left_shoulder", "bust_left", "waist_left",
                 "hip_left", "knee_left", "hem_left", "ankle_left"]
        ys = [self.anchors[n][1] for n in order]
        self.assertEqual(ys, sorted(ys), "anchors are not in head→foot order")

    def test_build_rig_produces_valid_schema(self):
        rig = build_rig(self.anchors, canvas=(self.img.width, self.img.height))
        self.assertIn("canvas", rig)
        self.assertIn("anchors", rig)
        self.assertIn("garment_anchors", rig)
        for cat in ("dress", "topwear", "skirt", "pants", "legwear", "outerwear"):
            self.assertIn(cat, rig["garment_anchors"])

    def test_empty_image_raises(self):
        blank = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        with self.assertRaises(ValueError):
            detect_anchors(blank)


if __name__ == "__main__":
    unittest.main()
