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


# --- scratch / duplicate file exclusion (v1.3.x) --------------------------- #

from rule_engine.cli import _is_scratch_copy, discover_artifacts  # noqa: E402


def test_is_scratch_copy_flags_editor_duplicates():
    # Localized "copy" suffixes and numeric duplicates are scratch.
    assert _is_scratch_copy("02-aws-ha-multiregion-landscape \u043a\u043e\u043f\u0456\u044f.drawio")
    assert _is_scratch_copy("diagram - Copy.drawio")
    assert _is_scratch_copy("diagram copy.drawio")
    assert _is_scratch_copy("diagram copy 2.drawio")
    assert _is_scratch_copy("diagram (1).drawio")


def test_is_scratch_copy_keeps_legitimate_names():
    # A real name that merely contains the substring is NOT scratch.
    assert not _is_scratch_copy("01-aws-agent-platform.drawio")
    assert not _is_scratch_copy("copybook.drawio")
    assert not _is_scratch_copy("02-aws-ha-multiregion-landscape.drawio")


def test_discover_artifacts_skips_scratch_copies(tmp_path):
    ex = tmp_path / "examples" / "aws"
    _write(str(ex / "02-topic.drawio"), "<mxfile/>")
    _write(str(ex / "02-topic \u043a\u043e\u043f\u0456\u044f.drawio"), "<mxfile/>")
    _write(str(ex / "02-topic - Copy.drawio"), "<mxfile/>")
    found = discover_artifacts(str(tmp_path))
    names = {os.path.basename(a) for a in found}
    assert "02-topic.drawio" in names
    assert not any("\u043a\u043e\u043f" in n or "copy" in n.lower() for n in names)
