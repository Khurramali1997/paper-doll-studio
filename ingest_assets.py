#!/usr/bin/env python3
"""
AI Asset Ingestion Pipeline
============================
Processes raw AI-generated images into game-ready wardrobe assets.

Usage:
    ./venv/bin/python ingest_assets.py
    ./venv/bin/python ingest_assets.py --no-rembg        # Skip background removal
    ./venv/bin/python ingest_assets.py --dry-run          # Preview without writing

Workflow:
    1. Drop raw AI-generated PNGs into raw_imports/<slot>/
    2. Run this script
    3. Open Web Studio to preview and calibrate
"""

import os
import sys
import json
import re
import argparse
from PIL import Image

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_IMPORTS_DIR = os.path.join(PROJECT_ROOT, "raw_imports")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "public", "assets")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "doll_config.js")

VALID_SLOTS = ["topwear", "bottomwear", "legwear", "handwear"]

# Target bounding box regions per slot (derived from existing skin_wear layers)
# Format: (left, top, right, bottom) — the region where the clothing should fit
SLOT_TARGET_REGIONS = {
    "topwear":    (275, 150, 503, 400),   # chest/torso area
    "bottomwear": (300, 340, 475, 460),   # waist/hip area
    "legwear":    (290, 350, 490, 764),   # full legs
    "handwear":   (250, 180, 530, 500),   # arms and hands
}

CANVAS_SIZE = (768, 768)

# Z-index base for new wardrobe items (above existing clothing at Z:250)
NEW_ITEM_Z_BASE = 260

# Transparency threshold: if >20% of pixels are transparent, skip rembg
TRANSPARENCY_SKIP_THRESHOLD = 0.20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_name(filename):
    """Convert filename to a clean ID: 'Leather Armor.png' -> 'leather_armor'"""
    name = os.path.splitext(filename)[0]
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    name = name.strip('_')
    return name


def display_name(clean):
    """Convert clean_id to display name: 'leather_armor' -> 'Leather Armor'"""
    return clean.replace('_', ' ').title()


def has_transparency(img, threshold=TRANSPARENCY_SKIP_THRESHOLD):
    """Check if image already has significant transparency (pre-processed)."""
    if img.mode != 'RGBA':
        return False
    alpha = img.getchannel('A')
    pixels = list(alpha.getdata()) if not hasattr(alpha, 'get_flattened_data') else list(alpha.get_flattened_data())
    transparent_count = sum(1 for p in pixels if p < 128)
    ratio = transparent_count / len(pixels)
    return ratio > threshold


def remove_background(img, session=None):
    """Remove background using rembg. Returns RGBA image."""
    from rembg import remove, new_session
    if session is None:
        session = new_session("isnet-general-use")
    result = remove(img, session=session)
    return result


def align_to_canvas(img, slot):
    """
    Scale and position clothing image within the slot's target region on a 768x768 canvas.
    
    Strategy:
    - Scale the clothing's content (non-transparent bbox) to fit within the target region
    - Maintain aspect ratio
    - Center within the target region
    - Paste onto a full-size transparent canvas
    """
    # Ensure RGBA
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Get content bounding box (non-transparent area)
    bbox = img.getbbox()
    if bbox is None:
        print("    WARNING: Image is fully transparent after processing!")
        return Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    
    # Crop to content
    content = img.crop(bbox)
    content_w, content_h = content.size
    
    # Target region
    target = SLOT_TARGET_REGIONS[slot]
    target_w = target[2] - target[0]
    target_h = target[3] - target[1]
    
    # Scale to fit within target region while maintaining aspect ratio
    scale_w = target_w / content_w
    scale_h = target_h / content_h
    scale = min(scale_w, scale_h)
    
    # Don't upscale beyond 1.0 — only downscale if needed
    scale = min(scale, 1.5)  # Allow slight upscale up to 1.5x for small items
    
    new_w = int(content_w * scale)
    new_h = int(content_h * scale)
    
    if new_w < 1 or new_h < 1:
        print("    WARNING: Content too small after scaling!")
        return Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    
    scaled = content.resize((new_w, new_h), Image.LANCZOS)
    
    # Center within target region
    target_center_x = (target[0] + target[2]) // 2
    target_center_y = (target[1] + target[3]) // 2
    
    paste_x = target_center_x - new_w // 2
    paste_y = target_center_y - new_h // 2
    
    # Create full canvas and paste
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    canvas.paste(scaled, (paste_x, paste_y), scaled)
    
    return canvas


