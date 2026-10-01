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
import dataclasses
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


def _native_net(provider: str) -> str:
    return load_terminology()["resources"]["network_boundary"][provider]["label"].lower()


def build(skin: GenaiSkin) -> str:
    spec = genai_spec(api_global=skin.api_global)
    labels = {
        "account": skin.account_label,
        "region": f"region {skin.region}",
        "vpc": f"{_native_net(skin.provider)}-{skin.network_name}",
    }
    styles = {
        c.id: resolve_container(_KIND[c.kind], skin.provider)["style_string"]
        for c in spec.containers
    }
    # 1.10.6: the layout oracle scores the captions/styles this skin draws.
    spec = dataclasses.replace(
        spec,
        container_captions=tuple(sorted((c.id, labels[c.label_key]) for c in spec.containers)),
        container_styles=tuple(sorted(styles.items())),
    )
    placed = layout(spec)
    boundaries: List[Boundary] = []
    for c in spec.containers:
        b = placed.containers[c.id]
        boundaries.append(Boundary(
            id=f"boundary-{c.id}", label=labels[c.label_key],
            x=int(b.x), y=int(b.y), w=int(b.w), h=int(b.h),
            style=styles[c.id],
        ))
    nodes = [
        Node(id=n.id, label=skin.labels[n.id],
             x=int(placed.nodes[n.id].x), y=int(placed.nodes[n.id].y),
             render=skin.renderers[n.id])
        for n in spec.nodes
    ]
    def _edge(pe):
        # 1.10.6: engine-routed geometry only (no overrides — the scored solver
        # reaches the clean route itself; REVIEW.md D24).
        pts = tuple((int(x), int(y)) for x, y in pe.points)
        return Edge(id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
                    marker=pe.spec.marker, dashed=pe.spec.dashed,
                    exit=pe.exit, entry=pe.entry, points=pts)

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
    # (freshness) and write see the same bytes.
    xml, _ = edge_hygiene_text(xml)
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
