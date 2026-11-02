"""1.13.0: ``.lintignore`` and non-KB Markdown in lint discovery."""

from __future__ import annotations

import os
from pathlib import Path

from rule_engine import cli


def _touch(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _rel(root: Path, found):
    return sorted(os.path.relpath(p, root).replace(os.sep, "/") for p in found)


def test_discovery_honours_lintignore_and_non_kb_markdown(tmp_path):
    _touch(tmp_path / "scripts/README-13.md")
    _touch(tmp_path / "DELTA-x.md")
    _touch(tmp_path / "docs/notes.md")
    _touch(tmp_path / "01-topic.diagram.md")
    _touch(tmp_path / "inventory-aws-123456789012-us-east-1-2026-10-31_2044/x.json", "{}")
    _touch(tmp_path / ".lintignore", "# notes are hand-authored\n\ndocs/notes.md\n")
    found = cli.discover_artifacts(str(tmp_path))
    assert _rel(tmp_path, found) == [
        "01-topic.diagram.md",
        "inventory-aws-123456789012-us-east-1-2026-10-31_2044/x.json",
    ]


def test_lintignore_directory_pattern_prunes_tree(tmp_path):
    _touch(tmp_path / "drafts/a/01-old.drawio")
    _touch(tmp_path / "02-new.drawio")
    _touch(tmp_path / ".lintignore", "drafts/\n")
    assert _rel(tmp_path, cli.discover_artifacts(str(tmp_path))) == ["02-new.drawio"]


def test_lintignore_glob_matches_files(tmp_path):
    _touch(tmp_path / "x/01-a.drawio")
    _touch(tmp_path / "x/02-b.drawio")
    _touch(tmp_path / ".lintignore", "x/01-*.drawio\n")
    assert _rel(tmp_path, cli.discover_artifacts(str(tmp_path))) == ["x/02-b.drawio"]


def test_companion_and_inventory_markdown_never_exempt(tmp_path):
    _touch(tmp_path / "scripts/03-x.diagram.md")
    _touch(tmp_path / "inventory-aws-123456789012-us-east-1-2026-10-31_2044/README-x.md")
    found = _rel(tmp_path, cli.discover_artifacts(str(tmp_path)))
    assert found == [
        "inventory-aws-123456789012-us-east-1-2026-10-31_2044/README-x.md",
        "scripts/03-x.diagram.md",
    ]


def test_generated_markdown_predicate():
    assert not cli._is_generated_markdown("ws/scripts/README-13.md")
    assert not cli._is_generated_markdown("ws/DELTA-2026-10-31.md")
    assert not cli._is_generated_markdown("ws/README-network.md")
    assert cli._is_generated_markdown("ws/scripts/01-a.diagram.md")
    assert cli._is_generated_markdown("ws/docs/kb-page.md")
    # A note inside a snapshot keeps the KB contract (inventory is never exempt).
    snap = "ws/inventory-aws-123456789012-us-east-1-2026-10-31_2044"
    assert cli._is_generated_markdown(f"{snap}/delta-report.md")
    assert cli._is_generated_markdown(f"{snap}/scripts/README-x.md")
