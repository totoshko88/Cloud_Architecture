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
    Skin,
    build_diagram,
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
WAF_X = 240      # WAF node, edge lane, LEFT of CloudFront so it exits RIGHT
                 # into CloudFront's LEFT face (WAF fronts/protects CloudFront).
                 # GLOBAL/edge service — OUTSIDE the account/VPC, never inside.
SANDBOX_X = 600  # Sandbox fleets node, OUTSIDE the account, right-below the
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
    Node("sep", "SEP platform", SEP_X, 420, render=aws_renderer("sep_platform")),
    # Syndicate Server — the control plane that drives sandbox/org lifecycle.
    # It is an EC2 host IN the SEP account (870325637521, instance tagged
    # "syndicate-server", see compute.json) → drawn INSIDE the account boundary
    # with the EC2 service icon (compute_instance). Task-4 (2026-10-23): the
    # deprecated external "Syndicate task manager"/Jenkins (EPM-CMTR) is gone;
    # the real control plane is this server inside SEP (owner feedback 2026-10-21).
    # FEAT-003: one EC2 hosts TWO components (Education Extension + Syndi);
    # caption names both. Never split into two nodes; stays inside the account.
    # Two-line caption so the (Education Extension + Syndi) line stays narrow
    # enough that its caption band clears marker 5 (keycloak->SEP) — a single
    # 45-char line widened the caption under marker 5 (marker-label-collision).
    Node("syndicate", "Syndicate Server&#10;(Education Extension + Syndi)", SEP_X, 620,
         render=aws_renderer("compute_instance")),
    # Sandbox fleets — the multi-cloud (AWS / Azure / GCP) sandbox accounts the
    # Syndicate Server PROVISIONS and CLEANS UP. Role `sandbox_multicloud`
    # (same composite asset as 09), OUTSIDE the SEP account boundary (they are
    # separate sandbox accounts, not SEP-account resources). Drawn right-below
    # the Syndicate Server so the provision/cleanup edge is a short clean run.
    Node("sandbox", "Sandbox fleets (3 clouds)", SANDBOX_X, 800,
         render=aws_renderer("sandbox_multicloud")),
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
    # AI (Bedrock / DIAL) → the Amazon Bedrock icon (llm_platform). Label keeps
    # the DIAL mention (owner feedback f).
    Node("ai", "AI (Bedrock / DIAL)", EXT_X, 860,
         render=aws_renderer("llm_platform")),
]

