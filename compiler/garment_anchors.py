"""Garment anchor definitions and silhouette-based landmark inference.

Anchor authority model:
  - *Suggested* anchors come from automatic silhouette inference (UI only).
  - *Confirmed* anchors are user-approved positions required for fitting.
  - Fitting MUST NOT run with only suggested anchors.
"""

# ── Stable anchors per category (the only anchors allowed to drive fitting) ──

STABLE_ANCHORS = {
    "dress": ["neck",
              "strap_left", "strap_right",
              "bust_left", "bust_right",
              "armpit_left", "armpit_right",
              "waist_left", "waist_right",
              "navel",
              "hip_left", "hip_right",
              "hem_left", "hem_right",
              "elbow_left", "elbow_right",
              "wrist_left", "wrist_right"],
    "topwear": ["neck", "left_shoulder", "right_shoulder",
                "armpit_left", "armpit_right",
                "waist_left", "waist_right",
                "navel",
                "elbow_left", "elbow_right",
                "wrist_left", "wrist_right"],
    "top": ["neck", "left_shoulder", "right_shoulder",
            "armpit_left", "armpit_right",
            "waist_left", "waist_right",
            "navel",
            "elbow_left", "elbow_right",
            "wrist_left", "wrist_right"],
    "skirt": ["waist_left", "waist_right",
              "navel",
              "hip_left", "hip_right",
              "hem_left", "hem_right"],
    "pants": ["waist_left", "waist_right",
              "navel", "crotch",
              "hip_left", "hip_right",
              "knee_left", "knee_right"],
    "legwear": ["waist_left", "waist_right",
                "navel", "crotch",
                "hip_left", "hip_right",
                "knee_left", "knee_right"],
    "outerwear": ["neck", "left_shoulder", "right_shoulder",
                  "armpit_left", "armpit_right",
                  "waist_left", "waist_right",
                  "navel",
                  "hip_left", "hip_right",
                  "hem_left", "hem_right",
                  "elbow_left", "elbow_right",
                  "wrist_left", "wrist_right"],
}

# ── Anchors that can be auto-inferred from silhouette (suggested only) ──

SUGGESTED_ANCHOR_NAMES = [
    "neck", "left_shoulder", "right_shoulder",
    "armpit_left", "armpit_right",
    "waist_left", "waist_right",
    "navel",
    "crotch",
    "hip_left", "hip_right",
    "hem_left", "hem_right",
    "elbow_left", "elbow_right",
    "wrist_left", "wrist_right",
    "knee_left", "knee_right",
    "ankle_left", "ankle_right",
]

# ── Full catalog of expected anchors per category ──

CATEGORY_ANCHOR_MAP = {
    "dress": ["neck",
              "strap_left", "strap_right",
              "bust_left", "bust_right",
              "armpit_left", "armpit_right",
              "waist_left", "waist_right",
              "navel",
              "hip_left", "hip_right",
              "hem_left", "hem_right",
              "elbow_left", "elbow_right",
              "wrist_left", "wrist_right"],
    "topwear": ["neck", "left_shoulder", "right_shoulder",
                "armpit_left", "armpit_right",
                "waist_left", "waist_right",
                "navel",
                "elbow_left", "elbow_right",
                "wrist_left", "wrist_right"],
    "top": ["neck", "left_shoulder", "right_shoulder",
            "armpit_left", "armpit_right",
            "waist_left", "waist_right",
            "navel",
            "elbow_left", "elbow_right",
            "wrist_left", "wrist_right"],
    "skirt": ["waist_left", "waist_right",
              "navel",
              "hip_left", "hip_right",
              "hem_left", "hem_right"],
    "pants": ["waist_left", "waist_right",
              "navel", "crotch",
              "hip_left", "hip_right",
              "knee_left", "knee_right"],
    "legwear": ["waist_left", "waist_right",
                "navel", "crotch",
                "hip_left", "hip_right",
                "knee_left", "knee_right"],
    "outerwear": ["neck", "left_shoulder", "right_shoulder",
                  "armpit_left", "armpit_right",
                  "waist_left", "waist_right",
                  "navel",
                  "hip_left", "hip_right",
                  "hem_left", "hem_right",
                  "elbow_left", "elbow_right",
                  "wrist_left", "wrist_right"],
}

# ── Anchors that MUST be present in confirmed set for fitting to proceed ──

REQUIRED_CONFIRMED_ANCHORS = {
    "dress": ["waist_left", "waist_right", "hem_left", "hem_right"],
    "topwear": ["neck", "left_shoulder", "right_shoulder"],
    "top": ["neck", "left_shoulder", "right_shoulder"],
    "skirt": ["waist_left", "waist_right", "hem_left", "hem_right"],
    "pants": ["waist_left", "waist_right", "knee_left", "knee_right"],
    "legwear": ["waist_left", "waist_right", "knee_left", "knee_right"],
    "outerwear": ["neck", "left_shoulder", "right_shoulder",
                  "waist_left", "waist_right"],
}

# ── Legacy: minimum anchors for backward compat (used only for suggested path) ──

REQUIRED_MIN_ANCHORS = {
    "dress": ["neck", "left_shoulder", "right_shoulder"],
    "topwear": ["neck", "left_shoulder", "right_shoulder"],
    "top": ["neck", "left_shoulder", "right_shoulder"],
    "skirt": ["waist_left", "waist_right"],
    "pants": ["waist_left", "waist_right"],
    "legwear": ["waist_left", "waist_right"],
    "outerwear": ["neck", "left_shoulder", "right_shoulder"],
}


