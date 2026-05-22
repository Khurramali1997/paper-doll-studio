# Paper Doll Studio

Local-first character customization pipeline. Import PSD character rigs, manually align wardrobe PNGs over the body ghost, bake to compiled assets, and export portable doll projects.

## Quick Start

```bash
# Start the dev server
npm run dev
# Open http://localhost:8000
```

The server runs Python (FastAPI backend) via npm; `npm run dev:reload` adds uvicorn `--reload`.

## Architecture

```
PSD Importer ──→ Base Rig ──→ Frontend ──→ Compiler ──→ Export
                    │            │            │
                rig.json     DOLL_CONFIG   compiled assets
                masks/       wardrobe/     metadata.json
                base_rig/    state.json    wardrobe_manifest.json
```

PSD ingestion path:
- **Flat PSD** (v0.1): `importers/flat_psd_importer.py` — reads flat (non-grouped) PSD layers, normalizes names via `flat_layer_map.json`, produces canonical composites and split (left/right arm) layers. The live UI uses an in-browser parser (`agPsd`); the Python importer covers batch/scripted builds.

Garment ingestion path (v0.1):
- **Manual placement** for every wardrobe slot — drop PNG → align visually (drag, wheel, scaleX/scaleY, pixel inputs, arrow-key nudge) → optional chroma key and body subtraction → bake natural-dims-centered into a compiled asset.

## Key Features

- **Unified category registry** — `compiler/category_registry.py` is the single source of truth for all 10 wardrobe slots (dress, topwear, bottomwear, skirt, pants, legwear, handwear, outerwear, shoes, accessory). All components import from here.
- **Natural-dims-centered bake** — `js/utils.js` exports `computeBakeGeometry` and `applyBakeTransform`; the bake and the live preview overlay both call the same helper so they cannot drift.
- **Pixel-honest alignment** — Width/Height number inputs read and write the rendered pixel size directly (a 50×50 accessory renders at 50×50 px; a 768 × 768 dress fills the canvas). Independent Scale X / Scale Y for non-uniform fit; uniform Scale slider plus mouse-wheel zoom for ratio-preserving changes; arrow keys nudge by 1 px (Shift = 10 px).
- **Auto-shrink on load** — sources larger than the canvas auto-fit on import so nothing overflows by default; small sources keep their native pixel size.
- **Canonical z-order** — new wardrobe layers receive their category's z value at ingest time (dress=205, topwear=210, outerwear=215, bottomwear=220, skirt/pants=225, legwear=230, shoes=235, handwear=240, accessory=245).
- **Non-destructive validation** — `validate_asset` warns by default; `crop_to_allowed_region=True` is opt-in.
- **Alpha-aware chroma key** — automatically skipped for images that already have transparency.
- **Export ZIP** — bundles dynamic `project.json` (with current wardrobe state), `doll_config.js`, every wardrobe layer PNG, every compiled-asset folder referenced by `wardrobe_manifest.json` (metadata + preview + per-layer PNGs), and the core app files.

## Pipeline

### PSD → Base Rig
```
PSD ──→ FlatPsdImporter.extract_layers() ──→ canonical composites
        │                                        │
    layer_map.json                           write_base_rig_outputs()
    normalization                                   │
    aliases                                     base_rig/*.png
    composites                                base_rig/masks/*.png
    splits                                   base_rig/rig.json
```

### Garment Compilation
```
Upload ──→ alignSettings (x, y, scaleX, scaleY)
   │
   └─→ applyBakeTransform on docW × docH canvas
            │
            └─→ chroma key (auto-skip if alpha)
                     │
                     └─→ optional body subtract
                              │
                              └─→ POST /api/compile-asset
                                       │
                              normalize_canvas
                              validate_asset (warn)
                              split_slots
                                       │
                              public/assets/compiled/{category}/{asset_id}/
                                  metadata.json, preview.png, per-layer PNGs
                              wardrobe_manifest.json (updated)
```

### Export
```
DOLL_CONFIG ──→ generateConfigJSString() ──→ doll_config.js (in ZIP)
DOLL_CONFIG ──→ JSON.stringify() ──→ project.json (in ZIP)
DOLL_CONFIG.layers ──→ fetch ──→ public/assets/* (in ZIP)
wardrobe_manifest.json ──→ iterate ──→ public/assets/compiled/.../{metadata,preview,layers,...}
```

## Project Structure

