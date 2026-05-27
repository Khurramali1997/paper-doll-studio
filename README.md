# Paper Doll Studio

Local-first character customization pipeline for visual novel and indie game devs. Drop a layered PSD **or** a single character PNG, get a paper doll with a wardrobe slot system, AI-generate new garments via SD 1.5 inpainting, and export game-ready wardrobe assets. Everything runs on your machine — no cloud, no signup. Built and tested on a 16 GB M4 Mac; the entire stack is tuned for memory-constrained Apple Silicon.

## Quick start

```bash
# 1. Python deps (Python 3.11+)
python3 -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install -e ".[inpaint,sam,tagger,upscale]"

# 2. Optional: pre-warm the heavy model downloads so the first inpaint
#    isn't a silent 60-sec wait
huggingface-cli download Sanster/anything-4.0-inpainting
huggingface-cli download h94/IP-Adapter \
  models/ip-adapter_sd15.safetensors \
  --include "models/image_encoder/*"
huggingface-cli download 24yearsold/l2d_sam_iter2

# 3. JS dev tools (optional — only for tests)
npm install

# 4. Run
npm run dev                        # → http://localhost:8000
```

`npm run dev:reload` adds uvicorn `--reload` for live Python changes. Note that the inpaint worker is a long-lived subprocess — `pkill -f "scripts/inpaint/worker.py"` after editing `worker.py` so it picks up changes.

## Two ways to start a project

### 1. PSD import (artist workflow)
Drop a layered PSD into **Studio Tools → Import Master PSD**. Layers are extracted client-side via `ag-psd`, categorized by name heuristics into hair / face / eyes / wardrobe slots, and assembled into `DOLL_CONFIG.layers` with z-order, visibility toggles, and dye support. Best for production work where the artist controls layer separation.

### 2. Character PNG import (SAM auto-layer)
Drop a flat anime character PNG into **Studio Tools → Import Character PNG**. The 19-class anime SAM model (from the See-through project — see credits) decomposes the image into per-class RGBA layers (hair, face, eyes, topwear, bottomwear, etc.) and builds the same `DOLL_CONFIG` structure server-side. No PSD required.

- **Naked-character input** → complete doll, all body layers visible, wardrobe slots empty (ready for AI generation)
- **Dressed-character input** → wardrobe layers come out clean as ingestible assets, but the naked-body composite has holes where the wardrobe covered the body. Inpaint regeneration of those slots fills naturally because the new mask covers the same regions.

Both paths converge on the same `DOLL_CONFIG.layers + DOLL_CONFIG.wardrobe` shape, so every downstream tool (renderer, inpaint, cleanup workbench, export ZIP) works identically.

## The AI inpaint pipeline

Mask-conditioned inpainting via `Sanster/anything-4.0-inpainting` (SD 1.5 anime variant). Persistent FastAPI worker keeps the model warm across requests, SSE streaming for progress, cancellable mid-run.

### Architectural decisions worth knowing

These are the calls that ended up mattering for quality on 16 GB Apple Silicon:

**Diffusion is pinned to 512×512** regardless of canvas size. SD 1.5 was trained at 512; above 768 it starts duplicating limbs. Pinning to native res frees ~2-3 GB working memory (opens room for IP-Adapter), gives best quality per pass, and runs ~2× faster. After inference, the result is upscaled to canvas dim with **Lanczos** (default, zero-dep) or **RealESRGAN-anime** (optional `[upscale]` extra, ~17 MB, sharper cel-shaded lines).

**Per-garment generation, not whole-outfit.** A single inpaint pass with "blazer + skirt + boots" splits SD 1.5's fixed expressive capacity across all three garments. Per-garment passes give each region the full attention budget — the same math that makes ADetailer work for faces, applied to clothing. The per-garment refinement function uses the naked-body composite as base (never iterates on dressed pixels) and the SAM cutout for that slot as the mask, with slot-aware prompt scaffolds biasing generation toward the requested garment.

**IP-Adapter for cross-pass style cohesion.** Separately-generated garments don't naturally harmonize. IP-Adapter (`h94/IP-Adapter` basic + CLIP-ViT-H image encoder at fp16) lets you feed any style reference (character render, target outfit photo) and every pass anchors to it. ~1.3 GB add, fits the budget. **Mutually exclusive with ControlNet** in the UI — both loaded is ~8 GB and MPS fragmentation hits OOM.

**The naked-body invariant.** The base image for every inpaint pass is always the naked body composite — never the result of a previous inpaint. This means each generated garment is independently interpretable as "what would this garment look like on a fresh body," which is the right model for layered wardrobe assets. The composite is built live from current active-view body layers (matches what the user sees, respects toggles/offsets).

### Per-garment workflow

Inside the **Stencils** tab's Inpaint Garment Generator:

