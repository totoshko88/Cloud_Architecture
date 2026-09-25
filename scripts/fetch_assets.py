#!/usr/bin/env python3
"""Thin wrapper around ``rule_engine.fetch_assets`` for the repo's own build.

The fetch logic now lives in the installed package (``src/rule_engine/
fetch_assets.py``) so it is importable after a pip/Power install without the
repo's ``scripts/`` directory. This wrapper preserves the historical
``python scripts/fetch_assets.py`` entry point (and the ``--root`` argument that
``build_icon_sets_cli`` passes) by delegating to the package module, defaulting
the workspace to the repo root.

Usage::

    python scripts/fetch_assets.py                      # fetch all into assets/vendor
    python scripts/fetch_assets.py --only oci aws       # only some providers
    python scripts/fetch_assets.py --root assets/vendor # explicit asset root
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rule_engine import fetch_assets as _fa  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Delegate to the package fetcher, defaulting --workspace to the repo root."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if not any(a == "--workspace" for a in args):
        args = ["--workspace", str(REPO_ROOT), *args]
    return _fa.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
