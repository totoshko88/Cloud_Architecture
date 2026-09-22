#!/usr/bin/env python3
"""Extract one version's section from CHANGELOG.md for GitHub Release notes.

Given a Semantic Version (tolerating a leading ``v``), print the body of the
matching ``## [<version>] - <date>`` section from ``CHANGELOG.md`` — everything
up to (but not including) the next ``## [`` heading. Used by the release
workflow to populate the GitHub Release notes from the changelog that is the
project's source of truth for per-version history (Requirement 10.6).

Exit codes:
  0  section found and printed
  1  the version has no section in the changelog (release notes unavailable)
  2  usage error / changelog missing

Usage::

    python scripts/changelog_section.py 1.1.0 [CHANGELOG.md]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def normalize(version: str) -> str:
    return version.strip().lstrip("v").strip()


def extract_section(changelog_text: str, version: str) -> str | None:
    """Return the body of the ``## [<version>]`` section, or None if absent."""
    v = re.escape(normalize(version))
    # Match the heading line, capture everything until the next '## [' heading.
    pattern = re.compile(
        r"^##\s*\[v?" + v + r"\][^\n]*\n(.*?)(?=^##\s*\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(changelog_text)
    if not m:
        return None
    return m.group(1).strip()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: changelog_section.py <version> [changelog_path]", file=sys.stderr)
        return 2
    version = args[0]
    path = Path(args[1]) if len(args) > 1 else Path("CHANGELOG.md")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    section = extract_section(text, version)
    if section is None:
        print(
            f"error: no changelog section for version {normalize(version)!r} in {path}",
            file=sys.stderr,
        )
        return 1
    sys.stdout.write(section + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