def compute_width_profile(image):
    """Scan garment alpha channel to compute left/right edges per row.

    Returns (left_edges, right_edges, widths) where each is a list of
    length image height. Missing rows have None / 0.
    """
    alpha = image.getchannel('A')
    w, h = image.size

    left_edges = []
    right_edges = []
    widths = []

    row_data = alpha.tobytes()
    row_len = w

    for y in range(h):
        start = y * row_len
        row = row_data[start:start + row_len]
        non_transparent = [x for x, px in enumerate(row) if px > 10]
        if non_transparent:
            left = non_transparent[0]
            right = non_transparent[-1]
            left_edges.append((left, y))
            right_edges.append((right, y))
            widths.append(right - left)
        else:
            left_edges.append(None)
            right_edges.append(None)
            widths.append(0)

    return left_edges, right_edges, widths


def _is_suggestable(name):
    """Return True if *name* is in the set of auto-inferrable anchors."""
    return name in SUGGESTED_ANCHOR_NAMES


def infer_garment_anchors(image):
    """Detect garment landmarks from silhouette profile.

    Returns a *suggested* anchor dict ``{"suggested": {name: [x, y]}}``
    or an empty dict if the garment has insufficient content.
    These are **not** confirmed — they must be reviewed and approved
    by the user before they can drive fitting.
    """
    alpha = image.getchannel('A')
    if alpha.getbbox() is None:
        return {}

    w, h = image.size
    left_edges, right_edges, widths = compute_width_profile(image)

    top_y = next((y for y in range(h) if widths[y] > 0), None)
    bottom_y = next((y for y in range(h - 1, -1, -1) if widths[y] > 0), None)

    if top_y is None or bottom_y is None:
        return {}

    garment_height = bottom_y - top_y
    if garment_height < 10:
        return {}

    def edge_x_at(y):
        le = left_edges[y]
        re = right_edges[y]
        if le is None or re is None:
            return None, None
        return le[0], re[0]

    def center_x_at(y):
        lx, rx = edge_x_at(y)
        if lx is None:
            return None
        return (lx + rx) / 2.0

    anchors = {}

    neck_region_end = top_y + max(int(garment_height * 0.08), 5)
    neck_y = top_y + max(int(garment_height * 0.03), 2)
    cx = center_x_at(neck_y)
    if cx is not None:
        anchors["neck"] = [cx, neck_y]

    shoulders_region_end = top_y + int(garment_height * 0.40)
    shoulder_candidates = []
    for y in range(neck_region_end, min(shoulders_region_end, h)):
        if widths[y] > 0:
            shoulder_candidates.append((y, widths[y]))
    if shoulder_candidates:
        shoulder_candidates.sort(key=lambda x: -x[1])
        shoulder_y = shoulder_candidates[0][0]
        lx, rx = edge_x_at(shoulder_y)
        if lx is not None:
            anchors["left_shoulder"] = [lx, shoulder_y]
            anchors["right_shoulder"] = [rx, shoulder_y]

    waist_region_start = top_y + int(garment_height * 0.30)
    waist_region_end = top_y + int(garment_height * 0.60)
    waist_candidates = []
    for y in range(waist_region_start, min(waist_region_end, h)):
        if widths[y] > 10:
            waist_candidates.append((y, widths[y]))
    if waist_candidates:
        waist_candidates.sort(key=lambda x: x[1])
        waist_y = waist_candidates[0][0]
        lx, rx = edge_x_at(waist_y)
        if lx is not None:
            anchors["waist_left"] = [lx, waist_y]
            anchors["waist_right"] = [rx, waist_y]

    if "waist_left" in anchors:
        hip_region_start = int(anchors["waist_left"][1]) + 1
    else:
        hip_region_start = top_y + int(garment_height * 0.40)
    hip_region_end = top_y + int(garment_height * 0.75)
    hip_candidates = []
    for y in range(hip_region_start, min(hip_region_end, h)):
        if widths[y] > 10:
            hip_candidates.append((y, widths[y]))
    if hip_candidates:
        hip_candidates.sort(key=lambda x: -x[1])
        hip_y = hip_candidates[0][0]
        lx, rx = edge_x_at(hip_y)
        if lx is not None:
            anchors["hip_left"] = [lx, hip_y]
            anchors["hip_right"] = [rx, hip_y]

    hem_y = bottom_y
    hem_region_start = max(top_y + int(garment_height * 0.70), 0)
    hem_candidates = []
    for y in range(hem_region_start, bottom_y + 1):
        if widths[y] > 5:
            hem_candidates.append((y, widths[y]))
    if hem_candidates:
        hem_candidates.sort(key=lambda x: x[0])
        hem_y = hem_candidates[-1][0]
    else:
        hem_y = bottom_y

    lx, rx = edge_x_at(hem_y)
    if lx is not None:
        anchors["hem_left"] = [lx, hem_y]
        anchors["hem_right"] = [rx, hem_y]

    knee_y = int((waist_region_end + hem_y) / 2) if "waist_right" in anchors else top_y + int(garment_height * 0.55)
    lx, rx = edge_x_at(knee_y)
    if lx is not None:
        anchors["knee_left"] = [lx, knee_y]
        anchors["knee_right"] = [rx, knee_y]

    ankle_y = hem_y
    lx, rx = edge_x_at(ankle_y)
    if lx is not None:
        anchors["ankle_left"] = [lx, ankle_y]
        anchors["ankle_right"] = [rx, ankle_y]

    if not anchors:
        return {}

    return {"suggested": anchors}
