"""Inpainting command bridge — warm worker (preferred) + subprocess fallback."""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional


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
    feather: int = 8
    dilate: int = 6
    controlnet: bool = False
    controlnet_model: str = "lllyasviel/control_v11p_sd15_canny"
    controlnet_scale: float = 0.5
    model_repo: str = "Sanster/anything-4.0-inpainting"
    device: str = "auto"
    image: Optional[Path] = None
    mask: Optional[Path] = None


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _worker_port() -> int:
    return int(_env("PAPERDOLL_INPAINT_WORKER_PORT", "7863") or "7863")


def _worker_base_url() -> str:
    return f"http://127.0.0.1:{_worker_port()}"


def inpaint_status() -> Dict:
    runner = _env("PAPERDOLL_INPAINT_RUNNER", "scripts/inpaint/run_inpaint.py")
    python_exe = _env("PAPERDOLL_INPAINT_PYTHON", sys.executable)
    worker_script = _env("PAPERDOLL_INPAINT_WORKER", "scripts/inpaint/worker.py")
    return {
        "configured": Path(runner).exists(),
        "python": python_exe,
        "runner": runner,
        "runner_exists": Path(runner).exists(),
        "worker_script": worker_script,
        "worker_port": _worker_port(),
        "default_model_repo": _env("PAPERDOLL_INPAINT_MODEL_REPO", "Sanster/anything-4.0-inpainting"),
    }


# ── warm worker management ────────────────────────────────────────────────────

_worker_proc: Optional[subprocess.Popen] = None
_worker_start_lock = asyncio.Lock()


async def _worker_healthy() -> bool:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{_worker_base_url()}/health")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_worker(model_repo: str = "Sanster/anything-4.0-inpainting", device: str = "auto"):
    """Start the persistent worker if not already running. Awaitable, non-blocking."""
    global _worker_proc
    async with _worker_start_lock:
        if await _worker_healthy():
            return

        python_exe = _env("PAPERDOLL_INPAINT_PYTHON", sys.executable)
        worker_script = _env("PAPERDOLL_INPAINT_WORKER", "scripts/inpaint/worker.py")
        if not Path(worker_script).exists():
            raise RuntimeError(f"Worker script not found: {worker_script}")

        _worker_proc = subprocess.Popen([
            python_exe, worker_script,
            "--port", str(_worker_port()),
            "--model-repo", model_repo,
            "--device", device,
        ])

        # Wait up to 120 s for the worker to load its model and become healthy.
        deadline = asyncio.get_event_loop().time() + 120
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2)
            if await _worker_healthy():
                return
            if _worker_proc.poll() is not None:
                raise RuntimeError("Inpaint worker process exited unexpectedly during startup")

        raise RuntimeError("Inpaint worker did not become healthy within 120 seconds")


async def submit_to_worker(req: InpaintRequest) -> str:
    """POST a job to the warm worker and return the job_id."""
    import httpx
    if req.image is None or req.mask is None:
        raise RuntimeError("image and mask paths are required")

    data = {
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt or "",
        "seed": str(req.seed),
        "steps": str(req.steps),
        "guidance_scale": str(req.guidance_scale),
        "strength": str(req.strength),
        "width": str(req.width),
        "height": str(req.height),
        "fast": "true" if req.fast else "false",
        "feather": str(req.feather),
        "dilate": str(req.dilate),
        "controlnet": "true" if req.controlnet else "false",
        "controlnet_model": req.controlnet_model,
        "controlnet_scale": str(req.controlnet_scale),
        "model_repo": req.model_repo,
        "device": req.device,
    }
    files = {
        "image": ("body_composite.png", req.image.read_bytes(), "image/png"),
        "mask": ("garment_mask.png", req.mask.read_bytes(), "image/png"),
    }

    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{_worker_base_url()}/generate", data=data, files=files)
        r.raise_for_status()
        return r.json()["job_id"]


async def cancel_worker_job(job_id: str):
    """Signal the worker to interrupt a running job."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{_worker_base_url()}/cancel/{job_id}")
    except Exception:
        pass


# ── subprocess fallback (no warm worker) ─────────────────────────────────────

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
        "--feather", str(req.feather),
        "--width", str(req.width),
        "--height", str(req.height),
        "--device", req.device,
    ]
    if req.fast:
        cmd.append("--fast")
    return cmd


def run_generation(req: InpaintRequest, output_path: Path) -> Dict:
    """Synchronous subprocess fallback — used when the warm worker is unavailable."""
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
