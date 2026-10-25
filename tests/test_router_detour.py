"""Regression test for the clockwise-detour obstacle avoidance (P0 fix).

Before this fix every ``route_*`` router computed a detour into a local ``route``
list via ``_detour_clockwise_if_blocked`` and then ``return waypoints`` — the
detoured coordinates were discarded, so obstacle avoidance (Req 7.7) was dead.
The helper now returns the (mutated) route and the routers read the corrected
interior back with ``_interior_waypoints``.

These tests exercise the helper directly (deterministic, no full pipeline):
a blocked interior segment must shift clockwise by one grid step, the pinned
endpoints must never move, and an unblocked route must be returned unchanged.
"""

from __future__ import annotations

from rule_engine.layout_engine import (
    GRID,
    _detour_clockwise_if_blocked,
    _interior_waypoints,
)
from rule_engine.geometry import Box


def test_detour_shifts_blocked_interior_and_keeps_endpoints():
    # A horizontal interior run y=100 from x=0..200 straight through an obstacle
    # centred on that line. The route is [exit, wp_a, wp_b, entry]; the two
    # interior waypoints sit on the blocked corridor.
    obstacle = Box("blocker", x=80.0, y=80.0, w=40.0, h=40.0)  # covers y=100
    exit_pt = (0.0, 100.0)
    entry_pt = (200.0, 100.0)
    route = [exit_pt, (0.0, 100.0), (200.0, 100.0), entry_pt]

    result = _detour_clockwise_if_blocked(list(route), [obstacle])

    # The helper returns the (possibly mutated) route, not None.
    assert result is not None
    # Endpoints are pinned — never moved.
    assert result[0] == exit_pt
    assert result[-1] == entry_pt
    # A horizontal blocked segment shifts clockwise = up (y decreases) by >=1 grid
    # step, so the interior waypoints are lifted off the obstacle's row.
    interior = _interior_waypoints(result)
    assert all(wp[1] <= 100.0 - GRID for wp in interior)
    # And the shifted interior now clears the obstacle.
    assert not _blocks(result, obstacle)


def test_detour_inserts_corner_for_blocked_two_point_route():
    # A two-point route [exit, entry] — no interior waypoint — whose single
    # straight segment runs through an obstacle. Before the fix this route could
    # not be detoured at all (neither pinned end may move, and there is no
    # interior vertex to shift), so the blocked run was emitted verbatim.
    obstacle = Box("blocker", x=80.0, y=80.0, w=40.0, h=40.0)  # covers y=100
    exit_pt = (0.0, 100.0)
    entry_pt = (200.0, 100.0)

    result = _detour_clockwise_if_blocked([exit_pt, entry_pt], [obstacle])

    # Endpoints stay pinned; at least one detour waypoint was inserted between.
    assert result[0] == exit_pt
    assert result[-1] == entry_pt
    assert len(result) > 2
    # The detour now clears the obstacle...
    assert not _blocks(result, obstacle)
    # ...and every leg is axis-aligned (orthogonal routing preserved).
    for a, b in zip(result, result[1:]):
        assert a[0] == b[0] or a[1] == b[1], f"non-orthogonal leg {a}->{b}"


def test_detour_leaves_clear_route_untouched():
    obstacle = Box("blocker", x=80.0, y=80.0, w=40.0, h=40.0)
    # A route well below the obstacle: nothing to detour.
    route = [(0.0, 400.0), (0.0, 400.0), (200.0, 400.0), (200.0, 400.0)]
    result = _detour_clockwise_if_blocked(list(route), [obstacle])
    assert result == route


