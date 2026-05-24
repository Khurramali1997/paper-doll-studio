"""Semantic annotation orchestrator for garment assets.

Calls garment_schema, danbooru_mapper, anime_segmenter, and anime_detector
in sequence, returning a unified annotation dict grounded in the 768×768
paper-doll mask geometry. Every sub-call degrades gracefully — a missing
model or import produces an empty section, never a crash.
"""

import base64
import json
import os
from typing import Dict, Optional

import cv2
import numpy as np


def _load_rig_anchors(base_rig_dir: str) -> Optional[Dict]:
    rig_path = os.path.join(base_rig_dir, "rig.json")
    if not os.path.exists(rig_path):
        return None
    try:
        with open(rig_path) as f:
            return json.load(f).get("anchors")
    except Exception:
        return None


def _mask_to_b64_png(mask: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", mask)
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def _extract_mask_geometry(mask_bin: np.ndarray, base_rig_dir: Optional[str]) -> Dict:
    result = {
        "mask_overlap_face_px": 0,
        "mask_overlap_hair_px": 0,
        "in_allowed_region_pct": 1.0,
    }
    if not base_rig_dir:
        return result

    masks_dir = os.path.join(base_rig_dir, "masks")

    for attr, fname in [("mask_overlap_face_px", "face_forbidden_region.png"),
                        ("mask_overlap_hair_px", "hair_forbidden_region.png")]:
        path = os.path.join(masks_dir, fname)
        if os.path.exists(path):
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                bin_img = (img > 10).astype(np.uint8) * 255
                result[attr] = int(np.count_nonzero(cv2.bitwise_and(mask_bin, bin_img)))

    body_path = os.path.join(masks_dir, "body_silhouette.png")
    if os.path.exists(body_path):
        body = cv2.imread(body_path, cv2.IMREAD_GRAYSCALE)
        if body is not None:
            body_bin = (body > 10).astype(np.uint8) * 255
            in_region = int(np.count_nonzero(cv2.bitwise_and(mask_bin, body_bin)))
            total = int(np.count_nonzero(mask_bin))
            result["in_allowed_region_pct"] = round(in_region / total, 4) if total > 0 else 1.0

    return result


def annotate(
    garment_rgba: np.ndarray,
    mask_bin: np.ndarray,
    label: str,
    rig_anchors: Optional[Dict] = None,
    base_rig_dir: Optional[str] = None,
) -> Dict:
    """Return a unified semantic annotation dict for one garment asset.

    garment_rgba is BGRA uint8 (OpenCV channel order).
    mask_bin is uint8 binary 0/255.
    """
    anchors = rig_anchors
    if anchors is None and base_rig_dir:
        anchors = _load_rig_anchors(base_rig_dir)

    # --- DeepFashion2 ---
    df2_block: Dict = {}
    try:
        from compiler.garment_schema import DF2_CATEGORY_MAP, extract_landmarks
        lbl = label.lower().split("_")[0]
        landmarks = extract_landmarks(mask_bin, label, rig_anchors=anchors)
        df2_block = {
            "category": lbl,
            "df2_category_id": DF2_CATEGORY_MAP.get(lbl),
            "landmarks": landmarks,
        }
    except Exception as e:
        print(f"semantic_layer: deepfashion2 failed: {e}")

    # --- Danbooru ---
    danbooru_block: Dict = {}
    try:
        from compiler.danbooru_mapper import get_danbooru_hints
        danbooru_block = get_danbooru_hints(
            label,
            df2_block.get("landmarks", {}),
            mask_bin=mask_bin,
            rig_anchors=anchors,
        )
    except Exception as e:
        print(f"semantic_layer: danbooru hints failed: {e}")

    # --- Anime segmentation ---
    anime_seg_block: Dict = {}
    try:
        from PIL import Image as _PIL
        from compiler.anime_segmenter import segment_anime_foreground
        channels = garment_rgba.shape[2] if garment_rgba.ndim == 3 else 3
        rgb = cv2.cvtColor(garment_rgba, cv2.COLOR_BGRA2RGB if channels == 4 else cv2.COLOR_BGR2RGB)
        anime_mask = segment_anime_foreground(_PIL.fromarray(rgb, mode="RGB"))
        if anime_mask is not None:
            anime_seg_block = {
                "foreground_mask_b64": _mask_to_b64_png(anime_mask),
                "pixel_count": int(np.count_nonzero(anime_mask)),
            }
    except Exception as e:
        print(f"semantic_layer: anime segmentation failed: {e}")

    # --- Forbidden regions ---
    forbidden_block: Dict = {"faces": [], "hands": []}
    try:
        from compiler.anime_detector import detect_anime_faces, detect_anime_hands
        channels = garment_rgba.shape[2] if garment_rgba.ndim == 3 else 3
        bgr = cv2.cvtColor(garment_rgba, cv2.COLOR_BGRA2BGR) if channels == 4 else garment_rgba[:, :, :3]
        rgb_arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        forbidden_block["faces"] = detect_anime_faces(bgr)
        forbidden_block["hands"] = detect_anime_hands(rgb_arr)
    except Exception as e:
        print(f"semantic_layer: forbidden region detection failed: {e}")

    return {
        "deepfashion2": df2_block,
        "danbooru": danbooru_block,
        "anime_segmentation": anime_seg_block,
        "forbidden_regions": forbidden_block,
        "mask_geometry": _extract_mask_geometry(mask_bin, base_rig_dir),
    }
