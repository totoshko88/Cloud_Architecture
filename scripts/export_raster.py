#!/usr/bin/env python3
"""Thin shim: delegate to ``rule_engine.export_raster``.

The exporter's implementation now lives in the installed package
(``rule_engine.export_raster``, console script ``rule-engine-export-raster``) so
it ships with a pip / Kiro-Power install and is not confined to a repo checkout.
This script is kept so the historical ``python scripts/export_raster.py …``
invocation (CI, agent allow-lists, companion docs) keeps working — it simply
calls the package ``main`` after ensuring ``src/`` is importable from a bare
checkout.

The asset root defaults to the current working directory in the package; this
shim passes ``--repo-root <repo>`` by default so ``scripts/export_raster.py``
run from the repo keeps resolving ``assets/vendor`` paths against the repo root,
exactly as before.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from rule_engine.export_raster import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not any(a == "--repo-root" or a.startswith("--repo-root=") for a in argv):
        argv = ["--repo-root", str(_REPO_ROOT), *argv]
    raise SystemExit(main(argv))
