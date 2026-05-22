#!/usr/bin/env python3
import os
from PIL import Image, ImageChops
from compiler.category_registry import is_fitted as _is_fitted

def count_non_transparent(img: Image.Image) -> int:
    """Helper to count non-transparent pixels in an RGBA image."""
    alpha = img.getchannel('A')
    return sum(1 for p in alpha.tobytes() if p > 10)

def has_alpha_channel(img: Image.Image) -> bool:
    """Check if image has a non-trivial alpha channel (any transparent pixel)."""
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    alpha = img.getchannel('A')
    total = alpha.size[0] * alpha.size[1]
    opaque = sum(1 for b in alpha.tobytes() if b > 254)
    return opaque < total

def validate_asset(
    garment_image: Image.Image,
    category: str,
    base_rig_dir: str,
    crop_to_allowed_region: bool = False,
    auto_clean_face: bool = False,
) -> tuple[Image.Image, dict]:
    """
    Validates the garment image against the rig masks.
    Detects if the asset violates allowed boundaries (e.g. overlaps the face).

    By default (crop_to_allowed_region=False) the allowed-region check only
    warns — it does NOT destructively crop the garment.  This preserves dress
    silhouettes that naturally extend beyond the naked body contour.

    Returns (cleaned_garment_image, report_dict).
    """
    report = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "face_overlap_pixels": 0,
        "garbage_pixels": 0,
        "crop_to_allowed_region_applied": False,
    }
    
    # 1. Canvas Size Check
    rig_json_path = os.path.join(base_rig_dir, "rig.json")
    target_size = (768, 768)
    if os.path.exists(rig_json_path):
        import json
        try:
            with open(rig_json_path, "r") as f:
                rig_data = json.load(f)
                target_size = tuple(rig_data["canvas"])
        except Exception:
            pass
            
    if garment_image.size != target_size:
        report["valid"] = False
        report["errors"].append(f"Canvas size mismatch. Expected {target_size}, got {garment_image.size}")
        return garment_image, report

    # 2. Extract garment pixel count
    garment_pixels = count_non_transparent(garment_image)
    if garment_pixels == 0:
        report["valid"] = False
        report["errors"].append("Garment image is fully transparent or empty.")
        return garment_image, report

    # 3. Alpha channel warning
    if not has_alpha_channel(garment_image):
        report["warnings"].append(
            "This PNG is not transparent; background removal required."
        )

    # 4. Forbidden Region Overlap Checks (Face & Hair)
    face_mask_path = os.path.join(base_rig_dir, "masks", "face_forbidden_region.png")
    cleaned_image = garment_image.copy()
    
    if os.path.exists(face_mask_path):
        face_mask = Image.open(face_mask_path).convert("RGBA")
        face_alpha = face_mask.split()[-1]
        
        # Calculate overlap
        overlap_img = Image.new("RGBA", garment_image.size, (0, 0, 0, 0))
        overlap_img.paste(garment_image, (0, 0), mask=face_alpha)
        face_overlap = count_non_transparent(overlap_img)
        report["face_overlap_pixels"] = face_overlap
        
        if face_overlap > 500 or (face_overlap / max(garment_pixels, 1)) > 0.10:
            # Severe overlap — still reject (garment is clearly on the face)
            report["valid"] = False
            report["errors"].append(f"Severe face overlap detected ({face_overlap}px). Garment covers face region.")
        elif face_overlap > 0 and auto_clean_face:
            # Optional autoclean for minor overlap (disabled by default)
            print(f"Cleaning minor face overlap of {face_overlap}px...")
            inverted_face_alpha = ImageChops.invert(face_alpha)
            temp = Image.new("RGBA", cleaned_image.size, (0, 0, 0, 0))
            temp.paste(cleaned_image, (0, 0), mask=inverted_face_alpha)
            cleaned_image = temp
            report["warnings"].append(f"Auto-cleaned face overlap of {face_overlap}px.")
        elif face_overlap > 0:
            # Minor overlap — warn only, no destructive change
            report["warnings"].append(
                f"Minor face overlap detected ({face_overlap}px). "
                "Enable auto_clean_face to crop, or adjust anchors."
            )

    # 5. Background Garbage Check (non-destructive by default)
    cat = category.lower()
    allowed_region_path = None
    if _is_fitted(cat):
        allowed_region_path = os.path.join(
            base_rig_dir, "masks", f"{cat}_allowed_region.png",
        )
        if not os.path.exists(allowed_region_path):
            allowed_region_path = None

    if not allowed_region_path:
        allowed_region_path = os.path.join(base_rig_dir, "masks", "body_silhouette.png")

    hair_path = os.path.join(base_rig_dir, "masks", "hair_forbidden_region.png")

    if os.path.exists(allowed_region_path) and os.path.exists(hair_path):
        allowed_region = Image.open(allowed_region_path).convert("RGBA")
        hair = Image.open(hair_path).convert("RGBA")

        # Combined allowed silhouette = category allowed region + hair
        region_alpha = allowed_region.split()[-1]
        hair_alpha = hair.split()[-1]
        allowed_alpha = ImageChops.screen(region_alpha, hair_alpha)

        # Calculate pixels outside allowed region
        inverted_allowed = ImageChops.invert(allowed_alpha)
        outside_img = Image.new("RGBA", garment_image.size, (0, 0, 0, 0))
        outside_img.paste(cleaned_image, (0, 0), mask=inverted_allowed)
        outside_pixels = count_non_transparent(outside_img)
        report["garbage_pixels"] = outside_pixels

        if outside_pixels > 0 and crop_to_allowed_region:
            # Destructive crop — only when user explicitly enables it
            print(f"Auto-cropping background garbage ({outside_pixels}px) using {os.path.basename(allowed_region_path)}...")
            temp = Image.new("RGBA", cleaned_image.size, (0, 0, 0, 0))
            temp.paste(cleaned_image, (0, 0), mask=allowed_alpha)
            cleaned_image = temp
            report["crop_to_allowed_region_applied"] = True
            report["warnings"].append(
                f"Auto-cropped background garbage ({outside_pixels}px) "
                f"using {os.path.basename(allowed_region_path)}."
            )
        elif outside_pixels > 0:
            # Non-destructive: warn only
            report["warnings"].append(
                f"Background pixels outside allowed region ({outside_pixels}px). "
                f"Enable crop_to_allowed_region to remove them."
            )
            
    return cleaned_image, report
