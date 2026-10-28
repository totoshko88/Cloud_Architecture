"""SYS-A (G37) — prefer a DOWNWARD / straight exit when the target is below.

The owner's rule R3 ("вихід ближче до цілі") means a target BELOW the source is
left on the BOTTOM face (a straight/downward drop), not stepped out RIGHT into a
side-corridor stair. The pre-1.11.0 Rule A exited every edge right to spare the
node's own caption; since ENG-R2 (1.11.0) masks any crossed caption with an
opaque background and paints edges beneath the vertices, a bottom exit through
the source's own caption is legible, so :func:`select_contacts` now follows the
target direction.

These tests guard the four mandatory guards from the audit (§3.4 / §6):

* (a) a MOSTLY-below target with a clear column and <= 1 crossing edge routes as
  a straight/bottom drop (exit y == 1, entry y == 0);
* (b) GUARD 1 forces the right/side-corridor route when another icon sits in the
  drop column (a straight drop through a foreign icon is an edge-routing ERROR);
* (c) GUARD 2 forces the right/stair route for the 2nd edge when a foreign line
  also crosses one source caption (the R5 mask covers ONE line, not two);
* (d) GUARD 3 spills onto the bottom face rather than adding a 4th bottom point.
"""
from __future__ import annotations

from rule_engine.layout import layout
from rule_engine.layout.contacts import (
    MAX_SIDE_EXITS,
    _box_mostly_below,
    select_contacts,
)
from rule_engine.layout.pipeline import _global_contacts
from rule_engine.layout.place import place_and_size
from rule_engine.layout.model import (
    ContainerSpec,
    DiagramSpec,
    EdgeSpec,
    NodeSpec,
)
from rule_engine.geometry import Box

ACCOUNT = (ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),)


# --------------------------------------------------------------------------- #
# (a) a mostly-below target with a clear column drops straight (bottom→top).
# --------------------------------------------------------------------------- #

def test_mostly_below_clear_column_exits_bottom_enters_top():
    """A target below the source within half a column step, column clear, with a
    single edge: the contact ladder returns a bottom-centre exit and a top-centre
    entry — the straight/downward drop (owner comments 03, 08a, 10)."""
    placed = {
        "a": Box("a", 100.0, 100.0, 78.0, 78.0),
        "b": Box("b", 150.0, 360.0, 78.0, 78.0),  # below, dx=50 < COL_STEP/2
    }
    edge = EdgeSpec(id="e1", source="a", target="b", marker="1")
    assert _box_mostly_below(placed["a"], placed["b"], [])
    exit_pt, entry_pt = select_contacts(edge, placed)
    assert exit_pt[1] == 1.0, "mostly-below target must exit the BOTTOM face"
    assert entry_pt[1] == 0.0, "a downward drop must enter the target's TOP face"


def test_side_target_keeps_right_exit():
    """A target to the side (not below) keeps the right-centre exit — SYS-A only
    inverts a BELOW target."""
    placed = {
        "a": Box("a", 100.0, 100.0, 78.0, 78.0),
        "b": Box("b", 600.0, 110.0, 78.0, 78.0),  # to the right, same row
    }
    edge = EdgeSpec(id="e1", source="a", target="b", marker="1")
    assert not _box_mostly_below(placed["a"], placed["b"], [])
    exit_pt, _entry = select_contacts(edge, placed)
    assert exit_pt == (1.0, 0.5), "a side target keeps the right-centre exit"


def test_far_offset_below_is_not_mostly_below():
    """A target below but a FULL column to the side is a sideways fan-out, not a
    drop — it must keep the right exit (|dx| > COL_STEP/2)."""
    placed = {
        "a": Box("a", 100.0, 100.0, 78.0, 78.0),
        "b": Box("b", 420.0, 360.0, 78.0, 78.0),  # dx=320 > COL_STEP/2 (110)
    }
    edge = EdgeSpec(id="e1", source="a", target="b", marker="1")
    assert not _box_mostly_below(placed["a"], placed["b"], [])
    exit_pt, _entry = select_contacts(edge, placed)
    assert exit_pt == (1.0, 0.5)


# --------------------------------------------------------------------------- #
# (b) GUARD 1 — an intervening icon in the drop column forces the right exit.
# --------------------------------------------------------------------------- #

def test_guard1_intervening_icon_keeps_right_exit():
    """When another node's icon sits in the vertical corridor between source and
    target, the straight drop would cut it (an edge-routing ERROR the caption
    mask cannot fix), so the right/side-corridor exit stands."""
    placed = {
        "a": Box("a", 100.0, 100.0, 78.0, 78.0),
        "mid": Box("mid", 110.0, 220.0, 78.0, 78.0),  # in the drop column
        "b": Box("b", 120.0, 360.0, 78.0, 78.0),
    }
    others = [placed["mid"]]
    edge = EdgeSpec(id="e1", source="a", target="b", marker="1")
    assert not _box_mostly_below(placed["a"], placed["b"], others)
    exit_pt, _entry = select_contacts(edge, placed)
    assert exit_pt == (1.0, 0.5), "GUARD 1: an icon in the column forces the right exit"


# --------------------------------------------------------------------------- #
# (c) GUARD 2 — only ONE edge per source caption may take the downward route.
# --------------------------------------------------------------------------- #