def test_interior_waypoints_drops_pinned_endpoints():
    route = [(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (30.0, 20.0)]
    assert _interior_waypoints(route) == [(10.0, 0.0), (10.0, 20.0)]


def _blocks(route, obstacle) -> bool:
    from rule_engine.geometry import segment_crosses_box

    return any(
        segment_crosses_box(route[i], route[i + 1], obstacle)
        for i in range(len(route) - 1)
    )


# --- wave-4 ITEM 4b: spine level-run shortcut ------------------------------


def _spine(src, tgt, exit_pt, entry_pt, extra=()):
    from rule_engine.layout_engine import CorridorAllocator, route_spine
    from rule_engine.layout.model import EdgeSpec
    alloc = CorridorAllocator()
    edge = EdgeSpec(id="e", source=src.id, target=tgt.id, marker="1")
    return route_spine(edge, exit_pt, entry_pt, alloc, [src, tgt, *extra])


def test_spine_level_run_with_aligned_contacts_is_a_straight_segment():
    # Two 78px icons whose TOPS differ by 20px (a band-packing quirk) but whose
    # right-face exit and left-face entry resolve to the SAME absolute y: the
    # spine router returns no interior waypoints (a single straight segment),
    # not a jog up to a corridor and back.
    src = Box("src", x=100.0, y=240.0, w=78.0, h=78.0)   # right face at y 240..318
    tgt = Box("tgt", x=600.0, y=220.0, w=78.0, h=78.0)   # left face at y 220..298
    # exitY=0.2564 -> 240 + 0.2564*78 = 260 ; entryY=0.5128 -> 220 + 0.5128*78 = 260
    exit_pt = (1.0256410256410255, 0.2564102564102564)
    entry_pt = (0.0, 0.5128205128205128)
    assert _spine(src, tgt, exit_pt, entry_pt) == []


def test_spine_level_run_with_an_obstacle_between_still_jogs():
    # Same aligned contacts, but an icon stands on the direct run: the shortcut
    # must NOT fire — the edge falls through to the side-corridor route (which
    # emits interior waypoints to go around).
    src = Box("src", x=100.0, y=240.0, w=78.0, h=78.0)
    tgt = Box("tgt", x=600.0, y=220.0, w=78.0, h=78.0)
    blocker = Box("mid", x=360.0, y=230.0, w=78.0, h=78.0)  # covers y=260 at x~360
    exit_pt = (1.0256410256410255, 0.2564102564102564)
    entry_pt = (0.0, 0.5128205128205128)
    assert _spine(src, tgt, exit_pt, entry_pt, extra=(blocker,)) != []


def test_spine_different_rows_still_jogs():
    # Contacts on genuinely different rows (a real tier hop): the shortcut does
    # not fire, so the side-corridor route is used (interior waypoints emitted).
    src = Box("src", x=100.0, y=60.0, w=78.0, h=78.0)
    tgt = Box("tgt", x=600.0, y=400.0, w=78.0, h=78.0)
    exit_pt = (1.0256410256410255, 0.5)
    entry_pt = (0.0, 0.5)
    assert _spine(src, tgt, exit_pt, entry_pt) != []


def _fanout(src, tgt, exit_pt, entry_pt, extra=()):
    from rule_engine.layout_engine import CorridorAllocator, route_fan_out_row
    from rule_engine.layout.model import EdgeSpec
    alloc = CorridorAllocator()
    edge = EdgeSpec(id="e", source=src.id, target=tgt.id, marker="1")
    return route_fan_out_row(edge, exit_pt, entry_pt, alloc, [src, tgt, *extra])


def test_fanout_row_level_run_with_aligned_contacts_is_a_straight_segment():
    # SEP 13 lambda→rds: the target's icon top sits 20px above the source's, so
    # classify_edge calls it fan-out-row (an upward hop to the right), but the
    # right-face exit and left-face entry both resolve to y=260. The fan-out
    # router returns no interior waypoints (a straight segment), not a jog up to
    # the target's row and back.
    src = Box("src", x=910.0, y=240.0, w=78.0, h=78.0)
    tgt = Box("tgt", x=1350.0, y=220.0, w=78.0, h=78.0)
    exit_pt = (1.0256410256410255, 0.2564102564102564)   # -> y 260
    entry_pt = (0.0, 0.5128205128205128)                 # -> y 260
    assert _fanout(src, tgt, exit_pt, entry_pt) == []


def test_fanout_row_with_obstacle_between_still_lanes():
    src = Box("src", x=910.0, y=240.0, w=78.0, h=78.0)
    tgt = Box("tgt", x=1350.0, y=220.0, w=78.0, h=78.0)
    blocker = Box("mid", x=1120.0, y=230.0, w=78.0, h=78.0)
    exit_pt = (1.0256410256410255, 0.2564102564102564)
    entry_pt = (0.0, 0.5128205128205128)
    assert _fanout(src, tgt, exit_pt, entry_pt, extra=(blocker,)) != []
