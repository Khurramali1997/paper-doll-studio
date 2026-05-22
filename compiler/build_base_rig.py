#!/usr/bin/env python3
"""Build the canonical base rig from a PSD using the adapter system.

Usage:
    python -m compiler.build_base_rig [path/to/character.psd]
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PSD_PATH = os.path.join(PROJECT_ROOT, "character.psd")

from importers.custom_flat_psd_importer import CustomFlatPsdImporter
from importers.layer_mapper import write_base_rig_outputs
from PIL import Image


def main(psd_path):
    print(f"Loading {psd_path}...")
    if not os.path.exists(psd_path):
        print(f"Error: {psd_path} not found!")
        return

    importer = CustomFlatPsdImporter(psd_path)
    psd = importer.open_psd()
    print(f"Canvas size: {psd.width}x{psd.height}")

    layers = importer.extract_layers(psd)
    canvas_size = (psd.width, psd.height)

    write_base_rig_outputs(PROJECT_ROOT, layers, canvas_size)
    print(f"Base Rig created successfully at {os.path.join(PROJECT_ROOT, 'base_rig')}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else PSD_PATH
    main(path)
