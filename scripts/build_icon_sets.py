#!/usr/bin/env python3
"""Thin wrapper: standardise service icons on the official bundles at init.

Delegates to :mod:`rule_engine.build_icon_sets_cli` (the installed
``rule-engine-build-icon-sets`` entry point) so the logic has a single home.
Run either as this script or via the console entry point.

Usage::

    python scripts/build_icon_sets.py                 # fetch + build index
    python scripts/build_icon_sets.py --no-fetch       # index already-fetched packs
    python scripts/build_icon_sets.py --check          # verify committed index is current
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.build_icon_sets_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
