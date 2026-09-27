#!/usr/bin/env python3
"""Thin shim: delegate to ``rule_engine.orthogonalise``.

The implementation now lives in the installed package
(``rule_engine.orthogonalise``, console script ``rule-engine-orthogonalise``) so
it ships with a pip / Kiro-Power install. This script keeps the historical
``python scripts/orthogonalise_drawio.py …`` invocation (CI) working.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.orthogonalise import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
