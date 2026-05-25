#!/usr/bin/env python3
"""Paperdoll LayerDiffuse runner.

Runs the rootonchair Diffusers port as a small command-line backend and emits
one transparent PNG. The wrapper keeps Paperdoll-specific concerns here:
Apple/MPS device selection, background-conditioned foreground generation, and
optional alpha clamping to a garment mask.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from diffusers import LCMScheduler, StableDiffusionPipeline
from huggingface_hub import hf_hub_download
from PIL import Image
from safetensors.torch import load_file


ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "diffuser_layerdiffuse"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from layer_diffuse.loaders import load_lora_to_unet  # noqa: E402
from layer_diffuse.models import TransparentVAEDecoder  # noqa: E402
from layer_diffuse.utils import crop_and_resize_image, rgba2rgbfp32  # noqa: E402


def patch_transparent_decoder_mps_median():
    """Avoid an MPS crash in torch.median over the decoder's 5D augment stack."""

    def estimate_augmented(self, pixel, latent):
        args = [
            [False, 0], [False, 1], [False, 2], [False, 3],
            [True, 0], [True, 1], [True, 2], [True, 3],
        ]
        result = []
        for flip, rok in args:
            feed_pixel = pixel.clone()
            feed_latent = latent.clone()
            if flip:
                feed_pixel = torch.flip(feed_pixel, dims=(3,))
                feed_latent = torch.flip(feed_latent, dims=(3,))
            feed_pixel = torch.rot90(feed_pixel, k=rok, dims=(2, 3))
            feed_latent = torch.rot90(feed_latent, k=rok, dims=(2, 3))
            eps = self.estimate_single_pass(feed_pixel, feed_latent).clip(0, 1)
            eps = torch.rot90(eps, k=-rok, dims=(2, 3))
            if flip:
                eps = torch.flip(eps, dims=(3,))
            result.append(eps)
        stacked = torch.stack(result, dim=0)
        if stacked.device.type == "mps":
            return torch.median(stacked.cpu(), dim=0).values.to(device=stacked.device, dtype=stacked.dtype)
        return torch.median(stacked, dim=0).values

    TransparentVAEDecoder.estimate_augmented = estimate_augmented


WEIGHT_REPO = "LayerDiffusion/layerdiffusion-v1"
TRANSPARENT_DECODER = "layer_sd15_vae_transparent_decoder.safetensors"
LCM_LORA_REPO = "latent-consistency/lcm-lora-sdv1-5"
WEIGHTS = {
    "fg_only": "layer_sd15_transparent_attn.safetensors",
    "bg2fg": "layer_sd15_bg2fg.safetensors",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(WEIGHTS), default="bg2fg")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--background", default="")
    parser.add_argument("--mask", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="digiplay/Juggernaut_final")
    parser.add_argument("--vae-subfolder", default="vae")
    parser.add_argument("--speed-preset", choices=["normal", "lcm"], default="normal")
    parser.add_argument("--seed", type=int, default=93)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--guidance-scale", type=float, default=7.0)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cpu-offload", action="store_true")
    return parser.parse_args()


def choose_device(name: str) -> str:
    if name != "auto":
        return name
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_weight(name: str) -> str:
    return hf_hub_download(repo_id=WEIGHT_REPO, filename=name)


def load_pipeline(args, device: str):
    decoder_path = load_weight(TRANSPARENT_DECODER)
    vae = TransparentVAEDecoder.from_pretrained(
        args.model,
        subfolder=args.vae_subfolder,
        torch_dtype=torch.float16,
    )
    vae.set_transparent_decoder(
        load_file(str(decoder_path)),
        mod_number=2 if args.mode == "bg2fg" else 1,
    )

    pipe = StableDiffusionPipeline.from_pretrained(
        args.model,
        vae=vae,
        torch_dtype=torch.float16,
        safety_checker=None,
    )
    pipe.set_progress_bar_config(disable=True)
    if args.cpu_offload:
        pipe.enable_model_cpu_offload()
    else:
        pipe = pipe.to(device)

    if args.speed_preset == "lcm":
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        pipe.load_lora_weights(LCM_LORA_REPO)
        pipe.fuse_lora()
    return pipe


def encode_condition(path: str, width: int, height: int):
    image = Image.open(path).convert("RGBA")
    arr = np.array(image)
    arr = crop_and_resize_image(rgba2rgbfp32(arr), 1, height, width)
    tensor = torch.from_numpy(np.ascontiguousarray(arr[None].copy())).movedim(-1, 1)
    return tensor.float() * 2.0 - 1.0


def clamp_alpha_to_mask(image: Image.Image, mask_path: str) -> Image.Image:
    if not mask_path:
        return image
    rgba = image.convert("RGBA")
    mask = Image.open(mask_path).convert("L").resize(rgba.size, Image.Resampling.LANCZOS)
    arr = np.array(rgba)
    mask_arr = np.array(mask, dtype=np.uint8)
    arr[:, :, 3] = np.minimum(arr[:, :, 3], mask_arr)
    return Image.fromarray(arr, mode="RGBA")


def main():
    args = parse_args()
    patch_transparent_decoder_mps_median()
    device = choose_device(args.device)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    weight_path = load_weight(WEIGHTS[args.mode])
    pipe = load_pipeline(args, device)

    frames = 1
    cross_attention_kwargs = None
    num_images = 1
    if args.mode == "bg2fg":
        if not args.background:
            raise ValueError("--background is required for bg2fg")
        frames = 2
        kwargs_encoder = load_lora_to_unet(pipe.unet, weight_path, frames=frames, use_control=True)
        condition = encode_condition(args.background, args.width, args.height)
        background_signal = kwargs_encoder(condition)
        cross_attention_kwargs = {"layerdiffuse_control_signals": background_signal}
        num_images = 2
    else:
        load_lora_to_unet(pipe.unet, weight_path, frames=frames)

    generator = torch.Generator(device="cpu").manual_seed(args.seed)
    guidance_scale = 1.0 if args.speed_preset == "lcm" else args.guidance_scale
    num_steps = min(args.steps, 4) if args.speed_preset == "lcm" else args.steps
    images = pipe(
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
        width=args.width,
        height=args.height,
        num_inference_steps=num_steps,
        guidance_scale=guidance_scale,
        cross_attention_kwargs=cross_attention_kwargs,
        generator=generator,
        num_images_per_prompt=num_images,
        return_dict=False,
    )[0]

    result = images[0]
    result = clamp_alpha_to_mask(result, args.mask)
    result.save(output)
    print(output)


if __name__ == "__main__":
    main()