def test_guard2_only_one_downward_per_source_caption():
    """Two edges whose downward drops both pass through ONE source's caption: the
    R5 opaque background masks a single line, so only ONE may drop — the other
    keeps the right/stair exit (recorded as a conscious keep-with-reason)."""
    placed = {
        "a": Box("a", 100.0, 100.0, 78.0, 78.0),
        "b1": Box("b1", 120.0, 360.0, 78.0, 78.0),  # below a, mostly-below
        "b2": Box("b2", 140.0, 620.0, 78.0, 78.0),  # below a, mostly-below
    }
    # Both candidates leave source 'a'; GUARD 2 clears only the first.
    allow_downward = {"e1"}  # the pre-pass keeps the first declared edge
    e1 = EdgeSpec(id="e1", source="a", target="b1", marker="1")
    e2 = EdgeSpec(id="e2", source="a", target="b2", marker="2")
    assert _box_mostly_below(placed["a"], placed["b1"], [placed["b2"]])
    x1, _ = select_contacts(e1, placed, allow_downward)
    x2, _ = select_contacts(e2, placed, allow_downward)
    assert x1[1] == 1.0, "GUARD 2: the cleared edge takes the downward drop"
    assert x2 == (1.0, 0.5), "GUARD 2: the 2nd edge over one caption keeps the right exit"


def test_guard2_prepass_clears_one_edge_per_source():
    """The pipeline pre-pass (``_global_contacts``) groups the candidate downward
    edges by source and clears at most ONE per source caption to drop."""
    nodes = (
        NodeSpec(id="a", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="b1", role="object_store", lane="data", region="", slot=0),
        NodeSpec(id="b2", role="managed_sql", lane="data", region="", slot=1),
    )
    edges = (
        EdgeSpec(id="e1", source="a", target="b1", marker="1"),
        EdgeSpec(id="e2", source="a", target="b2", marker="2"),
    )
    spec = DiagramSpec(
        diagram_id="sys-a-g2", diagram_name="sys-a-g2", axis="left-right",
        nodes=nodes, edges=edges, containers=ACCOUNT,
        flow_lines=("Flow", "1. b1", "2. b2"),
        title="aws sys-a — 000000000000 / eu-central-1 | 2026-10-23 | v1",
        order="manual",
    )
    placed, containers = place_and_size(spec)
    exits, _entries, _lanes = _global_contacts(spec, placed, containers)
    # At most one of the two edges from 'a' may have a bottom exit (y == 1.0).
    bottom = [eid for eid, pt in exits.items() if pt[1] is not None and pt[1] >= 1.0
              and eid in ("e1", "e2")]
    assert len(bottom) <= 1, "GUARD 2: at most one downward drop per source caption"


# --------------------------------------------------------------------------- #
# (d) GUARD 3 — an over-connected bottom spills rather than adding a 4th point.
# --------------------------------------------------------------------------- #

def test_guard3_over_connected_bottom_spills_no_fourth_point():
    """A source that would drop more than MAX_SIDE_EXITS edges straight down must
    NOT emit a 4th bottom contact point; the existing spill/valve moves the
    surplus to another face. The finished layout has <= MAX_SIDE_EXITS exits on
    any one source face."""
    nodes = (
        NodeSpec(id="hub", role="serverless_fn", lane="workers", region="", slot=2),
        NodeSpec(id="t0", role="object_store", lane="data", region="", slot=0),
        NodeSpec(id="t1", role="managed_sql", lane="data", region="", slot=1),
        NodeSpec(id="t2", role="message_queue", lane="data", region="", slot=2),
        NodeSpec(id="t3", role="secrets_store", lane="data", region="", slot=3),
    )
    edges = tuple(
        EdgeSpec(id=f"e{i}", source="hub", target=f"t{i}", marker=str(i + 1))
        for i in range(4)
    )
    spec = DiagramSpec(
        diagram_id="sys-a-g3", diagram_name="sys-a-g3", axis="left-right",
        nodes=nodes, edges=edges, containers=ACCOUNT,
        flow_lines=("Flow",) + tuple(f"{i + 1}. t{i}" for i in range(4)),
        title="aws sys-a — 000000000000 / eu-central-1 | 2026-10-23 | v1",
        order="manual",
    )
    placed = layout(spec)  # must not raise OverConnectedError
    # Count exits per (source, face) on the finished diagram.
    from collections import Counter

    def _face(pt):
        fx, fy = pt
        if fy is not None and fy >= 1.0:
            return "bottom"
        if fy is not None and fy <= 0.0:
            return "top"
        return "right" if (fx is not None and fx >= 0.5) else "left"

    counts = Counter()
    for pe in placed.edges:
        counts[(pe.spec.source, _face(pe.exit))] += 1
    assert all(c <= MAX_SIDE_EXITS for c in counts.values()), (
        f"GUARD 3: no source face may carry more than {MAX_SIDE_EXITS} exits; got {counts}"
    )


# --------------------------------------------------------------------------- #
# The scored objective must NOT penalise an own-caption drop (edge-crosses-own-
# label stays lint/finishing-pass-only, NOT in geometry.rule_violations).
# --------------------------------------------------------------------------- #

def test_rule_violations_excludes_edge_crosses_own_label():
    """``geometry.rule_violations`` — the scored objective — must not list
    ``edge-crosses-own-label`` in either errors or advisory warnings, so a
    masked own-caption drop scores no penalty (acceptance criterion)."""
    import inspect
    import rule_engine.geometry as geo

    src = inspect.getsource(geo.rule_violations)
    assert "edge-crosses-own-label" not in src
    assert "check_edge_strikes_own_text" not in src
