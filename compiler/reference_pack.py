"""AI-conditioning reference pack generator.

Given a body silhouette image and a rig's anchor dict, produces a set of
derived images that ControlNet / depth-conditioned / pose-conditioned models
can consume directly:

  - silhouette.png : binary alpha mask, neutral gray fill (filter-safe; no anatomy)
  - outline.png    : 2 px stroke around silhouette boundary, transparent inside
  - canny.png      : cv2.Canny edge map of the silhouette
  - depth.png      : distance-transform depth proxy (brighter = farther from edge)
  - pose.png       : OpenPose-style stick figure from rig.json anchors

The pack is filter-safe: every output is derived from a binary mask. No
anatomical pixels exist in any image.
"""

import io
import zipfile
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

OUTLINE_COLOR = (0, 0, 0, 255)
OUTLINE_STROKE = 2

# Full OpenPose 18-keypoint COCO topology + ControlNet OpenPose color scheme.
POSE_JOINT_COLOR = {
    "nose":            (255, 0, 0),
    "neck":            (255, 85, 0),
    "right_shoulder":  (255, 170, 0),
    "right_elbow":     (255, 255, 0),
    "right_wrist":     (170, 255, 0),
    "left_shoulder":   (85, 255, 0),
    "left_elbow":      (0, 255, 0),
    "left_wrist":      (0, 255, 85),
    "right_hip":       (0, 255, 170),
    "right_knee":      (0, 255, 255),
    "right_ankle":     (0, 170, 255),
    "left_hip":        (0, 85, 255),
    "left_knee":       (0, 0, 255),
    "left_ankle":      (85, 0, 255),
    "right_eye":       (170, 0, 255),
    "left_eye":        (255, 0, 255),
    "right_ear":       (255, 0, 170),
    "left_ear":        (255, 0, 85),
    # Synonyms used when sourcing from rig.json (anchor-stick fallback).
    "hip_left":  (0, 85, 255),
    "hip_right": (0, 255, 170),
    "knee_left":  (0, 0, 255),
    "knee_right": (0, 255, 255),
    "ankle_left":  (85, 0, 255),
    "ankle_right": (0, 170, 255),
}
POSE_LIMBS = [
    ("neck", "right_shoulder", (255, 128, 0)),
    ("neck", "left_shoulder",  (255, 200, 0)),
    ("right_shoulder", "right_elbow", (200, 200, 0)),
    ("right_elbow",    "right_wrist", (200, 255, 0)),
    ("left_shoulder",  "left_elbow",  (128, 255, 0)),
    ("left_elbow",     "left_wrist",  (0, 255, 0)),
    ("neck", "right_hip", (0, 255, 128)),
    ("neck", "left_hip",  (0, 255, 200)),
    ("right_hip", "right_knee",  (0, 200, 255)),
    ("right_knee", "right_ankle",(0, 128, 255)),
    ("left_hip",  "left_knee",   (0, 0, 255)),
    ("left_knee", "left_ankle",  (128, 0, 255)),
    ("neck", "nose",       (200, 0, 200)),
    ("nose", "right_eye",  (200, 0, 100)),
    ("nose", "left_eye",   (200, 100, 200)),
    ("right_eye", "right_ear", (100, 0, 100)),
    ("left_eye",  "left_ear",  (255, 0, 100)),
    # Fallback synonyms (anchor-stick path).
    ("neck", "hip_left",  (0, 200, 200)),
    ("neck", "hip_right", (0, 255, 200)),
    ("hip_left",  "hip_right",  (0, 200, 0)),
    ("hip_left",  "knee_left",  (0, 255, 128)),
    ("hip_right", "knee_right", (0, 255, 200)),
    ("knee_left",  "ankle_left",  (0, 128, 255)),
    ("knee_right", "ankle_right", (128, 0, 255)),
]


def _silhouette_to_mask(silhouette: Image.Image) -> np.ndarray:
    """Return a single-channel binary mask (0 or 255) from any silhouette PNG."""
    img = silhouette.convert("RGBA")
    alpha = np.array(img.getchannel("A"))
    return (alpha > 10).astype(np.uint8) * 255


def make_outline(silhouette: Image.Image, stroke: int = OUTLINE_STROKE) -> Image.Image:
    mask = _silhouette_to_mask(silhouette)
    out = Image.new("RGBA", silhouette.size, (0, 0, 0, 0))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    arr = np.array(out)
    cv2.drawContours(arr, contours, -1, OUTLINE_COLOR, stroke)
    return Image.fromarray(arr, mode="RGBA")


