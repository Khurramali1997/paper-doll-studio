# Paper Doll Studio

Local-first character customization pipeline for indie visual novel, RPG, and narrative game creators. Import a layered PSD character rig, build a wardrobe of fitted garments, clean and validate each asset with an assisted workbench, generate AI-conditioned guide packs, and export game-ready wardrobe ZIPs — all running on your machine, no cloud required.

## Quick Start

```bash
# 1. Install Python dependencies (Python 3.11+)
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Install JS dev tools (optional — only needed for tests/lint)
npm install

# 3. Start the server
npm run dev
# → http://localhost:8000
```

`npm run dev:reload` adds uvicorn `--reload` for live Python changes.

## What It Does

```
PSD ──→ Base Rig ──→ Frontend ──→ Compiler ──→ Export ZIP
           │              │            │
       rig.json      DOLL_CONFIG   compiled/       ┌─ AI Reference Pack
       masks/        wardrobe      metadata.json   │  (silhouette + depth +
       base_rig/     state.json    manifest.json   │   pose + canny + outline)
                                                   └─ Garment Generators
                                                      (LayerDiffuse · Inpaint · CoreML)
```

**Core pipeline** — Import a PSD → auto-detect body anchors → manually place and align garment PNGs over the body ghost → clean alpha edges in the Cleanup Workbench → bake to compiled assets → export as a self-contained ZIP.

**Authoring tools** — Download guide templates (seven garment silhouette PNGs in human + AI variants), body silhouette, and a five-channel AI conditioning reference pack.

**Garment generators (optional)** — Three local generators produce RGBA garment PNGs and route them straight into the Cleanup Workbench:
- **Digital Tailor** — deterministic mask-to-garment constructor (8 recipes, no diffusion)
- **LayerDiffuse** — Stable Diffusion with a transparent VAE decoder; best for tattoos and overlays
- **Inpaint** — `Sanster/anything-4.0-inpainting` with a brush-painted mask; best for fitted garments

## Requirements

| Requirement | Version |
|-------------|---------|
| Python | ≥ 3.11 |
| Node.js | ≥ 18 (dev tools only) |
| RAM | 8 GB minimum; 16 GB recommended for diffusion generators |
| GPU / NPU | Optional — MPS (Apple Silicon) or CUDA auto-detected by generators |

## Optional: Diffusion Generators

The inpaint and LayerDiffuse generators run in isolated venvs to avoid dependency conflicts with the main server.

### Inpaint (`Sanster/anything-4.0-inpainting`)

```bash
python -m venv venv                         # reuse main venv — no extra install needed
pip install torch diffusers transformers accelerate peft
# Model downloads automatically from HuggingFace on first generate (~2 GB)
```

Environment overrides (all optional):

| Variable | Default | Purpose |
|----------|---------|---------|
| `PAPERDOLL_INPAINT_PYTHON` | `sys.executable` | Python used to run the inpaint script |
| `PAPERDOLL_INPAINT_RUNNER` | `scripts/inpaint/run_inpaint.py` | Script path |
| `PAPERDOLL_INPAINT_MODEL_REPO` | `Sanster/anything-4.0-inpainting` | HuggingFace model repo |
| `PAPERDOLL_INPAINT_TIMEOUT_SEC` | `1200` | Per-generation timeout |

### LayerDiffuse (`digiplay/Juggernaut_final` + transparent VAE)

```bash
python3.11 -m venv .venv-layerdiffuse
source .venv-layerdiffuse/bin/activate
pip install torch diffusers transformers accelerate peft
# Clone the layerdiffuse vendor library into vendor/diffuser_layerdiffuse/
```

