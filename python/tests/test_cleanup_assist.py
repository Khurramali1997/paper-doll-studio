import os
import sys
import unittest

from PIL import Image, ImageDraw

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from compiler.cleanup_assist import propose_lane_c_mask


def _stylized_guide() -> Image.Image:
    img = Image.new("RGBA", (96, 96), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((28, 20, 68, 70), fill=(30, 115, 220, 255), outline=(18, 18, 22, 255), width=3)
    draw.polygon([(28, 70), (68, 70), (78, 88), (18, 88)], fill=(30, 115, 220, 255), outline=(18, 18, 22, 255))
    draw.ellipse((2, 2, 5, 5), fill=(220, 20, 20, 255))
    draw.rectangle((40, 18, 56, 25), fill=(232, 180, 140, 255))
    return img


class TestCleanupAssist(unittest.TestCase):
    def test_keeps_dark_outlines(self):
        result = propose_lane_c_mask(_stylized_guide(), style_strength=0.25)
        alpha = result.alpha.load()
        self.assertGreater(alpha[28, 22], 10)
        self.assertGreater(result.stats["edge_preservation_score"], 0.9)

    def test_removes_white_background_regions(self):
        result = propose_lane_c_mask(_stylized_guide(), style_strength=0.35)
        alpha = result.alpha.load()
        self.assertEqual(alpha[0, 90], 0)
        self.assertGreater(alpha[48, 48], 10)

    def test_removes_small_islands(self):
        result = propose_lane_c_mask(_stylized_guide(), style_strength=0.7)
        alpha = result.alpha.load()
        self.assertEqual(alpha[3, 3], 0)

    def test_avoids_nearly_empty_output(self):
        img = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((20, 20, 44, 44), fill=(15, 40, 180, 255), outline=(10, 10, 10, 255), width=2)
        result = propose_lane_c_mask(img, style_strength=1.0)
        self.assertFalse(result.stats["warnings"]["empty"])
        self.assertGreater(result.stats["visible_pixels"], 128)

    def test_conservative_preserves_more_pixels_than_aggressive(self):
        img = _stylized_guide()
        conservative = propose_lane_c_mask(img, style_strength=0.0)
        aggressive = propose_lane_c_mask(img, style_strength=1.0)
        self.assertGreaterEqual(conservative.stats["visible_pixels"], aggressive.stats["visible_pixels"])


if __name__ == "__main__":
    unittest.main()