def parse_config():
    """Read and parse the existing doll_config.js file."""
    with open(CONFIG_PATH, 'r') as f:
        content = f.read()
    
    # Extract JSON between "const DOLL_CONFIG = " and the final ";"
    match = re.search(r'const DOLL_CONFIG\s*=\s*({.*});', content, re.DOTALL)
    if not match:
        print("ERROR: Could not parse doll_config.js!")
        sys.exit(1)
    
    # Python booleans differ from JS: true/false vs True/False
    json_str = match.group(1)
    return json.loads(json_str)


def write_config(config_data):
    """Write config data back to doll_config.js."""
    with open(CONFIG_PATH, 'w') as f:
        f.write("// Dynamic Paper Doll Studio Configuration\n")
        f.write("// Automatically generated by psd_to_prototype.py\n")
        f.write("// Last updated by ingest_assets.py\n\n")
        f.write("const DOLL_CONFIG = ")
        json.dump(config_data, f, indent=2)
        f.write(";\n")


def get_existing_asset_ids(config):
    """Get set of existing layer IDs to prevent duplicates."""
    return set(layer["id"] for layer in config["layers"])


def get_next_z_index(config):
    """Get the next available z-index (above all existing layers)."""
    max_z = max(layer["z"] for layer in config["layers"])
    return max_z + 10


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def process_slot(slot, config, rembg_session, dry_run=False, skip_rembg=False):
    """Process all raw images in a slot folder."""
    slot_dir = os.path.join(RAW_IMPORTS_DIR, slot)
    
    if not os.path.isdir(slot_dir):
        return []
    
    existing_ids = get_existing_asset_ids(config)
    new_assets = []
    
    files = sorted([
        f for f in os.listdir(slot_dir)
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))
    ])
    
    if not files:
        return []
    
    print(f"\n  📂 {slot}/ ({len(files)} file(s))")
    
    for filename in files:
        clean_id = f"{slot}_{clean_name(filename)}"
        
        # Skip if already exists
        if clean_id in existing_ids:
            print(f"    ⏭️  {filename} → already registered as '{clean_id}', skipping")
            continue
        
        filepath = os.path.join(slot_dir, filename)
        print(f"    🔄 Processing: {filename}")
        
        try:
            # Load image
            img = Image.open(filepath).convert("RGBA")
            print(f"       Input size: {img.size}")
            
            # Background removal
            if skip_rembg:
                print("       Background removal: SKIPPED (--no-rembg)")
            elif has_transparency(img):
                print("       Background removal: SKIPPED (already transparent)")
            else:
                print("       Removing background with rembg...")
                img = remove_background(img, session=rembg_session)
                print("       Background removed ✓")
            
            # Canvas alignment
            aligned = align_to_canvas(img, slot)
            content_bbox = aligned.getbbox()
            if content_bbox:
                print(f"       Aligned to canvas: content at ({content_bbox[0]},{content_bbox[1]})-({content_bbox[2]},{content_bbox[3]})")
            
            # Save
            output_filename = f"{clean_id}.png"
            output_path = os.path.join(ASSETS_DIR, output_filename)
            
            if dry_run:
                print(f"       DRY RUN: would save to {output_filename}")
            else:
                aligned.save(output_path, "PNG")
                print(f"       Saved: {output_filename}")
            
            new_assets.append({
                "id": clean_id,
                "filename": output_filename,
                "slot": slot,
                "display_name": display_name(clean_name(filename)),
            })
            
        except Exception as e:
            print(f"    ❌ Error processing '{filename}': {e}")
    
    return new_assets


