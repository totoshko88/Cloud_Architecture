"""1.13.0 fix (ITEM 17): caption-vs-caption overlap and captions printed across
a container border.

* ``node-overlap`` reason ``caption-overlap``: two nodes whose icon-width
  footprints clear while their real-width captions overlap (SEP 10 IGW / NAT).
* ``container-padding`` reason ``caption-outside-container``: a member's caption
  runs past its container's left/right border (ERROR on a landscape).
* the vertical-spill test skips an ``external=1`` / global node (review E5).
"""
from __future__ import annotations

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry
from rule_engine.linter import Artifact, Severity, lint


def _findings(g, rule, cls="flow"):
    art = Artifact(kind="diagram", node_names=sorted(g.nodes), geometry=g, diagram_class=cls)
    return [f for f in lint(art)["findings"] if f["rule"] == rule]


def test_adjacent_long_captions_overlap():
    g = DiagramGeometry()
    g.nodes["igw"] = Box("igw", 100, 100, 78, 78)
    g.nodes["nat"] = Box("nat", 200, 100, 78, 78)        # 100px apart
    g.node_labels["igw"] = "Internet gateway (igw-01)"   # 25 chars -> 175px
    g.node_labels["nat"] = "NAT gateway (nat-0a1b2c3)"
    assert geo.check_node_overlap(g) == []               # icon-width footprints clear
    assert geo.check_caption_overlap(g) == [("igw", "nat")]
    hits = _findings(g, "node-overlap")
    assert len(hits) == 1 and hits[0]["reason"] == "caption-overlap"
    assert hits[0]["offenders"] == ["igw", "nat"]


def test_short_captions_do_not_overlap():
    g = DiagramGeometry()
    g.nodes["a"] = Box("a", 100, 100, 78, 78)
    g.nodes["b"] = Box("b", 320, 100, 78, 78)
    g.node_labels.update({"a": "app-az1", "b": "cache-az1"})
    assert geo.check_caption_overlap(g) == []
    assert _findings(g, "node-overlap") == []


def _vpc_geo(label):
    g = DiagramGeometry()
    g.containers["vpc"] = Box("vpc", 100, 100, 400, 300)
    g.container_styles["vpc"] = "rounded=0;dashed=1;fillColor=none"
    g.nodes["n"] = Box("n", 130, 160, 78, 78)            # icon well inside
    g.node_labels["n"] = label
    return g


def test_long_caption_crossing_the_vpc_left_border_is_an_error_on_landscape():
    g = _vpc_geo("very-long-service-caption-name")       # 30 chars -> 210px
    assert geo.check_caption_outside_container(g) == [("n", "vpc", 36.0)]
    land = _findings(g, "container-padding", "landscape")
    assert any(f["reason"] == "caption-outside-container"
               and f["severity"] == Severity.ERROR.value for f in land), land
    flow = _findings(g, "container-padding", "flow")
    assert any(f["reason"] == "caption-outside-container"
               and f["severity"] == Severity.WARNING.value for f in flow), flow


def test_caption_inside_the_box_is_clean():
    g = _vpc_geo("api")
    assert geo.check_caption_outside_container(g) == []


def test_spill_skips_external_and_global_nodes():
    g = DiagramGeometry()
    g.containers["acct"] = Box("acct", 100, 200, 600, 400)
    g.container_styles["acct"] = "rounded=0;dashed=1;fillColor=none"
    # A node in the account's x-band just above its top border (a spill shape).
    g.nodes["edge"] = Box("edge", 300, 80, 78, 78)
    assert any(n == "edge" for n, _c, _p in geo.check_container_padding(g))
    g.node_styles["edge"] = "image;scope=global;"
    assert geo.check_container_padding(g) == []
    g.node_styles["edge"] = "image;external=1;"
    assert geo.check_container_padding(g) == []


def test_draw_cli_wraps_long_slugs_inside_the_pad():
    from rule_engine.draw_cli import _wrap_slug
    for slug in ("arn-aws-s3-agent-artifact-store", "arn-aws-bedrock-us-east-1-foundation-mod",
                 "abcdefghijklmnopqrstuvwxyz0123456789abcd"):
        out = _wrap_slug(slug)
        lines = geo.caption_lines(out)
        assert len(lines) == 2 and all(len(ln) <= 18 for ln in lines), out
        assert len(out) <= 40                    # node-label-length cap
    assert _wrap_slug("short-slug") == "short-slug"
