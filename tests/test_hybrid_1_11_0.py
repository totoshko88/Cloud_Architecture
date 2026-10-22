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