def update_config(config, all_new_assets):
    """Add new assets to the config structure."""
    if not all_new_assets:
        return config
    
    next_z = get_next_z_index(config)
    
    for asset in all_new_assets:
        slot = asset["slot"]
        
        # 1. Add layer entry
        layer_entry = {
            "id": asset["id"],
            "name": asset["display_name"],
            "file": asset["filename"],
            "z": next_z,
            "category": "wardrobe",
            "subcategory": slot,
            "optionValue": asset["id"]  # Unique option value = layer ID
        }
        config["layers"].append(layer_entry)
        next_z += 10
        
        # 2. Add wardrobe option
        if slot not in config["wardrobe"]:
            # Create new wardrobe slot if it doesn't exist
            config["wardrobe"][slot] = {
                "name": slot.replace("wear", "wear").capitalize(),
                "options": [
                    {"value": "none", "name": "Invisible / None", "layers": []}
                ],
                "defaultValue": "none"
            }
        
        slot_config = config["wardrobe"][slot]
        
        # Find skin_wear layers for this slot (to underlay beneath clothing)
        skin_wear_layers = [
            l["id"] for l in config["layers"]
            if l.get("subcategory") == slot and l.get("optionValue") == "skin_wear"
        ]
        
        # Build the new option
        option_layers = skin_wear_layers + [asset["id"]]
        new_option = {
            "value": asset["id"],
            "name": asset["display_name"],
            "layers": option_layers
        }
        
        # Insert before the "none" option (keep it last)
        none_idx = next(
            (i for i, opt in enumerate(slot_config["options"]) if opt["value"] == "none"),
            len(slot_config["options"])
        )
        slot_config["options"].insert(none_idx, new_option)
    
    return config


def main():
    parser = argparse.ArgumentParser(description="AI Asset Ingestion Pipeline")
    parser.add_argument("--no-rembg", action="store_true", help="Skip background removal")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    args = parser.parse_args()
    
    print("=" * 60)
    print("  🎮 Paper Doll Studio — AI Asset Ingestion Pipeline")
    print("=" * 60)
    print(f"  Source:  {RAW_IMPORTS_DIR}")
    print(f"  Output:  {ASSETS_DIR}")
    print(f"  Config:  {CONFIG_PATH}")
    if args.dry_run:
        print("  Mode:    DRY RUN (no files will be written)")
    if args.no_rembg:
        print("  Rembg:   DISABLED")
    print()
    
    # Verify directories exist
    if not os.path.isdir(RAW_IMPORTS_DIR):
        print(f"ERROR: raw_imports/ directory not found at {RAW_IMPORTS_DIR}")
        print("Create it with: mkdir -p raw_imports/topwear raw_imports/bottomwear raw_imports/legwear raw_imports/handwear")
        sys.exit(1)
    
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    # Initialize rembg session (loads model once, reuses for all images)
    rembg_session = None
    if not args.no_rembg:
        try:
            from rembg import new_session
            print("  Loading rembg model (isnet-general-use)...")
            rembg_session = new_session("isnet-general-use")
            print("  Model loaded ✓\n")
        except ImportError:
            print("  WARNING: rembg not installed. Install with: ./venv/bin/pip install 'rembg[cpu]'")
            print("  Continuing without background removal...\n")
            args.no_rembg = True
    
    # Parse existing config
    print("📋 Reading existing configuration...")
    config = parse_config()
    existing_count = len(config["layers"])
    print(f"   Found {existing_count} existing layers\n")
    
    # Process each slot
    print("🔍 Scanning raw_imports/ for new assets...")
    all_new_assets = []
    
    for slot in VALID_SLOTS:
        new_assets = process_slot(
            slot, config, rembg_session,
            dry_run=args.dry_run,
            skip_rembg=args.no_rembg
        )
        all_new_assets.extend(new_assets)
    
    # Summary and config update
    print("\n" + "=" * 60)
    
    if not all_new_assets:
        print("  ℹ️  No new assets to process.")
        print("  Drop images into raw_imports/<slot>/ and run again.")
        print("=" * 60)
        return
    
    print(f"  ✨ Processed {len(all_new_assets)} new asset(s):")
    for asset in all_new_assets:
        print(f"     • [{asset['slot']}] {asset['display_name']}")
    
    if args.dry_run:
        print("\n  DRY RUN complete. No files were written.")
        print("  Run without --dry-run to commit changes.")
    else:
        # Update config
        config = update_config(config, all_new_assets)
        write_config(config)
        print(f"\n  📝 Updated doll_config.js ({len(config['layers'])} total layers)")
        print(f"  🎉 Done! Reload http://localhost:8000 to see new options.")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
