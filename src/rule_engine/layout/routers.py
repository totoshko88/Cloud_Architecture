"""Edge classification and per-class routing (Req 7).

This module is the routers slice of the ``layout/`` package split
(scored-router release 1.8.0, Phase A, task 1.2). It holds :func:`classify_edge`,
the five per-class routers (:func:`route_straight`, :func:`route_spine`,
:func:`route_fan_out_row`, :func:`route_cross_region`, :func:`route_back_edge`),
the :data:`ROUTERS` dispatch table and :func:`route_edge`, the whole-row
lane-side decision (:func:`decide_lane_sides`) and every routing helper —
relocated **verbatim** from ``layout_engine.py``, so ``layout_engine`` (which
re-imports them) resolves every router symbol with no caller edit.

This is a **behavior-preserving mechanical relocation**: every symbol name,
default and body is identical to its pre-split definition.

Dependencies, all leaf or already-defined by import time (no cycle):

* canonical constants + geometry helpers from :mod:`rule_engine.diagram_layout`
  / :mod:`rule_engine.geometry`;
* the model types (:class:`EdgeSpec`, :data:`Contact`, :data:`Point`) from
  :mod:`rule_engine.layout.model`;
* the two exit-band quarter constants (:data:`_UPPER_QUARTER`,
  :data:`_LOWER_QUARTER`) from :mod:`rule_engine.layout.contacts`;
* :class:`CorridorExhaustedError` from :mod:`rule_engine.layout.corridors`;
* two base symbols still living in ``layout_engine`` — :class:`SpecError` and
  :func:`_snap` — imported back by name (``layout_engine`` defines both before
  it imports this module).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

try:  # package-relative import when used as ``rule_engine.layout.routers``
    from ..diagram_layout import ICON_SIZE, GRID, COL_STEP, ROW_STEP, CONTAINER_PAD
    from ..geometry import Box, LABEL_BAND, CONTAINER_LABEL_BAND, segment_crosses_box
    from .model import Contact, Point, EdgeSpec, DiagramSpec
    from .contacts import _UPPER_QUARTER, _LOWER_QUARTER
    from .corridors import CorridorAllocator, CorridorExhaustedError
    from .base import SpecError, _snap, REGION_GAP
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import ICON_SIZE, GRID, COL_STEP, ROW_STEP, CONTAINER_PAD  # type: ignore[no-redef]
    from geometry import Box, LABEL_BAND, CONTAINER_LABEL_BAND, segment_crosses_box  # type: ignore[no-redef]
    from layout.model import Contact, Point, EdgeSpec, DiagramSpec  # type: ignore[no-redef]
    from layout.contacts import _UPPER_QUARTER, _LOWER_QUARTER  # type: ignore[no-redef]
    from layout.corridors import CorridorAllocator, CorridorExhaustedError  # type: ignore[no-redef]
    from layout.base import SpecError, _snap, REGION_GAP  # type: ignore[no-redef]


EDGE_KINDS = ("straight", "spine", "fan-out-row", "cross-region", "back-edge")

#: A rightward source→target separation at or beyond this distance reads as a
#: *cross-region* hop (A→B) rather than an in-region same-row fan-out. It must
#: sit **above** the widest in-region fan-out span and **below** the region-B
#: offset: with 4-column bands an in-region fan-out spans up to 3·COL_STEP (660),
#: while region B is region-A-extent + REGION_GAP away (~1180). ``REGION_GAP +
#: 2·COL_STEP`` (880) lands cleanly between them, so a 3-column in-region fan-out
#: (e.g. app→objstore) is NOT mistaken for a cross-region hop. Genuine
#: cross-region edges are additionally declared via ``kind_hint`` in the spec.
CROSS_REGION_SPAN = REGION_GAP + 2 * COL_STEP


class UnclassifiableEdgeError(ValueError):
    """Raised when an edge matches none of the five :data:`EDGE_KINDS`.

    The engine covers exactly the classes present in the HA diagrams; an edge
    that classifies as none raises rather than emitting a guessed route
    (fail-honest, Req 7.1 / design.md scope guard). The message names the edge
    and the source/target geometry so the gap is actionable."""


def _same_row(a: Box, b: Box) -> bool:
    """True when two boxes share a row (equal top edge)."""
    return a.y == b.y


def classify_edge(edge: EdgeSpec, placed: Dict[str, Box]) -> str:
    """Classify ``edge`` into one of the five :data:`EDGE_KINDS` (Req 7.1).

    Classification is pure geometry from the source/target boxes, applied in a
    fixed priority order so it is deterministic:

    1. ``back-edge`` — the target's column is **left of** the source
       (``target.x < source.x``): the edge must loop out the right and re-enter
       the target's left (Req 7.6). Checked first because a left-ward target is
       a back-edge regardless of row.
    2. ``straight`` — the target sits **directly opposite on the same row**, to
       the right and adjacent (one column step), with nothing between: a single
       centred segment (Req 7.2).
    3. ``cross-region`` — the target is **far** to the right (≥
       :data:`CROSS_REGION_SPAN`) on roughly the same tier: a region A→B hop
       that rises into its own over-row corridor and enters the target's top
       (Req 7.5).
    4. ``fan-out-row`` — the target is on the **same row**, to the right, but not
       adjacent (a later column on the row): the source fans out to several
       same-row targets, each in its own below-row lane (Req 7.4).
    5. ``spine`` — otherwise a tier hop within a region (a different row, to the
       right or same column-ish): route through a side corridor beside the
       column into the target's near face (Req 7.3).

    An ``edge.kind_hint`` that names a valid kind overrides the derivation
    (design.md — an optional hint, never a coordinate). An edge matching none of
    the five raises :class:`UnclassifiableEdgeError` (Req 7.1 scope guard).
    """
    if edge.kind_hint is not None:
        if edge.kind_hint not in EDGE_KINDS:
            raise UnclassifiableEdgeError(
                f"edge {edge.id!r} declares unknown kind_hint {edge.kind_hint!r}; "
                f"kind must be one of {EDGE_KINDS}"
            )
        return edge.kind_hint

    src = placed[edge.source]
    tgt = placed[edge.target]
    dx = tgt.x - src.x
    dy = tgt.y - src.y

    # 1. back-edge: target column strictly left of the source.
    if dx < 0:
        return "back-edge"

    # 2. straight: same row, adjacent to the right, nothing between.
    if _same_row(src, tgt) and 0 < dx <= COL_STEP + src.w:
        return "straight"

    # 3. cross-region: a large rightward hop at roughly the same tier.
    if dx >= CROSS_REGION_SPAN and abs(dy) <= ROW_STEP:
        return "cross-region"

    # 4. fan-out-row: same row, to the right, but not adjacent.
    if _same_row(src, tgt) and dx > 0:
        return "fan-out-row"

    # 5. spine: a tier hop within a region (different row, rightward/near column).
    if dy != 0 and dx >= 0:
        return "spine"

    raise UnclassifiableEdgeError(
        f"edge {edge.id!r} ({edge.source!r}->{edge.target!r}) matches no known "
        f"edge class (dx={dx}, dy={dy}); classes are {EDGE_KINDS}"
    )


# -- routing helpers --------------------------------------------------------


def _contact_point(box: Box, contact: Contact) -> Point:
    """Return the absolute ``(x, y)`` of a unit-square ``contact`` on ``box``."""
    fx, fy = contact
    return (box.x + fx * box.w, box.y + fy * box.h)


def _grid_contact(box: Box, contact: Contact) -> Contact:
    """Return ``contact`` adjusted so its ABSOLUTE point lands on the grid.

    An icon is 78px, so a face-centre fraction (0.5) resolves to ``x0+39`` — off
    the 10-grid — while routed waypoints are grid-snapped. That 1px mismatch is
    what skewed every arrowhead. Snapping the *fraction* so the absolute contact
    equals ``_snap(x0 + f·78)`` makes the arrow land exactly where the final
    grid-aligned waypoint sits: no kink, and every waypoint stays on the grid.
    The fraction is nudged by at most ~half a grid step, so the contact stays on
    the same face band (0.5 → ~0.513), preserving the directional contract and
    the distinct-exit spread."""
    fx, fy = contact
    ax = box.x + fx * box.w
    ay = box.y + fy * box.h
    nfx = (_snap(ax) - box.x) / box.w if box.w else fx
    nfy = (_snap(ay) - box.y) / box.h if box.h else fy
    return (nfx, nfy)


def _obstacles_between(
    p: Point, q: Point, obstacles: List[Box]
) -> List[Box]:
    """Return the obstacle boxes a straight ``p``→``q`` run would cross.

    Uses the **same** segment-sampling predicate the ``check_edge_routing``
    validator uses (:func:`geometry.segment_crosses_box`), so the router's
    obstacle test and the acceptance oracle agree by construction (Req 7.7)."""
    return [b for b in obstacles if segment_crosses_box(p, q, b)]


def _relevant_obstacles(edge: EdgeSpec, obstacles: List[Box]) -> List[Box]:
    """Drop the edge's own endpoints from the obstacle set."""
    return [b for b in obstacles if b.id not in (edge.source, edge.target)]


