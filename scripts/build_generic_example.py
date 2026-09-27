#!/usr/bin/env python3
"""Generate the **generic** (vendor-neutral) golden example (D1, release 1.7.0).

Why this example exists
-----------------------
Decision **D1** makes draw.io the *only* publishable diagram source: a ``.puml``
/ ``.mmd`` file is a ``source-format`` ERROR at lint. The vendor-neutral
reference architecture that used to ship as
``examples/generic/generic-reference-architecture.puml`` is re-authored here as a
full ``.drawio`` triple (``01-generic-reference-architecture.drawio`` +
``.drawio.png`` + ``.diagram.md``), built through the shared layout engine like
every other example rather than hand-placed.

It is a **flow-class** diagram (``diagram_class: flow``) of the vendor-neutral
``generic`` Provider Profile: grayscale shapes only — white fill (``#FFFFFF``),
black stroke (``#000000``) — and **no** vendor icons, exactly as
``mappings/generic-icons.yaml`` prescribes. Node styles are taken verbatim from
that mapping's ``resources:`` block (never a hand-written ``fillColor``); the
Environment (stack Boundary) renders as a dashed **green** rectangle and the
Network Boundary as a dashed **blue** rectangle, per the generic profile in
``provider-profiles.md`` and the diagram-standards Legend convention.

Architecture (unchanged from the retired PlantUML source): an external end user
reaches a managed Kubernetes cluster that fronts the API and enqueues work on a
message queue. A serverless function consumes queued messages asynchronously,
calls the LLM platform for inference, and persists state to the managed SQL
database, object store, and secrets store. Seven cloud service nodes inside the
two boundaries plus one external actor = eight nodes, within the 12-node cap.

Geometry (78x78 icons, grid step 10, container padding, right-margin
Flow/Legend) comes entirely from ``rule_engine.diagram_layout``.

Usage::

    python scripts/build_generic_example.py            # write the .drawio
    python scripts/build_generic_example.py --stdout
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
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "examples" / "generic" / "01-generic-reference-architecture.drawio"

TITLE = "generic reference-architecture — env-prod / region-1 | 2026-09-22 | v1"

# ---------------------------------------------------------------------------
# Node styles — grayscale only, taken verbatim from mappings/generic-icons.yaml
# (resources: block). The generic profile uses NO vendor icons: every node is a
# base draw.io shape with a white/black-to-gray fill and stroke. Never a
# resIcon/vendor grIcon, never a brand color. builtin_icon() just prepends the
# style string and appends the shared label suffix, so a full grayscale style
# string is exactly what it needs.
# ---------------------------------------------------------------------------
_S_K8S = (  # managed_k8s
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#333333"
)
_S_QUEUE = (  # message_queue
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#333333"
)
_S_FUNCTION = (  # serverless_fn
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000"
)
_S_LLM = (  # llm_platform
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000"
)
_S_SQL = (  # managed_sql
    "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "boundedLbl=1;backgroundOutline=1;size=15"
)
_S_OBJECT = (  # object_store
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000"
)
_S_SECRETS = (  # secrets_store
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;dashed=0"
)
# The external actor is a plain grayscale box — outside the cloud boundaries
# (only cloud resources live inside the Environment / Network). The generic
# profile ships no vendor icons and no dedicated actor stencil, so a declared
# base rectangle (leading token ``rounded`` — the same generic base shape as the
# object/secrets nodes) keeps the actor fully resolvable by rule-engine-verify-icon
# while staying grayscale (white fill / black stroke). A vendor ``shape=umlActor``
# is NOT a declared generic shape and would report unresolved.
_S_ACTOR = (
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000"
)

# ---------------------------------------------------------------------------
# Geometry — left -> right flow layout (flow class).
# Lane order: actors -> edge -> async messaging -> workers -> platform core /
# data. The end user (actor) sits OUTSIDE the boundaries; every other node is a
# cloud resource inside the Network Boundary.
#
#   EndUser(40,500)  K8s(320,500)  Queue(560,340)  Function(780,500)
#   data column x=1040: LLM(1040,180) SQL(1040,400) ObjectStore(1040,620)
#                       Secrets(1040,840)
# ---------------------------------------------------------------------------
X_ACTOR = 40
X_K8S = 320
X_QUEUE = 560
X_FUNC = 780
X_DATA = 1040

# (node id, label, style, x, y)
NODE_SPECS = [
    ("end-user", "End_User", _S_ACTOR, X_ACTOR, 500),
    ("api-cluster", "api-cluster", _S_K8S, X_K8S, 500),
    ("task-queue", "task-queue", _S_QUEUE, X_QUEUE, 340),
    ("tool-invoker", "tool-invoker", _S_FUNCTION, X_FUNC, 500),
    ("inference", "inference", _S_LLM, X_DATA, 180),
    ("state-db", "state-db", _S_SQL, X_DATA, 400),
    ("artifact-store", "artifact-store", _S_OBJECT, X_DATA, 620),
    ("app-secrets", "app-secrets", _S_SECRETS, X_DATA, 840),
]

# Node centres (icon 78 -> +39):
#   end-user(79,539)     api-cluster(359,539)  task-queue(599,379)
#   tool-invoker(819,539)
#   inference(1079,219)  state-db(1079,439)    artifact-store(1079,659)
#   app-secrets(1079,879)
EDGES: List[Edge] = [
    # 1: external end user submits the request to the managed Kubernetes cluster
    # (ingress crossing the Environment + Network boundaries — expected for an
    # external actor). Straight left->right.
    Edge("e1", "end-user", "api-cluster", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 2: the cluster enqueues each task onto the message queue. Exit the
    # cluster's right (upper band, biased to the upward target), rise in the gap
    # corridor at x=490, enter the queue's left.
    Edge("e2", "api-cluster", "task-queue", "2",
         exit=(1.0, 0.25), entry=(0.0, 0.5), points=[(490, 500), (490, 379)]),
    # 3: the queue delivers messages asynchronously (dashed) to the function.
    # Exit the queue's right, drop in the gap corridor at x=720 (past the queue's
    # own label band), enter the function's left.
    Edge("e3", "task-queue", "tool-invoker", "3", dashed=True,
         exit=(1.0, 0.5), entry=(0.0, 0.5), points=[(720, 379), (720, 539)]),
    # 4: the function invokes the LLM platform for inference. Right face, upper
    # band; rise in the gap corridor at x=970, enter the platform's left.
    Edge("e4", "tool-invoker", "inference", "4",
         exit=(1.0, 0.25), entry=(0.0, 0.5), points=[(970, 480), (970, 219)]),
    # 5: the function persists state to the managed SQL database. Right face,
    # centred (straight run to the same row band).
    Edge("e5", "tool-invoker", "state-db", "5",
         exit=(1.0, 0.5), entry=(0.0, 0.5), points=[(940, 539), (940, 439)]),
    # 6: the function writes generated output to the object store. Right face,
    # lower band; drop in the gap corridor at x=970, enter the store's left.
    Edge("e6", "tool-invoker", "artifact-store", "6",
         exit=(1.0, 0.75), entry=(0.0, 0.5), points=[(970, 600), (970, 659)]),
    # 7: the function reads credentials from the secrets store. The fourth
    # fan-out branch spills onto the BOTTOM face (keeps the right face at <=3
    # exits, per exit-thirds): drop in the lane at y=780 (past the function's own
    # label band at 548, above the lower data row at 840), run right, enter the
    # secrets store's left.
    Edge("e7", "tool-invoker", "app-secrets", "7",
         exit=(0.5, 1.0), entry=(0.0, 0.5), points=[(819, 780), (1010, 780), (1010, 879)]),
]

FLOW_LINES = [
    "Flow",
    "1. End_User submits the request to api-cluster (HTTPS)",
    "2. api-cluster enqueues the task onto task-queue",
    "3. task-queue delivers the message to tool-invoker (async)",
    "4. tool-invoker invokes inference on the LLM platform",
    "5. tool-invoker persists state to state-db",
    "6. tool-invoker writes the artifact to artifact-store",
    "7. tool-invoker reads credentials from app-secrets",
]

# ---------------------------------------------------------------------------
# Boundaries. The generic profile draws the Environment (stack Boundary) as a
# dashed GREEN rectangle and the Network Boundary as a dashed BLUE rectangle
# (provider-profiles.md generic row / diagram-standards Legend convention). The
# shared Boundary default strokes are exactly those two colors, so no vendor
# color is introduced.
#
#   nodes span: left K8s x=320 ; right data icons right edge 1118 ;
#   top inference y=180 ; bottom app-secrets footprint 840+78+30(label)=948.
#   Network pads 30 each side, top caption strip 30+30=60.
#     left 320-30=290 ; top 180-60=120 ; right 1118+30=1148 ;
#     bottom 948+30=978  -> x=290 y=120 w=858 h=858
#   Environment wraps Network with the same padding (top 60):
#     x=260 y=60 w=918 h=948
# The external actor (end-user, right edge 118) sits left of the Environment
# (left 260), so it is OUTSIDE both boundaries as required.
# ---------------------------------------------------------------------------
STACK_STROKE = "#00A000"   # dashed green Environment boundary
NETWORK_STROKE = "#0062AD"  # dashed blue Network boundary


def build() -> str:
    boundaries = [
        Boundary("boundary-environment", "Environment env-prod",
                 x=260, y=60, w=918, h=948, stroke=STACK_STROKE),
        Boundary("boundary-network", "Network region-1",
                 x=290, y=120, w=858, h=858, stroke=NETWORK_STROKE),
    ]
    nodes: List[Node] = [
        Node(id=nid, label=label, x=x, y=y, render=builtin_icon(style))
        for (nid, label, style, x, y) in NODE_SPECS
    ]
    return build_diagram(
        diagram_id="generic-reference-architecture",
        diagram_name="generic-reference-architecture",
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=EDGES,
        flow_lines=FLOW_LINES,
        # Right margin, one grid step past the Environment boundary right edge
        # (1178). Pinned narrow (legend_w) so the Flow/Legend block wraps taller
        # instead of running wide, keeping the export canvas within the flow
        # raster budget (<= 1600px). Block right edge = 1190 + 300 = 1490, so
        # canvas width 1490 + 2*8 = 1506 <= 1600.
        legend_x=1190,
        legend_w=300,
        page_w=1560,
        page_h=1080,
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
    parser = argparse.ArgumentParser(prog="build_generic_example")
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
        if _check_one(Path(args.out), xml, "build_generic_example"):
            print(f"build_generic_example: OK — {args.out} is up to date")
            return 0
        return 1
    Path(args.out).write_text(xml, encoding="utf-8")
    print(f"build_generic_example: wrote {args.out} ({len(NODE_SPECS)} nodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
