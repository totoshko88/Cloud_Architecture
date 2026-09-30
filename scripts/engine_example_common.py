#!/usr/bin/env python3
"""Shared builder for engine-generated single-provider flow examples.

Every example diagram is **engine-generated**: a coordinate-free
:class:`~rule_engine.layout.model.DiagramSpec` is laid out by ``layout()`` and
serialized by ``build_diagram()``, so the geometry (node boxes, container
sizing, edge routing, caption-safe corridors) is the engine's output and is
regenerated whenever the engine changes. A generator supplies only a
:class:`ExampleSkin` — the spec, an icon renderer + label per node, the
per-container captions, the Flow text, and the title.

This generalises :mod:`genai_pipeline_common` (which is bound to the one shared
GenAI spec) to any spec, so ``aws/01`` and ``azure/01`` — previously
hand-authored — are produced the same way as every other example.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import Boundary, Edge, Node, build_diagram  # noqa: E402
from rule_engine.layout.model import DiagramSpec  # noqa: E402
from rule_engine.layout_engine import layout  # noqa: E402
from rule_engine.orthogonalise import edge_hygiene_text  # noqa: E402

IconRenderer = Callable[[Node, str], str]
_PAGE_MARGIN = 60

#: Container kind (spec) -> mapping container kind (icon_resolver / provider
#: mapping). ``account`` is the stack Boundary, ``region`` the region level,
#: ``vpc`` the Network Boundary.
_KIND = {"account": "boundary", "region": "region", "vpc": "network_boundary"}


@dataclass(frozen=True)
class ExampleSkin:
    """Everything a provider supplies on top of the coordinate-free spec."""

    spec: DiagramSpec
    renderers: Dict[str, IconRenderer]        # spec node id -> icon renderer
    labels: Dict[str, str]                    # spec node id -> display label
    container_labels: Dict[str, str]          # spec container id -> caption
    container_styles: Dict[str, str]          # spec container id -> style string
    flow_lines: Sequence[str]
    title: str
    diagram_id: str
    #: Optional per-edge geometry override (1.10.5). Maps an edge id to a dict
    #: with ``exit`` / ``entry`` unit-square contacts and absolute ``points``
    #: waypoints that REPLACE the engine-routed geometry for that edge after
    #: ``layout()``. This is the sanctioned escape hatch for a hand-verified,
    #: lower-crossing route the greedy scored router cannot reach on its own (the
    #: coordinate-free spec forbids pinning waypoints, and forcing the route
    #: through the solver tripped an unrepairable corridor-sharing finding). An
    #: override is a pure constant, so the generated diagram stays a deterministic
    #: function of its inputs and ``--check`` freshness holds. Absent → the edge
    #: keeps its engine geometry (every pre-1.10.5 example is byte-unchanged).
    edge_overrides: Optional[Dict[str, dict]] = None


def _edge_from_placed(pe, override: Optional[dict]) -> Edge:
    """Build a presentation :class:`Edge` from a placed edge, applying an optional
    geometry override (1.10.5). When ``override`` is given it replaces the
    engine-routed ``exit`` / ``entry`` / ``points`` with the hand-verified route;
    otherwise the engine geometry is used verbatim (byte-unchanged)."""
    if override is not None:
        exit_pt = tuple(override.get("exit", pe.exit))
        entry_pt = tuple(override.get("entry", pe.entry))
        pts = tuple((int(x), int(y)) for x, y in override.get("points", pe.points))
    else:
        exit_pt, entry_pt = pe.exit, pe.entry
        pts = tuple((int(x), int(y)) for x, y in pe.points)
    return Edge(
        id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
        marker=pe.spec.marker, dashed=pe.spec.dashed,
        exit=exit_pt, entry=entry_pt, points=pts,
    )


def build(skin: ExampleSkin) -> str:
    """Lay out ``skin.spec`` and serialize the full ``.drawio`` XML."""
    placed = layout(skin.spec)
    boundaries: List[Boundary] = []
    for c in skin.spec.containers:
        b = placed.containers[c.id]
        boundaries.append(Boundary(
            id=f"boundary-{c.id}", label=skin.container_labels[c.id],
            x=int(b.x), y=int(b.y), w=int(b.w), h=int(b.h),
            style=skin.container_styles[c.id],
        ))
    nodes = [
        Node(id=n.id, label=skin.labels[n.id],
             x=int(placed.nodes[n.id].x), y=int(placed.nodes[n.id].y),
             render=skin.renderers[n.id])
        for n in skin.spec.nodes
    ]
    overrides = skin.edge_overrides or {}
    edges = [
        _edge_from_placed(pe, overrides.get(pe.spec.id))
        for pe in placed.edges
    ]
    right = max(int(b.right) for b in placed.containers.values())
    bottom = max(int(b.bottom) for b in placed.containers.values())
    return build_diagram(
        diagram_id=skin.diagram_id, diagram_name=skin.diagram_id,
        title=skin.title, boundaries=boundaries, nodes=nodes, edges=edges,
        flow_lines=list(skin.flow_lines),
        legend_x=placed.legend_x, legend_w=placed.legend_w,
        page_w=max(right, placed.legend_x + placed.legend_w) + _PAGE_MARGIN,
        page_h=bottom + _PAGE_MARGIN,
    )


def run_cli(skin_factory: Callable[[], ExampleSkin], out: Path, prog: str,
            argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="compare with the committed file; write nothing")
    ap.add_argument("--out", default=str(out))
    args = ap.parse_args(argv)
    skin = skin_factory()
    xml = build(skin)
    # Deterministic edge-hygiene (1.10.5 A1/A2/A3): idempotent, so --check and
    # write see the same bytes. Edges carrying a hand-verified override are
    # exempt (already crossing-clean; hygiene must not perturb their route).
    xml, _ = edge_hygiene_text(xml, skip_ids=set((skin.edge_overrides or {}).keys()))
    path = Path(args.out)
    if args.stdout:
        sys.stdout.write(xml)
        return 0
    if args.check:
        if path.exists() and path.read_text(encoding="utf-8") == xml:
            print(f"{prog}: OK — {path} is up to date")
            return 0
        print(f"{prog}: STALE: regenerate {path}", file=sys.stderr)
        return 1
    path.write_text(xml, encoding="utf-8")
    print(f"{prog}: wrote {path} ({len(skin.spec.nodes)} nodes)")
    return 0
