"""Anime face detection (OpenCV LBP cascade) + hand detection (MediaPipe).

Both functions return [] gracefully on any error — missing cascade, missing
mediapipe, or inference failure. The cascade (~2.6 MB) is auto-downloaded
from nagadomi/lbpcascade_animeface on first call.
"""

import os
import urllib.request
from typing import Dict, List, Optional

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
CASCADE_PATH = os.path.join(MODELS_DIR, "lbpcascade_animeface.xml")
CASCADE_URL = (
    "https://raw.githubusercontent.com/nagadomi/lbpcascade_animeface/"
    "master/lbpcascade_animeface.xml"
)
HAND_MODEL_PATH = os.path.join(MODELS_DIR, "hand_landmarker.task")
HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)

_cascade: Optional[cv2.CascadeClassifier] = None


def ensure_cascade() -> Optional[cv2.CascadeClassifier]:
    global _cascade
    if _cascade is not None:
        return _cascade
    if not os.path.exists(CASCADE_PATH):
        os.makedirs(MODELS_DIR, exist_ok=True)
        print(f"Downloading lbpcascade_animeface → {CASCADE_PATH} (~2.6 MB)…")
        try:
            urllib.request.urlretrieve(CASCADE_URL, CASCADE_PATH)
        except Exception as e:
            print(f"anime_detector: cascade download failed: {e}")
            return None
    try:
        clf = cv2.CascadeClassifier(CASCADE_PATH)
        if clf.empty():
            return None
        _cascade = clf
        return _cascade
    except Exception as e:
        print(f"anime_detector: cascade load failed: {e}")
        return None


def detect_anime_faces(image_bgr: np.ndarray) -> List[Dict]:
    """Detect anime faces. Returns list of {"bbox": [x, y, w, h]}."""
    clf = ensure_cascade()
    if clf is None:
        return []
    try:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        detections = clf.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
        )
        if len(detections) == 0:
            return []
        return [{"bbox": [int(x), int(y), int(w), int(h)]} for x, y, w, h in detections]
    except Exception as e:
        print(f"anime_detector: face detection failed: {e}")
        return []


def detect_anime_hands(image_rgb: np.ndarray) -> List[Dict]:
    """Detect hands via MediaPipe HandLandmarker (tasks API, v0.10+).

    Returns list of {"bbox":[x,y,w,h], "landmarks":[[x,y],...]}.
    Auto-downloads hand_landmarker.task (~8 MB) on first call.
    """
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except (ImportError, AttributeError):
        return []

    if not os.path.exists(HAND_MODEL_PATH):
        os.makedirs(MODELS_DIR, exist_ok=True)
        print(f"Downloading hand_landmarker model → {HAND_MODEL_PATH} (~8 MB)…")
        try:
            urllib.request.urlretrieve(HAND_MODEL_URL, HAND_MODEL_PATH)
        except Exception as e:
            print(f"anime_detector: hand model download failed: {e}")
            return []

    h, w = image_rgb.shape[:2]
    try:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
        base_opts = mp_python.BaseOptions(model_asset_path=HAND_MODEL_PATH)
        opts = mp_vision.HandLandmarkerOptions(
            base_options=base_opts,
            running_mode=mp_vision.RunningMode.IMAGE,
            num_hands=4,
            min_hand_detection_confidence=0.5,
        )
        with mp_vision.HandLandmarker.create_from_options(opts) as detector:
            result = detector.detect(mp_image)

        if not result.hand_landmarks:
            return []

        output = []
        for hand_lm in result.hand_landmarks:
            pts = [[int(lm.x * w), int(lm.y * h)] for lm in hand_lm]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bbox = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            output.append({"bbox": bbox, "landmarks": pts})
        return output
    except Exception as e:
        print(f"anime_detector: hand detection failed: {e}")
        return []