1. **Generate** — paint a brush mask or pick a SAM region from the dropdown, write a prompt, click Generate Garment. Result appears in the preview.
2. **Extract Garments (SAM)** — runs SAM on the result and decomposes into per-class RGBA cutouts. Each appears as a card in the Garment Extraction Workbench.
3. **Per-card actions**:
   - **Refine** — re-inpaint that one slot with a focused prompt against the naked body. Returns a cropped RGBA garment that alpha-composites into the preview without a SAM re-extract round-trip.
   - **To Cleanup** — send the cutout to the Cleanup Workbench for alpha cleanup and wardrobe ingest.
4. **Merge selected** — for one-piece garments (dresses, jumpsuits) that SAM splits across topwear + bottomwear, multi-select cards and merge into one unified cutout via union of alphas. Client-side, no extra SAM pass.

### What didn't work (and why it's not here)

- **LayerDiffusion transparency decoder** — would have created a second alpha-generation path that competes with SAM. The 19-class taxonomy is the spine; redundant consistency mechanisms reduce coherence rather than add it.
- **Whole-outfit-then-SAM-split** — initial workflow that got refactored into per-garment-from-the-start. Cleaner architecture, naturally produces ingestible wardrobe assets.
- **Frozen `body_ref` snapshot** — original design baked the naked-body reference at import time. Live editing in the UI did nothing. Now live-composites from current layer state via `generateBodyCompositeCanvas` (delegates to `generateDynamicBodyReferenceCanvas`).

## Hardware

| Requirement | Recommended |
|-------------|-------------|
| Python | ≥ 3.11 |
| Node.js | ≥ 18 (dev tools / tests only) |
| RAM | 16 GB unified memory (Apple Silicon) or 12 GB+ VRAM (CUDA) |
| GPU / accelerator | MPS (Apple Silicon), CUDA, or CPU — auto-detected |