def make_canny(
    silhouette: Image.Image,
    source: Optional[Image.Image] = None,
    lo: int = 50,
    hi: int = 150,
) -> Image.Image:
    src = source.convert("RGBA") if source is not None else silhouette.convert("RGBA")
    rgb = np.array(src.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if source is None:
        mask = _silhouette_to_mask(silhouette)
        gray = mask
    else:
        alpha = np.array(src.getchannel("A"))
        gray = np.where(alpha > 10, gray, 0).astype(np.uint8)
    edges = cv2.Canny(gray, lo, hi)
    rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
    return Image.fromarray(rgb, mode="RGB")


def make_depth(silhouette: Image.Image, depth_source: Optional[Image.Image] = None) -> Image.Image:
    """Depth map for ControlNet-Depth conditioning.

    If ``depth_source`` is provided AND the ONNX Depth Anything model is
    installed/downloaded, runs real monocular depth estimation on the body
    composite (silhouette is too low-detail for a depth model to reason
    about). Otherwise falls back to a distance-transform proxy from the
    silhouette mask. The fallback is honestly worse — prefer to provide a
    body composite if depth conditioning matters downstream.
    """
    if depth_source is not None:
        try:
            from compiler.depth_estimator import estimate_depth
            arr = estimate_depth(depth_source)
            if arr is not None:
                # Mask the depth to the silhouette so background stays black.
                mask = _silhouette_to_mask(silhouette)
                arr = np.where(mask > 0, arr, 0).astype(np.uint8)
                rgb = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
                return Image.fromarray(rgb, mode="RGB")
        except Exception as e:
            print(f"depth: real model failed, falling back to proxy: {e}")

    mask = _silhouette_to_mask(silhouette)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    if dist.max() > 0:
        dist = (dist / dist.max()) * 255
    depth = dist.astype(np.uint8)
    rgb = cv2.cvtColor(depth, cv2.COLOR_GRAY2RGB)
    return Image.fromarray(rgb, mode="RGB")


def make_pose(
    anchors: Dict[str, List[int]],
    canvas_size: Tuple[int, int],
    dot_radius: int = 6,
    line_width: int = 4,
) -> Image.Image:
    img = Image.new("RGB", canvas_size, (0, 0, 0))
    draw = ImageDraw.Draw(img)

    def pt(name):
        p = anchors.get(name)
        if p is None:
            return None
        return (int(p[0]), int(p[1]))

    for a_name, b_name, color in POSE_LIMBS:
        a = pt(a_name)
        b = pt(b_name)
        if a is None or b is None:
            continue
        draw.line([a, b], fill=color, width=line_width)

    for name, color in POSE_JOINT_COLOR.items():
        p = pt(name)
        if p is None:
            continue
        x, y = p
        draw.ellipse(
            (x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius),
            fill=color,
        )

    return img


def _try_mediapipe_pose(body_image: Image.Image, canvas_size: Tuple[int, int]) -> Optional[Image.Image]:
    try:
        from compiler.pose_estimator import estimate_pose
        joints = estimate_pose(body_image)
        if joints:
            return make_pose(joints, canvas_size)
    except Exception as e:
        print(f"pose: MediaPipe failed, falling back to anchors: {e}")
    return None


def build_reference_pack(
    silhouette: Image.Image,
    anchors: Optional[Dict[str, List[int]]] = None,
    body_composite: Optional[Image.Image] = None,
) -> bytes:
    """Compose all reference channels into a single ZIP archive.

    Args:
      silhouette:     filter-safe binary mask (no anatomical pixels).
      anchors:        rig.json anchors, used for pose fallback when no body
                      composite is supplied or MediaPipe fails to detect.
      body_composite: optional body image with structure (face + clothing).
                      When provided, enables real MediaPipe pose detection
                      and real ONNX depth estimation. When omitted, both
                      channels fall back to silhouette-only approximations.
    """
    channels = build_reference_channels(
        silhouette,
        anchors=anchors,
        body_composite=body_composite,
    )
    return build_reference_zip(channels)


def build_reference_zip(channels: List[Tuple[str, Image.Image]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, img in channels:
            png_buf = io.BytesIO()
            img.save(png_buf, "PNG")
            zf.writestr(name, png_buf.getvalue())
    return buf.getvalue()


def build_reference_channels(
    silhouette: Image.Image,
    anchors: Optional[Dict[str, List[int]]] = None,
    body_composite: Optional[Image.Image] = None,
) -> List[Tuple[str, Image.Image]]:
    """Return the raw reference images without zipping them."""
    w, h = silhouette.size

    pose_img: Optional[Image.Image] = None
    if body_composite is not None:
        pose_img = _try_mediapipe_pose(body_composite, (w, h))
    if pose_img is None and anchors:
        pose_img = make_pose(anchors, (w, h))

    channels: List[Tuple[str, Image.Image]] = [
        ("silhouette.png", silhouette),
        ("outline.png",    make_outline(silhouette)),
        ("canny.png",      make_canny(silhouette, source=body_composite)),
        ("depth.png",      make_depth(silhouette, depth_source=body_composite)),
    ]
    if pose_img is not None:
        channels.append(("pose.png", pose_img))
    return channels
