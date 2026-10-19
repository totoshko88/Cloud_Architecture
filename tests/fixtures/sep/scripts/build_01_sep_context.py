#!/usr/bin/env python3
"""Build the 01-sep-context diagram triple (.drawio) via the shared builder.

C4 System Context for the Syndicate Education Platform (SEP).
- diagram_class: flow, diagram_type: context, provider profile: aws for cloud node.
- SEP is ONE AWS Account boundary (870325637521 / eu-central-1) with a single
  representative platform node inside it.
- All actors and external systems are drawn OUTSIDE the account boundary.
- External non-AWS systems use a neutral grayscale labelled box (no fake vendor
  icon). Actors likewise. AWS nodes (SEP platform, CloudFront/DNS edge) resolve
  their icon through mappings/aws-icons.yaml.

Coordinates here are the hand-authored geometry for a conceptual context view
(the lane-grid layout() engine models cloud account/region containers only and
cannot express external-outside-boundary nodes). The shared build_diagram()
handles orthogonalisation, label backgrounds, text-box padding, Flow/Legend
sizing and marker hygiene.
"""
from __future__ import annotations

from pathlib import Path

from rule_engine.diagram_layout import (
    ICON_SIZE,
    Boundary,
    Edge,
    Node,
    STANDARD_LEGEND_LINES,
    build_diagram,
)
from rule_engine.icon_resolver import resolve_icon, resolve_container

OUT = Path("01-sep-context.drawio")

# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #


def aws_renderer(role: str):
    """Renderer emitting the authoritative AWS style verbatim (no double label).

    The AWS style resolves to a file-path image under assets/vendor; build_diagram
    does NOT process a hand-passed render output, so embed the asset here the same
    way builtin_icon/image_icon do, so it renders in the editor and PNG export.
    """
    from rule_engine.diagram_layout import _embed_asset_style

    style = resolve_icon(role, "aws")["style_string"]
    style = _embed_asset_style(style)

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
# "external system" node, NOT a faked vendor icon. White fill, black stroke,
# 12px label centred inside, rounded for actors / square for systems.
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
# Geometry (hand-authored for a conceptual context view)
# --------------------------------------------------------------------------- #
# Columns: actors (x=40) | edge + account (center) | external systems (x=840)
# Grid step 10; every origin a grid multiple.

AX = 40          # actors column
SEP_X = 440      # SEP platform node inside the account boundary
EDGE_X = SEP_X   # edge node (CloudFront/DNS) directly above SEP for a clean drop
EXT_X = 860      # external systems column

