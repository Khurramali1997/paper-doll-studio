import os
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw
import numpy as np


# ── Shared helpers ──────────────────────────────────────────────────────────

def _make_dress_img():
    img = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([
        (370, 160), (398, 160), (410, 165), (470, 240),
        (460, 350), (440, 410), (460, 440), (455, 600),
        (313, 600), (308, 440), (328, 410), (298, 350),
        (298, 240), (358, 165),
    ], fill=(200, 50, 50, 255))
    return img


def _dress_confirmed_anchors():
    """Return a plausible user-confirmed anchor set for the test dress."""
    return {
        "neck": [384, 170],
        "strap_left": [320, 210],
        "strap_right": [448, 210],
        "bust_left": [340, 280],
        "bust_right": [428, 280],
        "waist_left": [320, 410],
        "waist_right": [446, 410],
        "hip_left": [310, 440],
        "hip_right": [458, 440],
        "hem_left": [315, 595],
        "hem_right": [453, 595],
    }


def _dress_rig_anchors(d=None):
    """Return a minimal rig anchor dict for dress fitting tests."""
    if d is None:
        d = {
            "neck": [384, 180],
            "strap_left": [320, 210],
            "strap_right": [448, 210],
            "bust_left": [340, 280],
            "bust_right": [428, 280],
            "waist_left": [318, 420],
            "waist_right": [446, 420],
            "hip_left": [300, 440],
            "hip_right": [468, 440],
            "hem_left": [320, 580],
            "hem_right": [456, 580],
        }
    return d