def route_straight(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
) -> List[Point]:
    """Route a ``straight`` edge as a single centred segment (Req 7.2).

    A straight edge connects a directly-opposite adjacent target, so no
    intermediate waypoint is needed: draw.io draws the orthogonal segment from
    the pinned exit to the pinned entry. Returns ``[]`` (no interior waypoints)
    — the empty list *is* the single centred segment. The caller supplies the
    placed boxes only to assert the run crosses nothing (it cannot, by the
    adjacency precondition)."""
    return []


def _stair_first_waypoint(
    src: Box, exit_pt: Contact, toward_down: bool
) -> Point:
    """Return the first stair waypoint: a PURELY HORIZONTAL step off the exit.

    The stair rule (diagram-standards): step one grid corridor off the glyph
    **before** turning. The step-out must be **horizontal only** — it keeps the
    exit's own ``y`` and moves ``x`` right — so the first segment leaves the
    right face straight (not a diagonal), and the arrow/stub is not skewed at the
    glyph (the "перекошена стрілка" defect). The *next* waypoint (the corridor
    drop, set by each router) then moves ``y``, so the two waypoints together
    form a clean right-angle stair with neither axis collapsing.

    ``toward_down`` is retained for signature stability but no longer nudges
    ``y`` (that nudge is what skewed the stub); the vertical turn happens at the
    router's corridor waypoint instead. The exit ``y`` is grid-aligned because
    the contact fraction is grid-resolving (:func:`_grid_contact`), so the
    horizontal step-out is level and stays on the grid."""
    ex, ey = _contact_point(src, exit_pt)
    return (_snap(ex + GRID), _snap(ey))


def _gap_column_x(allocator: "CorridorAllocator", src: Box, edge_id: str) -> float:
    """Allocate a distinct vertical-corridor x in the gap right of ``src``.

    Every vertical leg (a spine drop, or a fan-out / cross-region step-out) that
    runs in the gap immediately right of a source column takes a line from the
    SAME physical gap namespace (``vcol:<gap-left-x>``), so unrelated vertical
    runs in one gap land on DISTINCT grid lines instead of all defaulting to
    ``src_right + GRID`` and merging. This is what keeps a tier-skipping spine
    (e.g. lb→app-az2) off the fan-out step-out lanes in the same gap without any
    repair pass (``check_corridor_sharing`` clean by construction)."""
    gap_left = int(src.right)
    gap_low, gap_high = allocator.column_gap(src.x, src.x + COL_STEP)
    return _snap(_allocate_or_first(allocator, f"vcol:{gap_left}", gap_low, gap_high))


def _enclosing_container(box: Box, containers: Optional[Dict[str, Box]]) -> Optional[Box]:
    """Return the SMALLEST container that fully encloses ``box`` (or ``None``)."""
    if not containers:
        return None
    best: Optional[Box] = None
    for c in containers.values():
        if c.x <= box.x and c.y <= box.y and box.right <= c.right and box.bottom <= c.bottom:
            if best is None or (c.right - c.x) < (best.right - best.x):
                best = c
    return best


def _free_left_corridor_x(
    src: Box,
    tgt: Box,
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]],
    edge_id: str,
) -> Optional[float]:
    """Return a LEFT-side corridor x for a vertical tier-skip, or ``None``.

    Generalises the reviewer's hand-route (edge 4): when a source fans down to a
    target in the SAME COLUMN but past an intermediate node, route the vertical
    in the gap to the **left** of the column and enter the target's LEFT face —
    shorter and cleaner than a right corridor that must step back across the
    column. Only returned when that left gap is genuinely usable:

    * source and target share a column (``src.x == tgt.x``);
    * the enclosing container leaves >= one GRID step between its left edge and
      the column (``col_x - container_left >= 2*GRID``, room for a corridor with
      padding);
    * no OTHER node occupies that corridor's vertical span in the left gap.

    The corridor x is placed midway in the left gap, snapped to the grid. When
    any condition fails (no room, an obstacle in the gap, no container) it
    returns ``None`` and the caller falls back to the default right corridor +
    top entry — so a dense/edge-hugging layout is never forced into a left rail."""
    if abs(src.x - tgt.x) > 1e-9:
        return None
    # Use the SOURCE's enclosing container: the corridor runs from the source
    # (in the VPC service row, above the AZ boxes) down into the target, so it
    # must live in the VPC's left gap — the widest usable gap — not a narrow AZ
    # inset. Fall back to the target's container, then the canvas.
    container = _enclosing_container(src, containers) or _enclosing_container(tgt, containers)
    left_edge = container.x if container is not None else 0.0
    gap = src.x - left_edge
    if gap < 2 * GRID:
        return None  # no room for a left corridor with padding
    # Place the corridor MIDWAY in the left gap (v1.6.0), clamped to stay >= one
    # GRID inside both the container edge and the node column.
    #
    # The docstring above has always said "midway", but the code took
    # ``src.x - GRID`` — the lane NEAREST the column. On the HA landscape that put
    # the tier-skip vertical 10px from ``app_a1``/``api_a1``'s left border, where a
    # 540px run reads as a second rail beside the icons — the very defect
    # diagram-standards forbids ("no long vertical run parallel to a node column"),
    # and one a reviewer corrected by hand. Centring maximises the clearance to the
    # nearest border on either side (30px instead of 10px in that gap) and is what
    # the function always claimed to do.
    centre = (left_edge + src.x) / 2.0
    lo_x, hi_x = _snap(left_edge + GRID), _snap(src.x - GRID)
    corridor_x = _snap(min(max(centre, lo_x), hi_x))
    # v1.6.0: never land ON a container border. A long vertical that coincides with
    # a nested box's edge reads as part of that edge ("a line riding along a box
    # border reads as part of the border" — diagram-standards), and the centred
    # lane in a VPC's left gap lands exactly on the nested AZ box's left edge,
    # because both are derived from the same column. Step to the nearest grid line
    # in the gap that clears every container border by one grid step, preferring
    # the smallest move so the lane stays as centred as it can be.
    lo, hi = min(src.y, tgt.y), max(src.bottom, tgt.bottom)
    borders = [
        edge_x
        for c in (containers or {}).values()
        if not (c.bottom < lo or c.y > hi)
        for edge_x in (c.x, c.right)
    ]

    def _on_border(x: float) -> bool:
        return any(abs(x - b) < GRID for b in borders)

    if _on_border(corridor_x):
        candidates = sorted(
            (x for x in range(int(lo_x), int(hi_x) + 1, GRID) if not _on_border(x)),
            key=lambda x: (abs(x - corridor_x), x),
        )
        if candidates:
            corridor_x = candidates[0]
    # The corridor must clear every OTHER node's box: reject only when a node's
    # actual box (not a padded halo) sits on the corridor line within the run.
    for b in obstacles:
        if b.id in (src.id, tgt.id):
            continue
        if b.x <= corridor_x <= b.right and not (b.bottom < lo or b.y > hi):
            return None  # an icon actually sits on the left corridor's path
    return corridor_x


