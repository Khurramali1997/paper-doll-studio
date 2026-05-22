#!/usr/bin/env python3
import math
from PIL import Image

def align_asset(image: Image.Image, x_offset=0, y_offset=0, scale=1.0, candidate_anchors=None, rig_anchors=None) -> Image.Image:
    """
    Applies spatial transformations to align the clothing asset to the rig.
    Supports either manual (x_offset, y_offset, scale) or anchor-based registration.
    """
    width, height = image.size
    
    # If anchor registration is requested and we have valid points
    if candidate_anchors and rig_anchors and "neck" in candidate_anchors and "neck" in rig_anchors:
        print("Performing anchor-based alignment...")
        c_neck = candidate_anchors["neck"]
        r_neck = rig_anchors["neck"]
        
        # Calculate scale based on shoulder distance if available
        if ("left_shoulder" in candidate_anchors and "right_shoulder" in candidate_anchors and
            "left_shoulder" in rig_anchors and "right_shoulder" in rig_anchors):
            
            c_shoulder_dist = math.hypot(
                candidate_anchors["right_shoulder"][0] - candidate_anchors["left_shoulder"][0],
                candidate_anchors["right_shoulder"][1] - candidate_anchors["left_shoulder"][1]
            )
            r_shoulder_dist = math.hypot(
                rig_anchors["right_shoulder"][0] - rig_anchors["left_shoulder"][0],
                rig_anchors["right_shoulder"][1] - rig_anchors["left_shoulder"][1]
            )
            
            if c_shoulder_dist > 0:
                scale = r_shoulder_dist / c_shoulder_dist
                print(f"Computed anchor scale factor: {scale:.4f}")
        
        # Translate to match neck anchors
        # Target neck position = rig neck. Candidate neck position under scale needs to match.
        # Neck relative to center is: c_neck_scaled = [c_neck[0] * scale, c_neck[1] * scale]
        # X/Y offsets to center and translate:
        x_offset = r_neck[0] - (c_neck[0] * scale)
        y_offset = r_neck[1] - (c_neck[1] * scale)
        print(f"Computed anchor offset: X={x_offset:.1f}, Y={y_offset:.1f}")

    # Apply manual or computed transform
    if x_offset == 0 and y_offset == 0 and scale == 1.0:
        return image

    print(f"Applying transform: Offset=({x_offset:.2f}, {y_offset:.2f}), Scale={scale:.4f}")
    
    # We can perform the scaling and translation using Pillow transforms
    # A standard affine transform maps (x, y) in destination to (u, v) in source.
    # [ u ] = [ a  b  c ] [ x ]
    # [ v ]   [ d  e  f ] [ y ]
    #                     [ 1 ]
    # Let's scale around the center of the canvas: (cx, cy) = (width/2, height/2)
    # Forward: x' = scale * (x - cx) + cx + x_offset
    # Inverse: x = (x' - x_offset - cx)/scale + cx = (1/scale)*x' + (cx - (x_offset + cx)/scale)
    cx, cy = width / 2, height / 2
    
    if scale == 0:
        scale = 1.0
        
    a = 1.0 / scale
    b = 0.0
    c = cx - (x_offset + cx) / scale
    
    d = 0.0
    e = 1.0 / scale
    f = cy - (y_offset + cy) / scale
    
    aligned = image.transform(
        (width, height),
        Image.Transform.AFFINE,
        (a, b, c, d, e, f),
        resample=Image.Resampling.BILINEAR
    )
    
    return aligned
