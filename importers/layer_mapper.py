"""Generic PSD-to-canonical-rig adapter infrastructure.

Every PSD importer adapter must subclass ``PsdImporterAdapter`` and implement
``extract_layers()``.
"""

import os
import json
from PIL import Image
from psd_tools import PSDImage

from compiler.canonical_schema import (
    get_canonical_layers,
    BASE_ANCHORS,
    GARMENT_ANCHORS,
    RIG_FILES,
    MASK_FILES,
    ALLOWED_REGION_MASK_FILES,
)
from compiler.category_registry import (
    ALL_CATEGORIES,
    WARDROBE_SLOTS,
    SLOT_DISPLAY_NAMES,
)


# ── Canonical output writing helpers ───────────────────────────────────────

def composite_layers(layer_list, layers_dict, canvas_size):
    result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    for name in layer_list:
        img = layers_dict.get(name)
        if img is not None:
            result = Image.alpha_composite(result, img)
    return result


def alpha_mask(image):
    return image.split()[-1]


def make_alpha_image(alpha):
    return Image.merge("RGBA", (alpha, alpha, alpha, alpha))


def write_base_rig_outputs(project_root, layers_dict, canvas_size):
    """Write all canonical base_rig image files from extracted layer dict.

    ``layers_dict`` keys expected:
        hair_back, hair_front, head, face, torso, left_arm, right_arm, legs
    Plus optional clothing layers for project.json generation.
    """
    base_rig_dir = os.path.join(project_root, "base_rig")
    masks_dir = os.path.join(base_rig_dir, "masks")

    os.makedirs(base_rig_dir, exist_ok=True)
    os.makedirs(masks_dir, exist_ok=True)

    # ── Save individual parts ──────────────────────────────────────────────
    if "hair_back" in layers_dict:
        layers_dict["hair_back"].save(os.path.join(base_rig_dir, "hair_back.png"), "PNG")
    if "hair_front" in layers_dict:
        layers_dict["hair_front"].save(os.path.join(base_rig_dir, "hair_front.png"), "PNG")
    if "head" in layers_dict:
        layers_dict["head"].save(os.path.join(base_rig_dir, "head.png"), "PNG")
    if "face" in layers_dict:
        layers_dict["face"].save(os.path.join(base_rig_dir, "face.png"), "PNG")
    if "torso" in layers_dict:
        layers_dict["torso"].save(os.path.join(base_rig_dir, "torso.png"), "PNG")
    if "left_arm" in layers_dict:
        layers_dict["left_arm"].save(os.path.join(base_rig_dir, "left_arm.png"), "PNG")
    if "right_arm" in layers_dict:
        layers_dict["right_arm"].save(os.path.join(base_rig_dir, "right_arm.png"), "PNG")
    if "legs" in layers_dict:
        layers_dict["legs"].save(os.path.join(base_rig_dir, "legs.png"), "PNG")

    # ── body_base.png composite ────────────────────────────────────────────
    body_base_parts = ["head", "torso", "left_arm", "right_arm", "legs"]
    body_base = composite_layers(body_base_parts, layers_dict, canvas_size)
    body_base.save(os.path.join(base_rig_dir, "body_base.png"), "PNG")

    # ── Region masks ───────────────────────────────────────────────────────
    body_silhouette_alpha = alpha_mask(body_base)
    make_alpha_image(body_silhouette_alpha).save(
        os.path.join(masks_dir, "body_silhouette.png"), "PNG"
    )

    for mask_name, source_key in [
        ("torso_region.png", "torso"),
        ("arm_region.png", "arms"),
        ("leg_region.png", "legs"),
        ("shoe_region.png", "shoes_alpha"),
    ]:
        if source_key in layers_dict:
            src = layers_dict[source_key]
            if isinstance(src, Image.Image):
                a = alpha_mask(src)
            else:
                a = src  # already an alpha/L-mode image
            make_alpha_image(a).save(os.path.join(masks_dir, mask_name), "PNG")

    # ── dress_region and shoe_region (y-based cut) ─────────────────────────
    torso_region = alpha_mask(layers_dict.get("torso", Image.new("RGBA", canvas_size, (0,0,0,0))))
    leg_region = alpha_mask(layers_dict.get("legs", Image.new("RGBA", canvas_size, (0,0,0,0))))
    w, h = canvas_size

    dress_alpha = Image.new("L", canvas_size, 0)
    shoe_alpha = Image.new("L", canvas_size, 0)
    for y in range(h):
        for x in range(w):
            t = torso_region.getpixel((x, y))
            l = leg_region.getpixel((x, y))
            if y < 600 and (t > 0 or l > 0):
                dress_alpha.putpixel((x, y), max(t, l))
            if y >= 600 and l > 0:
                shoe_alpha.putpixel((x, y), l)

    make_alpha_image(dress_alpha).save(os.path.join(masks_dir, "dress_region.png"), "PNG")
    make_alpha_image(shoe_alpha).save(os.path.join(masks_dir, "shoe_region.png"), "PNG")

    # ── face_forbidden_region (face features) ──────────────────────────────
    face_img = layers_dict.get("face", Image.new("RGBA", canvas_size, (0,0,0,0)))
    head_img = layers_dict.get("head", Image.new("RGBA", canvas_size, (0,0,0,0)))
    face_contour = Image.alpha_composite(head_img, face_img)
    make_alpha_image(alpha_mask(face_contour)).save(
        os.path.join(masks_dir, "face_forbidden_region.png"), "PNG"
    )

    # ── hair_forbidden_region ──────────────────────────────────────────────
    hair_composite = composite_layers(
        ["hair_front", "hair_back"], layers_dict, canvas_size
    )
    make_alpha_image(alpha_mask(hair_composite)).save(
        os.path.join(masks_dir, "hair_forbidden_region.png"), "PNG"
    )

    # ── Allowed region masks ───────────────────────────────────────────────
    torso_region_img = Image.open(os.path.join(masks_dir, "torso_region.png")).convert("RGBA") \
        if os.path.exists(os.path.join(masks_dir, "torso_region.png")) else None
    arm_region_img = Image.open(os.path.join(masks_dir, "arm_region.png")).convert("RGBA") \
        if os.path.exists(os.path.join(masks_dir, "arm_region.png")) else None
    leg_region_img = Image.open(os.path.join(masks_dir, "leg_region.png")).convert("RGBA") \
        if os.path.exists(os.path.join(masks_dir, "leg_region.png")) else None
    dress_region_img = Image.open(os.path.join(masks_dir, "dress_region.png")).convert("RGBA") \
        if os.path.exists(os.path.join(masks_dir, "dress_region.png")) else None
    shoe_region_img = Image.open(os.path.join(masks_dir, "shoe_region.png")).convert("RGBA") \
        if os.path.exists(os.path.join(masks_dir, "shoe_region.png")) else None

    def safe_composite(imgs):
        result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        for img in imgs:
            if img:
                result = Image.alpha_composite(result, img)
        return result

    region_map = {
        "dress_allowed_region.png":     dress_region_img,
        "topwear_allowed_region.png":   safe_composite([torso_region_img, arm_region_img]),
        "top_allowed_region.png":       safe_composite([torso_region_img, arm_region_img]),
        "outerwear_allowed_region.png": safe_composite([torso_region_img, arm_region_img]),
        "skirt_allowed_region.png":     leg_region_img,
        "pants_allowed_region.png":     leg_region_img,
        "legwear_allowed_region.png":   leg_region_img,
        "shoe_allowed_region.png":      shoe_region_img,
    }
    for filename, img in region_map.items():
        if img:
            img.save(os.path.join(masks_dir, filename), "PNG")

    # ── rig.json ────────────────────────────────────────────────────────────
    from compiler.canonical_schema import BASE_ANCHORS, GARMENT_ANCHORS
    rig_config = {
        "canvas": list(canvas_size),
        "pose": "front_standing_v1",
        "body_archetype": "muscular_curvy_female_v1",
        "anchors": dict(BASE_ANCHORS),
        "garment_anchors": {k: dict(v) for k, v in GARMENT_ANCHORS.items()},
    }
    with open(os.path.join(base_rig_dir, "rig.json"), "w") as f:
        json.dump(rig_config, f, indent=2)

    print(f"Canonical base rig written to {base_rig_dir}")


