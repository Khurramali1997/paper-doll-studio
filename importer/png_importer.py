#!/usr/bin/env python3
import os
import sys
import argparse
from compiler.compiler import AssetCompiler

def main():
    parser = argparse.ArgumentParser(description="Ingest and compile a single PNG/JPG garment asset.")
    parser.add_argument("image_path", help="Path to raw candidate garment image.")
    parser.add_argument("category", help="Wardrobe slot category (e.g. topwear, bottomwear, legwear, handwear).")
    parser.add_argument("--x-offset", type=float, default=0.0, help="Horizontal alignment offset.")
    parser.add_argument("--y-offset", type=float, default=0.0, help="Vertical alignment offset.")
    parser.add_argument("--scale", type=float, default=1.0, help="Scaling factor.")
    parser.add_argument("--no-rembg", action="store_true", help="Skip chroma key background removal.")
    parser.add_argument("--chromakey-color", default="#ffffff", help="Color hex to key out for background.")
    parser.add_argument("--chromakey-tolerance", type=int, default=40, help="Chroma key tolerance value.")
    parser.add_argument("--asset-id", help="Custom asset ID (default: slugified display name).")
    parser.add_argument("--display-name", help="Display name for the wardrobe UI.")

    args = parser.parse_args()
    
    if not os.path.exists(args.image_path):
        print(f"Error: File '{args.image_path}' not found.")
        sys.exit(1)
        
    compiler = AssetCompiler()
    
    options = {
        "x_offset": args.x_offset,
        "y_offset": args.y_offset,
        "scale": args.scale,
        "remove_bg": not args.no_rembg,
        "chromakey_color": args.chromakey_color,
        "chromakey_tolerance": args.chromakey_tolerance,
        "asset_id": args.asset_id,
        "display_name": args.display_name
    }
    
    try:
        metadata = compiler.compile_asset(args.image_path, args.category, options)
        print("Import Complete!")
        print(f"Asset ID     : {metadata['asset_id']}")
        print(f"Display Name : {metadata['display_name']}")
        print(f"Layers       : {[l['name'] for l in metadata['layers']]}")
    except Exception as e:
        print(f"Compilation Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
