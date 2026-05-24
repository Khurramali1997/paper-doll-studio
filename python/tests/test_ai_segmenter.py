"""Tests for compiler/ai_segmenter.py.

Mocks rembg so the real ~85 MB ONNX model files are never downloaded
during the test run (mirrors test_estimators.py's mocking approach).
"""

import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from PIL import Image

# Import the module under test. Avoid importing rembg at module-load time —
# the wrappers import lazily so tests that mock rembg work cleanly.
from compiler import ai_segmenter


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class TestAISegmenter(unittest.TestCase):
    def setUp(self):
        # Clear the module-level session cache between tests so each starts fresh.
        ai_segmenter._sessions.clear()

    def _fake_rembg(self):
        """Build a fake rembg module that returns the input image unchanged."""
        fake = MagicMock()
        sessions_created = []

        def fake_new_session(name):
            s = MagicMock(name=f"session({name})")
            sessions_created.append(name)
            return s

        def fake_remove(png_bytes, session=None):
            # Return the same bytes (round-trip), the wrapper will convert to RGBA.
            return png_bytes

        fake.new_session = fake_new_session
        fake.remove = fake_remove
        fake._sessions_created = sessions_created
        return fake

    def test_remove_background_returns_rgba_image(self):
        fake = self._fake_rembg()
        with patch.dict("sys.modules", {"rembg": fake}):
            src = Image.new("RGB", (100, 100), (255, 0, 0))
            result = ai_segmenter.remove_background(src)
        self.assertIsInstance(result, Image.Image)
        self.assertEqual(result.size, (100, 100))
        self.assertEqual(result.mode, "RGBA")

    def test_isolate_clothing_returns_rgba_image(self):
        fake = self._fake_rembg()
        with patch.dict("sys.modules", {"rembg": fake}):
            src = Image.new("RGB", (64, 64), (0, 255, 0))
            result = ai_segmenter.isolate_clothing(src)
        self.assertIsInstance(result, Image.Image)
        self.assertEqual(result.mode, "RGBA")

    def test_session_cached_per_model(self):
        fake = self._fake_rembg()
        with patch.dict("sys.modules", {"rembg": fake}):
            src = Image.new("RGB", (32, 32), (128, 128, 128))
            ai_segmenter.remove_background(src)
            ai_segmenter.remove_background(src)
            ai_segmenter.remove_background(src)
        # Three calls, one session creation
        self.assertEqual(fake._sessions_created.count("u2net"), 1)

    def test_different_modes_use_different_sessions(self):
        fake = self._fake_rembg()
        with patch.dict("sys.modules", {"rembg": fake}):
            src = Image.new("RGB", (32, 32), (10, 20, 30))
            ai_segmenter.remove_background(src)
            ai_segmenter.isolate_clothing(src)
        self.assertEqual(set(fake._sessions_created), {"u2net", "u2net_cloth_seg"})

    def test_process_dispatch_by_mode(self):
        fake = self._fake_rembg()
        with patch.dict("sys.modules", {"rembg": fake}):
            src = Image.new("RGB", (16, 16), (50, 50, 50))
            r1 = ai_segmenter.process(src, "bg-remove")
            r2 = ai_segmenter.process(src, "clothing-isolate")
        self.assertEqual(r1.mode, "RGBA")
        self.assertEqual(r2.mode, "RGBA")
        # Both modes triggered their respective session creations
        self.assertEqual(set(fake._sessions_created), {"u2net", "u2net_cloth_seg"})

    def test_process_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            ai_segmenter.process(Image.new("RGB", (8, 8)), "nonsense-mode")

    def test_cached_models_diagnostic(self):
        fake = self._fake_rembg()
        with patch.dict("sys.modules", {"rembg": fake}):
            self.assertEqual(ai_segmenter.cached_models(), {})
            ai_segmenter.remove_background(Image.new("RGB", (8, 8)))
        self.assertIn("u2net", ai_segmenter.cached_models())


if __name__ == "__main__":
    unittest.main()