nodes = [
    # Actors (OUTSIDE the boundary, left column). Rows chosen so none shares a
    # horizontal band with SEP (420..498) — avoids a mis-read "level" jog.
    # Student and Operator are HUMAN USERS → the AWS General User resource icon
    # (user role, white bg), not a neutral box (owner feedback 2026-10-17 b).
    Node("student", "Student", AX, 160, render=aws_renderer("user")),
    Node("operator", "Operator", AX, 330, render=aws_renderer("user")),
    # LMS: owner asked for a student/mortarboard (graduation-cap) glyph from
    # draw.io's Education set (regen9). The installed draw.io ships no generic
    # mortarboard stencil, and a bare mxgraph.* stencil fails verify-icon
    # --strict (reported `unverified`). The faithful, gate-passing answer is a
    # hand-authored public-domain mortarboard SVG (assets/vendor/education/)
    # wired as the `education` image role — a real learning glyph, not a
    # look-alike, that renders in the PNG.
    Node("lms", "LMS (learn.epam.com)", AX, 560, render=aws_renderer("education")),
    # Keycloak SSO renders the colorized Keycloak brand leaf (keycloak role,
    # 1.10.11 Theme 35), not the neutral actor box. Same 78×78 footprint and
    # position — only the glyph changes, so the edge geometry is unchanged.
    Node("keycloak", "Keycloak SSO", AX, 730, render=aws_renderer("keycloak")),
    # Edge (AWS CloudFront + DNS) — edge lane, directly above SEP. Pinned at
    # y=130 (not 40) so the reserved title band at the top of the canvas no
    # longer prints over the CloudFront icon/caption (edge-crosses-title /
    # title keep-out — the user's "заголовок наліз на CloudFront" finding).
    Node("edge", "CloudFront + DNS", EDGE_X, 130, render=aws_renderer("cdn")),
    # SEP platform — the ONE representative AWS node, inside the account boundary.
    # Rendered with the custom SEP brand mark (sep_platform role, assets/local).
    Node("sep", "SEP platform", SEP_X, 420, render=aws_renderer("sep_platform")),
    # External systems (OUTSIDE the boundary, right column). cmtr kept clear of
    # SEP's band (top 520 > 498) so the SEP->cmtr edge is not a mis-read jog.
    Node("atlas", "MongoDB Atlas (eu-central-1)", EXT_X, 120,
         render=aws_renderer("mongodb_atlas")),
    # Syndicate Server is an EC2 host → the EC2 service icon (compute_instance).
    # External (different account) but naming the real resource type is correct
    # and Icon-Fidelity clean (owner feedback 2026-10-17 e).
    Node("syndicate", "Syndicate Server", EXT_X, 300,
         render=aws_renderer("compute_instance")),
    # EPM-CMTR literally IS an AWS account (088595288622) → the AWS Organizations
    # Account resource icon (peer_account), not a neutral box. Stays OUTSIDE the
    # SEP account boundary — it is a different account (owner feedback c).
    Node("cmtr", "EPM-CMTR (088595288622)", EXT_X, 520,
         render=aws_renderer("peer_account")),
    # License Manager → the real AWS License Manager service icon (new
    # license_manager role, Management & Governance family) (owner feedback g).
    Node("lm", "License Manager", EXT_X, 690,
         render=aws_renderer("license_manager")),
    # AI (Bedrock / DIAL) → the Amazon Bedrock icon (llm_platform). Label keeps
    # the DIAL mention (owner feedback f).
    Node("ai", "AI (Bedrock / DIAL)", EXT_X, 860,
         render=aws_renderer("llm_platform")),
]

# AWS Account boundary — wraps ONLY the SEP platform node.
# SEP at (440, 420), footprint bottom 420+78+30(label)=528.
# top strip = 60 (caption + pad); left/right/bottom pad = 30.
account = Boundary(
    id="boundary-account",
    label="SEP — AWS 870325637521 / eu-central-1",
    x=390,
    y=350,
    w=ICON_SIZE + 2 * 50,   # 178: left/right pad ~50 so caption fits
    h=528 - 350 + 40,       # bottom pad clears the label band
    style=resolve_container("boundary", "aws")["style_string"],
    kind="account",
)

# --------------------------------------------------------------------------- #
# Edges (numbered flow markers 1..N; exit right/bottom, enter left/top)
# --------------------------------------------------------------------------- #
# SEP footprint: x=440..518, y=420..498 (icon), caption to ~528.
# A corridor to the right of the external column caption band sits at ~ x=830
# (gap between SEP's account and the external column). Vertical corridors in the
# gap x=620..830. Bottom-face drops use lower-row corridors.
GAP = 700  # vertical corridor x between account (right ~568) and externals (860)

