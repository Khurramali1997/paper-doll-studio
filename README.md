# Paper Doll Studio

Local-first character customization pipeline. Import PSD character rigs, manually align wardrobe PNGs over the body ghost, bake to compiled assets, and export both finished projects and AI-ready conditioning packs (silhouette, depth, pose, edges) for downstream image-generation workflows.

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
                                                │
                                                └─→ AI conditioning pack
                                                    (silhouette + outline +
                                                     canny + depth + pose)
```

PSD ingestion path:
- **Flat PSD** (v0.1): `importers/flat_psd_importer.py` — reads flat (non-grouped) PSD layers, normalizes names via `flat_layer_map.json`, produces canonical composites and split (left/right arm) layers. The live UI uses an in-browser parser (`agPsd`); the Python importer covers batch/scripted builds.

Garment ingestion path (v0.1):
- **Manual placement** for every wardrobe slot — drop PNG → align visually (drag, wheel, scaleX/scaleY, pixel inputs, arrow-key nudge) → optional chroma key and body subtraction → bake natural-dims-centered into a compiled asset.

## Key Features

- **Unified category registry** — `compiler/category_registry.py` is the single source of truth for all 10 wardrobe slots (dress, topwear, outerwear, bottomwear, skirt, pants, legwear, shoes, handwear, accessory). All components import from here.
- **Natural-dims-centered bake** — `js/utils.js` exports `computeBakeGeometry` and `applyBakeTransform`; the bake and the live preview overlay both call the same helper so they cannot drift.
- **Pixel-honest alignment** — Width/Height number inputs read and write the rendered pixel size directly (a 50×50 accessory renders at 50×50 px; a 768×768 dress fills the canvas). Independent Scale X / Scale Y for non-uniform fit; uniform Scale slider plus mouse-wheel zoom for ratio-preserving changes; arrow keys nudge by 1 px (Shift = 10 px).
- **Auto-shrink on load** — sources larger than the canvas auto-fit on import so nothing overflows by default; small sources keep their native pixel size.
- **Canonical z-order** — new wardrobe layers receive their category's z value at ingest time (dress=205, topwear=210, outerwear=215, bottomwear=220, skirt/pants=225, legwear=230, shoes=235, handwear=240, accessory=245).
- **PSD-aware canvas sizing** — the doll container resizes to match each imported PSD's dimensions; layers are kept at their native PSD resolution.
- **Non-destructive validation** — `validate_asset` warns by default; `crop_to_allowed_region=True` is opt-in.
- **Alpha-aware chroma key** — automatically skipped for images that already have transparency.
- **Anchor-derived guide templates** — `compiler/guide_templates.py` renders per-garment authoring references (dress_bodycon, dress_flared, topwear, skirt, pants, legwear, handwear) as 768×768 PNGs in both human (labelled) and AI (label-free) variants. Polygons come from `rig.json` anchors so they always agree with the alignment lines.
- **Silhouette-based rig autodetect** — `compiler/rig_autodetect.py` derives a draft `rig.json` (17 anchors, full garment-anchor schema) from a body silhouette PNG. UI under "Generate Rig from Body Silhouette". Output is a starting point; artist reviews.
- **AI conditioning reference pack** — one-click ZIP of five channels per loaded rig:
  - `silhouette.png` — filter-safe binary mask
  - `outline.png` — 2 px contour stroke
  - `canny.png` — `cv2.Canny` edge map
  - `depth.png` — Depth Anything V2 ONNX monocular depth (real, not a proxy)
  - `pose.png` — MediaPipe-detected 18-keypoint OpenPose stick figure
- **Export ZIP** — bundles dynamic `project.json`, `doll_config.js`, every wardrobe layer PNG, every compiled asset folder referenced by `wardrobe_manifest.json`, and the core app files.

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

### AI Conditioning Reference Pack
```
Frontend composites:                    Backend (POST /api/reference-pack):
  silhouette  (alpha union, gray fill)    ┌─ silhouette.png  (pass-through)
  body        (RGB layers in z-order)     ├─ outline.png    (cv2.findContours)
        │                                 ├─ canny.png      (cv2.Canny)
        │                                 ├─ depth.png      (Depth Anything V2 ONNX)
        └─→ POST both ────────────────────└─ pose.png       (MediaPipe BlazePose → OpenPose)
                                               │
                                          reference_pack.zip
