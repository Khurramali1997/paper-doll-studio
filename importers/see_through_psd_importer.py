"""PSD adapter for See-through / VSeeFace format PSDs with nested groups.

⚠ EXPERIMENTAL — Not yet verified against a real See-through output PSD.
   Requires a real See-through/VSeeFace output PSD fixture to validate
   recursive group traversal, visibility inheritance, and group-offset
   compositing.

TODO: Obtain a real See-through output PSD fixture, then:
  1. Verify recursive group traversal preserves group-level paint effects.
  2. Verify visibility inheritance from parent groups.
  3. Verify group offset (layer.left/top) composes correctly through nested transforms.
  4. Update layer map keys to match actual See-through output naming.

The current implementation uses ``see_through_layer_map.json`` where keys are
group-path suffixes and values are canonical slot names.
Recursively traverses all groups to collect leaf layers with their full group path.
"""

import os
import json

from PIL import Image
from psd_tools import PSDImage

from importers.layer_mapper import PsdImporterAdapter
from compiler.canonical_schema import CANONICAL_RENDER_LAYERS


MAP_PATH = os.path.join(os.path.dirname(__file__), "see_through_layer_map.json")


def _traverse_psd_group(psd_or_group, prefix=""):
    """Recursively yield (group_path, layer) for every visible leaf layer."""
    for layer in psd_or_group:
        if not layer.is_visible():
            continue
        name = layer.name.strip()
        if layer.is_group():
            yield from _traverse_psd_group(layer, prefix + name + "/")
        else:
            # leaf layer
            yield (prefix + name, layer)


def _match_path(layer_path, layer_map, separator="/", match_mode="suffix"):
    """Try to match a layer_path against the map.

    ``match_mode``:
      - "suffix": path ends with the map key
      - "prefix": path starts with the map key
      - "exact": exact match

    Returns canonical name or None.
    """
    for key, canonical in layer_map.items():
        if match_mode == "suffix":
            if layer_path.endswith(separator + key) or layer_path == key:
                return canonical
        elif match_mode == "prefix":
            if layer_path.startswith(key + separator) or layer_path == key:
                return canonical
        elif match_mode == "exact":
            if layer_path == key:
                return canonical
    return None


class SeeThroughPsdImporter(PsdImporterAdapter):

    def __init__(self, psd_path, layer_map_path=MAP_PATH):
        super().__init__(psd_path, layer_map_path)
        self._layer_map = {}
        self._composites = {}
        self._splits = {}
        self._separator = "/"
        self._match_mode = "suffix"
        if self.layer_map:
            self._layer_map = self.layer_map.get("layer_map", {})
            self._composites = self.layer_map.get("composites", {})
            self._splits = self.layer_map.get("splits", {})
            self._separator = self.layer_map.get("group_path_separator", "/")
            self._match_mode = self.layer_map.get("match_mode", "suffix")

    # ── Recursive extraction ───────────────────────────────────────────────

    def extract_layers(self, psd):
        canvas_size = (psd.width, psd.height)
        matched = {}  # canonical_name -> list of PIL Images
        unmatched = []

        for layer_path, layer in _traverse_psd_group(psd):
            pil = layer.composite().convert("RGBA")
            canonical = _match_path(
                layer_path, self._layer_map,
                separator=self._separator,
                match_mode=self._match_mode,
            )
            if canonical:
                matched.setdefault(canonical, []).append(pil)
            else:
                unmatched.append((layer_path, pil))

        # ── Composite multiple matches into single canonical layer ────
        result = {}
        for canonical, pils in matched.items():
            if len(pils) == 1:
                result[canonical] = pils[0]
            else:
                composite = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
                for p in pils:
                    composite = Image.alpha_composite(composite, p)
                result[canonical] = composite

        # ── Apply composites config ─────────────────────────────────────
        for composite_name, source_keys in self._composites.items():
            src_pils = [result.get(k) for k in source_keys if result.get(k) is not None]
            if src_pils:
                comp = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
                for p in src_pils:
                    comp = Image.alpha_composite(comp, p)
                result[composite_name] = comp

        # ── Apply splits config ─────────────────────────────────────────
        for split_name, cfg in self._splits.items():
            source = cfg.get("source")
            if source and source in result:
                crop_pct = cfg.get("crop_pct", [0.0, 0.0, 1.0, 1.0])
                w, h = canvas_size
                box = (
                    int(crop_pct[0] * w),
                    int(crop_pct[1] * h),
                    int(crop_pct[2] * w),
                    int(crop_pct[3] * h),
                )
                result[split_name] = result[source].crop(box)

        return result

    # ── Build render layers ────────────────────────────────────────────────

    def build_render_layers(self, psd):
        layers = self.extract_layers(psd)

        render_layers = []
        for entry in CANONICAL_RENDER_LAYERS:
            z, layer_id, category, subcategory, flags = entry
            img = layers.get(category if subcategory is None else subcategory)
            config = {
                "name": layer_id,
                "z": z,
                "visible": img is not None,
                "category": category,
            }
            if subcategory is not None:
                config["subcategory"] = subcategory
            if flags:
                config["flags"] = flags
            render_layers.append(config)

        # Build wardrobe mapping from detected clothing layers
        wardrobe_mapping = {}
        slot_membership = {
            "topwear": ["clothing_topwear"],
            "bottomwear": ["clothing_bottomwear"],
            "legwear": ["clothing_legwear"],
            "handwear": ["clothing_handwear_l", "clothing_handwear_r"],
        }
        for slot, member_ids in slot_membership.items():
            entries = []
            for mid in member_ids:
                if mid in layers:
                    entries.append({"id": mid, "optionValue": "clothing"})
            # also try to find skin_wear body parts
            body_map = {"topwear": "torso", "bottomwear": "legs", "handwear": "arms"}
            body_key = body_map.get(slot)
            if body_key in layers:
                entries.insert(0, {"id": body_key, "optionValue": "skin_wear"})
            wardrobe_mapping[slot] = entries if entries else []

        return render_layers, wardrobe_mapping


# ── CLI entry point ────────────────────────────────────────────────────────

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m importers.see_through_psd_importer <path/to/see_through.psd>")
        sys.exit(1)
    psd_path = sys.argv[1]
    if not os.path.exists(psd_path):
        print(f"PSD not found: {psd_path}")
        sys.exit(1)
    importer = SeeThroughPsdImporter(psd_path)
    importer.run()


if __name__ == "__main__":
    main()
