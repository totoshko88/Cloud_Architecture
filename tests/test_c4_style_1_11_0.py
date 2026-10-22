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