```

First call downloads the ~10 MB MediaPipe task file and ~50 MB Depth Anything ONNX model to `models/` (gitignored). Subsequent calls reuse the cached files. If either model fails to load, the corresponding channel falls back to a silhouette-only approximation.

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
│   ├── build_base_rig.py        # Standalone base rig builder
│   ├── guide_templates.py       # Authoring guide PNG renderer (human + AI)
│   ├── rig_autodetect.py        # Silhouette → draft rig.json
│   ├── reference_pack.py        # Silhouette + outline + canny + depth + pose ZIP
│   ├── pose_estimator.py        # MediaPipe BlazePose → OpenPose mapper
│   ├── depth_estimator.py       # Depth Anything V2 ONNX wrapper
│   ├── pattern_constructor.py   # Digital Tailor — body-slice garment constructor (8 recipes)
│   ├── garment_schema.py        # Garment landmark extraction
│   ├── danbooru_mapper.py       # Danbooru tag → neckline/sleeve/silhouette hints
│   ├── anime_segmenter.py       # ISNet-anime foreground segmentation wrapper
│   ├── anime_detector.py        # Anime face/hand detection for forbidden regions
│   ├── semantic_layer.py        # Semantic hint aggregator
│   └── stencil_pipeline.py      # Stencil geometry channel pipeline
├── importers/                   # PSD import adapters
│   ├── flat_psd_importer.py     # v0.1 flat PSD importer
│   ├── flat_layer_map.json      # Layer name mapping + aliases
│   └── layer_mapper.py          # Adapter base class + canonical writers
├── js/                          # Frontend
│   ├── utils.js                 # Bake helpers + chroma key + name cleaning
│   ├── state.js                 # DOLL_CONFIG runtime state
│   ├── render.js                # Canvas rendering + pending overlay
│   ├── import.js                # PSD + garment ingestion + alignment UI + rig autodetect
│   ├── wardrobe.js              # Wardrobe panel
│   ├── calibration.js           # Per-layer color/offset adjustments
│   ├── export.js                # ZIP export + silhouette + reference pack
│   └── stencils.js              # Stencil editor + Fabric Asset Generator + Digital Tailor UI
├── server.py                    # FastAPI backend
│                                #   POST /api/compile-asset
│                                #   POST /api/reference-pack
│                                #   POST /api/reference-channels
│                                #   POST /api/rig-autodetect
│                                #   GET  /api/guide-templates.zip
│                                #   POST /api/construct-pattern
├── base_rig/                    # Generated base rig
│   ├── rig.json                 # Anchors, canvas, garment regions
│   └── masks/                   # Body silhouette + per-category allowed regions
├── models/                      # Downloaded ML models (gitignored)
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

156 total tests (105 Python + 51 JS). The estimator unit tests mock model inference; no model downloads occur during `pytest`.

## Importing Garments

1. Open the app at `http://localhost:8000`.
2. Click **Open Importer / Anchor Editor**.
3. Select a **wardrobe slot** (dress, topwear, etc.).
4. Drop the garment PNG. It loads with auto-shrink — oversized sources fit within the canvas; smaller ones keep native pixel size.
5. Adjust over the body ghost: drag to position; mouse-wheel to scale uniformly; arrow keys to nudge (Shift for 10 px); Scale X / Scale Y sliders or the Width / Height pixel inputs for precise sizing; click **Auto-Align to Body Mask** to size and center against the body's bounding box.
6. (Optional) Toggle **Color Key Background Removal** or **Subtract Body Reference** for chroma-key or body-mask cleanup.
7. Click **Process & Add to Wardrobe**. The Python backend runs `normalize_canvas`, `validate_asset`, and `split_slots`, writes the compiled asset under `public/assets/compiled/<category>/<asset_id>/`, updates `wardrobe_manifest.json`, and the new option appears in the wardrobe panel.

## Authoring Tools

### Generate Rig from Body Silhouette

Drop a body silhouette PNG into the "🦴 Generate Rig from Body Silhouette" section of the Importer tab. The backend derives 17 anchors (neck, shoulders, strap, bust, waist, hips, knees, ankles, hem) from the silhouette's width profile + anatomical Y proportions and returns a draft `rig.json`. The output is a starting point — review and hand-adjust before replacing `base_rig/rig.json`.

### Download Guide Templates

The Export Project Package section's "📐 Download Guide Templates (ZIP)" button produces seven per-garment PNGs in two variants:

- `human/<id>.png` — title, alignment lines (waist/hips merged when within 25 px), red anchor dots, color-coded limb segments, 2 px canvas border. For human artists.
- `ai/<id>.png` — silhouette + region tint only. No text, dots, or border. For upstream image-generation models.

Guides cover `dress_bodycon`, `dress_flared`, `topwear`, `skirt`, `pants`, `legwear`, `handwear`. Each region is a polygon defined from `rig.json` anchors, so regions and alignment lines cannot disagree.

### Download Body Silhouette

The "🧍 Download Body Silhouette PNG" button composes the alpha union of every non-hair layer in the loaded rig, strips RGB, and fills with neutral gray. The output is a filter-safe binary mask — no anatomical pixels exist in the file. Useful as a tracing layer in any image editor or as a ControlNet "scribble" / "mask" input.

### Download AI Reference Pack

The "🤖 Download AI Reference Pack (ZIP)" button produces five conditioning channels ready for ControlNet workflows:

