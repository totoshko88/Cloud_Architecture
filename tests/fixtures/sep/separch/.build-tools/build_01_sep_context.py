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
    Skin,
    build_diagram,
    legend_lines_for,
)
from rule_engine.icon_resolver import resolve_icon, resolve_container

OUT = Path("01-sep-context.drawio")

# 1.11.0 native skin (FEAT-001): light Flow/Legend furniture (#B3B3B3), grey
# edges (#5A6B7B), circle marker badges (#1A1A1A disc + white numeral). Applied
# through the shared build_diagram() skin channel, so the three presentation
# channels land on the engine-emitted edge/marker/furniture style strings while
# the hand-pinned node/edge GEOMETRY (coordinates) stays byte-stable.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #


def aws_renderer(role: str, extra: str = ""):
    """Renderer emitting the authoritative AWS style verbatim (no double label).

    The AWS style resolves to a file-path image under assets/vendor; build_diagram
    does NOT process a hand-passed render output, so embed the asset here the same
    way builtin_icon/image_icon do, so it renders in the editor and PNG export.
    """
    from rule_engine.diagram_layout import _embed_asset_style

    style = resolve_icon(role, "aws")["style_string"]
    style = _embed_asset_style(style)
    if extra:
        style = style.rstrip(";") + ";" + extra

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

# Callout — an explanatory text annotation box (NOT a node). It carries
# overlay=callout (documented in the Legend) and a `text;` style so node-count,
# node-label-length and verify-icon all skip it (geometry/cli key off
# is_text_cell_style). kiroAnnotation=1 marks it as an annotation. Uniform inner
# padding (spacing*=10) satisfies the text-padding rule for a filled+stroked box.
_CALLOUT_STYLE = (
    "text;html=1;whiteSpace=wrap;overlay=callout;kiroAnnotation=1;"
    "fillColor=#FFF7E6;strokeColor=#D79B00;fontColor=#000000;fontSize=12;"
    "align=left;verticalAlign=top;"
    "spacingLeft=10;spacingRight=10;spacingTop=10;spacingBottom=10"
)


def callout_renderer(w: int, h: int):
    def render(node: Node, parent_id: str) -> str:
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" '
            f'style="{_CALLOUT_STYLE}" vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{w}" height="{h}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render

# --------------------------------------------------------------------------- #
# Geometry (hand-authored for a conceptual context view)
# --------------------------------------------------------------------------- #
# Columns: actors (x=40) | edge + account (center) | external systems (x=840)
# Grid step 10; every origin a grid multiple.

AX = 40          # actors column
SEP_X = 560      # SEP platform node inside the account boundary. Shifted right
                 # (was 440) so the CloudFront->SEP drop (x=599) lands RIGHT of the
                 # wrapped, left-aligned account caption (ends ~x=565) and no longer
                 # crosses it (01-V2 / edge-crosses-container-label).
EDGE_X = SEP_X   # edge node (CloudFront/DNS) directly above SEP for a clean drop
EXT_X = 860      # external systems column
WAF_X = 240      # WAF node, edge lane, LEFT of CloudFront so it exits RIGHT
                 # into CloudFront's LEFT face (WAF fronts/protects CloudFront).
                 # GLOBAL/edge service — OUTSIDE the account/VPC, never inside.
