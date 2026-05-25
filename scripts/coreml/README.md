# Core ML backend notes

Paperdoll calls Core ML generation through `/api/coreml/generate`. The app does
not load Core ML models at FastAPI startup; it shells out to a configured local
runner so Apple Python, Swift, or converted custom runners can be swapped.

## Swift/CoreML sample runner

This is the preferred local path for this project.

Set:

```bash
export PAPERDOLL_COREML_BACKEND=swift
export PAPERDOLL_COREML_SWIFT_PACKAGE=/Volumes/Khurrum/hobby/paperdoll/vendor/ml-stable-diffusion
export PAPERDOLL_COREML_MODEL_DIR=/path/to/CoreML/Resources
```

Paperdoll will call:

```bash
swift run StableDiffusionSample ...
```

The Swift sample supports text-to-image, image-to-image, and ControlNet when
the matching controlled UNet/controlnet models exist in the Resources folder.
It does not implement mask inpainting.

## Default Apple Python pipeline

Set:

```bash
export PAPERDOLL_COREML_MODEL_DIR=/path/to/converted/CoreML/Resources
export PAPERDOLL_COREML_PYTHON=/path/to/coreml/venv/bin/python
```

The default command is:

```bash
python -m python_coreml_stable_diffusion.pipeline ...
```

This path supports txt2img with optional ControlNet inputs. Apple's public
Python sample does not expose inpaint image/mask arguments.

## Swift/CoreML inpaint runner

For inpaint, provide a command template:

```bash
export PAPERDOLL_COREML_COMMAND_TEMPLATE='swift run PaperdollInpaint --prompt {prompt} --negative {negative_prompt} --init {init_image} --mask {mask_image} --out {output_dir} --seed {seed} --steps {steps} --cfg {guidance_scale} --compute {compute_unit} --controls {controlnet_inputs}'
```

Available fields:

- `{prompt}`
- `{negative_prompt}`
- `{seed}`
- `{steps}`
- `{guidance_scale}`
- `{compute_unit}`
- `{model_version}`
- `{mode}`
- `{model_dir}`
- `{output_dir}`
- `{init_image}`
- `{mask_image}`
- `{controlnet_models}`
- `{controlnet_inputs}`

The command must write at least one PNG under `{output_dir}`. Paperdoll returns
the newest PNG and also copies it to `public/assets/coreml_generated/`.
