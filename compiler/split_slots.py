#!/usr/bin/env python3
import os
from PIL import Image, ImageChops
from compiler.category_registry import is_upper_body as _cat_is_upper_body

def split_slots(garment_image: Image.Image, category: str, base_rig_dir: str) -> dict:
    """
    Splits a garment image into multiple Z-order layers using rig region masks.
    For dresses/topwear:
      - sleeves: Garment intersected with arm_region mask
      - body: Garment minus arm_region mask
    """
    width, height = garment_image.size
    layers_dict = {}
    
    # Paths to masks
    arm_mask_path = os.path.join(base_rig_dir, "masks", "arm_region.png")
    
    # Only split upper-body categories
    upper = _cat_is_upper_body(category)
    
    if upper and os.path.exists(arm_mask_path):
        print("Splitting upper body garment into body and sleeves...")
        arm_mask = Image.open(arm_mask_path).convert("RGBA")
        arm_alpha = arm_mask.split()[-1]
        
        # 1. Sleeves layer: Garment intersected with arm mask
        sleeves = Image.new("RGBA", garment_image.size, (0, 0, 0, 0))
        sleeves.paste(garment_image, (0, 0), mask=arm_alpha)
        
        # 2. Body layer: Garment minus arm mask
        inverted_arm_alpha = ImageChops.invert(arm_alpha)
        body = Image.new("RGBA", garment_image.size, (0, 0, 0, 0))
        body.paste(garment_image, (0, 0), mask=inverted_arm_alpha)
        
        # Clean up empty layers
        # Check if layers have any non-transparent pixels
        if body.getbbox():
            layers_dict["clothing_front"] = body
        if sleeves.getbbox():
            layers_dict["sleeves_front"] = sleeves
            
        print(f"Created layers: {list(layers_dict.keys())}")
    else:
        # Default: No split
        # We assign it to clothing_front (Z: 50)
        layers_dict["clothing_front"] = garment_image
        
    return layers_dict