def write_project_json(layers_config, wardrobe_config, psd_path, output_path):
    """Write a project.json from canonical layer and wardrobe configs."""
    project_data = {
        "version": 1,
        "canvas": {"width": 768, "height": 768},
        "body_ref": "base_rig/body_base.png",
        "layers": layers_config,
        "wardrobe": wardrobe_config,
        "defaults": {
            "theme": "dark",
            "zoom": 1.0,
            "showGrid": True,
        },
        "meta": {
            "name": "Paper Doll Project",
            "characterName": "Character",
            "sourceFiles": [os.path.basename(psd_path)],
        },
    }
    with open(output_path, "w") as f:
        json.dump(project_data, f, indent=2)


def write_doll_config_js(layers_config, wardrobe_config, output_path):
    """Write a doll_config.js (legacy JS config)."""
    config_data = {
        "canvas": {"width": 768, "height": 768},
        "layers": layers_config,
        "wardrobe": wardrobe_config,
        "defaults": {"theme": "dark", "zoom": 1.0, "showGrid": True},
    }
    with open(output_path, "w") as f:
        f.write("// Paper Doll Studio Configuration\n")
        f.write("// Generated by PSD adapter\n\n")
        f.write("window.DOLL_CONFIG = ")
        json.dump(config_data, f, indent=2)
        f.write(";\n")