def _fanout_above_row(
    src: Box,
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]],
) -> bool:
    """True when a ``fan-out-row`` hop from ``src`` belongs in the ABOVE-row lane.

    A fan-out hop has to leave its row, run across, and come back — the question
    is which side of the row it runs on. The default has always been *below*, but
    the band **above** a container's first row is free **by construction**: the
    only thing between a container's caption strip and its topmost icons is
    padding, and nothing is ever placed there. The band *below* a row is the
    opposite — it is where the next tier's spine drops, the nested AZ boxes and
    their captions all live, so a hop routed there dips through other structure
    and needs the caption-avoidance machinery to stay legal.

    So: when ``src`` sits in the **topmost row inside its enclosing container**,
    the hop runs above the row. The predicate is exactly that — no node in the
    same container sits on a higher row — which makes the lane free without
    having to prove it, and is cheap and pure enough to be evaluated twice (the
    pipeline needs it to pick the exit band, the router to pick the lane).

    Returns ``False`` when there is no enclosing container, when the caption
    strip leaves no room for a lane with padding, or when any container-mate sits
    higher — in which case the caller keeps the below-row lane.

    (This reproduces both lane moves in the reviewer's hand-route of the AWS HA
    landscape: ``WAF -> CDN`` in the account edge tier and
    ``app -> object-store`` in the first AZ row, each lifted out of the crowded
    below-row band into the empty lane above.)
    """
    container = _enclosing_container(src, containers)
    if container is None:
        return False
    lane_low = container.y + CONTAINER_LABEL_BAND
    if src.y - lane_low < 2 * GRID:
        return False        # caption strip leaves no room for a lane with padding
    for b in obstacles:
        if b.id == src.id:
            continue
        if b.y < src.y and _box_contains(container, b):
            return False    # a higher row in this container → the band is not free
    return True


