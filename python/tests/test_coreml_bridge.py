import os
import sys
from pathlib import Path

import pytest

from compiler.coreml_bridge import CoreMLRequest, build_command, coreml_status


def test_status_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("PAPERDOLL_COREML_MODEL_DIR", raising=False)
    monkeypatch.delenv("PAPERDOLL_COREML_COMMAND_TEMPLATE", raising=False)

    status = coreml_status()

    assert status["configured"] is False
    assert status["command_template_configured"] is False


def test_apple_python_command_for_txt2img(monkeypatch, tmp_path):
    model_dir = tmp_path / "coreml-model"
    model_dir.mkdir()
    monkeypatch.setenv("PAPERDOLL_COREML_MODEL_DIR", str(model_dir))
    monkeypatch.delenv("PAPERDOLL_COREML_COMMAND_TEMPLATE", raising=False)

    req = CoreMLRequest(prompt="red velvet fabric", seed=123, steps=12)
    cmd = build_command(req, tmp_path / "out")

    assert cmd[:3] == [sys.executable, "-m", "python_coreml_stable_diffusion.pipeline"]
    assert "--prompt" in cmd
    assert "red velvet fabric" in cmd
    assert "-i" in cmd
    assert str(model_dir) in cmd
    assert "--num-inference-steps" in cmd
    assert "12" in cmd


def test_apple_python_command_rejects_inpaint_without_template(monkeypatch, tmp_path):
    model_dir = tmp_path / "coreml-model"
    model_dir.mkdir()
    monkeypatch.setenv("PAPERDOLL_COREML_MODEL_DIR", str(model_dir))
    monkeypatch.delenv("PAPERDOLL_COREML_COMMAND_TEMPLATE", raising=False)

    req = CoreMLRequest(prompt="dress", mode="inpaint")

    with pytest.raises(RuntimeError, match="does not expose inpaint"):
        build_command(req, tmp_path / "out")


def test_template_command_allows_inpaint_fields(monkeypatch, tmp_path):
    init = tmp_path / "init.png"
    mask = tmp_path / "mask.png"
    init.write_bytes(b"init")
    mask.write_bytes(b"mask")
    monkeypatch.setenv(
        "PAPERDOLL_COREML_COMMAND_TEMPLATE",
        "swift run PaperdollInpaint --prompt {prompt} --init {init_image} "
        "--mask {mask_image} --out {output_dir} --seed {seed}",
    )
    monkeypatch.setenv("PAPERDOLL_COREML_MODEL_DIR", "/models/coreml")

    req = CoreMLRequest(prompt="blue silk gown", mode="inpaint", init_image=init, mask_image=mask)
    cmd = build_command(req, tmp_path / "out")

    assert cmd[:3] == ["swift", "run", "PaperdollInpaint"]
    assert "blue silk gown" in cmd
    assert str(init) in cmd
    assert str(mask) in cmd


def test_swift_command_uses_resource_path(monkeypatch, tmp_path):
    model_dir = tmp_path / "Resources"
    package_dir = tmp_path / "ml-stable-diffusion"
    model_dir.mkdir()
    package_dir.mkdir()
    monkeypatch.setenv("PAPERDOLL_COREML_BACKEND", "swift")
    monkeypatch.setenv("PAPERDOLL_COREML_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("PAPERDOLL_COREML_SWIFT_PACKAGE", str(package_dir))
    monkeypatch.delenv("PAPERDOLL_COREML_COMMAND_TEMPLATE", raising=False)

    req = CoreMLRequest(prompt="denim fabric", steps=8, compute_unit="CPU_AND_NE")
    cmd = build_command(req, tmp_path / "out")

    assert cmd[:5] == ["swift", "run", "-c", "release", "StableDiffusionSample"]
    assert "--resource-path" in cmd
    assert str(model_dir) in cmd
    assert "--compute-units" in cmd
    assert "cpuAndNeuralEngine" in cmd
