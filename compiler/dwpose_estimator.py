"""DWPose ONNX whole-body pose estimator for anime/illustration.

Auto-downloads ``dw-ll_ucoco_384.onnx`` (~134 MB, HuggingFace) on first use.
Uses the silhouette mask for person bounding box (no YOLOX needed).
Returns None gracefully on any error — missing onnxruntime, download failure,
or inference error.

DWPose outputs 133 COCO-WholeBody keypoints (body 17 + face 68 + hands 42 + feet 6).
We map the relevant body keypoints to our anchor format.
"""

import os
import urllib.request
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
MODEL_PATH = os.path.join(MODELS_DIR, "dw-ll_ucoco_384.onnx")
MODEL_URL = (
    "https://huggingface.co/NirZabari/DWPose/resolve/main/"
    "dw-ll_ucoco_384.onnx"
)

DWPOSE_INPUT_H = 384
DWPOSE_INPUT_W = 288

_session = None

# COCO-WholeBody keypoint indices for body (17 keypoints)
KP_NOSE           = 0
KP_LEFT_EYE       = 1
KP_RIGHT_EYE      = 2
KP_LEFT_EAR       = 3
KP_RIGHT_EAR      = 4
KP_LEFT_SHOULDER  = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_ELBOW     = 7
KP_RIGHT_ELBOW    = 8
KP_LEFT_WRIST     = 9
KP_RIGHT_WRIST    = 10
KP_LEFT_HIP       = 11
KP_RIGHT_HIP      = 12
KP_LEFT_KNEE      = 13
KP_RIGHT_KNEE     = 14
KP_LEFT_ANKLE     = 15
KP_RIGHT_ANKLE    = 16


def ensure_model() -> Optional[str]:
    """Download DWPose model on first use; return path or None."""
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"Downloading DWPose model → {MODEL_PATH} (one-time, ~134 MB)…")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        return MODEL_PATH
    except Exception as e:
        print(f"dwpose_estimator: download failed: {e}")
        if os.path.exists(MODEL_PATH):
            os.remove(MODEL_PATH)
        return None


def _get_session():
    """Return cached ONNX Runtime session, or None on failure."""
    global _session
    if _session is not None:
        return _session
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    path = ensure_model()
    if path is None:
        return None
    try:
        _session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        return _session
    except Exception as e:
        print(f"dwpose_estimator: session load failed: {e}")
        return None


def _decode_keypoints(
    heatmaps: np.ndarray,
    input_w: int,
    input_h: int,
) -> List[Tuple[int, int, float]]:
    """Decode DWPose heatmaps into keypoint coordinates and scores.

    Args:
        heatmaps: (1, K, H_out, W_out) float32 tensor.
        input_w, input_h: original input image dimensions.

    Returns:
        List of (x, y, score) for each of K keypoints, in input image coords.
    """
    B, K, H_out, W_out = heatmaps.shape
    scale_x = input_w / W_out
    scale_y = input_h / H_out

    flat = heatmaps.reshape(B, K, -1)
    max_vals = flat.max(axis=2)
    max_inds = flat.argmax(axis=2)

    y_coords = max_inds[0] // W_out
    x_coords = max_inds[0] % W_out

    keypoints = []
    for k in range(K):
        x = int(round(x_coords[k] * scale_x))
        y = int(round(y_coords[k] * scale_y))
        score = float(max_vals[0, k])
        keypoints.append((x, y, score))
    return keypoints


