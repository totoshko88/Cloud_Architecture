#!/usr/bin/env python3
"""WS10 variant of 08-network-crossaccount: peering drawn BOUNDARY → BOUNDARY.

Defect C15 (1.10.12 plan): the production 08 landscape attaches every VPC
peering to a proxy NODE inside the boundary (``lambda → atlas``,
``rds → cmtr-cmtm``, …) because the engine had no boundary-to-boundary edge
idiom. A VPC peering is a relationship between two NETWORKS, not between a
Lambda and a peer host, so the honest shape is an edge anchored on the two
container FACES — the ``se`` VPC boundary and the external peer boundary — with
NO RDS/Lambda proxy node in the peering path.

This variant imports the production 08 spec verbatim and swaps the four
per-node peering edges (e7–e10) for ONE boundary-to-boundary peering edge
``boundary-vpc-a → peer-ext`` (WS10). The public EKS endpoints (e11/e12, NAT
egress over the internet — NOT peering) stay node edges, and every in-VPC data
edge is unchanged, so the diagram still reads as a real network. The peering
edge exits the VPC boundary's face and enters the peer boundary's face under
the directional contract, exactly as a node edge does.

Run from the fixture root (``tests/fixtures/sep``) so ``assets/vendor`` paths
resolve cwd-relative::

    cd tests/fixtures/sep && ../../../.venv/bin/python scripts/build_08v2_boundary_peering.py
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_08_network_crossaccount as b08  # noqa: E402
from rule_engine.layout.model import EdgeSpec  # noqa: E402

OUT = HERE.parent / "repro" / "08v2-boundary-peering.drawio"


# The four per-node peerings (e7–e10) collapse into ONE boundary-to-boundary
# peering edge: the ``se`` VPC boundary peers with the external peer boundary.
# Keep the in-VPC edges (e1–e6) and the public EKS endpoints (e11/e12) as they
# are. The peer and proxy nodes carry a ``supporting`` overlay so the drawing
# declares why they no longer sit on the peering path (node-connectivity's
# sanctioned exemption) — the peering is a network relationship, drawn between
# the two boundaries, not between a Lambda/RDS and a peer host.
_KEEP = {"e1", "e2", "e3", "e4", "e5", "e6", "e11", "e12"}
_PEERING = EdgeSpec(
    id="e7",
    source="boundary-vpc-a",   # the ``se`` VPC network boundary (container id)
    target="peer-ext",         # the external peer account boundary (container id)
    marker="7",
    peering=True,
)

b08.EDGES = tuple(e for e in b08.EDGES if e.id in _KEEP) + (_PEERING,)

# Mark the peer/proxy nodes no longer on a peering path as ``supporting`` so the
# node-connectivity rule is satisfied by declaration (double-encoded + Legend),
# the sanctioned alternative to a fabricated edge.
_SUPPORTING = {"atlas", "cmtr-sre", "cmtr-cmtm", "cicd"}
b08.NODES = tuple(
    dataclasses.replace(n, overlay="supporting") if n.id in _SUPPORTING else n
    for n in b08.NODES
)

# The Flow legend: replace the four peering steps with the one boundary peering,
# and document the ``supporting`` overlay term (overlay-legend-coverage).
b08.FLOW = (
    "Flow",
    "1. Route 53 syndicate.education resolves to CloudFront (acct 323549576358)",
    "2. CloudFront / clients ingress to the se VPC via the Internet Gateway",
    "3. IGW fronts the public path into the VPC-attached Lambda tier",
    "4. S3 + DynamoDB reached via gateway VPC endpoints (no NAT hop)",
    "5. ECR dkr + api reached via interface VPC endpoints",
    "6. Lambda / Strapi persist content to RDS sep-strapi-pg (VPC-scoped)",
    "7. VPC PEERING: the se VPC peers with the external peer accounts "
    "(Atlas pcx-0e257b23d337fda0b, EPM-CMTR pcx-0ba890357ddac7479 / "
    "pcx-0bd56ed835959cbbc, CICD pcx-0754f6dee2f5bf2fd) — boundary to boundary",
    "11. PUBLIC EKS endpoint to control-plane shared (088595288622) via NAT — not peering",
    "12. PUBLIC EKS endpoint to student development-dev (183631338639) via NAT — not peering",
)
b08.LEGEND_EXTRA = b08.LEGEND_EXTRA + (
    "supporting = peer target reached over VPC peering (drawn as a boundary-to-"
    "boundary edge, not a per-host edge)",
)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(b08._build(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
