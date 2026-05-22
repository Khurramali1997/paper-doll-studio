#!/usr/bin/env python3
import os
import sys
import json
from psd_tools import PSDImage
from PIL import Image

# Categorization keywords
KEYWORDS = {
    'hair': ['hair', 'bang', 'fringe', 'tail'],
    'eyes': ['eye', 'iris', 'brow', 'lash', 'white'],
    'face': ['face', 'neck', 'ears', 'nose', 'mouth', 'body', 'torso', 'skin', 'head'],
    'wardrobe': ['wear', 'cloth', 'top', 'bottom', 'leg', 'hand', 'glove', 'pants', 'shirt', 'skirt', 'shoe', 'sock']
}

WARDROBE_SLOTS = {
    'topwear': ['top', 'shirt', 'jacket', 'vest', 'coat', 'chest'],
    'bottomwear': ['bottom', 'skirt', 'underwear', 'waist'],
    'legwear': ['leg', 'pant', 'sock', 'shoe', 'boot', 'foot', 'feet'],
    'handwear': ['hand', 'glove', 'arm', 'sleeve']
}

def clean_layer_name(name):
    return name.lower().strip().replace(" ", "_").replace("-", "_")

def get_category(clean_name):
    # Wardrobe is high priority
    if any(w in clean_name for w in KEYWORDS['wardrobe']):
        return 'wardrobe'
    if any(w in clean_name for w in KEYWORDS['hair']):
        return 'hair'
    if any(w in clean_name for w in KEYWORDS['eyes']):
        return 'eyes'
    return 'face'  # Default category (base body)

def get_wardrobe_slot(clean_name):
    for slot, kws in WARDROBE_SLOTS.items():
        if any(kw in clean_name for kw in kws):
            return slot
    return 'accessories'

def get_option_value(clean_name, slot, psd_file_name=None):
    if 'skin_wear' in clean_name or 'naked' in clean_name:
        return 'skin_wear'
    if 'clothing' in clean_name or 'clothed' in clean_name:
        return 'clothing'
    
    # Extract option value by stripping out slot and standard terms
    val = clean_name
    to_remove = [slot, 'wear', 'cloth', 'l', 'r', 'left', 'right']
    if slot in WARDROBE_SLOTS:
        to_remove.extend(WARDROBE_SLOTS[slot])
        
    for word in to_remove:
        val = val.replace(word, '')
        
    val = val.strip('_')
    if not val:
        if psd_file_name:
            fn_lower = psd_file_name.lower()
            if 'clothed' in fn_lower or 'clothing' in fn_lower:
                return 'clothing'
            if 'naked' in fn_lower or 'skin' in fn_lower:
                return 'skin_wear'
        
        # Fallback to exact slot matches or orientation suffixes mapping to skin_wear
        if (clean_name == slot or 
            clean_name.endswith('_l') or 
            clean_name.endswith('_r') or 
            clean_name.endswith('_left') or 
            clean_name.endswith('_right')):
            return 'skin_wear'
            
        return 'default'
    return val

def flatten_layers(node):
    flat = []
    if node.is_group():
        for child in node:
            flat.extend(flatten_layers(child))
    else:
        flat.append(node)
    return flat

