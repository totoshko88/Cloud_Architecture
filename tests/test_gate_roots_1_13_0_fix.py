"""1.13.0: every gate takes ``--workspace-root`` and defaults to the cwd."""

from __future__ import annotations

import shutil
from pathlib import Path

from rule_engine import asset_paths_guard, raster_gate, snapshot_gate

REPO = Path(__file__).resolve().parents[1]
STEM = "01-aws-agent-platform"


def _workspace(tmp_path: Path) -> Path:
    for suffix in (".drawio", ".drawio.png", ".diagram.md"):
        shutil.copy(REPO / "examples/aws" / f"{STEM}{suffix}", tmp_path / f"{STEM}{suffix}")
    return tmp_path


def test_raster_gate_defaults_to_cwd_without_examples_dir(tmp_path, monkeypatch, capsys):
    ws = _workspace(tmp_path)
    monkeypatch.chdir(ws)
    code = raster_gate.main([])
    out = capsys.readouterr()
    assert code != raster_gate.EXIT_USAGE, out.err
    assert code == raster_gate.EXIT_OK, out.err
    assert "all 1 exported raster(s)" in out.out


def test_raster_gate_skips_excluded_dirs_at_workspace_root(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    vendor = ws / "assets" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "style-guide.drawio").write_text("<mxfile/>", encoding="utf-8")
    monkeypatch.chdir(ws)
    assert raster_gate.main([]) == raster_gate.EXIT_OK


def test_workspace_root_equals_repo_root_alias(tmp_path, monkeypatch, capsys):
    ws = _workspace(tmp_path)
    monkeypatch.chdir(REPO / "src")  # cwd is NOT the workspace
    new = raster_gate.main(["--workspace-root", str(ws)])
    out_new = capsys.readouterr().out
    old = raster_gate.main(["--repo-root", str(ws)])
    out_old = capsys.readouterr().out
    assert new == old == raster_gate.EXIT_OK
    assert out_new == out_old


def test_raster_gate_empty_cwd_is_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert raster_gate.main([]) == raster_gate.EXIT_USAGE


def test_snapshot_gate_accepts_workspace_root(tmp_path, capsys):
    assert snapshot_gate.main(["--workspace-root", str(tmp_path)]) == snapshot_gate.EXIT_OK
    assert "no inventory-* snapshot folder" in capsys.readouterr().out
    root = REPO / "examples"
    assert snapshot_gate.main(["--workspace-root", str(root)]) == snapshot_gate.main(
        ["--root", str(root)]
    )


def test_asset_paths_guard_accepts_workspace_root(tmp_path, capsys):
    """``--workspace-root`` and the ``--repo-root`` alias give one result."""
    new = asset_paths_guard.main(["--workspace-root", str(tmp_path)])
    out_new = capsys.readouterr()
    old = asset_paths_guard.main(["--repo-root", str(tmp_path)])
    out_old = capsys.readouterr()
    assert new == old == 0
    assert (out_new.out, out_new.err) == (out_old.out, out_old.err)
