#!/usr/bin/env python3
import os
import sys
import argparse
import json
import re
from psd_tools import PSDImage
from PIL import Image
from compiler.compiler import AssetCompiler, remove_background_chromakey
from compiler.normalize_canvas import normalize_canvas
from compiler.align_asset import align_asset
from compiler.validate_asset import validate_asset

def main():
    parser = argparse.ArgumentParser(description="Ingest and compile a multi-layered garment from a PSD file.")
    parser.add_argument("psd_path", help="Path to raw candidate garment PSD file.")
    parser.add_argument("category", help="Wardrobe slot category (e.g. topwear, bottomwear).")
    parser.add_argument("--x-offset", type=float, default=0.0, help="Horizontal alignment offset.")
    parser.add_argument("--y-offset", type=float, default=0.0, help="Vertical alignment offset.")
    parser.add_argument("--scale", type=float, default=1.0, help="Scaling factor.")
    parser.add_argument("--asset-id", help="Custom asset ID (default: slugified filename).")
    parser.add_argument("--display-name", help="Display name for the wardrobe UI.")

    args = parser.parse_args()
    
    if not os.path.exists(args.psd_path):
        print(f"Error: File '{args.psd_path}' not found.")
        sys.exit(1)
        
    print(f"Reading PSD {args.psd_path}...")
    psd = PSDImage.open(args.psd_path)
    width, height = psd.width, psd.height
    
    compiler = AssetCompiler()
    target_size = tuple(compiler.rig_config.get("canvas", [768, 768]))
    
    display_name = args.display_name or os.path.splitext(os.path.basename(args.psd_path))[0].replace("_", " ").title()
    asset_id = args.asset_id or re.sub(r'[^a-z0-9]+', '_', display_name.lower()).strip('_')
    
    pack_dir = os.path.join(compiler.output_dir, args.category, asset_id)
    os.makedirs(pack_dir, exist_ok=True)
    
    layers_meta = []
    preview_img = Image.new("RGBA", target_size, (0, 0, 0, 0))
    
    # Process each flat layer in the PSD
    flat_layers = []
    def traverse(node):
        if node.is_group():
            for child in node:
                traverse(child)
        else:
            flat_layers.append(node)
    
    for layer in psd:
        traverse(layer)
        
    for layer in flat_layers:
        img = layer.topil()
        if img is None or layer.width == 0 or layer.height == 0:
            continue
            
        clean_layer_name = layer.name.lower().strip().replace(" ", "_").replace("-", "_")
        print(f"Processing layer '{layer.name}' -> '{clean_layer_name}'...")
        
        # Paste into full-size canvas of the PSD size
        full_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        full_img.paste(img, (layer.left, layer.top))
        
        # Normalize to rig size
        full_img = normalize_canvas(full_img, target_size)
        
        # Align
        full_img = align_asset(
            full_img,
            x_offset=args.x_offset,
            y_offset=args.y_offset,
            scale=args.scale,
            rig_anchors=compiler.rig_config.get("anchors")
        )
        
        # Validate / Clean against rig masks
        cleaned_img, report = validate_asset(full_img, args.category, compiler.base_rig_dir)
        
        # Save layer
        filename = f"{clean_layer_name}.png"
        cleaned_img.save(os.path.join(pack_dir, filename), "PNG")
        
        # Map Z index (back vs front)
        z_idx = 50
        if "back" in clean_layer_name:
            z_idx = 20
        elif "sleeve" in clean_layer_name or "overlay" in clean_layer_name:
            z_idx = 55
        elif "front" in clean_layer_name:
            z_idx = 50
            
        layers_meta.append({
            "name": clean_layer_name,
            "file": filename,
            "z_index": z_idx
        })
        
        # Composite preview (only draw front layers on preview, or all)
        preview_img = Image.alpha_composite(preview_img, cleaned_img)
        
    preview_img.save(os.path.join(pack_dir, "preview.png"), "PNG")
    
    metadata = {
        "asset_id": asset_id,
        "display_name": display_name,
        "category": args.category,
        "compatible_pose": compiler.rig_config.get("pose", "front_standing_v1"),
        "compatible_body": compiler.rig_config.get("body_archetype", "muscular_curvy_female_v1"),
        "layers": layers_meta,
        "anchors_used": list(compiler.rig_config.get("anchors", {}).keys())
    }
    
    with open(os.path.join(pack_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
        
    compiler.update_manifest(asset_id, args.category, display_name, os.path.join("public", "assets", "compiled", args.category, asset_id, "metadata.json"))
    
    print(f"PSD Import Complete! Saved layered pack to {pack_dir}")

if __name__ == "__main__":
    main()
