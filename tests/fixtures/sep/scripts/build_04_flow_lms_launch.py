#!/usr/bin/env python3
"""Build the 04-flow-lms-launch diagram triple (.drawio) via the shared builder.

SEP runtime data-flow: LMS / LTI 1.0/1.1 launch and run management.
- diagram_class: flow, diagram_type: data-flow, provider profile: aws.
- Left-to-right along the lane order.
- AWS Account boundary (870325637521 / eu-central-1) wraps ONLY the cloud nodes:
  ui-api, lti-adapter, management-api-handler.
- Student-in-LMS, Keycloak SSO, MongoDB Atlas are EXTERNAL (non-AWS) and are
  drawn OUTSIDE the boundary as neutral grayscale labelled boxes (no faked AWS
  icon — icon fidelity).
- AWS nodes resolve their icon through mappings/aws-icons.yaml (API Gateway,
  Lambda); no hand-written fillColor / stencil id.

Geometry is hand-authored for this conceptual flow with externals on both sides
of the account boundary (the lane-grid layout() engine models cloud
account/region containers only and cannot express external-outside-boundary
nodes). The shared build_diagram() handles orthogonalisation, label
backgrounds, text-box padding, Flow/Legend sizing and marker hygiene.
"""
from __future__ import annotations

from pathlib import Path

from rule_engine.diagram_layout import (
    ICON_SIZE,
    Boundary,
    Edge,
    Node,
    legend_lines_for,
    build_diagram,
)
from rule_engine.icon_resolver import resolve_icon, resolve_container

OUT = Path("04-flow-lms-launch.drawio")

# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #


def aws_renderer(role: str):
    """Renderer emitting the authoritative AWS style (asset embedded for PNG)."""
    from rule_engine.diagram_layout import _embed_asset_style

    style = _embed_asset_style(resolve_icon(role, "aws")["style_string"])

    def render(node: Node, parent_id: str) -> str:
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


# Neutral grayscale labelled box for external systems / actors — an honest
# "external system" node, NOT a faked vendor icon.
_NEUTRAL_SYSTEM = (
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "fontSize=12;fontColor=#000000;verticalAlign=middle;align=center"
)
_NEUTRAL_ACTOR = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "fontSize=12;fontColor=#000000;verticalAlign=middle;align=center"
)


def neutral_renderer(style: str):
    def render(node: Node, parent_id: str) -> str:
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


SYS = neutral_renderer(_NEUTRAL_SYSTEM)
ACTOR = neutral_renderer(_NEUTRAL_ACTOR)

# --------------------------------------------------------------------------- #
# Geometry (hand-authored, left-to-right)
# --------------------------------------------------------------------------- #
# Columns:
#   actors (x=40)  |  ui-api (x=340)  |  lti-adapter (x=640)  |  externals (x=1000)
# management-api-handler sits below lti-adapter (same column, lower row).
# Grid step 10; every origin a grid multiple. Icon 78, caption band ~30 below.

AX = 40           # Student-in-LMS actor column (outside, left)
UI_X = 320        # ui-api (inside account)
LTI_X = 560       # lti-adapter + management-api-handler (inside account)
EXT_X = 900       # Keycloak + Atlas (outside, right)

ROW_TOP = 240     # ui-api / lti-adapter row
ROW_BOT = 430     # management-api-handler row

nodes = [
    # Student in the LMS — a HUMAN USER → the AWS General User resource icon
    # (user role), not a neutral box (owner feedback 2026-10-17 b). External
    # actor, OUTSIDE the boundary (left).
    Node("student", "Student in LMS", AX, ROW_TOP, render=aws_renderer("user")),
    # ui-api — REST API Gateway (no gateway authorizer), INSIDE the account.
    Node("ui-api", "ui-api (REST API GW)", UI_X, ROW_TOP, render=aws_renderer("api_gateway")),
    # lti-adapter — Lambda, validates LTI launch + authorization, INSIDE.
    Node("lti-adapter", "lti-adapter (Lambda)", LTI_X, ROW_TOP, render=aws_renderer("serverless_fn")),
    # management-api-handler — Lambda, run / enrolment coordination, INSIDE.
    Node("mgmt-api", "management-api-handler", LTI_X, ROW_BOT, render=aws_renderer("serverless_fn")),
    # Keycloak SSO — external IdP, OUTSIDE (right, upper). 1.10.11 Theme 35:
    # the colorized Keycloak brand leaf (keycloak role), not the grey box.
    # Same 78×78 footprint and position — only the glyph changes.
    Node("keycloak", "Keycloak SSO", EXT_X, 100, render=aws_renderer("keycloak")),
    # MongoDB Atlas — external datastore (over VPC peering), OUTSIDE (right).
    # 1.10.11: real brand-green leaf (mongodb_atlas role), not the grey box.
    Node("atlas", "MongoDB Atlas (eu-central-1)", EXT_X, ROW_BOT,
         render=aws_renderer("mongodb_atlas")),
]

