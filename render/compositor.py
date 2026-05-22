#!/usr/bin/env python3
import os
import sys
import json
import argparse
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_RIG_DIR = os.path.join(PROJECT_ROOT, "base_rig")

def composite_character(garment_metadata_paths: list[str], output_path: str, base_rig_dir=BASE_RIG_DIR) -> Image.Image:
    """
    Composites base rig elements and any active compiled garments together
    using their Z-indexes, writing the output image.
    """
    rig_json = os.path.join(base_rig_dir, "rig.json")
    if not os.path.exists(rig_json):
        raise FileNotFoundError(f"rig.json not found in {base_rig_dir}")
        
    with open(rig_json, "r") as f:
        rig_config = json.load(f)
        
    width, height = rig_config["canvas"]
    canvas_size = (width, height)
    
    # 1. Define base rig layers with Z-indexes
    # Z-indexes:
    # 10: hair_back
    # 30: body_torso
    # 35: body_legs
    # 40: arms (both left and right combined, or separate)
    # 80: face (eyes, eyebrows, eyelashes, nose, mouth)
    # 90: hair_front
    layers_to_render = [
        {"path": os.path.join(base_rig_dir, "hair_back.png"), "z": 10},
        {"path": os.path.join(base_rig_dir, "head.png"), "z": 30},
        {"path": os.path.join(base_rig_dir, "torso.png"), "z": 31}, # renders on top of neck
        {"path": os.path.join(base_rig_dir, "legs.png"), "z": 35},
        {"path": os.path.join(base_rig_dir, "left_arm.png"), "z": 40},
        {"path": os.path.join(base_rig_dir, "right_arm.png"), "z": 40},
        {"path": os.path.join(base_rig_dir, "face.png"), "z": 80},
        {"path": os.path.join(base_rig_dir, "hair_front.png"), "z": 90},
    ]
    
    # 2. Add clothing layers from active garment packs
    for meta_path in garment_metadata_paths:
        if not os.path.exists(meta_path):
            print(f"Warning: Garment metadata '{meta_path}' not found. Skipping.")
            continue
            
        with open(meta_path, "r") as f:
            meta = json.load(f)
            
        pack_dir = os.path.dirname(meta_path)
        for layer in meta["layers"]:
            layer_path = os.path.join(pack_dir, layer["file"])
            layers_to_render.append({
                "path": layer_path,
                "z": layer["z_index"]
            })
            
    # Remove files that do not exist (e.g. optional base rig parts)
    layers_to_render = [l for l in layers_to_render if os.path.exists(l["path"])]
    
    # Sort layers by Z-index
    # If Z-indexes are equal, sort alphabetically by path to ensure deterministic ordering
    layers_to_render.sort(key=lambda l: (l["z"], l["path"]))
    
    # 3. Blending / Compositing
    print(f"Compositing {len(layers_to_render)} layers...")
    composite = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    for layer in layers_to_render:
        print(f"  [layer] Z={layer['z']}: {os.path.basename(layer['path'])}")
        layer_img = Image.open(layer["path"]).convert("RGBA")
        composite = Image.alpha_composite(composite, layer_img)
        
    # Save result
    composite.save(output_path, "PNG")
    print(f"Composited character saved to {output_path}")
    return composite

def main():
    parser = argparse.ArgumentParser(description="Composite base rig and garment layer packs.")
    parser.add_argument("output", help="Path to save output composited PNG.")
    parser.add_argument("garments", nargs="*", help="Paths to metadata.json files of garments to wear.")
    parser.add_argument("--rig", default=BASE_RIG_DIR, help="Path to base rig directory.")
    
    args = parser.parse_args()
    
    try:
        composite_character(args.garments, args.output, args.rig)
    except Exception as e:
        print(f"Rendering failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
