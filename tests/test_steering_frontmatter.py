"""Guard: every steering file carries valid Kiro inclusion frontmatter.

``diagram-standards.md`` shipped from 1.1.x to 1.6.0 starting with ``---``, a
blank line, then ``## inclusion: always`` — a Markdown formatter had read
``inclusion: always`` followed by ``---`` as a setext H2 heading and rewritten
it as ``##``. The file kept working only because Kiro's default inclusion mode
happens to be ``always``; any other mode would have been silently lost, and
nothing noticed, because the linter deliberately skips steering files. These
tests make the frontmatter a checked contract for the workspace steering and the
Power's steering alike.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_STEERING_FILES = sorted(
    list((_REPO / ".kiro" / "steering").glob("*.md"))
    + list((_REPO / "powers" / "rule-engine-artifacts" / "dev.kiro" / "steering").glob("*.md"))
)
_MODES = {"always", "fileMatch", "manual", "auto"}
# The formatter corruption: a frontmatter key turned into a Markdown heading.
_HEADING_KEY_RE = re.compile(r"^#{1,6}\s+(inclusion|fileMatchPattern|name|description)\s*:", re.M)


def _ids(paths):
    return [str(p.relative_to(_REPO)) for p in paths]


def test_steering_files_exist():
    assert len(_STEERING_FILES) >= 7


@pytest.mark.parametrize("path", _STEERING_FILES, ids=_ids(_STEERING_FILES))
def test_steering_frontmatter_is_valid(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines and lines[0] == "---", "frontmatter must start on the first line"
    try:
        end = lines.index("---", 1)
    except ValueError:
        pytest.fail("frontmatter has no closing '---'")
    meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    assert isinstance(meta, dict), "frontmatter must be a YAML mapping"
    mode = meta.get("inclusion")
    assert mode in _MODES, f"inclusion must be one of {sorted(_MODES)}, got {mode!r}"
    if mode == "fileMatch":
        assert meta.get("fileMatchPattern"), "fileMatch needs fileMatchPattern"
    if mode == "auto":
        assert meta.get("name") and meta.get("description"), "auto needs name + description"


@pytest.mark.parametrize("path", _STEERING_FILES, ids=_ids(_STEERING_FILES))
def test_no_frontmatter_key_was_turned_into_a_heading(path: Path):
    match = _HEADING_KEY_RE.search(path.read_text(encoding="utf-8"))
    assert match is None, f"a frontmatter key became a heading: {match.group(0)!r}"