# AWS Account boundary — wraps ui-api, lti-adapter, management-api-handler.
# ui-api/lti-adapter at y=240 (icon 240..318, caption ~348).
# mgmt-api at y=430 (icon 430..508, caption ~538).
# left: ui-api x=320 -> box left 280; right: lti-adapter x=560..638 -> box right 678.
# top: 240 - 60 (caption strip + pad) = 180; bottom: 538 + 30 = 568.
account = Boundary(
    id="boundary-account",
    label="SEP — 870325637521 / eu-central-1",
    x=280,
    y=180,
    w=(LTI_X + ICON_SIZE + 40) - 280,   # right edge 678 -> w=398
    h=568 - 180,                        # 388
    style=resolve_container("boundary", "aws")["style_string"],
    kind="account",
)

# --------------------------------------------------------------------------- #
# Edges (numbered flow markers 1..7; exit right/bottom, enter left/top)
# --------------------------------------------------------------------------- #
# Vertical corridor between the account right edge (760) and externals (1000)
# sits at ~x=860. lti-adapter footprint: x=640..718, y=240..318 (caption ~348).

GAP = 790  # vertical corridor x between account (right 678) and externals (900)

edges = [
    # 1 Student -> ui-api : LTI 1.0/1.1 launch. student right -> ui-api left.
    Edge("e1", "student", "ui-api", "1", exit=(1.0, 0.5), entry=(0.0, 0.5),
         points=[(280, 279)]),
    # 2 ui-api -> lti-adapter : routes the launch. right -> left (same row).
    Edge("e2", "ui-api", "lti-adapter", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 3 lti-adapter -> Keycloak : validate corporate SSO token (external).
    #    right-top -> keycloak left. Up into the gap corridor, then across.
    Edge("e3", "lti-adapter", "keycloak", "3", exit=(1.0, 0.25), entry=(0.0, 0.5),
         points=[(GAP, 259), (GAP, 139)]),
    # 4 lti-adapter -> Atlas : read/write run + enrolment + session state.
    #    right-bottom -> atlas left (over VPC peering).
    Edge("e4", "lti-adapter", "atlas", "4", exit=(1.0, 0.6), entry=(0.0, 0.3),
         points=[(GAP + 40, 287), (GAP + 40, 453)]),
    # 5 lti-adapter -> management-api-handler : run / enrolment coordination.
    #    bottom-centre -> mgmt-api top (straight drop, same column, clear below).
    Edge("e5", "lti-adapter", "mgmt-api", "5", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # 6 management-api-handler -> Atlas : run / enrolment write.
    #    right -> atlas left (same row, straight level line).
    Edge("e6", "mgmt-api", "atlas", "6", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 7 lti-adapter -> Student : grade / score return to the LMS (async).
    #    back-edge, dashed. Exit lti-adapter LEFT, drop in the clear corridor
    #    between ui-api (ends x=398) and lti-adapter (starts x=560), run left
    #    below the boundary, up into the student's bottom. The drop column
    #    (x=480) clears the mgmt-api column (x=560..638) entirely.
    Edge("e7", "lti-adapter", "student", "7", dashed=True, exit=(0.0, 0.77), entry=(0.5, 1.0),
         points=[(480, 300), (480, 620), (79, 620)]),
]

flow_lines = [
    "Flow",
    "1. Student in the LMS initiates an LTI 1.0/1.1 launch to ui-api",
    "2. ui-api routes the launch to lti-adapter (no gateway authorizer)",
    "3. lti-adapter validates the corporate SSO token with Keycloak",
    "4. lti-adapter reads/writes run + enrolment + session in Atlas (VPC peering)",
    "5. lti-adapter calls management-api-handler for run / enrolment coordination",
    "6. management-api-handler writes run / enrolment state to Atlas",
    "7. lti-adapter returns the grade / score to the LMS (async callback)",
]

# Legend: only the boundaries actually drawn (legend_lines_for, WS11/C10 — this
# flow draws the SEP account box but NO VPC, so no "Inner boundary" line). No
# optional overlay vocabulary is used on this draft.
legend_lines = list(legend_lines_for([account]))

title = "aws SEP LMS launch — 870325637521 / eu-central-1 | 2026-10-17 | v5"

# Right-margin Flow/Legend: clear the external column + its wide captions.
legend_x = EXT_X + ICON_SIZE + 200   # 1178
legend_w = 300

drawio = build_diagram(
    diagram_id="aws-lms-launch",
    diagram_name="04-flow-lms-launch",
    title=title,
    boundaries=[account],
    nodes=nodes,
    edges=edges,
    flow_lines=flow_lines,
    legend_x=legend_x,
    legend_y_flow=60,
    legend_y_legend=320,
    legend_w=legend_w,
    legend_lines=legend_lines,
    page_w=legend_x + legend_w + 60,
    page_h=760,
)

OUT.write_text(drawio, encoding="utf-8")
print(f"wrote {OUT} ({len(drawio)} bytes), {len(nodes)} nodes, {len(edges)} edges")
