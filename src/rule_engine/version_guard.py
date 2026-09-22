"""Release version guard (Requirement 10.7).

The CI Pipeline packages a Release Bundle only for a Semantic Version that is
not already recorded in the Changelog. If a release trigger specifies a
Semantic Version that already exists in ``CHANGELOG.md``, the run must fail and
produce no Release Bundle.

This module extracts that duplicate-version check into a small, testable unit
so it can run as an early CI ``version-guard`` job (before the build stage
packages any bundle) and be exercised directly by unit tests.

A version is considered "present" in the Changelog when the Changelog contains
a version section heading for it, i.e. a line of the form::

    ## [1.2.3] - 2025-01-15
    ## [1.2.3]

The comparison is on the exact Semantic Version string, tolerant of an optional
leading ``v`` (``v1.2.3`` and ``1.2.3`` are treated as the same version).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


class DuplicateVersionError(ValueError):
    """Raised when a release Semantic Version already exists in the Changelog."""

    def __init__(self, version: str, changelog_path: str | Path | None = None) -> None:
        self.version = version
        self.changelog_path = str(changelog_path) if changelog_path is not None else None
        location = f" in {self.changelog_path}" if self.changelog_path else ""
        super().__init__(
            f"Semantic Version {version!r} already exists in the Changelog{location}; "
            "refusing to produce a Release Bundle."
        )


def normalize_version(version: str) -> str:
    """Return the bare Semantic Version, dropping an optional leading ``v``.

    ``"v1.2.3"`` and ``" 1.2.3 "`` both normalize to ``"1.2.3"``.
    """
    return version.strip().lstrip("v").strip()


def changelog_has_version(changelog_text: str, version: str) -> bool:
    """Return ``True`` if ``version`` already has a section in the Changelog.

    A version is present when the Changelog contains a heading line of the form
    ``## [<version>]`` (optionally followed by a date). The check tolerates an
    optional leading ``v`` on the requested version.
    """
    normalized = normalize_version(version)
    if not normalized:
        return False
    # Match a Markdown version heading: "## [<version>]" at line start,
    # allowing an optional leading "v" on the recorded version.
    pattern = r"^##\s*\[v?" + re.escape(normalized) + r"\]"
    return re.search(pattern, changelog_text, re.MULTILINE) is not None


def assert_version_absent(changelog_path: str | Path, version: str) -> None:
    """Raise :class:`DuplicateVersionError` if ``version`` is already recorded.

    If the Changelog file does not exist, the version is trivially absent and
    this function returns without error (the changelog stage will create it).
    """
    path = Path(changelog_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    if changelog_has_version(text, version):
        raise DuplicateVersionError(normalize_version(version), path)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the CI ``version-guard`` job.

    Usage::

        python -m rule_engine.version_guard <changelog_path> <version>

    Exits ``0`` when the version is absent (safe to build a Release Bundle) and
    ``1`` when the version already exists in the Changelog (fail-closed: no
    bundle is produced).
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(
            "usage: python -m rule_engine.version_guard <changelog_path> <version>",
            file=sys.stderr,
        )
        return 2
    changelog_path, version = args
    try:
        assert_version_absent(changelog_path, version)
    except DuplicateVersionError as exc:
        print(f"BLOCKING: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK: Semantic Version {normalize_version(version)!r} is not yet in "
        f"{changelog_path}; safe to build the Release Bundle."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
