"""Core ML Stable Diffusion command bridge.

This module deliberately does not import Apple's Core ML package at server
startup. The generator is an external command so Paperdoll can support either
Apple's Python sample pipeline or a Swift/CoreML inpaint runner without binding
the app process to those dependencies.
"""

from __future__ import annotations

import base64
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Dict, List, Optional


DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, deformed, extra limbs, body paint, skin tight "
    "bodysuit, naked, watermark, text, logo, multiple people"
)


@dataclass
class CoreMLRequest:
    prompt: str
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    seed: int = 93
    steps: int = 28
    guidance_scale: float = 7.0
    compute_unit: str = "CPU_AND_NE"
    model_version: str = "runwayml/stable-diffusion-v1-5"
    mode: str = "txt2img"
    init_image: Optional[Path] = None
    mask_image: Optional[Path] = None
    controlnet_models: List[str] = field(default_factory=list)
    controlnet_inputs: List[Path] = field(default_factory=list)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def coreml_status() -> Dict:
    model_dir = _env("PAPERDOLL_COREML_MODEL_DIR")
    command_template = _env("PAPERDOLL_COREML_COMMAND_TEMPLATE")
    python_exe = _env("PAPERDOLL_COREML_PYTHON", sys.executable)
    swift_package = _env("PAPERDOLL_COREML_SWIFT_PACKAGE")
    backend = _env("PAPERDOLL_COREML_BACKEND", "apple_python_pipeline")
    return {
        "configured": bool(model_dir or command_template),
        "model_dir": model_dir,
        "model_dir_exists": bool(model_dir and Path(model_dir).exists()),
        "command_template_configured": bool(command_template),
        "python": python_exe,
        "swift_package": swift_package,
        "swift_package_exists": bool(swift_package and Path(swift_package).exists()),
        "default_backend": backend,
    }


def _quote_list(values: List[str]) -> str:
    return " ".join(shlex.quote(str(v)) for v in values)


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            fields.add(field_name)
    return fields


def _build_template_command(req: CoreMLRequest, output_dir: Path) -> List[str]:
    template = _env("PAPERDOLL_COREML_COMMAND_TEMPLATE")
    if not template:
        raise RuntimeError("PAPERDOLL_COREML_COMMAND_TEMPLATE is not configured")

    values = {
        "prompt": shlex.quote(req.prompt),
        "negative_prompt": shlex.quote(req.negative_prompt or ""),
        "seed": str(req.seed),
        "steps": str(req.steps),
        "guidance_scale": str(req.guidance_scale),
        "compute_unit": shlex.quote(req.compute_unit),
        "model_version": shlex.quote(req.model_version),
        "mode": shlex.quote(req.mode),
        "model_dir": shlex.quote(_env("PAPERDOLL_COREML_MODEL_DIR")),
        "output_dir": shlex.quote(str(output_dir)),
        "init_image": shlex.quote(str(req.init_image or "")),
        "mask_image": shlex.quote(str(req.mask_image or "")),
        "controlnet_models": _quote_list(req.controlnet_models),
        "controlnet_inputs": _quote_list([str(p) for p in req.controlnet_inputs]),
    }
    missing = _template_fields(template) - set(values)
    if missing:
        raise RuntimeError(f"Unknown Core ML command template fields: {sorted(missing)}")
    return shlex.split(template.format(**values))


def _build_apple_python_command(req: CoreMLRequest, output_dir: Path) -> List[str]:
    model_dir = _env("PAPERDOLL_COREML_MODEL_DIR")
    if not model_dir:
        raise RuntimeError("PAPERDOLL_COREML_MODEL_DIR is not configured")
    if not Path(model_dir).exists():
        raise RuntimeError(f"PAPERDOLL_COREML_MODEL_DIR does not exist: {model_dir}")
    if req.mode != "txt2img":
        raise RuntimeError(
            "Apple's public Python Core ML sample pipeline does not expose inpaint "
            "arguments. Set PAPERDOLL_COREML_COMMAND_TEMPLATE to a Swift/CoreML "
            "inpaint runner command."
        )
    if req.controlnet_models and len(req.controlnet_models) != len(req.controlnet_inputs):
        raise RuntimeError("ControlNet model count must match ControlNet input count")

    python_exe = _env("PAPERDOLL_COREML_PYTHON", sys.executable)
    module = _env("PAPERDOLL_COREML_MODULE", "python_coreml_stable_diffusion.pipeline")
    cmd = [
        python_exe,
        "-m",
        module,
        "--prompt",
        req.prompt,
        "-i",
        model_dir,
        "-o",
        str(output_dir),
        "--seed",
        str(req.seed),
        "--model-version",
        req.model_version,
        "--compute-unit",
        req.compute_unit,
        "--num-inference-steps",
        str(req.steps),
        "--guidance-scale",
        str(req.guidance_scale),
    ]
    if req.negative_prompt:
        cmd.extend(["--negative-prompt", req.negative_prompt])
    if req.controlnet_models:
        cmd.append("--controlnet")
        cmd.extend(req.controlnet_models)
        cmd.append("--controlnet-inputs")
        cmd.extend(str(p) for p in req.controlnet_inputs)
    return cmd


