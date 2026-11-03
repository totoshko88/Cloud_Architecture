"""1.13.0 fix (task item 13): membership comes from the spec, not geometry.

SEP 12 (``tests/fixtures/sep/scripts/build_12_sep_access.py``): ``p-sched``
declares no container, yet it ended up inside the ``trust-box`` (an
``external_cloud`` box around ``p-admin``) and was parented to it. Cause: the
layout repair loop answered a ``container-padding`` spill of the orphan
``p-sched`` by growing the trust box around it (``repair._repair``), and
``build_diagram`` then parented the node to the box by geometry.

Now the repair loop only grows a box around a node the spec assigns to it (or
the account / region), ``layout`` reports ``scope-membership`` when a
container-less node still lands inside a box it is not a member of, and
``build_diagram(membership=...)`` parents nodes by the spec.
"""
from __future__ import annotations

import importlib.util
import re
from dataclasses import replace
from pathlib import Path

from rule_engine import diagram_layout as dl
from rule_engine.cli import parse_artifacts
from rule_engine.layout import layout, membership_of, scope_membership_warnings
from rule_engine.linter import lint

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sep" / "scripts"
_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"
_BOX = ("rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;strokeColor=#666666;"
        "fontColor=#333333;verticalAlign=top;align=left;spacingLeft=6;fontSize=12")


def _spec12():
    spec = importlib.util.spec_from_file_location("b12", _FIXTURES / "build_12_sep_access.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._spec()


def _inside(b, c) -> bool:
    return c.x <= b.x and c.y <= b.y and b.x + b.w <= c.x + c.w and b.y + b.h <= c.y + c.h


def test_sep12_trust_box_no_longer_swallows_the_scheduler():
    placed = layout(_spec12(), strict=False)
    trust = placed.containers["trust-box"]
    assert _inside(placed.nodes["p-admin"], trust)
    assert not _inside(placed.nodes["p-sched"], trust)
    member = membership_of(placed)
    assert member["p-admin"] == "trust-box"
    assert member["p-sched"] == ""
    assert not any(w.startswith("scope-membership") for w in placed.layout_warnings)


def test_layout_reports_a_container_less_node_inside_a_foreign_box():
    placed = layout(_spec12(), strict=False)
    trust = placed.containers["trust-box"]
    admin = placed.nodes["p-admin"]
    # move p-sched into the trust box beside p-admin
    moved = replace(placed, nodes={**placed.nodes,
                                   "p-sched": replace(placed.nodes["p-sched"],
                                                      x=admin.x, y=admin.y)})
    assert _inside(moved.nodes["p-sched"], trust)
    assert scope_membership_warnings(moved) == (
        "scope-membership: p-sched inside trust-box but not declared a member",
    )


def _build(membership=None) -> str:
    box = dl.Boundary(id="trust-box", label="Trust boundary", x=60, y=60, w=300, h=420,
                      style=_BOX)
    nodes = [
        dl.Node(id="p-sched", label="Scheduler role", x=170, y=130, render=_ICON),
        dl.Node(id="p-admin", label="sandbox admin", x=170, y=320, render=_ICON),
        dl.Node(id="pol", label="policy", x=520, y=320, render=_ICON),
    ]
    edges = [dl.Edge(id="e1", source="p-sched", target="pol", marker="1"),
             dl.Edge(id="e2", source="p-admin", target="pol", marker="2")]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[box],
        nodes=nodes, edges=edges, flow_lines=["Flow", "1. a", "2. b"],
        legend_x=700, page_w=1100, page_h=600, membership=membership,
    )


def _parent(text: str, nid: str) -> str:
    return re.search(r'<mxCell id="' + nid + r'"[^>]*\bparent="([^"]*)"', text).group(1)


def test_builder_parents_by_spec_membership(tmp_path):
    geometric = _build()
    assert _parent(geometric, "p-sched") == "trust-box"
    spec = _build({"p-sched": "", "p-admin": "trust-box", "pol": ""})
    assert _parent(spec, "p-sched") == "1"
    assert _parent(spec, "p-admin") == "trust-box"
    # the non-member is now visible to lint
    path = tmp_path / "01-t.drawio"
    path.write_text(spec, encoding="utf-8")
    (art,) = parse_artifacts(str(path))
    hits = [f for f in lint(art)["findings"] if f["rule"] == "geometric-containment"]
    assert hits and "p-sched" in str(hits[0])


def test_membership_omitting_a_node_falls_back_to_geometry():
    text = _build({"p-admin": "trust-box"})
    assert _parent(text, "p-sched") == "trust-box"