# AWS Account boundary — wraps the SEP platform node AND the Syndicate Server
# (the in-account control plane). SEP at (440, 420); syndicate at (440, 620),
# footprint bottom 620+78+30(label)=728. top strip = 60 (caption + pad);
# left/right pad ~50 so the caption fits; bottom pad 30 clears the label band.
account = Boundary(
    id="boundary-account",
    label="SEP — AWS 870325637521 / eu-central-1",
    x=390,
    y=350,
    w=ICON_SIZE + 2 * 50,   # 178: left/right pad ~50 so caption fits
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
GAP = 700  # vertical corridor x between account (right ~568) and externals (860)

edges = [
    # 1 Student -> WAF (the external request path hits the CloudFront WAF first).
    # WAF now fronts CloudFront in the drawn path (WAF added wave-12), so the
    # student request enters at the WAF and is relayed to CloudFront by e11.
    # Student icon 40..118 x, 160..238 y → right-centre (1.0,0.5) = (118, 199).
    # Enter the WAF's LEFT face at the SAME y (199) — WAF icon 240..318, y130..208,
    # so entryY=(199-130)/78 ≈ 0.885 — one straight horizontal segment, no bend.
    Edge("e1", "student", "waf", "1", exit=(1.0, 0.5), entry=(0.0, 0.885)),
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
    # --- SEP outgoing: 3 on the RIGHT face (atlas, lm, ai), 1 on the BOTTOM
    #     face to the in-account Syndicate Server.
    # 6 SEP -> MongoDB Atlas (data, over peering): right -> atlas left (rises
    #    in the outer corridor x=GAP=700)
    Edge("e6", "sep", "atlas", "6", exit=(1.0, 0.3), entry=(0.0, 0.5),
         points=[(GAP, 443), (GAP, 159)]),
    # 7 SEP ⇄ Syndicate Server (SQS, in-account control plane): SEP bottom ->
    #    syndicate top, a short straight vertical drop inside the account (the
    #    opaque caption background masks the own-label crossing; z-order safe).
    Edge("e7", "sep", "syndicate", "7", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # --- e8/e9 nest crossing-free on SEP's right face (Task-5 uncross) ---
    #     Both targets sit in the external column at x=860 (lm higher at y690,
    #     ai lower at y860), so each edge drops in its own corridor and then
    #     runs right to x=860. For the two runs to NOT cross, the edge to the
    #     HIGHER target takes the OUTER corridor and exits HIGHER on the face,
    #     while the edge to the LOWER target takes the INNER corridor and exits
    #     LOWER — the runs nest. (The original pinned the higher target through
    #     the righter corridor AND the lower through the lefter corridor, which
    #     inverted them because both must still reach the shared x=860 column,
    #     so their right-runs crossed the opposite vertical; this re-pin fixes
    #     it against the FINAL node layout after the Task-4 move.) Every leg is
    #     axis-aligned; exit right, enter left.
    # --- e8/e9 corridors moved OUTSIDE the account right edge (690) so neither
    #     marker anchor rides a container border (FEAT-002 ITEM A / FEAT-001
    #     marker-on-container-border: e9's old x=620 vertical crossed the account
    #     bottom border y=758 inside its x-extent 390..690, so marker 9's numeral
    #     sat on the box edge — the owner's "9 наїхала на box account" finding).
    #     Both corridors now sit right of x=690 and NEST so their right-runs do
    #     not cross: the LOWER target (ai) takes the OUTER corridor x=720 and runs
    #     along the lower y=900; the HIGHER target (lm) takes the INNER corridor
    #     x=760 and runs along y=730. The inner vertical (x=760, y 460..730) never
    #     reaches the outer's lower run, and the outer vertical (x=720) sits left
    #     of the inner's horizontal start (x=760), so the two legs are disjoint.
    # 8 License Manager -> SEP (owner step 21, CONFIRMED via ESM 5fe731e5):
    #    License Manager sends to the SEP sep-lm-synchronization-queue, which an
    #    event-source mapping relays to the se-management-api-handler Lambda, so
    #    LM is the SOURCE and SEP the target. The edge is flipped lm->sep and
    #    re-pinned contract-legal: exit lm BOTTOM (0.5,1.0)=(899,768), drop to a
    #    floor lane y=940, run left (clear of the account x390..568) to x=370,
    #    rise in the x=370 left lane (left of the account border 390, a fresh
    #    corridor distinct from e3@360/e4@340/e5@320), then enter SEP's LEFT face
    #    at y~436. Every leg is axis-aligned; the only crossing is with e10's
    #    floor loop, within the flow crossing cap. No collision with e6's x=700
    #    corridor (sep->atlas).
    Edge("e8", "lm", "sep", "8", dashed=True, exit=(0.5, 1.0), entry=(0.0, 0.2),
         points=[(899, 940), (370, 940), (370, 436)]),
    # 9 SEP -> AI (Bedrock / DIAL) — LOWER target, OUTER corridor x=720. Exit SEP
    #    right at y=480 (band 0.769); run to x=720; drop to y=900; enter ai left
    #    (ai icon 860..938 → ~0.51). Corridor x=720 is 30px right of the account
    #    border (690), so marker 9's midpoint anchor (~720, 659) is clear of every
    #    border.
    Edge("e9", "sep", "ai", "9", exit=(1.0, 0.769), entry=(0.0, 0.513),
         points=[(720, 480), (720, 900)]),
    # 10 SEP -> LMS (LTI grade passback / Assignment-and-Grade Services): SEP
    #    returns task results to the LMS so the learner's course grade updates.
    #    A return edge to the bottom-left external LMS. Exits SEP right (contract
    #    legal), runs down the right gap INSIDE its own account, exits the account
    #    bottom once, loops along the canvas floor (below the AI row) and up the
    #    far-left margin, entering LMS on its LEFT face. The route stays clear of
    #    e4 (LMS->SEP, which lives on the x=340 left corridor) and never re-enters
    #    the account interior after leaving it.
    #    wave-10 B3 (owner: "9 та 10 поміняти місцями точку виходу"): e9 (SEP->AI,
    #    lower-RIGHT) keeps the RIGHT-face exit; e10 (SEP->LMS, lower-LEFT) now
    #    exits the BOTTOM face LEFT-of-centre (0.3, left of e7's bottom-centre at
    #    0.5) and runs LEFT immediately, so the two no longer share the right face
    #    and cross. The drop is assigned by TARGET DIRECTION: the leftward return
    #    (LMS) takes a dedicated LEFT corridor x=300 (left of every incoming
    #    corridor e3@360/e4@340/e5@320 and of the account border 390), while the
    #    rightward target (AI) keeps the right corridor x=730 — the two runs now
    #    diverge from the SEP node with no crossing. Exit bottom-left -> short
    #    drop to y=520 (above the Syndicate Server at y620) -> left across y=520
    #    (clears the server, which starts at x440) -> down x=300 to the floor ->
    #    up the far-left margin into LMS's LEFT face. Every leg axis-aligned.
    Edge("e10", "sep", "lms", "10", exit=(0.3, 1.0), entry=(0.0, 0.5),
         points=[(463, 520), (300, 520), (300, 970), (30, 970), (30, 599)]),
    # 11 WAF -> CloudFront (WAF fronts/protects CloudFront; the inspected request
    #    is relayed to the CDN). WAF icon 240..318, y130..208; CloudFront icon
    #    440..518, y130..208 (same row). Exit WAF right-centre (1.0,0.5)=(318,169),
    #    enter CloudFront left-centre (0.0,0.5)=(440,169) — one straight
    #    horizontal segment, nothing between the two icons.
    Edge("e11", "waf", "edge", "11", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 12 Syndicate Server -> Sandbox fleets (provision + cleanup, control). The
    #    Syndicate Server (x=440 y=620, icon 440..518 y620..698) is INSIDE the
    #    account; sandbox (x=600 y=800) is OUTSIDE it. Exit syndicate RIGHT
    #    (1.0,0.5)=(518,659), run right to x=639 (sandbox top-centre column;
    #    crosses the account right border at x=568 legitimately as it leaves the
    #    account, stays left of e9's x=720 corridor so no crossing), then drop
    #    to sandbox TOP (0.5,0.0)=(639,800). Dashed = lifecycle control plane.
    Edge("e12", "syndicate", "sandbox", "12", dashed=True,
         exit=(1.0, 0.5), entry=(0.5, 0.0),
         points=[(639, 659), (639, 800)]),
]

flow_lines = [
    "Flow",
    "1. Student request enters via the CloudFront WAF (Syndicate UI / LMS launch)",
    "2. Edge (CloudFront) serves the UI and forwards API calls to SEP (se-ui-api REST)",
    "3. Operator drives SEP via the management API / CLI",
    "4. LMS launches SEP via LTI 1.0/1.1",
    "5. Keycloak validates the corporate SSO token for SEP",
    "6. SEP reads/writes application data in MongoDB Atlas (over VPC peering)",
    "7. SEP ⇄ Syndicate Server over SQS: sandbox/org lifecycle (the in-account control plane)",
    "8. License Manager -> SEP (sep-lm-synchronization-queue -> se-management-api-handler)",
    "9. SEP calls AI providers (Bedrock / DIAL) for Syndi / Angry EdA",
    "10. SEP returns task results to the LMS over LTI grade passback (AGS)",
    "11. WAF (syndicate_education_cloudfront_waf, global) relays to CloudFront",
    "12. Syndicate Server provisions and cleans up the multi-cloud sandbox fleets",
]

# Legend: standard lines + the draft-assumption callout term documented +
# the two new context nodes (WAF global/edge, multi-cloud sandbox fleets).
legend_lines = list(STANDARD_LEGEND_LINES) + [
    "callout 'draft-assumption' = unconfirmed path, first-draft assumption",
    "WAF = syndicate_education_cloudfront_waf (global, fronts CloudFront)",
    "Sandbox fleets = multi-cloud sandbox accounts (AWS/Azure/GCP), provisioned + cleaned by the Syndicate Server",
]

title = "aws SEP context — 870325637521 / eu-central-1 | 2026-10-28 | v14"

# Below-body Flow/Legend (Mode B, 1.10.12): a right-margin legend past this
# diagram's wide external column + long captions pushed the natural canvas width
# so the mandatory flow upscale rendered the PNG ~1608px — over the 1600px flow
# budget (the legend furniture, not any node, was the width driver). Placing the
# Flow/Legend as one block BELOW the body, left-aligned with it, makes the body
# (~1000px) the width driver instead, so the raster fits the flow budget. The
# body bottom is the e10 floor loop at y=970; the block sits at y=1010 (one grid
# step clear) and the page grows taller, which a flow diagram does not budget.
# Right-margin Flow/Legend: past the external column + its wide captions.
legend_x = EXT_X + ICON_SIZE + 200   # 1138
legend_w = 300
legend_y_flow = 60
legend_y_legend = 460

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
    page_h=1020,
    skin=NATIVE_SKIN,
)

OUT.write_text(drawio, encoding="utf-8")
print(f"wrote {OUT} ({len(drawio)} bytes), {len(nodes)} nodes, {len(edges)} edges")