def route_spine(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]] = None,
) -> List[Point]:
    """Route a ``spine`` tier hop through a side corridor beside the column (Req 7.3).

    Shape: exit the source's right, step one ``GRID`` into the inter-column gap
    (the stair), drop in a corridor **beside** the node column (never straight
    down the column), then turn into the target's near face. The vertical drop x
    is an allocated corridor line in the gap immediately right of the source
    column, so the run clears the icons stacked in that column and stays distinct
    from any fan-out step-out sharing that gap.

    **Adaptive left corridor (v1.5.1).** When the target sits in the SAME COLUMN
    past an intermediate node and the column's LEFT gap is free
    (:func:`_free_left_corridor_x`), the run instead drops in the **left**
    corridor and enters the target's **LEFT** face — the reviewer's hand-route
    for edge 4 (lb→app-az2), shorter than a right corridor that must step back
    across the column. Both a left entry and a top entry are contract-legal, so
    ``edge-direction`` is unaffected; the left route is taken only when the gap
    is genuinely usable, else it falls back to the right-corridor + top entry."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    # Straight vertical drop (Exception I, compact flow): a bottom-centre exit
    # into a top-centre entry on the same column is a single clean vertical —
    # no side corridor, no hook. draw.io draws the orthogonal segment between the
    # two pinned contacts, so no interior waypoints are needed.
    if exit_pt[1] >= 1.0 and entry_pt[1] <= 0.0 and abs(src.x - tgt.x) < 1e-9:
        return []

    # Adaptive LEFT corridor for a same-column tier-skip past an intermediate
    # node (edge-4 generalisation). The caller (_place_and_route) pins a bottom
    # exit + LEFT entry when the left gap is free; honour that here by dropping
    # in the left corridor into the target's left face. Guarded on the pinned
    # contacts AND a re-check that the left gap is usable, so a caller that did
    # not set this shape falls through to the default right-corridor route.
    bottom_exit = exit_pt[1] >= 1.0
    left_entry = entry_pt[0] is not None and entry_pt[0] <= 0.0
    left_x = _free_left_corridor_x(src, tgt, others, containers, edge.id)
    if bottom_exit and left_entry and left_x is not None:
        exit_src = _contact_point(src, exit_pt)
        entry_left = _contact_point(tgt, entry_pt)
        turn_y = _snap(entry_left[1])
        waypoints = [
            (_snap(exit_src[0]), _snap(src.bottom + GRID)),  # step down off the glyph
            (left_x, _snap(src.bottom + GRID)),              # into the left corridor
            (left_x, turn_y),                                # drop to the target row
            (_snap(entry_left[0] - GRID), turn_y),           # step in to the left face
        ]
        waypoints = _dedupe_axis_collapse(waypoints, waypoints[0])
        route = [exit_src] + waypoints + [entry_left]
        route = _detour_clockwise_if_blocked(route, others)
        return _interior_waypoints(route)

    entry = _contact_point(tgt, entry_pt)
    down = tgt.y >= src.y
    first = _stair_first_waypoint(src, exit_pt, toward_down=down)

    # Side corridor x: an allocated grid line in the gap right of the source,
    # shared with every other vertical leg in that gap (see _gap_column_x).
    corridor_x = _gap_column_x(allocator, src, edge.id)
    # The stair's first waypoint moves onto the same allocated corridor x, so the
    # vertical leg and its step-out are one line (no doubled stub).
    first = (corridor_x, first[1])

    # Rule E: step INTO the target's corridor before entering its face — mirror
    # of the exit stair. A TOP entry (spine descending into a target below):
    # drop the corridor to one grid step above the target, step across to the
    # target's centre x, then descend into the top. A LEFT entry: drop to the
    # entry row, then run across into the left face.
    top_entry = entry_pt[1] <= 0.0
    if top_entry:
        # Approach lane above the TARGET's row, ALLOCATED from the same
        # ``hcorr-above:<row>`` namespace every long-haul corridor uses (v1.6.0).
        # It used to be a hard-coded ``entry_y - GRID``, which is the first line of
        # that band — so a cross-region or fan-out run that legitimately allocated
        # the same line ended up sharing the corridor with this step-across
        # (``l9``x``l10``). Allocating it makes the lane distinct by construction.
        band_lo, band_hi = _hcorridor_band(edge, tgt, tgt, False, containers)
        step_y = _snap(_allocate_or_first(
            allocator, f"hcorr-above:{int(tgt.y)}", band_lo, band_hi
        ))
        waypoints = [
            first,
            (corridor_x, step_y),               # drop in the side corridor
            (_snap(entry[0]), step_y),          # step across above the target
            (_snap(entry[0]), _snap(entry[1])), # descend into the top face
        ]
    else:
        turn_y = _snap(entry[1])
        waypoints = [first, (corridor_x, first[1]), (corridor_x, turn_y)]
    waypoints = _dedupe_axis_collapse(waypoints, first)

    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    route = _detour_clockwise_if_blocked(route, others)
    return _interior_waypoints(route)


def route_fan_out_row(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]] = None,
    lane_above: Optional[bool] = None,
) -> List[Point]:
    """Route a ``fan-out-row`` edge in its own off-row lane (Req 7.4).

    Shape (right exit, the default): exit the source right (the stair moves both
    axes), step one ``GRID`` into an off-row corridor allocated for this edge, run
    across **clear of the row** to the gap immediately left of the target, then
    turn back into the target's left face. Each fan-out edge takes its own lane so
    parallel runs never merge (``check_corridor_sharing`` clean).

    **Lane side (v1.6.0).** The lane runs **above** the row when the source sits
    in the topmost row of its container and **below** otherwise — see
    :func:`_fanout_above_row` for why the above-row band is the better lane when
    it exists. The pipeline reads the same predicate to pick the exit band
    (:func:`_place_and_route` step 2b4), so an above-lane hop leaves from the
    *upper* band and a below-lane hop from the *lower* one; the stub therefore
    always leaves toward the lane it will run in and never crosses a sibling on
    the way there.

    Shape (BOTTOM exit — the overflow-valve spill, v1.5.1): when the source's
    RIGHT face is over-connected, the pipeline (:func:`_place_and_route` step 1d)
    spills the farthest fan-out edge(s) onto the source's **bottom** face
    (``exit_pt[1] >= 1.0``) so the right face keeps at most two clean lanes.
    A bottom-exit fan-out honours that exit: it drops **straight down** from the
    bottom contact into its OWN below-row lane (no right-side stair — the stair
    would run rightward across the row and re-tangle with the right-face
    siblings, the exact defect the valve exists to remove), then proceeds like
    the normal fan-out — across below the row, up into the target's left face.
    The drawn polyline therefore starts by going *down* from the pinned bottom
    contact, so the stored ``exit`` matches where the polyline actually begins
    (no exit/route mismatch)."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    entry = _contact_point(tgt, entry_pt)
    exit_abs = _contact_point(src, exit_pt)

    bottom_exit = exit_pt[1] is not None and exit_pt[1] >= 1.0

    # Lane side (v1.6.0). ABOVE the row when the pipeline said so
    # (:func:`decide_lane_sides`), else the local default — the topmost row in a
    # container has a free band above it (:func:`_fanout_above_row`). A BOTTOM-face
    # exit (the overflow-valve spill) always stays below: it leaves the source
    # going down, so an above-row lane would make it double back across its own
    # caption. The band itself and its caption clamps are the one shared definition
    # every long-haul router uses (:func:`_hcorridor_band`), and so is the lane
    # namespace — a fan-out and a cross-region run in the same physical band get
    # DISTINCT grid lines (``check_corridor_sharing`` clean by construction).
    if lane_above is None:
        above = not bottom_exit and _fanout_above_row(src, obstacles, containers)
    else:
        above = not bottom_exit and lane_above
    row_low, row_high = _hcorridor_band(edge, src, tgt, not above, containers)
    side = "above" if above else "below"
    lane_y = _snap(_allocate_or_first(allocator, f"hcorr-{side}:{int(src.y)}", row_low, row_high))

    # Turn back toward the row in the gap just LEFT of the target (target_x -
    # ~half a gap): UP from a below-row lane, DOWN from an above-row one.
    turn_x = _snap(tgt.x - (COL_STEP - ICON_SIZE) // 2)

    if bottom_exit:
        # Honour the bottom exit: drop STRAIGHT DOWN from the bottom contact into
        # this edge's own below-row lane, then run across and up into the target
        # left. No gap-column step-out and no right-side stair, so the run leaves
        # the source going down (matching the pinned bottom exit) and never runs
        # rightward across the source row where it would re-cross the right-face
        # siblings the valve spilled it away from.
        drop_x = _snap(exit_abs[0])
        waypoints = [
            (drop_x, lane_y),               # straight drop into the below-row lane
            (turn_x, lane_y),               # run across below the row
            (turn_x, _snap(entry[1])),      # turn up into the target's left face
        ]
        waypoints = _dedupe_axis_collapse(waypoints, waypoints[0])
        route = [exit_abs] + waypoints + [entry]
        route = _detour_clockwise_if_blocked(route, others)
        return _interior_waypoints(route)

    first = _stair_first_waypoint(src, exit_pt, toward_down=lane_y > src.y)

    # Step-out vertical leg: an allocated column line in the gap right of the
    # source, shared with every other vertical leg in that gap (see
    # _gap_column_x), so the fan-out step-out never coincides with a spine drop.
    step_x = _gap_column_x(allocator, src, edge.id)
    first = (step_x, first[1])

    waypoints = [
        first,
        (first[0], lane_y),
        (turn_x, lane_y),
        (turn_x, _snap(entry[1])),
    ]
    waypoints = _dedupe_axis_collapse(waypoints, first)
    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    route = _detour_clockwise_if_blocked(route, others)
    return _interior_waypoints(route)


def _hcorridor_below(src: Box, tgt: Box) -> bool:
    """True when a long horizontal run from ``src`` uses the corridor BELOW its row.

    Two reasons to run below rather than above: there is no room above (the source
    sits in the top band, so an above corridor would rise out of the account box),
    or the target sits a full row or more **below** — a downward hop reads better
    routed downward, and routing it above makes it climb over its own row only to
    come back down.

    Shared by :func:`route_cross_region` and :func:`route_back_edge` so that the
    exit band chosen by the pipeline (:func:`_place_and_route` step 2b4) is on the
    same side as the corridor the router will actually allocate. ``route_back_edge``
    used to decide this on canvas room alone, which sent the worker→API-tier hop
    UP over the edge tier and back down the far side of the diagram even though its
    target was two rows below it."""
    return (src.y - ROW_STEP) <= CONTAINER_PAD or tgt.y >= src.y + ROW_STEP


def _exit_band_rank(
    edge: EdgeSpec,
    kind: str,
    placed: Dict[str, Box],
    lane_above: Dict[str, bool],
) -> int:
    """Rank an edge along its exit face: negative = upper, 0 = centre, positive = lower.

    The rank is read off the route the edge will actually take — ``lane_above``
    holds the corridor side the pipeline already decided for it — which is what
    makes the band ordering correct rather than cosmetic:

    * a branch whose corridor runs **above** the row must leave from an **upper**
      band and one running **below** from a **lower** band. Leave from the wrong
      side and the stub has to travel back across the face to reach its lane,
      cutting through every sibling on the way — the ``l19``/``l20`` tangle, where
      a descending fan-out left from *above* the level run it then crossed.
    * a **level** branch (a straight run to a same-row neighbour) ranks 0 and keeps
      the centre: a straight line is the most readable route and it is the one
      route with no turn for a sibling to cross.
    * among branches on the same side, one that runs **back** (turns and heads
      left) ranks outermost. Its turn column is necessarily the *nearest* lane to
      the face, so a sibling turning farther out would cross it at the stub
      (``dns -> lb_a`` cutting ``dns -> lb_b``).
    """
    src, tgt = placed[edge.source], placed[edge.target]
    if kind == "straight":
        return 0
    if kind in ("fan-out-row", "cross-region", "back-edge"):
        above = lane_above.get(edge.id, False)
    elif kind == "spine":
        above = tgt.y < src.y
    else:
        return 0
    back = tgt.x <= src.x          # the run heads LEFT after its turn
    if above:
        return -2 if back else -1
    return 2 if back else 1


def decide_lane_sides(
    spec: DiagramSpec,
    placed: Dict[str, Box],
    containers: Optional[Dict[str, Box]],
    exits: Dict[str, Contact],
    entries: Dict[str, Contact],
) -> Dict[str, bool]:
    """Decide, per long-haul edge, whether its horizontal corridor runs ABOVE its row.

    A fan-out, a cross-region hop and a back-edge all run one long horizontal leg
    in a row gap. *Which* gap used to be decided inside each router from purely
    local rules — fan-out: always below; cross-region and back-edge: whether there
    was canvas room above — and a local rule cannot see the two things that
    actually decide it:

    * **The band above a container's first row is empty by construction**
      (:func:`_fanout_above_row`), so it is the better lane for a fan-out — *unless*
      an inbound TOP-entry approach has to cross it, in which case the fan-out
      would cut that approach. That is the ``l7``-into-``db_a2`` case: the drop
      into the lower AZ arrives through exactly the band the fan-out wanted. The
      test is per-run: an approach column strictly inside the run's horizontal
      extent blocks the above lane; one outside it (``l3`` dropping into
      ``app_a1`` at the far left, while the fan-out runs off to the right) does
      not.
    * **Two long runs leaving the same row in the same direction must not take the
      same side**, or the second's turn leg crosses the first's run — the two
      replication hops ``l10``x``l11``. They alternate: the first (by marker)
      keeps its natural side, the next flips, and so on. A flip is only taken when
      the other side is legal (there is no room above a top-row source, which is
      why the edge tier's two back-edges both stay below).

    Among several above-capable fan-out branches from ONE source, only the
    **farthest** takes the above lane and the rest stay below, so the two sides
    are used one each instead of stacking on one. That is the reviewer's split of
    ``app_a1``'s fan-out: the long ``-> object-store`` run gets the empty lane
    above, the shorter ``-> database`` run keeps the band below.

    Returns ``{edge_id: True}`` for an above corridor, ``False`` for below; edges
    with no horizontal corridor are absent.
    """
    order_index = {e.id: i for i, e in enumerate(spec.edges)}
    obstacles = list(placed.values())

    def _mk(eid: str):
        m = spec.edges[order_index[eid]].marker
        return (0, int(m)) if m.isdigit() else (1, m)

    # Approach columns: the x of every TOP-face entry, grouped by the target's row.
    # A fan-out lane above that row would cut any approach whose column falls
    # inside the run.
    approach_cols: Dict[float, List[float]] = {}
    for edge in spec.edges:
        fx, fy = entries[edge.id]
        if fy is not None and fy <= 0.0:
            tgt = placed[edge.target]
            approach_cols.setdefault(tgt.y, []).append(
                tgt.x + (fx if fx is not None else 0.5) * tgt.w
            )

    sides: Dict[str, bool] = {}

    # --- fan-out-row -------------------------------------------------------
    above_capable: Dict[str, List[str]] = {}
    for edge in spec.edges:
        if classify_edge(edge, placed) != "fan-out-row":
            continue
        sides[edge.id] = False
        ey = exits[edge.id][1]
        if ey is not None and ey >= 1.0:
            continue        # a bottom-face spill leaves downward → below lane
        src, tgt = placed[edge.source], placed[edge.target]
        if not _fanout_above_row(src, obstacles, containers):
            continue
        run_lo, run_hi = src.right, tgt.x - (COL_STEP - ICON_SIZE) // 2
        if any(run_lo < col < run_hi for col in approach_cols.get(src.y, ())):
            continue        # an inbound approach must cross this band
        above_capable.setdefault(edge.source, []).append(edge.id)
    for src_id, eids in sorted(above_capable.items()):
        src = placed[src_id]
        farthest = min(
            eids,
            key=lambda e: (-(placed[spec.edges[order_index[e]].target].x - src.x), _mk(e)),
        )
        sides[farthest] = True

    # --- cross-region / back-edge -----------------------------------------
    # One band, non-overlapping runs. Two long horizontal runs in one row band do
    # get distinct *lanes* from the allocator, but distinct lanes are not enough:
    # each run turns vertically at its ends, and when two runs' horizontal extents
    # overlap, those turn legs cut through the sibling's lane whichever lane each
    # got. (``l8``'s turn down into the object store slicing ``l10``'s replication
    # run, both in the band above the app row — and symmetrically ``l10``'s rise
    # slicing ``l8``'s run, so no lane ordering fixes it.) Overlapping extents
    # therefore belong on OPPOSITE sides of the row.
    #
    # So: claim extents per (row, side). The fan-out runs decided above are seeded
    # first, because their side is forced by the container geometry, then each
    # long-haul edge takes the first side whose claims it does not overlap,
    # preferring its natural side. This is what puts the two replication hops on
    # opposite sides of the app row — the near one below with the fan-out that
    # overlaps it, the far one above where nothing does.
    claimed: Dict[Tuple[float, bool], List[Tuple[float, float]]] = {}

    def _span(src: Box, tgt: Box) -> Tuple[float, float]:
        """The horizontal extent a long run covers, conservatively."""
        return (min(src.x, tgt.x), max(src.right, tgt.right))

    def _overlaps(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
        return a[0] < b[1] and b[0] < a[1]

    for eid, above in sorted(sides.items()):
        edge = spec.edges[order_index[eid]]
        src, tgt = placed[edge.source], placed[edge.target]
        run_lo, run_hi = src.right, tgt.x - (COL_STEP - ICON_SIZE) // 2
        claimed.setdefault((src.y, above), []).append(
            (min(run_lo, run_hi), max(run_lo, run_hi))
        )

    for edge in sorted(
        (e for e in spec.edges
         if classify_edge(e, placed) in ("cross-region", "back-edge")),
        key=lambda e: _mk(e.id),
    ):
        src, tgt = placed[edge.source], placed[edge.target]
        natural = not _hcorridor_below(src, tgt)
        room_above = (src.y - ROW_STEP) > CONTAINER_PAD
        span = _span(src, tgt)
        options = [natural, not natural] if room_above else [False]
        chosen = options[0]
        for above in options:
            if not any(_overlaps(span, s) for s in claimed.get((src.y, above), ())):
                chosen = above
                break
        sides[edge.id] = chosen
        claimed.setdefault((src.y, chosen), []).append(span)

    return sides


def _assign_exit_bands(ranked: List[Tuple[str, int]]) -> Dict[str, float]:
    """Hand out distinct bands on ONE exit face, top to bottom, honouring ranks.

    ``ranked`` is ``(edge_id, rank)`` already sorted by ``(rank, marker)``. A
    level branch (rank 0) keeps the face **centre** (Req 5.1); the others take the
    band on the side their own route leaves toward, so every stub diverges from
    the glyph instead of crossing a sibling to reach its lane. Bands come from the
    same three-step ladder as before (0.25 / 0.5 / 0.75), each ≥
    :data:`MERGE_THRESHOLD` apart, so ``check_exit_thirds`` stays clean.
    """
    if len(ranked) == 1:
        return {ranked[0][0]: 0.5}
    if len(ranked) == 2:
        (a_id, a_rank), (b_id, _b_rank) = ranked
        if a_rank < 0:
            return {a_id: _UPPER_QUARTER, b_id: 0.5}
        return {a_id: 0.5, b_id: _LOWER_QUARTER}
    bands = (_UPPER_QUARTER, 0.5, _LOWER_QUARTER)
    return {eid: band for (eid, _r), band in zip(ranked, bands)}


def _has_free_left_approach(tgt: Box, obstacles: List[Box]) -> bool:
    """True when the target's LEFT face has a clear horizontal approach.

    A cross-region run can enter the target's LEFT face (instead of dropping into
    its TOP over the AZ caption) when no other node sits immediately to the
    target's left on its row — i.e. the target is the leftmost-reachable in its
    row from the left, with >= one grid step of clear approach. Used to decide
    whether a cross-region hop routes below-row + left-entry (the reviewer's l11
    route) rather than over-row + top-entry."""
    for b in obstacles:
        if b.id == tgt.id:
            continue
        same_row = abs(b.y - tgt.y) < tgt.h
        to_left = b.right <= tgt.x and (tgt.x - b.right) < 2 * GRID
        if same_row and to_left:
            return False
    return True


def _target_container_top(
    edge: EdgeSpec, containers: Optional[Dict[str, Box]], tgt: Box
) -> Optional[float]:
    """Return the top y of the SMALLEST container enclosing the target box.

    Superseded for corridor sizing by :func:`_caption_free_band` (v1.6.0), which
    considers **every** container in the band rather than only the target's
    innermost one; kept because the adaptive-entry decisions still ask "where does
    the target's own container start?".

    A long-haul corridor that drops into a target inside a VPC must not run
    along that VPC's top caption band. This returns the enclosing container's
    top edge so the router can keep its horizontal corridor ABOVE it (a
    ``below``-side corridor caps its ``row_high`` at this y). ``None`` when there
    are no containers (synthetic specs) or the target sits in none."""
    if not containers:
        return None
    best: Optional[Box] = None
    for c in containers.values():
        if c.x <= tgt.x and c.y <= tgt.y and tgt.right <= c.right and tgt.bottom <= c.bottom:
            if best is None or (c.right - c.x) < (best.right - best.x):
                best = c
    return best.y if best is not None else None


def _box_contains(outer: Box, inner: Box) -> bool:
    """True when ``inner`` sits wholly within ``outer``."""
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.right <= outer.right
        and inner.bottom <= outer.bottom
    )


def _caption_free_band(
    row_low: float,
    row_high: float,
    containers: Optional[Dict[str, Box]],
    src: Box,
) -> Tuple[float, float]:
    """Narrow a horizontal corridor band so it excludes every container caption.

    A draw.io group draws its caption *inside* its own top edge, so the strip
    ``[c.y, c.y + CONTAINER_LABEL_BAND)`` of every container is occupied by text.
    A corridor lane allocated in that strip runs along the caption — the
    ``edge-crosses-container-label`` finding.

    Before v1.6.0 only ``_target_container_top`` guarded this, and only in two
    routers, and only against the target's **innermost** enclosing container. That
    left three real gaps, all of which the re-connected landscape hit:

    * a run whose target is in an **AZ** was capped against the AZ's top and still
      crossed the enclosing **VPC**'s caption (the worker→API-tier hop);
    * a run between two nodes that are **both outside** the container it passes had
      no cap at all (the account-row WAF→CDN hop dipping into the VPC caption);
    * a run **inside** a container cannot be fixed by capping above that
      container's top — that would push the lane outside the box it belongs to.
      It has to sit **below** the caption instead.

    So each intersecting caption band narrows the corridor to one of two
    sub-bands — **above** the container top, or **below** its caption — and the
    preferred side is the one that keeps the run on the correct side of that
    container: a source *inside* the container prefers below (stay in the box,
    under the text), a source outside prefers above (stay out of the box). When
    the preferred sub-band collapses (the caption straddles the corridor's own
    lower edge, which is what the account-row fan-out hit), the other side is
    taken instead; when both collapse the original band stands, so the WARNING
    still surfaces rather than the router emitting a degenerate lane. Containers
    are visited top-down, so the result is deterministic.
    """
    if not containers:
        return row_low, row_high
    for c in sorted(containers.values(), key=lambda b: (b.y, b.id)):
        cap_lo, cap_hi = c.y, c.y + CONTAINER_LABEL_BAND
        if cap_hi <= row_low or cap_lo >= row_high:
            continue  # this caption band is outside the corridor band
        above = (row_low, min(row_high, cap_lo))
        below = (max(row_low, cap_hi), row_high)
        options = (below, above) if _box_contains(c, src) else (above, below)
        for lo, hi in options:
            if hi - lo >= GRID:
                row_low, row_high = lo, hi
                break
    return row_low, row_high


def _column_is_clear(
    x: float, y_lo: float, y_hi: float, obstacles: List[Box], skip: Tuple[str, ...]
) -> bool:
    """True when no node box other than ``skip`` sits on the vertical line ``x``
    between ``y_lo`` and ``y_hi``."""
    lo, hi = sorted((y_lo, y_hi))
    for b in obstacles:
        if b.id in skip:
            continue
        if b.x <= x <= b.right and not (b.bottom <= lo or b.y >= hi):
            return False
    return True


def _free_drop_column(
    tgt: Box,
    across: float,
    from_y: float,
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]],
) -> float:
    """Return a free column to descend in before entering ``tgt``'s TOP face.

    The natural drop column for a top entry is the target's own centre
    (``across``), and when that column is clear between the corridor and the
    target it is also the best one — one turn, no detour. But when the target sits
    at the bottom of a **stacked column** (load balancer over app tier over API
    tier, all at one x), that column is full: the drop cuts through every icon
    above the target, and the clockwise detour then pushes it a couple of pixels
    off their right border, where a long vertical reads as a second rail beside the
    services.

    So: prefer ``across``; else the midway line in the gap to the target's **left**
    (kept ≥ one grid step inside the enclosing container and the target column);
    else the midway line in the gap to its **right**. The first candidate whose
    column is clear wins. When none is, fall back to ``across`` and let the detour
    handle it — the honest failure, not a silently wrong route.
    """
    if _column_is_clear(across, from_y, tgt.y, obstacles, (tgt.id,)):
        return across
    container = _enclosing_container(tgt, containers)
    left_edge = container.x if container is not None else 0.0
    right_edge = container.right if container is not None else tgt.right + COL_STEP
    candidates = []
    if tgt.x - left_edge >= 2 * GRID:
        centre = (left_edge + tgt.x) / 2.0
        candidates.append(_snap(min(max(centre, left_edge + GRID), tgt.x - GRID)))
    if right_edge - tgt.right >= 2 * GRID:
        centre = (tgt.right + right_edge) / 2.0
        candidates.append(_snap(max(min(centre, right_edge - GRID), tgt.right + GRID)))
    for x in candidates:
        if _column_is_clear(x, from_y, tgt.y, obstacles, (tgt.id,)):
            return x
    return across


