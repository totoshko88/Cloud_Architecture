"""Tests for the release-notes changelog extractor (scripts/changelog_section.py).

The GitHub release workflow pulls per-version release notes from CHANGELOG.md via
this helper, so its slicing must be correct: the right section body, tolerant of a
leading ``v``, and a clean miss when the version is absent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "changelog_section.py"
_spec = importlib.util.spec_from_file_location("changelog_section", _MODULE_PATH)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)  # type: ignore[union-attr]

_SAMPLE = """# Changelog

Intro line.

## [1.1.0] - 2026-09-23

Second release summary.

### Added
- Feature B.

## [1.0.0] - 2026-09-22

First release summary.

### Added
- Feature A.
"""


def test_extracts_the_matching_section_only():
    body = cs.extract_section(_SAMPLE, "1.1.0")
    assert "Second release summary." in body
    assert "Feature B." in body
    # Must stop at the next version heading.
    assert "First release summary." not in body
    assert "Feature A." not in body


def test_tolerates_leading_v():
    assert cs.extract_section(_SAMPLE, "v1.0.0") == cs.extract_section(_SAMPLE, "1.0.0")
    assert "First release summary." in cs.extract_section(_SAMPLE, "v1.0.0")


def test_missing_version_returns_none():
    assert cs.extract_section(_SAMPLE, "9.9.9") is None


def test_real_changelog_has_current_version():
    text = (_MODULE_PATH.parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    # Whatever the current pyproject version is, it must have release notes.
    import tomllib

    version = tomllib.loads(
        (_MODULE_PATH.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    assert cs.extract_section(text, version), f"CHANGELOG.md missing section for {version}"
