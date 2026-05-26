"""Minimal shim providing the three functions extend_sam.py imports from
see-through's utils.torch_utils, plus init_model_from_pretrained for
body_parser.py. No other see-through dependencies needed.
"""
from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Optional, Union

import numpy as np
import torch
import torch.nn as nn
from einops import rearrange
from PIL import Image
from torchvision.transforms.functional import pil_to_tensor
import torchvision.transforms.functional as tv_functional


# ---------------------------------------------------------------------------
# fix_params
# ---------------------------------------------------------------------------

def fix_params(model: nn.Module) -> None:
    for param in model.parameters():
        param.requires_grad = False


# ---------------------------------------------------------------------------
# tensor2img
# ---------------------------------------------------------------------------

def tensor2img(
    t: torch.Tensor,
    output_type: str = "numpy",
    denormalize: bool = False,
    mean: Union[float, list] = 0.0,
    std: Union[float, list] = 255.0,
    from_mode: str = "RGB",
    convert_mode: Optional[str] = None,
    src_dim_order: str = "chw",
    dtype=np.uint8,
    clip=(0, 255),
):
    def _norm_val(v, c):
        if isinstance(v, (int, float)):
            return v
        v = np.array(v)
        if len(v) > c:
            v = v[:c]
        return v.reshape(1, 1, -1)

    t = t.detach().to(device="cpu", dtype=torch.float32).squeeze().numpy()

    if t.ndim == 3:
        if src_dim_order == "chw":
            t = rearrange(t, "c h w -> h w c")
        c = t.shape[-1]
    else:
        c = 1

    if denormalize:
        t = t * _norm_val(std, c) + _norm_val(mean, c)

    if clip is not None:
        t = np.clip(t, clip[0], clip[1])

    image = t.astype(dtype)

    if output_type == "pil":
        if image.ndim == 2:
            from_mode = "L"
        image = Image.fromarray(image, mode=from_mode)
        if convert_mode:
            image = image.convert(convert_mode)
    else:
        image = np.ascontiguousarray(image)

    return image


# ---------------------------------------------------------------------------
# img2tensor
# ---------------------------------------------------------------------------

def img2tensor(
    img,
    normalize: bool = False,
    mean: Union[float, list] = 0.0,
    std: Union[float, list] = 255.0,
    dim_order: str = "bchw",
    dtype=torch.float32,
    device: str = "cpu",
    imread_mode: str = "RGB",
) -> torch.Tensor:
    def _norm_vals(v, c):
        if isinstance(v, (int, float)):
            return [v] * c
        v = list(v)
        return v[:c] if len(v) > c else v

    if isinstance(img, str):
        img = Image.open(img).convert(imread_mode)

    if isinstance(img, Image.Image):
        img = pil_to_tensor(img)
        if dim_order == "bchw":
            img = img.unsqueeze(0)
        elif dim_order == "hwc":
            img = img.permute(1, 2, 0)
    elif isinstance(img, np.ndarray):
        if img.ndim == 2:
            img = img[..., None]
        if dim_order == "bchw":
            img = rearrange(img, "h w c -> c h w")[None, ...]
        elif dim_order == "chw":
            img = rearrange(img, "h w c -> c h w")
        img = torch.from_numpy(np.ascontiguousarray(img))
    else:
        raise TypeError(f"img2tensor: unsupported type {type(img)}")

    img = img.to(device=device, dtype=dtype)

    if normalize and mean is not None and std is not None:
        if dim_order == "bchw":
            c = img.shape[1]
        elif dim_order == "chw":
            c = img.shape[0]
        else:
            c = img.shape[2]
        img = tv_functional.normalize(img, mean=_norm_vals(mean, c), std=_norm_vals(std, c))

    return img


# ---------------------------------------------------------------------------
# init_model_from_pretrained
# ---------------------------------------------------------------------------

def _get_module_by_name(module, access_string: str):
    return reduce(getattr, access_string.split("."), module)


def _load_state_dict(path: str) -> dict:
    ext = Path(path).suffix.lower()
    if ext == ".safetensors":
        import safetensors.torch
        return safetensors.torch.load_file(path, device="cpu")
    # .pt / .pth / .bin — try weights_only first, fall back for old-style checkpoints
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except Exception:
        return torch.load(path, map_location="cpu", weights_only=False)


def _resolve_checkpoint(pretrained_model_name_or_path: str, weights_name: Optional[str]) -> str:
    p = Path(pretrained_model_name_or_path)
    if p.is_file():
        return str(p)
    if p.is_dir():
        candidates = ([weights_name] if weights_name else []) + [
            "model.safetensors", "pytorch_model.bin", "model.bin",
        ]
        for name in candidates:
            candidate = p / name
            if candidate.exists():
                return str(candidate)
        raise FileNotFoundError(f"No checkpoint found in {p}")
    # HF repo id — if weights_name given, download it directly
    from huggingface_hub import hf_hub_download, list_repo_files
    if weights_name:
        return hf_hub_download(pretrained_model_name_or_path, filename=weights_name)
    # Discover the checkpoint file from the repo listing
    repo_files = list(list_repo_files(pretrained_model_name_or_path))
    for ext in (".safetensors", ".pt", ".pth", ".bin"):
        matches = [f for f in repo_files if f.endswith(ext)]
        if matches:
            return hf_hub_download(pretrained_model_name_or_path, filename=matches[0])
    raise FileNotFoundError(
        f"No recognisable checkpoint file found in HF repo {pretrained_model_name_or_path}. "
        f"Files: {repo_files}"
    )


def init_model_from_pretrained(
    pretrained_model_name_or_path: str,
    module_cls,
    subfolder: Optional[str] = None,
    model_args: Optional[dict] = None,
    weights_name: Optional[str] = None,
    patch_state_dict_func=None,
    download_from_hf: bool = True,
    device: str = "cpu",
    pass_statedict_to_model_init: bool = False,
) -> nn.Module:
    if model_args is None:
        model_args = {}

    if not download_from_hf and Path(pretrained_model_name_or_path).exists():
        ckpt_path = pretrained_model_name_or_path
    else:
        ckpt_path = _resolve_checkpoint(pretrained_model_name_or_path, weights_name)

    state_dict = _load_state_dict(ckpt_path)

    import accelerate
    with accelerate.init_empty_weights(include_buffers=False):
        if pass_statedict_to_model_init:
            model, state_dict = module_cls(**model_args, state_dict=state_dict)
        else:
            model = module_cls(**model_args)

    if patch_state_dict_func is not None:
        result = patch_state_dict_func(model, state_dict)
        if result is not None:
            state_dict = result

    if "state_dict" in state_dict:
        state_dict = state_dict["state_dict"]

    incompatible = model.load_state_dict(state_dict, strict=False, assign=True)

    missing_set = set(incompatible.missing_keys)
    for k in incompatible.missing_keys:
        if k.endswith(".bias") and k.replace(".bias", ".weight") in missing_set:
            continue
        try:
            mod = _get_module_by_name(model, k.replace(".weight", "").replace(".bias", ""))
        except AttributeError:
            continue
        if isinstance(mod, nn.Parameter):
            mod.data = torch.randn(mod.data.size(), device="cpu")
        else:
            try:
                mod.to_empty(device="cpu")
                mod.reset_parameters()
            except Exception:
                pass

    if device != "cpu":
        model = model.to(device=device)

    return model
