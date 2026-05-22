"""Paper Doll Studio Flat PSD Importer — v0.1 input contract.

Contract:
  - Input: flat (non-grouped) PSD
  - Groups: unsupported — skipped with a warning
  - Layer order: preserved from PSD
  - Layer offsets: preserved (paste at layer.left, layer.top)
  - Canvas size: preserved from PSD header
  - Visible raster layers: read; hidden layers are skipped
  - Layer names: normalized (lowercase, spaces→underscores, hyphens→underscores)
                 then resolved through the alias/name map

Output:
  - ``extract_layers()`` → canonical composites dict for base_rig generation
  - ``source_layers`` → dict of all individual source images by canonical name
  - ``build_render_layers()`` → (render_layer_configs, wardrobe_mapping) for project.json
  - ``save_layer_images()`` → writes individual PNGs to ``public/assets/``
  - ``generate_mapping_report()`` → structured report of what was mapped/unmapped

See ``flat_layer_map.json`` for the name-mapping table.
"""

import os
import json
import re

from PIL import Image
from psd_tools import PSDImage

from importers.layer_mapper import PsdImporterAdapter
from compiler.canonical_schema import CANONICAL_RENDER_LAYERS


MAP_PATH = os.path.join(os.path.dirname(__file__), "flat_layer_map.json")


def normalize_name(name):
    """Normalize a PSD layer name for map lookup.

    Steps:
      1. Lowercase
      2. Strip whitespace
      3. Replace spaces with underscores
      4. Replace hyphens with underscores
      5. Normalize left/right suffixes:
         - ``_l`` → ``_left``  (only if followed by end-of-string)
         - ``_r`` → ``_right``
    """
    n = name.lower().strip()
    n = n.replace(" ", "_").replace("-", "_")
    n = re.sub(r'_l\b', '_left', n)
    n = re.sub(r'_r\b', '_right', n)
    # Undo the above for character.psd convention (_l, _r stay as-is)
    return n


