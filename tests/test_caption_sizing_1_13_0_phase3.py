"""1.13.0 phase 3 (item 7): captions sized to members / node-label word count.

* 7b: ``build_diagram(node_caption_wrap=N)`` wraps a node label wider than its
  enclosing boundary onto <= N lines (no-op when every caption fits).
* 7c: ``caption-outside-container`` surfaces as a ``container-padding`` WARNING
  on a FLOW diagram too (ERROR on landscape), so lint and layout agree.
* 7d: ``node-label-length`` ignores bare punctuation tokens (``+``, ``&``).
"""
from __future__ import annotations

from rule_engine import diagram_layout as dl
from rule_engine.linter import Artifact, _check_node_label_length


# --------------------------------------------------------------------------- #
# 7d: bare punctuation tokens are not words
# --------------------------------------------------------------------------- #

def test_node_label_length_ignores_bare_punctuation():
    # "Syndicate Server (EE + Syndi)" reads as 4 words (the `+` is a connector).
    a = Artifact(kind="diagram", node_names=["Syndicate Server (EE + Syndi)"])
    assert _check_node_label_length(a) is False


def test_node_label_length_still_flags_five_real_words():
    a = Artifact(kind="diagram", node_names=["one two three four five six"])
    hit = _check_node_label_length(a)
    assert hit and "one two three four five six" in hit.offenders


def test_node_label_length_still_flags_the_char_cap():
    long = "A" * 41
    hit = _check_node_label_length(Artifact(kind="diagram", node_names=[long]))
    assert hit and long in hit.offenders


# --------------------------------------------------------------------------- #
# 7b: node_caption_wrap
# --------------------------------------------------------------------------- #

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"


def _build(nodes, **kw):
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE,
        boundaries=[dl.Boundary("boundary-vpc", "VPC", 100, 100, 160, 200)],
        nodes=nodes, edges=[], flow_lines=["Flow"], legend_x=900,
        page_w=1200, page_h=600, **kw,
    )


def test_node_caption_wrap_splits_an_overhanging_label():
    # a long label on a narrow (160px) VPC: wraps onto 2 lines with node_caption_wrap.
    nodes = [dl.Node("a", "Very Long Service Name Here", 120, 150, render=_ICON)]
    plain = _build(nodes)
    wrapped = _build(nodes, node_caption_wrap=2)
    assert "Very Long Service Name Here" in plain and "br&gt;" not in plain
    # the stored value carries the <br> break entity (escaped `<`, un-escaped by
    # the drawio parser so the lint splits it and html=1 renders two lines).
    assert "&lt;br&gt;" in wrapped or "&lt;br>" in wrapped


def test_wrap_node_captions_helper_splits_only_overhang():
    nodes = [
        dl.Node("a", "Very Long Service Name Here", 120, 150, render=_ICON),
        dl.Node("b", "svc", 120, 150, render=_ICON),
    ]
    b = [dl.Boundary("boundary-vpc", "VPC", 100, 100, 160, 200)]
    out = {n.id: n.label for n in dl._wrap_node_captions(nodes, b, 2)}
    assert "<br>" in out["a"]
    assert out["b"] == "svc"


def test_node_caption_wrap_is_a_noop_when_captions_fit():
    nodes = [dl.Node("a", "svc", 120, 150, render=_ICON)]
    assert _build(nodes) == _build(nodes, node_caption_wrap=2)


def test_node_caption_wrap_zero_is_byte_identical():
    nodes = [dl.Node("a", "Very Long Service Name Here", 120, 150, render=_ICON)]
    assert _build(nodes) == _build(nodes, node_caption_wrap=0)
