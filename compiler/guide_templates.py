"""Authoring-guide PNG generator.

Per-garment 768×768 reference PNGs. Each guide is rendered twice:

  - ``human/<id>.png`` — title, alignment lines, anchor dots, labels, border
  - ``ai/<id>.png``    — silhouette + region only, no text/dots/border

Garment regions are derived **from anchor polygons** in ``rig.json``, not from
the legacy ``*_allowed_region.png`` masks. This guarantees regions and
alignment lines cannot disagree. A guide may set ``region_mask_override`` to a
PNG path if hand-tuned artwork is needed instead.
"""

import io
import json
import os
import zipfile
from typing import Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

CANVAS = (768, 768)

LINE_ANCHORS = {
    "shoulders": ("left_shoulder", "right_shoulder"),
    "bust":      ("bust_left", "bust_right"),
    "waist":     ("waist_left", "waist_right"),
    "hips":      ("hip_left", "hip_right"),
    "knees":     ("knee_left", "knee_right"),
    "hem":       ("hem_left", "hem_right"),
    "ankles":    ("ankle_left", "ankle_right"),
}

# Each entry's spec:
#   title            : guide heading (human mode)
#   lines            : alignment-line names (subset of LINE_ANCHORS)
#   region_polygons  : list of polygons; each is a list of anchor names OR
#                      callables(anchors) -> [(x, y), ...]
#   region_mask_override : path under base_rig/masks/ to use instead
#   arm_layers       : True for handwear-style composite (arms + hands)
GUIDES = {
    "dress_bodycon": {
        "title": "Dress (Bodycon)",
        "lines": ["shoulders", "bust", "waist", "hips", "hem"],
        "region_polygons": [
            [
                "left_shoulder", "bust_left", "waist_left", "hip_left",
                "hem_left", "hem_right", "hip_right", "waist_right",
                "bust_right", "right_shoulder",
            ],
        ],
    },
    "dress_flared": {
        "title": "Dress (Flared)",
        "lines": ["shoulders", "bust", "waist", "hips", "hem"],
        "region_polygons": [
            lambda a: [
                a["left_shoulder"],
                a["bust_left"],
                a["waist_left"],
                a["hip_left"],
                (max(0, a["hem_left"][0] - 90), a["hem_left"][1]),
                (min(CANVAS[0], a["hem_right"][0] + 90), a["hem_right"][1]),
                a["hip_right"],
                a["waist_right"],
                a["bust_right"],
                a["right_shoulder"],
            ],
        ],
    },
    "topwear": {
        "title": "Topwear",
        "lines": ["shoulders", "bust", "waist"],
        "region_polygons": [
            [
                "left_shoulder", "bust_left", "waist_left",
                "waist_right", "bust_right", "right_shoulder",
            ],
        ],
    },
    "skirt": {
        "title": "Skirt",
        "lines": ["waist", "hips", "hem"],
        "region_polygons": [
            lambda a: [
                a["waist_left"],
                a["hip_left"],
                (max(0, a["hem_left"][0] - 60), a["hem_left"][1]),
                (min(CANVAS[0], a["hem_right"][0] + 60), a["hem_right"][1]),
                a["hip_right"],
                a["waist_right"],
            ],
        ],
    },
    "pants": {
        "title": "Pants",
        "lines": ["waist", "hips", "knees", "ankles"],
        "region_polygons": [
            lambda a: _leg_polygon(a, "left"),
            lambda a: _leg_polygon(a, "right"),
        ],
    },
    "legwear": {
        "title": "Legwear",
        "lines": ["waist", "hips", "knees", "ankles"],
        "region_polygons": [
            lambda a: _leg_polygon(a, "left"),
            lambda a: _leg_polygon(a, "right"),
        ],
    },
    "handwear": {
        "title": "Handwear",
        "lines": [],
        "region_polygons": [],
        "arm_layers": True,
    },
}

