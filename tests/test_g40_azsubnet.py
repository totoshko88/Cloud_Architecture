"""G40 (1.12.0) — the AWS AZ + subnet-tier nested container CORE.

These tests exercise the one remaining deferred piece of the Wave-8 engine work
(wave8-engine-design-r3.md PART 1, the LOCKED model): a real ``az`` box per
engine region (side-by-side East-West) wrapping the four AWS subnet tiers, which
are the new **banded leaf kind** stacked North-South. Depth 5.

The model is additive + default-inert: no shipped golden declares a ``subnet`` /
``public_subnet`` container, so every golden stays byte-identical
(``tests/test_golden_examples.py`` is the named golden-safety anchor; the four
HA landscapes nest ``az`` boxes at depth 5 unchanged).
"""

from __future__ import annotations

import pytest

from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import (
    DiagramGeometry,
    check_container_overlap,
    check_container_padding,
    check_geometric_containment,
    check_scope_placement,
)
from rule_engine import icon_resolver
from rule_engine.layout import layout
from rule_engine.layout.base import (
    BANDED_KINDS,
    CONTAINER_PAD,
    SpecError,
    _subnet_ordinals,
)
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec


# --------------------------------------------------------------------------- #
# Spec builders (coordinate-free — only (lane, region, slot) + containers).
# --------------------------------------------------------------------------- #

#: The four subnet tiers inside one AZ, in the canonical declaration order the
#: build script must use (public → private-app → private-batch → isolated-db).
_TIERS = (
    ("public", "public_subnet"),
    ("app", "subnet"),
    ("batch", "subnet"),
    ("db", "subnet"),
)


def _subnet_spec(nodes_per_tier=1, regions=("a", "b")) -> DiagramSpec:
    """account ⊃ vpc ⊃ {az-a, az-b} ⊃ 4 subnet tiers, one AZ per region.

    Each subnet tier holds ``nodes_per_tier`` ``scope='network'`` nodes. The VPC
    is declared in region 'a' and wraps both AZ regions by geometry (the locked
    model); az-a is region 'a' (East-West LEFT), az-b region 'b' (RIGHT).
    """
    containers = [
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="vpc", kind="vpc", region="a", parent="acct", label_key="vpc"),
    ]
    nodes = []
    for r in regions:
        az_id = f"az-{r}"
        containers.append(
            ContainerSpec(id=az_id, kind="az", region=r, parent="vpc", label_key="az")
        )
        for ti, (tier, kind) in enumerate(_TIERS):
            sub_id = f"sub-{tier}-{r}"
            containers.append(
                ContainerSpec(id=sub_id, kind=kind, region=r, parent=az_id, label_key="subnet")
            )
            for s in range(nodes_per_tier):
                nodes.append(
                    NodeSpec(
                        id=f"{tier}{s}-{r}",
                        role="compute_instance",
                        lane="workers",
                        region=r,
                        slot=s,
                        container=sub_id,
                        scope="network",
                    )
                )
    return DiagramSpec(
        diagram_id="g40",
        diagram_name="g40 az/subnet",
        axis="north-south",
        nodes=tuple(nodes),
        edges=(),
        containers=tuple(containers),
        flow_lines=("Flow",),
        title="aws g40 — 870325637521 / eu-central-1 | 2026-10-07 | v1",
    )


# --------------------------------------------------------------------------- #
# _subnet_ordinals — the pure tier-band function.
# --------------------------------------------------------------------------- #


def test_subnet_ordinals():
    spec = _subnet_spec()
    ord_ = _subnet_ordinals(spec)
    # Declaration order within one az → public 0, app 1, batch 2, db 3.
    for r in ("a", "b"):
        assert ord_[f"sub-public-{r}"] == 0
        assert ord_[f"sub-app-{r}"] == 1
        assert ord_[f"sub-batch-{r}"] == 2
        assert ord_[f"sub-db-{r}"] == 3
    # BANDED_KINDS carries the two new members.
    assert {"subnet", "public_subnet"} <= BANDED_KINDS


# --------------------------------------------------------------------------- #
# Subnet tiers stack North-South.
# --------------------------------------------------------------------------- #