def process_psd(psd_path, output_dir, config_path):
    print(f"=== Starting PSD to Interactive Prototype Pipeline ===")
    print(f"PSD Source: {psd_path}")
    print(f"Assets Destination: {output_dir}")
    print(f"Config Destination: {config_path}")

    if not os.path.exists(psd_path):
        print(f"Error: PSD file '{psd_path}' not found!")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    psd = PSDImage.open(psd_path)
    print(f"Canvas Dimensions: {psd.width}x{psd.height}")

    # Flatten layers to assign sequential Z-indexes (bottom-to-top order)
    raw_layers = []
    for layer in psd:
        raw_layers.extend(flatten_layers(layer))
    
    layers_config = []
    wardrobe_mapping = {}

    print(f"Found {len(raw_layers)} flat layers. Extracting and building metadata...")

    for idx, layer in enumerate(raw_layers):
        clean_name = clean_layer_name(layer.name)
        
        # Determine relative z-index (scale by 10 for clean spacing and manual tweaks)
        z_index = (idx + 1) * 10
        
        try:
            image = layer.topil()
            if image is None:
                print(f"Skipped empty layer: {layer.name}")
                continue

            # Check if layer has any content (non-transparent pixels)
            # basic bounding box check
            if layer.width == 0 or layer.height == 0:
                print(f"Skipped 0-size layer: {layer.name}")
                continue

            # Paste into a full-sized transparent canvas to preserve placement alignment
            full_canvas = Image.new("RGBA", (psd.width, psd.height), (0, 0, 0, 0))
            full_canvas.paste(image, (layer.left, layer.top))

            filename = f"{clean_name}.png"
            dest_path = os.path.join(output_dir, filename)
            full_canvas.save(dest_path, "PNG")
            
            category = get_category(clean_name)
            
            # Metadata object for each layer
            layer_meta = {
                "id": clean_name,
                "name": layer.name.strip(),
                "file": filename,
                "z": z_index,
                "category": category
            }

            # Handle wardrobe categorization
            if category == 'wardrobe':
                slot = get_wardrobe_slot(clean_name)
                opt_val = get_option_value(clean_name, slot, os.path.basename(psd_path))
                layer_meta["subcategory"] = slot
                layer_meta["optionValue"] = opt_val
                
                # Initialize wardrobe slot in configuration tracking
                if slot not in wardrobe_mapping:
                    wardrobe_mapping[slot] = {
                        "name": slot.replace("wear", "wear").capitalize(),
                        "layers": []
                    }
                wardrobe_mapping[slot]["layers"].append({
                    "id": clean_name,
                    "optionValue": opt_val
                })
            elif category == 'hair':
                subcat = 'hair_front' if any(w in clean_name for w in ['front', 'bang', 'fringe']) else 'hair_back'
                layer_meta["subcategory"] = subcat
                layer_meta["toggleable"] = True
                layer_meta["defaultVisible"] = True
                layer_meta["dyeable"] = True
            elif category == 'eyes':
                # Subcategory mapping
                if 'white' in clean_name:
                    subcat = 'eyewhite'
                elif 'iris' in clean_name or 'iride' in clean_name:
                    subcat = 'irides'
                    layer_meta["dyeable"] = True  # Irides are dyeable
                elif 'brow' in clean_name:
                    subcat = 'eyebrows'
                elif 'lash' in clean_name:
                    subcat = 'eyelashes'
                else:
                    subcat = 'eyes_other'
                layer_meta["subcategory"] = subcat
                layer_meta["toggleable"] = True
                layer_meta["defaultVisible"] = True
            else:  # face / body
                if 'neck' in clean_name:
                    subcat = 'neck'
                elif 'ears' in clean_name or 'ear' in clean_name:
                    subcat = 'ears'
                    layer_meta["toggleable"] = True
                    layer_meta["defaultVisible"] = True
                elif 'nose' in clean_name:
                    subcat = 'nose'
                    layer_meta["toggleable"] = True
                    layer_meta["defaultVisible"] = True
                elif 'mouth' in clean_name:
                    subcat = 'mouth'
                    layer_meta["toggleable"] = True
                    layer_meta["defaultVisible"] = True
                else:
                    subcat = 'face'
                layer_meta["subcategory"] = subcat

            layers_config.append(layer_meta)
            print(f"Exported [{category.upper()} -> {layer_meta.get('subcategory', 'None')}]: {filename} (Z: {z_index})")
            
        except Exception as e:
            print(f"Error processing layer '{layer.name}': {e}")

    # Build structured wardrobe options
    wardrobe_config = {}
    for slot, slot_data in wardrobe_mapping.items():
        # Get all unique option values
        unique_vals = list(set(l["optionValue"] for l in slot_data["layers"]))
        
        # Sort option values so 'skin_wear' comes first, then 'clothing', then others
        def sort_key(v):
            if v == 'skin_wear': return 0
            if v == 'clothing': return 1
            return 2
        unique_vals.sort(key=sort_key)

        options_list = []
        for val in unique_vals:
            # Build option display name
            display_name = val.replace("_", " ").title()
            if val == 'skin_wear':
                display_name = 'Naked / Skin Wear'
            elif val == 'clothing':
                display_name = 'Cozy Clothing'
            
            # Find layers associated with this option value
            assoc_layers = [l["id"] for l in slot_data["layers"] if l["optionValue"] == val]
            
            # Standard paper doll overlay helper:
            # If the option is a clothing item, overlay it on top of the 'skin_wear' layer (if it exists)
            # so the character body doesn't have holes under the clothing.
            skin_wear_layers = [l["id"] for l in slot_data["layers"] if l["optionValue"] == 'skin_wear']
            if val != 'skin_wear' and skin_wear_layers:
                assoc_layers = skin_wear_layers + assoc_layers
                
            options_list.append({
                "value": val,
                "name": display_name,
                "layers": assoc_layers
            })
            
        # Add a default 'none' option
        options_list.append({
            "value": "none",
            "name": "Invisible / None",
            "layers": []
        })

        # Default value is 'skin_wear' if available, otherwise the first option
        default_val = 'skin_wear' if 'skin_wear' in unique_vals else (unique_vals[0] if unique_vals else 'none')

        wardrobe_config[slot] = {
            "name": slot.replace("wear", "wear").capitalize(),
            "options": options_list,
            "defaultValue": default_val
        }

    # Build the final Javascript configuration object
    config_data = {
        "canvas": {
            "width": psd.width,
            "height": psd.height
        },
        "layers": layers_config,
        "wardrobe": wardrobe_config,
        "defaults": {
            "theme": "dark",
            "zoom": 1.0,
            "showGrid": True
        }
    }

    # Write Javascript file
    try:
        with open(config_path, "w") as f:
            f.write("// Dynamic Paper Doll Studio Configuration\n")
            f.write("// Automatically generated by psd_to_prototype.py\n\n")
            f.write("const DOLL_CONFIG = ")
            json.dump(config_data, f, indent=2)
            f.write(";\n")
        print(f"=== Pipeline Completed Successfully ===")
        print(f"Generated config file: {config_path}")
    except Exception as e:
        print(f"Error writing config file: {e}")

if __name__ == "__main__":
    psd_file = sys.argv[1] if len(sys.argv) > 1 else "character.psd"
    process_psd(psd_file, "public/assets", "doll_config.js")