def _make_fake_rig_json(path):
    """Write a minimal rig.json for end-to-end tests."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump({
            "canvas": [768, 768],
            "anchors": {
                "neck": [384, 180],
                "left_shoulder": [304, 250],
                "right_shoulder": [472, 250],
                "waist_left": [318, 420],
                "waist_right": [446, 420],
            },
            "garment_anchors": {
                "dress": _dress_rig_anchors(),
            },
        }, f)


# ── Test: Inferred anchors are suggested, not confirmed ─────────────────────

class TestSuggestedAnchors(unittest.TestCase):
    """infer_garment_anchors() must return suggested anchors only."""

    def setUp(self):
        from compiler.garment_anchors import infer_garment_anchors
        self.infer = infer_garment_anchors

    def test_inferred_anchors_wrapped_in_suggested(self):
        img = _make_dress_img()
        result = self.infer(img)
        self.assertIn('suggested', result,
                      "infer_garment_anchors must return {'suggested': ...}")
        self.assertNotIn('confirmed', result,
                         "Inferred anchors must NOT be marked confirmed")

    def test_suggested_anchors_are_valid_coordinates(self):
        img = _make_dress_img()
        result = self.infer(img)
        suggested = result.get('suggested', {})
        self.assertGreater(len(suggested), 0)
        for name, pos in suggested.items():
            self.assertEqual(len(pos), 2)
            self.assertIsInstance(pos[0], (int, float))
            self.assertIsInstance(pos[1], (int, float))

    def test_empty_image_returns_empty(self):
        img = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        result = self.infer(img)
        self.assertEqual(result, {})

    def test_suggested_dress_has_neck_shoulders_waist_hem(self):
        img = _make_dress_img()
        result = self.infer(img)
        suggested = result.get('suggested', {})
        for name in ('neck', 'left_shoulder', 'right_shoulder',
                     'waist_left', 'waist_right',
                     'hem_left', 'hem_right'):
            self.assertIn(name, suggested,
                          f"Dress suggestion missing: {name}")


# ── Test: fitting fails without confirmed anchors ───────────────────────────

class TestFittingRequiresConfirmedAnchors(unittest.TestCase):
    """fit_garment() must reject any call without confirmed_anchors."""

    def setUp(self):
        from compiler.fit_pipeline import fit_garment
        self.fit = fit_garment
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _save_image(self, img=None):
        if img is None:
            img = _make_dress_img()
        path = os.path.join(self.temp_dir, 'garment.png')
        img.save(path)
        return path

    def test_fails_without_any_confirmed_anchors(self):
        path = self._save_image()
        result = self.fit(path, {}, 'dress')
        self.assertFalse(result['fitted'],
                         "Must NOT fit without confirmed anchors")
        self.assertIn('errors', result['fit_report'])
        any_error = ' '.join(result['fit_report']['errors'])
        self.assertIn('confirmed', any_error.lower())

    def test_fails_with_empty_confirmed_anchors(self):
        path = self._save_image()
        result = self.fit(path, {}, 'dress', options={
            'confirmed_anchors': {},
        })
        self.assertFalse(result['fitted'])
        self.assertIn('errors', result['fit_report'])

    def test_succeeds_with_valid_confirmed_anchors(self):
        path = self._save_image()
        result = self.fit(path, {'garment_anchors': {'dress': _dress_rig_anchors()}},
                          'dress', options={
                              'confirmed_anchors': _dress_confirmed_anchors(),
                              'validate': False,
                          })
        self.assertTrue(result['fitted'],
                        "Should fit with valid confirmed anchors")


# ── Test: dress requires waist and hem anchors ──────────────────────────────

class TestDressRequiredAnchors(unittest.TestCase):
    """Dress requires waist and hem anchors, not only neck/shoulders."""

    def setUp(self):
        from compiler.fit_pipeline import fit_garment
        from compiler.garment_anchors import REQUIRED_CONFIRMED_ANCHORS
        self.fit = fit_garment
        self.required = REQUIRED_CONFIRMED_ANCHORS
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _save_image(self):
        path = os.path.join(self.temp_dir, 'garment.png')
        _make_dress_img().save(path)
        return path

    def test_dress_requires_waist_and_hem(self):
        required = self.required.get('dress', [])
        self.assertIn('waist_left', required)
        self.assertIn('waist_right', required)
        self.assertIn('hem_left', required)
        self.assertIn('hem_right', required)

    def test_fails_without_waist_anchors(self):
        path = self._save_image()
        anchors = _dress_confirmed_anchors()
        del anchors['waist_left']
        del anchors['waist_right']
        result = self.fit(path, {'garment_anchors': {'dress': _dress_rig_anchors()}},
                          'dress', options={
                              'confirmed_anchors': anchors,
                              'validate': False,
                          })
        self.assertFalse(result['fitted'])
        errors = ' '.join(result['fit_report'].get('errors', []))
        self.assertIn('waist', errors.lower())

    def test_fails_without_hem_anchors(self):
        path = self._save_image()
        anchors = _dress_confirmed_anchors()
        del anchors['hem_left']
        del anchors['hem_right']
        result = self.fit(path, {'garment_anchors': {'dress': _dress_rig_anchors()}},
                          'dress', options={
                              'confirmed_anchors': anchors,
                              'validate': False,
                          })
        self.assertFalse(result['fitted'])
        errors = ' '.join(result['fit_report'].get('errors', []))
        self.assertIn('hem', errors.lower())

    def test_neck_shoulders_alone_are_insufficient(self):
        """Dress must NOT succeed with only neck+shoulders."""
        path = self._save_image()
        anchors = {
            'neck': [384, 170],
            'left_shoulder': [304, 250],
            'right_shoulder': [472, 250],
        }
        result = self.fit(path, {'garment_anchors': {'dress': _dress_rig_anchors()}},
                          'dress', options={
                              'confirmed_anchors': anchors,
                              'validate': False,
                          })
        self.assertFalse(result['fitted'],
                         "Dress must not fit with only neck+shoulders")


# ── Test: bad anchors are not saved as reusable anchors.json ────────────────

class TestAnchorsNotSavedOnFailedFit(unittest.TestCase):
    """If fitting fails, anchors.json must NOT be written."""

    def setUp(self):
        from compiler.fit_pipeline import fit_garment
        self.fit = fit_garment
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_no_sidecar_on_failed_fit(self):
        path = os.path.join(self.temp_dir, 'garment.png')
        _make_dress_img().save(path)
        out_dir = os.path.join(self.temp_dir, 'output')

        # Fails because no confirmed anchors
        result = self.fit(path, {}, 'dress', output_dir=out_dir)
        self.assertFalse(result['fitted'])

        sidecar = os.path.join(out_dir, 'anchors.json')
        self.assertFalse(os.path.exists(sidecar),
                         "anchors.json must not exist after failed fit")

    def test_anchors_saved_only_on_successful_fit(self):
        path = os.path.join(self.temp_dir, 'garment.png')
        _make_dress_img().save(path)
        out_dir = os.path.join(self.temp_dir, 'output')

        result = self.fit(path,
                          {'garment_anchors': {'dress': _dress_rig_anchors()}},
                          'dress',
                          output_dir=out_dir,
                          options={
                              'confirmed_anchors': _dress_confirmed_anchors(),
                              'validate': False,
                          })
        self.assertTrue(result['fitted'])

        sidecar = os.path.join(out_dir, 'anchors.json')
        self.assertTrue(os.path.exists(sidecar),
                        "anchors.json should exist after successful fit")
        with open(sidecar) as f:
            data = json.load(f)
        self.assertTrue(data.get('confirmed'),
                        "Saved anchors must be marked confirmed")

    def test_sidecar_not_written_for_invalid_confirmed_set(self):
        path = os.path.join(self.temp_dir, 'garment.png')
        _make_dress_img().save(path)
        out_dir = os.path.join(self.temp_dir, 'output')

        # Missing required hem anchors
        anchors = _dress_confirmed_anchors()
        del anchors['hem_left']
        del anchors['hem_right']

        result = self.fit(path,
                          {'garment_anchors': {'dress': _dress_rig_anchors()}},
                          'dress',
                          output_dir=out_dir,
                          options={
                              'confirmed_anchors': anchors,
                              'validate': False,
                          })
        self.assertFalse(result['fitted'])

        sidecar = os.path.join(out_dir, 'anchors.json')
        self.assertFalse(os.path.exists(sidecar),
                         "anchors.json must not exist when required anchors missing")


# ── Test: existing warp tests still work with confirmed anchors ─────────────

class TestWarpFitWithConfirmedAnchors(unittest.TestCase):
    """Affine and piecewise warp produce valid output with confirmed anchors."""

    def setUp(self):
        from compiler.warp_fit import (
            fit_garment_affine, fit_garment_piecewise,
            estimate_affine_matrix, apply_affine_warp,
        )
        self.fit_affine = fit_garment_affine
        self.fit_piecewise = fit_garment_piecewise
        self.estimate_affine = estimate_affine_matrix
        self.apply_affine = apply_affine_warp

    def test_affine_warp_produces_valid_output(self):
        img = _make_dress_img()
        anchors = _dress_confirmed_anchors()
        rig = _dress_rig_anchors()
        warped = self.fit_affine(img, anchors, rig,
                                 ['neck', 'waist_left', 'waist_right',
                                  'hem_left', 'hem_right'])
        self.assertEqual(warped.size, (768, 768))
        self.assertEqual(warped.mode, 'RGBA')
        self.assertIsNotNone(warped.getbbox())

    def test_piecewise_warp_produces_valid_output(self):
        img = _make_dress_img()
        anchors = _dress_confirmed_anchors()
        rig = _dress_rig_anchors()
        warped = self.fit_piecewise(img, anchors, rig, 'dress')
        self.assertEqual(warped.size, (768, 768))
        self.assertIsNotNone(warped.getbbox())

    def test_affine_matrix_estimation(self):
        src_pts = [[0, 0], [100, 0], [0, 100], [100, 100]]
        dst_pts = [[10, 10], [110, 10], [10, 110], [110, 110]]
        matrix = self.estimate_affine(src_pts, dst_pts)
        self.assertIsNotNone(matrix)
        self.assertEqual(len(matrix), 6)

    def test_affine_matrix_translates_correctly(self):
        src_pts = [[0, 0], [100, 0], [0, 100]]
        dst_pts = [[50, 50], [150, 50], [50, 150]]
        matrix = self.estimate_affine(src_pts, dst_pts)
        self.assertIsNotNone(matrix)
        warped = self.apply_affine(
            Image.new('RGBA', (200, 200), (255, 0, 0, 255)),
            matrix, (200, 200),
        )
        self.assertEqual(warped.size, (200, 200))

    def test_insufficient_points_fallback(self):
        img = Image.new('RGBA', (768, 768), (255, 0, 0, 255))
        anchors = {'neck': [384, 180]}
        rig = {'neck': [384, 180]}
        warped = self.fit_affine(img, anchors, rig, ['neck'])
        self.assertEqual(warped.size, (768, 768))


# ── Test: fit validation with region path ───────────────────────────────────

class TestFitValidationWithRegionPath(unittest.TestCase):
    """validate_fit accepts any region path (body_silhouette or category-specific)."""

    def setUp(self):
        from compiler.fit_validation import validate_fit
        self.validate = validate_fit
        self.temp_dir = tempfile.mkdtemp()

        self.region_path = os.path.join(self.temp_dir, 'region.png')
        region = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        draw = ImageDraw.Draw(region)
        draw.ellipse([300, 200, 468, 600], fill=(255, 255, 255, 255))
        region.save(self.region_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_perfect_overlap_high_iou(self):
        img = Image.open(self.region_path)
        report = self.validate(img, self.region_path)
        self.assertGreater(report['iou'], 0.9)

    def test_no_overlap_low_iou(self):
        img = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 50, 50], fill=(255, 0, 0, 255))
        report = self.validate(img, self.region_path)
        self.assertLess(report['iou'], 0.15)

    def test_empty_garment_invalid(self):
        img = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        report = self.validate(img, self.region_path)
        self.assertFalse(report['valid'])

    def test_missing_region_file(self):
        img = Image.new('RGBA', (768, 768), (255, 0, 0, 255))
        report = self.validate(img, '/nonexistent/path/region.png')
        self.assertTrue(report['valid'])
        self.assertIn('warnings', report)

    def test_excellent_fit_quality(self):
        img = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([300, 200, 468, 600], fill=(255, 0, 0, 255))
        report = self.validate(img, self.region_path)
        self.assertEqual(report['fit_quality'], 'excellent')


# ── Test: STABLE_ANCHORS and REQUIRED_CONFIRMED_ANCHORS definitions ─────────

class TestAnchorDefinitions(unittest.TestCase):
    """Ensure the new constants match rig.json."""

    def setUp(self):
        from compiler.garment_anchors import (
            STABLE_ANCHORS, REQUIRED_CONFIRMED_ANCHORS, CATEGORY_ANCHOR_MAP,
        )
        self.stable = STABLE_ANCHORS
        self.required_confirmed = REQUIRED_CONFIRMED_ANCHORS
        self.full_map = CATEGORY_ANCHOR_MAP

        rig_path = os.path.join(PROJECT_ROOT, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            self.rig = json.load(f)

    def test_dress_stable_includes_straps_and_bust(self):
        stable = self.stable.get('dress', [])
        for name in ('strap_left', 'strap_right', 'bust_left', 'bust_right'):
            self.assertIn(name, stable)

    def test_dress_stable_in_rig_json(self):
        dress_rig = self.rig.get('garment_anchors', {}).get('dress', {})
        for name in ('strap_left', 'strap_right', 'bust_left', 'bust_right',
                     'waist_left', 'waist_right', 'hem_left', 'hem_right'):
            self.assertIn(name, dress_rig,
                          f"rig.json dress missing anchor: {name}")

    def test_required_confirmed_matches_stable(self):
        for cat in ('dress', 'topwear', 'skirt', 'pants', 'legwear', 'outerwear'):
            required = self.required_confirmed.get(cat, [])
            stable = self.stable.get(cat, [])
            for name in required:
                self.assertIn(name, stable,
                              f"{cat}: {name} is required but not in stable set")

    def test_all_stable_anchors_exist_in_rig(self):
        for cat, names in self.stable.items():
            rig_cat = self.rig.get('garment_anchors', {}).get(cat, {})
            for name in names:
                self.assertIn(name, rig_cat,
                              f"rig.json {cat} missing stable anchor: {name}")


# ── Test: end-to-end fitting pipeline with confirmed anchors ────────────────

class TestEndToEndWithConfirmedAnchors(unittest.TestCase):
    """Fit pipeline end-to-end with user-confirmed anchor flow."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.masks_dir = os.path.join(self.temp_dir, 'base_rig', 'masks')
        os.makedirs(self.masks_dir, exist_ok=True)

        # Body silhouette for validation
        sil = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sil)
        draw.ellipse([300, 150, 468, 650], fill=(255, 255, 255, 255))
        sil.save(os.path.join(self.masks_dir, 'body_silhouette.png'))

        # Create rig.json
        _make_fake_rig_json(os.path.join(self.temp_dir, 'base_rig', 'rig.json'))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _make_garment_png(self, name="garment.png"):
        path = os.path.join(self.temp_dir, name)
        _make_dress_img().save(path)
        return path

    def test_pipeline_with_confirmed_anchors(self):
        from compiler.fit_pipeline import fit_garment
        path = self._make_garment_png()
        rig_path = os.path.join(self.temp_dir, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            rig = json.load(f)

        result = fit_garment(
            path, rig, 'dress',
            output_dir=os.path.join(self.temp_dir, 'output'),
            options={
                'confirmed_anchors': _dress_confirmed_anchors(),
                'validate': True,
                'body_silhouette_path': os.path.join(
                    self.masks_dir, 'body_silhouette.png',
                ),
            },
        )
        self.assertTrue(result['fitted'])
        self.assertIsNotNone(result['fitted_image'])
        self.assertIn('fit_report', result)
        self.assertIn('output_paths', result)
        self.assertIn('fitted', result['output_paths'])

    def test_pipeline_rejects_empty_confirmed(self):
        from compiler.fit_pipeline import fit_garment
        path = self._make_garment_png()
        rig_path = os.path.join(self.temp_dir, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            rig = json.load(f)

        result = fit_garment(path, rig, 'dress')
        self.assertFalse(result['fitted'])
        self.assertIn('errors', result['fit_report'])

    def test_pipeline_output_files(self):
        from compiler.fit_pipeline import fit_garment
        path = self._make_garment_png()
        rig_path = os.path.join(self.temp_dir, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            rig = json.load(f)

        out_dir = os.path.join(self.temp_dir, 'output')
        result = fit_garment(
            path, rig, 'dress',
            output_dir=out_dir,
            options={
                'confirmed_anchors': _dress_confirmed_anchors(),
                'asset_id': 'test_dress',
                'validate': False,
            },
        )
        for key in ('fitted', 'thumbnail', 'overlay', 'report', 'anchors'):
            self.assertIn(key, result['output_paths'],
                          f"Missing output path: {key}")
            self.assertTrue(
                os.path.exists(result['output_paths'][key]),
                f"Output file not found: {result['output_paths'][key]}",
            )

    def test_pipeline_affine_method(self):
        from compiler.fit_pipeline import fit_garment
        path = self._make_garment_png()
        rig_path = os.path.join(self.temp_dir, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            rig = json.load(f)

        result = fit_garment(path, rig, 'dress', options={
            'method': 'affine',
            'confirmed_anchors': _dress_confirmed_anchors(),
            'validate': False,
        })
        self.assertTrue(result['fitted'])

    def test_pipeline_saves_sidecar_on_success(self):
        from compiler.fit_pipeline import fit_garment
        path = self._make_garment_png()
        rig_path = os.path.join(self.temp_dir, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            rig = json.load(f)

        out_dir = os.path.join(self.temp_dir, 'output')
        result = fit_garment(
            path, rig, 'dress',
            output_dir=out_dir,
            options={
                'confirmed_anchors': _dress_confirmed_anchors(),
                'validate': False,
            },
        )
        self.assertTrue(result['fitted'])
        sidecar = os.path.join(out_dir, 'anchors.json')
        self.assertTrue(os.path.exists(sidecar))
        with open(sidecar) as f:
            data = json.load(f)
        self.assertTrue(data.get('confirmed'))


class TestFitGarmentRefusesSuggestedOnly(unittest.TestCase):
    """fit_garment must refuse anchors wrapped in {'suggested': ...}."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._make_base_rig()

    def _make_base_rig(self):
        rig_dir = os.path.join(self.temp_dir, 'base_rig')
        masks_dir = os.path.join(rig_dir, 'masks')
        os.makedirs(masks_dir, exist_ok=True)
        sil = Image.new('L', (768, 768), 255)
        sil_img = Image.merge('RGBA', (sil, sil, sil, sil))
        sil_img.save(os.path.join(masks_dir, 'body_silhouette.png'), 'PNG')
        for name in ('dress', 'topwear', 'top', 'skirt', 'pants', 'legwear', 'outerwear'):
            mask = sil_img.copy()
            mask.save(os.path.join(masks_dir, f'{name}_allowed_region.png'), 'PNG')
        rig = {
            'canvas': [768, 768],
            'anchors': {
                'neck': [384, 180],
                'left_shoulder': [304, 250],
                'right_shoulder': [472, 250],
                'waist_left': [318, 420],
                'waist_right': [446, 420],
                'hip_left': [300, 440],
                'hip_right': [468, 440],
                'knee_left': [296, 540],
                'knee_right': [472, 540],
                'hem_left': [280, 620],
                'hem_right': [488, 620],
            },
            'garment_anchors': {
                cat: {} for cat in ('dress', 'topwear', 'top', 'skirt', 'pants', 'legwear', 'outerwear')
            },
        }
        with open(os.path.join(rig_dir, 'rig.json'), 'w') as f:
            json.dump(rig, f)

    def _make_garment_png(self, size=(768, 768)):
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        for y in range(100, 600):
            for x in range(100, 668):
                img.putpixel((x, y), (100, 100, 200, 255))
        path = os.path.join(self.temp_dir, 'garment.png')
        img.save(path, 'PNG')
        return path

    def test_rejects_suggested_only_wrapper(self):
        """Anchors passed as {'suggested': {neck: [...], ...}} must be rejected."""
        from compiler.fit_pipeline import fit_garment
        path = self._make_garment_png()
        rig_path = os.path.join(self.temp_dir, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            rig = json.load(f)
        result = fit_garment(
            path, rig, 'dress',
            options={
                'confirmed_anchors': {
                    'suggested': {
                        'neck': [384, 180],
                        'waist_left': [318, 420],
                        'waist_right': [446, 420],
                        'hem_left': [280, 620],
                        'hem_right': [488, 620],
                    },
                },
            },
        )
        self.assertFalse(result['fitted'])

    def test_fitted_category_does_not_save_raw_on_fit_failure(self):
        """When fit fails (no confirmed anchors), no sidecar and raw image not saved."""
        from compiler.fit_pipeline import fit_garment
        path = self._make_garment_png()
        rig_path = os.path.join(self.temp_dir, 'base_rig', 'rig.json')
        with open(rig_path) as f:
            rig = json.load(f)
        out_dir = os.path.join(self.temp_dir, 'out_fail')
        result = fit_garment(
            path, rig, 'dress',
            output_dir=out_dir,
            options={},
        )
        self.assertFalse(result['fitted'])
        self.assertIsNone(result.get('fitted_image'))
        sidecar = os.path.join(out_dir, 'anchors.json')
        self.assertFalse(os.path.exists(sidecar))


class TestValidateAssetUsesCategoryAllowedRegion(unittest.TestCase):
    """validate_asset must use category-specific allowed region for fitted cats."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.masks_dir = os.path.join(self.temp_dir, 'masks')
        os.makedirs(self.masks_dir, exist_ok=True)
        # body_silhouette — tight around torso (no flare)
        sil = Image.new('L', (768, 768), 0)
        for y in range(200, 440):
            for x in range(300, 468):
                sil.putpixel((x, y), 255)
        sil_img = Image.merge('RGBA', (sil, sil, sil, sil))
        sil_img.save(os.path.join(self.masks_dir, 'body_silhouette.png'), 'PNG')

        # dress_allowed_region — wider to allow flared skirt
        dress = Image.new('L', (768, 768), 0)
        for y in range(200, 650):
            for x in range(200, 568):
                dress.putpixel((x, y), 255)
        dress_img = Image.merge('RGBA', (dress, dress, dress, dress))
        dress_img.save(os.path.join(self.masks_dir, 'dress_allowed_region.png'), 'PNG')

        # hair_forbidden_region — empty for these tests
        hair = Image.new('L', (768, 768), 0)
        hair_img = Image.merge('RGBA', (hair, hair, hair, hair))
        hair_img.save(os.path.join(self.masks_dir, 'hair_forbidden_region.png'), 'PNG')

        # rig.json
        rig = {'canvas': [768, 768]}
        with open(os.path.join(self.temp_dir, 'rig.json'), 'w') as f:
            json.dump(rig, f)

    def _flare_dress(self):
        """Create a flared dress that extends outside body_silhouette but inside dress_region."""
        img = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        # Narrow top (within body silhouette)
        for y in range(200, 350):
            for x in range(300, 468):
                img.putpixel((x, y), (100, 100, 200, 255))
        # Flared bottom (extends beyond body silhouette but within dress region)
        for y in range(350, 600):
            for x in range(220, 548):
                img.putpixel((x, y), (100, 100, 200, 255))
        return img

    def test_flared_dress_not_cropped_by_body_silhouette(self):
        """Flared dress pixels outside body_silhouette but inside dress_allowed_region are kept."""
        from compiler.validate_asset import validate_asset
        dress_img = self._flare_dress()
        cleaned, report = validate_asset(dress_img, 'dress', self.temp_dir)
        self.assertTrue(report['valid'])
        # Garment should still have flared pixels (not cropped to body silhouette)
        cleaned_pixels = sum(1 for p in cleaned.getchannel('A').tobytes() if p > 10)
        original_pixels = sum(1 for p in dress_img.getchannel('A').tobytes() if p > 10)
        # Should keep most of original pixels (>= 90%)
        self.assertGreaterEqual(cleaned_pixels / original_pixels, 0.90)

    def test_non_fitted_category_falls_back_to_body_silhouette(self):
        """A non-fitted category still uses body_silhouette and gets cropped."""
        from compiler.validate_asset import validate_asset

        # No allowed_region for this non-fitted category
        # A flared garment outside body silhouette should get cropped
        img = Image.new('RGBA', (768, 768), (0, 0, 0, 0))
        # Inside body silhouette
        for y in range(200, 350):
            for x in range(300, 468):
                img.putpixel((x, y), (100, 100, 200, 255))
        # Outside body silhouette flare
        for y in range(350, 450):
            for x in range(220, 548):
                img.putpixel((x, y), (100, 100, 200, 255))

        # Pass a category not in fitted set, with explicit crop enabled
        cleaned, report = validate_asset(img, 'shoe', self.temp_dir, crop_to_allowed_region=True)
        self.assertTrue(report['valid'])
        cleaned_pixels = sum(1 for p in cleaned.getchannel('A').tobytes() if p > 10)
        # Flare pixels outside body silhouette should be cropped
        self.assertLess(cleaned_pixels, sum(1 for p in img.getchannel('A').tobytes() if p > 10))

    def test_no_allowed_region_falls_back_to_body_silhouette(self):
        """When no category-specific mask exists, body_silhouette is used."""
        from compiler.validate_asset import validate_asset
        img = self._flare_dress()
        # Use a category that has no allowed region mask (e.g. 'bottomwear')
        cleaned, report = validate_asset(img, 'bottomwear', self.temp_dir, crop_to_allowed_region=True)
        self.assertTrue(report['valid'])
        # Since there's no bottomwear_allowed_region, body_silhouette is used,
        # which is tighter — flare pixels should be cropped.
        cleaned_pixels = sum(1 for p in cleaned.getchannel('A').tobytes() if p > 10)
        original_pixels = sum(1 for p in img.getchannel('A').tobytes() if p > 10)
        self.assertLess(cleaned_pixels, original_pixels)


if __name__ == '__main__':
    unittest.main()
