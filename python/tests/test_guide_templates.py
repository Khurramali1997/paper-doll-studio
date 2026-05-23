"""Tests for the authoring-guide PNG renderer."""

import io
import os
import sys
import unittest
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from PIL import Image

from compiler.guide_templates import (
    GUIDES,
    build_guides_zip,
    generate_guide,
)


BASE_RIG_DIR = os.path.join(PROJECT_ROOT, "base_rig")


class TestGuideTemplates(unittest.TestCase):
    def test_each_guide_renders_768_rgba_human_and_ai(self):
        for guide_id in GUIDES.keys():
            for ai in (False, True):
                with self.subTest(guide=guide_id, ai=ai):
                    img = generate_guide(guide_id, BASE_RIG_DIR, ai=ai)
                    self.assertEqual(img.size, (768, 768))
                    self.assertEqual(img.mode, "RGBA")

    def test_human_guide_has_visible_content(self):
        img = generate_guide("dress_bodycon", BASE_RIG_DIR, ai=False)
        pixels = img.load()
        non_white = 0
        for y in range(0, 768, 8):
            for x in range(0, 768, 8):
                r, g, b, _ = pixels[x, y]
                if (r, g, b) != (255, 255, 255):
                    non_white += 1
        self.assertGreater(non_white, 100)

    def test_ai_guide_has_no_red_dots(self):
        """AI mode strips anchor dots (which use DOT_COLOR ~ (220, 30, 60))."""
        img = generate_guide("dress_bodycon", BASE_RIG_DIR, ai=True)
        pixels = img.load()
        red_dot_pixels = 0
        for y in range(768):
            for x in range(768):
                r, g, b, _ = pixels[x, y]
                if r > 180 and g < 80 and b < 100:
                    red_dot_pixels += 1
        self.assertEqual(red_dot_pixels, 0,
                         "AI guide should not contain red anchor dots")

    def test_flared_dress_has_more_tinted_pixels_than_bodycon(self):
        """The flared variant adds a secondary trapezoid below the hips."""
        bodycon = generate_guide("dress_bodycon", BASE_RIG_DIR, ai=True)
        flared = generate_guide("dress_flared", BASE_RIG_DIR, ai=True)

        def colored_pixel_count(img):
            count = 0
            px = img.load()
            for y in range(0, 768, 4):
                for x in range(0, 768, 4):
                    r, g, b, _ = px[x, y]
                    if (r, g, b) != (255, 255, 255):
                        count += 1
            return count

        self.assertGreater(colored_pixel_count(flared), colored_pixel_count(bodycon))

    def test_unsupported_guide_raises(self):
        with self.assertRaises(ValueError):
            generate_guide("not_a_real_guide", BASE_RIG_DIR)

    def test_build_guides_zip_contains_human_and_ai_for_each(self):
        data = build_guides_zip(BASE_RIG_DIR)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
        expected = set()
        for guide_id in GUIDES.keys():
            expected.add(f"human/{guide_id}.png")
            expected.add(f"ai/{guide_id}.png")
        self.assertEqual(names, expected)

    def test_zip_entries_are_valid_pngs(self):
        data = build_guides_zip(BASE_RIG_DIR)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                with zf.open(name) as fh:
                    img = Image.open(fh)
                    img.load()
                    self.assertEqual(img.size, (768, 768))


if __name__ == "__main__":
    unittest.main()
