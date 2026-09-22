#!/usr/bin/env python3
"""Generate the OCI golden example diagram with real, resolved OCI icons.

OCI ships no built-in draw.io ``mxgraph.oci.*`` stencil library, so the neutral
resource types cannot be resolved to an editable built-in stencil the way AWS
(``mxgraph.aws4.*``) can. Instead the official OCI draw.io pack ships a
``<mxlibrary>`` of shapes; ``scripts/fetch_assets.py`` decodes that library into
``assets/vendor/oci-stencils/stencils.json`` — one self-contained
``<mxGraphModel>`` group per shape whose cells carry inline ``shape=stencil(...)``
geometry that renders **without** the library installed.

This generator uses the shared, provider-neutral layout builder
(:mod:`rule_engine.diagram_layout`) so the OCI diagram matches the AWS reference
exactly on icon size, label placement, lane grid, container padding, and edge
routing. The only OCI-specific part is the icon renderer
(:class:`~rule_engine.diagram_layout.OciStencilIcon`), which embeds each stencil
group with its baked-in caption stripped and the icon scaled to the standard
78x78 square. (Headless draw.io does not fetch ``shape=image`` data-URIs, so an
image-node approach renders empty — inline stencil geometry is what actually
draws.)

Glyph slugs come only from the extracted pack (data), never hard-coded shape ids
(asset-packs.md anti-pattern). Where a service has no dedicated OCI stencil
(Generative AI), the closest official OCI category glyph (``analytics-and-ai``)
is used and the choice is recorded in NODES.

Usage::

    python scripts/build_oci_example.py            # write the .drawio
    python scripts/build_oci_example.py --stdout   # print to stdout instead
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Make the package importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import (  # noqa: E402
    Boundary,
    Edge,
    Node,
    OciStencilIcon,
    build_diagram,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STENCILS = REPO_ROOT / "assets" / "vendor" / "oci-stencils" / "stencils.json"
OUT = REPO_ROOT / "examples" / "oci" / "01-oci-genai-stack.drawio"

TITLE = "oci genai-stack — acme-prod / us-ashburn-1 | 2026-09-22 | v1"
OCI_BRAND = "#F80000"

# Node placements on the standard grid (lane order actors→edge→router→async→
# workers→platform core→data, left→right). Each maps a neutral service to its
# OCI stencil slug. `note` documents any non-exact glyph.
# Topology mirrors the AWS reference: a central hub (generative-ai) adjacent to
# the data column, with async messaging + workers stacked ABOVE/BELOW the hub so
# nothing sits between the hub and the data stores. Columns step by 220, rows by
# 160/220, matching the shared grid.
#   col0 x=120  api-function        (edge lane, middle row)
#   col1 x=360  load-balancer       (router lane, middle row)
#   col2 x=620  streaming-events    (async, top) / vault-secrets (core, bottom)
#   col3 x=880  generative-ai (hub, middle) / ingest-function (top) / training-oke (bottom)
#   col4 x=1140 autonomous-db (upper) / model-storage (lower)  -- data column
NODE_SPECS: List[Dict[str, Any]] = [
    {"id": "api-function", "slug": "functions", "x": 120, "y": 440},
    {"id": "load-balancer", "slug": "load-balancer", "x": 360, "y": 440},
    {"id": "streaming-events", "slug": "streaming", "x": 620, "y": 200},
    {"id": "vault-secrets", "slug": "vault", "x": 620, "y": 680},
    {"id": "ingest-function", "slug": "functions", "x": 880, "y": 200},
    {"id": "generative-ai", "slug": "analytics-and-ai", "x": 880, "y": 440,
     "note": "no dedicated Generative AI stencil in pack; using OCI Analytics and AI category glyph"},
    {"id": "training-oke", "slug": "container-engine-for-kubernetes", "x": 880, "y": 680},
    {"id": "autonomous-db", "slug": "autonomous-db", "x": 1140, "y": 360},
    {"id": "model-storage", "slug": "object-storage", "x": 1140, "y": 520},
]

# Edges: numeric markers 1..9. Parallel runs get explicit waypoint corridors so
# no two edges share a lane and none crosses an unrelated icon.
# Node centers (icon 78): api(159,479) lb(399,479) stream(659,239)
# vault(659,719) ingest(919,239) gen(919,479) train(919,719) adb(1179,399)
# store(1179,559). The x=880 column stacks ingest/gen/train, so edges among
# them use side corridors (left x=855, right x=985) to avoid passing through
# the middle icon.
EDGES: List[Edge] = [
    # 1: api -> load-balancer (middle row, straight).
    Edge("e1", "api-function", "load-balancer", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 2: load-balancer -> generative-ai (middle row, straight; nothing between).
    Edge("e2", "load-balancer", "generative-ai", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 3: api-function up to streaming (async); riser at x=159 up to y=239.
    Edge("e3", "api-function", "streaming-events", "3", dashed=True,
         exit=(0.5, 0.0), entry=(0.0, 0.5), points=[(159, 239)]),
    # 4: streaming -> ingest-function (top row, straight).
    Edge("e4", "streaming-events", "ingest-function", "4", dashed=True,
         exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 5: ingest down to training, skipping generative (middle) via LEFT corridor
    # x=855: exit ingest bottom-left, drop to y=719, into training left.
    Edge("e5", "ingest-function", "training-oke", "5", exit=(0.25, 1.0), entry=(0.0, 0.5),
         points=[(855, 719)]),
    # 6: training up to generative bottom (adjacent rows, straight vertical).
    Edge("e6", "training-oke", "generative-ai", "6", exit=(0.5, 0.0), entry=(0.5, 1.0)),
    # 7: generative-ai (upper-right) to autonomous-db; riser x=1060 up to y=399.
    Edge("e7", "generative-ai", "autonomous-db", "7", exit=(1.0, 0.25), entry=(0.0, 0.5),
         points=[(1060, 459), (1060, 399)]),
    # 8: generative-ai (lower-right) to model-storage; riser x=1090 down to y=559.
    Edge("e8", "generative-ai", "model-storage", "8", exit=(1.0, 0.75), entry=(0.0, 0.5),
         points=[(1090, 499), (1090, 559)]),
    # 9: generative-ai left to vault-secrets — single L-bend. Exit hub left at
    # y=498 (below the load-balancer->hub edge at y=479), one corner at (659,498),
    # then straight down into vault top.
    Edge("e9", "generative-ai", "vault-secrets", "9", exit=(0.0, 0.75), entry=(0.5, 0.0),
         points=[(659, 498)]),
]

FLOW_LINES = [
    "Flow",
    "1. api-function forwards request to load-balancer",
    "2. load-balancer routes inference to Generative AI",
    "3. api-function publishes event to Streaming (async)",
    "4. Streaming delivers event to ingest-function (async)",
    "5. ingest-function submits training job to OKE",
    "6. OKE registers trained model with Generative AI",
    "7. Generative AI reads metadata from Autonomous DB",
    "8. Generative AI stores artifacts in Object Storage",
    "9. Generative AI fetches credentials from Vault",
]


def build(stencils: Dict[str, Any]) -> str:
    boundaries = [
        Boundary("boundary-compartment", "compartment-acme-prod",
                 x=40, y=70, w=1360, h=790, stroke="#00A000"),
        # Network boundary encloses streaming/ingest/generative/training/vault
        # (x 620..958, y 200..758) with >=1 grid-step padding on every side.
        Boundary("boundary-vcn", "vcn-prod",
                 x=580, y=150, w=420, h=670, stroke="#0062AD"),
    ]
    nodes: List[Node] = []
    for spec in NODE_SPECS:
        renderer = OciStencilIcon(stencils, spec["slug"], brand_hex=OCI_BRAND)
        nodes.append(Node(id=spec["id"], label=spec["id"], x=spec["x"], y=spec["y"], render=renderer))

    return build_diagram(
        diagram_id="oci-genai-stack",
        diagram_name="oci-genai-stack",
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=EDGES,
        flow_lines=FLOW_LINES,
        legend_x=1460,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build_oci_example")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--stencils", default=str(STENCILS))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    stencils_path = Path(args.stencils)
    if not stencils_path.is_file():
        print(
            f"build_oci_example: error: extracted stencils not found at "
            f"{stencils_path}. Run: python scripts/fetch_assets.py --only oci",
            file=sys.stderr,
        )
        return 2
    stencils = json.loads(stencils_path.read_text(encoding="utf-8"))

    try:
        xml = build(stencils)
    except KeyError as exc:
        print(f"build_oci_example: error: {exc}", file=sys.stderr)
        return 2

    if args.stdout:
        sys.stdout.write(xml)
        return 0
    Path(args.out).write_text(xml, encoding="utf-8")
    print(f"build_oci_example: wrote {args.out} ({len(NODE_SPECS)} nodes with OCI glyphs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
