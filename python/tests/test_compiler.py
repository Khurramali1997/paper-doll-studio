import os
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PIL import Image


class TestSchemaValidation(unittest.TestCase):
    """Test project.json schema validation."""

    def setUp(self):
        self.valid_project = {
            "version": 1,
            "canvas": {"width": 768, "height": 768},
            "layers": [
                {"id": "hair_back", "name": "hair_back", "file": "hair_back.png",
                 "z": 10, "category": "hair", "subcategory": "hair_back",
                 "toggleable": True, "defaultVisible": True, "dyeable": True},
                {"id": "body_face", "name": "body_face", "file": "body_face.png",
                 "z": 50, "category": "face", "subcategory": "face"},
            ],
            "wardrobe": {
                "topwear": {
                    "name": "Topwear",
                    "defaultValue": "skin_wear",
                    "options": [
                        {"value": "skin_wear", "name": "Naked / Skin Wear", "layers": ["skin_wear_top"]},
                        {"value": "none", "name": "Invisible / None", "layers": []},
                    ],
                },
            },
        }

    def test_required_fields_present(self):
        self.assertIn("version", self.valid_project)
        self.assertIn("canvas", self.valid_project)
        self.assertIn("layers", self.valid_project)
        self.assertIn("wardrobe", self.valid_project)

    def test_valid_canvas_dimensions(self):
        self.assertGreater(self.valid_project["canvas"]["width"], 0)
        self.assertGreater(self.valid_project["canvas"]["height"], 0)

    def test_layers_have_required_fields(self):
        for layer in self.valid_project["layers"]:
            self.assertIn("id", layer)
            self.assertIn("name", layer)
            self.assertIn("file", layer)
            self.assertIn("z", layer)
            self.assertIn("category", layer)

    def test_valid_categories(self):
        valid_cats = {"hair", "eyes", "face", "wardrobe"}
        for layer in self.valid_project["layers"]:
            self.assertIn(layer["category"], valid_cats)

    def test_unique_layer_ids(self):
        ids = [l["id"] for l in self.valid_project["layers"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_layer_id_format(self):
        import re
        for layer in self.valid_project["layers"]:
            self.assertTrue(re.match(r'^[a-z0-9_]+$', layer["id"]))

    def test_wardrobe_options_exist(self):
        for slot_name, slot in self.valid_project["wardrobe"].items():
            self.assertIn("options", slot)
            self.assertGreater(len(slot["options"]), 0)


class TestCanvasNormalization(unittest.TestCase):
    """Test normalize_canvas function."""

    def setUp(self):
        from compiler.normalize_canvas import normalize_canvas
        self.normalize_canvas = normalize_canvas

    def test_same_size_returns_original(self):
        img = Image.new("RGBA", (768, 768))
        result = self.normalize_canvas(img, (768, 768))
        self.assertEqual(result.size, (768, 768))

    def test_smaller_image_gets_centered(self):
        from PIL import ImageDraw
        img = Image.new("RGBA", (384, 384), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([100, 100, 200, 200], fill=(255, 0, 0, 255))
        result = self.normalize_canvas(img, (768, 768))
        self.assertEqual(result.size, (768, 768))
        # Content should be centered (non-transparent pixels exist)
        bbox = result.getbbox()
        self.assertIsNotNone(bbox)

    def test_larger_image_gets_scaled_down(self):
        img = Image.new("RGBA", (1536, 1536))
        result = self.normalize_canvas(img, (768, 768))
        self.assertEqual(result.size, (768, 768))

    def test_non_rgba_converted_to_rgba(self):
        img = Image.new("RGB", (768, 768), (255, 0, 0))
        result = self.normalize_canvas(img, (768, 768))
        self.assertEqual(result.mode, "RGBA")


class TestAssetValidation(unittest.TestCase):
    """Test validate_asset with simulated rig data."""

    def setUp(self):
        # Create a temp directory structure mimicking base_rig
        self.temp_dir = tempfile.mkdtemp()
        masks_dir = os.path.join(self.temp_dir, "masks")
        os.makedirs(masks_dir, exist_ok=True)

        # Create rig.json
        with open(os.path.join(self.temp_dir, "rig.json"), "w") as f:
            json.dump({"canvas": [768, 768]}, f)

        # Create an empty face mask (all transparent -> no overlap)
        face_mask = Image.new("RGBA", (768, 768), (0, 0, 0, 0))
        face_mask.save(os.path.join(masks_dir, "face_forbidden_region.png"))

        # Create body silhouette (all transparent -> no garbage)
        sil = Image.new("RGBA", (768, 768), (0, 0, 0, 0))
        sil.save(os.path.join(masks_dir, "body_silhouette.png"))

        # Create hair region (all transparent)
        hair = Image.new("RGBA", (768, 768), (0, 0, 0, 0))
        hair.save(os.path.join(masks_dir, "hair_forbidden_region.png"))

        self.base_rig_dir = self.temp_dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_valid_garment_passes(self):
        from compiler.validate_asset import validate_asset
        img = Image.new("RGBA", (768, 768), (0, 0, 0, 0))
        # Draw a small garment shape
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([200, 200, 400, 400], fill=(255, 0, 0, 255))

        cleaned, report = validate_asset(img, "topwear", self.base_rig_dir)
        self.assertTrue(report["valid"])

    def test_empty_garment_fails(self):
        from compiler.validate_asset import validate_asset
        img = Image.new("RGBA", (768, 768), (0, 0, 0, 0))
        cleaned, report = validate_asset(img, "topwear", self.base_rig_dir)
        self.assertFalse(report["valid"])

    def test_wrong_size_fails(self):
        from compiler.validate_asset import validate_asset
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        cleaned, report = validate_asset(img, "topwear", self.base_rig_dir)
        self.assertFalse(report["valid"])


class TestZOrderSorting(unittest.TestCase):
    """Test z-order sorting logic."""

    def test_basic_sorting(self):
        layers = [
            {"id": "a", "z": 30},
            {"id": "b", "z": 10},
            {"id": "c", "z": 20},
        ]
        sorted_layers = sorted(layers, key=lambda l: l["z"])
        self.assertEqual([l["id"] for l in sorted_layers], ["b", "c", "a"])

    def test_z_increments(self):
        indices = list(range(5))
        z_values = [(i + 1) * 10 for i in indices]
        self.assertEqual(z_values, [10, 20, 30, 40, 50])

    def test_equal_z_stability(self):
        layers = [
            {"id": "x", "z": 10},
            {"id": "y", "z": 10},
        ]
        sorted_layers = sorted(layers, key=lambda l: l["z"])
        self.assertEqual(sorted_layers[0]["id"], "x")
        self.assertEqual(sorted_layers[1]["id"], "y")


class TestSplitSlots(unittest.TestCase):
    """Test split_slots for garment layer splitting."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        masks_dir = os.path.join(self.temp_dir, "masks")
        os.makedirs(masks_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_non_upper_body_returns_single_layer(self):
        from compiler.split_slots import split_slots
        img = Image.new("RGBA", (768, 768), (255, 0, 0, 255))
        result = split_slots(img, "legwear", self.temp_dir)
        self.assertIn("clothing_front", result)
        self.assertEqual(len(result), 1)

    def test_missing_mask_returns_single_layer(self):
        from compiler.split_slots import split_slots
        img = Image.new("RGBA", (768, 768), (255, 0, 0, 255))
        result = split_slots(img, "topwear", self.temp_dir)
        # No arm mask exists, so returns single layer
        self.assertIn("clothing_front", result)


class TestCompileAssetFailFast(unittest.TestCase):
    """Fitted categories must raise ValueError on fit failure, no output written."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.rig_dir = os.path.join(self.temp_dir, "base_rig")
        self.masks_dir = os.path.join(self.rig_dir, "masks")
        os.makedirs(self.masks_dir, exist_ok=True)

        # body_silhouette
        sil = Image.new("L", (768, 768), 255)
        sil_img = Image.merge("RGBA", (sil, sil, sil, sil))
        sil_img.save(os.path.join(self.masks_dir, "body_silhouette.png"))

        # hair_forbidden_region
        hair = Image.new("L", (768, 768), 0)
        hair_img = Image.merge("RGBA", (hair, hair, hair, hair))
        hair_img.save(os.path.join(self.masks_dir, "hair_forbidden_region.png"))

        # face_forbidden_region
        face = Image.new("L", (768, 768), 0)
        face_img = Image.merge("RGBA", (face, face, face, face))
        face_img.save(os.path.join(self.masks_dir, "face_forbidden_region.png"))

        # allowed region masks for all fitted cats
        for name in ("dress", "topwear", "top", "skirt", "pants", "legwear", "outerwear"):
            mask = sil_img.copy()
            mask.save(os.path.join(self.masks_dir, f"{name}_allowed_region.png"))

        # rig.json with garment_anchors
        rig = {
            "canvas": [768, 768],
            "anchors": {
                "neck": [384, 180],
                "left_shoulder": [304, 250],
                "right_shoulder": [472, 250],
                "waist_left": [318, 420],
                "waist_right": [446, 420],
                "hip_left": [300, 440],
                "hip_right": [468, 440],
            },
            "garment_anchors": {
                "dress": {
                    "neck": [384, 180],
                    "waist_left": [318, 420],
                    "waist_right": [446, 420],
                    "hem_left": [280, 620],
                    "hem_right": [488, 620],
                },
            },
        }
        with open(os.path.join(self.rig_dir, "rig.json"), "w") as f:
            json.dump(rig, f)

        # Input garment
        self.input_path = os.path.join(self.temp_dir, "garment.png")
        img = Image.new("RGBA", (768, 768), (0, 0, 0, 0))
        for y in range(100, 600):
            for x in range(100, 668):
                img.putpixel((x, y), (100, 100, 200, 255))
        img.save(self.input_path, "PNG")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_dress_piecewise_no_confirmed_anchors_raises(self):
        """dress + enable_fit + fit_method=piecewise + no confirmed_anchors must raise."""
        from compiler.compiler import AssetCompiler
        output_dir = os.path.join(self.temp_dir, "compiled")
        compiler = AssetCompiler(base_rig_dir=self.rig_dir, output_dir=output_dir)
        with self.assertRaises(ValueError) as ctx:
            compiler.compile_asset(
                self.input_path, "dress",
                options={"enable_fit": True, "fit_method": "piecewise"},
            )
        self.assertIn("confirmed", str(ctx.exception).lower())

    def test_dress_fit_failure_writes_no_metadata(self):
        """No metadata.json or manifest entry written after fit failure."""
        from compiler.compiler import AssetCompiler
        output_dir = os.path.join(self.temp_dir, "compiled")
        compiler = AssetCompiler(base_rig_dir=self.rig_dir, output_dir=output_dir)
        try:
            compiler.compile_asset(
                self.input_path, "dress",
                options={
                    "asset_id": "test_dress",
                    "enable_fit": True,
                    "fit_method": "piecewise",
                },
            )
        except ValueError:
            pass

        # No metadata.json should exist
        meta_path = os.path.join(output_dir, "dress", "test_dress", "metadata.json")
        self.assertFalse(os.path.exists(meta_path),
                         "metadata.json must not be written after fit failure")

        # No manifest update
        manifest_path = os.path.join(output_dir, "..", "wardrobe_manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            ids = [e["asset_id"] for e in manifest]
            self.assertNotIn("test_dress", ids,
                             "manifest must not contain entry for failed fit")

    def test_dress_fit_method_none_does_not_raise(self):
        """dress + fit_method=none skips fit and does not raise."""
        from compiler.compiler import AssetCompiler
        output_dir = os.path.join(self.temp_dir, "compiled")
        compiler = AssetCompiler(base_rig_dir=self.rig_dir, output_dir=output_dir)
        try:
            result = compiler.compile_asset(
                self.input_path, "dress",
                options={
                    "asset_id": "none_fit_dress",
                    "fit_method": "none",
                },
            )
        except ValueError:
            self.fail("compile_asset raised ValueError with fit_method=none")
        self.assertIsNotNone(result)
        self.assertFalse(result.get("fit", {}).get("applied", False))

    def test_dress_compile_outputs_all_expected_files(self):
        """Compiled dress produces metadata.json, preview.png, layer PNGs,
        fit_debug/anchors.json, and manifest entry."""
        from compiler.compiler import AssetCompiler

        asset_id = "regression_test_dress"
        output_dir = os.path.join(self.temp_dir, "compiled")

        compiler = AssetCompiler(base_rig_dir=self.rig_dir, output_dir=output_dir)

        # Compile with valid confirmed anchors (experimental fit path)
        result = compiler.compile_asset(
            self.input_path, "dress",
            options={
                "asset_id": asset_id,
                "enable_fit": True,
                "fit_method": "piecewise",
                "confirmed_anchors": {
                    "neck": [384, 180],
                    "waist_left": [318, 420],
                    "waist_right": [446, 420],
                    "hem_left": [280, 620],
                    "hem_right": [488, 620],
                },
                "remove_bg": False,
                "crop_to_allowed_region": False,
            },
        )

        # 1. metadata.json exists and has correct category
        meta_path = os.path.join(output_dir, "dress", asset_id, "metadata.json")
        self.assertTrue(os.path.exists(meta_path),
                        "metadata.json must exist after successful compile")
        with open(meta_path) as f:
            meta = json.load(f)
        self.assertEqual(meta["category"], "dress")
        self.assertEqual(meta["asset_id"], asset_id)

        # 2. preview.png exists
        preview_path = os.path.join(output_dir, "dress", asset_id, "preview.png")
        self.assertTrue(os.path.exists(preview_path),
                        "preview.png must exist")

        # 3. At least one compiled layer PNG exists
        pack_dir = os.path.join(output_dir, "dress", asset_id)
        layer_files = [f for f in os.listdir(pack_dir)
                       if f.endswith('.png') and f != 'preview.png'
                       and not f.startswith('preview_')]
        self.assertGreater(len(layer_files), 0,
                           f"Expected at least one layer PNG in {pack_dir}, found: {layer_files}")
        # Verify the layer file is a valid PNG
        layer_path = os.path.join(pack_dir, layer_files[0])
        layer_img = Image.open(layer_path)
        self.assertEqual(layer_img.mode, "RGBA")

        # 4. fit_debug/anchors.json exists with confirmed:true
        anchors_path = os.path.join(pack_dir, "fit_debug", "anchors.json")
        self.assertTrue(os.path.exists(anchors_path),
                        "fit_debug/anchors.json must exist")
        with open(anchors_path) as f:
            anchors = json.load(f)
        self.assertTrue(anchors.get("confirmed", False),
                        "anchors.json must have confirmed: true")

        # 5. Result metadata includes fit_report with fit info
        self.assertTrue(result.get("fit", {}).get("applied", False))
        self.assertIn("fit_quality", result.get("fit", {}).get("report", {}))

        # 6. Compiler also writes to project-level manifest (side effect)
        #    Clean up the manifest entry after verifying
        project_manifest = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "public", "assets", "wardrobe_manifest.json",
        )
        if os.path.exists(project_manifest):
            with open(project_manifest) as f:
                manifest_before = json.load(f)
            ids_before = [e["asset_id"] for e in manifest_before]
            self.assertIn(asset_id, ids_before,
                          "manifest must contain entry for compiled dress")
            # Restore manifest to pre-test state
            manifest_after = [e for e in manifest_before if e["asset_id"] != asset_id]
            with open(project_manifest, "w") as f:
                json.dump(manifest_after, f, indent=2)

        # 7. preview_stage images exist (raw, cleaned, fitted)
        for stage in ("preview_raw", "preview_cleaned", "preview_fitted"):
            stage_path = os.path.join(pack_dir, f"{stage}.png")
            self.assertTrue(os.path.exists(stage_path),
                            f"{stage}.png must exist")


if __name__ == "__main__":
    unittest.main()