def _hcorridor_band(
    edge: EdgeSpec,
    src: Box,
    tgt: Box,
    below: bool,
    containers: Optional[Dict[str, Box]],
) -> Tuple[float, float]:
    """Return the ``(low, high)`` band a long horizontal run may use on one side.

    One definition for all three long-haul routers (cross-region, back-edge,
    fan-out), because it *is* one physical band:

    * **below** — the gap under the source row, starting past the source's own
      LABEL BAND (Rule F) so the run does not cross the captions of the row it
      leaves;
    * **above** — the gap over the source row, starting past the LABEL BAND of the
      row above, for the same reason.

    Then two clamps, both about container captions: cap the band at the target
    container's top edge when that edge falls inside it, and remove every
    container caption strip the band still overlaps
    (:func:`_caption_free_band`). Callers allocate their lane from the returned
    band, sharing one ``hcorr-<side>:<row>`` namespace so any two runs in the same
    physical band get DISTINCT grid lines.
    """
    if below:
        row_low = src.y + ICON_SIZE + LABEL_BAND + GRID
        row_high = src.y + ROW_STEP
    else:
        row_low = (src.y - ROW_STEP) + ICON_SIZE + LABEL_BAND + GRID
        row_high = src.y
    ceil = _target_container_top(edge, containers, tgt)
    if ceil is not None and row_low < ceil < row_high:
        row_high = _snap(ceil)
    return _caption_free_band(row_low, row_high, containers, src)


