# Paper Doll Studio Plan

## Product Thesis
Paper Doll Studio is a Guide Pack + Asset Compiler for fixed-rig paper-doll characters.

It creates guide packs from layered characters and compiles guide-compatible assets into reusable wardrobe, hair, accessory, and expression layers.

## Non-Goals
- Not a general AI image generator
- Not a Photoshop replacement
- Not a universal auto-fit/retargeting system
- Not for wild internet fashion photos
- Not dependent on local diffusion
- Not a ComfyUI wrapper

## Supported Inputs
- Layered PSD / base rig
- Guide-compatible PNGs
- White-background compatible assets
- Cloted guide outputs
- Arst-drawn template assets
- Genrated assets from external tools

## Core Systems
1. Rig extraction
2. Guide pack generation
3. Compatible asset import
4. Cleanup / extraction workbench
5. Deterministic align / bake / slot / export compiler

## Scope Boundary
Paper Doll supports compatible and convertible assets, not wild assets.

## V1 Goal
A non-artist indie dev can turn guide-compatible clothing assets into game-ready paper-doll wardrobe layers without Photoshop or a high-end GPU.