#!/usr/bin/env python3
"""E-06 spec template — a **network** topology diagram (``diagram_type: network``).

A network diagram is a Network_Diagram (``diagram-lint.md`` -> ``ip-range``):
ingress at the top, internal networks descending, with real cloud boundaries
(account -> region -> VPC) and real provider icons. This template uses the AWS
profile; swap the provider string and the role icons resolve from that profile's
mapping instead -- the geometry never forks.

Unlike the Context / C4 templates, this one resolves **real provider glyphs**
from the committed icon mappings via :func:`icon_resolver.resolve_icon`, so a
node is drawn with its official AWS icon rather than a neutral box. VPC-scoped
roles (``compute_instance``, ``lb``) declare the VPC container; a regional role
(``object_store``) declares the region container, so the engine places it
outside the Network Boundary by scope (and FEAT-001's ``scope-placement`` lint
is satisfied). Run it::

    python examples/spec_templates/build_network.py            # writes a temp triple
    python examples/spec_templates/build_network.py --out net.drawio
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rule_engine.diagram_layout import image_icon  # noqa: E402
from rule_engine.icon_resolver import resolve_container, resolve_icon  # noqa: E402
from rule_engine.layout.model import (  # noqa: E402
    ContainerSpec,
    DiagramSpec,
    EdgeSpec,
    NodeSpec,
)

from _common import companion_md, run_template  # noqa: E402

_PROVIDER = "aws"

# ---------------------------------------------------------------------------
# Account -> Region -> VPC. An internet gateway is the ingress at the edge; a
# load balancer and a compute instance are VPC-scoped (inside the VPC); an
# object store is a regional managed service (inside the region, OUTSIDE the
# VPC). The engine places each by its role scope and the declared container.
# ---------------------------------------------------------------------------
_NODES = (
    NodeSpec(id="igw", role="internet_gateway", lane="edge", region="a", slot=0, container="region-a"),
    NodeSpec(id="alb", role="lb", lane="router", region="a", slot=0, container="vpc-a"),
    NodeSpec(id="ec2", role="compute_instance", lane="workers", region="a", slot=0, container="vpc-a"),
    NodeSpec(id="bucket", role="object_store", lane="data", region="a", slot=0, container="region-a"),
)
_EDGES = (
    EdgeSpec(id="e1", source="igw", target="alb", marker="1"),
    EdgeSpec(id="e2", source="alb", target="ec2", marker="2"),
    EdgeSpec(id="e3", source="ec2", target="bucket", marker="3"),
)
_CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
    ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
    ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
)

_LABELS = {
    "igw": "internet-gateway",
    "alb": "app-load-balancer",
    "ec2": "app-instance",
    "bucket": "artifact-store",
}
_CONTAINER_LABELS = {
    "account": "Account 123456789012",
    "region-a": "region us-east-1",
    "vpc-a": "VPC app-vpc (10.0.0.0/16)",
}
_FLOW = (
    "Flow",
    "1. Internet gateway admits traffic to the load balancer",
    "2. Load balancer forwards to the application instance",
    "3. Application instance writes to the regional object store",
)

SPEC = DiagramSpec(
    diagram_id="network-template",
    diagram_name="network-template",
    axis="north-south",
    nodes=_NODES,
    edges=_EDGES,
    containers=_CONTAINERS,
    flow_lines=_FLOW,
    title="aws network-template — 123456789012 / us-east-1 | 2026-01-01 | v1",
    node_labels=tuple(_LABELS.items()),
)

_OVERVIEW = (
    "This template produces a network topology diagram for the AWS profile: a "
    "Network_Diagram with real cloud boundaries and official provider icons. It "
    "shows an account containing one region, which contains one VPC. The ingress "
    "is an internet gateway at the edge; inside the VPC an application load "
    "balancer forwards to a compute instance; and a regional object store sits "
    "inside the region but outside the VPC, because an object store is a "
    "regional managed service reached over the backbone rather than a "
    "VPC-scoped resource. The diagram therefore demonstrates correct service "
    "scope placement: VPC-scoped resources inside the Network Boundary, regional "
    "services inside the account but outside it. Because the VPC caption carries "
    "a reserved documentation address range, the Network_Diagram ip-range rule "
    "is satisfied and no routable public address leaks into the drawing here."
)
_MAIN = (
    "Each node declares a lane, a region, and a slot, plus the container it "
    "belongs to; the engine derives every coordinate and sizes every boundary "
    "with padding, so the template writes no x or y. The internet gateway and "
    "the object store declare the region container, so the engine draws them in "
    "the regional column outside the VPC; the load balancer and the compute "
    "instance declare the VPC container, so they sit inside the Network "
    "Boundary. Three numbered edges carry the flow down the North-South axis: "
    "the gateway admits traffic to the load balancer, the load balancer forwards "
    "to the instance, and the instance writes to the object store. Each node "
    "resolves its icon from the committed AWS mapping through the icon resolver, "
    "so no glyph is hand-written and none is a look-alike. Change the provider "
    "string at the top and the same spec resolves each role against that "
    "profile, with the identical placement and routing geometry."
)
_TROUBLE = (
    "If the Linter reports an icon-resolved error, a node style points at an "
    "image path that does not resolve; confirm the role is in the AWS mapping "
    "and the icon index is current, and never hand-write a shape id. A "
    "scope-placement finding means a node sits in the wrong boundary for its "
    "scope; a VPC-scoped role belongs in the VPC container and a regional role "
    "in the region container, exactly as declared above. An ip-range warning "
    "means a routable public address appears in the on-diagram text; use a "
    "reserved documentation or private range, as the VPC caption does here. A "
    "container-padding finding means a node is too close to a boundary edge; "
    "regenerate rather than nudge, since the layout is deterministic. For a "
    "verify-icon failure, fetch the AWS asset pack so the resolved SVG file path "
    "exists, since the committed source references the icon by file path."
)
_SEE_ALSO = (
    "This template pairs with the Context, C4 Container, and component "
    "templates in this directory, which use neutral C4 boxes rather than cloud "
    "icons. The README maps every diagram_type to its template and to the "
    "relevant steering sections. The service scope rules this diagram "
    "demonstrates are defined in provider-profiles under Service Scope "
    "Classification and in diagram-standards under Service Scope Placement. The "
    "North-South orientation, the lane order, and the container nesting and "
    "padding rules are defined in the diagram standards steering document. The "
    "ip-range rule, the scope-placement rule, and the class-aware severities "
    "that judge this diagram are defined in the diagram lint ruleset, and the "
    "frontmatter contract this companion satisfies is in the knowledge-base "
    "frontmatter steering rules. For a larger as-built, author a landscape and "
    "cross-link a flow summary, as the HA multi-region golden pair does today."
)

COMPANION = companion_md(
    basename="network-template",
    diagram_type="network",
    diagram_class="flow",
    title="aws network-template",
    overview=_OVERVIEW,
    main=_MAIN,
    trouble=_TROUBLE,
    see_also=_SEE_ALSO,
    tags=("aws", "network", "topology", "spec-template"),
)


def main(argv=None) -> int:
    # Resolve each node's official icon renderer from the committed mapping.
    renderers = {}
    for n in SPEC.nodes:
        style = resolve_icon(n.role, _PROVIDER)["style_string"]
        # resolve_icon returns a full image style; extract the image path for
        # image_icon, which re-wraps it with the canonical label tokens.
        path = style.split("image=", 1)[1]
        renderers[n.id] = image_icon(path)
    container_styles = {
        "account": resolve_container("boundary", _PROVIDER)["style_string"],
        "region-a": resolve_container("region", _PROVIDER)["style_string"],
        "vpc-a": resolve_container("network_boundary", _PROVIDER)["style_string"],
    }
    return run_template(
        prog="build_network",
        spec=SPEC,
        renderers=renderers,
        labels=_LABELS,
        container_labels=_CONTAINER_LABELS,
        container_styles=container_styles,
        companion=COMPANION,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