def route_cross_region(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]] = None,
    lane_above: Optional[bool] = None,
) -> List[Point]:
    """Route a ``cross-region`` A→B hop through its own over-row corridor (Req 7.5).

    Shape: step out of the source's right into the gap (the stair moves both
    axes), rise into an over-row corridor allocated for this edge (one lane
    each), run across to above the target, then drop into the target's top
    face."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    entry = _contact_point(tgt, entry_pt)

    # Adaptive INTER-ROW corridor + LEFT entry (v1.5.1, edge-11 generalisation).
    # A same-tier cross-region hop whose target has a clear LEFT approach
    # (:func:`_has_free_left_approach`) routes in the inter-row gap BELOW the
    # source row and enters the target's LEFT face — the reviewer's l11 route.
    # This keeps the long run in the empty band between two rows rather than on
    # an AZ/VPC top caption (the caption-slice + top-entry pierce the over-row
    # route caused), and a left entry into a row-rightmost target is clean. Taken
    # only when the caller pinned a LEFT entry AND the approach is free; else the
    # default over/below-row + top-entry route stands.
    below = _hcorridor_below(src, tgt) if lane_above is None else not lane_above
    left_entry = entry_pt[0] is not None and entry_pt[0] <= 0.0
    if left_entry and _has_free_left_approach(tgt, others):
        # Inter-row corridor on the side the pipeline chose (v1.6.0): the gap under
        # the source row by default, or the one above it when a same-row sibling
        # already took the lane below (``decide_lane_sides`` alternates them, which
        # is what stops the two replication hops crossing each other).
        row_low, row_high = _hcorridor_band(edge, src, tgt, below, containers)
        side = "below" if below else "above"
        lane_y = _snap(_allocate_or_first(allocator, f"hcorr-{side}:{int(src.y)}", row_low, row_high))
        rise_x = _gap_column_x(allocator, src, edge.id)
        exit_abs = _contact_point(src, exit_pt)
        entry_left = _contact_point(tgt, entry_pt)
        left_of_tgt = _snap(tgt.x - GRID)   # step in to the left face
        waypoints = [
            (rise_x, _snap(exit_abs[1])),       # step out into the gap right of src
            (rise_x, lane_y),                   # drop into the below-row lane
            (left_of_tgt, lane_y),              # run across in the inter-row gap
            (left_of_tgt, _snap(entry_left[1])),# rise/settle to the entry row
        ]
        waypoints = _dedupe_axis_collapse(waypoints, waypoints[0])
        route = [exit_abs] + waypoints + [entry_left]
        route = _detour_clockwise_if_blocked(route, others)
        return _interior_waypoints(route)

    # The horizontal corridor side (``below``) was chosen above: the pipeline's
    # ``decide_lane_sides`` value when it supplied one, else the local default
    # (:func:`_hcorridor_below` — above the source unless it is in the top band or
    # the target sits clearly lower).
    first = _stair_first_waypoint(src, exit_pt, toward_down=below)
    # Vertical leg in the gap right of the source, distinct per gap.
    rise_x = _gap_column_x(allocator, src, edge.id)
    first = (rise_x, first[1])

    # Cross-region corridor: an allocated grid line in the row gap above (default)
    # or below (top-band / downward hop) the source. Keyed by the physical row
    # band + side, so two cross-region runs leaving the same source row (e.g.
    # db_a1->db_b1 and obj_a1->obj_b1) get DISTINCT lanes from the shared
    # allocator instead of merging (the corridor-sharing regression this fixes).
    row_low, row_high = _hcorridor_band(edge, src, tgt, below, containers)
    side = "below" if below else "above"
    # Shared horizontal-corridor namespace (``hcorr``) keyed by the physical band
    # + side, so ANY long horizontal run in this band (cross-region OR back-edge)
    # gets a DISTINCT lane from the shared allocator — two edges in different
    # per-class namespaces used to both grab the first line and merge (e.g. edge
    # 1 back-edge and edge 2 cross-region both leaving dns).
    over_y = _snap(_allocate_or_first(allocator, f"hcorr-{side}:{int(src.y)}", row_low, row_high))

    across_x = _snap(entry[0])
    waypoints = [
        first,
        (first[0], over_y),
        (across_x, over_y),
        (across_x, _snap(entry[1])),
    ]
    waypoints = _dedupe_axis_collapse(waypoints, first)
    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    route = _detour_clockwise_if_blocked(route, others)
    return _interior_waypoints(route)


def route_back_edge(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]] = None,
    lane_above: Optional[bool] = None,
) -> List[Point]:
    """Route a ``back-edge`` (target left of source) out the right and back (Req 7.6).

    Shape: exit the source's **right** (never the side it enters), step into the
    gap (the stair moves both axes), rise into a dedicated loop corridor above
    the rows, run left past the target's column, then drop into the target's
    **left** face. Exiting right and entering left is the whole point of a
    back-edge (diagram-standards → directional back-edge)."""
    src = obstacle_box(edge.source, obstacles)
    tgt = obstacle_box(edge.target, obstacles)
    others = _relevant_obstacles(edge, obstacles)

    entry = _contact_point(tgt, entry_pt)
    # Loop corridor above the source by default, but BELOW when the source is in
    # the top band (no room above → the loop would rise above the account box) OR
    # when the target sits a full row or more below — the same rule
    # ``route_cross_region`` uses (:func:`_hcorridor_below`). Deciding this on
    # canvas room alone sent a downward back-edge (the worker → API-tier hop, whose
    # target is two rows below) UP into the edge tier's gap and then back down the
    # length of the diagram, when the clean lane was the inter-row gap right below
    # the source.
    below = (_hcorridor_below(src, tgt) if lane_above is None else not lane_above)
    first = _stair_first_waypoint(src, exit_pt, toward_down=below)
    # Vertical leg in the gap right of the source, distinct per gap.
    rise_x = _gap_column_x(allocator, src, edge.id)
    first = (rise_x, first[1])

    # Dedicated loop corridor in the row gap on the chosen side, keyed by the
    # physical row band + side so parallel back-edges from the same row get
    # distinct loop lanes rather than merging on one. The band and its two caption
    # clamps are the shared definition (:func:`_hcorridor_band`).
    row_low, row_high = _hcorridor_band(edge, src, tgt, below, containers)
    side = "below" if below else "above"
    # Shared horizontal-corridor namespace (see route_cross_region): a back-edge
    # and a cross-region run in the same band+side get distinct lanes.
    loop_y = _snap(_allocate_or_first(allocator, f"hcorr-{side}:{int(src.y)}", row_low, row_high))

    if entry_pt[1] <= 0.0:
        # TOP entry (Rule G: the target has no left gap — set by the pipeline):
        # run the loop corridor across, drop toward the target, and enter its top.
        across = _snap(entry[0])
        # v1.6.0: the DROP COLUMN must be free. ``across`` is the target's own
        # centre x, which is the right answer only when nothing else stands in that
        # column. On a stacked column — a load balancer over an app tier over the
        # API tier, all at one x — the drop ran straight through every icon above
        # the target, and ``_detour_clockwise_if_blocked`` then shoved it a few
        # pixels off their right border: a 370px vertical running two pixels from
        # two service glyphs, which reads as a second rail beside the column and is
        # exactly what diagram-standards forbids. Drop in a free gap column beside
        # the target instead and step across in the lane just above it.
        drop_x = _free_drop_column(tgt, across, loop_y, others, containers)
        if drop_x == across:
            waypoints = [
                first,
                (first[0], loop_y),
                (across, loop_y),
                (across, _snap(entry[1])),
            ]
        else:
            # Approach lane above the target's row, from the shared namespace (see
            # route_spine) so it cannot land on another run's corridor.
            band_lo, band_hi = _hcorridor_band(edge, tgt, tgt, False, containers)
            approach_y = _snap(_allocate_or_first(
                allocator, f"hcorr-above:{int(tgt.y)}", band_lo, band_hi
            ))
            waypoints = [
                first,
                (first[0], loop_y),
                (drop_x, loop_y),                 # run across to the free column
                (drop_x, approach_y),             # drop beside the column
                (across, approach_y),             # step in above the target
                (across, _snap(entry[1])),        # descend into the top face
            ]
    else:
        # LEFT entry: run left in the loop corridor to the gap just left of the
        # target, then drop into its left face. Clamp so the turn stays on-canvas.
        left_x = _snap(max(tgt.x - (COL_STEP - ICON_SIZE) // 2, CONTAINER_PAD))
        waypoints = [
            first,
            (first[0], loop_y),
            (left_x, loop_y),
            (left_x, _snap(entry[1])),
        ]
    waypoints = _dedupe_axis_collapse(waypoints, first)
    route = [_contact_point(src, exit_pt)] + waypoints + [entry]
    route = _detour_clockwise_if_blocked(route, others)
    return _interior_waypoints(route)


ROUTERS = {
    "straight": route_straight,
    "spine": route_spine,
    "fan-out-row": route_fan_out_row,
    "cross-region": route_cross_region,
    "back-edge": route_back_edge,
}


def route_edge(
    edge: EdgeSpec,
    exit_pt: Contact,
    entry_pt: Contact,
    allocator: "CorridorAllocator",
    obstacles: List[Box],
    containers: Optional[Dict[str, Box]] = None,
    lane_above: Optional[bool] = None,
) -> List[Point]:
    """Classify ``edge`` and dispatch to the matching ``route_<kind>`` router.

    A thin convenience over :func:`classify_edge` + :data:`ROUTERS`. Raises
    :class:`UnclassifiableEdgeError` (via :func:`classify_edge`) for an edge that
    matches no class — the engine never guesses a route (Req 7.1).

    ``containers`` (optional) lets the corridor routers keep their horizontal lane
    clear of a container's top caption band (v1.5.1; generalised to every
    container in the band by :func:`_caption_free_band` in v1.6.0, which also
    brought ``fan-out-row`` into the set — an account-row fan-out reaching past a
    region VPC otherwise dipped into its caption). Routers that allocate no
    horizontal corridor ignore it, so synthetic specs that pass no containers are
    byte-unchanged.

    ``lane_above`` (optional, v1.6.0) carries the corridor side the pipeline chose
    for this edge (:func:`decide_lane_sides`) — a whole-row decision no single
    router can make. ``None`` means "use your own default", so a router called
    directly is unchanged."""
    placed = {b.id: b for b in obstacles}
    kind = classify_edge(edge, placed)
    if kind in ("cross-region", "back-edge", "fan-out-row"):
        return ROUTERS[kind](
            edge, exit_pt, entry_pt, allocator, obstacles, containers, lane_above
        )
    if kind == "spine":
        return ROUTERS[kind](edge, exit_pt, entry_pt, allocator, obstacles, containers)
    return ROUTERS[kind](edge, exit_pt, entry_pt, allocator, obstacles)


# -- small shared router utilities ------------------------------------------


def obstacle_box(node_id: str, obstacles: List[Box]) -> Box:
    """Return the placed box for ``node_id`` from the obstacle list."""
    for b in obstacles:
        if b.id == node_id:
            return b
    raise SpecError(f"router given no placed box for node {node_id!r}")


def _allocate_or_first(
    allocator: "CorridorAllocator", gap_id: str, low: float, high: float
) -> float:
    """Allocate a corridor line, tolerating a degenerate (empty) gap.

    A router occasionally faces a gap too narrow to hold a stride-spaced line
    (adjacent boxes, or a row gap trimmed to 30px by a container caption strip).
    Rather than fail, step down through progressively tighter options:

    1. the normal **strided** allocation (``2·GRID`` apart — visibly separate);
    2. a **dense** allocation at ``GRID`` spacing
       (:meth:`CorridorAllocator.allocate_dense`) — tighter but still distinct;
    3. only then the gap **midpoint**, which may coincide with another run.

    Step 2 exists because step 3 silently merges corridors: three runs asking for
    the one strided line above the app row all fell back to the same midpoint, so
    two of them shared a lane and the repair loop could not separate them (they
    were not *allocated* anywhere, so bumping one moved it onto the other). The
    repair loop still widens genuinely exhausted gaps; here the router just needs a
    deterministic corridor coordinate, and preferring a free line over a colliding
    one is strictly better."""
    try:
        return allocator.allocate(gap_id, low, high)
    except CorridorExhaustedError:
        pass
    try:
        return allocator.allocate_dense(gap_id, low, high)
    except CorridorExhaustedError:
        return _snap((low + high) / 2.0)


def _dedupe_axis_collapse(waypoints: List[Point], first: Point) -> List[Point]:
    """Drop consecutive duplicate waypoints while preserving the first stair step.

    The first waypoint (``first``) always changes both axes off the exit (the
    no-collapse rule); this only removes *later* points that coincide with their
    predecessor, keeping the emitted polyline minimal and orthogonal."""
    out: List[Point] = []
    for pt in waypoints:
        if not out or out[-1] != pt:
            out.append(pt)
    return out


def _corner_detour(p: Point, q: Point, obstacles: List[Box]) -> List[Point]:
    """Return the detour waypoint(s) that route a blocked ``p``→``q`` run around.

    A straight segment with no interior vertex is bent into an orthogonal detour
    that steps **off the blocked line** clockwise (up for a horizontal run, right
    for a vertical run), just past the blocking obstacles' band, then back to the
    far endpoint. Returns:

    * a single **L-corner** (share p.x/q.y or q.x/p.y) when one clears both legs
      — the ordinary case where the endpoints are not collinear;
    * a **two-waypoint** staple (off-line, across, back) when the run is
      axis-collinear with its endpoints (both on the blocked line), since a
      single corner would stay on that line.

    Endpoints are never returned, so the edge stays pinned to both node faces."""
    blockers = _obstacles_between(p, q, obstacles)
    for corner in ((_snap(p[0]), _snap(q[1])), (_snap(q[0]), _snap(p[1]))):
        if corner not in (p, q) and not _obstacles_between(
            p, corner, obstacles
        ) and not _obstacles_between(corner, q, obstacles):
            return [corner]
    # Collinear run: a two-waypoint staple past the blockers' band, clockwise.
    if abs(p[1] - q[1]) <= 1 and blockers:  # horizontal → lift up
        off = _snap(min(b.y for b in blockers) - GRID)
        return [(_snap(p[0]), off), (_snap(q[0]), off)]
    if abs(p[0] - q[0]) <= 1 and blockers:  # vertical → shift right
        off = _snap(max(b.x + b.w for b in blockers) + GRID)
        return [(off, _snap(p[1])), (off, _snap(q[1]))]
    return [(_snap(p[0]), _snap(q[1]))]


def _detour_clockwise_if_blocked(route: List[Point], obstacles: List[Box]) -> List[Point]:
    """Nudge any blocked straight segment clockwise by one corridor, in place.

    Walks the emitted polyline; where a segment would cut an unrelated obstacle
    (tested with the *same* :func:`geometry.segment_crosses_box` predicate the
    validator uses), it shifts the segment's free axis by one ``GRID`` step
    clockwise (obstacle kept on the edge's left) and retries, up to a small
    bound. Deterministic: a fixed turn direction means two agents routing the
    same edge produce the same detour (Req 7.7).

    Mutates ``route`` in place AND returns it, so a caller can capture the
    detoured polyline. The pinned endpoints (``route[0]`` exit contact,
    ``route[-1]`` entry contact) are never moved — only the interior corridor
    waypoints shift — so the edge stays attached to both nodes; the caller reads
    the detoured interior back with :func:`_interior_waypoints`.

    A **two-point** route (``[exit, entry]``, no interior) whose single straight
    segment is blocked has no interior vertex to shift, so an L-shaped corner
    waypoint is inserted (clockwise) once — turning the blocked straight run into
    a two-leg detour around the obstacle without moving either pinned end."""
    if len(route) == 2 and _obstacles_between(route[0], route[1], obstacles):
        route[1:1] = _corner_detour(route[0], route[1], obstacles)
    for i in range(len(route) - 1):
        for _ in range(4):  # bounded clockwise nudges
            blocked = _obstacles_between(route[i], route[i + 1], obstacles)
            if not blocked:
                break
            x0, y0 = route[i]
            x1, y1 = route[i + 1]
            # Never move the pinned endpoints (exit/entry contact points); only
            # an interior vertex of a blocked segment may shift onto the next
            # corridor lane, so the edge remains connected to both node faces.
            if abs(x1 - x0) <= 1:  # vertical segment → shift x clockwise (right)
                if 0 < i:
                    route[i] = (_snap(x0 + GRID), y0)
                if i + 1 < len(route) - 1:
                    route[i + 1] = (_snap(x1 + GRID), y1)
            else:  # horizontal segment → shift y clockwise (up)
                if 0 < i:
                    route[i] = (x0, _snap(y0 - GRID))
                if i + 1 < len(route) - 1:
                    route[i + 1] = (x1, _snap(y1 - GRID))
    return route


def _interior_waypoints(route: List[Point]) -> List[Point]:
    """Return a route's interior corridor waypoints (drop the pinned endpoints).

    A router emits ``[exit_contact] + waypoints + [entry_contact]`` and stores
    only the interior ``waypoints`` on the edge (draw.io re-derives the two
    contact points from ``exitX/entryX``). After :func:`_detour_clockwise_if_blocked`
    shifts a blocked interior vertex, this reads the corrected interior back so
    the detour actually reaches the emitted geometry."""
    return list(route[1:-1])
