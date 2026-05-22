"""PSD adapter for flat (non-grouped) PSDs like character.psd.

Uses ``custom_flat_layer_map.json`` to map layer names to canonical slots.
Handles compositing (multiple source layers → one canonical layer) and
splitting (one source layer → two canonical halves).
"""

import os
import json

from PIL import Image
from psd_tools import PSDImage

from importers.layer_mapper import PsdImporterAdapter
from compiler.canonical_schema import CANONICAL_RENDER_LAYERS, GARMENT_ANCHORS


MAP_PATH = os.path.join(os.path.dirname(__file__), "custom_flat_layer_map.json")


class CustomFlatPsdImporter(PsdImporterAdapter):

    def __init__(self, psd_path, layer_map_path=MAP_PATH):
        super().__init__(psd_path, layer_map_path)
        self._layer_map = {}
        self._composites = {}
        self._splits = {}
        if self.layer_map:
            self._layer_map = self.layer_map.get("layer_map", {})
            self._composites = self.layer_map.get("composites", {})
            self._splits = self.layer_map.get("splits", {})

    # ── Extract layers ────────────────────────────────────────────────────

    def extract_layers(self, psd):
        """Return canonical composites dict (head, face, torso, left_arm, right_arm, etc.)

        Also stores individual source layers on self.source_layers for rendering.
        """
        canvas_size = (psd.width, psd.height)
        self.source_layers = {}  # individual PSD layer name -> full-canvas PIL Image
        direct = {}       # canonical_name -> Image
        composite_sources = {k: [] for k in self._composites}
        split_sources = {}  # source_name -> Image

        for layer in psd:
            if not layer.is_visible():
                continue
            name = layer.name.strip()
            pil = layer.composite().convert("RGBA")
            # Paste onto full canvas at layer offset
            full_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            full_img.paste(pil, (layer.left, layer.top))
            self.source_layers[name] = full_img

            if name in self._layer_map:
                canonical = self._layer_map[name]
                direct[canonical] = full_img
                self.source_layers[name] = full_img
                self.source_layers[canonical] = full_img  # also by canonical name

            for composite_name, sources in self._composites.items():
                if name in sources:
                    composite_sources.setdefault(composite_name, []).append(full_img)

            for split_name, split_cfg in self._splits.items():
                if name == split_cfg["source"]:
                    split_sources[split_name] = full_img

        # 2. Composite
        for composite_name, src_pils in composite_sources.items():
            if src_pils:
                result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
                for p in src_pils:
                    result = Image.alpha_composite(result, p)
                direct[composite_name] = result
                self.source_layers[composite_name] = result  # also save composite

        # 3. Split (pixel-by-pixel, preserving full canvas coordinates)
        for split_name, split_pil in split_sources.items():
            cfg = self._splits[split_name]
            crop_pct = cfg.get("crop_pct", [0.0, 0.0, 1.0, 1.0])
            w, h = canvas_size
            left_pct, top_pct, right_pct, bottom_pct = crop_pct
            result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            for y in range(h):
                for x in range(w):
                    if left_pct * w <= x < right_pct * w and top_pct * h <= y < bottom_pct * h:
                        px = split_pil.getpixel((x, y))
                        if px[3] > 0:
                            result.putpixel((x, y), px)
            direct[split_name] = result
            self.source_layers[split_name] = result

        return direct

    # ── Build render layers ────────────────────────────────────────────────

    def build_render_layers(self, psd):
        """Build (render_layers, wardrobe_mapping) using the canonical layer order.

        Each render layer entry includes ``file`` referencing the individual
        PSD source layer PNG (or composite) saved to ``public/assets/``.
        """
        layers = self.extract_layers(psd)

        render_layers = []
        for entry in CANONICAL_RENDER_LAYERS:
            z, layer_id, category, subcategory, flags = entry
            # Determine which key holds the image for this layer:
            #   - If layer_id is a known key in source_layers, use it directly
            #   - Otherwise fall back to the composite key (category or subcategory)
            img = self.source_layers.get(layer_id) or layers.get(layer_id) or \
                  layers.get(subcategory) or layers.get(category)
            config = {
                "id": layer_id,
                "name": layer_id,
                "file": f"{layer_id}.png",
                "z": z,
                "visible": img is not None,
                "category": category,
            }
            if subcategory is not None:
                config["subcategory"] = subcategory
            config.update(flags)
            render_layers.append(config)

        # Wardrobe mapping: derive from canonical layer flags
        # Group canonical entries by subcategory (slot), collect layer IDs by optionValue
        slot_layers = {}
        for entry in CANONICAL_RENDER_LAYERS:
            z, layer_id, category, subcategory, flags = entry
            if category != "wardrobe":
                continue
            slot = subcategory
            if slot not in slot_layers:
                slot_layers[slot] = {"skin_wear": [], "clothing": []}
            opt = flags.get("optionValue", "clothing")
            if opt in slot_layers[slot]:
                slot_layers[slot][opt].append(layer_id)

        wardrobe_mapping = {}
        for slot, layer_groups in slot_layers.items():
            entries = []
            for opt, layer_ids in layer_groups.items():
                # Only include layers that have an image in source_layers
                existing = [lid for lid in layer_ids if lid in self.source_layers]
                if existing:
                    for lid in existing:
                        entries.append({"id": lid, "optionValue": opt})
            if entries:
                wardrobe_mapping[slot] = entries

        return render_layers, wardrobe_mapping

    def save_layer_images(self, output_dir, psd=None):
        """Save each render layer's image as a PNG file.

        ``output_dir``: path to ``public/assets/``.
        ``psd``: if provided, used to extract source layers; otherwise uses
                 self.source_layers from the most recent extract_layers call.
        """
        os.makedirs(output_dir, exist_ok=True)
        if psd is not None:
            self.extract_layers(psd)

        # Save individual source layers (from PSD) as {original_name}.png
        for src_name, img in self.source_layers.items():
            path = os.path.join(output_dir, f"{src_name}.png")
            img.save(path, "PNG")

        # Save composites under their canonical names too
        layers_cfg, _ = self.build_render_layers(psd)
        for entry in layers_cfg:
            file_name = entry.get("file", f"{entry['id']}.png")
            path = os.path.join(output_dir, file_name)
            if not os.path.exists(path):
                # Try to find the image from source layers or composites
                img = self.source_layers.get(entry["id"])
                if img is not None:
                    img.save(path, "PNG")


# ── CLI entry point ────────────────────────────────────────────────────────

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m importers.custom_flat_psd_importer <path/to/character.psd>")
        sys.exit(1)
    psd_path = sys.argv[1]
    if not os.path.exists(psd_path):
        print(f"PSD not found: {psd_path}")
        sys.exit(1)
    importer = CustomFlatPsdImporter(psd_path)
    importer.run()


if __name__ == "__main__":
    main()