SANDBOX_X = 620  # Sandbox fleets node, OUTSIDE the account, right-below the
                 # Syndicate Server (which provisions + cleans them). Kept left
                 # of e9's x=720 corridor so no edge crosses it.

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
    # WAF (syndicate_education_cloudfront_waf, wafv2 GLOBAL/us-east-1) fronts
    # CloudFront. Role `waf`; GLOBAL/edge, so it sits in the EDGE lane OUTSIDE
    # the account boundary, LEFT of CloudFront (so the protect edge exits WAF's
    # right face into CloudFront's left face — contract-legal). Short caption so
    # node-label-length stays <=4 words / <=40 chars and the caption band clears
    # the Student edge.
    Node("waf", "WAF (CloudFront)", WAF_X, 130, render=aws_renderer("waf")),
    # SEP platform — the ONE representative AWS node, inside the account boundary.
    # Rendered with the custom SEP brand mark (sep_platform role, assets/local).
    Node("sep", "SEP&#10;platform", SEP_X, 420, render=aws_renderer("sep_platform")),
    # Syndicate Server — the control plane that drives sandbox/org lifecycle.
    # It is an EC2 host IN the SEP account (870325637521, instance tagged
    # "syndicate-server", see compute.json) → drawn INSIDE the account boundary
    # with the EC2 service icon (compute_instance). The deprecated external
    # EPM-CMTR / CMTM (legacy Jenkins Task Manager) is NOT drawn anywhere on this
    # diagram (owner decision 2026-11-03: "Jenkins не треба … EPM-CMTR застарілий");
    # the real in-account control plane is this server.
    # FEAT-003: one EC2 hosts TWO components (Education Extension + Syndi). The
    # node caption is kept SHORT — the service name only ("Syndicate Server") —
    # so node-label-length stays <=4 words / <=40 chars and the caption band is
    # narrow. The two-component detail moves into a callout box (c-syndicate),
    # per diagram-standards "short labels; explanation goes in a callout".
    # Never split into two nodes; stays inside the account.
    Node("syndicate", "Syndicate Server", SEP_X, 620,
         render=aws_renderer("compute_instance")),
    # Sandbox fleets — the multi-cloud (AWS / Azure / GCP) sandbox accounts the
    # Syndicate Server PROVISIONS and CLEANS UP. Role `sandbox_multicloud`
    # (same composite asset as 09), OUTSIDE the SEP account boundary (they are
    # separate sandbox accounts, not SEP-account resources). Drawn right-below
    # the Syndicate Server so the provision/cleanup edge is a short clean run.
    # external=1: the sandbox accounts are separate accounts OUTSIDE the SEP
    # account; the token exempts it from the vertical-spill container-padding
    # test (it shares the account's x-band by design) and from scope-placement.
    Node("sandbox", "Sandbox fleets (3 clouds)", SANDBOX_X, 800,
         render=aws_renderer("sandbox_multicloud", extra="external=1")),
    # External systems (OUTSIDE the boundary, right column).
    Node("atlas", "MongoDB Atlas (eu-central-1)", EXT_X, 120,
         render=aws_renderer("mongodb_atlas")),
    # License Manager → a VENDOR-NEUTRAL license/certificate glyph (FIX 1,
    # 2026-10-21). SEP's "License Manager" is an EPAM licensing service (account
    # 652063929809), NOT the AWS License Manager service — so it must not carry
    # the AWS License Manager icon (an Icon-Fidelity look-alike). It now renders
    # the grayscale `license_neutral` certificate-with-seal mark, consistent with
    # how MongoDB / DIAL are handled (neutral / own-brand, never a fake AWS glyph).
    Node("lm", "License Manager", EXT_X, 690,
         render=aws_renderer("license_neutral")),
    # AI (Bedrock / DIAL) → the Amazon Bedrock icon (llm_platform). Two DISTINCT
    # AI paths feed this node (canonical-facts §2): Bedrock is reached from the
    # Lambda app (the "Angry EdA" path, edge from SEP), and the EPAM DIAL API is
    # reached from the Syndicate Server EC2 (the "Syndi" path, edge from
    # syndicate). The two are NEVER one merged edge from a single generic node.
    Node("ai", "AI (Bedrock / DIAL)", EXT_X, 860,
         render=aws_renderer("llm_platform")),
    # Callout (NOT a node): names the two logical components the one Syndicate
    # Server EC2 hosts. Placed directly under the account, beside the
    # Syndicate Server it annotates. overlay=callout documented in the Legend.
    Node("c-syndicate",
         "One EC2, two components:&#10;Education Extension (05)&#10;+ Syndi (07)",
         400, 790, render=callout_renderer(170, 100)),
]