Environment overrides:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PAPERDOLL_LAYERDIFFUSE_PYTHON` | `.venv-layerdiffuse/bin/python` | Python for LayerDiffuse |
| `PAPERDOLL_LAYERDIFFUSE_RUNNER` | `scripts/layerdiffuse/run_layerdiffuse.py` | Script path |
| `PAPERDOLL_LAYERDIFFUSE_VENDOR` | `vendor/diffuser_layerdiffuse` | LayerDiffuse library path |
| `PAPERDOLL_LAYERDIFFUSE_MODEL` | `digiplay/Juggernaut_final` | Base SD model |

### CoreML (Apple Silicon only)

```bash
python3.11 -m venv .venv-coreml
source .venv-coreml/bin/activate
pip install torch coremltools ...
# Place CoreML model packages in models/coreml/
```

## ML Models

All models auto-download to `models/` on first API call. No manual steps.

| Model | Size | Used by | Download |
|-------|------|---------|----------|
| `depth_anything_v2_vits.onnx` | ~50 MB | Reference Pack — depth channel | HuggingFace `onnx-community/depth-anything-v2-small` |
| `pose_landmarker_full.task` | ~10 MB | Reference Pack — pose channel | Google MediaPipe CDN |
| `dw-ll_ucoco_384.onnx` | ~134 MB | Digital Tailor — whole-body pose | HuggingFace `NirZabari/DWPose` |
| `isnet-anime_1024.onnx` | ~170 MB | Stencil Pipeline — foreground seg | HuggingFace `skytnt/anime-seg` |
| `lbpcascade_animeface.xml` | ~2.6 MB | Stencil Pipeline — face detection | GitHub `nagadomi/lbpcascade_animeface` |
| `hand_landmarker.task` | ~8 MB | Stencil Pipeline — hand detection | Google MediaPipe CDN |

Diffusion models (`anything-4.0-inpainting`, `Juggernaut_final`) download via HuggingFace Hub the first time a generator runs and are cached in `~/.cache/huggingface/`.

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

**PSD ingestion** — `importers/flat_psd_importer.py` reads flat (non-grouped) PSDs, normalizes layer names via `flat_layer_map.json`, and produces canonical composites and split (left/right arm) layers. The live UI uses an in-browser parser (`ag-psd`); the Python importer covers batch/scripted builds.

**Garment ingestion** — Drop PNG → align visually (drag, wheel, scale X/Y, pixel inputs, arrow-key nudge) → optional chroma key and body subtraction → Cleanup Workbench → bake natural-dims-centered to a compiled asset.

## Key Features

- **Unified category registry** — `compiler/category_registry.py` is the single source of truth for all 10 wardrobe slots. All components import from here; no hardcoded lists anywhere.
- **Natural-dims-centered bake** — `applyBakeTransform` is shared by the live preview overlay and the compile step; they cannot drift.
- **Pixel-honest alignment** — Width/Height inputs read and write the rendered pixel size directly. Independent Scale X / Scale Y for non-uniform fit; uniform Scale slider plus mouse-wheel for ratio-preserving changes; arrow keys nudge 1 px (Shift = 10 px).
- **Auto-shrink on load** — sources larger than the canvas auto-fit; small sources keep native pixel size.
- **Canonical z-order** — new layers receive their category's z value at ingest time.
- **Cleanup Workbench** — canvas-based eraser/restore brush, undo stack, white-background removal, halo cleanup, island removal, body stencil clipping (soft/strict/preview-only), and a CV-assisted Lane C proposal for clothed-guide outputs. Custom stencils from the Stencil Editor populate the workbench mask dropdown automatically.
- **Inpaint brush mask** — paint the inpaint region directly on the character viewport with a brush/erase/clear tool; exports as a white-on-black mask into the inpaint API.
- **AI conditioning reference pack** — one-click ZIP of five ControlNet-ready channels: silhouette, outline, canny, depth (Depth Anything V2), pose (MediaPipe → 18-keypoint OpenPose).
- **Digital Tailor** — deterministic mask-to-garment constructor. Body silhouette is the authoritative contour. 8 recipes (bodice, tight_top, bodycon_dress, tight_dress, simple_flared_dress, leggings, stockings, gloves), 7 user-controllable transforms, solid/texture/edge/shadow material system.
- **Export ZIP** — bundles `project.json`, `doll_config.js`, every layer PNG, every compiled asset folder, and the full app.

## Project Structure

```
├── compiler/                    # Python compiler pipeline (35+ modules)
│   ├── category_registry.py     # Canonical 10-slot wardrobe registry
│   ├── canonical_schema.py      # Rig contract (anchors, layers, z-order)
│   ├── compiler.py              # AssetCompiler orchestrator
│   ├── reference_pack.py        # Five-channel conditioning ZIP
│   ├── pose_estimator.py        # MediaPipe BlazePose → OpenPose (18 joints)
│   ├── depth_estimator.py       # Depth Anything V2 ONNX wrapper
│   ├── dwpose_estimator.py      # DWPose COCO-WholeBody (133 keypoints)
│   ├── anime_segmenter.py       # ISNet-anime foreground segmentation
│   ├── anime_detector.py        # Anime face + hand detection
│   ├── pattern_constructor.py   # Digital Tailor (8 recipes, 7 transforms)
│   ├── cleanup_assist.py        # Lane C CV mask proposal
│   ├── stencil_pipeline.py      # Stencil geometry channel pipeline
│   ├── layerdiffuse_bridge.py   # LayerDiffuse subprocess bridge
│   ├── inpaint_bridge.py        # Inpainting subprocess bridge
│   ├── coreml_bridge.py         # CoreML generation bridge
│   ├── rig_autodetect.py        # Silhouette → draft rig.json (17 anchors)
│   ├── guide_templates.py       # Per-garment authoring PNGs (human + AI)
│   └── [20+ more modules]
├── importers/                   # PSD ingestion
│   ├── flat_psd_importer.py
│   ├── flat_layer_map.json
│   └── layer_mapper.py
├── js/                          # Frontend (ES modules)
│   ├── state.js                 # DOLL_CONFIG runtime state
│   ├── render.js                # Canvas rendering
│   ├── import.js                # PSD + garment ingestion, alignment UI, cleanup workbench
│   ├── wardrobe.js              # Wardrobe panel
│   ├── export.js                # ZIP export + reference pack
│   ├── stencils.js              # Stencil editor, Digital Tailor, generator UIs
│   ├── calibration.js           # Per-layer color/offset adjustments
│   ├── cleanup.js               # Background cleanup image processing
│   └── utils.js                 # Bake helpers, chroma key, name cleaning
├── scripts/
│   ├── inpaint/                 # Inpainting subprocess runner
│   └── layerdiffuse/            # LayerDiffuse subprocess runner
├── base_rig/
│   ├── rig.json                 # Anchors (17), canvas dimensions, garment regions
│   └── masks/                   # Body silhouette + per-category allowed regions
├── models/                      # Auto-downloaded ML models (gitignored)
├── public/assets/               # Layer PNGs (checked in); compiled/ gitignored
├── python/tests/                # Python test suite (14 files, 105 tests)
├── tests/                       # JS test suite (4 files, 51 tests)
├── server.py                    # FastAPI backend
├── index.html                   # App entry point
├── style.css
├── requirements.txt
└── pyproject.toml
```

## Categories

| Slot | z-index | Upper body |
|------|---------|------------|
| dress | 205 | yes |
| topwear | 210 | yes |
| outerwear | 215 | yes |
| bottomwear | 220 | no |
| skirt | 225 | no |
| pants | 225 | no |
| legwear | 230 | no |
| shoes | 235 | no |
| handwear | 240 | no |
| accessory | 245 | no |

Skin layers occupy z = 170–199.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/compile-asset` | Bake aligned garment PNG into a compiled asset |
| `POST` | `/api/reference-pack` | Generate five-channel AI conditioning ZIP |
| `POST` | `/api/reference-channels` | Individual conditioning channels |
| `POST` | `/api/rig-autodetect` | Silhouette → draft rig.json |
| `GET` | `/api/guide-templates.zip` | Download per-garment authoring guides |
| `POST` | `/api/construct-pattern` | Digital Tailor garment generation |
| `POST` | `/api/stencil-pipeline` | Stencil geometry channel pipeline |
| `POST` | `/api/cleanup-assist/lane-c` | CV-assisted mask proposal for clothed guides |
| `POST` | `/api/ai-process` | Background removal (rembg) |
| `GET` | `/api/inpaint/status` | Check inpaint runner availability |
| `POST` | `/api/inpaint/generate` | Generate garment via inpainting |
| `GET` | `/api/layerdiffuse/status` | Check LayerDiffuse availability |
| `POST` | `/api/layerdiffuse/generate` | Generate transparent-layer RGBA via LayerDiffuse |
| `GET` | `/api/coreml/status` | Check CoreML availability |
| `POST` | `/api/coreml/generate` | Generate via CoreML (Apple Silicon) |

