#!/usr/bin/env python3
"""Rewrite a hand-authored ``.drawio`` so every edge leg is axis-aligned.

Why this exists
---------------
An ``orthogonalEdgeStyle`` edge never draws a diagonal. When two consecutive
points of a route are not axis-aligned, draw.io inserts its own corner and
**chooses which way it turns** — so an unaligned waypoint is not a diagonal on
screen, it is a corner the author did not specify. That is how an edge ends up
grazing a glyph or sliding along a container border even though every waypoint
looked deliberate.

Diagrams produced through :mod:`rule_engine.diagram_layout` are aligned by the
builder, and routes computed by :mod:`rule_engine.layout_engine` are aligned after
every repair. This script is for the third case: a ``.drawio`` whose waypoints were
written or dragged **by hand**, which no generator sees. It applies the same
:func:`rule_engine.geometry.orthogonalise_route` pass, so a hand-edit converges on
the same geometry the generators produce instead of drifting from it.

What it changes, per edge:

* **Contacts are grid-resolved.** A hand-written ``exitY=0.25`` on a 78px icon
  resolves to ``y0 + 19.5`` — half a pixel off the grid every waypoint snaps to,
  which leaves a permanent kink at the arrowhead. The *fraction* is nudged (by under
  half a grid step, so the face and the directional contract are unchanged) until the
  absolute contact lands on the grid.
* **Corners are made explicit**, so the rendered path is fully determined by the
  source.
* **Backtracks collapse** — an overshoot that returns along the same axis becomes one
  clean run.
* **Both contact legs are forced perpendicular to their face**, adding an approach
  lane one grid step off the glyph when the touching leg ran *along* the face (the
  arrow sliding down a node's top border into a top-centre entry).

Usage::

    python scripts/orthogonalise_drawio.py examples/aws/01-aws-agent-platform.drawio
    python scripts/orthogonalise_drawio.py --check examples/**/*.drawio
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.geometry import (  # noqa: E402
    build_geometry,
    contact_faces,
    leg_axis,
    grid_resolve_contact,
    orthogonalise_route,
    required_leg_axis,

)

_EDGE_CELL_RE = re.compile(r'(<mxCell\b[^>]*\bedge="1"[^>]*?)(/>|>.*?</mxCell>)', re.S)
_ID_RE = re.compile(r'\bid="([^"]*)"')
_STYLE_RE = re.compile(r'\bstyle="([^"]*)"')
_ARRAY_RE = re.compile(r"<Array\b[^>]*as=\"points\"[^>]*>.*?</Array>", re.S)
_GEOM_RE = re.compile(r'(<mxGeometry\b[^>]*\bas="geometry"\s*)(/>)', re.S)


def _set_token(style: str, name: str, value: float) -> str:
    """Replace ``name=<n>`` in a style string, preserving token order."""
    text = f"{name}={value:.4f}".rstrip("0").rstrip(".")
    if re.search(rf"\b{name}=", style):
        return re.sub(rf"\b{name}=[-0-9.]+", text, style)
    return style + (";" if style and not style.endswith(";") else "") + text


def _render_points(pts: Sequence[tuple]) -> str:
    inner = "".join(
        f'\n              <mxPoint x="{px:.2f}" y="{py:.2f}" />' for px, py in pts
    )
    return f'<Array as="points">{inner}\n            </Array>'


def orthogonalise_text(text: str) -> tuple[str, List[str]]:
    """Return ``(rewritten_xml, changed_edge_ids)``."""
    geo = build_geometry(text)
    changed: List[str] = []
    edges = {e.id: e for e in geo.edges}

    def rewrite(match: re.Match) -> str:
        head, body = match.group(1), match.group(2)
        m = _ID_RE.search(head)
        eid = m.group(1) if m else ""
        e = edges.get(eid)
        if e is None:
            return match.group(0)
        src, tgt = geo.nodes.get(e.source), geo.nodes.get(e.target)
        if src is None or tgt is None:
            return match.group(0)
        if e.exit[0] is None or e.exit[1] is None or e.entry[0] is None or e.entry[1] is None:
            return match.group(0)  # a floating contact is edge-float's problem

        exit_abs, exit_frac = grid_resolve_contact(src, e.exit)
        entry_abs, entry_frac = grid_resolve_contact(tgt, e.entry)
        pts = orthogonalise_route(
            exit_abs, e.points, entry_abs,
            contact_faces(*exit_frac), contact_faces(*entry_frac),
        )
        if (
            [(round(x), round(y)) for x, y in pts]
            == [(round(x), round(y)) for x, y in e.points]
            and abs(exit_frac[0] - e.exit[0]) < 1e-6
            and abs(exit_frac[1] - e.exit[1]) < 1e-6
            and abs(entry_frac[0] - e.entry[0]) < 1e-6
            and abs(entry_frac[1] - e.entry[1]) < 1e-6
        ):
            return match.group(0)  # already aligned — leave byte-identical

        sm = _STYLE_RE.search(head)
        if sm:
            style = sm.group(1)
            for name, value in (
                ("exitX", exit_frac[0]), ("exitY", exit_frac[1]),
                ("entryX", entry_frac[0]), ("entryY", entry_frac[1]),
            ):
                style = _set_token(style, name, value)
            head = head[: sm.start(1)] + style + head[sm.end(1):]

        array = _render_points(pts) if pts else ""
        if _ARRAY_RE.search(body):
            body = _ARRAY_RE.sub(lambda _m: array, body, count=1) if array else \
                _ARRAY_RE.sub("", body, count=1)
        elif array:
            # No <Array> yet: expand a self-closing <mxGeometry ... /> to hold one.
            if _GEOM_RE.search(body):
                body = _GEOM_RE.sub(
                    lambda m: f"{m.group(1)}>\n            {array}\n          </mxGeometry>",
                    body, count=1,
                )
        changed.append(eid)
        return head + body

    return _EDGE_CELL_RE.sub(rewrite, text), changed


def report(path: Path) -> List[str]:
    """Return a human-readable list of alignment defects in ``path``."""
    geo = build_geometry(path.read_text(encoding="utf-8"))
    out: List[str] = []
    for e in geo.edges:
        src, tgt = geo.nodes.get(e.source), geo.nodes.get(e.target)
        if src is None or tgt is None or None in e.exit or None in e.entry:
            continue
        poly = (
            [(src.x + e.exit[0] * src.w, src.y + e.exit[1] * src.h)]
            + [(x, y) for x, y in e.points]
            + [(tgt.x + e.entry[0] * tgt.w, tgt.y + e.entry[1] * tgt.h)]
        )
        legs = [leg_axis(a, b) for a, b in zip(poly, poly[1:])]
        want_first = required_leg_axis(contact_faces(*e.exit))
        want_last = required_leg_axis(contact_faces(*e.entry))
        why = []
        if "D" in legs:
            why.append("diagonal leg")
        if want_first and legs[0] not in (want_first, "0"):
            why.append(f"first leg {legs[0]}, face wants {want_first}")
        if want_last and legs[-1] not in (want_last, "0"):
            why.append(f"last leg {legs[-1]}, face wants {want_last}")
        if why:
            out.append(f"{e.id}: " + "; ".join(why))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="orthogonalise_drawio")
    parser.add_argument("files", nargs="+")
    parser.add_argument(
        "--check", action="store_true",
        help="report defects and exit 1 if any; write nothing",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    failed = False
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f"error: no such file: {path}", file=sys.stderr)
            return 2
        defects = report(path)
        if args.check:
            if defects:
                failed = True
                print(f"[DEFECT] {path}", file=sys.stderr)
                for d in defects:
                    print(f"    - {d}", file=sys.stderr)
            else:
                print(f"[OK] {path}")
            continue
        text = path.read_text(encoding="utf-8")
        new, changed = orthogonalise_text(text)
        if changed:
            path.write_text(new, encoding="utf-8")
            print(f"{path}: re-aligned {len(changed)} edge(s): {', '.join(changed)}")
        else:
            print(f"{path}: already aligned")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
