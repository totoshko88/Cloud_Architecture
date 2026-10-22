"""WS4 (1.11.0) — C4 style mode tests.

C4 is a STYLE mode over the flow geometry class, not a new diagram_class:
c4-context / c4-container map to flow, and --style c4 swaps the per-node
renderer to a box with a [Container: role] label and no provider icon.
"""

from __future__ import annotations

from rule_engine import draw_cli as dc
from rule_engine.diagram_layout import ICON_SIZE, Node


def test_c4_types_map_to_flow_class():
    assert dc._CLASS_OF["c4-context"] == "flow"
    assert dc._CLASS_OF["c4-container"] == "flow"
    # context stays an accepted alias (same class)
    assert dc._CLASS_OF["context"] == "flow"


def test_c4_box_renderer_emits_box_with_stereotype_and_no_icon():
    render = dc._c4_box_renderer("serverless_fn")
    node = Node(id="n1", label="api", x=10, y=20, render=render)
    xml = render(node, "1")
    assert "[Container: serverless_fn]" in xml
    assert "api" in xml
    # box style, not an image/icon shape
    assert "rounded=1" in xml and "image=" not in xml and "resIcon" not in xml
    assert f'width="{ICON_SIZE}" height="{ICON_SIZE}"' in xml


def test_skin_renderers_c4_uses_box_for_every_role():
    from rule_engine.layout.model import NodeSpec
    nodes = [
        NodeSpec(id="a", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="b", role="object_store", lane="data", region="", slot=0),
    ]
    renderers = dc._skin_renderers("aws", nodes, style="c4")
    for role, render in renderers.items():
        node = Node(id="x", label="x", x=0, y=0, render=render)
        xml = render(node, "1")
        assert "image=" not in xml and f"[Container: {role}]" in xml


def test_skin_renderers_icon_default_is_unchanged():
    # default style resolves provider glyphs (image shapes), not C4 boxes.
    from rule_engine.layout.model import NodeSpec
    nodes = [NodeSpec(id="a", role="serverless_fn", lane="workers", region="", slot=0)]
    renderers = dc._skin_renderers("aws", nodes, style="icon")
    key = dc._renderer_key("serverless_fn", None)
    node = Node(id="x", label="x", x=0, y=0, render=renderers[key])
    xml = renderers[key](node, "1")
    assert "image=" in xml and "[Container:" not in xml


# --------------------------------------------------------------------------- #
# WS4.3 — _c4_container_spec: one level inside the system, neutral boxes.
# --------------------------------------------------------------------------- #

from rule_engine.draw import _c4_container_spec, _CONTEXT_SYSTEM_ROLE  # noqa: E402
from rule_engine.layout import layout  # noqa: E402


def _resolved(roles):
    return [({"id": f"svc{i}"}, r) for i, r in enumerate(roles)]


def test_c4_container_spec_uses_only_the_neutral_role():
    # C4 is implementation-agnostic: every box is the neutral presentation role,
    # never the resource's provider role — so no provider glyph is emitted.
    spec = _c4_container_spec(
        "aws", "acct", "us-east-1",
        _resolved(["serverless_fn", "object_store", "cdn"]), None,
    )
    assert {n.role for n in spec.nodes} == {_CONTEXT_SYSTEM_ROLE}


def test_c4_container_spec_nests_boxes_in_a_membership_boundary():
    spec = _c4_container_spec(
        "aws", "acct", "us-east-1", _resolved(["serverless_fn", "object_store"]), None,
    )
    # the single boundary is a region (membership) kind so nodes may nest
    assert [c.kind for c in spec.containers] == ["vpc"]
    nested = [n for n in spec.nodes if n.container == "system-boundary"]
    assert len(nested) == len(spec.nodes)  # all in-cloud here


def test_c4_container_spec_caps_at_the_flow_budget():
    from rule_engine.draw import _FLOW_NODE_BUDGET
    spec = _c4_container_spec(
        "aws", "a", "r", _resolved(["serverless_fn"] * 15), None,
    )
    assert len(spec.nodes) == _FLOW_NODE_BUDGET


def test_c4_container_spec_lays_out_without_a_provider_icon():
    spec = _c4_container_spec(
        "aws", "acct", "us-east-1",
        _resolved(["serverless_fn", "object_store", "cdn", "dns"]),
        [{"source": "svc0", "target": "svc1", "label": "writes"}],
    )
    placed = layout(spec)  # must not raise UnresolvedTypeError
    assert len(placed.nodes) == len(spec.nodes)


def test_c4_container_edges_survive():
    spec = _c4_container_spec(
        "aws", "a", "r", _resolved(["serverless_fn", "object_store"]),
        [{"source": "svc0", "target": "svc1"}],
    )
    assert [(e.source, e.target) for e in spec.edges] == [("svc0", "svc1")]


# --------------------------------------------------------------------------- #
# WS4.4 — provider-icon lint rules are suppressed for C4 diagram types.
# --------------------------------------------------------------------------- #

from rule_engine.linter import Artifact, lint, _is_c4_diagram  # noqa: E402


def _lint_rules(diagram_type):
    a = Artifact(
        kind="diagram", is_drawio=True, source_format="drawio",
        diagram_type=diagram_type, node_names=["api"],
    )
    return {f["rule"] for f in lint(a)["findings"]}


def test_c4_types_are_recognized_for_suppression():
    for dt in ("c4-context", "c4-container"):
        a = Artifact(kind="diagram", is_drawio=True, source_format="drawio",
                     diagram_type=dt)
        assert _is_c4_diagram(a) is True
    assert _is_c4_diagram(
        Artifact(kind="diagram", is_drawio=True, source_format="drawio",
                 diagram_type="summary")
    ) is False


def test_icon_and_container_rules_suppressed_for_c4():
    rules = _lint_rules("c4-container")
    assert "icon-resolved" not in rules
    assert "container-style" not in rules


def test_non_c4_type_keeps_the_provider_icon_rules_byte_inert():
    # A non-C4 diagram_type is unaffected: the suppression gate returns early
    # only for C4, so a summary artifact still goes through icon-resolved.
    assert _is_c4_diagram(
        Artifact(kind="diagram", is_drawio=True, source_format="drawio",
                 diagram_type="simple")
    ) is False