```
├── compiler/                    # Python compiler pipeline
│   ├── category_registry.py     # Shared category definitions
│   ├── canonical_schema.py      # Rig contract (anchors, layers, z-order)
│   ├── compiler.py              # AssetCompiler orchestrator
│   ├── normalize_canvas.py      # Canvas size normalization
│   ├── validate_asset.py        # Non-destructive validation
│   ├── split_slots.py           # Z-order layer splitting
│   ├── align_asset.py           # Bounding-box alignment for non-fitted categories
│   └── build_base_rig.py        # Standalone base rig builder
├── importers/                   # PSD import adapters
│   ├── flat_psd_importer.py     # v0.1 flat PSD importer
│   ├── flat_layer_map.json      # Layer name mapping + aliases
│   └── layer_mapper.py          # Adapter base class + canonical writers
├── js/                          # Frontend
│   ├── utils.js                 # Bake helpers + chroma key + name cleaning
│   ├── state.js                 # DOLL_CONFIG runtime state
│   ├── render.js                # Canvas rendering + pending overlay
│   ├── import.js                # PSD + garment ingestion + alignment UI
│   ├── wardrobe.js              # Wardrobe panel
│   ├── calibration.js           # Per-layer color/offset adjustments
│   └── export.js                # ZIP export
├── server.py                    # FastAPI backend (POST /api/compile-asset)
├── base_rig/                    # Generated base rig
│   ├── rig.json                 # Anchors, canvas, garment regions
│   └── masks/                   # Body silhouette + per-category allowed regions
├── public/assets/               # Layer PNGs + compiled assets
├── python/tests/                # Python test suite
├── tests/                       # JS test suite
├── project.json                 # Static project config loaded at startup
├── doll_config.js               # Fallback config (window.DOLL_CONFIG)
└── index.html                   # App entry point
```

## Categories

10 canonical wardrobe slots with z-indices:

| Slot       | z    | Upper Body |
|------------|------|------------|
| dress      | 205  | yes        |
| topwear    | 210  | yes        |
| outerwear  | 215  | yes        |
| bottomwear | 220  | no         |
| skirt      | 225  | no         |
| pants      | 225  | no         |
| legwear    | 230  | no         |
| shoes      | 235  | no         |
| handwear   | 240  | no         |
| accessory  | 245  | no         |

Skin layers occupy z=170–199.

## Testing

```bash
# Python tests
venv/bin/python -m pytest

# JS tests
npx vitest run

# All
venv/bin/python -m pytest && npx vitest run
```

105 total tests (61 Python + 44 JS).

## Importing Garments

1. Open the app at `http://localhost:8000`.
2. Click **Open Importer / Anchor Editor**.
3. Select a **wardrobe slot** (dress, topwear, etc.).
4. Drop the garment PNG. It loads with auto-shrink — oversized sources fit within the canvas; smaller ones keep native pixel size.
5. Adjust over the body ghost: drag to position; mouse-wheel to scale uniformly; arrow keys to nudge (Shift for 10 px); Scale X / Scale Y sliders or the Width / Height pixel inputs for precise sizing; click **Auto-Align to Body Mask** to size and center against the body's bounding box.
6. (Optional) Toggle **Color Key Background Removal** or **Subtract Body Reference** for chroma-key or body-mask cleanup.
7. Click **Process & Add to Wardrobe**. The Python backend runs `normalize_canvas`, `validate_asset`, and `split_slots`, writes the compiled asset under `public/assets/compiled/<category>/<asset_id>/`, updates `wardrobe_manifest.json`, and the new option appears in the wardrobe panel.

## Export

Click **Export Project (ZIP)** to download `paperdoll_project.zip` containing:
- `doll_config.js` — dynamic config with current state
- `project.json` — metadata with wardrobe entries
- `public/assets/*` — every base layer + every compiled asset folder referenced by the manifest
- `public/assets/wardrobe_manifest.json`
- `index.html`, `style.css`, `js/*.js` — full app

## Progress

- Flat PSD import pipeline complete (name normalization, aliases, composites, splits)
- All compiler modules share `category_registry.py` — no hardcoded lists
- v0.1 manual-placement flow with natural-dims-centered bake and pixel-honest inputs
- Live preview and bake share the same transform helper (`applyBakeTransform`) — preview and output cannot drift
- Canonical z-order applied at ingest
- Non-destructive validation by default
- Alpha-aware chroma key (auto-skip for transparent PNGs)
- Compiler output integrated with frontend rendering and ZIP export
- 105 passing tests