TINT_PRIMARY  = (0, 153, 204, 70)
TINT_HANDWEAR = (200, 60, 180, 90)
LINE_COLOR    = (0, 153, 204, 200)
GHOST_COLOR   = (40, 40, 40, 70)
BORDER_COLOR  = (0, 0, 0, 255)
DOT_COLOR     = (220, 30, 60, 255)
LABEL_COLOR   = (0, 102, 153, 255)

LABEL_MERGE_GAP_PX = 25


def _leg_polygon(anchors: dict, side: str) -> List[Tuple[float, float]]:
    """Approximate a single leg tube from waist/hip → knee → ankle."""
    suffix = "left" if side == "left" else "right"
    hip = anchors[f"hip_{suffix}"]
    knee = anchors[f"knee_{suffix}"]
    ankle = anchors[f"ankle_{suffix}"]
    waist = anchors[f"waist_{suffix}"]
    waist_l = anchors["waist_left"]
    waist_r = anchors["waist_right"]
    center_x = (waist_l[0] + waist_r[0]) / 2
    inner_offset = 18
    outer_pad = 6
    if side == "left":
        outer_top = (waist[0] - outer_pad, waist[1])
        outer_knee = (knee[0] - outer_pad, knee[1])
        outer_ankle = (ankle[0] - outer_pad, ankle[1])
        inner_ankle = (ankle[0] + outer_pad, ankle[1])
        inner_knee = (knee[0] + outer_pad + 4, knee[1])
        inner_top = (center_x - 4, waist[1])
    else:
        outer_top = (waist[0] + outer_pad, waist[1])
        outer_knee = (knee[0] + outer_pad, knee[1])
        outer_ankle = (ankle[0] + outer_pad, ankle[1])
        inner_ankle = (ankle[0] - outer_pad, ankle[1])
        inner_knee = (knee[0] - outer_pad - 4, knee[1])
        inner_top = (center_x + 4, waist[1])
    return [outer_top, outer_knee, outer_ankle, inner_ankle, inner_knee, inner_top]


def _load_font(size: int):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _silhouette_ghost(base_rig_dir: str) -> Image.Image:
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    sil_path = os.path.join(base_rig_dir, "masks", "body_silhouette.png")
    if not os.path.exists(sil_path):
        return layer
    src = Image.open(sil_path).convert("RGBA").resize(CANVAS, Image.Resampling.LANCZOS)
    fill = Image.new("RGBA", CANVAS, GHOST_COLOR)
    layer.paste(fill, (0, 0), src.getchannel("A"))
    return layer


def _resolve_polygon(spec, anchors: dict) -> Optional[List[Tuple[float, float]]]:
    """Turn a polygon spec into a list of (x, y). Returns None if any anchor missing."""
    if callable(spec):
        try:
            return [(float(p[0]), float(p[1])) for p in spec(anchors)]
        except KeyError:
            return None
    pts = []
    for name in spec:
        if name not in anchors:
            return None
        x, y = anchors[name]
        pts.append((float(x), float(y)))
    return pts


def _draw_polygon_region(img: Image.Image, points: Sequence[Tuple[float, float]], color) -> None:
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon(list(points), fill=color)
    img.alpha_composite(layer)


def _handwear_region(base_rig_dir: str) -> Image.Image:
    layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    sources = [
        os.path.join(base_rig_dir, "left_arm.png"),
        os.path.join(base_rig_dir, "right_arm.png"),
        os.path.join(
            os.path.dirname(base_rig_dir), "public", "assets", "skin_wear_hands.png"
        ),
    ]
    for src in sources:
        if not os.path.exists(src):
            continue
        img = Image.open(src).convert("RGBA").resize(CANVAS, Image.Resampling.LANCZOS)
        alpha = img.getchannel("A")
        fill = Image.new("RGBA", CANVAS, TINT_HANDWEAR)
        tinted = Image.composite(fill, Image.new("RGBA", CANVAS, (0, 0, 0, 0)), alpha)
        layer = Image.alpha_composite(layer, tinted)
    return layer


