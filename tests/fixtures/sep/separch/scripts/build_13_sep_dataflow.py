#!/usr/bin/env python3
"""Build 13-sep-dataflow — HAND-PINNED builder (rule-engine 1.13.0 final).

13 is a frozen, owner hand-routed diagram (see README-13-HAND-PINNED.md): every
node position and every edge waypoint below is declared EXPLICITLY and handed
straight to ``build_diagram()`` — there is NO ``layout()`` call, so a regenerate
cannot re-flow the owner's routing. This replaces the archived coordinate-free
builder (``build_13_sep_dataflow.py.ARCHIVED-coordinate-free``), which must not
be run.

Hand-pin geometry is seeded 1:1 from the committed ``.drawio`` (v9). The v10
surgical edits (all other nodes / waypoints are verbatim):

  * ADD  syndicate-server (EC2) -> MongoDB Atlas (the PII flow to the unencrypted
         primary learner store) and Syndi -> DIAL AI; ADD Lambda -> Bedrock; each
         carries a data-classification note in the Flow legend.
  * DROP the false Lambda -> DynamoDB CI-lock edge (e8). DynamoDB stays as a
         `supporting` operational node (not a data-flow step).
  * S3 is regional: it sits in the Region box, OUTSIDE the se VPC. The VPC box
         is re-drawn (scope-placement ERROR otherwise) around ONLY the VPC-scoped
         nodes: RDS, ECS strapi-server and the Syndicate Server EC2.
  * ADD  a callout: RDS is VPC-scoped and its CMK is cross-account (account
         088595288622, DELTA-2026-10-31 F-5), so the "KMS boundary" label is exact.
  * SPLIT the Lambda exit contacts (bottom 0.25/0.5, right 0.25/0.5/0.75).
  * SHIFT e4 off the account's left border; SHORTEN node captions.

Run from the workspace root, then orthogonalise:
    python3 scripts/build_13_sep_dataflow.py
    rule-engine-orthogonalise 13-sep-dataflow.drawio
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from rule_engine.diagram_layout import (
    CONTAINER_PAD,
    Boundary,
    Edge,
    ICON_SIZE,
    Node,
    Skin,
    build_diagram,
    image_icon,
    legend_lines_for,
    overlay_legend_lines,
)

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "13-sep-dataflow"
PROVIDER = "aws"
TITLE = "aws SEP dataflow — 870325637521 / eu-central-1 | 2026-10-31 | v10"

NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

# --------------------------------------------------------------------------- #
# Icon styles from the WORKSPACE mapping (+ local overlay), as the archived
# builder did; fall back to the engine resolver for roles the mapping lacks.
# --------------------------------------------------------------------------- #
_MAP = yaml.safe_load((ROOT / "mappings" / "aws-icons.yaml").read_text(encoding="utf-8"))
_LOCAL = ROOT / "mappings" / "local" / "aws-icons.yaml"
if _LOCAL.exists():
    for _k, _v in ((yaml.safe_load(_LOCAL.read_text(encoding="utf-8")) or {}).get("resources") or {}).items():
        _MAP.setdefault("resources", {})[_k] = _v
AWS_STYLES: Dict[str, str] = {
    r: e["style"] for r, e in (_MAP.get("resources") or {}).items()
    if isinstance(e, dict) and e.get("style")
}
AWS_CONTAINERS: Dict[str, str] = {
    k: e["style"] for k, e in (_MAP.get("containers") or {}).items()
    if isinstance(e, dict) and e.get("style")
}
# 1.13.0 `external_cloud` container kind (bundled mapping; the workspace copy is
# stale and lacks it), caption centred so edges entering the Atlas top face never
# cut the caption text.
try:
    from rule_engine.icon_resolver import resolve_container
    ATLAS_BOX_STYLE = resolve_container("external_cloud", PROVIDER)["style_string"]
except Exception:  # pragma: no cover - stale mapping fallback
    ATLAS_BOX_STYLE = ("rounded=0;dashed=1;dashPattern=8 4;fillColor=none;strokeColor=#7D8998;"
                       "fontColor=#545B64;verticalAlign=top;fontStyle=1;html=1;whiteSpace=wrap;fontSize=12")
ATLAS_BOX_STYLE = ATLAS_BOX_STYLE.replace("align=left", "align=center").replace("spacingLeft=10;", "")


def _renderer(role: str):
    style = AWS_STYLES.get(role)
    if not style:
        from rule_engine.icon_resolver import resolve_icon
        style = resolve_icon(role, PROVIDER)["style_string"]
    return image_icon(style.split("image=", 1)[1])


def fx(px: int) -> float:
    """Contact fraction for a pixel offset on a 78px face (grid-resolved)."""
    return px / ICON_SIZE


# --------------------------------------------------------------------------- #
# Hand-pinned nodes: (id, role, x, y, caption, host boundary or "" = root, overlay)
# Absolute model coordinates (the builder emits child-relative geometry from the
# explicit ``membership`` mapping).
# --------------------------------------------------------------------------- #
_NODES = (
    ("student", "user", 60, 120, "Learner (PII, encrypted)", "", None),
    ("lms", "education", 60, 280, "LMS (LTI launch)", "", None),
    ("waf", "waf", 250, 120, "WAF", "boundary-account", None),
    ("cloudfront", "cdn", 250, 280, "CloudFront", "boundary-account", None),
    ("apigw", "api_gateway", 470, 280, "API Gateway", "boundary-region-a", None),
    ("lambda", "serverless_fn", 910, 280, "Lambda handlers", "boundary-region-a", None),
    ("batch", "batch", 1130, 280, "AWS Batch jobs", "boundary-region-a", None),
    ("strapi", "ecs", 520, 560, "ECS strapi-server", "boundary-vpc-a", None),
    ("syndi", "compute_instance", 520, 680, "Syndicate Server", "boundary-vpc-a", None),
    ("bedrock", "llm_platform", 1130, 440, "Amazon Bedrock", "boundary-region-a", None),
    ("rds", "managed_sql", 760, 560, "RDS strapi-pg (encrypted)", "boundary-vpc-a", None),
    ("s3", "object_store", 1350, 440, "S3 (PII, encrypted)", "boundary-region-a", None),
    ("dynamodb", "dynamodb", 1350, 580, "DynamoDB CI locks", "boundary-region-a", "supporting"),
    ("secrets", "secrets_store", 1350, 760, "Secrets / KMS", "boundary-region-a", None),
    # Reconcile coverage (inventory roles lb / message_queue): drawn as
    # `supporting` nodes - not steps of the PII/AI data flow this view traces.
    ("alb", "lb", 760, 680, "ALB strapi-alb", "boundary-vpc-a", "supporting"),
    ("sqs", "message_queue", 1130, 600, "SQS queues (14)", "boundary-region-a", "supporting"),
    ("dial", "dial", 30, 870, "DIAL AI (external)", "", None),
    ("atlas", "mongodb_atlas", 250, 1020, "MongoDB Atlas<br>(PII, confidential)", "atlas-box", None),
)
POS = {n[0]: (n[2], n[3]) for n in _NODES}
MEMBERSHIP = {n[0]: n[5] for n in _NODES}

# --------------------------------------------------------------------------- #
# Hand-pinned edges. Markers are contiguous 1..15 in Flow order. Every route is
# explicit; contacts are grid-resolved fractions (px offset / 78).
# --------------------------------------------------------------------------- #
_ax, _ay = POS["atlas"]  # atlas top-entry x = _ax + 40 (e10) / + 60 (e14)
EDGES = (
    Edge("e13", "waf", "cloudfront", "1", exit=(1.0, fx(40)), entry=(fx(60), 0.0),
         points=((360, 160), (360, 250), (310, 250))),
    Edge("e1", "student", "lms", "2", exit=(fx(40), 1.0256410256410255), entry=(fx(40), 0.0)),
    Edge("e2", "lms", "cloudfront", "3", exit=(1.0256410256410255, fx(40)), entry=(0.0, fx(40))),
    Edge("e3", "cloudfront", "apigw", "4", exit=(1.0256410256410255, fx(40)), entry=(0.0, fx(40))),
    # e4: learner -> CloudFront bypassing the LMS. The engine's approach-lane
    # rule puts the last vertical 30px left of the CloudFront face (x=220), which
    # rode the old account border (x=220); the account box is widened to x=190 so
    # the lane (and marker 5) sit 30px INSIDE the border instead.
    Edge("e4", "student", "cloudfront", "5", dashed=True,
         exit=(1.0256410256410255, fx(60)), entry=(0.0, fx(20)),
         points=((220, 180), (220, 300))),
    Edge("e5", "apigw", "lambda", "6", exit=(1.0256410256410255, fx(40)), entry=(0.0, fx(40))),
    # Lambda -> Atlas (hand-pinned): bottom exits split 0.25 / 0.5 / 0.75
    # (x = 930 / 950 / 970) for e10 / e7 / e9.
    Edge("e10", "lambda", "atlas", "7", exit=(fx(20), 1.0), entry=(fx(40), 0.0),
         points=((930, 440), (_ax + 40, 440), (_ax + 40, _ay))),
    # Lambda right face: e6 0.5 (y=320), e15 0.75 (y=340).
    Edge("e6", "lambda", "batch", "8", dashed=True, exit=(1.0, fx(40)), entry=(0.0, fx(40))),
    # e7: RDS now sits inside the re-drawn se VPC (lower-left); the edge leaves
    # the Lambda bottom, turns left under the Atlas lane and drops into RDS top.
    Edge("e7", "lambda", "rds", "9", exit=(fx(40), 1.0), entry=(fx(40), 0.0),
         points=((950, 470), (800, 470))),
    Edge("e9", "lambda", "secrets", "10", exit=(fx(60), 1.0), entry=(fx(40), 0.0),
         points=((970, 500), (1040, 500), (1040, 720), (1390, 720))),
    # NEW: Lambda -> Bedrock (AI flow).
    Edge("e15", "lambda", "bedrock", "11", exit=(1.0, fx(60)), entry=(fx(40), 0.0),
         points=((1060, 340), (1060, 400), (1170, 400))),
    Edge("e11", "batch", "s3", "12", exit=(1.0, fx(40)), entry=(0.0, fx(40)),
         points=((1230, 320), (1230, 480))),
    # e12: strapi and RDS share the VPC row now -> a straight run.
    Edge("e12", "strapi", "rds", "13", exit=(1.0, fx(40)), entry=(0.0, fx(40))),
    # NEW: Syndicate Server (EC2) -> Atlas (PII). Upper exit / outer lane so it
    # nests with the DIAL edge without crossing it; enters Atlas top at +60.
    Edge("e14", "syndi", "atlas", "14", exit=(1.0, fx(20)), entry=(fx(60), 0.0),
         points=((690, 700), (690, 830), (_ax + 60, 830), (_ax + 60, _ay))),
    # NEW: Syndi -> DIAL AI (external, left of the account); enters DIAL top.
    Edge("e16", "syndi", "dial", "15", exit=(1.0, fx(60)), entry=(fx(40), 0.0),
         points=((670, 740), (670, 810), (POS["dial"][0] + 40, 810))),
)
PINNED = tuple(e.id for e in EDGES)

FLOW = (
    "Flow",
    "1. WAF (global) inspects requests at the CloudFront edge before the origin [no data stored]",
    "2. Learner launches a task from the LMS (LTI); learner PII travels over TLS [PII, TLS]",
    "3. LMS redirects the learner to SEP via CloudFront [PII, TLS]",
    "4. CloudFront (TLS) forwards the request to API Gateway [PII, TLS]",
    "5. Learner also opens the Syndicate UI directly via CloudFront, bypassing the LMS [PII, TLS]",
    "6. API Gateway (TLS) forwards requests to the Lambda handlers [PII, TLS]",
    "7. Lambda reads/writes the PRIMARY learner datastore MongoDB Atlas over VPC peering [PII, confidential, Atlas enc-at-rest NONE]",
    "8. Lambda submits AWS Batch jobs directly; Batch uses its own built-in job queue [internal job metadata]",
    "9. Lambda persists content to RDS sep-strapi-pg (VPC-scoped) [encrypted at rest, KMS CMK in account 088595288622]",
    "10. Lambda reads Secrets / SSM parameters [KMS-encrypted; values never read]",
    "11. Lambda invokes Amazon Bedrock models (AI flow) [confidential; learner text may contain PII; TLS; DRAFT-ASSUMPTION classification]",
    "12. Batch writes task artifacts / verification outputs to S3 [PII, encryption draft-unverified]",
    "13. ECS strapi-server persists Strapi content to RDS sep-strapi-pg [content only, encrypted at rest, KMS]",
    "14. Syndicate Server (EC2) reads/writes learner data in MongoDB Atlas over VPC peering [PII, confidential, Atlas enc-at-rest NONE]",
    "15. Syndi calls the external DIAL AI proxy (ai-proxy.lab.epam.com) outside the account [AI flow; confidential, may contain PII; TLS; DRAFT-ASSUMPTION classification]",
)

CALLOUT_TEXT = (
    "RDS sep-strapi-pg is VPC-scoped (se VPC, DB subnets). Its CMK is "
    "cross-account: the key lives in account 088595288622, "
    "so the KMS encryption boundary spans two accounts (DELTA-2026-10-31, F-5)."
)
CALLOUT = (1050, 770, 250, 110)  # x, y, w, h (inside the Region box, clear of e9 and Secrets)

LEGEND_EXTRA = (
    "callout = explanatory note (RDS VPC scope and cross-account CMK), not a node",
    "WAF (global) protects CloudFront at the edge, outside the region (syndicate_education_cloudfront_waf web ACL)",
    "Classification markers (Flow list, node captions): PII = personal data; confidential/encrypted = data posture",
    "GDPR FINDING (confirmed): MongoDB Atlas holds the primary SEP learner data with encryption-at-rest NONE; written by Lambda (7) and the Syndicate Server (14)",
    "CONFIRMED encryption: RDS strapi-pg StorageEncrypted=True (CMK in account 088595288622); Secrets/SSM via KMS (6 keys)",
    "DRAFT-ASSUMPTION (inventory silent): S3 default encryption + DynamoDB SSE drawn as encrypted draft-unverified; PII scope of se-* buckets assumed from naming",
    "DRAFT-ASSUMPTION: classification of the AI flows (Bedrock 11, DIAL 15) assumed (learner text may contain PII); content of prompts not inspected",
    "DynamoDB CiTerraformStateLocks = Terraform CI state locks (operational, non-PII); not written by Lambda",
    "Data residency: AWS eu-central-1 + MongoDB Atlas EU_CENTRAL_1 (Frankfurt); DIAL AI proxy location unconfirmed",
    "Source: inventory 2026-10-31 storage/database/secrets/ai + INVENTORY-STATE.md section 3 (Atlas)",
)

ACCOUNT_CAPTION = ("SEP — AWS 870325637521 / eu-central-1 "
                   "(in-region data; KMS boundary, RDS CMK cross-account — see note)")
CAPTIONS = {
    "boundary-account": ACCOUNT_CAPTION,
    "boundary-region-a": "Region eu-central-1 — regional managed data stores",
    "boundary-vpc-a": "se VPC (192.168.128.0/20)",
    "atlas-box": ("External encryption boundary — MongoDB Atlas (EU_CENTRAL_1, "
                  "Atlas-managed account, VPC-peered; NO Atlas enc-at-rest)"),
}


def _callout_cell() -> str:
    x, y, w, h = CALLOUT
    return (
        f'        <mxCell id="callout-rds-kms" value="{CALLOUT_TEXT}" '
        'style="text;html=1;whiteSpace=wrap;overlay=callout;kiroAnnotation=1;'
        'fillColor=#FFF7E6;strokeColor=#D79B00;fontColor=#000000;fontSize=12;'
        'align=left;verticalAlign=top;spacingLeft=10;spacingRight=10;'
        'spacingTop=10;spacingBottom=10" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />\n'
        "        </mxCell>\n"
    )


def build() -> str:
    nodes: List[Node] = [
        Node(id=nid, label=cap, x=x, y=y, render=_renderer(role), overlay=ov)
        for nid, role, x, y, cap, _host, ov in _NODES
    ]
    boundaries = [
        Boundary(id="boundary-account", label=CAPTIONS["boundary-account"],
                 x=190, y=80, w=1330, h=850, style=AWS_CONTAINERS["boundary"], kind="account"),
        Boundary(id="boundary-region-a", label=CAPTIONS["boundary-region-a"],
                 x=440, y=198, w=1060, h=700, style=AWS_CONTAINERS["region"], kind="region"),
        Boundary(id="boundary-vpc-a", label=CAPTIONS["boundary-vpc-a"],
                 x=470, y=500, w=470, h=360, style=AWS_CONTAINERS["network_boundary"], kind="vpc"),
        Boundary(id="atlas-box", label=CAPTIONS["atlas-box"],
                 x=190, y=960, w=1330, h=198, style=ATLAS_BOX_STYLE, kind="external_cloud"),
    ]
    legend_x = 1660
    legend_w = 280
    legend_lines = (list(legend_lines_for(boundaries)) + list(overlay_legend_lines(nodes))
                    + list(LEGEND_EXTRA))
    xml = build_diagram(
        diagram_id="aws-sep-dataflow",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=list(EDGES),
        flow_lines=FLOW,
        legend_x=legend_x,
        legend_w=legend_w,
        legend_lines=legend_lines,
        page_w=2000,
        page_h=1218,
        skin=NATIVE_SKIN,
        membership=MEMBERSHIP,
        respect_pins=True,
        pinned_ids=PINNED,
    )
    return xml.replace("      </root>", _callout_cell() + "      </root>", 1)


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