edges = [
    # 1 Student -> edge (UI + LMS launch). Owner feedback (a): leave Student from
    # its RIGHT-CENTRE cleanly, with NO bend at all. Student icon 40..118 x,
    # 160..238 y → right-centre (1.0,0.5) = (118, 199). Enter the edge's LEFT
    # face at the SAME y (199) — edge icon 130..208 y, so entryY=(199-130)/78
    # ≈ 0.885 — making e1 one perfectly straight horizontal segment (no jog,
    # no corridor points), which is exactly "exit from the middle of Student".
    Edge("e1", "student", "edge", "1", exit=(1.0, 0.5), entry=(0.0, 0.885)),
    # 2 edge -> SEP: edge bottom-centre -> straight vertical drop into SEP top
    #    (edge node is directly above SEP, so this is a single straight segment)
    Edge("e2", "edge", "sep", "2", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # 3 Operator -> SEP (management API/CLI): operator right -> SEP left-top
    Edge("e3", "operator", "sep", "3", exit=(1.0, 0.5), entry=(0.0, 0.25),
         points=[(360, 369), (360, 440)]),
    # 4 LMS -> SEP (LTI 1.0/1.1 launch): lms right -> SEP left-middle
    Edge("e4", "lms", "sep", "4", exit=(1.0, 0.4), entry=(0.0, 0.55),
         points=[(340, 591), (340, 463)]),
    # 5 Keycloak -> SEP (SSO token validation): keycloak right -> SEP left-bottom
    Edge("e5", "keycloak", "sep", "5", exit=(1.0, 0.3), entry=(0.0, 0.85),
         points=[(320, 753), (320, 486)]),
    # --- SEP outgoing to externals: 3 on the RIGHT face, 2 on the BOTTOM face
    # 6 SEP -> MongoDB Atlas (data, over peering): right -> atlas left
    Edge("e6", "sep", "atlas", "6", exit=(1.0, 0.3), entry=(0.0, 0.5),
         points=[(GAP, 443), (GAP, 159)]),
    # 7 SEP ⇄ Syndicate Server (SQS): one edge annotated request/response
    #    (sandbox lifecycle + support out; results back) — right -> syndicate left
    Edge("e7", "sep", "syndicate", "7", exit=(1.0, 0.6), entry=(0.0, 0.4),
         points=[(GAP + 40, 467), (GAP + 40, 324)]),
    # 8 SEP -> EPM-CMTR (task verification SRE/CMTM/KTM, over peering):
    #    right -> cmtr left
    Edge("e8", "sep", "cmtr", "8", exit=(1.0, 0.85), entry=(0.0, 0.5),
         points=[(GAP + 80, 486), (GAP + 80, 559)]),
    # 9 SEP -> License Manager (license sync) — draft-assumption (BOTTOM face)
    Edge("e9", "sep", "lm", "9", dashed=True, exit=(0.35, 1.0), entry=(0.0, 0.3),
         points=[(467, 650), (GAP - 40, 650), (GAP - 40, 709)]),
    # 10 SEP -> AI (Bedrock / DIAL) (BOTTOM face)
    Edge("e10", "sep", "ai", "10", exit=(0.65, 1.0), entry=(0.0, 0.5),
         points=[(491, 830), (GAP - 80, 830), (GAP - 80, 899)]),
]

flow_lines = [
    "Flow",
    "1. Student opens Syndicate UI / LMS launch via the edge",
    "2. Edge (CloudFront) serves the UI and forwards API calls to SEP",
    "3. Operator drives SEP via the management API / CLI",
    "4. LMS launches SEP via LTI 1.0/1.1",
    "5. Keycloak validates the corporate SSO token for SEP",
    "6. SEP reads/writes application data in MongoDB Atlas (over VPC peering)",
    "7. SEP ⇄ Syndicate Server over SQS: sandbox lifecycle + support out, results back",
    "8. SEP submits task verification to EPM-CMTR (SRE/CMTM/KTM, over peering)",
    "9. SEP license sync to License Manager [draft-assumption]",
    "10. SEP calls AI providers (Bedrock / DIAL) for Syndi / Angry EdA",
]

# Legend: standard lines + the draft-assumption callout term documented.
legend_lines = list(STANDARD_LEGEND_LINES) + [
    "callout 'draft-assumption' = unconfirmed path, first-draft assumption",
]

title = "aws SEP context — 870325637521 / eu-central-1 | 2026-10-17 | v6"

# Right-margin Flow/Legend: past the external column + its wide captions.
# External captions are long ("MongoDB Atlas (eu-central-1)"), so clear them.
legend_x = EXT_X + ICON_SIZE + 200   # 1138
legend_w = 300

drawio = build_diagram(
    diagram_id="aws-context",
    diagram_name="01-sep-context",
    title=title,
    boundaries=[account],
    nodes=nodes,
    edges=edges,
    flow_lines=flow_lines,
    legend_x=legend_x,
    legend_y_flow=60,
    legend_y_legend=460,
    legend_w=legend_w,
    legend_lines=legend_lines,
    page_w=legend_x + legend_w + 60,
    page_h=1020,
)

OUT.write_text(drawio, encoding="utf-8")
print(f"wrote {OUT} ({len(drawio)} bytes), {len(nodes)} nodes, {len(edges)} edges")
