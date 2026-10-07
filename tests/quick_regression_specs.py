"""Anonymised quick-run specs — layout-engine regression fixtures (hotfix 1.10.7).

The 1.10.0 quick run (a live serverless account: EventBridge → Lambda → S3 →
Glue → Athena → Amazon Quick) produced a ``flow`` summary and a ``landscape``
as-built through ``layout()`` + ``build_diagram()``. The 1.10.6 engine could not
lay that landscape out at all (``LayoutError`` on the original spec and on every
corrected variant), so these specs pin the regression: ``layout()`` must return
a diagram for both, deterministically, with the account box wrapping only the
in-account nodes.

The node / edge / flow declarations are copied from the run's
``tools/build_architecture_diagrams.py`` with the customer name replaced
by ``Acme`` and the account id replaced by ``123456789012``.

* :data:`SUMMARY` — the 11-node flow summary (``compact=True``, left → right).
* :data:`LANDSCAPE` — the 28-node as-built exactly as the agent declared it
  (``compact=False``, North–South, slots with gaps, AWS-operated source APIs in
  the ``on-premises`` lane).
* :data:`LANDSCAPE_CONFORMANT` — the same as-built written the way the 1.10.7
  SKILL guidance (M7) asks: every external source / recipient in the ``actors``
  lane, IAM roles and the CloudFormation stack dropped as data-flow nodes. Slots
  stay as declared (gaps included); account-only compaction (M4) closes them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping, Sequence, Tuple

import yaml

from rule_engine.diagram_layout import Node, build_diagram
from rule_engine.draw_cli import _boundaries_from, _edges_from, _node_renderer, _page_size
from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

REPO_ROOT = Path(__file__).resolve().parents[1]

ACCOUNT = "123456789012"
REGION = "us-east-1"
DATE = "2026-10-06"
VERSION = "v6"
ACCOUNT_CAPTION = f"AWS account {ACCOUNT} / {REGION}"
EXTERNAL_LANES = frozenset({"actors", "on-premises"})

# Role aliases the quick builder used → the mapping keys.
_ROLE = {"fn": "serverless_fn", "queue": "message_queue", "obj": "object_store"}

Declared = Tuple[NodeSpec, str]


def _n(id: str, role: str, lane: str, slot: int, label: str) -> Declared:
    return (NodeSpec(id=id, role=_ROLE.get(role, role), lane=lane, region="", slot=slot), label)


# --------------------------------------------------------------------------- #
# Summary (flow, <= 12 nodes)
# --------------------------------------------------------------------------- #
SUMMARY_NODES: Tuple[Declared, ...] = (
    _n("src_partner", "external_aws_api", "actors", 1, "Partner + Marketplace APIs"),
    _n("src_sb", "external_aws_api", "actors", 2, "Skill Builder IR API"),
    _n("src_manual", "manual_feed", "actors", 3, "Manual exports"),
    _n("sched", "event_bus", "router", 0, "EventBridge schedules"),
    _n("etl", "fn", "workers", 1, "QuickPartnerETL"),
    _n("alerts", "notification_topic", "workers", 2, "SNS quick-etl-alerts"),
    _n("lake", "obj", "data", 3, "S3 data lake"),
    _n("glue", "data_catalog", "data", 4, "Glue catalog"),
    _n("athena", "query_engine", "data", 5, "Athena latest views"),
    _n("quick", "bi_platform", "data", 6, "Amazon Quick"),
    _n("users", "end_users", "on-premises", 6, "Quick users"),
)
SUMMARY_EDGES: Tuple[Tuple[str, str, str], ...] = (
    ("sched", "etl", "1"), ("src_partner", "etl", "2"), ("src_sb", "etl", "3"),
    ("etl", "lake", "4"), ("src_manual", "lake", "5"), ("lake", "glue", "6"),
    ("glue", "athena", "7"), ("athena", "quick", "8"), ("quick", "users", "9"),
    ("etl", "alerts", "10"),
)
SUMMARY_FLOW: Tuple[str, ...] = (
    "Flow",
    "1. EventBridge: hourly opportunities, 10:00 daily datasets, 11:00 Skill Builder",
    "2. Partner Central Selling + Benefits, Marketplace Catalog APIs",
    "3. Skill Builder IR V3: 11 async SigV4 queries, 4 in flight, dedup on write",
    "4. NDJSON per dataset in daily dt=YYYY-MM-DD partitions",
    "5. Operator uploads certifications (NDJSON) and Payee Central invoices (CSV)",
    "6. Lambda registers the partition and re-pins TABLE_latest views",
    "7. 22 typed _latest views; WG quick-partner-data, 1 GB cutoff",
    "8. 22 typed DIRECT_QUERY datasets; all 4 groups see all columns",
    "9. Topics Acme data + Skill Builder, agent Partner Data Analyst",
    "10. EMF metrics, 7 CloudWatch alarms, SNS e-mail",
)
SUMMARY_DASHED = frozenset({"10"})

# --------------------------------------------------------------------------- #
# Landscape (as-built, every enumerated resource)
# --------------------------------------------------------------------------- #
LANDSCAPE_NODES: Tuple[Declared, ...] = (
    _n("manual", "manual_feed", "actors", 0, "Manual exports"),
    _n("users", "end_users", "actors", 1, "Quick users + groups"),
    _n("idc", "identity_provider", "actors", 9, "Identity Center SSO"),
    _n("rule_hourly", "event_bus", "router", 3, "Rule hourly opportunities"),
    _n("rule_sb", "event_bus", "router", 4, "Rule Skill Builder 11:00"),
    _n("stack", "iac_stack", "router", 5, "CFN QuickPartnerIntegration"),
    _n("rule_daily", "event_bus", "router", 6, "Rule daily 10:00"),
    _n("dlq", "queue", "async", 2, "SQS EventBridge DLQ"),
    _n("sns", "notification_topic", "async", 6, "SNS quick-etl-alerts"),
    _n("etl", "fn", "workers", 1, "Lambda QuickPartnerETL"),
    _n("logs", "monitoring", "workers", 2, "CloudWatch logs + metrics"),
    _n("etl_role", "iam_role", "workers", 3, "QuickPartnerETL-LambdaRole"),
    _n("alarms", "alarm", "workers", 4, "7 CloudWatch alarms"),
    _n("lake", "obj", "platform", 1, "S3 data lake"),
    _n("glue", "data_catalog", "platform", 2, "Glue quick_partner_data"),
    _n("athena", "query_engine", "platform", 3, "Athena WG quick-partner-data"),
    _n("results", "obj", "platform", 4, "S3 Athena results"),
    _n("qs_role", "iam_role", "platform", 5, "QuickSight data roles"),
    _n("qs_ds", "bi_platform", "platform", 6, "Datasource partner-data-athena"),
    _n("qs_sets", "bi_platform", "platform", 9, "22 DIRECT_QUERY datasets"),
    _n("topic_acme", "bi_platform", "platform", 10, "Topic Acme data"),
    _n("topic_sb", "bi_platform", "platform", 11, "Topic Skill Builder"),
    _n("space", "bi_platform", "platform", 12, "Space Acme Data"),
    _n("qs_acct", "bi_platform", "platform", 13, "Quick account acme-apn"),
    _n("mp_catalog", "marketplace_api", "on-premises", 1, "Marketplace Catalog API"),
    _n("pc_api", "external_aws_api", "on-premises", 2, "Partner Central APIs"),
    _n("operator", "end_users", "on-premises", 6, "ETL operator e-mail"),
    _n("sb_ir", "external_aws_api", "on-premises", 11, "Skill Builder IR V3"),
)
LANDSCAPE_EDGES: Tuple[Tuple[str, str, str], ...] = (
    ("rule_hourly", "etl", "1"),
    ("rule_daily", "etl", "2"),
    ("rule_sb", "etl", "3"),
    ("rule_sb", "dlq", "4"),
    ("etl", "pc_api", "5"),
    ("etl", "mp_catalog", "6"),
    ("etl", "sb_ir", "7"),
    ("manual", "lake", "8"),
    ("etl", "etl_role", "9"),
    ("etl", "lake", "10"),
    ("lake", "glue", "11"),
    ("etl", "logs", "12"),
    ("logs", "alarms", "13"),
    ("alarms", "sns", "14"),
    ("stack", "etl_role", "15"),
    ("glue", "athena", "16"),
    ("lake", "athena", "17"),
    ("athena", "results", "18"),
    ("qs_role", "qs_ds", "19"),
    ("athena", "qs_ds", "20"),
    ("qs_ds", "qs_sets", "21"),
    ("qs_sets", "topic_acme", "22"),
    ("topic_acme", "space", "23"),
    ("topic_sb", "space", "24"),
    ("qs_acct", "qs_ds", "25"),
    ("idc", "qs_acct", "26"),
    ("users", "space", "27"),
    ("sns", "operator", "28"),
)
LANDSCAPE_FLOW: Tuple[str, ...] = (
    "Flow",
    "1. rate(1 hour): opportunities (incremental)",
    "2. cron 10:00 UTC: 8 Partner/Marketplace/Benefits datasets",
    "3. cron 11:00 UTC: 11 Skill Builder datasets",
    "4. undeliverable events (all 3 rules) to DLQ, 14 d",
    "5. pull: Selling (opportunities, engagements, solutions) + Benefits",
    "6. pull: ListEntities for 5 product types, Solution, Offer",
    "7. pull: StartReportQuery / DescribeReportQuery (SigV4)",
    "8. operator: certifications data.json, invoices data.csv",
    "9. execution role: 2 inline policies (extraction + view DDL)",
    "10. NDJSON dt= partitions + Glue partition + _latest view re-pin",
    "11. partitions catalogued; lifecycle 90 d (manual feeds kept)",
    "12. logs 365 d + EMF metrics (namespace QuickPartnerETL)",
    "13. Errors, Duration, Failures, Skipped, NoRuns, 2x ManualFeedStale",
    "14. ALARM and OK notifications",
    "15. stack owns all infra (drift IN_SYNC 2026-10-06)",
    "16. 22 tables + 22 typed _latest views (+11 sb_*_history)",
    "17. Quick queries: WG quick-partner-data, 1 GB per-query cutoff",
    "18. query results, 7-day lifecycle",
    "19. datasource uses QuickSight service roles for Athena / Glue / S3",
    "20. DIRECT_QUERY on TABLE_latest views",
    "21. 22 datasets on one Athena datasource",
    "22. topic Acme data: 10 datasets, 3 relations; open to all 4 groups",
    "23. topics + agent Partner Data Analyst in space Acme Data",
    "24. topic Skill Builder: 10 datasets, 8 relations on learner_key",
    "25. Enterprise edition, us-east-1",
    "26. SSO: Identity Center, SCIM from Entra ID",
    "27. ask questions in the space / Quick chat",
    "28. alert e-mail",
)
LANDSCAPE_DASHED = frozenset({"4", "14", "28"})

# M7-conformant rewrite of the landscape.
_TO_ACTORS = ("mp_catalog", "pc_api", "sb_ir", "operator")
_NOT_DATA_FLOW = frozenset({"etl_role", "qs_role", "stack"})
_DROPPED_MARKERS = frozenset({"9", "15", "19"})


def _conformant_nodes() -> Tuple[Declared, ...]:
    """Move the external nodes to ``actors`` and drop the IAM/CFN nodes.

    Slots stay as declared. Where a moved node's declared slot is already taken
    in ``actors`` (``mp_catalog`` and ``users`` both declare slot 1) it takes the
    next free slot, in declaration order, so the (lane, slot) key stays unique."""
    kept = [(s, lab) for s, lab in LANDSCAPE_NODES if s.id not in _NOT_DATA_FLOW]
    taken = {s.slot for s, _ in kept if s.lane == "actors" and s.id not in _TO_ACTORS}
    out = []
    for s, lab in kept:
        if s.id in _TO_ACTORS:
            slot = s.slot
            while slot in taken:
                slot += 1
            taken.add(slot)
            s = NodeSpec(id=s.id, role=s.role, lane="actors", region="", slot=slot)
        out.append((s, lab))
    return tuple(out)


LANDSCAPE_CONFORMANT_NODES = _conformant_nodes()
LANDSCAPE_CONFORMANT_EDGES = tuple(e for e in LANDSCAPE_EDGES if e[2] not in _DROPPED_MARKERS)
LANDSCAPE_CONFORMANT_FLOW = ("Flow",) + tuple(
    line for line in LANDSCAPE_FLOW[1:] if line.split(".", 1)[0] not in _DROPPED_MARKERS
)


# --------------------------------------------------------------------------- #
# Spec construction
# --------------------------------------------------------------------------- #


def _spec(name: str, nodes: Sequence[Declared], edges, flow, dashed, *, axis: str,
          compact: bool) -> DiagramSpec:
    return DiagramSpec(
        diagram_id=name,
        diagram_name=name,
        axis=axis,
        nodes=tuple(s for s, _ in nodes),
        edges=tuple(
            EdgeSpec(id=f"e{m}", source=a, target=b, marker=m, dashed=m in dashed)
            for a, b, m in edges
        ),
        containers=(ContainerSpec(id="boundary-account", kind="account", region="",
                                  parent=None, label_key="account"),),
        flow_lines=tuple(flow),
        title=name,
        compact=compact,
        node_labels=tuple((s.id, lab) for s, lab in nodes),
    )


SUMMARY = _spec("quick-summary", SUMMARY_NODES, SUMMARY_EDGES, SUMMARY_FLOW,
                SUMMARY_DASHED, axis="left-right", compact=True)
LANDSCAPE = _spec("quick-landscape", LANDSCAPE_NODES, LANDSCAPE_EDGES, LANDSCAPE_FLOW,
                  LANDSCAPE_DASHED, axis="north-south", compact=False)
LANDSCAPE_CONFORMANT = _spec(
    "quick-landscape-conformant", LANDSCAPE_CONFORMANT_NODES, LANDSCAPE_CONFORMANT_EDGES,
    LANDSCAPE_CONFORMANT_FLOW, LANDSCAPE_DASHED, axis="north-south", compact=False,
)

SUMMARY_LABELS: Dict[str, str] = {s.id: lab for s, lab in SUMMARY_NODES}
LANDSCAPE_LABELS: Dict[str, str] = {s.id: lab for s, lab in LANDSCAPE_NODES}

SUMMARY_TITLE = f"aws Quick Partner Data flow summary — {ACCOUNT} / {REGION} | {DATE} | {VERSION}"
LANDSCAPE_TITLE = (
    f"aws Quick Partner Data as-built landscape — {ACCOUNT} / {REGION} | {DATE} | {VERSION}"
)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _aws_styles() -> Dict[str, str]:
    mapping = yaml.safe_load((REPO_ROOT / "mappings" / "aws-icons.yaml").read_text(encoding="utf-8"))
    styles = {k: v["style"] for k, v in (mapping.get("resources") or {}).items()}
    styles.update({k: v["style"] for k, v in (mapping.get("presentation") or {}).items()})
    return styles


def render(spec: DiagramSpec, labels: Mapping[str, str], title: str) -> str:
    """Lay ``spec`` out and serialise it to ``.drawio`` text, as the quick run did.

    Node styles come from ``mappings/aws-icons.yaml``. The quick run's own roles
    (``event_bus``, ``data_catalog``, ``bi_platform``, …) live in that
    workspace's edited mapping, not in the repository's, so a role the
    repository mapping lacks is drawn with the ``serverless_fn`` style. That is
    a **geometry-neutral test stand-in, not an icon choice**: every node is one
    78×78 cell whatever its glyph, and these fixtures exercise layout, not icon
    fidelity. Boundaries, edges and the Legend go through the same helpers
    ``rule-engine-draw`` uses; nothing is moved after ``layout()``.
    """
    placed = layout(spec)
    styles = _aws_styles()
    fallback = styles["serverless_fn"]
    nodes = [
        Node(
            id=n.id,
            label=labels[n.id],
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=_node_renderer(styles.get(n.role, fallback)),
        )
        for n in spec.nodes
    ]
    boundaries = _boundaries_from(placed, "aws", {"boundary-account": ACCOUNT_CAPTION})
    page_w, page_h = _page_size(placed)
    return build_diagram(
        diagram_id=spec.diagram_id,
        diagram_name=spec.diagram_name,
        title=title,
        boundaries=boundaries,
        nodes=nodes,
        edges=_edges_from(placed),
        flow_lines=spec.flow_lines,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        page_w=page_w,
        page_h=page_h,
    )