def _group_lines(line_specs: List[Tuple[str, int]]) -> List[List[Tuple[str, int]]]:
    """Group lines whose y values are within LABEL_MERGE_GAP_PX of each other."""
    sorted_specs = sorted(line_specs, key=lambda t: t[1])
    groups: List[List[Tuple[str, int]]] = []
    for name, y in sorted_specs:
        if groups and (y - groups[-1][-1][1]) < LABEL_MERGE_GAP_PX:
            groups[-1].append((name, y))
        else:
            groups.append([(name, y)])
    return groups


def _draw_alignment_lines(img: Image.Image, anchors: dict, line_names: Iterable[str]) -> None:
    draw = ImageDraw.Draw(img)
    font = _load_font(14)

    line_specs: List[Tuple[str, int]] = []
    for name in line_names:
        pair = LINE_ANCHORS.get(name)
        if not pair:
            continue
        a, b = pair
        if a not in anchors or b not in anchors:
            continue
        y = int(round((anchors[a][1] + anchors[b][1]) / 2))
        line_specs.append((name, y))

    for group in _group_lines(line_specs):
        for name, y in group:
            draw.line([(20, y), (CANVAS[0] - 20, y)], fill=LINE_COLOR, width=1)
            a, b = LINE_ANCHORS[name]
            for (x, ay) in (anchors[a], anchors[b]):
                draw.ellipse((x - 4, ay - 4, x + 4, ay + 4), fill=DOT_COLOR)
        avg_y = sum(y for _, y in group) // len(group)
        label = " / ".join(n.upper() for n, _ in group)
        if len(group) > 1:
            ys = "/".join(str(y) for _, y in group)
            text = f"{label}  y={ys}"
        else:
            text = f"{label}  y={group[0][1]}"
        draw.text((24, avg_y + 3), text, fill=LABEL_COLOR, font=font)


def _draw_border(img: Image.Image) -> None:
    ImageDraw.Draw(img).rectangle(
        [(0, 0), (CANVAS[0] - 1, CANVAS[1] - 1)],
        outline=BORDER_COLOR,
        width=2,
    )


def _load_rig(base_rig_dir: str) -> dict:
    path = os.path.join(base_rig_dir, "rig.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def generate_guide(guide_id: str, base_rig_dir: str, ai: bool = False) -> Image.Image:
    if guide_id not in GUIDES:
        raise ValueError(f"Unsupported guide id: {guide_id}")
    spec = GUIDES[guide_id]

    img = Image.new("RGBA", CANVAS, (255, 255, 255, 255))
    img = Image.alpha_composite(img, _silhouette_ghost(base_rig_dir))

    rig = _load_rig(base_rig_dir)
    anchors = rig.get("anchors", {})

    override = spec.get("region_mask_override")
    if override:
        mask_path = os.path.join(base_rig_dir, "masks", override)
        if os.path.exists(mask_path):
            src = Image.open(mask_path).convert("RGBA").resize(CANVAS, Image.Resampling.LANCZOS)
            fill = Image.new("RGBA", CANVAS, TINT_PRIMARY)
            layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
            layer.paste(fill, (0, 0), src.getchannel("A"))
            img = Image.alpha_composite(img, layer)
    else:
        for polygon_spec in spec.get("region_polygons", []):
            pts = _resolve_polygon(polygon_spec, anchors)
            if pts and len(pts) >= 3:
                _draw_polygon_region(img, pts, TINT_PRIMARY)

    if spec.get("arm_layers"):
        img = Image.alpha_composite(img, _handwear_region(base_rig_dir))

    if not ai:
        _draw_alignment_lines(img, anchors, spec["lines"])
        ImageDraw.Draw(img).text(
            (24, 24),
            f"{spec['title'].upper()}  ·  768×768",
            fill=BORDER_COLOR,
            font=_load_font(20),
        )
        _draw_border(img)

    return img


def build_guides_zip(base_rig_dir: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for guide_id in GUIDES.keys():
            for ai in (False, True):
                img = generate_guide(guide_id, base_rig_dir, ai=ai)
                png_buf = io.BytesIO()
                img.save(png_buf, "PNG")
                folder = "ai" if ai else "human"
                zf.writestr(f"{folder}/{guide_id}.png", png_buf.getvalue())
    return buf.getvalue()
