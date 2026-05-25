from pathlib import Path

import pytest

from compiler.layerdiffuse_bridge import LayerDiffuseRequest, build_command, layerdiffuse_status


def test_status_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE", raising=False)
    monkeypatch.setenv("PAPERDOLL_LAYERDIFFUSE_PYTHON", "/tmp/not-real-layerdiffuse-python")

    status = layerdiffuse_status()

    assert status["configured"] is False
    assert status["python_exists"] is False


def test_default_command_uses_runner(monkeypatch, tmp_path):
    py = tmp_path / "python"
    runner = tmp_path / "runner.py"
    bg = tmp_path / "background.png"
    mask = tmp_path / "mask.png"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    runner.write_text("print('ok')\n", encoding="utf-8")
    bg.write_bytes(b"bg")
    mask.write_bytes(b"mask")
    monkeypatch.setenv("PAPERDOLL_LAYERDIFFUSE_PYTHON", str(py))
    monkeypatch.setenv("PAPERDOLL_LAYERDIFFUSE_RUNNER", str(runner))
    monkeypatch.delenv("PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE", raising=False)

    req = LayerDiffuseRequest(prompt="red dress", background=bg, mask=mask, speed_preset="lcm")
    cmd = build_command(req, tmp_path / "out.png")

    assert cmd[:2] == [str(py), str(runner)]
    assert "--mode" in cmd
    assert "bg2fg" in cmd
    assert "--background" in cmd
    assert str(bg) in cmd
    assert "--mask" in cmd
    assert str(mask) in cmd
    assert "--speed-preset" in cmd
    assert "lcm" in cmd
    assert "--steps" in cmd
    assert "4" in cmd
    assert "--guidance-scale" in cmd
    assert "1.0" in cmd


def test_default_command_requires_python(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPERDOLL_LAYERDIFFUSE_PYTHON", str(tmp_path / "missing-python"))
    monkeypatch.delenv("PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE", raising=False)

    with pytest.raises(RuntimeError, match="Python does not exist"):
        build_command(LayerDiffuseRequest(prompt="dress"), tmp_path / "out.png")


def test_template_command(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "PAPERDOLL_LAYERDIFFUSE_COMMAND_TEMPLATE",
        "python run.py --prompt {prompt} --background {background} --preset {speed_preset} --output {output}",
    )
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"bg")

    cmd = build_command(
        LayerDiffuseRequest(prompt="lace garment", background=bg, speed_preset="lcm"),
        tmp_path / "out.png",
    )

    assert cmd[:2] == ["python", "run.py"]
    assert "lace garment" in cmd
    assert str(bg) in cmd
    assert "lcm" in cmd
