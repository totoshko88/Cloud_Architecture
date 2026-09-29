#!/usr/bin/env python3
"""Generate the **cross-cloud composition** golden example (D1, release 1.7.0).

Why this example exists
-----------------------
Decision **D1** makes draw.io the *only* publishable diagram source: a ``.puml``
/ ``.mmd`` file is a ``source-format`` ERROR at lint. The cross-cloud composition
that used to ship as ``examples/cross-cloud/cross-cloud-composition.puml`` is
re-authored here as a full ``.drawio`` triple
(``01-cross-cloud-composition.drawio`` + ``.drawio.png`` + ``.diagram.md``),
built through the shared layout engine like every other example rather than
hand-placed.

It is a **cross-cloud C4 container diagram** (``diagram-standards.md`` →
*Multi-cloud Composition*): each provider is named and rendered with its
profile's icons and brand-colored Boundary / Network-Boundary containers, the
node count stays at the 12-node cap, and every cross-provider edge is labeled
with the data flow it carries.

Architecture (unchanged from the retired PlantUML source): the edge +
authentication tier lives on **AWS**, the retrieval-augmented-generation tier on
**Azure**, and the training + artifact-storage tier on **Google Cloud**. Six
service nodes across three provider stacks, connected by six labeled edges that
close a loop AWS → Azure → GCP → AWS.

Icons resolve through ``mappings/<provider>-icons.yaml`` — AWS official SVG
file paths (migrated in 1.10.2), Azure ``img/lib/azure2/*`` image shapes, and GCP
official 2025 file-path SVGs — never a hand-written ``shape=`` id or ``fillColor``.
Geometry (78x78 icons, grid step 10, container padding, right-margin Flow/Legend)
comes entirely from ``rule_engine.diagram_layout``.

Usage::

    python scripts/build_cross_cloud_example.py            # write the .drawio
    python scripts/build_cross_cloud_example.py --stdout
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
    builtin_icon,
    image_icon,
    STANDARD_LEGEND_LINES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "examples" / "cross-cloud" / "01-cross-cloud-composition.drawio"

TITLE = "multicloud agent-platform — acme-multicloud / multi-region | 2026-09-22 | v1"

# ---------------------------------------------------------------------------
# Icon styles — resolved via mappings/<provider>-icons.yaml so each node
# carries the correct service-family style (never a hand-written id/fillColor).
#
# Migration 1.10.2: AWS now uses official SVG file paths (like Azure/GCP),
# not mxgraph.aws4 stencils. All providers now use the same image= approach.
# ---------------------------------------------------------------------------
from rule_engine.icon_resolver import resolve_icon, resolve_container  # noqa: E402

# AWS - resolve via mappings/aws-icons.yaml (now official SVG file paths)
_AWS_CDN = resolve_icon("cdn", "aws")["style_string"]
_AWS_LAMBDA = resolve_icon("serverless_fn", "aws")["style_string"]

# Azure azure2 file-path image shapes (built into the draw.io app, per
# mappings/azure-icons.yaml — img/lib/azure2/<category>/<Name>.svg).
_AZ_OPENAI = "img/lib/azure2/ai_machine_learning/Azure_OpenAI.svg"
_AZ_SERVICEBUS = "img/lib/azure2/general/Service_Bus.svg"
# GCP official 2025 file-path SVGs (Core Product first, Category fallback).
_GCP_VERTEX = (
    "assets/vendor/gcp-core/Unique Icons/Vertex AI/SVG/VertexAI-512-color.svg"
)
_GCP_STORAGE = (
    "assets/vendor/gcp-core/Unique Icons/Cloud Storage/SVG/Cloud_Storage-512-color.svg"
)

# Azure image shapes are declared in mappings/azure-icons.yaml as
# ``image=img/lib/azure2/...`` (built into the draw.io app, verified against
# azure2-shapes.json). File path, never a data: URI.
_AZ_STYLE = (
    "image;aspect=fixed;html=1;points=[];align=center;"
    "verticalLabelPosition=bottom;verticalAlign=top;fontSize=12;image="
)


def _az_icon(path: str) -> str:
    return _AZ_STYLE + path


# ---------------------------------------------------------------------------
# Geometry — three provider stacks read left -> right (flow class).
# Each stack: Boundary (Account/Subscription/Project) ⊃ Network Boundary
# (VPC/VNet/VPC) containing two service nodes stacked top/bottom.
# Node columns: AWS x=200, Azure x=680, GCP x=1160. Rows: top y=320, bottom 480.
# ---------------------------------------------------------------------------
ROW_TOP = 320
ROW_BOT = 480
X_AWS = 200
X_AZ = 680
X_GCP = 1160

# (node id, label, renderer-kind, style/path, x, y)
NODE_SPECS = [
    ("edge-gateway", "edge-gateway", "resolved", _AWS_CDN, X_AWS, ROW_TOP),
    ("auth-lambda", "auth-lambda", "resolved", _AWS_LAMBDA, X_AWS, ROW_BOT),
    ("openai-service", "openai-service", "image", _AZ_OPENAI, X_AZ, ROW_TOP),
    ("service-bus", "service-bus", "image", _AZ_SERVICEBUS, X_AZ, ROW_BOT),
    ("vertex-ai", "vertex-ai", "image", _GCP_VERTEX, X_GCP, ROW_TOP),
    ("cloud-storage", "cloud-storage", "image", _GCP_STORAGE, X_GCP, ROW_BOT),
]

# Node centres (icon 78 -> +39):
#   edge-gateway(239,359) auth-lambda(239,519)
#   openai(719,359)       service-bus(719,519)
#   vertex-ai(1199,359)   cloud-storage(1199,519)
EDGES: List[Edge] = [
    # 1: within AWS — edge gateway validates via the auth lambda (straight drop).
    Edge("e1", "edge-gateway", "auth-lambda", "1",
         exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # 2: AWS -> Azure — the authenticated prompt crosses to Azure OpenAI. Exit
    # the lambda's right, rise in the gap corridor between the AWS Account
    # (right 338) and the Azure Subscription (left 620), enter OpenAI's left.
    Edge("e2", "auth-lambda", "openai-service", "2",
         exit=(1.0, 0.5), entry=(0.0, 0.5), points=[(490, 519), (490, 359)]),
    # 3: within Azure — OpenAI publishes a completion event (async, straight drop).
    Edge("e3", "openai-service", "service-bus", "3", dashed=True,
         exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # 4: Azure -> GCP — the event streams to Vertex AI. Mirror of e2: rise in the
    # gap corridor between the Azure Subscription (right 818) and the GCP Project
    # (left 1100), enter Vertex AI's left.
    Edge("e4", "service-bus", "vertex-ai", "4", dashed=True,
         exit=(1.0, 0.5), entry=(0.0, 0.5), points=[(970, 519), (970, 359)]),
    # 5: within GCP — Vertex AI persists model artifacts to Cloud Storage (drop).
    Edge("e5", "vertex-ai", "cloud-storage", "5",
         exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # 6: GCP -> AWS — the return loop. Cloud Storage returns a signed artifact URL
    # to the AWS edge gateway. A long back-edge: exit the bottom, run in a
    # dedicated low corridor (y=700, below every container bottom at 648), up the
    # far-left riser (x=100, left of the AWS Account at 140), enter the gateway's
    # left face.
    Edge("e6", "cloud-storage", "edge-gateway", "6",
         exit=(0.5, 1.0), entry=(0.0, 0.5),
         points=[(1199, 700), (100, 700), (100, 359)]),
]

FLOW_LINES = [
    "Flow",
    "1. edge-gateway validates the caller via auth-lambda (AWS)",
    "2. auth-lambda forwards the RAG prompt to Azure OpenAI (AWS to Azure)",
    "3. openai-service publishes a completion event to Service Bus (async)",
    "4. service-bus streams embeddings to Vertex AI (Azure to GCP)",
    "5. vertex-ai persists model artifacts to Cloud Storage (GCP)",
    "6. cloud-storage returns a signed artifact URL to edge-gateway (GCP to AWS)",
]

# Extend the standard Legend with the per-provider brand anchors (the retired
# PlantUML legend carried this line too).
LEGEND_LINES = list(STANDARD_LEGEND_LINES) + [
    "AWS = brand #232F3E ; Azure = brand #0078D4 ; GCP = brand #4285F4",
]

# ---------------------------------------------------------------------------
# Per-provider Boundary + Network-Boundary container styles, from the mappings.
# AWS ships a dedicated group stencil; Azure and GCP render as dashed rectangles
# in the profile brand color (they have no built-in group shape).
# ---------------------------------------------------------------------------
STYLE_AWS_ACCOUNT = resolve_container("boundary", "aws")["style_string"]
STYLE_AWS_VPC = resolve_container("network_boundary", "aws")["style_string"]
# Every provider's boxes come from its own mapping (REVIEW.md D19), so the
# composition shows each cloud in its own container convention.
STYLE_AZ_SUB = resolve_container("boundary", "azure")["style_string"]
STYLE_AZ_VNET = resolve_container("network_boundary", "azure")["style_string"]
STYLE_GCP_PROJECT = resolve_container("boundary", "gcp")["style_string"]
STYLE_GCP_VPC = resolve_container("network_boundary", "gcp")["style_string"]


def _render(kind: str, style_or_path: str):
    if kind == "builtin":
        return builtin_icon(style_or_path)
    if kind == "image":
        return image_icon(style_or_path)
    if kind == "resolved":
        # Already a full style string from icon_resolver
        return builtin_icon(style_or_path)
    raise ValueError(f"unknown renderer kind: {kind}")


def build() -> str:
    boundaries = [
        # AWS stack: Account ⊃ VPC. Top padding reserves the caption strip (30)
        # plus one grid-step of clearance (30) = 60; other sides bare 30.
        Boundary("boundary-aws-account", "AWS Account 111111111111",
                 x=140, y=200, w=198, h=448, style=STYLE_AWS_ACCOUNT),
        Boundary("boundary-aws-vpc", "AWS VPC vpc-edge",
                 x=170, y=260, w=138, h=358, style=STYLE_AWS_VPC),
        # Azure stack: Subscription ⊃ VNet.
        Boundary("boundary-azure-sub", "Azure Subscription sub-acme",
                 x=620, y=200, w=198, h=448, style=STYLE_AZ_SUB),
        Boundary("boundary-azure-vnet", "Azure VNet vnet-core",
                 x=650, y=260, w=138, h=358, style=STYLE_AZ_VNET),
        # GCP stack: Project ⊃ VPC.
        Boundary("boundary-gcp-project", "GCP Project acme-data",
                 x=1100, y=200, w=198, h=448, style=STYLE_GCP_PROJECT),
        Boundary("boundary-gcp-vpc", "GCP VPC vpc-data",
                 x=1130, y=260, w=138, h=358, style=STYLE_GCP_VPC),
    ]
    nodes: List[Node] = [
        Node(id=nid, label=label, x=x, y=y, render=_render(kind, s))
        for (nid, label, kind, s, x, y) in NODE_SPECS
    ]
    return build_diagram(
        diagram_id="cross-cloud-composition",
        diagram_name="cross-cloud-composition",
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=EDGES,
        flow_lines=FLOW_LINES,
        legend_lines=LEGEND_LINES,
        # Right margin, just past the GCP Project boundary (right edge 1298) by
        # one grid step. The Flow/Legend blocks are pinned NARROW (legend_w) so
        # they wrap taller instead of running wide — keeping the export canvas
        # within the flow raster budget (<= 1600px). See diagram-standards →
        # "Flow and Legend share one width … a narrow pin is the sanctioned
        # exception".
        legend_x=1310,
        legend_w=270,
        page_w=1620,
        page_h=860,
    )


def _first_diff_line(expected: str, actual: str) -> str:
    """Return a human-readable description of the first differing line."""
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()
    for i, (e, a) in enumerate(zip(exp_lines, act_lines), start=1):
        if e != a:
            return f"line {i}: committed {e!r} != regenerated {a!r}"
    if len(exp_lines) != len(act_lines):
        n = min(len(exp_lines), len(act_lines)) + 1
        longer = "regenerated" if len(act_lines) > len(exp_lines) else "committed"
        return f"line {n}: {longer} has extra content ({len(exp_lines)} vs {len(act_lines)} lines)"
    return "trailing bytes differ (no newline / whitespace at EOF)"


def _check_one(path: Path, regenerated: str, prog: str) -> bool:
    if not path.exists():
        print(f"{prog}: STALE: regenerate {path} — committed file is missing",
              file=sys.stderr)
        return False
    committed = path.read_text(encoding="utf-8")
    if committed == regenerated:
        return True
    print(f"{prog}: STALE: regenerate {path} — {_first_diff_line(committed, regenerated)}",
          file=sys.stderr)
    return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build_cross_cloud_example")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare regenerated output byte-for-byte with the committed file "
             "without writing; exit non-zero if it is stale or missing",
    )
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    xml = build()
    if args.stdout:
        sys.stdout.write(xml)
        return 0
    if args.check:
        if _check_one(Path(args.out), xml, "build_cross_cloud_example"):
            print(f"build_cross_cloud_example: OK — {args.out} is up to date")
            return 0
        return 1
    Path(args.out).write_text(xml, encoding="utf-8")
    print(f"build_cross_cloud_example: wrote {args.out} ({len(NODE_SPECS)} nodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
