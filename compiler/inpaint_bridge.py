"""Inpainting command bridge (Anything-v4.5-inpainting + optional LCM-LoRA)."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_NEGATIVE = (
    "low quality, blurry, deformed, extra limbs, body paint, skin tight "
    "bodysuit, naked, watermark, text, logo, multiple people, bad anatomy, "
    "worst quality, normal quality"
)


@dataclass
class InpaintRequest:
    prompt: str
    negative_prompt: str = DEFAULT_NEGATIVE
    seed: int = 93
    steps: int = 20
    guidance_scale: float = 7.0
    strength: float = 1.0
    width: int = 512
    height: int = 512
    fast: bool = True
    model_repo: str = "Sanster/anything-4.0-inpainting"
    device: str = "auto"
    image: Optional[Path] = None
    mask: Optional[Path] = None


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def inpaint_status() -> Dict:
    runner = _env("PAPERDOLL_INPAINT_RUNNER", "scripts/inpaint/run_inpaint.py")
    python_exe = _env("PAPERDOLL_INPAINT_PYTHON", sys.executable)
    return {
        "configured": Path(runner).exists(),
        "python": python_exe,
        "runner": runner,
        "runner_exists": Path(runner).exists(),
        "default_model_repo": _env("PAPERDOLL_INPAINT_MODEL_REPO", "Sanster/anything-4.0-inpainting"),
    }


def build_command(req: InpaintRequest, output_path: Path) -> List[str]:
    python_exe = _env("PAPERDOLL_INPAINT_PYTHON", sys.executable)
    runner = _env("PAPERDOLL_INPAINT_RUNNER", "scripts/inpaint/run_inpaint.py")
    if not Path(runner).exists():
        raise RuntimeError(f"Inpaint runner not found: {runner}")
    if req.image is None:
        raise RuntimeError("image is required for inpainting")
    if req.mask is None:
        raise RuntimeError("mask is required for inpainting")

    cmd = [
        python_exe, runner,
        "--prompt", req.prompt,
        "--negative-prompt", req.negative_prompt or "",
        "--image", str(req.image),
        "--mask", str(req.mask),
        "--output", str(output_path),
        "--model-repo", req.model_repo,
        "--seed", str(req.seed),
        "--steps", str(req.steps),
        "--guidance-scale", str(req.guidance_scale),
        "--strength", str(req.strength),
        "--width", str(req.width),
        "--height", str(req.height),
        "--device", req.device,
    ]
    if req.fast:
        cmd.append("--fast")
    return cmd


def run_generation(req: InpaintRequest, output_path: Path) -> Dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(req, output_path)
    timeout = int(_env("PAPERDOLL_INPAINT_TIMEOUT_SEC", "1200") or "1200")
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Inpaint command failed ({proc.returncode}): {stderr[-2000:]}")
    if not output_path.exists():
        raise RuntimeError("Inpaint command completed but produced no output PNG")
    image_b64 = base64.b64encode(output_path.read_bytes()).decode("ascii")
    return {
        "image_path": str(output_path),
        "image_b64": image_b64,
        "command": cmd,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }
