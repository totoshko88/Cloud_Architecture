"""1.13.0 E-VPCFIT: re-wrap a VPC band around its AZ children after width-equalize.

``size_containers`` sizes each VPC band around its AZ children, THEN
``_equalize_peer_widths`` widens the narrower peer AZ outward to match its
sibling. When one region's content is wider than the other (a multi-node VPC
service row widening region a), equalize grows the region-b AZ a few pixels past
the VPC that was already sized to the narrower region-b AZ, so the VPC no longer
wraps it (``container-overlap``). The E-VPCFIT pass re-wraps every non-account,
non-az band around its (now equalized) children before the account is sized.

Golden-safe: where the peer AZs already match (every shipped HA golden), equalize
is a no-op and the re-wrap reproduces the same box — locked by the corpus
byte-identical guard in ``make examples-check``. Here we assert the structural
property directly: after layout, every VPC band encloses all its AZ children.
"""

from __future__ import annotations

from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec


def _asymmetric_vpc_spec() -> DiagramSpec:
    """Account ⊃ VPC ⊃ { az-a (3 subnet tiers) | az-b (1 subnet tier) } with a
    two-node VPC service row widening region a — the SEP shape that exposed the
    pre-E-VPCFIT overflow."""
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="vpc", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ContainerSpec(id="az-a", kind="az", region="a", parent="vpc", label_key="az_a"),
        ContainerSpec(id="sa1", kind="subnet", region="a", parent="az-a", label_key="s"),
        ContainerSpec(id="sa2", kind="subnet", region="a", parent="az-a", label_key="s"),
        ContainerSpec(id="az-b", kind="az", region="b", parent="vpc", label_key="az_b"),
        ContainerSpec(id="sb1", kind="subnet", region="b", parent="az-b", label_key="s"),
    )
    nodes = (
        # Two VPC-direct service-row nodes (region a) -> widen region a.
        NodeSpec(id="igw", role="internet_gateway", lane="edge", region="a", slot=0, container="vpc"),
        NodeSpec(id="nat", role="nat_gateway", lane="edge", region="a", slot=1, container="vpc"),
        # az-a private tiers.
        NodeSpec(id="app-a", role="compute_instance", lane="workers", region="a", slot=0, container="sa1"),
        NodeSpec(id="db-a", role="managed_sql", lane="data", region="a", slot=0, container="sa2"),
        # az-b single tier.
        NodeSpec(id="db-b", role="managed_sql", lane="data", region="b", slot=0, container="sb1"),
    )
    edges = (
        EdgeSpec(id="e1", source="app-a", target="db-a", marker="1"),
        EdgeSpec(id="e2", source="app-a", target="db-b", marker="2"),
    )
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. a", "2. b"),
        title="aws t — 1 / r | 2026-10-23 | v1",
    )


def test_vpc_wraps_equalized_az_children():
    placed = layout(_asymmetric_vpc_spec(), strict=False)
    vpc = placed.containers["vpc"]
    for az in ("az-a", "az-b"):
        box = placed.containers[az]
        assert box.x >= vpc.x - 0.5, (az, box.x, vpc.x)
        assert box.x + box.w <= vpc.x + vpc.w + 0.5, (
            f"{az} right {box.x + box.w} past vpc right {vpc.x + vpc.w}")
        assert box.y + box.h <= vpc.y + vpc.h + 0.5, (
            f"{az} bottom past vpc bottom")
    # And no container-overlap finding between the VPC and either AZ.
    overlaps = [w for w in placed.layout_warnings
                if "container-overlap" in str(w) and "vpc" in str(w)]
    assert overlaps == [], overlaps