## Testing

```bash
# Python
venv/bin/python -m pytest

# JavaScript
npx vitest run

# Both
venv/bin/python -m pytest && npx vitest run
```

156 total tests (105 Python + 51 JS). Model inference is mocked in unit tests; no network calls during `pytest`.

## Importing Garments

1. Open `http://localhost:8000` → **Stencils** tab or **Importer**.
2. Select a **wardrobe slot** (dress, topwear, etc.).
3. Drop a garment PNG. Auto-shrink fits oversized sources within the canvas.
4. Align over the body ghost: drag to position, scroll to scale uniformly, arrow keys to nudge (Shift = 10 px), Scale X / Scale Y for non-uniform fit, Width / Height pixel inputs for exact sizing, or **Auto-Align to Body Mask**.
5. (Optional) Enable **Color Key Background Removal** or **Subtract Body Reference**.
6. Click **Process & Add to Wardrobe**. The compiler normalizes, validates, and splits the asset; the new option appears in the wardrobe panel.

## Cleanup Workbench

Every garment that enters the workbench (via importer or any generator) goes through a non-destructive cleanup pipeline:

- **Lanes** — `transparent_png` (generator outputs), `white_background`, `clothed_guide` (Lane C with CV-assisted mask proposal)
- **Toggles** — white background removal, color key, halo cleanup, island removal, body subtraction, body stencil clipping
- **Manual brush** — canvas eraser / restore tool with undo stack
- **Lane C assist** — generates a CV proposal mask; apply via union, intersect, or replace
- **Body stencil** — soft blend, strict clip, or preview-only; sources: body silhouette, visible body layers, PSD layer projection, or custom stencil from the Stencil Editor

