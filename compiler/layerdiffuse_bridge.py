"""LayerDiffuse command bridge for transparent garment generation."""

from __future__ import annotations

import base64
import os
import shlex
import subprocess
import sys
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Dict, List, Optional


DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, deformed, extra limbs, body paint, skin tight "
    "bodysuit, naked, watermark, text, logo, multiple people"
)


@dataclass
class LayerDiffuseRequest:
    prompt: str
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    mode: str = "bg2fg"
    speed_preset: str = "normal"
    seed: int = 93
    steps: int = 24
    guidance_scale: float = 7.0
    width: int = 512
    height: int = 512
    model: str = "digiplay/Juggernaut_final"
    device: str = "auto"
    background: Optional[Path] = None
    mask: Optional[Path] = None


def normalize_request(req: LayerDiffuseRequest) -> LayerDiffuseRequest:
    if req.speed_preset != "lcm":
        return req
    return replace(
        req,
        steps=min(req.steps, 4),
        guidance_scale=1.0,
    )


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def layerdiffuse_status() -> Dict:
    venv_python = _env("PAPERDOLL_LAYERDIFFUSE_PYTHON", ".venv-layerdiffuse/bin/python")
    runner = _env("PAPERDOLL_LAYERDIFFUSE_RUNNER", "scripts/layerdiffuse/run_layerdiffuse.py")
    vendor_dir = _env("PAPERDOLL_LAYERDIFFUSE_VENDOR", "vendor/diffuser_layerdiffuse")
    command_template = _env("PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE")
    return {
        "configured": Path(venv_python).exists() or bool(command_template),
        "python": venv_python,
        "python_exists": Path(venv_python).exists(),
        "runner": runner,
        "runner_exists": Path(runner).exists(),
        "vendor": vendor_dir,
        "vendor_exists": Path(vendor_dir).exists(),
        "command_template_configured": bool(command_template),
        "model": _env("PAPERDOLL_LAYERDIFFUSE_MODEL", "digiplay/Juggernaut_final"),
    }


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            fields.add(field_name)
    return fields


def _build_template_command(req: LayerDiffuseRequest, output_path: Path) -> List[str]:
    req = normalize_request(req)
    template = _env("PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE")
    if not template:
        raise RuntimeError("PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE is not configured")
    values = {
        "prompt": shlex.quote(req.prompt),
        "negative_prompt": shlex.quote(req.negative_prompt or ""),
        "mode": shlex.quote(req.mode),
        "seed": str(req.seed),
        "steps": str(req.steps),
        "guidance_scale": str(req.guidance_scale),
        "speed_preset": shlex.quote(req.speed_preset),
        "width": str(req.width),
        "height": str(req.height),
        "model": shlex.quote(req.model),
        "device": shlex.quote(req.device),
        "background": shlex.quote(str(req.background or "")),
        "mask": shlex.quote(str(req.mask or "")),
        "output": shlex.quote(str(output_path)),
    }
    missing = _template_fields(template) - set(values)
    if missing:
        raise RuntimeError(f"Unknown LayerDiffuse command template fields: {sorted(missing)}")
    return shlex.split(template.format(**values))


def build_command(req: LayerDiffuseRequest, output_path: Path) -> List[str]:
    req = normalize_request(req)
    if _env("PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE"):
        return _build_template_command(req, output_path)
    python_exe = _env("PAPERDOLL_LAYERDIFFUSE_PYTHON", ".venv-layerdiffuse/bin/python")
    runner = _env("PAPERDOLL_LAYERDIFFUSE_RUNNER", "scripts/layerdiffuse/run_layerdiffuse.py")
    if not Path(python_exe).exists():
        raise RuntimeError(f"LayerDiffuse Python does not exist: {python_exe}")
    if not Path(runner).exists():
        raise RuntimeError(f"LayerDiffuse runner does not exist: {runner}")

    cmd = [
        python_exe,
        runner,
        "--mode", req.mode,
        "--prompt", req.prompt,
        "--negative-prompt", req.negative_prompt or "",
        "--seed", str(req.seed),
        "--steps", str(req.steps),
        "--guidance-scale", str(req.guidance_scale),
        "--speed-preset", req.speed_preset,
        "--width", str(req.width),
        "--height", str(req.height),
        "--model", req.model,
        "--device", req.device,
        "--output", str(output_path),
    ]
    if req.background:
        cmd.extend(["--background", str(req.background)])
    if req.mask:
        cmd.extend(["--mask", str(req.mask)])
    if _env("PAPERDOLL_LAYERDIFFUSE_CPU_OFFLOAD") == "1":
        cmd.append("--cpu-offload")
    return cmd


def run_generation(req: LayerDiffuseRequest, output_path: Path) -> Dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(req, output_path)
    timeout = int(_env("PAPERDOLL_LAYERDIFFUSE_TIMEOUT_SEC", "1800") or "1800")
    proc = subprocess.run(
        cmd,
        cwd=_env("PAPERDOLL_LAYERDIFFUSE_WORKDIR") or None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"LayerDiffuse command failed ({proc.returncode}): {stderr[-2000:]}")
    if not output_path.exists():
        raise RuntimeError("LayerDiffuse command completed but produced no output PNG")
    image_b64 = base64.b64encode(output_path.read_bytes()).decode("ascii")
    return {
        "image_path": str(output_path),
        "image_b64": image_b64,
        "command": cmd,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }
