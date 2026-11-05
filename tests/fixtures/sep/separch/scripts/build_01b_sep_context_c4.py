#!/usr/bin/env python3
"""Build the 01b-sep-context-c4 diagram triple (.drawio) — C4 rendering of 01.

TASK F of the 1.11.0 regeneration (WS4 C4 style). Renders the SEP system context
in C4 style: every actor/system is a NEUTRAL dashed box labelled
``<name>\\n[Container: <role>]`` with NO provider icon, replicating the engine's
`_c4_box_renderer` (draw_cli.py:138-162, _C4_BOX_STYLE). This is a SEPARATE
triple from 01-sep-context — the existing 01 (AWS-glyph context) is unchanged.

Same actors/systems as 01: Student, Operator, LMS, Keycloak, SEP platform (with
the in-account Syndicate Server control plane), MongoDB Atlas, License Manager,
AI. The deprecated external EPM-CMTR / "Syndicate task manager" is removed. The hand-pinned
geometry mirrors 01 (the lane-grid layout() engine models cloud containers only
and cannot express external-outside-boundary nodes); the shared build_diagram()
handles orthogonalisation, label backgrounds, Flow/Legend sizing and marker
hygiene. The 1.11.0 native skin (grey edges, light furniture, circle badges) is
applied via the build_diagram skin channel.

Run from the workspace root:
    python3 scripts/build_01b_sep_context_c4.py
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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "01b-sep-context-c4.drawio"

# 1.11.0 native skin (FEAT-001): light Flow/Legend furniture (#B3B3B3), grey
# edges (#5A6B7B), circle marker badges (#1A1A1A disc + white numeral).
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

# --------------------------------------------------------------------------- #
# C4 box renderer — replicated from draw_cli.py:135-162 (WS4). A neutral dashed
# box labelled "<name>\n[Container: <tech>]" with NO provider icon, so the
# diagram reads as C4 Container boxes rather than cloud glyphs.
# --------------------------------------------------------------------------- #

_C4_BOX_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#333333;"
    "fontColor=#333333;fontSize=12;verticalAlign=middle;align=center"
)


def c4_renderer(tech: str):
    def render(node: Node, parent_id: str) -> str:
        label = f"{node.label}&#10;[Container: {tech}]" if tech else node.label
        return (
            f'        <mxCell id="{node.id}" value="{label}" style="{_C4_BOX_STYLE}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


# --------------------------------------------------------------------------- #
# Geometry (hand-authored for a conceptual context view, mirroring 01).
# Columns: actors (x=40) | edge + account (center) | external systems (x=860).
# Grid step 10; every origin a grid multiple.
# --------------------------------------------------------------------------- #

AX = 40
SEP_X = 440
EDGE_X = SEP_X
EXT_X = 860

nodes = [
    # Actors (OUTSIDE the boundary, left column) — C4 "Person" containers.
    Node("student", "Student", AX, 160, render=c4_renderer("Person")),
    Node("operator", "Operator", AX, 330, render=c4_renderer("Person")),
    Node("lms", "LMS learn.epam.com", AX, 560, render=c4_renderer("LMS / LTI")),
    Node("keycloak", "Keycloak SSO", AX, 730, render=c4_renderer("OIDC IdP")),
    # Edge (CloudFront + DNS) directly above SEP.
    Node("edge", "CloudFront + DNS", EDGE_X, 130, render=c4_renderer("CDN / DNS")),
    # SEP platform — the system under design (inside the account boundary).
    Node("sep", "SEP platform", SEP_X, 420, render=c4_renderer("AWS Lambda / Batch")),
    # Syndicate Server — the in-account control plane (EC2 host in the SEP
    # account) that drives sandbox/org lifecycle. Task-4 (2026-10-23): drawn
    # INSIDE the SEP boundary as a C4 "EC2 host" container; the deprecated
    # external EPM-CMTR / "Syndicate task manager" (Jenkins) is removed.
    # FEAT-003: one EC2 hosts TWO components (Education Extension + Syndi);
    # caption names both. Never split into two nodes; stays inside the account.
    Node("syndicate", "Syndicate Server&#10;(Education Extension + Syndi)", SEP_X, 620,
         render=c4_renderer("EC2 host")),
    # External systems (OUTSIDE the boundary, right column).
    Node("atlas", "MongoDB Atlas", EXT_X, 120, render=c4_renderer("MongoDB")),
    Node("lm", "License Manager", EXT_X, 690, render=c4_renderer("EPAM licensing")),
    Node("ai", "AI Bedrock / DIAL", EXT_X, 860, render=c4_renderer("LLM platform")),
]

# The SEP boundary is also a neutral C4 box (no AWS group glyph), but the shared
# builder still accepts a resolved container style; use the dashed C4 look so the
# whole diagram stays provider-neutral (no resIcon / image=assets token).
_C4_BOUNDARY_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;strokeColor=#333333;"
    "fontColor=#333333;verticalAlign=top;align=left;spacingLeft=6;fontSize=12"
)

account = Boundary(
    id="boundary-account",
    label="SEP — software system (AWS 870325637521 / eu-central-1)",
    x=390,
    y=350,
    w=ICON_SIZE + 2 * 50,
    h=728 - 350 + 30,   # 408: encloses SEP + the in-account Syndicate Server
    style=_C4_BOUNDARY_STYLE,
    kind="account",
)

# --------------------------------------------------------------------------- #
# Edges (numbered flow markers 1..N; exit right/bottom, enter left/top) — same
# relationships as 01.
# --------------------------------------------------------------------------- #
GAP = 700

edges = [
    Edge("e1", "student", "edge", "1", exit=(1.0, 0.5), entry=(0.0, 0.885)),
    Edge("e2", "edge", "sep", "2", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    Edge("e3", "operator", "sep", "3", exit=(1.0, 0.5), entry=(0.0, 0.25),
         points=[(360, 369), (360, 440)]),
    Edge("e4", "lms", "sep", "4", exit=(1.0, 0.4), entry=(0.0, 0.55),
         points=[(340, 591), (340, 463)]),
    Edge("e5", "keycloak", "sep", "5", exit=(1.0, 0.3), entry=(0.0, 0.85),
         points=[(320, 753), (320, 486)]),
    Edge("e6", "sep", "atlas", "6", exit=(1.0, 0.3), entry=(0.0, 0.5),
         points=[(GAP, 443), (GAP, 159)]),
    # SEP ⇄ Syndicate Server (SQS, in-account control plane): short straight
    # vertical drop inside the account (SEP bottom -> syndicate top).
    Edge("e7", "sep", "syndicate", "7", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # e8/e9 nest crossing-free on SEP's right face (Task-5 uncross): HIGHER
    # target (License Mgr, y690) exits HIGHER (band 0.513) and takes the OUTER
    # corridor x=GAP-40=660; LOWER target (AI, y860) exits LOWER (band 0.769)
    # and takes the INNER corridor x=GAP-80=620, so the two runs nest and never
    # cross as they reach the shared external column at x=860.
    # 8 License Manager -> SEP (owner step 21, CONFIRMED via ESM 5fe731e5): LM
    #    sends to the SEP sep-lm-synchronization-queue, relayed to the
    #    se-management-api-handler Lambda — LM is the SOURCE. Flipped lm->sep and
    #    re-pinned contract-legal: exit lm BOTTOM (0.5,1.0)=(899,768), floor lane
    #    y=940, left to x=370 (left of the account border 390, a fresh corridor),
    #    rise, enter SEP LEFT at y~436. Every leg axis-aligned; no collision with
    #    e6 (x=700) or e9 (floor at y~900).
    Edge("e8", "lm", "sep", "8", dashed=True, exit=(0.5, 1.0), entry=(0.0, 0.2),
         points=[(899, 940), (370, 940), (370, 436)]),
    Edge("e9", "sep", "ai", "9", exit=(1.0, 0.769), entry=(0.0, 0.513),
         points=[(GAP - 80, 480), (GAP - 80, 900)]),
]

flow_lines = [
    "Flow",
    "1. Student opens Syndicate UI / LMS launch via the edge",
    "2. Edge (CloudFront) serves the UI and forwards API calls to SEP (se-ui-api REST)",
    "3. Operator drives SEP via the management API / CLI",
    "4. LMS launches SEP via LTI 1.0/1.1",
    "5. Keycloak validates the corporate SSO token for SEP",
    "6. SEP reads/writes application data in MongoDB Atlas (over VPC peering)",
    "7. SEP <-> Syndicate Server over SQS: sandbox/org lifecycle (in-account control plane)",
    "8. License Manager -> SEP (sep-lm-synchronization-queue -> se-management-api-handler)",
    "9. SEP calls AI providers (Bedrock / DIAL) for Syndi / Angry EdA",
]

legend_lines = list(STANDARD_LEGEND_LINES) + [
    "C4 box = <name> [Container: <tech>]; no provider icon (C4 Container grammar)",
    "callout 'draft-assumption' = unconfirmed path, first-draft assumption",
]

title = "aws SEP context C4 — 870325637521 / eu-central-1 | 2026-10-23 | v4"

legend_x = EXT_X + ICON_SIZE + 160
legend_w = 300

drawio = build_diagram(
    diagram_id="aws-context-c4",
    diagram_name="01b-sep-context-c4",
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
    skin=NATIVE_SKIN,
)

OUT.write_text(drawio, encoding="utf-8")
print(f"wrote {OUT} ({len(drawio)} bytes), {len(nodes)} nodes, {len(edges)} edges")
