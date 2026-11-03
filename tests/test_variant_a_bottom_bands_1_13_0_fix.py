"""1.13.0 fix (FEAT-004, item 10): Variant A on the bottom face.

A source whose caption sits under its icon must not fan out of its bottom on
side bands (0.25 / 0.75): every such stub crosses the name. ``layout()`` moves
a bottom exit toward a target right of (or below-right of) the source onto the
right face while that face has room (at most three exits), and a lone bottom
exit left after that takes the bottom centre. Two or more bottom exits that
cannot move (an overloaded source: the right face is full) keep distinct
bands, because two stubs on one point is the worse defect.

SEP regression bound: the SEP 02 fixture keeps two own-caption cuts, both on
``lambda-core``, whose five exits overload it (three on the right face, so
``e8`` / ``e9`` must leave the bottom; R1 keeps them on distinct thirds, masked
by the caption background).
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box
from rule_engine.layout import layout
from rule_engine.layout import pipeline
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sep" / "scripts"


def _spec(axis, targets, labels=()):
    nodes = [NodeSpec(id="hub", role="serverless_fn", lane="workers", region="", slot=0)]
    edges = []
    for i, (lane, slot) in enumerate(targets):
        nodes.append(NodeSpec(id=f"t{i}", role="object_store", lane=lane, region="", slot=slot))
        edges.append(EdgeSpec(id=f"e{i}", source="hub", target=f"t{i}", marker=str(i + 1)))
    return DiagramSpec(
        diagram_id="va", diagram_name="va", axis=axis, nodes=tuple(nodes), edges=tuple(edges),
        containers=(ContainerSpec(id="account", kind="account", region="", parent=None,
                                  label_key="account"),),
        flow_lines=(), title="aws va — 123456789012 / us-east-1 | 2026-11-03 | v1",
        order="manual", node_labels=tuple(labels))


def _box(x, y):
    return Box(id="n", x=x, y=y, w=78, h=78)


def test_three_bottom_exits_to_the_right_move_to_the_right_face():
    spec = _spec("north-south", [("data", 1), ("data", 2), ("data", 3)])
    placed = {"hub": _box(30, 30), "t0": _box(250, 350), "t1": _box(470, 350),
              "t2": _box(690, 350)}
    exits = {"e0": (0.5, 1.0), "e1": (0.25, 1.0), "e2": (0.75, 1.0)}
    order_of = {"e0": 0, "e1": 1, "e2": 2}
    pipeline._variant_a_bottom_bands(spec, placed, exits, order_of, lambda eid: eid)
    assert all(fy < 1.0 and fx >= 1.0 for fx, fy in exits.values()), exits


def test_full_right_face_keeps_distinct_bottom_bands():
    targets = [("data", i) for i in range(5)]
    spec = _spec("north-south", targets)
    placed = {"hub": _box(30, 30), **{f"t{i}": _box(250 + 220 * i, 350) for i in range(5)}}
    exits = {"e0": (1.0, 0.5), "e1": (1.0, 0.25), "e2": (1.0, 0.75),
             "e3": (0.25, 1.0), "e4": (0.75, 1.0)}
    before = dict(exits)
    pipeline._variant_a_bottom_bands(spec, placed, exits, {f"e{i}": i for i in range(5)},
                                     lambda eid: eid)
    assert exits == before                          # overloaded: nothing can move


def test_lone_bottom_exit_takes_the_centre():
    targets = [("data", i) for i in range(4)]
    spec = _spec("north-south", targets)
    placed = {"hub": _box(30, 30), "t0": _box(30, 350),
              **{f"t{i}": _box(250 + 220 * i, 350) for i in range(1, 4)}}
    exits = {"e0": (0.25, 1.0), "e1": (1.0, 0.5), "e2": (1.0, 0.25), "e3": (1.0, 0.75)}
    pipeline._variant_a_bottom_bands(spec, placed, exits, {f"e{i}": i for i in range(4)},
                                     lambda eid: eid)
    assert exits["e0"] == (0.5, 1.0)


def test_layout_gives_a_captioned_hub_no_lone_bottom_side_band():
    """A hub with three right exits and one more target below-right: the
    fourth branch leaves the bottom, from the centre (it was the 0.25 band)."""
    spec = _spec("left-right", [("platform", 0), ("platform", 1), ("data", 2), ("data", 3)])
    placed = layout(spec)
    bottom = [pe for pe in placed.edges if pe.spec.source == "hub" and pe.exit[1] >= 1.0]
    assert len(bottom) == 1
    hub = placed.nodes["hub"]
    assert abs(hub.x + bottom[0].exit[0] * hub.w - (hub.x + hub.w / 2)) <= geo.GRID / 2


def _build_sep(name: str) -> str:
    from rule_engine.icon_resolver import _load_mapping_cached

    path = _FIXTURES / name
    cwd = os.getcwd()
    os.chdir(_FIXTURES.parent)
    _load_mapping_cached.cache_clear()
    try:
        spec = importlib.util.spec_from_file_location(path.stem + "_va_feat004", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return (getattr(module, "build", None) or module._build)()
    finally:
        os.chdir(cwd)
        _load_mapping_cached.cache_clear()


@pytest.mark.sep
def test_sep_02_own_caption_cuts_are_the_overloaded_residual():
    g = geo.build_geometry(parse_drawio(_build_sep("build_02_sep_summary.py"),
                                        path="02.drawio")[0])
    cuts = sorted(eid for eid, _ in geo.check_edge_crosses_own_label(g))
    assert cuts == ["e8", "e9"]
    right = [e for e in g.edges if e.source == "lambda-core" and e.exit[0] >= 1.0]
    assert len(right) == 3                          # the right face is full
    by_id = {e.id: e for e in g.edges}
    assert {by_id[c].source for c in cuts} == {"lambda-core"}
    assert by_id["e8"].exit != by_id["e9"].exit     # distinct thirds
