#!/usr/bin/env python3
"""Build the 04-flow-lms-launch diagram triple (.drawio) via the shared builder.

SEP runtime data-flow: LMS / LTI 1.0/1.1 launch and run management.
- diagram_class: flow, diagram_type: data-flow, provider profile: aws.
- Left-to-right along the lane order.
- Canonical ingress (canonical-facts.md section 1): Client -> WAF -> CloudFront
  -> ui-api. WAF and CloudFront are global/edge services and are drawn OUTSIDE
  the account boundary (WAF is CloudFront-scoped only).
- AWS Account boundary (870325637521 / eu-central-1) wraps ONLY the regional
  nodes: ui-api, lti-adapter, SQS queue, management-api-handler.
- Student (human) and the LMS service (learn.epam.com) are separate external
  nodes; the grade passback returns to the LMS service over a return bus.
- Keycloak SSO and MongoDB Atlas are EXTERNAL and drawn outside the boundary.
- AWS nodes resolve their icon through mappings/aws-icons.yaml; no hand-written
  fillColor / stencil id.

Geometry is hand-authored for this conceptual flow with externals on both sides
of the account boundary. The shared build_diagram() handles orthogonalisation,
label backgrounds, text-box padding, Flow/Legend sizing and marker hygiene.
"""
from __future__ import annotations

from pathlib import Path

from rule_engine.diagram_layout import (
    ICON_SIZE,
    Boundary,
    Edge,
    Node,
    Skin,
    build_diagram,
    legend_lines_for,
)
from rule_engine.icon_resolver import resolve_icon, resolve_container

OUT = Path("04-flow-lms-launch.drawio")

# 1.11.0 native skin: light Flow/Legend furniture, grey edges, circle markers.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")


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


# --------------------------------------------------------------------------- #
# Geometry (hand-authored). Edge row on top, account below, externals right.
# --------------------------------------------------------------------------- #
R0 = 120          # edge / actors row
R1 = 300          # ui-api / lti-adapter row (inside account)
R2 = 460          # sqs / management-api-handler share the row (inside account)
UI_X, LTI_X, SQS_X, MGMT_X = 800, 1020, 1020, 1240
EXT_X = 1440

nodes = [
    Node("student", "Student", 40, R0, render=aws_renderer("user")),
    # The LMS service (learn.epam.com): external SaaS, neutral client glyph.
    Node("lms", "LMS (learn.epam.com)", 240, R0, render=aws_renderer("saas")),
    Node("waf", "AWS WAF", 440, R0, render=aws_renderer("waf")),
    Node("cf", "CloudFront", 640, R0, render=aws_renderer("cdn")),
    Node("ui-api", "ui-api (REST API GW)", UI_X, R1, render=aws_renderer("api_gateway")),
    Node("lti-adapter", "lti-adapter (Lambda)", LTI_X, R1, render=aws_renderer("serverless_fn")),
    Node("sqs", "SQS queue", SQS_X, R2, render=aws_renderer("message_queue")),
    Node("mgmt-api", "management-api-handler", MGMT_X, R2, render=aws_renderer("serverless_fn")),
    Node("keycloak", "Keycloak SSO", EXT_X, R0, render=aws_renderer("keycloak")),
    Node("atlas", "MongoDB Atlas (eu-central-1)", EXT_X, R2, render=aws_renderer("mongodb_atlas")),
]

account = Boundary(
    id="boundary-account",
    label="SEP — 870325637521 / eu-central-1",
    x=760,
    y=240,
    w=(MGMT_X + ICON_SIZE + 40) - 760,
    h=(R2 + 78 + 30 + 30) - 240,
    style=resolve_container("boundary", "aws")["style_string"],
    kind="account",
)

edges = [
    Edge("e1", "student", "lms", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    Edge("e2", "lms", "waf", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    Edge("e3", "waf", "cf", "3", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    Edge("e4", "cf", "ui-api", "4", exit=(1.0, 0.5), entry=(0.0, 0.5),
         points=[(740, R0 + 39), (740, R1 + 39)]),
    Edge("e5", "ui-api", "lti-adapter", "5", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    Edge("e6", "lti-adapter", "keycloak", "6", exit=(1.0, 0.5), entry=(0.0, 0.5),
         points=[(1390, R1 + 39), (1390, R0 + 39)]),
    Edge("e7", "lti-adapter", "atlas", "7", exit=(1.0, 0.85), entry=(0.0, 0.25),
         points=[(1410, R1 + 66), (1410, R2 + 19)]),
    # lti-adapter -> management-api-handler goes THROUGH SQS (async, dashed);
    # inventory shows no direct invoke.
    Edge("e8", "lti-adapter", "sqs", "8", dashed=True, exit=(0.5, 1.0), entry=(0.5, 0.0)),
    Edge("e9", "sqs", "mgmt-api", "9", dashed=True, exit=(1.0, 0.5), entry=(0.0, 0.5)),
    Edge("e10", "mgmt-api", "atlas", "10", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # Grade passback returns to the LMS service (not the student): return bus
    # over the edge row, then drop into the LMS top.
    Edge("e11", "lti-adapter", "lms", "11", dashed=True, exit=(1.0, 0.1), entry=(0.5, 0.0),
         points=[(1150, R1 + 8), (1150, 70), (279, 70)]),
]

flow_lines = [
    "Flow",
    "1. Student opens the course in the LMS and starts an LTI 1.0/1.1 launch",
    "2. LMS sends the signed launch through AWS WAF (CloudFront-scoped)",
    "3. WAF passes allowed requests to CloudFront (sep-main)",
    "4. CloudFront forwards the launch to the ui-api origin (REST API GW; S3 se-ui and Lambda URL origins not drawn)",
    "5. ui-api routes the launch to lti-adapter (no gateway authorizer)",
    "6. lti-adapter validates the corporate SSO token with Keycloak",
    "7. lti-adapter reads/writes run + enrolment + session in Atlas (VPC peering)",
    "8. lti-adapter enqueues run / enrolment work on SQS (queue name unconfirmed)",
    "9. SQS triggers management-api-handler (event-source mapping)",
    "10. management-api-handler writes run / enrolment state to Atlas",
    "11. lti-adapter returns the grade (Basic Outcomes) to the LMS service (async)",
]

# Legend names only the boundaries actually drawn (no VPC here).
legend_lines = list(legend_lines_for([account]))

title = "aws SEP LMS launch — 870325637521 / eu-central-1 | 2026-11-03 | v8"

# Flow/Legend below the body, left-aligned with it (keeps the aspect ratio sane).
legend_x = 40
legend_w = 640

drawio = build_diagram(
    diagram_id="aws-lms-launch",
    diagram_name="04-flow-lms-launch",
    title=title,
    boundaries=[account],
    nodes=nodes,
    edges=edges,
    flow_lines=flow_lines,
    legend_x=legend_x,
    legend_y_flow=640,
    legend_y_legend=860,
    legend_w=legend_w,
    legend_lines=legend_lines,
    page_w=1560,
    page_h=1150,
    skin=NATIVE_SKIN,
)

OUT.write_text(drawio, encoding="utf-8")
print(f"wrote {OUT} ({len(drawio)} bytes), {len(nodes)} nodes, {len(edges)} edges")
