import os
from PIL import Image

def analyze_body():
    img_path = "body_ref_transparent.png"
    if not os.path.exists(img_path):
        print("body_ref_transparent.png not found!")
        return
        
    img = Image.open(img_path).convert("RGBA")
    width, height = img.size
    print(f"Image dimensions: {width}x{height}")
    
    # We want to find:
    # 1. Neck center: usually near the top of the body, just below the chin
    # 2. Shoulders: where the arm connections start.
    # 3. Waist: the narrowest part of the torso.
    # 4. Hips: the widest part of the pelvic area.
    
    # Let's print the bounding box first
    bbox = img.getbbox()
    print(f"Body bounding box: {bbox}")
    
    # Scan horizontal rows to find width of non-transparent body pixels
    rows = []
    for y in range(height):
        row_pixels = []
        for x in range(width):
            r, g, b, a = img.getpixel((x, y))
            if a > 10:
                row_pixels.append(x)
        if row_pixels:
            rows.append((y, min(row_pixels), max(row_pixels), len(row_pixels)))
            
    # Print some key segments to understand vertical structure
    # Neck: y is around 180-210
    # Shoulders: y is around 220-270
    # Waist: y is around 350-420
    # Hips: y is around 450-520
    print("\nRow samples (y, min_x, max_x, width):")
    for y in range(bbox[1], bbox[3], 15):
        matching = [r for r in rows if r[0] == y]
        if matching:
            print(f"y={y}: min_x={matching[0][1]}, max_x={matching[0][2]}, width={matching[0][3]}")

if __name__ == "__main__":
    analyze_body()