def test_subnet_tiers_stack_north_south():
    placed = layout(_subnet_spec())
    boxes = placed.containers
    for r in ("a", "b"):
        ys = [boxes[f"sub-{tier}-{r}"].y for tier, _ in _TIERS]
        # Strictly increasing y: public on top, db at the bottom.
        assert ys == sorted(ys) and len(set(ys)) == 4, (r, ys)
        # Adjacent subnet boxes are disjoint with >= one CONTAINER_PAD clear.
        for (tier_a, _), (tier_b, _) in zip(_TIERS, _TIERS[1:]):
            top = boxes[f"sub-{tier_a}-{r}"]
            bot = boxes[f"sub-{tier_b}-{r}"]
            assert bot.y >= top.y + top.h + CONTAINER_PAD, (r, tier_a, tier_b)


# --------------------------------------------------------------------------- #
# az nests its subnets; az-a left of az-b, East-West, equal width.
# --------------------------------------------------------------------------- #


def test_az_nests_subnets():
    placed = layout(_subnet_spec())
    boxes = placed.containers
    az_a, az_b = boxes["az-a"], boxes["az-b"]
    # az-a is strictly LEFT of az-b, East-West, with a clear corridor between
    # them (the region spread is preserved — the two AZ boxes do not stack).
    assert az_a.right <= az_b.x, (az_a.right, az_b.x)
    assert az_b.x - az_a.right >= 2 * CONTAINER_PAD, (az_a.right, az_b.x)
    # Peer az boxes share one width (mirror-symmetric).
    assert az_a.w == az_b.w, (az_a.w, az_b.w)
    # Each subnet is fully inside its az with >= CONTAINER_PAD padding.
    for r, az in (("a", az_a), ("b", az_b)):
        for tier, _ in _TIERS:
            sub = boxes[f"sub-{tier}-{r}"]
            assert sub.x >= az.x + CONTAINER_PAD
            assert sub.right <= az.right - CONTAINER_PAD
            assert sub.bottom <= az.bottom - CONTAINER_PAD


# --------------------------------------------------------------------------- #
# A subnet wraps its member nodes (1 node and 3 nodes), >= 30px pad.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("n", [1, 3])
def test_subnet_holds_nodes(n):
    spec = _subnet_spec(nodes_per_tier=n)
    placed = layout(spec)
    boxes = placed.containers
    for node in spec.nodes:
        sub = boxes[node.container]
        icon = placed.nodes[node.id]
        assert icon.x >= sub.x + CONTAINER_PAD, node.id
        assert icon.right <= sub.right - CONTAINER_PAD, node.id
        assert icon.y >= sub.y + CONTAINER_PAD, node.id
    # The oracle agrees: padding and overlap are clean at depth 5.
    g = DiagramGeometry(nodes=placed.nodes, containers=placed.containers)
    assert check_container_padding(g, pad=CONTAINER_PAD) == []
    assert check_container_overlap(g) == []


# --------------------------------------------------------------------------- #
# Scope guard fires without a region-kind container (the locked model).
# --------------------------------------------------------------------------- #


def test_scope_guard_fires_without_region_container():
    # A regional node declaring a subnet raises (no scope='network' override).
    bad = _subnet_spec()
    bad = DiagramSpec(
        **{
            **bad.__dict__,
            "nodes": bad.nodes
            + (
                NodeSpec(
                    id="obj-in-subnet",
                    role="object_store",
                    lane="data",
                    region="a",
                    slot=9,
                    container="sub-db-a",
                ),
            ),
        }
    )
    with pytest.raises(SpecError):
        layout(bad)

    # A scope='network' node inside a subnet is accepted (the base spec already
    # declares only network-scoped nodes in subnets, and it lays out clean).
    placed = layout(_subnet_spec())
    assert "public0-a" in placed.nodes


# --------------------------------------------------------------------------- #
# An empty subnet is a build error ([r3-med1]).
# --------------------------------------------------------------------------- #


def test_empty_subnet_is_build_error():
    spec = _subnet_spec()
    # Drop the only member of sub-db-a, leaving the container empty.
    kept = tuple(n for n in spec.nodes if n.id != "db0-a")
    spec = DiagramSpec(**{**spec.__dict__, "nodes": kept})
    with pytest.raises(SpecError, match="no children to size around"):
        layout(spec)