def _swift_compute_unit(value: str) -> str:
    return {
        "ALL": "all",
        "CPU_ONLY": "cpuOnly",
        "CPU_AND_GPU": "cpuAndGPU",
        "CPU_AND_NE": "cpuAndNeuralEngine",
    }.get(value, value)


def _swift_control_name(model: str) -> str:
    mapping = {
        "lllyasviel/sd-controlnet-depth": "LllyasvielSdControlnetDepth",
        "lllyasviel/sd-controlnet-openpose": "LllyasvielSdControlnetOpenpose",
        "lllyasviel/sd-controlnet-canny": "LllyasvielSdControlnetCanny",
        "lllyasviel/sd-controlnet-mlsd": "LllyasvielSdControlnetMlsd",
    }
    return mapping.get(model, model.rsplit("/", 1)[-1].replace("-", "_"))


def _build_swift_command(req: CoreMLRequest, output_dir: Path) -> List[str]:
    model_dir = _env("PAPERDOLL_COREML_MODEL_DIR")
    package_dir = _env("PAPERDOLL_COREML_SWIFT_PACKAGE", "vendor/ml-stable-diffusion")
    if not model_dir:
        raise RuntimeError("PAPERDOLL_COREML_MODEL_DIR is not configured")
    if not Path(model_dir).exists():
        raise RuntimeError(f"PAPERDOLL_COREML_MODEL_DIR does not exist: {model_dir}")
    if not Path(package_dir).exists():
        raise RuntimeError(f"PAPERDOLL_COREML_SWIFT_PACKAGE does not exist: {package_dir}")
    if req.mode == "inpaint":
        raise RuntimeError(
            "Apple's Swift sample supports image-to-image but not mask inpainting. "
            "Use mode txt2img/image2image or provide PAPERDOLL_COREML_COMMAND_TEMPLATE "
            "for a custom inpaint runner."
        )
    if req.controlnet_models and len(req.controlnet_models) != len(req.controlnet_inputs):
        raise RuntimeError("ControlNet model count must match ControlNet input count")

    cmd = [
        "swift",
        "run",
        "-c",
        "release",
        "StableDiffusionSample",
        req.prompt,
        "--negative-prompt",
        req.negative_prompt or "",
        "--resource-path",
        model_dir,
        "--output-path",
        str(output_dir),
        "--seed",
        str(req.seed),
        "--step-count",
        str(req.steps),
        "--guidance-scale",
        str(req.guidance_scale),
        "--compute-units",
        _swift_compute_unit(req.compute_unit),
        "--reduce-memory",
        "--disable-safety",
    ]
    if req.init_image is not None and req.mode == "image2image":
        cmd.extend(["--image", str(req.init_image), "--strength", _env("PAPERDOLL_COREML_IMG2IMG_STRENGTH", "0.7")])
    if req.controlnet_models:
        cmd.append("--controlnet")
        cmd.extend(_swift_control_name(model) for model in req.controlnet_models)
        cmd.append("--controlnet-inputs")
        cmd.extend(str(path) for path in req.controlnet_inputs)
    return cmd


def build_command(req: CoreMLRequest, output_dir: Path) -> List[str]:
    if _env("PAPERDOLL_COREML_COMMAND_TEMPLATE"):
        return _build_template_command(req, output_dir)
    if _env("PAPERDOLL_COREML_BACKEND") == "swift":
        return _build_swift_command(req, output_dir)
    return _build_apple_python_command(req, output_dir)


def _find_generated_png(output_dir: Path) -> Path:
    pngs = [p for p in output_dir.rglob("*.png") if p.is_file()]
    if not pngs:
        raise RuntimeError("Core ML command completed but produced no PNG output")
    return max(pngs, key=lambda p: p.stat().st_mtime)


def run_generation(req: CoreMLRequest, output_dir: Path) -> Dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(req, output_dir)
    timeout = int(_env("PAPERDOLL_COREML_TIMEOUT_SEC", "1200") or "1200")
    proc = subprocess.run(
        cmd,
        cwd=_env("PAPERDOLL_COREML_WORKDIR") or _env("PAPERDOLL_COREML_SWIFT_PACKAGE") or None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Core ML command failed ({proc.returncode}): {stderr[-2000:]}")

    image_path = _find_generated_png(output_dir)
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {
        "image_path": str(image_path),
        "image_b64": image_b64,
        "command": cmd,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }
