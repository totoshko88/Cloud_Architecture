#!/usr/bin/env python3
"""Generate the GCP golden example diagram on the shared layout standard.

GCP resolves icons to the **official Google Cloud 2025 packs** referenced by file
path (never the pre-2025 ``mxgraph.gcp2.*`` stencils, which the icon mapping and
``asset-packs.md`` keep only as a last-resort fallback). Each node is a single
flat ``image`` cell rendered by :func:`rule_engine.diagram_layout.image_icon`,
with the icon path taken from ``mappings/gcp-icons.yaml`` (Core Product first,
Product Category fallback). The golden example additionally uses the **Apigee**
product icon for ``api-gateway`` so it reads distinctly from ``load-balancer``
(Networking category). The layout geometry (icon size, label placement, lane
grid, container padding, edge routing) comes entirely from the shared builder, so
the GCP diagram matches the AWS reference and the OCI example exactly.

This replaces the earlier hand-authored GCP diagram, whose icons were 64px (vs the
78px standard) and whose flow-5 corridor ran too close to the VPC bottom border.

Usage::

    python scripts/build_gcp_example.py            # write the .drawio
    python scripts/build_gcp_example.py --stdout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import (  # noqa: E402
    Boundary,
    Edge,
    Node,
    build_diagram,
    image_icon,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "examples" / "gcp" / "01-gcp-vertex-pipeline.drawio"

TITLE = "gcp vertex-pipeline — acme-prod / us-central1 | 2026-09-22 | v1"


# Official GCP 2025 icon paths under the fetched asset root, per node. Sourced
# from mappings/gcp-icons.yaml (Core Product first, Product Category fallback);
# api-gateway uses the Apigee product icon (closest official product to an API
# gateway) so it is visually distinct from load-balancer (Networking category).
# Paths must stay file-path (never data: URIs) to pass the icon-resolved linter.
_GCP_CORE = "assets/vendor/gcp-core/Unique Icons"
_GCP_CAT = "assets/vendor/gcp-category/Category Icons"

# Same AWS-mirrored topology as OCI: hub (vertex-ai) adjacent to the data column;
# async messaging + workers stacked above/below the hub.
# (node id, icon path, x, y)
NODE_SPECS = [
    ("api-gateway", f"{_GCP_CORE}/Apigee/SVG/Apigee-512-color-rgb.svg", 120, 440),
    ("load-balancer", f"{_GCP_CAT}/Networking/SVG/Networking-512-color-rgb.svg", 360, 440),
    ("pubsub-events", f"{_GCP_CAT}/Integration Services/SVG/IntegrationServices-512-color.svg", 620, 200),
    ("secret-manager", f"{_GCP_CAT}/Security Identity/SVG/SecurityIdentity-512-color.svg", 620, 680),
    ("ingest-function", f"{_GCP_CAT}/Serverless Computing/SVG/ServerlessComputing-512-color.svg", 880, 200),
    ("vertex-ai", f"{_GCP_CORE}/Vertex AI/SVG/VertexAI-512-color.svg", 880, 440),
    ("training-gke", f"{_GCP_CORE}/GKE/SVG/GKE-512-color.svg", 880, 680),
    ("cloud-sql", f"{_GCP_CORE}/Cloud SQL/SVG/CloudSQL-512-color.svg", 1140, 360),
    ("model-storage", f"{_GCP_CORE}/Cloud Storage/SVG/Cloud_Storage-512-color.svg", 1140, 520),
]

# Node centers (icon 78): api(159,479) lb(399,479) pubsub(659,239)
# secret(659,719) ingest(919,239) vertex(919,479) train(919,719)
# sql(1179,399) store(1179,559). Mirrors the OCI routing exactly.
EDGES: List[Edge] = [
    Edge("e1", "api-gateway", "load-balancer", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    Edge("e2", "load-balancer", "vertex-ai", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 3: api-gateway up to the event topic. v1.6.0: exits the gateway's RIGHT
    # face (upper band, biased toward the upward run), steps into the gap column
    # at x=250, rises, then enters the topic's LEFT face. The pre-1.6.0 route
    # exited the TOP — an edge leaving straight out of the top of its own glyph,
    # which the directional contract forbids and which `edge-direction` only
    # started catching once it classified the contact FACE instead of testing the
    # half-plane (`exitX >= 0.5` rescued the top-centre point).
    Edge("e3", "api-gateway", "pubsub-events", "3", dashed=True,
         exit=(1.0, 0.25), entry=(0.0, 0.5), points=[(250, 460), (250, 239)]),
    Edge("e4", "pubsub-events", "ingest-function", "4", dashed=True,
         exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 5: ingest down to training, skipping the hub via the LEFT corridor.
    # v1.6.0: the lane turn is now an EXPLICIT waypoint. The route used to be a
    # bottom exit followed by one far waypoint, leaving draw.io to choose the
    # corner — and once the corner is specified rather than guessed, a
    # vertical-first turn drives the run straight through the hub icon. Pinning
    # the step-down lane at y=320 (clear of the ingest row's label band) and the
    # corridor at x=860 (left of the hub column) makes the path deterministic and
    # hub-free.
    # v1.6.0 (2nd pass): the corridor moved from x=860 to x=800. At 860 the 400px
    # descent ran 20px from vertex-ai's left border, which reads as a second rail
    # beside the hub column — the defect diagram-standards names outright. x=800
    # clears that border by 80px, leaves the free riser column at 840 for e6, and
    # crosses nothing extra: the two crossings this descent makes (e2's approach
    # into the hub's left, e9's lane out of its bottom) are its floor, since both
    # of those runs span the whole left gap.
    Edge("e5", "ingest-function", "training-gke", "5", exit=(0.25, 1.0), entry=(0.0, 0.5),
         points=[(800, 320), (800, 719)]),
    # 6: training up to vertex. v1.6.0: the pre-1.6.0 straight vertical exited
    # the TOP and entered the BOTTOM — both faces the directional contract
    # forbids, and both invisible to the pre-1.6.0 half-plane test. Re-routed as
    # the sanctioned back-edge/loop: exit the RIGHT face, rise in the free column
    # at x=1010 (clear of the e7/e8 risers at 1060/1090), run left in the lane at
    # y=420 (above vertex-ai, below the upper row's label band), and drop into
    # vertex-ai's TOP — so the arrow arrives from above instead of up through the
    # glyph.
    #
    # This riser does cross e7's and e8's stubs, and that is the floor for this
    # layout rather than a routing slip: vertex-ai is a four-edge hub whose only
    # free approach column lies inside its own fan-out. Every alternative was
    # measured — a riser right of e8 (1100..1130) meets e7's and e8's approach legs
    # into the 1140 data column; a left-side riser meets e5's descent and e9's
    # lane, both of which span the whole left gap; a bottom exit into the hub's
    # LEFT face trades the same two crossings for two others. Fixing it needs the
    # hub's neighbours moved, not its edges rerouted — a placement change, recorded
    # in docs/REVIEW.md rather than papered over here.
    Edge("e6", "training-gke", "vertex-ai", "6", exit=(1.0, 0.25), entry=(0.5, 0.0),
         points=[(1010, 699), (1010, 420), (919, 420)]),
    # 7: vertex (upper-right) to cloud-sql; riser x=1060 up to row y=399.
    Edge("e7", "vertex-ai", "cloud-sql", "7", exit=(1.0, 0.25), entry=(0.0, 0.5),
         points=[(1060, 459), (1060, 399)]),
    # 8: vertex (lower-right) to model-storage; riser x=1090 down to row y=559.
    Edge("e8", "vertex-ai", "model-storage", "8", exit=(1.0, 0.75), entry=(0.0, 0.5),
         points=[(1090, 499), (1090, 559)]),
    # 9: vertex down-left to secret-manager. v1.6.0: the pre-1.6.0 route exited
    # the hub's LEFT face, which the directional contract forbids (and which
    # `edge-direction` already flagged before the face fix). Now it exits the
    # BOTTOM — legal, and the shortest path to a target below-left — drops into
    # the lane at y=600 (past the hub's own label band at 548, above the lower
    # row at 680), runs left, and enters secret-manager's TOP.
    Edge("e9", "vertex-ai", "secret-manager", "9", exit=(0.5, 1.0), entry=(0.5, 0.0),
         points=[(919, 600), (659, 600)]),
]

FLOW_LINES = [
    "Flow",
    "1. api-gateway forwards request to load-balancer",
    "2. load-balancer routes inference to Vertex AI",
    "3. api-gateway publishes event to Pub/Sub (async)",
    "4. Pub/Sub delivers event to ingest-function (async)",
    "5. ingest-function submits training job to GKE",
    "6. GKE registers trained model with Vertex AI",
    "7. Vertex AI reads metadata from Cloud SQL",
    "8. Vertex AI stores artifacts in Cloud Storage",
    "9. Vertex AI fetches credentials from Secret Manager",
]


def build() -> str:
    boundaries = [
        Boundary("boundary-project", "project-acme-prod",
                 x=40, y=70, w=1360, h=790, stroke="#00A000"),
        Boundary("boundary-vpc", "vpc-prod",
                 x=580, y=150, w=420, h=670, stroke="#0062AD"),
    ]
    nodes: List[Node] = [
        Node(id=nid, label=nid, x=x, y=y, render=image_icon(icon_path))
        for (nid, icon_path, x, y) in NODE_SPECS
    ]
    return build_diagram(
        diagram_id="gcp-vertex-pipeline",
        diagram_name="gcp-vertex-pipeline",
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=EDGES,
        flow_lines=FLOW_LINES,
        legend_x=1460,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build_gcp_example")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    xml = build()
    if args.stdout:
        sys.stdout.write(xml)
        return 0
    Path(args.out).write_text(xml, encoding="utf-8")
    print(f"build_gcp_example: wrote {args.out} ({len(NODE_SPECS)} nodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