def build_wardrobe_config(wardrobe_mapping):
    """Build wardrobe config dict from mapping of slot -> list of (id, optionValue)."""
    from compiler.category_registry import WARDROBE_SLOTS, SLOT_DISPLAY_NAMES

    wardrobe_config = {}
    for slot in WARDROBE_SLOTS:
        entries = wardrobe_mapping.get(slot, [])
        skin_wear_ids = [e["id"] for e in entries if e.get("optionValue") == "skin_wear"]
        clothing_ids = [e["id"] for e in entries if e.get("optionValue") == "clothing"]

        options = []
        if skin_wear_ids:
            options.append({
                "value": "skin_wear",
                "name": "Naked / Skin Wear",
                "layers": skin_wear_ids,
            })
        for opt_val, ids in [("clothing", clothing_ids)]:
            if ids:
                combined = list(skin_wear_ids) + list(ids) if skin_wear_ids else list(ids)
                options.append({
                    "value": opt_val,
                    "name": SLOT_DISPLAY_NAMES.get(slot, slot.capitalize()),
                    "layers": combined,
                })
        options.append({
            "value": "none",
            "name": "Invisible / None",
            "layers": [],
        })

        default_val = "skin_wear" if skin_wear_ids else ("clothing" if clothing_ids else "none")

        wardrobe_config[slot] = {
            "name": SLOT_DISPLAY_NAMES.get(slot, slot.capitalize()),
            "options": options,
            "defaultValue": default_val,
        }

    return wardrobe_config


# ── Base adapter class ─────────────────────────────────────────────────────

class PsdImporterAdapter:
    """Base class for PSD adapter importers.

    Subclasses must implement:
        extract_layers(psd) -> dict of canonical_name -> PIL Image

    The canonical layer names expected by write_base_rig_outputs:
        hair_back, hair_front, head, face, torso, left_arm, right_arm, legs
    Plus any clothing layers that should appear in project.json.
    """

    def __init__(self, psd_path, layer_map_path=None):
        self.psd_path = psd_path
        self.layer_map_path = layer_map_path
        self.layer_map = {}
        if layer_map_path and os.path.exists(layer_map_path):
            with open(layer_map_path) as f:
                self.layer_map = json.load(f)

    def open_psd(self):
        return PSDImage.open(self.psd_path)

    def extract_layers(self, psd):
        """Return dict of canonical_name -> PIL Image."""
        raise NotImplementedError

    def build_render_layers(self, psd):
        """Return (layers_config_list, wardrobe_mapping_dict)."""
        raise NotImplementedError

    def run(self):
        """Full pipeline: extract layers, write base_rig, write project.json."""
        psd = self.open_psd()
        layers = self.extract_layers(psd)
        canvas_size = (psd.width, psd.height)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        write_base_rig_outputs(project_root, layers, canvas_size)

        layers_config, wardrobe_mapping = self.build_render_layers(psd)
        wardrobe_config = build_wardrobe_config(wardrobe_mapping)

        write_project_json(
            layers_config,
            wardrobe_config,
            self.psd_path,
            os.path.join(project_root, "project.json"),
        )
        write_doll_config_js(
            layers_config,
            wardrobe_config,
            os.path.join(project_root, "doll_config.js"),
        )

        print("Adapter pipeline complete.")
