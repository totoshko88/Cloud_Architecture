"""Phase 3 item 8a (F7): the return bus is offered to a LOWER-ROW reply, not
only a same-row leftward one.

Before the fix, ``variants._is_return`` qualified an edge only when the target's
centre sat LEFT of the source's left edge. SEP 05 ``e7`` — EE's reply queue on a
lower row, directly below-left — was not leftward, so no bus variant was
generated and its ordinary row-gap loop cut five forward edges
(``crossings-over-cap:5/11``). The widened predicate also qualifies a reply whose
target is a full row BELOW the source and not to its right.

The bus stays variant-scored (``face_swap``): a below-row reply that is already
clean keeps its ordinary route; the bus is taken only on strictly fewer
crossings with no new finding. ``8b`` (feedback-arc-set ordering) is NOT shipped
(see CHANGELOG Notes).
"""
from __future__ import annotations

from rule_engine.geometry import Box
from rule_engine.layout import variants
from rule_engine.layout.model import EdgeSpec

_BUS_PLANS = (variants.RoutePlan.RETURN_BUS_ABOVE, variants.RoutePlan.RETURN_BUS_BELOW)


def _bus_variants(edge, placed, kind):
    return [v for v in variants.generate(edge, placed, {}, kind) if v.plan in _BUS_PLANS]


def test_leftward_reply_still_qualifies():
    # the original case: target left of the source's left edge
    placed = {"s": Box("s", 540, 280, 78, 78), "t": Box("t", 100, 280, 78, 78)}
    e = EdgeSpec(id="r", source="s", target="t", marker="2")
    assert variants._is_return(e, placed)
    assert _bus_variants(e, placed, "back-edge")


def test_lower_row_reply_below_left_qualifies():
    # SEP 05 e7 shape: target a full row BELOW the source and below-left.
    placed = {"s": Box("s", 300, 280, 78, 78), "t": Box("t", 120, 500, 78, 78)}
    e = EdgeSpec(id="r", source="s", target="t", marker="2")
    assert variants._is_return(e, placed)
    assert _bus_variants(e, placed, "back-edge")


def test_lower_row_reply_directly_below_qualifies():
    # directly below (same column) one row down: not-right, below -> qualifies.
    placed = {"s": Box("s", 300, 280, 78, 78), "t": Box("t", 300, 540, 78, 78)}
    e = EdgeSpec(id="r", source="s", target="t", marker="2")
    assert variants._is_return(e, placed)


def test_lower_row_target_to_the_right_does_not_qualify():
    # a forward (down-RIGHT) edge is not a return edge; no bus.
    placed = {"s": Box("s", 300, 280, 78, 78), "t": Box("t", 600, 540, 78, 78)}
    e = EdgeSpec(id="f", source="s", target="t", marker="1")
    assert not variants._is_return(e, placed)
    assert _bus_variants(e, placed, "cross-region") == []


def test_same_row_rightward_does_not_qualify():
    placed = {"s": Box("s", 100, 280, 78, 78), "t": Box("t", 540, 280, 78, 78)}
    e = EdgeSpec(id="f", source="s", target="t", marker="1")
    assert not variants._is_return(e, placed)