def estimate_pose(
    body_composite: Image.Image,
    body_mask: np.ndarray,
) -> Optional[Dict[str, Tuple[int, int]]]:
    """Run DWPose on body composite; return keypoints in original pixel coords.

    Args:
        body_composite: PIL Image (RGB) of the full character.
        body_mask: uint8 binary mask (0/255) matching the composite dimensions.

    Returns:
        Dict of keypoint name → (x, y) in original image coords, or None.
        Only includes keypoints with score > 0.3.
    """
    session = _get_session()
    if session is None:
        return None

    comp_w, comp_h = body_composite.size

    # Compute body bounding box from mask
    rows, cols = np.where(body_mask > 0)
    if len(rows) == 0:
        return None

    y1, y2 = int(rows.min()), int(rows.max())
    x1, x2 = int(cols.min()), int(cols.max())

    # Expand bbox by 10% to give DWPose context
    bbox_w = x2 - x1
    bbox_h = y2 - y1
    pad_x = max(20, int(bbox_w * 0.10))
    pad_y = max(20, int(bbox_h * 0.10))
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(comp_w, x2 + pad_x)
    y2 = min(comp_h, y2 + pad_y)

    # Crop composite to bbox and resize to DWPose input
    crop = body_composite.crop((x1, y1, x2, y2))
    crop_resized = crop.resize((DWPOSE_INPUT_W, DWPOSE_INPUT_H), Image.Resampling.BICUBIC)

    # Prepare input: NCHW float32, normalized to [0, 1]
    arr = np.array(crop_resized, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[None, ...]

    # Run inference
    try:
        outputs = session.run(None, {session.get_inputs()[0].name: arr})
    except Exception as e:
        print(f"dwpose_estimator: inference failed: {e}")
        return None

    heatmaps = outputs[0]
    keypoints = _decode_keypoints(heatmaps, DWPOSE_INPUT_W, DWPOSE_INPUT_H)

    # Scale keypoints from crop space back to original image space
    crop_scale_x = (x2 - x1) / DWPOSE_INPUT_W
    crop_scale_y = (y2 - y1) / DWPOSE_INPUT_H

    score_threshold = 0.3

    def _kp(idx: int) -> Optional[Tuple[int, int]]:
        x, y, s = keypoints[idx]
        if s < score_threshold:
            return None
        return (int(round(x * crop_scale_x + x1)),
                int(round(y * crop_scale_y + y1)))

    ls = _kp(KP_LEFT_SHOULDER)
    rs = _kp(KP_RIGHT_SHOULDER)
    le = _kp(KP_LEFT_ELBOW)
    re = _kp(KP_RIGHT_ELBOW)
    lw = _kp(KP_LEFT_WRIST)
    rw = _kp(KP_RIGHT_WRIST)
    lh = _kp(KP_LEFT_HIP)
    rh = _kp(KP_RIGHT_HIP)
    la = _kp(KP_LEFT_ANKLE)
    ra = _kp(KP_RIGHT_ANKLE)

    # Synthesize neck from shoulder midpoint
    neck = None
    if ls is not None and rs is not None:
        neck = ((ls[0] + rs[0]) // 2, (ls[1] + rs[1]) // 2)

    # Synthesize waist from hip midpoint (waist is above hips)
    waist_left = None
    waist_right = None
    if lh is not None and rh is not None:
        waist_y = (lh[1] + rh[1]) // 2 - int((rh[1] - lh[1]) * 0.3)
        # Derive left/right waist from body silhouette edges at waist Y
        if 0 <= waist_y < body_mask.shape[0]:
            waist_row = body_mask[waist_y, :]
            waist_cols = np.where(waist_row > 0)[0]
            if len(waist_cols) > 1:
                waist_left  = (int(waist_cols[0]), waist_y)
                waist_right = (int(waist_cols[-1]), waist_y)
        # Fallback: center point if silhouette scan fails
        if waist_left is None:
            waist_x = (lh[0] + rh[0]) // 2
            waist_left = (waist_x, waist_y)

    # Synthesize armpit from silhouette at Y between shoulder and chest
    def _synthesize_armpit(side_y):
        if 0 <= side_y < body_mask.shape[0]:
            row = body_mask[side_y, :]
            cols = np.where(row > 0)[0]
            if len(cols) > 1:
                return (int(cols[0]), side_y), (int(cols[-1]), side_y)
        return None, None

    armpit_left = armpit_right = None
    if ls is not None:
        armpit_y = ls[1] + int((lh[1] - ls[1]) * 0.15) if lh is not None else ls[1] + 30
        armpit_left, armpit_right = _synthesize_armpit(armpit_y)

    # Synthesize navel from silhouette between waist and hip
    navel_pt = None
    if waist_left is not None and lh is not None:
        navel_y = (waist_left[1] + lh[1]) // 2
        if 0 <= navel_y < body_mask.shape[0]:
            row = body_mask[navel_y, :]
            cols = np.where(row > 0)[0]
            if len(cols) > 1:
                navel_pt = ((int(cols[0]) + int(cols[-1])) // 2, navel_y)

    # Synthesize crotch from silhouette: find Y where body mask splits into legs
    crotch_pt = None
    if lh is not None and la is not None:
        hip_y = max(lh[1], rh[1]) if rh is not None else lh[1]
        knee_y = min(la[1], ra[1]) if ra is not None else la[1]
        for y in range(hip_y + 5, min(knee_y, body_mask.shape[0] - 1)):
            row = body_mask[y, :]
            cols = np.where(row > 0)[0]
            if len(cols) < 6:  # waist-width drops sharply at leg split
                crotch_pt = (int(cols.mean()) if len(cols) > 0 else int(body_mask.shape[1] // 2), y)
                break

    result = {}
    if ls is not None:
        result["strap_left"] = ls
    if rs is not None:
        result["strap_right"] = rs
    if neck is not None:
        result["neck"] = neck
    if armpit_left is not None:
        result["armpit_left"] = armpit_left
    if armpit_right is not None:
        result["armpit_right"] = armpit_right
    if waist_left is not None:
        result["waist_left"] = waist_left
    if waist_right is not None:
        result["waist_right"] = waist_right
    if navel_pt is not None:
        result["navel"] = navel_pt
    if crotch_pt is not None:
        result["crotch"] = crotch_pt
    if lh is not None:
        result["hip_left"] = lh
    if rh is not None:
        result["hip_right"] = rh
    if le is not None:
        result["elbow_left"] = le
    if re is not None:
        result["elbow_right"] = re
    if lw is not None:
        result["wrist_left"] = lw
    if rw is not None:
        result["wrist_right"] = rw
    if la is not None:
        result["ankle_left"] = la
    if ra is not None:
        result["ankle_right"] = ra

    # Hem: bottom of body (from silhouette mask)
    hem_y = int(rows.max())
    hem_x = int(cols.mean())
    result["hem_left"] = (hem_x, hem_y)

    # Shoulder positions for flare/taper fallback
    if ls is not None:
        result["left_shoulder"] = ls
    if rs is not None:
        result["right_shoulder"] = rs

    return result if result else None
