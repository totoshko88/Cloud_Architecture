#!/usr/bin/env python3
"""FEAT-005 (1.13.0): coordinate-free variant of SEP 10 (network topology).

The synced SEPARCH builder ``build_10_network_topology.py`` is HAND-PINNED
because the coordinate-free solver over-stretched the asymmetric AZ boxes. This
fixture re-declares the SAME diagram as a ``DiagramSpec`` (same node ids, roles,
captions, container nesting and edges as the hand-pinned tables, which it
imports; no coordinates) so the engine's layout of it can be regression-tested,
in particular the L6 lever ``ContainerSpec(fit_content=True)``. The declaration
here leaves ``fit_content`` off; ``tests/test_sep_levers_1_13_0_fix.py`` turns
it on in-test with ``dataclasses.replace``.

Depth 5: Account > VPC > {AZ 1a | AZ 1b} > subnet tiers (public, private-app,
private-batch, isolated-db), plus the disjoint external Atlas peer box. The VPC
edge devices (IGW, regional NAT) sit in the VPC outside every subnet.

Run from the fixture root (``tests/fixtures/sep``); it writes
``repro/10-coordfree.drawio``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_10_network_topology as b10  # noqa: E402  (tables only; no build at import)

from rule_engine.diagram_layout import (  # noqa: E402
    Boundary,
    CONTAINER_PAD,
    Edge,
    ICON_SIZE,
    Node,
    build_diagram,
    legend_lines_for,
    overlay_legend_lines,
)
from rule_engine.layout import DiagramSpec, layout, membership_of  # noqa: E402
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec  # noqa: E402

ROOT = HERE.parent
BASENAME = "10-network-topology"
_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Containers: the hand-pinned _CONTAINER_GEOM ids/kinds, as nesting only.
# --------------------------------------------------------------------------- #

_PARENT = {
    "boundary-account": None,
    "boundary-vpc": "boundary-account",
    "az-a": "boundary-vpc",
    "az-b": "boundary-vpc",
    "sub-pub-a": "az-a", "sub-app-a": "az-a", "sub-batch-a": "az-a", "sub-db-a": "az-a",
    "sub-pub-b": "az-b", "sub-app-b": "az-b", "sub-batch-b": "az-b", "sub-db-b": "az-b",
    "peer-atlas": None,
}
_REGION = {cid: ("b" if cid.endswith("-b") else ("" if cid in ("boundary-account", "peer-atlas") else "a"))
           for cid in _PARENT}

# Declaration order matters: subnet tiers stack public -> app -> batch -> db.
_ORDER = ("boundary-account", "boundary-vpc", "az-a", "az-b",
          "sub-pub-a", "sub-app-a", "sub-batch-a", "sub-db-a",
          "sub-pub-b", "sub-app-b", "sub-batch-b", "sub-db-b", "peer-atlas")
_KIND = {cid: kind for (cid, kind, *_geom) in b10._CONTAINER_GEOM}

CONTAINERS = tuple(
    ContainerSpec(id=cid, kind=_KIND[cid], region=_REGION[cid], parent=_PARENT[cid],
                  label_key=cid)
    for cid in _ORDER
)

# --------------------------------------------------------------------------- #
# Nodes: the hand-pinned NODE_META, placed by (lane, region, slot, container).
# --------------------------------------------------------------------------- #

#: node id -> (lane, region, slot, container)
_PLACE = {
    "igw": ("edge", "a", 0, "boundary-vpc"),
    "nat": ("edge", "a", 1, "boundary-vpc"),
    "vpce-s3": ("workers", "a", 0, "sub-pub-a"),
    "lambda": ("workers", "a", 0, "sub-app-a"),
    "ec2-syndi": ("workers", "a", 1, "sub-app-a"),
    "batch-a": ("workers", "a", 0, "sub-batch-a"),
    "vpce-ecr-api": ("workers", "a", 1, "sub-batch-a"),
    "rds-standby": ("data", "a", 0, "sub-db-a"),
    "vpce-ddb": ("workers", "b", 0, "sub-pub-b"),
    "strapi": ("workers", "b", 0, "sub-app-b"),
    "batch-b": ("workers", "b", 0, "sub-batch-b"),
    "vpce-ecr-dkr": ("workers", "b", 1, "sub-batch-b"),
    "rds-primary": ("data", "b", 0, "sub-db-b"),
    "pcx-atlas": ("on-premises", "", 0, "peer-atlas"),
    "atlas": ("on-premises", "", 1, "peer-atlas"),
}

NODES = tuple(
    NodeSpec(id=nid, role=b10.NODE_META[nid]["role"], lane=lane, region=region,
             slot=slot, container=container, overlay=b10.NODE_META[nid]["overlay"],
             scope=(b10.NODE_META[nid]["scope"]
                    or ("network" if container and container.startswith(("sub-", "boundary-vpc"))
                        else None)))
    for nid, (lane, region, slot, container) in _PLACE.items()
)

EDGES = tuple(
    EdgeSpec(id=e.id, source=e.source, target=e.target, marker=e.marker, dashed=e.dashed)
    for e in b10.EDGES
)


def _spec() -> DiagramSpec:
    return DiagramSpec(
        diagram_id="aws-sep-network-topology",
        diagram_name=BASENAME,
        axis="north-south",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=b10.FLOW,
        title=b10.TITLE,
        node_labels=tuple((nid, b10.NODE_META[nid]["caption"]) for nid in _PLACE),
        container_captions=tuple(b10.CONTAINER_CAPTIONS.items()),
    )


def _build(spec: DiagramSpec | None = None) -> str:
    spec = spec or _spec()
    placed = layout(spec, strict=False)
    for w in placed.layout_warnings:
        print(f"[layout WARNING] {w}")
    nodes: List[Node] = [
        Node(id=n.id, label=b10.NODE_META[n.id]["caption"],
             x=int(placed.nodes[n.id].x), y=int(placed.nodes[n.id].y),
             render=b10._renderer_for(n.id), overlay=n.overlay,
             scope=b10.NODE_META[n.id]["scope"])
        for n in spec.nodes if n.id in placed.nodes
    ]
    boundaries: List[Boundary] = []
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        boundaries.append(Boundary(
            id=c.id, label=b10.CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=b10._container_style(c.kind), kind=c.kind,
        ))
    edges: List[Edge] = [
        Edge(id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
             marker=pe.spec.marker, dashed=pe.spec.dashed,
             exit=pe.exit, entry=pe.entry,
             points=tuple((int(x), int(y)) for x, y in pe.points))
        for pe in placed.edges
    ]
    rights = [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [b.y + b.h for b in boundaries] + [n.y + ICON_SIZE for n in nodes]
    legend_lines = (list(legend_lines_for(boundaries)) + list(overlay_legend_lines(nodes))
                    + list(b10.LEGEND_EXTRA))
    return build_diagram(
        diagram_id="aws-sep-network-topology",
        diagram_name=BASENAME,
        title=b10.TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=b10.FLOW,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        legend_lines=legend_lines,
        page_w=int(max(rights)) + _PAGE_MARGIN,
        page_h=int(max(bottoms)) + _PAGE_MARGIN,
        membership=membership_of(placed),
    )


def main() -> int:
    out = ROOT / "repro" / "10-coordfree.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
