#!/usr/bin/env python3
"""Measure the route quality of a ``.drawio``: crossings, rails, turns, ink.

Why this exists
---------------
The engine routes each edge by **rule** — which corridor side, which lane, which
face — with no feedback loop. Every one of the ~25 named routing patterns in
``diagram-standards.md`` was distilled from a reviewer's hand-edit, which works
until two rules disagree about the same plane.

A reviewer's 2026-09-26 hand-edit of the AWS HA landscape made that concrete. The
four routes they changed were not individually wrong by any rule; they were
*jointly* better, and the improvement is only visible when you measure the diagram
as a whole:

============================  =========  =====  ====  ======
Metric                        generated  hand   delta  weight
============================  =========  =====  ====  ======
edge-edge crossings                   7      6    -1  medium
parallel rails                        4      2    -2  **high**
turns                                50     48    -2  low
ink (Manhattan length)            11.0k  10.8k  -0.2k low
============================  =========  =====  ====  ======

The headline is **parallel rails** — a long vertical running alongside a column of
icons, which ``diagram-standards.md`` forbids outright ("no long vertical run
parallel to a node column") because it reads as a second rail beside the services.
Crossings barely moved: the reviewer traded three for four while removing two
rails, so a crossing-only objective would have rejected their edit.

This script is the instrumentation for that objective. It does not change any
diagram; it reports the four numbers so a routing change can be judged by
measurement instead of by eye, and so route quality can be tracked over time.

Definitions
-----------
* **crossing** — a horizontal segment of one edge properly intersects a vertical
  segment of another, and the two edges share no endpoint (edges leaving a common
  source legitimately share a trunk).
* **parallel rail** — a vertical run spanning at least ``RAIL_MIN_SPAN`` that comes
  within ``RAIL_CLEARANCE`` of an unrelated node's left or right border, over that
  node's own vertical extent.
* **turns** — interior vertices of the polyline (contact points excluded).
* **ink** — total Manhattan length of every route.

Usage::

    python scripts/route_quality.py examples/aws/02-aws-ha-multiregion-landscape.drawio
    python scripts/route_quality.py --all
    python scripts/route_quality.py --detail <file>     # name every finding
"""

from __future__ import annotations

import argparse
import glob
import sys
from typing import Optional, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.geometry import (  # noqa: E402
    RAIL_CLEARANCE,
    RAIL_MIN_SPAN,
    build_geometry,
    route_cost,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def measure(path: str | Path):
    """Return the :class:`~rule_engine.geometry.RouteCost` of one ``.drawio``.

    The measurement itself lives in ``rule_engine.geometry.route_cost`` so the
    engine and this script cannot drift, and so a future scored router can reuse
    the exact objective this script reports.
    """
    return route_cost(build_geometry(Path(path).read_text(encoding="utf-8")))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="route_quality")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--all", action="store_true",
                        help="measure every examples/**/*.drawio")
    parser.add_argument("--detail", action="store_true",
                        help="name every crossing pair and rail")
    args = parser.parse_args(list(argv) if argv is not None else None)

    targets = list(args.files)
    if args.all:
        targets += sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"),
                                    recursive=True))
    if not targets:
        parser.error("give a file or --all")

    for name in targets:
        path = Path(name)
        if not path.is_file():
            print(f"error: no such file: {path}", file=sys.stderr)
            return 2
        r = measure(path)
        try:
            label = str(path.relative_to(REPO_ROOT))
        except ValueError:
            label = str(path)
        print(f"{label}\n    {r.summary()}")
        if args.detail:
            for i, j in r.crossing_pairs:
                print(f"    crossing: {i} x {j}")
            for eid, nid, span in r.rail_pairs:
                print(f"    rail:     {eid} vertical span {span} beside {nid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
