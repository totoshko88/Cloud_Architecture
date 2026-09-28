"""Single source of truth for every place the engine version is pinned.

A release bump used to be a grep for the old version string followed by hand
edits, and the old string also appears as historical prose ("New in 1.10.0"),
so the grep was noisy and a pin could be missed. This table names each pin by
file and by an anchored regex whose single capture group is the version, so the
bump script (``scripts/release.py bump``) rewrites exactly the pins and nothing
else, and ``tests/test_version_pin_table.py`` checks every pin against
``pyproject.toml``.

``required`` pins are committed and must exist. Optional pins are generated or
git-ignored copies (``VERSION`` is written by CI at tag time; the
``_bootstrap`` payload is staged by ``build_backend.py``) and are updated only
when present, so a local tree stays self-consistent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

__all__ = ["Pin", "PINS", "read_pin", "rewrite_pin", "SEMVER_RE"]

#: A bare Semantic Version (no leading ``v``).
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class Pin:
    """One pinned occurrence of the engine version."""

    path: str
    #: Anchored pattern; group 1 is the version string.
    pattern: str
    required: bool = True
    #: Expected number of matches in the file (a pin repeated twice is a bug
    #: the table should know about, not something the bump silently skips).
    count: int = 1

    def regex(self) -> "re.Pattern[str]":
        return re.compile(self.pattern, re.MULTILINE)


PINS: Tuple[Pin, ...] = (
    Pin("pyproject.toml", r'^version = "(\d+\.\d+\.\d+)"$'),
    Pin("powers/rule-engine-artifacts/plugin.json", r'^  "version": "(\d+\.\d+\.\d+)",$'),
    Pin(
        "powers/rule-engine-artifacts/skills/rule-engine-artifacts/scripts/bootstrap.sh",
        r'^RULE_ENGINE_VERSION="\$\{RULE_ENGINE_VERSION:-(\d+\.\d+\.\d+)\}"$',
    ),
    Pin(".kiro/hooks/check-workspace-init.json", r"Cloud_Architecture\.git@v(\d+\.\d+\.\d+)"),
    # Generated / git-ignored copies, kept consistent when present.
    Pin("VERSION", r"^(\d+\.\d+\.\d+)$", required=False),
    Pin(
        "src/rule_engine/_bootstrap/kiro/hooks/check-workspace-init.json",
        r"Cloud_Architecture\.git@v(\d+\.\d+\.\d+)",
        required=False,
    ),
)


def read_pin(root: Path, pin: Pin) -> Optional[List[str]]:
    """Return the versions the pin currently holds, or ``None`` if the file is absent."""
    path = Path(root) / pin.path
    if not path.is_file():
        return None
    return pin.regex().findall(path.read_text(encoding="utf-8"))


def rewrite_pin(root: Path, pin: Pin, new_version: str) -> Tuple[str, str]:
    """Return ``(old_text, new_text)`` with the pin rewritten to ``new_version``.

    Only the capture group changes; the surrounding text is preserved byte for
    byte. Raises ``ValueError`` when the pin is not found exactly ``pin.count``
    times, so a drifted file fails loudly instead of being half-bumped.
    """
    if not SEMVER_RE.match(new_version):
        raise ValueError(f"not a bare X.Y.Z version: {new_version!r}")
    path = Path(root) / pin.path
    old = path.read_text(encoding="utf-8")
    rx = pin.regex()
    found = len(rx.findall(old))
    if found != pin.count:
        raise ValueError(f"{pin.path}: expected {pin.count} pin(s), found {found}")

    def repl(m: "re.Match[str]") -> str:
        s, e = m.span(1)
        whole = m.group(0)
        off = m.start(0)
        return whole[: s - off] + new_version + whole[e - off :]

    return old, rx.sub(repl, old)