| Channel        | Backend                                | ControlNet target          |
|----------------|----------------------------------------|----------------------------|
| `silhouette.png` | Frontend alpha union, gray fill       | Scribble / mask / inpaint  |
| `outline.png`    | `cv2.findContours` 2 px stroke         | Lineart / scribble         |
| `canny.png`      | `cv2.Canny` edge map                   | Canny edge model           |
| `depth.png`      | Depth Anything V2 ONNX (518×518 → uint8) | Depth model              |
| `pose.png`       | MediaPipe BlazePose → 18-keypoint OpenPose stick figure | OpenPose model |

First call downloads the ~10 MB MediaPipe model and ~50 MB Depth Anything ONNX model to `models/` (one-time, cached). Filter safety: silhouette/outline/canny/depth all read from the binary mask only; pose is a colored stick figure with no body content; the body composite used as ML input never leaves localhost.

## Export

Click **Export Project (ZIP)** to download `paperdoll_project.zip` containing:
- `doll_config.js` — dynamic config with current state
- `project.json` — metadata with wardrobe entries
- `public/assets/*` — every base layer + every compiled asset folder referenced by the manifest
- `public/assets/wardrobe_manifest.json`
- `index.html`, `style.css`, `js/*.js` — full app

## Progress

### ✅ Milestone 1 — Core Pipeline (complete)
- Flat PSD import pipeline (name normalization, aliases, composites, splits)
- All compiler modules share `category_registry.py` — no hardcoded lists
- v0.1 manual-placement flow with natural-dims-centered bake and pixel-honest inputs
- Live preview and bake share `applyBakeTransform` — preview and output cannot drift
- Canonical z-order at ingest; `shoes` / `skirt` / `pants` as first-class wardrobe slots
- PSD-aware canvas resize; non-destructive validation; alpha-aware chroma key

### ✅ Milestone 2 — Authoring Tools (complete)
- Anchor-derived guide template polygons in human + AI variants
- Silhouette-based rig autodetect — 17 anchors from a body silhouette PNG
- AI conditioning reference pack: MediaPipe pose + Depth Anything V2 depth + Canny + outline + silhouette

### ✅ Milestone 3 — Digital Tailor V1 (complete)
Deterministic mask-to-garment constructor. No diffusion. Geometry is the source of truth.

**Architecture (geometry-first):**
- `body_silhouette` is the authoritative character contour — not abstract coordinate polygons
- Each garment zone is a vertical slice of the body silhouette bounded by `rig.json` anchor Y positions (e.g. bodice = rows neck_y → waist_y). This gives pixel-accurate body curves, correct arm-hole shapes, and real proportions instead of trapezoid approximations.
- Semantic hints (Danbooru neckline tag → `v_neck` / `round_neck` / `off_shoulder`) tell the system *what* to carve. The neck anchor tells it *where*. The body contour provides the actual pixel boundary.
- `hair_forbidden_region` removed from all recipes — garments render under the hair layer in the z-stack, so subtracting those pixels was wrong (was removing 44 % of the bodice).

**8 recipes across 5 categories:**

| Recipe | Category | Key modifier |
|---|---|---|
| `bodice` | topwear | round-neck cutout |
| `tight_top` | topwear | round-neck + erode 2 px |
| `bodycon_dress` | dress | round-neck + erode 6 px (pencil silhouette) |
| `tight_dress` | dress | round-neck + erode 4 px |
| `simple_flared_dress` | dress | round-neck + flare 60 px (a-line silhouette) |
| `leggings` | legwear | waist-to-ankle body slice |
| `stockings` | legwear | waist-to-ankle + erode 3 px |
| `gloves` | handwear | body − torso − leg − face |

**7 user-controllable transforms:** expand-x, expand-y, dilate, erode, smooth, flare (row-by-row hem widening), taper (waist pinch).

**Material + effects:** solid color, texture tile, edge stroke, inner shadow, highlight gradient.

**UI (Stencils tab → Digital Tailor panel):**
- Recipe selector, color picker, texture upload
- Live slider grid with value readouts
- Effect toggles (edge stroke on / inner shadow on / highlight off by default)
- Generate → thumbnail preview + area readout
- "Send to Cleanup Workbench" / "Send to Align/Bake" — both land correctly with button enabled, name pre-filled, alignment reset to 1:1, and live overlay firing immediately

**State hygiene fixes shipped alongside:**
- PSD swap now resets the entire import/ingest panel (pending asset, alignment, cleanup canvases, button, name field) so a new character never inherits a previous session's fit
- `character_composite` stencil source auto-refreshes after PSD load via `paperdoll:psd-loaded` custom event
- `buildGeometryVariants` always fetches a fresh composite before building geometry channels

**Tests:** 16 pytest (pattern constructor) + 7 Vitest (data contract) — 156 total passing