This project is built and tested on **M4 / 16 GB unified memory / MPS in fp32** (diffusers on MPS doesn't have a working fp16 path for SD). SDXL and FLUX are out of reach locally on this hardware; the entire pipeline is deliberately SD 1.5-tier. CUDA users with more VRAM can swap in heavier base models via the `model_repo` field in the inpaint UI.

## Optional dependencies

| Extra | Installs | Powers |
|-------|----------|--------|
| `[inpaint]` | torch, diffusers | The SD 1.5 inpaint worker |
| `[sam]` | torch, accelerate, huggingface-hub | 19-class anime body segmentation, garment extraction, character PNG import |
| `[tagger]` | torch, timm, pandas | WD-tagger v3 garment slot classification |
| `[upscale]` | torch, realesrgan | RealESRGAN-anime sharp upscale |

Install combined: `pip install -e ".[inpaint,sam,tagger,upscale]"`.

Each extra is independent — missing deps degrade to graceful 503 errors at the API layer with a clear "extras not installed" message, not crashes.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/compile-asset` | Bake aligned garment PNG into a compiled asset |
| `POST` | `/api/reference-pack` | Generate five-channel AI conditioning ZIP |
| `POST` | `/api/reference-channels` | Individual conditioning channels |
| `POST` | `/api/rig-autodetect` | Silhouette → draft rig.json |
| `GET` | `/api/guide-templates.zip` | Per-garment authoring guide templates |
| `POST` | `/api/construct-pattern` | Digital Tailor garment generation |
| `POST` | `/api/stencil-pipeline` | Stencil geometry channel pipeline |
| `POST` | `/api/cleanup-assist/lane-c` | CV-assisted mask proposal for clothed guides |
| `POST` | `/api/ai-process` | Background removal (rembg) |
| `POST` | `/api/classify-garment` | Predict wardrobe slot for a garment image (WD tagger) |
| `POST` | `/api/setup/body-ref` | Upload a body reference PNG |
| `POST` | `/api/setup/parse-body-regions` | Run SAM on body_ref → 19 binary class masks |
| `POST` | `/api/extract-garments` | Run SAM on a clothed image → per-garment RGBA cutouts |
| `POST` | `/api/import-character-png` | PNG → 19-class decompose → full DOLL_CONFIG manifest |
| `GET` | `/api/inpaint/status` | Worker health and current model |
| `POST` | `/api/inpaint/generate` | Submit inpaint job (returns SSE job_id) |
| `GET` | `/api/inpaint/progress/{job_id}` | Server-sent events stream for a job |
| `POST` | `/api/inpaint/cancel/{job_id}` | Cancel a running job mid-flight |

## Project structure

```
├── compiler/                    # Python pipeline + bridges
│   ├── body_parser.py           # SAM-based 19-class body segmentation
│   ├── visual_classifier.py     # WD-tagger v3 wardrobe slot classifier
│   ├── inpaint_bridge.py        # Inpaint worker process management
│   ├── ai_segmenter.py          # rembg foreground / clothing isolation
│   ├── anime_segmenter.py       # ISNet-anime foreground segmentation
│   ├── pattern_constructor.py   # Digital Tailor (8 recipes, 7 transforms)
│   ├── reference_pack.py        # Five-channel AI conditioning ZIP
│   ├── pose_estimator.py        # MediaPipe BlazePose → OpenPose 18-keypoint
│   ├── depth_estimator.py       # Depth Anything V2 ONNX wrapper
│   ├── dwpose_estimator.py      # DWPose COCO-WholeBody (133 keypoints)
│   ├── stencil_pipeline.py      # Stencil geometry channel pipeline
│   ├── cleanup_assist.py        # Lane C CV mask proposal
│   ├── rig_autodetect.py        # Silhouette → draft rig.json (17 anchors)
│   ├── category_registry.py     # Canonical wardrobe slot taxonomy
│   ├── see_through/             # Vendored SemanticSam (from See-through paper)
│   └── ... (compiler.py, schemas, guide_templates, etc.)
├── scripts/inpaint/
│   ├── worker.py                # Persistent FastAPI inpaint worker (warm pipe, SSE)
│   └── run_inpaint.py           # One-shot fallback runner
├── js/                          # ES-module frontend
│   ├── state.js                 # DOLL_CONFIG + runtime state
│   ├── render.js                # Canvas rendering + naked-body composite
│   ├── import.js                # PSD + PNG import, garment ingestion, cleanup workbench
│   ├── wardrobe.js              # Wardrobe panel UI
│   ├── export.js                # ZIP export + reference pack triggers
│   ├── stencils.js              # Stencil editor, inpaint UI, Garment Extraction Workbench
│   ├── calibration.js           # Per-layer adjustments
│   ├── cleanup.js               # Background cleanup image processing
│   └── utils.js
├── base_rig/
│   ├── rig.json                 # Anchors (17), canvas dims, garment regions
│   └── masks/                   # Body silhouette + per-category allowed regions
├── models/                      # Auto-downloaded ML models (gitignored)
├── public/assets/               # Layer PNGs, generator outputs (some gitignored)
├── importers/                   # PSD ingestion utilities
├── python/tests/                # Python test suite
├── tests/                       # JS test suite (vitest)
├── server.py                    # FastAPI backend
├── index.html                   # App entry
└── pyproject.toml
```

## Testing

```bash
venv/bin/python -m pytest        # Python tests
npx vitest run                   # JS tests
```

Model inference is mocked in unit tests; no network calls during `pytest`.

## Other tools (not directly part of the AI inpaint loop)

**Digital Tailor** — deterministic mask-to-garment constructor, no diffusion. 8 recipes (bodice, tight_top, bodycon_dress, tight_dress, simple_flared_dress, leggings, stockings, gloves), 7 transforms (expand-x, expand-y, dilate, erode, smooth, flare, taper), solid/texture/edge/shadow material system. Body silhouette is the authoritative contour. Output routes to Cleanup Workbench.

**Cleanup Workbench** — non-destructive post-process for any incoming garment. Lanes (`transparent_png`, `white_background`, `clothed_guide`), toggles (background removal, color key, halo cleanup, island removal, body subtraction, stencil clipping), manual eraser/restore brush with undo, CV-assisted Lane C mask proposal. Final step before wardrobe ingest.

**AI reference pack** — Export → Download AI Reference Pack (ZIP) produces five ControlNet-ready channels: silhouette, outline, canny, depth (Depth Anything V2), pose (MediaPipe → OpenPose 18-keypoint). Useful for downstream tools that want conditioning images.

**Guide templates** — Per-garment authoring PNGs (human + AI variants) with polygon regions derived from `rig.json` anchors. Useful for artists drafting custom garments.

**Rig autodetect** — Drop a body silhouette PNG → draft `rig.json` with 17 anchors derived from the silhouette's width profile. Manual review and adjustment before committing.

## Credits

This project would not exist without the work of others:

- **See-through project** (Lin, Li, Qin, Chan, Jin, Liu, Choy, Liu — Saint Francis University / U Penn / Spellbrush / Shitagaki Lab). "See-through: Single-image Layer Decomposition for Anime Characters," arXiv:2602.03749, Feb 2026. Paper doll Studio reuses their 19-class anime semantic taxonomy and the SAM checkpoint they trained (`24yearsold/l2d_sam_iter2`) as the foundation for all body parsing, garment extraction, and PNG import. Their paper does the architectural inverse of paperdoll (decompose dressed → per-part layers via SDXL) and showed me that user-driven attention is the right structural simplification on memory-constrained hardware.
- **h94** — IP-Adapter weights (`h94/IP-Adapter`).
- **xinntao** — RealESRGAN-anime upscaler.
- **SmilingWolf** — WD-tagger v3 anime classifier.
- **Sanster** — `anything-4.0-inpainting` (the SD 1.5 anime inpainting variant the worker uses).
- **lllyasviel** — ControlNet weights, scheduler / sampler work.
- **HuggingFace diffusers, transformers, accelerate** — the model serving stack.
- **MediaPipe** (Google) — pose and hand landmarkers.
- **Depth Anything V2**, **ISNet-anime**, **DWPose**, **rembg** — reference pack channels.
- **ag-psd** — client-side PSD parser.
