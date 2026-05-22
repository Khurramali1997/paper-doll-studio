#!/usr/bin/env python3
"""Generate project.json and doll_config.js from a PSD via the adapter system.

Usage:
    python -m psd_to_prototype [path/to/character.psd]
"""

import os
import sys

from importers.custom_flat_psd_importer import CustomFlatPsdImporter
from importers.layer_mapper import (
    build_wardrobe_config,
    write_project_json,
    write_doll_config_js,
)


def main(psd_path):
    project_root = os.path.dirname(os.path.abspath(__file__))
    print(f"=== Starting PSD to Prototype Pipeline (adapter-based) ===")
    print(f"PSD Source: {psd_path}")

    if not os.path.exists(psd_path):
        print(f"Error: PSD file '{psd_path}' not found!")
        sys.exit(1)

    importer = CustomFlatPsdImporter(psd_path)
    psd = importer.open_psd()
    print(f"Canvas Dimensions: {psd.width}x{psd.height}")

    # 1. Extract layers and save individual PNGs to public/assets/
    assets_dir = os.path.join(project_root, "public", "assets")
    importer.save_layer_images(assets_dir, psd)
    print(f"Saved layer images to {assets_dir}")

    # 2. Build render layer config + wardrobe mapping
    layers_config, wardrobe_mapping = importer.build_render_layers(psd)
    wardrobe_config = build_wardrobe_config(wardrobe_mapping)

    # 3. Write project.json and doll_config.js
    write_project_json(
        layers_config,
        wardrobe_config,
        psd_path,
        os.path.join(project_root, "project.json"),
    )
    write_doll_config_js(
        layers_config,
        wardrobe_config,
        os.path.join(project_root, "doll_config.js"),
    )

    print(f"Generated project.json and doll_config.js")
    print("=== Pipeline Completed Successfully ===")


if __name__ == "__main__":
    psd_file = sys.argv[1] if len(sys.argv) > 1 else "character.psd"
    main(psd_file)
