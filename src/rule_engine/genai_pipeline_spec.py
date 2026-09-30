"""Coordinate-free declaration of the GenAI pipeline example (gcp/01, oci/01).

The GCP *vertex-pipeline* and the OCI *genai-stack* are the same workload: an
API front door and a load balancer route inference to an LLM hub; an async
stream feeds an ingest function that submits training jobs to managed
Kubernetes; the hub reads a SQL store, writes an object store and reads a
secrets store. Until 1.10.3 each provider hand-placed the nine nodes with its own
coordinate literals, so the two copies could (and did) drift, and neither obeyed
service scope — the queue, function, hub, secrets and object store were drawn
inside the VPC/VCN.

This spec is the single source: ``layout()`` computes every coordinate, both
providers share byte-identical geometry (only icons, labels and container styles
differ), and the regional services land in the regional column outside the
network boundary (REVIEW.md D20).
"""

from __future__ import annotations

try:  # package-relative when imported as rule_engine.genai_pipeline_spec
    from .layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec
except ImportError:  # pragma: no cover - flat-module fallback
    from layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec  # type: ignore[no-redef]

__all__ = ["GENAI_SPEC", "GENAI_NODE_IDS", "genai_spec"]


def genai_spec(*, api_global: bool) -> DiagramSpec:
    """Return the GenAI pipeline spec with the API front door placed by scope.

    ``api_global=True`` (OCI): the API Gateway is a **global/edge** service, so it
    sits in the account edge row outside the region — the default. ``False``
    (GCP): Apigee is a **regional** product, so the front door sits inside the
    region, in the regional column, like the other regional managed services.
    Everything else in the spec is identical, so the two providers still share
    the whole body of the layout; only the ``api`` node's region/container
    differ. This is the one place the two provider diagrams legitimately diverge
    (provider-profiles → service scope: OCI API GW global vs GCP Apigee regional).
    """
    if api_global:
        nodes = _NODES
    else:
        # Apigee is regional: the API front door joins the regional column. That
        # shifts the clean layout, so the network sub-rows and regional slots are
        # re-picked for a fully warning-clean route (searched over the engine's
        # own checks — no corridor-sharing / container-crossing / caption
        # findings). sql on the main VPC row, train one sub-row down; regional
        # order sec, obj, queue; api at the top of the regional column.
        _regional_api = {
            "api": dict(region="a", slot=1, sub=0, container="region-a"),
            "lb": dict(sub=0), "train": dict(sub=2), "sql": dict(sub=1),
            "sec": dict(slot=2), "obj": dict(slot=3), "queue": dict(slot=4),
        }  # fully warning-clean (searched over the engine's own checks, D23)
        nodes = tuple(
            _apply(n, _regional_api[n.id]) if n.id in _regional_api else n
            for n in _NODES
        )
    return DiagramSpec(
        diagram_id="genai-pipeline", diagram_name="genai-pipeline",
        axis="north-south", nodes=nodes, edges=_EDGES, containers=_CONTAINERS,
        flow_lines=(), title="genai-pipeline",
    )


def _apply(node: NodeSpec, changes: dict) -> NodeSpec:
    import dataclasses as _dc
    return _dc.replace(node, **changes)


_NODES = (
    # Front door: account-level edge row, outside the region (OCI global default).
    NodeSpec(id="api", role="api", lane="edge", region="", slot=0),
    # Network-scoped: inside the VPC / VCN.
    NodeSpec(id="lb", role="lb", lane="router", region="a", slot=0, sub=1, container="vpc-a"),
    NodeSpec(id="train", role="k8s", lane="workers", region="a", slot=0, sub=1, container="vpc-a"),
    NodeSpec(id="sql", role="sql", lane="data", region="a", slot=0, sub=2, container="vpc-a"),
    # Regional managed services: inside the region, outside the network. The
    # unanchored ones stack by ``slot`` (queue, secrets, object store), so the
    # api→queue feed stays at the top of the column, clear of the hub's fan-out.
    NodeSpec(id="queue", role="queue", lane="async", region="a", slot=3, container="region-a"),
    NodeSpec(id="ingest", role="fn", lane="workers", region="a", slot=1, container="region-a"),
    NodeSpec(id="hub", role="llm_platform", lane="platform", region="a", slot=0, container="region-a"),
    NodeSpec(id="sec", role="sec", lane="platform", region="a", slot=4, container="region-a"),
    NodeSpec(id="obj", role="obj", lane="data", region="a", slot=2, container="region-a"),
)

_EDGES = (
    EdgeSpec(id="e1", source="api", target="lb", marker="1"),
    EdgeSpec(id="e2", source="lb", target="hub", marker="2"),
    EdgeSpec(id="e3", source="api", target="queue", marker="3", dashed=True),
    EdgeSpec(id="e4", source="queue", target="ingest", marker="4", dashed=True),
    EdgeSpec(id="e5", source="ingest", target="train", marker="5"),
    EdgeSpec(id="e6", source="train", target="hub", marker="6"),
    EdgeSpec(id="e7", source="hub", target="sql", marker="7"),
    EdgeSpec(id="e8", source="hub", target="obj", marker="8"),
    EdgeSpec(id="e9", source="hub", target="sec", marker="9"),
)

_CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
    ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
    ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
)

GENAI_NODE_IDS = tuple(n.id for n in _NODES)

GENAI_SPEC = DiagramSpec(
    diagram_id="genai-pipeline",
    diagram_name="genai-pipeline",
    axis="north-south",
    nodes=_NODES,
    edges=_EDGES,
    containers=_CONTAINERS,
    flow_lines=(),  # provider skins supply the service-named Flow text
    title="genai-pipeline",
)
