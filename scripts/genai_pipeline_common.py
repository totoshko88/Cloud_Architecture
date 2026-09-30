#!/usr/bin/env python3
"""Shared builder for the GenAI pipeline example (gcp/01, oci/01).

Both providers draw the same workload from one coordinate-free spec
(:mod:`rule_engine.genai_pipeline_spec`). ``layout()`` computes the geometry,
so the two diagrams have byte-identical node boxes, containers and routes; a
provider supplies only a :class:`GenaiSkin` (icon renderer + label per node, the
container styles from its mapping, native container captions, Flow text,
title). Regional services land outside the VPC/VCN by the engine's scope rule
(REVIEW.md D20).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.constants import load_terminology  # noqa: E402
from rule_engine.diagram_layout import Boundary, Edge, Node, build_diagram  # noqa: E402
from rule_engine.genai_pipeline_spec import genai_spec  # noqa: E402
from rule_engine.icon_resolver import resolve_container  # noqa: E402
from rule_engine.layout_engine import layout  # noqa: E402
from rule_engine.orthogonalise import edge_hygiene_text  # noqa: E402

IconRenderer = Callable[[Node, str], str]
_PAGE_MARGIN = 60
_KIND = {"account": "boundary", "region": "region", "vpc": "network_boundary"}


@dataclass(frozen=True)
class GenaiSkin:
    provider: str
    renderers: Dict[str, IconRenderer]   # spec node id -> renderer
    labels: Dict[str, str]               # spec node id -> display label
    account_label: str
    region: str
    network_name: str                    # e.g. "prod" -> "vpc-prod" / "vcn-prod"
    flow_lines: Sequence[str]
    title: str
    diagram_id: str
    api_global: bool = True
    #: Optional per-edge geometry override (1.10.5), same contract as
    #: :attr:`engine_example_common.ExampleSkin.edge_overrides`: an ``{edge_id:
    #: {"exit":…, "entry":…, "points":…}}`` map whose entries REPLACE the
    #: engine-routed geometry after ``layout()``, for a hand-verified
    #: lower-crossing route the greedy scored router cannot reach. A pure
    #: constant, so the diagram stays deterministic and --check stays fresh.
    edge_overrides: Optional[Dict[str, dict]] = None


def _native_net(provider: str) -> str:
    return load_terminology()["resources"]["network_boundary"][provider]["label"].lower()


def build(skin: GenaiSkin) -> str:
    spec = genai_spec(api_global=skin.api_global)
    placed = layout(spec)
    labels = {
        "account": skin.account_label,
        "region": f"region {skin.region}",
        "vpc": f"{_native_net(skin.provider)}-{skin.network_name}",
    }
    boundaries: List[Boundary] = []
    for c in spec.containers:
        b = placed.containers[c.id]
        boundaries.append(Boundary(
            id=f"boundary-{c.id}", label=labels[c.label_key],
            x=int(b.x), y=int(b.y), w=int(b.w), h=int(b.h),
            style=resolve_container(_KIND[c.kind], skin.provider)["style_string"],
        ))
    nodes = [
        Node(id=n.id, label=skin.labels[n.id],
             x=int(placed.nodes[n.id].x), y=int(placed.nodes[n.id].y),
             render=skin.renderers[n.id])
        for n in spec.nodes
    ]
    overrides = skin.edge_overrides or {}

    def _edge(pe):
        ov = overrides.get(pe.spec.id)
        if ov is not None:
            exit_pt = tuple(ov.get("exit", pe.exit))
            entry_pt = tuple(ov.get("entry", pe.entry))
            pts = tuple((int(x), int(y)) for x, y in ov.get("points", pe.points))
        else:
            exit_pt, entry_pt = pe.exit, pe.entry
            pts = tuple((int(x), int(y)) for x, y in pe.points)
        return Edge(id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
                    marker=pe.spec.marker, dashed=pe.spec.dashed,
                    exit=exit_pt, entry=entry_pt, points=pts)

    edges = [_edge(pe) for pe in placed.edges]
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


def run_cli(skin_factory: Callable[[], GenaiSkin], out: Path, prog: str,
            argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="compare with the committed file; write nothing")
    ap.add_argument("--out", default=str(out))
    args = ap.parse_args(argv)
    skin = skin_factory()
    xml = build(skin)
    # Deterministic edge-hygiene (1.10.5 A1/A2/A3): separate overprinting flow
    # markers, distribute bunched ports and offset parallel trunks at generation
    # time so every emitted diagram is collision-free. Idempotent, so --check
    # (freshness) and write see the same bytes. Edges carrying a hand-verified
    # override are exempt (already clean; hygiene must not perturb their route).
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
    print(f"{prog}: wrote {path} ({len(genai_spec(api_global=skin.api_global).nodes)} nodes)")
    return 0