## Authoring Tools

**Guide templates** — Export → *Download Guide Templates (ZIP)* produces seven per-garment PNGs in human-annotated and AI-clean variants. Polygon regions come from `rig.json` anchors.

**Body silhouette** — Export → *Download Body Silhouette PNG* composites all non-hair layers into a filter-safe binary mask.

**AI reference pack** — Export → *Download AI Reference Pack (ZIP)* produces the five ControlNet channels listed in the Key Features section. First call downloads ~60 MB of models; subsequent calls reuse the cache.

**Rig autodetect** — Drop a body silhouette PNG in the Importer tab to generate a draft `rig.json` with 17 anchors from the silhouette's width profile. Output is a starting point; review before replacing `base_rig/rig.json`.

## Digital Tailor

Deterministic mask-to-garment constructor (no diffusion). Body silhouette is the authoritative contour — each garment zone is a vertical body slice bounded by `rig.json` anchor Y positions.

**8 recipes:**

| Recipe | Category | Key shape |
|--------|----------|-----------|
| `bodice` | topwear | round-neck cutout |
| `tight_top` | topwear | round-neck + erode 2 px |
| `bodycon_dress` | dress | round-neck + erode 6 px |
| `tight_dress` | dress | round-neck + erode 4 px |
| `simple_flared_dress` | dress | round-neck + flare 60 px |
| `leggings` | legwear | waist-to-ankle body slice |
| `stockings` | legwear | waist-to-ankle + erode 3 px |
| `gloves` | handwear | body − torso − leg − face |

**7 transforms:** expand-x, expand-y, dilate, erode, smooth, flare (a-line widening), taper (waist pinch).

Output routes to the Cleanup Workbench or directly to the alignment/bake flow.

## Garment Generators

### Inpaint Garment Generator

Mask-conditioned inpainting via `Sanster/anything-4.0-inpainting`. DPM++ 2M Karras scheduler (float32 on Apple Silicon MPS, float16 on CUDA).

**Mask sources (priority order):**
1. Brush mask painted on the main character viewport (Paint Mask tool)
2. Stencil selected from the Stencil Editor

White region = inpaint, black region = keep. Output routes to Cleanup Workbench.

### LayerDiffuse

Stable Diffusion with a transparent-layer VAE decoder. Produces RGBA PNGs with genuine alpha channels — no post-hoc background removal. Best for tattoos, overlays, and semi-transparent garments.

Optional **Clip alpha to mask** toggle constrains generated alpha to the body silhouette for cleaner edges. **Alpha threshold** (default 20) removes noise below the cutoff.

### CoreML (Apple Silicon)

Runs `ml-stable-diffusion` CoreML models natively on the ANE/GPU. Fastest on Apple Silicon for smaller garment assets.

## Progress

### ✅ Milestone 1 — Core Pipeline
Flat PSD import, compiler pipeline, manual-placement bake, canonical z-order, non-destructive validation, alpha-aware chroma key, PSD-aware canvas sizing.

### ✅ Milestone 2 — Authoring Tools
Anchor-derived guide templates, silhouette-based rig autodetect, AI conditioning reference pack (MediaPipe pose + Depth Anything V2 + Canny + outline + silhouette).

### ✅ Milestone 3 — Digital Tailor V1
Deterministic body-slice garment constructor. 8 recipes, 7 transforms, material system. Geometry-first: body silhouette is the authoritative contour.

### ✅ Milestone 4 — AI Generators + Cleanup Workbench
Lane C CV-assisted mask cleanup, custom stencil integration, body stencil clipping modes, generator pipelines (CoreML, LayerDiffuse, Inpaint), inpaint brush mask painter, cleanup workbench stencil dropdowns wired to the Stencil Editor.
