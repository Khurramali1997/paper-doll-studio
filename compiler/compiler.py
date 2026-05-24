#!/usr/bin/env python3
import os
import json
import re
from PIL import Image, ImageChops

from compiler.category_registry import is_fitted as _cat_is_fitted
from compiler.normalize_canvas import normalize_canvas
from compiler.align_asset import align_asset
from compiler.split_slots import split_slots
from compiler.validate_asset import validate_asset, has_alpha_channel
from compiler.fit_pipeline import fit_garment

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_RIG_DIR = os.path.join(PROJECT_ROOT, "base_rig")
COMPILED_ASSETS_DIR = os.path.join(PROJECT_ROOT, "public", "assets", "compiled")
MANIFEST_PATH = os.path.join(PROJECT_ROOT, "public", "assets", "wardrobe_manifest.json")

def parse_hex_color(hex_str: str) -> tuple[int, int, int]:
    """Parse color hex string to RGB tuple."""
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 3:
        hex_str = ''.join([c*2 for c in hex_str])
    if len(hex_str) != 6:
        return (255, 255, 255) # default white
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

def remove_background_chromakey(image: Image.Image, color_hex: str, tolerance: int) -> Image.Image:
    """Removes a chroma key background color using native Pillow differences."""
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    target_color = parse_hex_color(color_hex)
    
    r, g, b, a = image.split()
    tr, tg, tb = target_color
    
    diff_r = ImageChops.difference(r, Image.new("L", image.size, tr))
    diff_g = ImageChops.difference(g, Image.new("L", image.size, tg))
    diff_b = ImageChops.difference(b, Image.new("L", image.size, tb))
    
    # Max coordinate difference acts as a box-tolerance filter (very fast)
    max_diff = ImageChops.lighter(ImageChops.lighter(diff_r, diff_g), diff_b)
    
    # 255 where diff > tolerance (keep), 0 where diff <= tolerance (key out)
    mask = max_diff.point(lambda p: 255 if p > tolerance else 0)
    new_a = ImageChops.darker(a, mask)
    
    return Image.merge("RGBA", (r, g, b, new_a))

