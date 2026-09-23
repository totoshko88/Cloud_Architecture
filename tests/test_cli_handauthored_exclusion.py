"""Tests for the hand-authored Markdown exclusion in rule-engine-lint.

Hand-authored project docs (README, ARCHITECTURE, a SKILL.md manifest, ...) are
not engine-generated KB documents, so the kb-frontmatter contract must not apply
to them. This is enforced in two places:

* the ``--all`` scan skips them (``_is_generated_markdown`` filters discovery), and
* the ``--file`` mode reports them ``[SKIP]`` with exit 0 rather than raising a
  false ``frontmatter`` CRITICAL (important because the lint-on-save hook calls
  ``--file`` on any saved ``.md``).

A genuinely generated KB document with no frontmatter must still be flagged.
"""

from __future__ import annotations

import os

from rule_engine.cli import _is_generated_markdown, main


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


_NO_FRONTMATTER = "# Title\n\nSome hand-authored prose without YAML frontmatter.\n"


def test_is_generated_markdown_excludes_hand_authored_basenames():
    assert _is_generated_markdown("docs/ARCHITECTURE.md") is False
    assert _is_generated_markdown("docs/KIRO-UNIVERSITY-COMPLIANCE.md") is False
    assert _is_generated_markdown(".kiro/skills/x/SKILL.md") is False
    assert _is_generated_markdown("README.md") is False
    # A companion / KB doc is still treated as generated.
    assert _is_generated_markdown("examples/aws/01-x.diagram.md") is True


def test_file_mode_skips_hand_authored_doc(tmp_path, capsys):
    p = tmp_path / "ARCHITECTURE.md"
    _write(str(p), _NO_FRONTMATTER)
    rc = main(["--file", str(p), "--fail-on", "error,critical"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[SKIP]" in out


def test_file_mode_skips_skill_manifest(tmp_path, capsys):
    p = tmp_path / "SKILL.md"
    _write(str(p), _NO_FRONTMATTER)
    rc = main(["--file", str(p), "--fail-on", "error,critical"])
    assert rc == 0
    assert "[SKIP]" in capsys.readouterr().out


def test_file_mode_still_flags_generated_doc_without_frontmatter(tmp_path, capsys):
    # A *.diagram.md with no frontmatter is a real KB doc -> frontmatter CRITICAL.
    p = tmp_path / "01-topic.diagram.md"
    _write(str(p), _NO_FRONTMATTER)
    rc = main(["--file", str(p), "--fail-on", "error,critical"])
    out = capsys.readouterr().out
    assert rc != 0
    assert "frontmatter" in out
