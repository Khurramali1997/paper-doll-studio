# Paper Doll Studio — Product Plan

## 1. Product Thesis

Paper Doll Studio is a **Guide Pack + Asset Compiler** for fixed-rig paper-doll characters.

It helps indie visual novel, RPG, and narrative-game creators turn a single layered character source into a reusable asset-production system.

The product does **not** primarily generate art. Instead, it:

1. extracts structure from a layered character or base rig,
2. generates guide packs for compatible asset creation,
3. imports compatible or guide-compatible assets,
4. cleans and validates those assets,
5. aligns and bakes them into full-canvas layers,
6. exports a game-ready wardrobe / character package.

The core promise is:

> Paper Doll Studio turns guide-compatible assets into reusable paper-doll layers.

---

## 2. Target User

Paper Doll Studio is for:

- solo indie developers
- Ren'Py visual novel creators
- RPG Maker / Godot hobbyists
- writers who can build games but cannot draw every outfit
- programmers who have one base character PSD but need many asset variants
- small teams without a dedicated character artist
- creators who cannot afford Photoshop or repeated commissions

The user may have:

- one layered PSD
- one base sprite
- one commissioned character
- one generated base body
- some external image-generation access
- no high-end GPU
- limited art skill

The user usually lacks:

- Photoshop expertise
- a full-time artist
- ComfyUI / Stable Diffusion expertise
- time to manually make 50 wardrobe layers
- budget to commission every variant

---

## 3. Core Product Identity

Paper Doll Studio is:

- a rig extractor
- a guide-pack generator
- a compatible asset importer
- a cleanup and extraction workbench
- a deterministic layer compiler
- a wardrobe/export manager

Paper Doll Studio is **not**:

- a general AI image generator
- a Photoshop replacement
- a universal fashion-photo extractor
- a universal auto-fit system
- a pose retargeting system
- a ComfyUI wrapper
- a local Stable Diffusion product
- a tool for arbitrary wild internet images

Generative AI may be used as an optional external asset source, but it is not the identity of the product.

---

## 4. Core Concept: Guide-Compatible Assets

Paper Doll Studio does not promise to handle wild assets.

It supports:

- compatible assets
- guide-compatible assets
- convertible assets created for the current rig

A guide-compatible asset is an image created with knowledge of:

- the fixed canvas
- the fixed body pose
- the allowed region
- the forbidden region
- the category
- the z-order slot
- the expected final layer structure

Examples of supported inputs:

- clothing drawn over a Paper Doll guide
- AI-generated clothing using a Paper Doll AI guide
- white-background garment made for the character pose
- transparent PNG aligned to the character
- clothed guide output that can be extracted
- PSD layer asset from an artist

Examples of unsupported inputs:

- random fashion photos
- side-view clothing
- random anime screenshots
- occluded people wearing clothes
- product photos with perspective distortion
- arbitrary internet images

---

## 5. Main Systems

Paper Doll Studio has five major systems.

### 5.1 Rig Extraction

Input:

- layered PSD
- see-through-derived layers
- manually provided base rig

Output:

- canonical canvas
- base body layer
- body silhouette
- body outline
- layer registry
- z-order
- slot definitions
- alpha masks
- anchors
- guide-pack source data

The layered PSD is treated as a source of structural information, not merely as an image.

Important extracted information:

- layer names
- layer order
- visibility
- opacity
- bounding boxes
- alpha masks
- body silhouette
- hair front/back regions
- face regions
- clothing regions
- accessory regions
- possible anchors

---

### 5.2 Guide Pack Generator

The guide pack is the central product primitive.

A guide pack is a visual API for asset creation.

Each guide pack tells a human, model, or external tool:

- where the body is
- where the new asset may exist
- what region must not be covered
- what canvas size to preserve
- what category is being created
- what layer slot the result belongs to
- how the compiled asset will be validated

Each guide pack should include:

```text
guide_pack/<category>/
  human_guide.png
  ai_guide.png
  allowed_mask.png
  forbidden_mask.png
  occlusion_mask.png
  silhouette.png
  outline.png
  anchor_overlay.png
  slot.json
  prompt_template.txt
  example_asset.png
```