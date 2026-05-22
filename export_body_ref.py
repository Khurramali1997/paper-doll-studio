#!/usr/bin/env python3
"""
export_body_ref.py
==================
Composites the character body layers into reference images that developers
can use when prompting AI models.

Outputs:
  - body_ref_transparent.png  — composited body (no hair) on transparent bg
  - body_ref_grid.png         — composited body WITH hair on a grey grid bg
"""

import os
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CANVAS_SIZE = (768, 768)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "public", "assets")

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Layers ordered by z-index (back → front).
# Each entry is (filename, z_index, is_optional).
LAYERS = [
    ("hair_back.png",        10,  True),
    ("body_neck.png",        20,  False),
    ("body_ears_l.png",      30,  False),
    ("body_ears_r.png",      40,  False),
    ("body_face.png",        50,  False),
    ("body_nose.png",        140, False),
    ("body_mouth.png",       150, False),
    ("hair_front.png",       160, True),
    ("skin_wear_top.png",    170, False),
    ("skin_wear_bottom.png", 180, False),
    ("skin_wear_legs.png",   190, False),
    ("skin_wear_hands.png",  200, False),
]

# Hair layer filenames (used to decide which layers go into which output).
HAIR_LAYERS = {"hair_back.png", "hair_front.png"}

GRID_BG_COLOR = (0xE0, 0xE0, 0xE0, 0xFF)   # #E0E0E0
GRID_LINE_COLOR = (0xD0, 0xD0, 0xD0, 0xFF)  # #D0D0D0
GRID_SPACING = 20  # pixels


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_layer(filename: str, optional: bool) -> "Image.Image | None":
    """Load a single RGBA layer from the assets directory."""
    path = os.path.join(ASSETS_DIR, filename)
    if not os.path.isfile(path):
        if optional:
            print(f"  [skip] {filename} (optional, not found)")
            return None
        raise FileNotFoundError(f"Required layer not found: {path}")
    img = Image.open(path).convert("RGBA")
    print(f"  [load] {filename}  ({img.size[0]}x{img.size[1]})")
    return img


def make_grid_background(size: tuple[int, int]) -> "Image.Image":
    """Create a light-grey background with subtle grid lines."""
    bg = Image.new("RGBA", size, GRID_BG_COLOR)
    draw = ImageDraw.Draw(bg)
    w, h = size
    for x in range(0, w, GRID_SPACING):
        draw.line([(x, 0), (x, h - 1)], fill=GRID_LINE_COLOR)
    for y in range(0, h, GRID_SPACING):
        draw.line([(0, y), (w - 1, y)], fill=GRID_LINE_COLOR)
    return bg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Assets directory : {ASSETS_DIR}")
    print(f"Output directory : {OUTPUT_DIR}")
    print()

    # --- Load all layers ------------------------------------------------
    print("Loading layers …")
    loaded: list[tuple[str, Image.Image]] = []
    for filename, _z, optional in LAYERS:
        img = load_layer(filename, optional)
        if img is not None:
            loaded.append((filename, img))
    print()

    # --- Composite: body only (no hair) → transparent bg ----------------
    print("Compositing body_ref_transparent.png (no hair) …")
    body_only = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    for filename, img in loaded:
        if filename in HAIR_LAYERS:
            continue
        body_only = Image.alpha_composite(body_only, img)

    out_transparent = os.path.join(OUTPUT_DIR, "body_ref_transparent.png")
    body_only.save(out_transparent)
    print(f"  → saved {out_transparent}")
    print()

    # --- Composite: body WITH hair → grid background --------------------
    print("Compositing body_ref_grid.png (with hair, grid bg) …")
    body_with_hair = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    for _filename, img in loaded:
        body_with_hair = Image.alpha_composite(body_with_hair, img)

    grid_bg = make_grid_background(CANVAS_SIZE)
    result = Image.alpha_composite(grid_bg, body_with_hair)

    out_grid = os.path.join(OUTPUT_DIR, "body_ref_grid.png")
    result.save(out_grid)
    print(f"  → saved {out_grid}")
    print()

    print("Done ✓")


if __name__ == "__main__":
    main()