class FlatPsdImporter(PsdImporterAdapter):
    """Flat PSD importer for Paper Doll Studio v0.1.

    Supports multiple flat-PSD naming conventions via ``flat_layer_map.json``.
    Groups are skipped. Hidden layers are skipped.
    """

    def __init__(self, psd_path, layer_map_path=MAP_PATH):
        super().__init__(psd_path, layer_map_path)
        self._layer_map = {}
        self._composites = {}
        self._splits = {}
        # Track mapping stats for report
        self._mapping_log = {
            "mapped": [],       # (source_name, canonical_name)
            "unmapped": [],     # source names that had no match
            "groups_skipped": [],  # group names skipped
            "hidden_skipped": 0,
        }
        if self.layer_map:
            self._layer_map = self.layer_map.get("layer_map", {})
            self._composites = self.layer_map.get("composites", {})
            self._splits = self.layer_map.get("splits", {})

    # ── Name resolution ───────────────────────────────────────────────────

    def _resolve_name(self, raw_name):
        """Normalize then resolve through layer_map.

        Returns (normalized_name, canonical_name) where canonical_name is
        the resolved name from the map, or the normalized name if not found.
        """
        n = normalize_name(raw_name)
        canonical = self._layer_map.get(n)
        if canonical:
            return n, canonical
        return n, n

    # ── Extract layers ────────────────────────────────────────────────────

    def extract_layers(self, psd):
        """Return canonical composites dict for base_rig generation.

        Also populates ``self.source_layers`` (canonical_name → PIL Image)
        and ``self._mapping_log`` for reporting.
        """
        canvas_size = (psd.width, psd.height)
        self.source_layers = {}
        self._mapping_log = {
            "mapped": [],
            "unmapped": [],
            "groups_skipped": [],
            "hidden_skipped": 0,
        }
        direct = {}
        composite_sources = {k: [] for k in self._composites}
        split_sources = {}

        for layer in psd:
            if layer.is_group():
                self._mapping_log["groups_skipped"].append(layer.name.strip())
                continue
            if not layer.is_visible():
                self._mapping_log["hidden_skipped"] += 1
                continue

            raw_name = layer.name.strip()
            pil = layer.composite().convert("RGBA")
            full_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            full_img.paste(pil, (layer.left, layer.top))

            norm, canonical = self._resolve_name(raw_name)

            # Store under both normalized and canonical names
            self.source_layers[norm] = full_img
            self.source_layers[canonical] = full_img

            if canonical != norm:
                self._mapping_log["mapped"].append((raw_name, canonical))
            else:
                self._mapping_log["unmapped"].append(raw_name)

            # Direct canonical mappings (for layer_map entries)
            if canonical != norm:
                direct[canonical] = full_img

            # Composite membership: composites reference canonical names
            for composite_name, members in self._composites.items():
                if canonical in members:
                    composite_sources.setdefault(composite_name, []).append(full_img)

            # Split membership
            for split_name, split_cfg in self._splits.items():
                if canonical == split_cfg.get("source"):
                    split_sources[split_name] = full_img

        # 2. Build composites
        for composite_name, src_pils in composite_sources.items():
            if src_pils:
                result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
                for p in src_pils:
                    result = Image.alpha_composite(result, p)
                direct[composite_name] = result
                self.source_layers[composite_name] = result

        # 3. Build splits (pixel-by-pixel, preserves coordinates)
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

    # ── Mapping report ────────────────────────────────────────────────────

    def generate_mapping_report(self):
        """Return a structured dict describing the mapping outcome."""
        report = {
            "total_source_layers": (
                len(self._mapping_log["mapped"])
                + len(self._mapping_log["unmapped"])
            ),
            "mapped": self._mapping_log["mapped"],
            "unmapped": self._mapping_log["unmapped"],
            "groups_skipped": self._mapping_log["groups_skipped"],
            "hidden_skipped": self._mapping_log["hidden_skipped"],
            "source_layer_keys": sorted(self.source_layers.keys()),
        }

        # Required canonical layers that are missing
        required = [
            "hair_back", "hair_front", "body_neck", "body_face",
            "skin_wear_top", "skin_wear_bottom", "skin_wear_legs",
        ]
        report["missing_required"] = sorted(
            r for r in required if r not in self.source_layers
        )

        # Duplicate source mappings (multiple source names → same canonical)
        seen = {}
        for src, can in self._mapping_log["mapped"]:
            seen.setdefault(can, []).append(src)
        report["duplicate_candidates"] = {
            can: sources for can, sources in seen.items() if len(sources) > 1
        }

        return report

    # ── Render layers ─────────────────────────────────────────────────────

    def build_render_layers(self, psd):
        """Build (render_layers, wardrobe_mapping) using canonical layer order.

        Each render-layer entry includes ``file`` referencing the individual
        source PNG saved to ``public/assets/``.
        """
        layers = self.extract_layers(psd)

        render_layers = []
        for entry in CANONICAL_RENDER_LAYERS:
            z, layer_id, category, subcategory, flags = entry
            # Look up by canonical layer_id, then fall back to composites
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
        """
        os.makedirs(output_dir, exist_ok=True)
        if psd is not None:
            self.extract_layers(psd)

        # Save all source layers (individual + composites) as PNGs
        for src_name, img in self.source_layers.items():
            path = os.path.join(output_dir, f"{src_name}.png")
            img.save(path, "PNG")

        # Ensure canonical layer files exist
        layers_cfg, _ = self.build_render_layers(psd)
        for entry in layers_cfg:
            file_name = entry.get("file", f"{entry['id']}.png")
            path = os.path.join(output_dir, file_name)
            if not os.path.exists(path):
                img = self.source_layers.get(entry["id"])
                if img is not None:
                    img.save(path, "PNG")


# ── CLI entry point ────────────────────────────────────────────────────────

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m importers.flat_psd_importer <path/to/character.psd>")
        sys.exit(1)
    psd_path = sys.argv[1]
    if not os.path.exists(psd_path):
        print(f"PSD not found: {psd_path}")
        sys.exit(1)
    importer = FlatPsdImporter(psd_path)
    importer.run()


if __name__ == "__main__":
    main()