# --------------------------------------------------------------------------- #
# Multi-AZ VPC sizing: the generic _size wraps BOTH az boxes, no new branch.
# --------------------------------------------------------------------------- #


def test_multi_az_vpc_sizing():
    placed = layout(_subnet_spec())
    boxes = placed.containers
    vpc, az_a, az_b = boxes["vpc"], boxes["az-a"], boxes["az-b"]
    # The VPC encloses both az boxes with >= CONTAINER_PAD padding on every side.
    assert vpc.x <= az_a.x - CONTAINER_PAD
    assert vpc.right >= az_b.right + CONTAINER_PAD
    assert vpc.y <= min(az_a.y, az_b.y) - CONTAINER_PAD
    assert vpc.bottom >= max(az_a.bottom, az_b.bottom) + CONTAINER_PAD
    # The account wraps the VPC.
    acct = boxes["acct"]
    assert acct.x <= vpc.x - CONTAINER_PAD and acct.right >= vpc.right + CONTAINER_PAD


# --------------------------------------------------------------------------- #
# Depth-5 landscape: ZERO padding / overlap / geometric-containment /
# scope-placement ERROR on a full diagram-10-shaped spec.
# --------------------------------------------------------------------------- #


def _render(spec: DiagramSpec) -> str:
    """Render a depth-5 subnet spec to .drawio XML via the shared builder, so the
    containers carry their real subnet / az / vpc styles and every node is a
    structural member of its subnet cell (draw.io ``parent``)."""
    from rule_engine.diagram_layout import Node, build_diagram
    from rule_engine.draw_cli import (
        _boundaries_from,
        _edges_from,
        _node_renderer,
        _page_size,
    )
    import yaml
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    mapping = yaml.safe_load((repo / "mappings" / "aws-icons.yaml").read_text("utf-8"))
    styles = {k: v["style"] for k, v in mapping["resources"].items()}
    fallback = styles["compute_instance"]
    placed = layout(spec)
    nodes = [
        Node(
            id=n.id,
            label=n.id,
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=_node_renderer(styles.get(n.role, fallback)),
            scope=getattr(n, "scope", None),
            external=bool(getattr(n, "external", False)),
        )
        for n in spec.nodes
    ]
    boundaries = _boundaries_from(placed, "aws", {})
    page_w, page_h = _page_size(placed)
    return build_diagram(
        diagram_id=spec.diagram_id,
        diagram_name=spec.diagram_name,
        title=spec.title,
        boundaries=boundaries,
        nodes=nodes,
        edges=_edges_from(placed),
        flow_lines=spec.flow_lines,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        page_w=page_w,
        page_h=page_h,
    )


def test_depth5_padding_overlap_containment_clean():
    # A diagram-10-shaped spec: two AZ, four subnet tiers each, every tier with a
    # node, all scope='network' members of their subnet.
    xml = _render(_subnet_spec(nodes_per_tier=1))
    g = geo.build_geometry(parse_drawio(xml, path="<g40>.drawio")[0])

    assert check_container_padding(g, pad=CONTAINER_PAD) == []
    assert check_container_overlap(g) == []
    assert check_geometric_containment(g) == []

    mappings = {"aws": icon_resolver.load_mapping("aws")["containers"]}
    scope_tok = {}
    for nid, style in g.node_styles.items():
        for part in style.split(";"):
            if part.startswith("scope="):
                scope_tok[nid] = part.split("=", 1)[1]
    sp = check_scope_placement(
        g,
        lambda n: scope_tok.get(n),
        lambda n: False,
        ["aws"],
        mappings,
        scope_is_explicit=lambda n: n in scope_tok,
    )
    assert sp == [], sp


# --------------------------------------------------------------------------- #
# egress-only IGW role resolves (F7 completeness).
# --------------------------------------------------------------------------- #


def test_egress_only_igw_resolves():
    entry = icon_resolver.resolve_icon("egress_only_igw", "aws")
    assert entry["style_string"]
