"""Canonical rig schema — the internal Paper Doll Studio format.

This module defines the expected structure of a base rig independently of
any one PSD source format.  All PSD importers (adapters) must produce this
canonical output.

"""
# ── CANONICAL BASE RIG FILES ───────────────────────────────────────────────
# Each file is written into base_rig/ (unless otherwise noted).

RIG_FILES = {
    "body_base.png":       "Full body composite — head + torso + arms + legs.",
    "torso.png":           "Torso and hips — typically skin_wear_top + bottom.",
    "legs.png":            "Legs — typically skin_wear_legs.",
    "left_arm.png":        "Left arm (from character's perspective, viewer's right).",
    "right_arm.png":       "Right arm (from character's perspective, viewer's left).",
    "head.png":            "Head — neck + ears + face base composited.",
    "face.png":            "Facial features — eyes, brows, lashes, nose, mouth.",
    "hair_back.png":       "Back hair layer.",
    "hair_front.png":      "Front hair / bangs layer.",
}

# ── CANONICAL MASK FILES (written to base_rig/masks/) ──────────────────────

MASK_FILES = {
    "body_silhouette.png":      "Full body alpha mask used as fallback validation region.",
    "torso_region.png":         "Torso alpha mask (from torso.png).",
    "arm_region.png":           "Arms alpha mask (left_arm + right_arm composited).",
    "leg_region.png":           "Legs alpha mask (from legs.png).",
    "dress_region.png":         "Torso + legs (y < 600) — legacy dress shape.",
    "shoe_region.png":          "Legs at y >= 600 — shoe/foot region.",
    "face_forbidden_region.png":"Face features — garments must not cover this area.",
    "hair_forbidden_region.png":"Hair alpha — hair is allowed to overlap garments.",
}

ALLOWED_REGION_MASK_FILES = {
    "dress_allowed_region.png":     "torso_region + leg_region (y < 600)",
    "topwear_allowed_region.png":   "torso_region + arm_region",
    "top_allowed_region.png":       "torso_region + arm_region",
    "outerwear_allowed_region.png": "torso_region + arm_region",
    "skirt_allowed_region.png":     "leg_region",
    "pants_allowed_region.png":     "leg_region",
    "legwear_allowed_region.png":   "leg_region",
    "shoe_allowed_region.png":      "shoe_region",
}

# ── RIG CONFIG / anchors (written to rig.json) ─────────────────────────────

# 17 canonical anchor points (768×768 canvas)
BASE_ANCHORS = {
    "neck":            [384, 180],
    "left_shoulder":   [304, 250],
    "right_shoulder":  [472, 250],
    "strap_left":      [345, 210],
    "strap_right":     [423, 210],
    "bust_left":       [320, 310],
    "bust_right":      [448, 310],
    "waist_left":      [318, 420],
    "waist_right":     [446, 420],
    "hip_left":        [300, 440],
    "hip_right":       [468, 440],
    "knee_left":       [296, 540],
    "knee_right":      [472, 540],
    "ankle_left":      [300, 660],
    "ankle_right":     [468, 660],
    "hem_left":        [280, 620],
    "hem_right":       [488, 620],
}

# Per-category anchor subsets
def _subset(*names):
    return {k: BASE_ANCHORS[k] for k in names}

GARMENT_ANCHORS = {
    "dress":     _subset("neck", "strap_left", "strap_right",
                         "bust_left", "bust_right",
                         "waist_left", "waist_right",
                         "hip_left", "hip_right",
                         "hem_left", "hem_right"),
    "topwear":   _subset("neck", "left_shoulder", "right_shoulder",
                         "waist_left", "waist_right"),
    "top":       _subset("neck", "left_shoulder", "right_shoulder",
                         "waist_left", "waist_right"),
    "skirt":     _subset("waist_left", "waist_right",
                         "hip_left", "hip_right",
                         "hem_left", "hem_right"),
    "pants":     _subset("waist_left", "waist_right",
                         "hip_left", "hip_right",
                         "knee_left", "knee_right"),
    "legwear":   _subset("waist_left", "waist_right",
                         "hip_left", "hip_right",
                         "knee_left", "knee_right"),
    "outerwear": _subset("neck", "left_shoulder", "right_shoulder",
                         "waist_left", "waist_right",
                         "hip_left", "hip_right",
                         "hem_left", "hem_right"),
}

