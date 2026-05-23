"""Tests for the AI conditioning reference-pack generator."""

import io
import json
import os
import sys
import unittest
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
from PIL import Image

from compiler.reference_pack import (
    build_reference_pack,
    make_canny,
    make_depth,
    make_outline,
    make_pose,
)


BASE_RIG_DIR = os.path.join(PROJECT_ROOT, "base_rig")
SILHOUETTE_PATH = os.path.join(BASE_RIG_DIR, "masks", "body_silhouette.png")


def _load_rig_anchors():
    with open(os.path.join(BASE_RIG_DIR, "rig.json")) as f:
        return json.load(f).get("anchors", {})


class TestReferencePack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.silhouette = Image.open(SILHOUETTE_PATH)
        cls.anchors = _load_rig_anchors()

    def test_outline_renders_rgba_with_transparent_interior(self):
        out = make_outline(self.silhouette)
        self.assertEqual(out.size, self.silhouette.size)
        self.assertEqual(out.mode, "RGBA")
        arr = np.array(out)
        # Some opaque pixels exist (the stroke)
        self.assertGreater((arr[:, :, 3] > 0).sum(), 100)
        # But far fewer than a full silhouette would have
        self.assertLess((arr[:, :, 3] > 0).sum(), arr.shape[0] * arr.shape[1] / 4)

    def test_canny_produces_edge_map(self):
        out = make_canny(self.silhouette)
        self.assertEqual(out.size, self.silhouette.size)
        self.assertEqual(out.mode, "RGB")
        arr = np.array(out)
        # Has both black (no edge) and white (edge) pixels
        self.assertTrue(np.any(arr > 200))
        self.assertTrue(np.any(arr < 50))

    def test_depth_has_gradient(self):
        out = make_depth(self.silhouette)
        self.assertEqual(out.size, self.silhouette.size)
        self.assertEqual(out.mode, "RGB")
        arr = np.array(out.convert("L"))
        # Distance transform produces a gradient: edge pixels = 0, interior > 0
        self.assertEqual(arr.min(), 0)
        self.assertGreater(arr.max(), 100)
        # Many distinct gray levels (not just binary)
        unique_levels = len(np.unique(arr))
        self.assertGreater(unique_levels, 20)

    def test_pose_draws_joints_when_anchors_present(self):
        out = make_pose(self.anchors, self.silhouette.size)
        self.assertEqual(out.size, self.silhouette.size)
        self.assertEqual(out.mode, "RGB")
        arr = np.array(out)
        # At least the joint dots and limb lines yield non-black pixels
        non_black = (arr.sum(axis=-1) > 30).sum()
        self.assertGreater(non_black, 200)

    def test_pose_with_no_anchors_is_blank(self):
        out = make_pose({}, self.silhouette.size)
        arr = np.array(out)
        self.assertEqual(arr.sum(), 0)

    def test_build_reference_pack_zip_contains_expected_channels(self):
        data = build_reference_pack(self.silhouette, anchors=self.anchors)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
        expected = {"silhouette.png", "outline.png", "canny.png", "depth.png", "pose.png"}
        self.assertEqual(names, expected)

    def test_zip_omits_pose_when_no_anchors_given(self):
        data = build_reference_pack(self.silhouette, anchors=None)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
        self.assertNotIn("pose.png", names)
        # Other channels still present
        self.assertEqual(names, {"silhouette.png", "outline.png", "canny.png", "depth.png"})

    def test_zip_entries_are_valid_pngs_of_correct_size(self):
        data = build_reference_pack(self.silhouette, anchors=self.anchors)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                with zf.open(name) as fh:
                    img = Image.open(fh)
                    img.load()
                    self.assertEqual(img.size, self.silhouette.size)


if __name__ == "__main__":
    unittest.main()
