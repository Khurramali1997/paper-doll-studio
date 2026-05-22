#!/usr/bin/env python3
from PIL import Image

def normalize_canvas(image: Image.Image, target_size=(768, 768)) -> Image.Image:
    """
    Normalizes the candidate image to target dimensions.
    If the image size doesn't match, it rescales and overlays it centered on a transparent canvas.
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
        
    if image.size == target_size:
        return image
        
    print(f"Normalizing canvas from {image.size} to {target_size}...")
    normalized = Image.new("RGBA", target_size, (0, 0, 0, 0))
    
    # Scale candidate to fit within target size maintaining aspect ratio
    img_w, img_h = image.size
    tgt_w, tgt_h = target_size
    
    scale = min(tgt_w / img_w, tgt_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    
    if new_w > 0 and new_h > 0:
        scaled_img = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # Center in the target canvas
        paste_x = (tgt_w - new_w) // 2
        paste_y = (tgt_h - new_h) // 2
        normalized.paste(scaled_img, (paste_x, paste_y), scaled_img)
        
    return normalized
