"""Detect rig anchors automatically from a body silhouette PNG.

Pure silhouette heuristics — no third-party ML models. Reads the alpha channel
of an input image, sweeps a width profile, and locates anatomical inflection
points (neck narrow, shoulder wide, bust wide, waist narrow, hips wide, knees,
ankles). Edge sampling at each Y produces left/right anchor pairs.

Suitable for symmetric, front-facing 2D rigs (the project's only supported
pose). For asymmetric poses, body archetypes that differ wildly from the
expected proportions, or multi-view rigs, this will need to be revisited.

Usage as a module:

    from compiler.rig_autodetect import detect_anchors, build_rig
    anchors = detect_anchors(PIL.Image.open("body_silhouette.png"))

Usage as a CLI:

    python -m compiler.rig_autodetect base_rig/masks/body_silhouette.png \\
        --output rig_auto.json
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

from PIL import Image

from compiler.garment_anchors import compute_width_profile

DEFAULT_CANVAS = (768, 768)


def _topmost(widths: List[int], min_w: int = 3) -> Optional[int]:
    for y, w in enumerate(widths):
        if w >= min_w:
            return y
    return None


def _bottommost(widths: List[int], min_w: int = 3) -> Optional[int]:
    for y in range(len(widths) - 1, -1, -1):
        if widths[y] >= min_w:
            return y
    return None


# Anatomical Y positions as fractions of body height (head-crown → foot-bottom).
# Calibrated against the reference muscular_curvy_female_v1 rig. Should hold
# within a few percent for any humanoid archetype; pose differences (raised
# arms, bent legs) will require recalibration.
ANATOMICAL_Y_FRACTIONS = {
    "neck":     0.121,
    "shoulder": 0.226,
    "bust":     0.317,
    "waist":    0.483,
    "hip":      0.513,
    "knee":     0.664,
    "hem":      0.784,
    "ankle":    0.845,
}


def detect_anchors(image: Image.Image) -> Dict[str, List[int]]:
    """Detect a draft anchor set from a body silhouette image.

    Returns ``{anchor_name: [x, y]}`` with the canonical anchor names used in
    ``base_rig/rig.json`` (neck, left/right_shoulder, strap_left/right,
    bust_left/right, waist_left/right, hip_left/right, knee_left/right,
    ankle_left/right, hem_left/right).

    Approach:
      - Y values use anatomical fractions of body height (top-of-head to
        bottom-of-foot). The front-standing-arms-down pose lacks a clear
        waist inflection, so width-profile extremum search is unreliable —
        proportions are the more robust signal.
      - X values use the silhouette's left/right edges at each Y. Where arms
        sit against the torso, these edges include the arm and read wider
        than the body landmark; the autodetect output is a draft that the
        artist is expected to review.

    Raises ``ValueError`` if the image contains no body content.
    """
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    left_edges, right_edges, widths = compute_width_profile(image)

    top_y = _topmost(widths)
    bottom_y = _bottommost(widths)
    if top_y is None or bottom_y is None:
        raise ValueError("Body silhouette is empty (no opaque pixels)")

    body_h = bottom_y - top_y
    if body_h < 50:
        raise ValueError(f"Body silhouette too small ({body_h} px tall)")

    def edge_at(y: int) -> Optional[Tuple[int, int]]:
        if y < 0 or y >= len(widths):
            return None
        le = left_edges[y]
        re = right_edges[y]
        if le is None or re is None:
            return None
        return le[0], re[0]

    ys: Dict[str, int] = {
        name: top_y + int(round(body_h * frac))
        for name, frac in ANATOMICAL_Y_FRACTIONS.items()
    }

    anchors: Dict[str, List[int]] = {}

    neck_edge = edge_at(ys["neck"])
    if neck_edge is not None:
        cx = int(round((neck_edge[0] + neck_edge[1]) / 2.0))
        anchors["neck"] = [cx, ys["neck"]]

    s_edge = edge_at(ys["shoulder"])
    if s_edge is not None:
        anchors["left_shoulder"]  = [s_edge[0], ys["shoulder"]]
        anchors["right_shoulder"] = [s_edge[1], ys["shoulder"]]
        span = s_edge[1] - s_edge[0]
        strap_y = max(top_y, ys["shoulder"] - max(15, int(body_h * 0.04)))
        anchors["strap_left"]  = [s_edge[0] + int(span * 0.22), strap_y]
        anchors["strap_right"] = [s_edge[1] - int(span * 0.22), strap_y]

    for short_name in ("bust", "waist", "hip"):
        edge = edge_at(ys[short_name])
        if edge is None:
            continue
        anchors[f"{short_name}_left"]  = [edge[0], ys[short_name]]
        anchors[f"{short_name}_right"] = [edge[1], ys[short_name]]

    knee_edge = edge_at(ys["knee"])
    if knee_edge is not None:
        anchors["knee_left"]  = [knee_edge[0], ys["knee"]]
        anchors["knee_right"] = [knee_edge[1], ys["knee"]]

    ankle_edge = edge_at(ys["ankle"])
    if ankle_edge is not None:
        anchors["ankle_left"]  = [ankle_edge[0], ys["ankle"]]
        anchors["ankle_right"] = [ankle_edge[1], ys["ankle"]]

    hem_edge = edge_at(ys["hem"])
    if hem_edge is not None:
        anchors["hem_left"]  = [hem_edge[0], ys["hem"]]
        anchors["hem_right"] = [hem_edge[1], ys["hem"]]

    return anchors


def _garment_subset(anchors: Dict[str, List[int]], names: List[str]) -> Dict[str, List[int]]:
    return {n: list(anchors[n]) for n in names if n in anchors}


def build_rig(
    anchors: Dict[str, List[int]],
    canvas: Tuple[int, int] = DEFAULT_CANVAS,
    pose: str = "front_standing_v1",
    body_archetype: str = "autodetected_v1",
) -> dict:
    """Wrap a flat anchor dict into the rig.json schema (canvas, pose, anchors,
    garment_anchors) with per-category subsets that match
    ``compiler.garment_anchors.STABLE_ANCHORS``."""
    return {
        "canvas": list(canvas),
        "pose": pose,
        "body_archetype": body_archetype,
        "anchors": {k: list(v) for k, v in anchors.items()},
        "garment_anchors": {
            "dress": _garment_subset(anchors, [
                "neck", "strap_left", "strap_right",
                "bust_left", "bust_right",
                "waist_left", "waist_right",
                "hip_left", "hip_right",
                "hem_left", "hem_right",
            ]),
            "topwear": _garment_subset(anchors, [
                "neck", "left_shoulder", "right_shoulder",
                "waist_left", "waist_right",
            ]),
            "skirt": _garment_subset(anchors, [
                "waist_left", "waist_right",
                "hip_left", "hip_right",
                "hem_left", "hem_right",
            ]),
            "pants": _garment_subset(anchors, [
                "waist_left", "waist_right",
                "hip_left", "hip_right",
                "knee_left", "knee_right",
            ]),
            "legwear": _garment_subset(anchors, [
                "waist_left", "waist_right",
                "hip_left", "hip_right",
                "knee_left", "knee_right",
            ]),
            "outerwear": _garment_subset(anchors, [
                "neck", "left_shoulder", "right_shoulder",
                "waist_left", "waist_right",
                "hip_left", "hip_right",
                "hem_left", "hem_right",
            ]),
        },
    }


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m compiler.rig_autodetect",
        description="Generate a draft rig.json from a body silhouette PNG.",
    )
    parser.add_argument("input", help="Path to body silhouette PNG (RGBA)")
    parser.add_argument("--output", "-o", default="rig_auto.json",
                        help="Output rig JSON path (default: rig_auto.json)")
    parser.add_argument("--pose", default="front_standing_v1")
    parser.add_argument("--body-archetype", default="autodetected_v1")
    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1

    img = Image.open(args.input)
    anchors = detect_anchors(img)
    canvas = (img.width, img.height) if img.width and img.height else DEFAULT_CANVAS
    rig = build_rig(anchors, canvas=canvas, pose=args.pose, body_archetype=args.body_archetype)
    with open(args.output, "w") as f:
        json.dump(rig, f, indent=2)
    print(f"wrote {len(anchors)} anchors → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
