#!/usr/bin/env python3
"""Rebuild the 06 v3 repro: ``06-flow-task-verification`` with ``atlas`` at ``sub=2``.

Defect C12 (1.10.12 plan, feedback icon-fidelity §3 / §4.3): with the
``MongoDB Atlas`` node at ``sub=2`` the ``e8`` (``lti -> atlas``) approach
corridor lands inside the ``S3 tasks / outputs`` icon band, so the e8 leg runs
through the S3 glyph and marker 8 overprints its caption, yet neither
``edge-routing knee-through-*`` nor ``marker-label-collision`` fires. SEP v4
worked around it from the spec (``sub=4``); this script restores ``sub=2`` so the
engine defect stays reproducible.

The spec is imported unchanged from ``build_06_flow_task_verification.py`` (a
verbatim copy of the SEPARCH build script); only the ``atlas`` NodeSpec is
swapped. Output goes to ``repro/06v3-atlas-sub2.drawio`` so the copied v4 triple
at the fixture root is never overwritten. The historical v3 output rendered by
engine 1.10.11 is kept beside it as ``repro/06v3-flow-task-verification.drawio``.

Run from the fixture root (``tests/fixtures/sep``) so ``assets/vendor`` paths
resolve cwd-relative::

    cd tests/fixtures/sep && ../../../.venv/bin/python scripts/build_06v3_atlas_sub2.py
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_06_flow_task_verification as b06  # noqa: E402

OUT = HERE.parent / "repro" / "06v3-atlas-sub2.drawio"


def main() -> int:
    b06.NODES = tuple(
        dataclasses.replace(n, sub=2) if n.id == "atlas" else n for n in b06.NODES
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(b06._build(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
