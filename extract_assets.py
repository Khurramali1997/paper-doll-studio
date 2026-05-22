import os
from psd_tools import PSDImage
from PIL import Image

def extract_standardized_assets(psd_path, output_dir):
    print(f"=== Extracting Standardized Layers from {psd_path} ===")
    if not os.path.exists(psd_path):
        print(f"Error: Master PSD file '{psd_path}' not found!")
        return

    psd = PSDImage.open(psd_path)
    print(f"Canvas Dimensions: {psd.width}x{psd.height}")
    os.makedirs(output_dir, exist_ok=True)
    
    def process_layer(layer, path_prefix=""):
        if layer.is_group():
            # If the layer is a group, recursively traverse it
            group_name = layer.name.lower().strip().replace(" ", "_").replace("-", "_")
            print(f"Entering group: {layer.name}")
            for child in layer:
                process_layer(child, f"{path_prefix}{group_name}_")
        else:
            try:
                image = layer.topil()
                if image is not None:
                    # Create a transparent full canvas image to ensure exact overlay alignment
                    full_image = Image.new("RGBA", (psd.width, psd.height), (0, 0, 0, 0))
                    
                    # Position the layer image at its absolute bounding box coordinate (layer.left, layer.top)
                    left = layer.left
                    top = layer.top
                    full_image.paste(image, (left, top))
                    
                    # Normalize the layer name for a clean, consistent filename
                    clean_name = layer.name.lower().strip().replace(" ", "_").replace("-", "_")
                    
                    # We use the flat name or include the group path prefix if relevant.
                    # Given the standard naming scheme, the layers themselves contain prefixes like 'body_', 'eyes_', etc.
                    # If they are inside groups in PSD, we can prefix them, or just use the layer name.
                    # Let's support both but prioritize the raw layer name if it's already structured.
                    filename = f"{clean_name}.png"
                    output_path = os.path.join(output_dir, filename)
                    
                    full_image.save(output_path, "PNG")
                    print(f"Exported: {filename} (BBox: left={left}, top={top}, size={image.size})")
                else:
                    print(f"Skipped empty layer: {layer.name}")
            except Exception as e:
                print(f"Error exporting layer {layer.name}: {e}")

    for layer in psd:
        process_layer(layer)
    print("=== Extraction Complete ===")

if __name__ == "__main__":
    extract_standardized_assets("character.psd", "public/assets")
