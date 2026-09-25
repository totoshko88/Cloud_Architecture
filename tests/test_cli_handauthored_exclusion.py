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
    assert _is_generated_markdown("CODE_OF_CONDUCT.md") is False
    assert _is_generated_markdown("SECURITY.md") is False
    assert _is_generated_markdown(".github/PULL_REQUEST_TEMPLATE.md") is False
    # Steering files are rule sources, not generated KB docs: both the repo's
    # own .kiro/steering and a power's dev.kiro/steering are exempt from the
    # frontmatter contract (they use Kiro's inclusion: frontmatter, not the 12
    # KB keys). Regression: a power's dev.kiro/steering used to trip a false
    # frontmatter CRITICAL and block the gate.
    assert _is_generated_markdown(".kiro/steering/diagram-standards.md") is False
    assert (
        _is_generated_markdown(
            "powers/rule-engine-artifacts/dev.kiro/steering/rule-engine-setup.md"
        )
        is False
    )
    # A companion / KB doc is still treated as generated.
    assert _is_generated_markdown("examples/aws/01-x.diagram.md") is True


def test_file_mode_skips_power_steering(tmp_path, capsys):
    # A power's dev.kiro/steering/*.md must be [SKIP], not a frontmatter CRITICAL.
    steering = tmp_path / "dev.kiro" / "steering"
    steering.mkdir(parents=True)
    p = steering / "rule-engine-setup.md"
    _write(str(p), "---\ninclusion: always\n---\n# Steering, not a KB doc\n")
    rc = main(["--file", str(p), "--fail-on", "error,critical"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[SKIP]" in out


def test_discover_skips_power_steering(tmp_path):
    # The --all scan must not pick up a power's dev.kiro/steering as a KB doc.
    from rule_engine.cli import discover_artifacts

    steering = tmp_path / "powers" / "p" / "dev.kiro" / "steering"
    steering.mkdir(parents=True)
    _write(str(steering / "setup.md"), "---\ninclusion: always\n---\n# x\n")
    ex = tmp_path / "examples" / "aws"
    _write(str(ex / "01-topic.diagram.md"), "# no frontmatter\n")
    found = discover_artifacts(str(tmp_path))
    assert not any(a.endswith(os.sep + "setup.md") for a in found)
    assert any(a.endswith("01-topic.diagram.md") for a in found)


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

from rule_engine.cli import (  # noqa: E402
    _is_reference_artifact,
    _is_scratch_copy,
    discover_artifacts,
)


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


# --- preserved -reference snapshot exclusion (lane-grid-layout-engine) ------ #


def test_is_reference_artifact_flags_reference_snapshots():
    # The frozen -reference triple (drawio + png + companion) is excluded.
    assert _is_reference_artifact("02-aws-ha-multiregion-landscape-reference.drawio")
    assert _is_reference_artifact("02-aws-ha-multiregion-landscape-reference.drawio.png")
    assert _is_reference_artifact("02-aws-ha-multiregion-summary-reference.diagram.md")


def test_is_reference_artifact_keeps_legitimate_names():
    # A live golden artifact and a name that merely contains the substring
    # (not as a terminating stem suffix) are NOT reference snapshots.
    assert not _is_reference_artifact("02-aws-ha-multiregion-landscape.drawio")
    assert not _is_reference_artifact("02-aws-ha-multiregion-summary.diagram.md")
    assert not _is_reference_artifact("reference-architecture.drawio")


def test_discover_artifacts_skips_reference_snapshots(tmp_path):
    ex = tmp_path / "examples" / "aws"
    _write(str(ex / "02-topic.drawio"), "<mxfile/>")
    _write(str(ex / "02-topic-reference.drawio"), "<mxfile/>")
    found = discover_artifacts(str(tmp_path))
    names = {os.path.basename(a) for a in found}
    assert "02-topic.drawio" in names
    assert "02-topic-reference.drawio" not in names
