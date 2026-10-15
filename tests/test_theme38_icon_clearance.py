"""Theme 38a — proactive line-to-icon clearance in the corridor choosers.

The engine already *measures* a rail (a long vertical passing within
``RAIL_CLEARANCE`` of an unrelated icon) in :func:`rule_engine.geometry.route_cost`,
but the rule-based corridor choosers never consulted it, so a spine could be
dropped ~2px off a neighbouring glyph (SEP 03-e2 beside SSM+KMS). These tests
pin the new proactive helper that pushes such a corridor off the icon at routing
time, reusing the same ``RAIL_CLEARANCE`` / ``RAIL_MIN_SPAN`` metric — and, just
as importantly, that it does NOTHING to a short tier-step or an already-clear
run (the byte-inert guarantee the shipped corpus depends on).
"""

from __future__ import annotations

from rule_engine.layout.routers import _nudge_clear_of_icons, _icon_clearance
from rule_engine.geometry import Box, RAIL_CLEARANCE, RAIL_MIN_SPAN


def _icon_at(x: float) -> Box:
    # A 78px glyph whose left border sits at x, spanning a tall vertical range so
    # it overlaps any test run.
    return Box("ssm", x=x, y=0.0, w=78.0, h=2000.0)


def test_icon_clearance_is_nearest_side_border():
    box = _icon_at(500.0)  # borders at 500 and 578
    # a line at 502 is 2px off the left border
    assert _icon_clearance(502.0, 0.0, 600.0, [box], ()) == 2.0
    # a line at 540 is 40px off the left, 38 off the right -> min 38
    assert _icon_clearance(540.0, 0.0, 600.0, [box], ()) == 38.0
    # skip set excludes the box -> nothing overlaps -> +inf
    assert _icon_clearance(502.0, 0.0, 600.0, [box], ("ssm",)) == float("inf")


def test_long_rail_flush_against_icon_is_nudged_clear():
    # A 540px vertical at x=480, with an icon whose left border is at 482 (2px).
    box = _icon_at(482.0)
    out = _nudge_clear_of_icons(
        480.0, 100.0, 640.0, [box], (), lo_bound=440.0, hi_bound=560.0
    )
    # It must move to a grid line that clears RAIL_CLEARANCE on the near side.
    assert out != 480.0
    assert _icon_clearance(out, 100.0, 640.0, [box], ()) >= RAIL_CLEARANCE


def test_short_step_is_never_nudged():
    # Same flush icon, but an 80px run (< RAIL_MIN_SPAN) is a tier step, not a
    # rail — it must be returned unchanged so the shipped corpus stays byte-inert.
    assert RAIL_MIN_SPAN > 80.0
    box = _icon_at(482.0)
    out = _nudge_clear_of_icons(
        480.0, 440.0, 520.0, [box], (), lo_bound=440.0, hi_bound=560.0
    )
    assert out == 480.0


def test_already_clear_run_is_unchanged():
    # The chosen line already clears RAIL_CLEARANCE -> byte-inert passthrough.
    box = _icon_at(600.0)  # far away
    assert _nudge_clear_of_icons(
        480.0, 100.0, 640.0, [box], (), lo_bound=440.0, hi_bound=560.0
    ) == 480.0


def test_no_better_grid_line_returns_original():
    # The whole band is boxed in: every candidate is as bad or worse, so the
    # helper must return the original x (honest failure, never a worse move).
    boxes = [_icon_at(float(x)) for x in range(440, 561, 10)]  # a wall of icons
    out = _nudge_clear_of_icons(
        480.0, 100.0, 640.0, boxes, (), lo_bound=440.0, hi_bound=560.0
    )
    assert out == 480.0