class AssetCompiler:
    def __init__(self, base_rig_dir=BASE_RIG_DIR, output_dir=COMPILED_ASSETS_DIR):
        self.base_rig_dir = base_rig_dir
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Load rig metadata
        self.rig_config = {}
        rig_json = os.path.join(self.base_rig_dir, "rig.json")
        if os.path.exists(rig_json):
            try:
                with open(rig_json, "r") as f:
                    self.rig_config = json.load(f)
            except Exception as e:
                print(f"Warning: Could not read rig.json: {e}")

    def compile_asset(self, input_image_path: str, category: str, options: dict) -> dict:
        """
        Compiles a raw garment image into a validated garment layer pack.
        
        Options dict:
          - x_offset: float (default 0)
          - y_offset: float (default 0)
          - scale: float (default 1.0)
          - remove_bg: bool (default True)
          - chromakey_color: str (default "#ffffff")
          - chromakey_tolerance: int (default 40)
          - asset_id: str (optional, auto-generated if omitted)
          - display_name: str (optional, auto-generated if omitted)
        """
        print(f"=== Compiling Garment Asset ===")
        print(f"Source: {input_image_path}")
        print(f"Category: {category}")
        
        # Load image
        img = Image.open(input_image_path).convert("RGBA")
        
        # 1. Clean Name and Asset ID
        display_name = options.get("display_name")
        if not display_name:
            basename = os.path.basename(input_image_path)
            name_no_ext = os.path.splitext(basename)[0]
            display_name = name_no_ext.replace("_", " ").replace("-", " ").title()
            
        asset_id = options.get("asset_id")
        if not asset_id:
            asset_id = re.sub(r'[^a-z0-9]+', '_', display_name.lower()).strip('_')
            
        # 2. Normalize Canvas to Rig Size
        pack_dir = os.path.join(self.output_dir, category, asset_id)
        os.makedirs(pack_dir, exist_ok=True)

        target_size = tuple(self.rig_config.get("canvas", [768, 768]))
        img = normalize_canvas(img, target_size)

        # Save raw (stage 0) preview
        img.save(os.path.join(pack_dir, "preview_raw.png"), "PNG")

        # 3. Background Removal (Chroma Key)
        # Auto-skip chroma key if source already has alpha channel
        source_has_alpha = has_alpha_channel(img)
        force_chromakey = options.get("force_chromakey", False)
        chromakey_applied = False

        if options.get("remove_bg", True):
            if source_has_alpha and not force_chromakey:
                print("Source image has alpha channel; skipping chroma key. "
                      "Use force_chromakey=True to override.")
            else:
                color = options.get("chromakey_color", "#ffffff")
                tolerance = options.get("chromakey_tolerance", 40)
                print(f"Removing background key {color} (tolerance: {tolerance})...")
                img = remove_background_chromakey(img, color, tolerance)
                chromakey_applied = True

        # Save cleaned (stage 1) preview — chroma key result or source if skipped
        img.save(os.path.join(pack_dir, "preview_cleaned.png"), "PNG")
            
        # 4. Decide alignment path: anchor-based fit_pipeline is OFF by default
        #    for v0.1. Manual placement + bake is the supported flow. Set
        #    options["enable_fit"]=True to opt into the experimental warp.
        fit_method = options.get("fit_method", "piecewise")
        enable_fit = options.get("enable_fit", False)
        is_fitted = enable_fit and fit_method != "none" and _cat_is_fitted(category)

        if not is_fitted:
            # Traditional alignment for non-fitted categories
            x_off = options.get("x_offset", 0.0)
            y_off = options.get("y_offset", 0.0)
            scale = options.get("scale", 1.0)
            img = align_asset(
                img,
                x_offset=x_off,
                y_offset=y_off,
                scale=scale,
                candidate_anchors=options.get("candidate_anchors"),
                rig_anchors=self.rig_config.get("anchors"),
            )
        else:
            # Fitted categories: skip align_asset entirely.
            # The fit_garment step is the single spatial transform.
            pass

        # 4b. Garment Fit (Anchor-Based Conformation)
        fit_report = {}
        fitted_anchors = {}

        if is_fitted:
            from compiler.fit_pipeline import fit_garment
            import tempfile

            fit_output_dir = os.path.join(
                self.output_dir, category, asset_id, "fit_debug"
            )

            # Accept confirmed_anchors from options OR sidecar
            confirmed_anchors = options.get("confirmed_anchors")
            if not confirmed_anchors:
                sidecar_path = os.path.join(fit_output_dir, "anchors.json")
                if os.path.exists(sidecar_path):
                    try:
                        with open(sidecar_path) as f:
                            data = json.load(f)
                        if data.get("confirmed") and data.get("garment_anchors"):
                            confirmed_anchors = data["garment_anchors"]
                            print(f"Loaded confirmed anchors from {sidecar_path}")
                    except Exception:
                        pass

            category_region_path = os.path.join(
                self.base_rig_dir, "masks", f"{category.lower()}_allowed_region.png",
            )
            if not os.path.exists(category_region_path):
                category_region_path = None

            fit_opts = {
                "method": fit_method,
                "asset_id": asset_id,
                "validate": True,
                "blend_radius": options.get("fit_blend_radius", 20),
                "allowed_region_path": category_region_path,
                "body_silhouette_path": os.path.join(
                    self.base_rig_dir, "masks", "body_silhouette.png",
                ),
                "confirmed_anchors": confirmed_anchors,
            }

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                img.save(tmp, "PNG")
                tmp_path = tmp.name

            try:
                fit_result = fit_garment(
                    input_image_path=tmp_path,
                    rig_config=self.rig_config,
                    category=category,
                    output_dir=fit_output_dir,
                    options=fit_opts,
                )
            finally:
                os.unlink(tmp_path)

            if fit_result.get("fitted") and fit_result["fitted_image"] is not None:
                img = fit_result["fitted_image"]

                # Save fitted (stage 2) preview
                img.save(os.path.join(pack_dir, "preview_fitted.png"), "PNG")

                fit_report = fit_result.get("fit_report", {})
                fitted_anchors = fit_result.get("garment_anchors", {})
                print(f"Garment fit applied: method={fit_method}, "
                      f"IoU={fit_report.get('iou', 'N/A')}, "
                      f"quality={fit_report.get('fit_quality', 'N/A')}")
                if fit_result.get("anchors_saved_to"):
                    print(f"Anchors saved to {fit_result['anchors_saved_to']}")

                if not fit_report.get("valid", True):
                    errors = fit_report.get("errors", fit_report.get("warnings", ["unknown fit error"]))
                    raise ValueError(f"Garment fit validation failed: {'; '.join(errors)}")
            else:
                errors = fit_result.get("fit_report", {}).get(
                    "errors", ["Fitting requires user-confirmed anchors."]
                )
                raise ValueError(f"Garment fit failed: {'; '.join(errors)}")
        else:
            # Non-fitted categories: save a placeholder fitted preview (same as cleaned)
            img.save(os.path.join(pack_dir, "preview_fitted.png"), "PNG")
        
        # 5. Validation (non-destructive by default for fitted categories)
        crop_to_allowed = options.get("crop_to_allowed_region", False)
        auto_clean_face = options.get("auto_clean_face", False)

        if is_fitted and not crop_to_allowed:
            print("Fitted category: allowed-region cropping disabled by default. "
                  "Enable crop_to_allowed_region=True to crop outside silhouette.")

        cleaned_img, report = validate_asset(
            img, category, self.base_rig_dir,
            crop_to_allowed_region=crop_to_allowed,
            auto_clean_face=auto_clean_face,
        )
        if not report["valid"]:
            print(f"Validation FAILED: {report['errors']}")
            raise ValueError(f"Garment validation failed: {'; '.join(report['errors'])}")
            
        # 6. Z-order Layer Splitting
        layers_map = split_slots(cleaned_img, category, self.base_rig_dir)
        
        # 7. Write Asset Pack files
        layers_meta = []
        preview_img = Image.new("RGBA", target_size, (0, 0, 0, 0))
        
        for name, layer_img in layers_map.items():
            filename = f"{name}.png"
            dest_path = os.path.join(pack_dir, filename)
            layer_img.save(dest_path, "PNG")
            
            # Map Z-Index based on slot name
            # Default mapping
            z_idx = 50
            if name == "sleeves_front":
                z_idx = 55
            elif name == "clothing_front":
                z_idx = 50
                
            layers_meta.append({
                "name": name,
                "file": filename,
                "z_index": z_idx
            })
            
            # Add to preview composite
            preview_img = Image.alpha_composite(preview_img, layer_img)
            
        # Save preview
        preview_img.save(os.path.join(pack_dir, "preview.png"), "PNG")
        
        # Build metadata.json
        fit_applied = bool(fit_report)
        metadata = {
            "asset_id": asset_id,
            "display_name": display_name,
            "category": category,
            "compatible_pose": self.rig_config.get("pose", "front_standing_v1"),
            "compatible_body": self.rig_config.get("body_archetype", "muscular_curvy_female_v1"),
            "layers": layers_meta,
            "anchors_used": list(self.rig_config.get("anchors", {}).keys()),
            "fit": {
                "applied": fit_applied,
                "method": fit_method if fit_applied else None,
                "report": fit_report,
                "stable_anchors": fitted_anchors,
                "anchors_path": f"fit_debug/anchors.json" if fit_applied else None,
            },
            "validation_report": report,
            "source_metadata": {
                "had_alpha": source_has_alpha,
                "chromakey_applied": chromakey_applied,
            },
        }
        if isinstance(options.get("cleanup"), dict):
            metadata["cleanup"] = options["cleanup"]
        
        with open(os.path.join(pack_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)
            
        # Update manifest
        self.update_manifest(asset_id, category, display_name, os.path.join("public", "assets", "compiled", category, asset_id, "metadata.json"))
        
        print(f"Successfully compiled asset pack at: {pack_dir}")
        return metadata

    def update_manifest(self, asset_id: str, category: str, display_name: str, rel_meta_path: str):
        """Adds or updates the compiled asset entry in the global wardrobe manifest."""
        manifest = []
        if os.path.exists(MANIFEST_PATH):
            try:
                with open(MANIFEST_PATH, "r") as f:
                    manifest = json.load(f)
            except Exception:
                pass
                
        # Remove existing if present
        manifest = [entry for entry in manifest if entry["asset_id"] != asset_id]
        
        # Add new entry
        manifest.append({
            "asset_id": asset_id,
            "category": category,
            "display_name": display_name,
            "metadata_path": rel_meta_path
        })
        
        # Ensure target dir exists
        os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
        with open(MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2)
        print("Updated wardrobe manifest.")
