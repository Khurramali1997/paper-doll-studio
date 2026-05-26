#!/usr/bin/env python3
"""Paperdoll inpainting runner.

Downloads Anything-v4.5-inpainting on first run (cached by huggingface_hub).
Accepts a body composite image + garment slot mask and inpaints the masked
region with the prompted garment. Output is RGB PNG — transparency is handled
downstream by the cleanup workbench.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from diffusers import DPMSolverMultistepScheduler, StableDiffusionInpaintPipeline
from PIL import Image, ImageFilter


DEFAULT_MODEL_REPO = "Sanster/anything-4.0-inpainting"

DEFAULT_NEGATIVE = (
    "low quality, blurry, deformed, extra limbs, body paint, skin tight "
    "bodysuit, naked, watermark, text, logo, multiple people, bad anatomy, "
    "worst quality, normal quality"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE)
    parser.add_argument("--image", required=True, help="Body composite RGB PNG")
    parser.add_argument("--mask", required=True, help="Garment slot mask — white=inpaint, black=keep")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-repo", default=DEFAULT_MODEL_REPO)
    parser.add_argument("--fast", action="store_true", help="Use DPM++ 2M Karras scheduler for ~10 step inference")
    parser.add_argument("--seed", type=int, default=93)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance-scale", type=float, default=7.0)
    parser.add_argument("--strength", type=float, default=1.0,
                        help="How much to repaint the masked region (1.0 = fully repaint)")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--feather", type=int, default=8,
                        help="Gaussian blur radius applied to mask edges (0 = off)")
    parser.add_argument("--device", default="auto")
    return parser.parse_args()


def choose_device(name: str) -> str:
    if name != "auto":
        return name
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_pipeline(args, device: str) -> StableDiffusionInpaintPipeline:
    # MPS float16 produces NaN/black output — use float32 on Apple Silicon
    dtype = torch.float16 if device == "cuda" else torch.float32
    pipe = StableDiffusionInpaintPipeline.from_pretrained(
        args.model_repo,
        torch_dtype=dtype,
        safety_checker=None,
    )
    # DPM++ 2M Karras converges in 10-15 steps and works with inpainting UNets
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config,
        use_karras_sigmas=True,
    )
    pipe = pipe.to(device)
    if device == "mps":
        pipe.enable_attention_slicing()
    return pipe


def main():
    args = parse_args()
    device = choose_device(args.device)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    pipe = load_pipeline(args, device)

    size = (args.width, args.height)
    image = Image.open(args.image).convert("RGB").resize(size, Image.Resampling.LANCZOS)
    mask = Image.open(args.mask).convert("L").resize(size, Image.Resampling.LANCZOS)
    if args.feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=args.feather))

    steps = min(args.steps, 12) if args.fast else args.steps
    guidance = args.guidance_scale

    generator = torch.Generator(device="cpu").manual_seed(args.seed)
    result = pipe(
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
        image=image,
        mask_image=mask,
        width=args.width,
        height=args.height,
        num_inference_steps=steps,
        guidance_scale=guidance,
        generator=generator,
    ).images[0]

    result.save(output)
    print(output)


if __name__ == "__main__":
    main()