# AWS Account boundary — wraps the SEP platform node AND the Syndicate Server
# (the in-account control plane). SEP at (440, 420); syndicate at (440, 620),
# footprint bottom 620+78+30(label)=728. top strip = 60 (caption + pad);
# left/right pad ~50 so the caption fits; bottom pad 30 clears the label band.
# Width chosen so the account caption
# "SEP — AWS 870325637521 / eu-central-1" (~38 chars, ~293px at 7px/char + the
# AWS-group spacingLeft) fits WITHIN the box: container-caption-overflow was
# +115px at w=178 (01-V2 / 01-L review). w=310 → right edge 700, holds the
# caption on one line (fit_boundary_captions no longer has to grow it, so the
# in-account Syndicate caption can no longer block the growth — engine E4).
account = Boundary(
    id="boundary-account",
    label="SEP — AWS 870325637521 / eu-central-1",
    x=390,
    y=350,
    w=310,                  # right edge 700; holds the caption on one line
    h=728 - 350 + 30,       # 408: bottom pad clears the syndicate label band
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
# Node boxes (icon 78x78):
#   student 40..118 / 160..238   operator 40..118 / 330..408
#   lms     40..118 / 560..638   keycloak 40..118 / 730..808
#   waf    240..318 / 130..208   edge(CF) 440..518 / 130..208
#   sep    440..518 / 420..498   syndicate 440..518 / 620..698
#   sandbox 600..678 / 800..878
#   atlas  860..938 / 120..198   lm 860..938 / 690..768   ai 860..938 / 860..938
# Account box: x 390..700, y 350..758. Right-gap corridors (right of 700, left of
# the external column 860) at x=720 / 760 / 800. Left-of-account corridors (left
# of actor-in corridors 320/340/360, left of account 390) at x=20 / 300.

edges = [
    # --- Ingress path, in flow order (canonical-facts §1):
    #     Student -> WAF -> CloudFront -> SEP ({S3 se-ui, se-ui-api, Lambda URL}).
    # 1 Student -> WAF: student right-centre (118,199) -> WAF left face. WAF icon
    #   240..318 y130..208; entryY=(199-130)/78 ~ 0.885 -> one straight segment.
    Edge("e1", "student", "waf", "1", exit=(1.0, 0.5), entry=(0.0, 0.885)),
    # 2 WAF -> CloudFront: same row (y130..208), nothing between. WAF right-centre
    #   (318,169) -> CloudFront left-centre (560,169): one straight horizontal.
    Edge("e2", "waf", "edge", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 3 CloudFront -> SEP: edge node directly above SEP (both x=560), so a single
    #   straight vertical drop from the edge bottom into SEP's top, right of the
    #   wrapped account caption.
    Edge("e3", "edge", "sep", "3", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # 4 Operator -> SEP (management API / CLI): corridor x=360, SEP left band 0.15.
    Edge("e4", "operator", "sep", "4", exit=(1.0, 0.5), entry=(0.0, 0.15),
         points=[(360, 369), (360, 432)]),
    # 5 LMS -> SEP (LTI 1.0/1.1 launch): OUTER corridor x=320 (higher entry nests outside e6), SEP left band 0.4.
    Edge("e5", "lms", "sep", "5", exit=(1.0, 0.4), entry=(0.0, 0.4),
         points=[(320, 591), (320, 451)]),
    # 6 Keycloak -> SEP (SSO token validation): INNER corridor x=340, SEP left band 0.65.
    Edge("e6", "keycloak", "sep", "6", exit=(1.0, 0.3), entry=(0.0, 0.65),
         points=[(340, 753), (340, 471)]),
    # 7 SEP -> MongoDB Atlas (application data, over VPC peering): exit SEP right
    #   (band 0.4), rise in the OUTER x=745 right-gap corridor into atlas left.
    Edge("e7", "sep", "atlas", "7", exit=(1.0, 0.4), entry=(0.0, 0.5),
         points=[(745, 451), (745, 159)]),
    # 8 SEP -> Syndicate Server over SQS (in-account control plane): SEP sits
    #   directly above syndicate. SEP's right face already carries 3 exits (e7,
    #   e10, e12), so leave the BOTTOM face at its LEFT corner (x=560): the SEP
    #   caption is two short lines ("SEP" / "platform", ~56px, centred 571..627),
    #   so a drop at x=560 clears it. Enter syndicate's top-left corner: one
    #   straight vertical, no jog, no own-caption cut.
    Edge("e8", "sep", "syndicate", "8", exit=(0.0, 1.0), entry=(0.0, 0.0)),
    # 9 License Manager -> SEP (owner step 21, CONFIRMED via ESM 5fe731e5):
    #   LM sends to the SEP sep-lm-synchronization-queue, relayed by an
    #   event-source mapping to se-management-api-handler, so LM is the SOURCE.
    #   LM sits directly above the AI node, so a bottom drop would cut through it.
    #   Back-edge: exit LM RIGHT, drop in the x=990 lane (right of the AI caption,
    #   which overhangs to ~x=961), run the floor y=975 (below the AI caption band)
    #   left to x=370 (right of the actor corridors 320/340/360, left of the
    #   account border 390), rise to y=494 and enter SEP's LEFT face at band 0.95,
    #   BELOW every actor entry (432/451/471) so the rise crosses none of them.
    Edge("e9", "lm", "sep", "9", dashed=True, exit=(1.0, 0.5), entry=(0.0, 0.95),
         points=[(990, 729), (990, 975), (380, 975), (380, 494)]),
    # 10 SEP -> Bedrock (the "Angry EdA" LLM path): Bedrock is reached from the
    #    Lambda app. Exit SEP right (band 0.7), drop in the x=800 right-gap
    #    corridor into the AI node's left face (upper band). Distinct from the
    #    DIAL edge (e11).
    Edge("e10", "sep", "ai", "10", exit=(1.0, 0.7), entry=(0.0, 0.35),
         points=[(800, 475), (800, 887)]),
    # 11 Syndicate Server -> DIAL (the "Syndi" path): the EPAM DIAL API
    #    (ai-proxy.lab.epam.com) is reached from the Syndicate Server EC2, NOT
    #    from Lambda (canonical-facts §2). Exit syndicate right, x=760 corridor,
    #    into the AI node's left face (lower band). Two DISTINCT edges (e10
    #    Bedrock, e11 DIAL) feed the one AI node, never one merged edge.
    Edge("e11", "syndicate", "ai", "11", exit=(1.0, 0.3), entry=(0.0, 0.65),
         points=[(760, 643), (760, 912)]),
    # 12 SEP -> LMS (LTI grade passback / AGS): a return bus OVER the row (01-V1).
    #    Exit SEP right (top band 0.1), out to the INNER x=720 corridor, rise to
    #    y=90 (above CloudFront row y130, below the title band y20..50), run left
    #    to x=20 (left of every icon column), drop to y=599, enter LMS LEFT face.
    #    Contract-legal (exit right, enter left) and crosses no other edge.
    Edge("e12", "sep", "lms", "12", exit=(1.0, 0.1), entry=(0.0, 0.5),
         points=[(720, 428), (720, 90), (20, 90), (20, 599)]),
    # 13 Syndicate Server -> Sandbox fleets (provision + cleanup lifecycle).
    #    Syndicate is INSIDE the account, sandbox OUTSIDE (x=620). Exit syndicate
    #    right (band 0.75), step into the x=659 sandbox column, drop into the
    #    sandbox top-centre. Dashed = lifecycle control plane.
    Edge("e13", "syndicate", "sandbox", "13", dashed=True,
         exit=(1.0, 0.75), entry=(0.5, 0.0),
         points=[(659, 679), (659, 800)]),
]

flow_lines = [
    "Flow",
    "1. Student request enters via the CloudFront WAF (Syndicate UI / LMS launch)",
    "2. WAF (syndicate_education_cloudfront_waf, global) relays to CloudFront",
    "3. CloudFront serves the UI and forwards API calls to SEP (se-ui-api REST, Lambda URL, S3 se-ui)",
    "4. Operator drives SEP via the management API / CLI",
    "5. LMS launches SEP via LTI 1.0/1.1",
    "6. Keycloak validates the corporate SSO token for SEP",
    "7. SEP reads/writes application data in MongoDB Atlas (over VPC peering)",
    "8. SEP -> SQS -> Syndicate Server (consume): sandbox/org lifecycle (in-account control plane)",
    "9. License Manager -> SEP (sep-lm-synchronization-queue -> se-management-api-handler)",
    "10. SEP (Lambda) calls Bedrock for Angry EdA",
    "11. Syndicate Server (EC2) calls the EPAM DIAL API for Syndi",
    "12. SEP returns task results to the LMS over LTI grade passback (AGS)",
    "13. Syndicate Server provisions and cleans up the multi-cloud sandbox fleets",
]

# Legend: built via legend_lines_for(boundaries) so the undrawn "Inner boundary"
# line is not listed (only the account box is drawn — no VPC). Extras document
# the callout overlay term and the two context nodes.
legend_lines = list(legend_lines_for([account])) + [
    "callout = explanatory annotation (not a node)",
    "WAF = syndicate_education_cloudfront_waf (global, fronts CloudFront)",
    "Sandbox fleets = multi-cloud sandbox accounts (AWS/Azure/GCP), provisioned + cleaned by the Syndicate Server",
]

title = "aws SEP context — 870325637521 / eu-central-1 | 2026-11-03 | v15"

# Right-margin Flow/Legend: left edge one grid step past the external column
# (x=860..938) and its captions. The external captions ("MongoDB Atlas
# (eu-central-1)", ~200px) overhang the icon, so start the furniture well clear
# at x=1138 (EXT_X + icon + 200). Flow at the top, Legend below it.
legend_x = EXT_X + ICON_SIZE + 200   # 1138
legend_w = 300
legend_y_flow = 60
legend_y_legend = 480

drawio = build_diagram(
    diagram_id="aws-context",
    diagram_name="01-sep-context",
    title=title,
    boundaries=[account],
    nodes=nodes,
    edges=edges,
    flow_lines=flow_lines,
    legend_x=legend_x,
    legend_y_flow=legend_y_flow,
    legend_y_legend=legend_y_legend,
    legend_w=legend_w,
    legend_lines=legend_lines,
    page_w=legend_x + legend_w + 60,
    page_h=1000,
    skin=NATIVE_SKIN,
    container_caption_wrap=2,   # wrap the account caption onto two lines (E4)
    respect_pins=True,          # keep the hand-routed lanes (engine may not move them)
    # pinned_ids=() → the hand-pinned edges are the engine's final routes we
    # want; the caption-safe / crossing-repair finishing passes may still
    # improve them. We do NOT pass respect_pins, so the passes can re-route.
)

OUT.write_text(drawio, encoding="utf-8")
print(f"wrote {OUT} ({len(drawio)} bytes), {len(nodes)} nodes, {len(edges)} edges")
