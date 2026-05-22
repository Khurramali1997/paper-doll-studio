"""Shared category registry — single source of truth for all wardrobe categories.

Every component (compiler, frontend, importers, validators, fit pipeline)
must derive its category lists from this module, never hardcode them.
"""

# ── Canonical category list ────────────────────────────────────────────────
ALL_CATEGORIES = [
    "dress",
    "topwear",
    "bottomwear",
    "skirt",
    "pants",
    "legwear",
    "handwear",
    "outerwear",
    "shoes",
    "accessory",
]

# ── Subsets used by specific pipeline stages ───────────────────────────────

FITTED_CATEGORIES = {
    "dress", "topwear", "top", "skirt", "pants", "legwear", "outerwear",
}

FITTING_METHOD_CATEGORIES = {
    "dress", "outerwear", "topwear", "top", "skirt", "pants", "legwear",
}

UPPER_BODY_CATEGORIES = {
    "topwear", "dress", "outerwear", "top",
}

LOWER_BODY_CATEGORIES = {
    "skirt", "pants", "legwear",
}

# ── Slot names that have a project.json render layer ───────────────────────
WARDROBE_SLOTS = [
    "dress",
    "topwear",
    "bottomwear",
    "skirt",
    "pants",
    "legwear",
    "handwear",
    "outerwear",
    "shoes",
    "accessory",
]

# ── Frontend display labels (also used by index.html dropdown) ─────────────
SLOT_DISPLAY_NAMES = {
    "dress": "Dress",
    "topwear": "Topwear",
    "bottomwear": "Bottomwear",
    "skirt": "Skirt",
    "pants": "Pants",
    "legwear": "Legwear",
    "handwear": "Handwear",
    "outerwear": "Outerwear",
    "shoes": "Shoes",
    "accessory": "Accessory",
}

# ── Legacy keyword mappings (used by psd_to_prototype heuristic) ──────────
WARDROBE_KEYWORDS = {
    "dress":       ["dress", "gown", "one_piece"],
    "topwear":     ["top", "shirt", "jacket", "vest", "coat", "chest"],
    "bottomwear":  ["bottom", "underwear", "waist"],
    "skirt":       ["skirt"],
    "pants":       ["pant", "trouser", "jean"],
    "legwear":     ["leg", "sock", "boot", "foot", "feet"],
    "handwear":    ["hand", "glove", "arm", "sleeve"],
    "outerwear":   ["outer", "overcoat", "hoodie", "sweater"],
    "shoes":       ["shoe"],
    "accessory":   ["accessory", "belt", "bag", "hat", "glasses"],
}


def category_for_layer(clean_name):
    """Heuristic: infer wardrobe slot from a cleaned layer name."""
    for slot, keywords in WARDROBE_KEYWORDS.items():
        if any(kw in clean_name for kw in keywords):
            return slot
    return "accessory"


def is_fitted(category):
    return category.lower() in FITTED_CATEGORIES


def is_fitting_method(category):
    return category.lower() in FITTING_METHOD_CATEGORIES


def is_upper_body(category):
    return category.lower() in UPPER_BODY_CATEGORIES


def is_lower_body(category):
    return category.lower() in LOWER_BODY_CATEGORIES
