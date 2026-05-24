# Draw Things Settings for Paperdoll Conditioning

Run this once you've dragged the four numbered PNGs into Draw Things. The
recipe below comes straight from the validated multi-ControlNet outfit-change
workflow — OpenPose anchors the joints, Depth softly suggests volume, the
inpaint mask scopes regeneration to the body while preserving the face.

## Model

- **Base**: any SD 1.5 *inpainting* checkpoint. Default: `Stable Diffusion v1.5 Inpainting`.
- **Why inpainting**: a regular SD 1.5 model will repaint the whole image. Inpainting respects the mask.

## Image inputs (drag-and-drop)

| Slot                    | File                                  |
|-------------------------|---------------------------------------|
| Image (init)            | `01_body_composite.png`              |
| Mask                    | `02_inpaint_mask.png`                |
| ControlNet 1 → OpenPose | `03_controlnet_openpose.png`         |
| ControlNet 2 → Depth    | `04_controlnet_depth.png`            |

The mask is already pre-built (body minus face). **Do not have Draw Things auto-detect a mask**; use the one provided.

## Sampling

| Parameter                | Value           | Why                                  |
|--------------------------|-----------------|--------------------------------------|
| Sampler                  | Euler a *or* DPM++ 2M Karras | Either works for inpaint     |
| Steps                    | 28–30           | Quality/speed sweet spot             |
| CFG / Guidance           | 7.0–7.5         | Standard SD 1.5                      |
| Width × Height           | match the input image (likely 768×768 or 1024×1024) |  |
| Strength / Denoising     | 0.95            | High — we want a real outfit change  |

## ControlNet weights

| ControlNet  | Weight  | Notes                                              |
|-------------|---------|----------------------------------------------------|
| OpenPose    | **1.0** | Full strength. This is the real anchor for the body. |
| Depth       | **0.35**| Deliberately low. Higher locks fabric to body volume ("bodypaint"). |

If Draw Things exposes "start step" / "end step" per ControlNet, leave both at default (apply throughout).

## Prompt template

**Positive:**
```
<your outfit description>, full body, simple plain background, photorealistic, detailed fabric, professional photo
```

**Negative:**
```
low quality, blurry, deformed, extra limbs, body paint, skin tight bodysuit, naked, watermark, text, logo, multiple people
```

Replace `<your outfit description>` with whatever you want to generate, e.g.:
- `red velvet evening gown`
- `black leather biker jacket and blue jeans`
- `fantasy plate armor with gold trim`
- `summer floral sundress, pastel colors`
- `cyberpunk streetwear, neon jacket`

## What "good" looks like

A successful run produces:
- The character's **face is preserved** (because the mask protected it).
- The **body is dressed** per the prompt.
- The **fabric drapes** past or away from the bare-body silhouette where physics would expect it (e.g., flared skirt extending below hips).
- No "bodypaint" effect (clothing vacuum-sealed onto skin).

## Failure modes (and quick tunings)

| Symptom                                | Tune                                         |
|----------------------------------------|----------------------------------------------|
| Fabric vacuum-sealed to body           | Drop Depth weight to 0.2 or disable Depth   |
| Face mangled / lost identity           | Mask is too aggressive — re-export after expanding the protect region (will need to edit the script) |
| Outline blurry, garment shapeless      | Add a third ControlNet: SoftEdge / HED at weight 0.4 (Draw Things has it) |
| Wrong limb positions / extra arms      | OpenPose weight too low — bump to 1.0 if you reduced it |
