"""WS3 (1.11.0) — hybrid diagram tests (per-node/container provider override)."""

from __future__ import annotations

from rule_engine import draw_cli as dc
from rule_engine.diagram_layout import Node
from rule_engine.layout.model import ContainerSpec, NodeSpec


def test_nodespec_and_containerspec_carry_optional_provider():
    n = NodeSpec(id="w", role="managed_k8s", lane="workers", region="a", slot=0,
                 provider="kubernetes")
    c = ContainerSpec(id="dep", kind="vpc", region="a", parent="acct",
                      label_key="vpc", provider="kubernetes")
    assert n.provider == "kubernetes" and c.provider == "kubernetes"
    # default is None (byte-inert for every existing spec)
    assert NodeSpec(id="x", role="lb", lane="edge", region="", slot=0).provider is None
    assert ContainerSpec(id="a", kind="account", region="", parent=None,
                         label_key="account").provider is None


def test_renderer_key_is_role_without_override_and_composite_with():
    assert dc._renderer_key("managed_k8s", None) == "managed_k8s"
    assert dc._renderer_key("managed_k8s", "kubernetes") == "managed_k8s@kubernetes"


def test_foreign_provider_node_resolves_its_own_profile_glyph():
    # An aws-primary diagram with a kubernetes-overridden workload: the override
    # resolves the k8s glyph, the plain node resolves the aws glyph.
    nodes = [
        NodeSpec(id="aws-fn", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="k8s-dep", role="managed_k8s", lane="platform", region="", slot=0,
                 provider="kubernetes"),
    ]
    renderers = dc._skin_renderers("aws", nodes, style="icon")
    assert "serverless_fn" in renderers
    assert "managed_k8s@kubernetes" in renderers
    # the k8s renderer draws the kubernetes asset, not an aws one
    xml = renderers["managed_k8s@kubernetes"](Node(id="k8s-dep", label="dep", x=0, y=0,
                                                   render=renderers["managed_k8s@kubernetes"]), "1")
    assert "kubernetes" in xml.lower() or "k8s" in xml.lower()


def test_no_override_keeps_single_role_keyed_renderer():
    nodes = [NodeSpec(id="a", role="lb", lane="edge", region="", slot=0)]
    renderers = dc._skin_renderers("aws", nodes, style="icon")
    assert list(renderers.keys()) == ["lb"]


# --------------------------------------------------------------------------- #
# WS3.2 / WS3.4 — per-container provider resolution in _boundaries_from.
#
# Owner's closed rule: a managed service in its own cloud keeps the provider
# brand box; a foreign / self-hosted cluster (provider=kubernetes) resolves the
# Kubernetes-blue #326CE5 box. Data-driven via resolve_container, no special
# casing. An unset container provider yields the primary verbatim (byte-inert).
# --------------------------------------------------------------------------- #

from rule_engine.layout import layout  # noqa: E402
from rule_engine.layout.model import DiagramSpec  # noqa: E402


def _hybrid_placed():
    spec = DiagramSpec(
        diagram_id="h", diagram_name="h", axis="north-south",
        nodes=(
            NodeSpec(id="api", role="serverless_fn", lane="workers", region="",
                     slot=0, container="vpc1"),
            NodeSpec(id="pod", role="compute_instance", lane="workers", region="",
                     slot=1, container="ns1", provider="kubernetes"),
        ),
        edges=(),
        containers=(
            ContainerSpec(id="vpc1", kind="vpc", region="", parent=None,
                          label_key="account"),
            ContainerSpec(id="ns1", kind="network_boundary", region="",
                          parent="vpc1", label_key="account", provider="kubernetes"),
        ),
        flow_lines=(), title="aws hybrid",
    )
    return layout(spec)


def test_foreign_container_resolves_kubernetes_blue():
    placed = _hybrid_placed()
    bs = {b.id: b for b in dc._boundaries_from(placed, "aws",
                                               {"vpc1": "VPC", "ns1": "ns/app"})}
    # the AWS VPC keeps the AWS brand; the k8s namespace is Kubernetes blue
    assert "8C4FFF" in bs["vpc1"].style
    assert "#326CE5" in bs["ns1"].style


def test_unset_container_provider_is_byte_inert():
    # Every container unset → each resolves under the primary, exactly as before.
    spec = DiagramSpec(
        diagram_id="p", diagram_name="p", axis="north-south",
        nodes=(NodeSpec(id="api", role="serverless_fn", lane="workers",
                        region="", slot=0, container="vpc1"),),
        edges=(),
        containers=(ContainerSpec(id="vpc1", kind="vpc", region="", parent=None,
                                  label_key="account"),),
        flow_lines=(), title="aws plain",
    )
    placed = layout(spec)
    primary = dc._boundaries_from(placed, "aws", {"vpc1": "VPC"})[0]
    # identical to resolving the kind directly under the primary provider
    assert primary.style == dc._container_style("vpc", "aws")


def test_hybrid_container_box_is_not_falsely_flagged_by_lint():
    # A k8s-blue namespace in an aws-titled diagram must not trip container-style:
    # its shape signature does not match any aws container candidate, so it is
    # skipped (recognised as foreign), never reported as an off-colour aws box.
    from rule_engine.geometry import check_container_style
    from rule_engine import icon_resolver
    from rule_engine.constants import PROVIDERS

    class _G:
        pass
    geo = _G()
    geo.container_styles = {
        "ns1": icon_resolver.resolve_container("network_boundary", "kubernetes")["style_string"],
    }
    maps = {}
    for p in PROVIDERS:
        try:
            maps[p] = icon_resolver.load_mapping(p).get("containers") or {}
        except Exception:
            pass
    # judged against aws only (hybrid title names the primary) → no false finding
    assert check_container_style(geo, ["aws"], maps) == []
