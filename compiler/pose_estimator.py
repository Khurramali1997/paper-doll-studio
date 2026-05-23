"""MediaPipe pose estimation → OpenPose-compatible keypoints.

Auto-downloads the ``pose_landmarker_full.task`` model file on first use to
``models/pose_landmarker_full.task``. Subsequent calls reuse the cached file.

The output mapping converts MediaPipe's 33-landmark BlazePose topology to the
18-keypoint COCO topology used by ControlNet OpenPose. This makes the
generated stick figure drop-in compatible with off-the-shelf OpenPose
conditioning workflows.
"""

import os
import urllib.request
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
POSE_MODEL_PATH = os.path.join(MODELS_DIR, "pose_landmarker_full.task")
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)

# MediaPipe BlazePose landmark indices (subset that maps to OpenPose).
MP_NOSE          = 0
MP_LEFT_EYE      = 2
MP_RIGHT_EYE     = 5
MP_LEFT_EAR      = 7
MP_RIGHT_EAR     = 8
MP_LEFT_SHOULDER = 11
MP_RIGHT_SHOULDER = 12
MP_LEFT_ELBOW    = 13
MP_RIGHT_ELBOW   = 14
MP_LEFT_WRIST    = 15
MP_RIGHT_WRIST   = 16
MP_LEFT_HIP      = 23
MP_RIGHT_HIP     = 24
MP_LEFT_KNEE     = 25
MP_RIGHT_KNEE    = 26
MP_LEFT_ANKLE    = 27
MP_RIGHT_ANKLE   = 28


def ensure_model() -> str:
    """Download the pose model on first use; return its path."""
    if os.path.exists(POSE_MODEL_PATH):
        return POSE_MODEL_PATH
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"Downloading pose model → {POSE_MODEL_PATH} (one-time)…")
    urllib.request.urlretrieve(POSE_MODEL_URL, POSE_MODEL_PATH)
    return POSE_MODEL_PATH


def estimate_pose(image: Image.Image) -> Optional[Dict[str, Tuple[int, int]]]:
    """Run MediaPipe pose; return OpenPose-keyed joint dict in image pixel coords.

    Returns ``None`` if no pose is detected or the model fails to load.

    Note: MediaPipe is trained on real photographs. Stylized / illustrated
    bodies sometimes confuse it. The caller should fall back to anchor-based
    pose if this returns ``None``.
    """
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except ImportError:
        return None

    model_path = ensure_model()

    if image.mode != "RGB":
        # MediaPipe expects RGB without alpha. Composite onto white to drop alpha.
        if image.mode == "RGBA":
            white = Image.new("RGB", image.size, (255, 255, 255))
            white.paste(image, mask=image.getchannel("A"))
            image = white
        else:
            image = image.convert("RGB")

    arr = np.array(image, dtype=np.uint8)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)

    base_opts = mp_python.BaseOptions(model_asset_path=model_path)
    opts = mp_vision.PoseLandmarkerOptions(
        base_options=base_opts,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_poses=1,
    )
    with mp_vision.PoseLandmarker.create_from_options(opts) as detector:
        result = detector.detect(mp_image)

    if not result.pose_landmarks:
        return None

    landmarks = result.pose_landmarks[0]
    h, w = arr.shape[:2]

    def pt(idx):
        lm = landmarks[idx]
        return (int(round(lm.x * w)), int(round(lm.y * h)))

    # Neck isn't a MediaPipe landmark — synthesize as midpoint of shoulders.
    ls = pt(MP_LEFT_SHOULDER)
    rs = pt(MP_RIGHT_SHOULDER)
    neck = ((ls[0] + rs[0]) // 2, (ls[1] + rs[1]) // 2)

    # MediaPipe "left" = anatomical left = canvas RIGHT. Map to our convention
    # (left_shoulder = canvas-low-x = anatomical right).
    return {
        "nose":           pt(MP_NOSE),
        "neck":           neck,
        "right_shoulder": ls,   # MP's anatomical-left → canvas right side
        "right_elbow":    pt(MP_LEFT_ELBOW),
        "right_wrist":    pt(MP_LEFT_WRIST),
        "left_shoulder":  rs,
        "left_elbow":     pt(MP_RIGHT_ELBOW),
        "left_wrist":     pt(MP_RIGHT_WRIST),
        "right_hip":      pt(MP_LEFT_HIP),
        "right_knee":     pt(MP_LEFT_KNEE),
        "right_ankle":    pt(MP_LEFT_ANKLE),
        "left_hip":       pt(MP_RIGHT_HIP),
        "left_knee":      pt(MP_RIGHT_KNEE),
        "left_ankle":     pt(MP_RIGHT_ANKLE),
        "right_eye":      pt(MP_LEFT_EYE),
        "left_eye":       pt(MP_RIGHT_EYE),
        "right_ear":      pt(MP_LEFT_EAR),
        "left_ear":       pt(MP_RIGHT_EAR),
    }