# ── CANONICAL RENDER LAYER ORDER (used by project.json) ────────────────────
# Each entry: (id, name, z, category, subcategory, flags...)
CANONICAL_RENDER_LAYERS = [
    # hair
    (10,  "hair_back",          "hair",     "hair_back",   {"toggleable": True, "dyeable": True}),
    # body
    (20,  "body_neck",          "face",     "neck",        {}),
    (30,  "body_ears_l",        "face",     "ears",        {"toggleable": True}),
    (40,  "body_ears_r",        "face",     "ears",        {"toggleable": True}),
    (50,  "body_face",          "face",     "face",        {}),
    # eyes
    (60,  "eyes_white_l",       "eyes",     "eyewhite",    {"toggleable": True}),
    (70,  "eyes_white_r",       "eyes",     "eyewhite",    {"toggleable": True}),
    (80,  "eyes_irides_l",      "eyes",     "irides",      {"toggleable": True, "dyeable": True}),
    (90,  "eyes_irides_r",      "eyes",     "irides",      {"toggleable": True, "dyeable": True}),
    (100, "eyes_eyelash_l",     "eyes",     "eyelashes",   {"toggleable": True}),
    (110, "eyes_eyelash_r",     "eyes",     "eyelashes",   {"toggleable": True}),
    (120, "eyes_eyebrow_l",     "eyes",     "eyebrows",    {"toggleable": True}),
    (130, "eyes_eyebrow_r",     "eyes",     "eyebrows",    {"toggleable": True}),
    (140, "body_nose",          "face",     "nose",        {"toggleable": True}),
    (150, "body_mouth",         "face",     "mouth",       {"toggleable": True}),
    # hair front (on top of face)
    (160, "hair_front",         "hair",     "hair_front",  {"toggleable": True, "dyeable": True}),
    # wardrobe: skin layers
    (170, "skin_wear_top",      "wardrobe", "topwear",     {"optionValue": "skin_wear"}),
    (175, "skin_wear_dress",    "wardrobe", "dress",       {"optionValue": "skin_wear"}),
    (180, "skin_wear_bottom",   "wardrobe", "bottomwear",  {"optionValue": "skin_wear"}),
    (185, "skin_wear_skirt",    "wardrobe", "skirt",       {"optionValue": "skin_wear"}),
    (190, "skin_wear_legs",     "wardrobe", "legwear",     {"optionValue": "skin_wear"}),
    (195, "skin_wear_hands",    "wardrobe", "handwear",    {"optionValue": "skin_wear"}),
    (197, "skin_wear_outerwear","wardrobe", "outerwear",   {"optionValue": "skin_wear"}),
    (198, "skin_wear_shoes",    "wardrobe", "shoes",       {"optionValue": "skin_wear"}),
    (199, "skin_wear_accessory","wardrobe", "accessory",   {"optionValue": "skin_wear"}),
    # wardrobe: clothing layers (above skin)
    (205, "clothing_dress",     "wardrobe", "dress",       {"optionValue": "clothing"}),
    (210, "clothing_topwear",   "wardrobe", "topwear",     {"optionValue": "clothing"}),
    (220, "clothing_bottomwear","wardrobe", "bottomwear",  {"optionValue": "clothing"}),
    (225, "clothing_skirt",     "wardrobe", "skirt",       {"optionValue": "clothing"}),
    (230, "clothing_legwear",   "wardrobe", "legwear",     {"optionValue": "clothing"}),
    (240, "clothing_handwear_l","wardrobe", "handwear",    {"optionValue": "clothing"}),
    (250, "clothing_handwear_r","wardrobe", "handwear",    {"optionValue": "clothing"}),
    (215, "clothing_outerwear", "wardrobe", "outerwear",   {"optionValue": "clothing"}),
    (235, "clothing_shoes",     "wardrobe", "shoes",       {"optionValue": "clothing"}),
    (245, "clothing_accessory", "wardrobe", "accessory",   {"optionValue": "clothing"}),
]

# Sorted by z-index for project.json output
CANONICAL_RENDER_LAYERS.sort(key=lambda x: x[0])


def build_render_layer_entry(z_index, layer_id, category, subcategory, flags):
    entry = {
        "id": layer_id,
        "name": layer_id,
        "file": f"{layer_id}.png",
        "z": z_index,
        "category": category,
        "subcategory": subcategory,
    }
    entry.update(flags)
    return entry


def get_canonical_layers():
    return [
        build_render_layer_entry(z, lid, cat, sub, flags)
        for z, lid, cat, sub, flags in CANONICAL_RENDER_LAYERS
    ]
