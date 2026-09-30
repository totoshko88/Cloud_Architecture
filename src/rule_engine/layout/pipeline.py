"""The layout pipeline: place → size → centre → (solver | legacy) → repair.

This is the pipeline slice of the ``layout/`` package split (scored-router
release 1.8.0, Phase A, task 1.3). It holds the package entry point
:func:`layout` and the retained ten-pass :func:`_place_and_route`
(``Legacy_Path``), relocated **verbatim** from ``layout_engine.py`` — so
``layout_engine`` (which re-imports them) resolves both symbols with no caller
edit and every shipped ``.drawio`` stays byte-identical.

**Behavior-preserving contract (design.md §``layout/`` package seam).** The
scored solver does **not exist yet** (Phase C, tasks 5–7). :func:`layout`
therefore orchestrates ``place → size → centre → (solver | legacy) → repair``
with the ``(solver | legacy)`` branch defaulting to the retained rule-driven
ten-pass path (:func:`_place_and_route`). The ``solver`` arm is a *seam only* —
a documented placeholder that is not wired to any solver — so with the solver
absent the default path and the ``--legacy`` path are the **same code** and the
output is unchanged (R1.1, R1.5, R1.6).

The ``--legacy`` flag is threaded from the generator entry points as the
``legacy`` keyword of :func:`layout`; it defaults to ``False`` so the current
behaviour is the default, and — until the solver lands — both values route
through :func:`_place_and_route` and produce byte-identical geometry.

Dependencies, all defined by import time (no cycle):

* the placement / contacts / corridors / routers symbols from their
  ``layout/`` submodules;
* the canonical placement constants (``TITLE_BAND``, ``_snap``) from
  :mod:`rule_engine.layout.base`;
* the oracle / repair finishing machinery (``place_legend``, ``_run_oracle``,
  ``_repair``, ``orthogonalise_candidate``, ``MAX_REPAIR_ITERS``,
  ``LayoutError``) from :mod:`rule_engine.layout.repair`;
* the model types from :mod:`rule_engine.layout.model`.

The relocation of the base helpers and the oracle/repair stage into
``layout.base`` / ``layout.repair`` (task 1.4) means this module imports them
from *within* the package rather than back from ``layout_engine`` — the last
piece of the old bidirectional dependency, now one-directional, so
``layout_engine`` is a pure re-export shim.

``variants``/``solver`` are **not** imported here: they are added unwired in
task 1.4, and the default path never references them (R1.6).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

try:  # package-relative import when used as ``rule_engine.layout.pipeline``
    from ..diagram_layout import ICON_SIZE, GRID, COL_STEP, CONTAINER_PAD
    from ..geometry import Box, LABEL_BAND, contact_faces, orthogonalise_route
    from .model import Contact, DiagramSpec, PlacedEdge, PlacedDiagram
    from .corridors import CorridorAllocator
    from .contacts import (
        MAX_SIDE_EXITS,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
        OverConnectedError,
        _box_directly_below,
        select_contacts,
        _exit_side,
        _with_band,
        _entry_face,
        spread_entries,
        spread_contacts,
    )
    from .place import place_nodes, size_containers, centre_block_in_vpc
    from .routers import (
        classify_edge,
        _contact_point,
        _grid_contact,
        _free_left_corridor_x,
        decide_lane_sides,
        decide_converging_corridors,
        _exit_band_rank,
        _assign_exit_bands,
        _has_free_left_approach,
        route_edge,
        nudge_off_container_borders,
    )
    from .base import TITLE_BAND, _snap
    from .repair import (
        MAX_REPAIR_ITERS,
        LayoutError,
        place_legend,
        _run_oracle,
        _repair,
        orthogonalise_candidate,
    )
    from .solver import solve as _solve
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from diagram_layout import ICON_SIZE, GRID, COL_STEP, CONTAINER_PAD  # type: ignore[no-redef]
    from geometry import Box, LABEL_BAND, contact_faces, orthogonalise_route  # type: ignore[no-redef]
    from layout.model import Contact, DiagramSpec, PlacedEdge, PlacedDiagram  # type: ignore[no-redef]
    from layout.corridors import CorridorAllocator  # type: ignore[no-redef]
    from layout.contacts import (  # type: ignore[no-redef]
        MAX_SIDE_EXITS,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
        OverConnectedError,
        _box_directly_below,
        select_contacts,
        _exit_side,
        _with_band,
        _entry_face,
        spread_entries,
        spread_contacts,
    )
    from layout.place import place_nodes, size_containers, centre_block_in_vpc  # type: ignore[no-redef]
    from layout.routers import (  # type: ignore[no-redef]
        classify_edge,
        _contact_point,
        _grid_contact,
        _free_left_corridor_x,
        decide_lane_sides,
        decide_converging_corridors,
        _exit_band_rank,
        _assign_exit_bands,
        _has_free_left_approach,
        route_edge,
        nudge_off_container_borders,
    )
    from layout.base import TITLE_BAND, _snap  # type: ignore[no-redef]
    from layout.repair import (  # type: ignore[no-redef]
        MAX_REPAIR_ITERS,
        LayoutError,
        place_legend,
        _run_oracle,
        _repair,
        orthogonalise_candidate,
    )
    from layout.solver import solve as _solve  # type: ignore[no-redef]


def _global_contacts(
    spec: DiagramSpec,
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
) -> Tuple[Dict[str, Contact], Dict[str, Contact], Dict[str, "bool | None"]]:
    """Compute the legacy ten-pass GLOBAL contact result for every edge.

    This is the extraction (scored-router 1.8.0 regression fix) of the ten
    sequential global contact passes (``1``, ``1b``, ``1c``, ``1c2``, ``1d``,
    ``2``, ``2b``, ``2b3``, ``2b4``, ``2c``) that ``_place_and_route`` ran inline
    before routing. It returns ``(exits, entries, lane_sides)`` — the exact
    exit/entry contacts and per-edge lane sides the rule-driven pipeline chooses
    for the whole diagram *at once*, seeing every edge together.

    It is a **pure function** of ``(spec, placed, containers)`` — no randomness,
    no wall-clock, no dict-iteration-order dependence (every group is iterated in
    ``sorted`` / declared order), so it is safe to call from both the legacy path
    (:func:`_place_and_route`, which then routes greedily) and the scored solver
    (which seeds each edge's rule-based variant from this global result, so the
    solver's ``argmin`` can never do worse than the legacy route — Property 4 /
    R3.10). Extracting it changes no legacy output: ``_place_and_route`` calls it
    and routes from its result exactly as before, so every shipped ``.drawio``
    stays byte-identical on the ``--legacy`` path (R1.5).
    """
    # 1. Select each edge's contact points via the ladder.
    exits: Dict[str, Contact] = {}
    entries: Dict[str, Contact] = {}
    for edge in spec.edges:
        ex, en = select_contacts(edge, placed)
        exits[edge.id] = ex
        entries[edge.id] = en

    # 1b. Rule C: a cross-region hop runs over (or under) the row and descends
    #     into the target from ABOVE, so it enters the target's TOP face, not its
    #     left. Override the entry here where the edge class is known; the router
    #     (route_cross_region) then lands the final vertical on the top face.
    #     Rule G: a back-edge whose target sits against the canvas left (no room
    #     for a >= 1-grid-step gap to its left) also enters the TOP — a left
    #     entry there would land on the target's own edge with no offset.
    obstacles_all = list(placed.values())
    for edge in spec.edges:
        kind = classify_edge(edge, placed)
        if kind == "cross-region":
            # Prefer a LEFT entry when the target has a clear left approach: the
            # router then routes the hop in the inter-row gap + left entry (the
            # reviewer's l11 route), avoiding an over-row corridor on the target
            # AZ's caption. Otherwise keep the TOP entry (Rule C) — a target with
            # a neighbour on its left is reached from above.
            tgt = placed[edge.target]
            others = [b for nid, b in placed.items()
                      if nid not in (edge.source, edge.target)]
            if _has_free_left_approach(tgt, others):
                entries[edge.id] = (0.0, 0.5)   # left face → inter-row route
            else:
                entries[edge.id] = (0.5, 0.0)   # top-centre (Rule C)
        elif kind == "back-edge":
            src = placed[edge.source]
            tgt = placed[edge.target]
            if tgt.y >= src.bottom:
                # Rule K (1.10.3): a back-edge to a target BELOW-LEFT leaves the
                # BOTTOM face (diagram-standards → directional back-edge: bottom
                # exit is acceptable when the target is both below AND left).
                # Looping out the right face first sent it back across its own
                # column. It enters the target's TOP when nothing stands in the
                # target's column between the two rows, else the target's LEFT
                # face via the free gap beside the column
                # (:func:`routers.route_back_edge`).
                others = [b for nid, b in placed.items()
                          if nid not in (edge.source, edge.target)]
                blocked = any(
                    b.x < tgt.right and tgt.x < b.right
                    and src.bottom <= b.y < tgt.y
                    for b in others
                )
                exits[edge.id] = (0.5, 1.0)
                entries[edge.id] = (0.0, 0.5) if blocked else (0.5, 0.0)
                continue
            left_gap_x = tgt.x - (COL_STEP - ICON_SIZE) // 2
            if left_gap_x < CONTAINER_PAD + GRID:
                entries[edge.id] = (0.5, 0.0)   # no left gap → top-centre (Rule G)
        elif kind == "spine":
            # Exception I: a spine to a target DIRECTLY BELOW in the same column
            # with nothing between (the summary's lb→app→db vertical chain) drops
            # STRAIGHT — bottom-centre exit into top-centre entry — instead of the
            # exit-right → side-corridor → step-back-left hook. A straight drop
            # removes the excessive hook (a crossing-like defect) and only grazes
            # the source's OWN caption.
            #
            # v1.6.0: this was gated on ``spec.compact``, on the theory that a
            # dense landscape needs the caption-avoiding side corridor. The side
            # corridor turned out to cost far more than it saved: a hooked spine
            # descends through the row gaps where every long-haul corridor runs, so
            # each one crossed several of them AND consumed a lane in the narrow
            # band above its target (three requests for the one line that fits
            # above the app row). A straight drop in a clear column crosses nothing
            # and allocates nothing. The precondition is already the strict one —
            # same column, nothing in between — so it is applied on both classes.
            src = placed[edge.source]
            tgt = placed[edge.target]
            others = [b for nid, b in placed.items()
                      if nid not in (edge.source, edge.target)]
            if _box_directly_below(src, tgt, others):
                exits[edge.id] = (0.5, 1.0)     # bottom-centre
                entries[edge.id] = (0.5, 0.0)   # top-centre → straight drop
            else:
                # Adaptive LEFT corridor (v1.5.1, edge-4 generalisation). A spine
                # to a target in the SAME COLUMN but PAST an intermediate node (so
                # the straight drop above is blocked) routes down the column's LEFT
                # gap and enters the target's LEFT face — WHEN that gap is free
                # (_free_left_corridor_x). Pin the bottom exit + left entry here so
                # the stored contacts match the route the spine router then draws;
                # both faces are contract-legal, so edge-direction is unaffected.
                # When the left gap is not usable this does nothing and the default
                # right-corridor + top-entry route stands.
                same_column_blocked = (
                    abs(src.x - tgt.x) < 1e-9 and tgt.y > src.y
                )
                if same_column_blocked and _free_left_corridor_x(
                    src, tgt, others, containers, edge.id
                ) is not None:
                    exits[edge.id] = (0.5, 1.0)     # bottom-centre → left gap
                    entries[edge.id] = (0.0, 0.5)   # target LEFT face

    # 1b2. Fan-out-row into a CONTENDED left-approach row → enter the TOP instead.
    #      A fan-out-row hop enters its same-row target's LEFT face along that
    #      row's centre line. When the node immediately LEFT of the target is the
    #      *source* of a CROSS-REGION hop, that node's right-centre exit stub runs
    #      on the very same centre line in the very same gap — so the fan-out's
    #      left-approach stub and the cross-region exit stub overlap on it
    #      (``check_corridor-sharing`` flags the pair). The repair loop cannot
    #      separate them: the shared line is the target's own left-face row, pinned
    #      by the contact, so bumping only walks the fan-out's drop column sideways
    #      until it lands ON the cross-region rise — the ``l8``x``l10`` coincident
    #      point at the AZ-1 db/obj gap. Entering the target's TOP-centre keeps the
    #      fan-out off the contended centre line entirely (the same reasoning
    #      :func:`select_contacts` already applies to a below-target that shares a
    #      replication row), so the finding never arises. Narrow by construction:
    #      only a left-entering fan-out-row whose target has a cross-region source
    #      one column to its left on the same row is retargeted; everything else is
    #      byte-unchanged.
    xregion_sources = {
        edge.source
        for edge in spec.edges
        if classify_edge(edge, placed) == "cross-region"
    }
    for edge in spec.edges:
        if classify_edge(edge, placed) != "fan-out-row":
            continue
        if entries[edge.id] != (0.0, 0.5):   # only a LEFT-face fan-out entry
            continue
        tgt = placed[edge.target]
        # The node one column-step to the target's left, on the same row.
        left_neighbour = next(
            (
                b for nid, b in placed.items()
                if nid in xregion_sources
                and abs((b.y + b.h / 2) - (tgt.y + tgt.h / 2)) < 1e-6
                and abs(b.x + COL_STEP - tgt.x) < 1e-6
            ),
            None,
        )
        if left_neighbour is not None:
            entries[edge.id] = (0.5, 0.0)     # top-centre → off the contended row

    # 1c. Two-sided fan-out for a SOURCE node (v1.5.1, variant A). A node that is
    #     the *start* of several downward flows — a load balancer or DNS that
    #     fans out to two app tiers / two regions — reads more naturally when it
    #     leaves from TWO faces (right AND bottom) instead of cramming every
    #     branch onto the right face and looping the straight-down one. Both
    #     right and bottom are contract-legal exits (``edge-direction`` admits
    #     ``exitX>=0.5`` OR ``exitY==1``), so this needs NO change to the linter —
    #     it only widens which allowed face the engine picks.
    #
    #     Scope, deliberately narrow so it never regresses a good layout:
    #       * the source has >= 2 downward edges (a genuine fan-out), and
    #       * exactly one of them goes to a target DIRECTLY BELOW in the same
    #         column with nothing between (the straight-down branch).
    #     That straight-down branch takes the BOTTOM face (a clean vertical drop,
    #     exactly like the compact summary's lb→app chain); the sibling branches
    #     keep the right face. A single-edge source, or a fan-out with no
    #     directly-below branch, is untouched (stays all-right), so every existing
    #     diagram is byte-unchanged unless it has this precise shape.
    order_index = {e.id: i for i, e in enumerate(spec.edges)}
    down_by_src: Dict[str, List[str]] = {}
    for edge in spec.edges:
        s, t = placed[edge.source], placed[edge.target]
        if t.y > s.y:                            # a downward edge
            down_by_src.setdefault(edge.source, []).append(edge.id)
    for src_id, eids in down_by_src.items():
        if len(eids) < 2:
            continue                             # not a fan-out → leave as right
        src = placed[src_id]
        # Find the branch(es) whose target is directly below in the same column.
        straight = [
            eid for eid in eids
            if _box_directly_below(
                src, placed[spec.edges[order_index[eid]].target],
                [b for nid, b in placed.items()
                 if nid not in (src_id, spec.edges[order_index[eid]].target)],
            )
        ]
        # Only act when EXACTLY one branch is the clean straight-down drop, so we
        # never have to choose between two bottom stubs (which would re-crowd the
        # bottom face and cross the caption).
        if len(straight) == 1:
            eid = straight[0]
            exits[eid] = (0.5, 1.0)              # bottom-centre → straight drop
            entries[eid] = (0.5, 0.0)            # into the target's top-centre

    # 1c2. Crowded-right relief via the straight drop (v1.6.0). Step 1c above only
    #     fires when a source has >= 2 *downward* edges, so it misses the very
    #     common shape where a node fans out sideways along its row AND has one
    #     branch to the tier directly below it: three exits pile onto the right
    #     face, and the downward one — whose target is in the same column — has to
    #     turn, run back left under the row, and cross both siblings on the way
    #     (``app_a2``'s l19/l20/l21, where l20 crossed l21 twice and l19 once).
    #
    #     That branch has a clean vertical available, which is what the standard
    #     asks for anyway ("the branch whose target is directly below in the same
    #     column exits the bottom"). Take it: bottom-centre to top-centre, no
    #     turns, no lane, nothing to cross. The right face drops to two exits, so
    #     the overflow valve below no longer needs to spill anything either.
    #
    #     Scoped tight: the face must be genuinely crowded (>= MAX_SIDE_EXITS
    #     exits) and there must be EXACTLY ONE directly-below branch, so we never
    #     have to choose between two bottom stubs.
    right_count: Dict[str, List[str]] = {}
    for edge in spec.edges:
        if _exit_side(exits[edge.id]) == "right":
            right_count.setdefault(edge.source, []).append(edge.id)
    for src_id, eids in sorted(right_count.items()):
        if len(eids) < MAX_SIDE_EXITS:
            continue
        src = placed[src_id]
        straight_down = [
            eid for eid in eids
            if _box_directly_below(
                src, placed[spec.edges[order_index[eid]].target],
                [b for nid, b in placed.items()
                 if nid not in (src_id, spec.edges[order_index[eid]].target)],
            )
        ]
        if len(straight_down) == 1:
            eid = straight_down[0]
            exits[eid] = (0.5, 1.0)              # bottom-centre
            entries[eid] = (0.5, 0.0)            # into the target's top-centre

    # 1d. Overflow valve (v1.5.1). A node's RIGHT face has room for only so many
    #     distinct fan-out lanes before their below-row corridors start crossing
    #     one another and the straight stub of an adjacent target (app→cache/db/obj:
    #     three right exits whose corridors tangled — l5×l6, l5×l8). When a source
    #     has MORE THAN TWO right-going edges, spill the surplus onto the BOTTOM
    #     face: the farthest targets (largest dx) leave the bottom and drop into
    #     their own fan-out corridor + enter the target's LEFT face, so the right
    #     face keeps at most two distinct exits. Deterministic — ordered by
    #     (dx desc, marker) so the SAME inputs always spill the same edges — and
    #     scoped to genuine over-connected right faces, so a node with <=2 right
    #     edges is byte-unchanged. Both faces are contract-legal (exit right OR
    #     bottom; enter left), so edge-direction is unaffected.
    right_by_src: Dict[str, List[str]] = {}
    for edge in spec.edges:
        ex, ey = exits[edge.id]
        is_right = ex is not None and ex >= 0.5 and (ey is None or ey < 1.0)
        s, t = placed[edge.source], placed[edge.target]
        if is_right and t.x > s.x:               # a right-going fan-out edge
            right_by_src.setdefault(edge.source, []).append(edge.id)
    #
    #     v1.6.0: the valve's premise — "the right face has room for only two
    #     distinct fan-out lanes" — was true only while every fan-out ran BELOW its
    #     row. Now that a fan-out can also run in the free band ABOVE the row
    #     (:func:`decide_lane_sides`), a three-exit face can be served without
    #     spilling anything: one branch above, one level, one below, each leaving
    #     toward its own lane. So the valve stands down when the face has a branch
    #     that can use the above lane and is within MAX_SIDE_EXITS — which is the
    #     reviewer's own split of ``app_a1``'s fan-out. It still fires when every
    #     branch is stuck in the below band.
    pre_sides = decide_lane_sides(spec, placed, containers, exits, entries)
    for src_id, eids in right_by_src.items():
        if len(eids) <= MAX_SIDE_EXITS - 1:      # <= 2 right exits → no overflow
            continue
        if len(eids) <= MAX_SIDE_EXITS and any(pre_sides.get(eid) for eid in eids):
            continue                             # a free above-row lane absorbs it
        src = placed[src_id]
        # Keep the two NEAREST targets on the right face; spill the rest (farthest
        # first). "Adjacent" straight targets (a same-row neighbour) are always
        # kept — they read as a clean short horizontal — so rank only the
        # non-adjacent fan-out-row edges for spilling.
        def _dx(eid: str) -> float:
            return placed[spec.edges[order_index[eid]].target].x - src.x
        spillable = sorted(
            (eid for eid in eids
             if classify_edge(spec.edges[order_index[eid]], placed) == "fan-out-row"),
            key=lambda e: (-_dx(e), order_index[e]),  # farthest first; declared order tiebreak
        )
        keep = max(0, len(eids) - (MAX_SIDE_EXITS - 1))  # how many to spill
        for eid in spillable[:keep]:
            exits[eid] = (0.5, 1.0)              # bottom face → own fan-out corridor
            entries[eid] = (0.0, 0.5)            # enter the target's LEFT face

    # 2. Spread same-side exits per source in EDGE-MARKER order: the first edge
    #    (lowest marker) keeps the face centre, the 2nd/3rd shift to the quarters
    #    (Req 5.3, "перший по центру"). Group by (source, exit-face).
    order_of = {e.id: i for i, e in enumerate(spec.edges)}
    marker_key = {e.id: e.marker for e in spec.edges}
    def _mk(eid: str):
        m = marker_key[eid]
        return (0, int(m)) if m.isdigit() else (1, m)  # numeric markers first, in order
    by_side: Dict[Tuple[str, str], List[str]] = {}
    for edge in spec.edges:
        side = _exit_side(exits[edge.id])
        by_side.setdefault((edge.source, side), []).append(edge.id)
    for (src_id, side), eids in by_side.items():
        # On the RIGHT face, an ADJACENT ``straight`` edge is drawn as a clean
        # level horizontal to its neighbour, so it must keep the face CENTRE
        # (band 0.5). A ``fan-out-row`` sibling instead exits and then STAIRS
        # DOWN into a below-row lane, so if the straight edge were pushed to the
        # lower band its level run would cross the fan-out edge's drop leg just
        # past the source (the l5×l6 tangle). Rank straight edges ahead of the
        # rest here (marker order within each class) so the spread hands the
        # centre to the straight edge and the offset band to the stair-dropping
        # fan-out edge. Only the right face is reordered; every other side keeps
        # pure marker order, so no other diagram shape changes.
        def _spread_key(eid: str):
            k = classify_edge(spec.edges[order_index[eid]], placed)
            straight_first = 0 if k == "straight" else 1
            return (straight_first, _mk(eid))
        # 2a-bottom. Spatial ordering on the BOTTOM face (diagram-standards →
        #     *Fan-out exit ordering (spatial logic)*): when a node's bottom face
        #     carries BOTH a straight-down target (dx≈0) AND a leftward target
        #     (dx<0), the band each takes must follow the TARGET's direction, not
        #     the edge marker — the straight-down branch keeps the CENTRE and the
        #     leftward branch takes the bottom-LEFT band. The marker-ordered spread
        #     put a low-marker back-edge (``hub→sql``, target far left) on the
        #     centre and pushed the straight-down ``hub→obj`` to the left band, so
        #     obj's bottom-left stub crossed sql's centre-then-left run (the OCI
        #     hub 7×8 crossing). Scoped tight — it fires ONLY on that left+down mix,
        #     so the landscape fan-outs (a straight-down centre branch beside a
        #     left-corridor branch, already handled by 2b3) and any all-downward or
        #     all-rightward face keep their existing spread bands byte-for-byte.
        if side == "bottom" and len(eids) > 1:
            src_box = placed[src_id]

            def _dx(eid: str) -> float:
                t = placed[spec.edges[order_index[eid]].target]
                return (t.x + t.w / 2.0) - (src_box.x + src_box.w / 2.0)

            has_left = any(_dx(e) < -1.0 for e in eids)
            has_straight = any(abs(_dx(e)) <= 1.0 for e in eids)
            if has_left and has_straight:
                # Assign the band by the target's DIRECTION category, not by a
                # sorted position: a leftward target takes the bottom-LEFT band, a
                # straight-down target the CENTRE, a rightward target the
                # bottom-RIGHT band. This keeps the straight-down branch on the
                # centre (a clean vertical drop) while the leftward branch diverges
                # left — the two never cross. A same-direction tie keeps marker
                # order and the distinct bands the spread would give it.
                def _band(eid: str) -> float:
                    e = spec.edges[order_index[eid]]
                    t = placed[e.target]
                    dx = _dx(eid)
                    # A genuinely-clear straight drop (nothing between) keeps the
                    # CENTRE; a same-column target BLOCKED by an intervening node
                    # must route to a side, so it takes the RIGHT band (away from a
                    # leftward sibling), not the centre it cannot use.
                    others = [b for nid, b in placed.items()
                              if nid not in (e.source, e.target)]
                    if abs(dx) <= 1.0:
                        return 0.5 if _box_directly_below(src_box, t, others) else _LOWER_QUARTER
                    return _UPPER_QUARTER if dx < 0 else _LOWER_QUARTER
                # Within one direction, keep the marker-ordered spread's distinct
                # bands so two same-direction siblings never merge on one band.
                buckets: Dict[float, List[str]] = {}
                for eid in sorted(eids, key=_mk):
                    buckets.setdefault(_band(eid), []).append(eid)
                if all(len(v) == 1 for v in buckets.values()):
                    for eid in eids:
                        exits[eid] = _with_band(exits[eid], "bottom", _band(eid))
                    continue
        if side == "right" and len(eids) > 1:
            eids_sorted = sorted(eids, key=_spread_key)
        else:
            eids_sorted = sorted(eids, key=_mk)
        group = [(eid, exits[eid]) for eid in eids_sorted]
        for eid, pt in spread_contacts(group):
            exits[eid] = pt

    # 2b. Spread shared ENTRY faces per target the same way: the first edge
    #     entering a given target face keeps its centre, the rest shift off it, so
    #     several arrivals on one face don't stack on one point.
    #
    #     Ordering within the group: normally edge-marker order. BUT for a TOP
    #     face reached by >= 2 edges from DIFFERENT sources (a convergence), order
    #     by the SOURCE's x instead — leftmost source takes the leftmost band — so
    #     the drops land left-to-right in source order and the paired
    #     :func:`decide_converging_corridors` can run the leftmost drop on the
    #     highest corridor with no crossing (diagram-standards → *Converging
    #     edges*; the ``l1``x``l15`` fix). Marker order is kept for every other
    #     face, so no other diagram shape changes.
    by_entry: Dict[Tuple[str, str], List[str]] = {}
    for edge in spec.edges:
        face = _entry_face(entries[edge.id])
        by_entry.setdefault((edge.target, face), []).append(edge.id)
    for (tgt_id, face), eids in by_entry.items():
        if len(eids) < 2:
            continue
        distinct_srcs = {spec.edges[order_index[e]].source for e in eids}
        if face == "top" and len(distinct_srcs) >= 2:
            # Converging top face: leftmost source → leftmost drop band.
            eids_sorted = sorted(
                eids,
                key=lambda e: (placed[spec.edges[order_index[e]].source].x, _mk(e)),
            )
        else:
            eids_sorted = sorted(eids, key=_mk)
        group = [(eid, entries[eid]) for eid in eids_sorted]
        for eid, pt in spread_entries(group):
            entries[eid] = pt

    # 2b3. Rule H-bottom (v1.5.1): a BOTTOM-face fan-out branch that turns toward
    #     the LEFT corridor (its entry is the target's LEFT face) must leave from
    #     the bottom-LEFT band, and the straight-down sibling (entry TOP) keeps
    #     the bottom-CENTRE. Otherwise the spread hands the later-marker left
    #     branch the LOWER/right quarter, so its immediate leftward step crosses
    #     the centre straight-down branch at the glyph (l4 crossing l3). Biasing
    #     the left-corridor branch to the left band makes the two bottom stubs
    #     diverge from the start — the straight one drops centre, the left one
    #     steps out left — with no crossing. Only touches bottom exits whose
    #     entry is a left face; a top-entry straight drop is left centred.
    #
    #     v1.6.0 guard: this runs AFTER the spread, so moving EVERY left-entry
    #     bottom branch to the one left band re-merges them when a source has more
    #     than one such branch (three downward edges from one node: two spilled
    #     left-entry branches both landing on 0.25, an ``exit-thirds``
    #     "bottom-exits-merge"). Keeping two stubs DISTINCT matters more than
    #     which band each takes, so the left bias is applied only when the source
    #     has exactly one left-entry bottom branch; otherwise the spread's
    #     already-distinct bands stand.
    _left_bottom_by_src: Dict[str, List[str]] = {}
    for edge in spec.edges:
        ex, ey = exits[edge.id]
        if ey is None or ey < 1.0:
            continue  # not a bottom exit
        nx, _ny = entries[edge.id]
        if nx is not None and nx <= 0.0:          # left-corridor branch
            _left_bottom_by_src.setdefault(edge.source, []).append(edge.id)
    for eids in _left_bottom_by_src.values():
        if len(eids) != 1:
            continue                              # keep the spread's distinct bands
        eid = eids[0]
        exits[eid] = (_UPPER_QUARTER, exits[eid][1])  # bottom-LEFT band (0.25)

    # 2b4. Monotone exit bands on the RIGHT face (v1.6.0), replacing the old
    #     Rule H. Rule H had the right idea — "a run rising into an above-row
    #     corridor takes the upper quarter, one dropping into a below-row corridor
    #     the lower quarter" — but the code it shipped pinned EVERY shifted
    #     long-haul exit to the UPPER quarter regardless of where its corridor
    #     actually ran, and it only looked at cross-region / back-edge kinds. A
    #     descending branch therefore left from ABOVE the level sibling it then had
    #     to cross on the way down to its lane: the l19/l20 tangle (a fan-out
    #     crossing a level run, then its own sibling twice), the l14/l15 pair, and
    #     the s1/s5 pair in every summary. Four crossings per landscape that the
    #     metric could not even see until its shared-endpoint exemption was lifted.
    #
    #     Instead, rank every branch on a face by the route it will actually take
    #     (:func:`_exit_band_rank`) and hand out the bands top-to-bottom in rank
    #     order (:func:`_assign_exit_bands`): above-going branches leave high,
    #     level runs keep the centre, below-going branches leave low, and a
    #     back-runner — whose turn column is necessarily the nearest lane — goes
    #     outermost so no sibling crosses it at the glyph. Every stub then diverges
    #     from the face toward its own lane.
    #
    #     Runs AFTER 2b/2b3 so it sees the final faces (the bottom-face spills are
    #     already out of the right-face groups) and it only rewrites the along-face
    #     band, never the face itself — so the directional contract and
    #     ``check_exit_thirds`` are untouched.
    lane_sides = decide_lane_sides(spec, placed, containers, exits, entries)
    right_face: Dict[str, List[str]] = {}
    for edge in spec.edges:
        if _exit_side(exits[edge.id]) == "right":
            right_face.setdefault(edge.source, []).append(edge.id)
    for src_id, eids in sorted(right_face.items()):
        ranked = sorted(
            ((eid, _exit_band_rank(
                spec.edges[order_index[eid]],
                classify_edge(spec.edges[order_index[eid]], placed),
                placed, lane_sides,
            )) for eid in eids),
            key=lambda pair: (pair[1], _mk(pair[0])),
        )
        for eid, band in _assign_exit_bands(ranked).items():
            exits[eid] = _with_band(exits[eid], "right", band)

    # 2c. Snap every contact FRACTION so its absolute point lands on the grid
    #     (icon centre 0.5 → x0+39 is off-grid; a grid-snapped waypoint would
    #     then meet it with a 1px kink that skews the arrowhead). After this the
    #     arrow lands exactly on the final grid waypoint — no skew, waypoints
    #     stay on the grid.
    for edge in spec.edges:
        exits[edge.id] = _grid_contact(placed[edge.source], exits[edge.id])
        entries[edge.id] = _grid_contact(placed[edge.target], entries[edge.id])

    return exits, entries, lane_sides


def _route_all_legacy(
    spec: DiagramSpec,
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
    exits: Dict[str, Contact],
    entries: Dict[str, Contact],
    lane_sides: Dict[str, "bool | None"],
) -> List[PlacedEdge]:
    """Route every edge greedily from the global contacts — the LEGACY geometry.

    This is step 3 of :func:`_place_and_route`, extracted so the scored solver can
    reproduce the **exact** legacy per-edge waypoints. It shares one
    :class:`CorridorAllocator` across the edges in **declared order** (so lanes
    are handed out exactly as the legacy path hands them out), routes each edge on
    its class, orthogonalises the finished polyline centrally, and returns the
    list of :class:`PlacedEdge` in declared order.

    A pure, deterministic function of ``(spec, placed, containers, exits,
    entries, lane_sides)`` — the allocator is created fresh inside, so calling it
    is side-effect-free. The scored solver calls it once to obtain the legacy
    geometry per edge, then seeds each edge's rule-based variant with those exact
    points: the winning route can then never score worse than legacy, because
    picking rule-based for every edge *is* the legacy geometry (Property 4 /
    R3.10). ``_place_and_route`` calls it too and returns its result verbatim, so
    the legacy path is byte-identical (R1.5)."""
    obstacles = [placed[n.id] for n in spec.nodes]
    allocator = CorridorAllocator()
    # Coordinate the loop corridors of edges that converge on one target's top
    # face, so the leftmost drop runs on the highest lane (diagram-standards →
    # *Converging edges*; the ``l1``x``l15`` fix). Absent edges keep their normal
    # per-edge allocation.
    corridor_y = decide_converging_corridors(
        spec, placed, containers, exits, entries, lane_sides
    )
    placed_edges: List[PlacedEdge] = []
    for edge in spec.edges:
        pts = route_edge(
            edge, exits[edge.id], entries[edge.id], allocator, obstacles, containers,
            lane_sides.get(edge.id), corridor_y.get(edge.id),
        )
        # Orthogonalise once, centrally (v1.6.0). Every router computes its
        # corridor correctly but emits the waypoint next to a contact from the
        # corridor's coordinates rather than the contact's, leaving a diagonal
        # leg that draw.io resolves into a corner of its own choosing. Rewriting
        # the finished polyline here fixes all eight routers at once and keeps the
        # rewrite in one testable place.
        src_box, tgt_box = placed[edge.source], placed[edge.target]
        pts = orthogonalise_route(
            _contact_point(src_box, exits[edge.id]),
            pts,
            _contact_point(tgt_box, entries[edge.id]),
            contact_faces(*exits[edge.id]),
            contact_faces(*entries[edge.id]),
        )
        placed_edges.append(
            PlacedEdge(spec=edge, exit=exits[edge.id], entry=entries[edge.id], points=list(pts))
        )
    return placed_edges


def _place_and_route(spec: DiagramSpec) -> "PlacedDiagram":
    """Run the pure pipeline (steps 1–8) into an initial candidate (design.md §9).

    place → size → centre → contacts (+ spread) → corridors → route → legend.
    No randomness, no time, dict iteration replaced by sorted/declared order, so
    the candidate is a deterministic function of ``spec`` (Req 11.1).

    The ten global contact passes are computed by :func:`_global_contacts` (an
    extraction that does not change this path's output — byte-identical on
    ``--legacy``, R1.5); this function then routes every edge greedily from that
    global result, exactly as before."""
    placed = place_nodes(spec)
    containers = size_containers(placed, spec)
    placed = centre_block_in_vpc(placed, containers, spec)

    exits, entries, lane_sides = _global_contacts(spec, placed, containers)

    # 3. Route every edge on its class from the global contacts (extracted into
    #    :func:`_route_all_legacy` so the scored solver can reuse the exact legacy
    #    geometry to seed each edge's rule-based variant — byte-identical here).
    placed_edges = _route_all_legacy(spec, placed, containers, exits, entries, lane_sides)

    # 4. Place the right-margin Flow/Legend past the account box (Req 8).
    account = next(
        (containers[c.id] for c in spec.containers if c.kind == "account" and c.id in containers),
        None,
    )
    if account is None:
        # No account container: fall back to the bounding box of all containers /
        # nodes so the legend still sits clear to the right.
        right = max(
            [b.right for b in containers.values()]
            + [placed[n.id].footprint(LABEL_BAND).right for n in spec.nodes],
            default=CONTAINER_PAD,
        )
        account = Box("_envelope", 0, 0, right, 0)
    legend_x, legend_w = place_legend(account, spec.flow_lines)

    return PlacedDiagram(
        spec=spec,
        nodes=placed,
        containers=containers,
        edges=placed_edges,
        legend_x=legend_x,
        legend_w=legend_w,
    )


def _place_and_route_scored(spec: DiagramSpec) -> "PlacedDiagram":
    """Run the pipeline with the **scored per-edge solver** as the routing stage.

    This is the default (non-``--legacy``) routing path for the 1.8.0 scored
    router (task 7.3, design.md §Architecture — the pipeline inversion). It keeps
    ``place → size → centre`` and the right-margin legend placement **identical**
    to :func:`_place_and_route`; only the contacts+route stage is replaced. Where
    :func:`_place_and_route` runs the ten sequential global contact passes and
    then routes every edge greedily, this hands the contacts+route decision to
    :func:`rule_engine.layout.solver.solve`, which chooses each edge's contacts
    *and* waypoints together — scoring every sanctioned variant against the edges
    already accepted and committing the ``argmin`` (design.md §control flow).

    Deterministic (R4.1, Decision D4): ``place → size → centre`` and
    :func:`place_legend` are pure functions of the spec, and :func:`solve` uses no
    randomness, no wall-clock, and no dict-iteration-order dependence and returns
    its edges in declared order — so the same spec yields byte-identical geometry,
    and the ``generator --check`` freshness gate holds. The artifact format is
    unchanged: the result is the same :class:`PlacedDiagram` the legacy path
    produces, so serialization, the repair loop, and every lint rule see an
    identical shape (R4.2, R4.3) — only *how* the waypoints are chosen differs."""
    placed = place_nodes(spec)
    containers = size_containers(placed, spec)
    placed = centre_block_in_vpc(placed, containers, spec)

    # Contacts + route: the scored per-edge solver replaces the ten-pass global
    # contact ladder + greedy route. The solver owns the corridor allocator (it
    # snapshots/restores it around each variant trial and keeps the winner's
    # lanes), so the pipeline hands it a fresh allocator and takes back the
    # committed edge set, in declared order (a pure function of the spec — R4.1).
    # Compute the legacy ten-pass GLOBAL contact result AND the full legacy routed
    # geometry ONCE, and hand both to the solver. Each edge's rule-based variant
    # is seeded from the global-pass exit/entry (for the variant contacts) and,
    # crucially, carries the EXACT legacy waypoints for that edge. Picking the
    # rule-based variant for every edge therefore reproduces the legacy diagram
    # byte-for-byte, so ``route_cost(scored) <= route_cost(legacy)`` always holds
    # — restoring Property 4 / R3.10 on dense landscapes where the global
    # fan-out-spread / overflow-valve / monotone-exit-band passes (which a
    # per-edge, isolated route cannot reproduce, since lane assignment depends on
    # the global routing order) are what hold the crossing count down.
    exits, entries, lane_sides = _global_contacts(spec, placed, containers)
    legacy_edges = _route_all_legacy(
        spec, placed, containers, exits, entries, lane_sides
    )

    allocator = CorridorAllocator()
    placed_edges = _solve(
        placed, containers, spec, allocator,
        (exits, entries, lane_sides), legacy_edges,
    )

    # Place the right-margin Flow/Legend past the account box — identical to
    # :func:`_place_and_route` step 4, so the only difference between the two
    # paths is the routed edge geometry, never the legend or the artifact format.
    account = next(
        (containers[c.id] for c in spec.containers if c.kind == "account" and c.id in containers),
        None,
    )
    if account is None:
        right = max(
            [b.right for b in containers.values()]
            + [placed[n.id].footprint(LABEL_BAND).right for n in spec.nodes],
            default=CONTAINER_PAD,
        )
        account = Box("_envelope", 0, 0, right, 0)
    legend_x, legend_w = place_legend(account, spec.flow_lines)

    return PlacedDiagram(
        spec=spec,
        nodes=placed,
        containers=containers,
        edges=placed_edges,
        legend_x=legend_x,
        legend_w=legend_w,
    )


def _normalise_origin(
    placed: "PlacedDiagram",
    margins: Tuple[int, int] = (CONTAINER_PAD, CONTAINER_PAD),
) -> "PlacedDiagram":
    """Translate the whole placed layout so its top-left sits at ``margins`` (Req 12.4).

    ``margins`` is ``(left_margin, top_margin)``; both default to
    :data:`CONTAINER_PAD` (the historical behaviour — ``min(x) == min(y) ==
    CONTAINER_PAD``, preserved for synthetic specs and callers that pass no
    margins). :func:`layout` passes a larger ``top_margin`` (``CONTAINER_PAD +
    TITLE_BAND``) so the outermost container clears the diagram title band drawn
    above it, matching the reference.

    The account-level edge row (region ``""``) is placed at the base origin and
    then centred / spread relative to the region bands, so a container band or an
    edge waypoint can end up at a **negative** coordinate (the reference regression
    saw ``boundary-account x=-220``). This final pass removes that: it anchors the
    translation on the **node and container boxes** — computing ``dx``/``dy`` so
    their minimum ``x``/``y`` lands exactly at :data:`CONTAINER_PAD` (the checked
    invariant, Req 12.4) — while also guaranteeing that **no edge waypoint** is
    pulled negative: the delta is at least large enough to lift the leftmost /
    topmost waypoint to the origin too, so nothing goes off-canvas after the shift.
    For these diagrams a box is the extreme on each axis, so the box-anchor already
    keeps every waypoint non-negative; the clamp is a safety net.

    Because it is one **uniform translation** applied to every coordinate, it
    preserves all relative geometry: grid alignment, overlaps, padding, direction,
    and corridor separation are unchanged, so an oracle-clean candidate stays clean
    (design.md §12 — "a single deterministic, grid-aligned shift"). Contact-point
    *fractions* (``exit``/``entry``) are unit-square face fractions, not absolute
    coordinates, so they are carried through untouched. ``legend_x`` is an absolute
    x, so it shifts by ``dx`` only.

    Deterministic and grid-aligned: every input coordinate is already a whole
    ``GRID`` multiple and ``CONTAINER_PAD`` is a whole ``GRID`` multiple, so the
    delta is grid-aligned; :func:`_snap` is applied for safety.
    """
    boxes = list(placed.nodes.values()) + list(placed.containers.values())
    if not boxes:  # a degenerate spec with no nodes/containers
        return placed

    left_margin, top_margin = margins
    box_min_x = min(b.x for b in boxes)
    box_min_y = min(b.y for b in boxes)

    # Every absolute coordinate (boxes + waypoints), so the shift can never pull a
    # waypoint off the top/left edge of the canvas.
    all_min_x = box_min_x
    all_min_y = box_min_y
    for pe in placed.edges:
        for px, py in pe.points:
            all_min_x = min(all_min_x, px)
            all_min_y = min(all_min_y, py)

    # Anchor on the box origins (so their min == the requested margin), but never
    # less than the shift needed to keep the leftmost/topmost waypoint non-negative.
    dx = _snap(max(left_margin - box_min_x, -all_min_x))
    dy = _snap(max(top_margin - box_min_y, -all_min_y))
    if dx == 0 and dy == 0:
        return placed  # already at the origin margin — nothing to translate

    nodes = {
        nid: Box(b.id, _snap(b.x + dx), _snap(b.y + dy), b.w, b.h)
        for nid, b in placed.nodes.items()
    }
    containers = {
        cid: Box(b.id, _snap(b.x + dx), _snap(b.y + dy), b.w, b.h)
        for cid, b in placed.containers.items()
    }
    edges = [
        PlacedEdge(
            spec=pe.spec,
            exit=pe.exit,
            entry=pe.entry,
            points=[(_snap(px + dx), _snap(py + dy)) for px, py in pe.points],
        )
        for pe in placed.edges
    ]
    return PlacedDiagram(
        spec=placed.spec,
        nodes=nodes,
        containers=containers,
        edges=edges,
        legend_x=_snap(placed.legend_x + dx),
        legend_w=placed.legend_w,
    )




def layout(
    spec: DiagramSpec,
    legacy: bool = False,
    *,
    _placement: bool = True,
) -> "PlacedDiagram":
    """Turn a coordinate-free ``spec`` into a placed, repaired diagram (Req 9).

    Orchestrates ``place → size → centre → (solver | legacy) → repair``
    (design.md §Architecture — the pipeline inversion), and — since 1.9.0 Part A
    (task 3) — wraps the **default** scored path in the scored **placement** loop
    (:func:`rule_engine.layout.solver.solve_placement`). The ``place → size →
    centre`` and the bounded ``repair`` stages are unchanged; the seams are:

    * **legacy / rule-driven path** (``legacy=True``) — the retained ten-pass
      :func:`_place_and_route`, which selects every edge's contacts in ten
      sequential global passes and then routes. This is the ``Legacy_Path``,
      selectable by the ``--legacy`` flag threaded from the generator entry
      points as the ``legacy`` keyword. It runs no placement search and no scored
      per-edge solver, so every ``--legacy`` diagram is byte-identical to its
      pre-1.9.0 bytes (R5.2, R5.3).
    * **scored placement loop (default)** — the outer placement search
      (:func:`rule_engine.layout.solver.solve_placement`), new in 1.9.0 Part A
      (design.md §Component A2). It enumerates a small, rank-ordered,
      deterministic set of placement variants, runs the **inner** scored route
      pipeline (below) on each to a finished candidate, scores each with the
      shared graded ``route_cost``, and returns the ``argmin`` over
      ``(RouteCost.as_tuple(), placement_rank, placement_id)``. The base
      placement (rank 0, no move) is always a candidate, so the selected
      placement can never score worse than the pre-placement default — the Part A
      analogue of the 1.8.0 per-edge guarantee (R1.3, R1.4). This is the path a
      generator gets by calling ``layout(spec)`` with no ``legacy`` flag.
    * **inner scored route path** (``legacy=False, _placement=False``) — the
      per-edge order-score-commit loop (:func:`_layout_scored_with_guard`, wired
      to :func:`rule_engine.layout.solver.solve`). This is the 1.8.0 route-only
      path: it chooses each edge's contacts *and* waypoints together, scoring
      every sanctioned variant against the edges already accepted and committing
      the ``argmin`` (design.md §control flow). ``solve_placement`` invokes this
      path once per placement variant (via ``layout(moved, _placement=False)``),
      so the placement loop reuses the exact 1.8.0 machinery as its "score one
      placement" step rather than duplicating it, and the private ``_placement``
      switch is what breaks the ``layout ⇄ solve_placement`` recursion (the loop
      never re-enters the loop). It uses no randomness, no wall-clock, and no
      dict-iteration-order dependence and returns its edges in declared order, so
      it is a deterministic, byte-identical function of the spec (R5.1) and feeds
      the same repair / normalise / serialize stages as the legacy path — it
      changes only how waypoints are chosen, never the artifact format (R5.3).

    After the contacts+route stage produces an initial candidate, the bounded
    repair loop runs: on each pass, run the oracle (:func:`_run_oracle`); if it
    is clean (zero blocking findings), return the candidate; otherwise apply one
    deterministic repair per fixable finding (:func:`_repair`) and retry. After
    :data:`MAX_REPAIR_ITERS` passes with a blocking finding still present, raise
    :class:`LayoutError` naming the first unresolved finding (Req 9.3).

    Once the repair loop accepts a candidate, a final :func:`_normalise_origin`
    pass translates the whole layout by one grid-aligned delta so
    ``min(x) == min(y) == CONTAINER_PAD`` — the account-level edge row can never
    pull a coordinate negative (Req 12.4). Normalisation runs **after** repair (a
    pure uniform translation cannot change any relative geometry, so the accepted
    oracle-clean result stays clean, and the repair loop reasons about the
    un-normalised candidate consistently).

    The whole function is deterministic: the pipeline is a pure function of the
    spec, the oracle's finding order is stable, and each repair is a fixed
    transform — so the same spec yields byte-identical geometry every time
    (Req 11.1, 11.4). An over-connected node surfaces as an
    :class:`OverConnectedError` from the pipeline, re-raised as a
    :class:`LayoutError` (unfixable, Req 9.3).

    ``_placement`` is a **private** switch (keyword-only, not part of the
    generator/CLI surface): a generator selects only ``legacy``. It exists so the
    placement loop can request the inner route-only path from ``layout`` without
    re-entering the placement loop, keeping the ``layout`` / ``solve_placement``
    load- and call-time graph acyclic.
    """
    # Contacts + route stage: (placement-loop | scored inner | legacy). The
    # scored PLACEMENT loop is the DEFAULT (1.9.0 Part A, task 3); ``--legacy``
    # retains the rule-driven ten-pass :func:`_place_and_route`; the private
    # ``_placement=False`` selects the 1.8.0 scored inner route path, which the
    # placement loop drives per variant. All three feed the same downstream
    # repair / normalise / serialize stages, so the choice changes only how
    # waypoints (and now the placement) are chosen, never the artifact format
    # (R5.3), and all are deterministic functions of the spec (R5.1).
    spec = _annotate_edge_regions(spec)
    try:
        if legacy:
            return _finish(spec, _place_and_route(spec))
        if _placement:
            # Default: the scored placement outer loop. Lazy import keeps the
            # ``pipeline`` (which ``solver`` imports ``solve`` from at load) and
            # ``solver.solve_placement`` (which imports ``layout`` back) graph
            # one-directional at load time — the loop is entered only here, at
            # call time.
            try:
                from .solver import solve_placement as _solve_placement
            except ImportError:  # pragma: no cover - flat-module fallback
                from layout.solver import solve_placement as _solve_placement  # type: ignore[no-redef]
            return _solve_placement(spec)
        # Inner scored route path (the placement loop's per-variant step, and the
        # 1.8.0 route-only path): no placement search, just place → size → centre
        # → scored solve → repair.
        return _layout_scored_with_guard(spec)
    except OverConnectedError as exc:
        raise LayoutError(
            f"layout({spec.diagram_id!r}) has an over-connected node — the "
            f"diagram must be split or re-laned: {exc}"
        ) from exc


def _annotate_edge_regions(spec: DiagramSpec) -> DiagramSpec:
    """Stamp each edge's ``same_region`` from its endpoints' declared regions.

    Region membership is a spec fact the geometric classifier cannot read from
    boxes; carrying it on the edge lets :func:`routers.classify_edge` refuse to
    call a long in-region hop ``cross-region``. Idempotent, and a no-op for a
    spec whose nodes declare no regions (every synthetic spec)."""
    from dataclasses import replace as _replace
    region = {n.id: n.region for n in spec.nodes}
    edges = []
    changed = False
    for e in spec.edges:
        a, b = region.get(e.source, ""), region.get(e.target, "")
        same = (a == b) if (a and b) else None
        if same != e.same_region:
            e = _replace(e, same_region=same)
            changed = True
        edges.append(e)
    return _replace(spec, edges=tuple(edges)) if changed else spec


def _layout_scored_with_guard(spec: DiagramSpec) -> "PlacedDiagram":
    """The default scored path with the whole-diagram Property 4 guarantee (R3.10).

    The scored solver picks each edge's variant greedily against the edges
    accepted so far and can never do worse than legacy *on the pre-repair
    geometry* (it seeds every edge's rule-based variant with the exact legacy
    route). But the bounded repair loop runs AFTER routing: a scored variant that
    scores lower on ``route_cost`` can trip an oracle finding the legacy route
    does not, and the repair that "fixes" it can reshape an edge into a crossing —
    so the *finished* scored diagram could end up worse than the *finished* legacy
    diagram. Property 4 is a guarantee about the published artifact, so it is
    enforced on the FINISHED diagrams: finish both the scored and the legacy
    candidate and keep the scored one only when it does not score worse. Because
    legacy is always available and both finishes are pure functions of the spec
    (deterministic repair, deterministic normalise), this makes
    ``route_cost(scored) <= route_cost(legacy)`` hold on every diagram while
    staying byte-identical run to run (R4.1). The extra legacy finish is the cost
    of the hard guarantee; the design retains the rule-based route precisely so it
    can be fallen back to."""
    scored = _finish(spec, _place_and_route_scored(spec))
    legacy_finished = _finish(spec, _place_and_route(spec))
    if _finished_cost(legacy_finished).as_tuple() < _finished_cost(scored).as_tuple():
        return legacy_finished
    return scored


def _clear_container_border_rides(candidate: "PlacedDiagram") -> "PlacedDiagram":
    """Return ``candidate`` with every edge's border-riding legs nudged into the
    gap (:func:`routers.nudge_off_container_borders`).

    Shared by the legacy and scored paths (both reach it through :func:`_finish`),
    so whichever router chose the waypoints, a long leg coincident with a
    container border it does not belong to is stepped one grid line clear. The
    contacts are recomputed from the placed boxes so the pinned faces are never
    moved. Deterministic and idempotent: an edge with no border-riding leg is
    returned with its points unchanged."""
    for pe in candidate.edges:
        src = candidate.nodes.get(pe.spec.source)
        tgt = candidate.nodes.get(pe.spec.target)
        if src is None or tgt is None:
            continue
        if None in pe.exit or None in pe.entry:
            continue
        pe.points = nudge_off_container_borders(
            _contact_point(src, pe.exit),
            list(pe.points),
            _contact_point(tgt, pe.entry),
            src, tgt, candidate.containers,
        )
    return candidate


#: A near-contact leg shorter than this reads as a stub/jog rather than a real
#: corridor turn. Matches STAIR_STEP (three grid steps), the router's own unit.
_APPROACH_JOG_MAX = 3 * GRID


def _straighten_top_entry_approaches(candidate: "PlacedDiagram") -> "PlacedDiagram":
    """Rebuild a top-entry spine's approach as a single clean corner when its
    settled route arrives via a short zig-zag, keeping it only when oracle-clean.

    The OCI ``e9`` (hub → sec, sec directly below but past ``obj``) is the case:
    the repair loop bumps its drop corridor to separate it from ``e4``, which is
    correct, but leaves an approach that steps to a near-column, drops a short
    stub, then steps the last grid into the target's top — three legs where the
    clean shape is *drop in the corridor to one lane above the target, step to the
    target's contact column, drop straight into its top*.

    Scoped tight: only a **top-entry** edge (``entryY == 0``) whose current route
    has ``>= 2`` interior waypoints and whose final approach jog is **short**
    (< :data:`_APPROACH_JOG_MAX`) is rebuilt. The rebuild is
    ``[corridor-drop, step-across, straight-drop]`` from the FIRST vertical
    corridor the route already uses, so it reuses the (repair-separated) corridor
    x and only tidies the tail. It is applied and then **reverted unless the whole
    diagram stays oracle-clean**, so it can never introduce a new finding — at
    worst the edge keeps its jogged (but valid) route."""
    for pe in candidate.edges:
        src = candidate.nodes.get(pe.spec.source)
        tgt = candidate.nodes.get(pe.spec.target)
        if src is None or tgt is None or None in pe.exit or None in pe.entry:
            continue
        if not (pe.entry[1] is not None and pe.entry[1] <= 0.0):
            continue                              # only a TOP-face entry
        pts = list(pe.points)
        if len(pts) < 3:
            continue
        # The final approach jog: the last three interior points should form a
        # short step-drop-step. Measure the last two legs; both short ⇒ a jog.
        (ax, ay), (bx, by), (cx, cy) = pts[-3], pts[-2], pts[-1]
        leg1 = abs(ax - bx) + abs(ay - by)
        leg2 = abs(bx - cx) + abs(by - cy)
        if not (leg1 <= _APPROACH_JOG_MAX and leg2 <= _APPROACH_JOG_MAX):
            continue
        entry_pt = _contact_point(tgt, pe.entry)
        # The first vertical corridor the route uses (its drop lane): the x of the
        # first interior waypoint. Drop there to one lane above the target, step to
        # the contact column, then the pinned top entry drops straight in.
        corridor_x = pts[0][0]
        drop_y = _snap(tgt.y - _APPROACH_JOG_MAX)
        rebuilt = [
            (corridor_x, pts[0][1]),
            (corridor_x, drop_y),
            (entry_pt[0], drop_y),
        ]
        # Collapse a redundant first point (exit stub already at corridor_x).
        rebuilt = [p for i, p in enumerate(rebuilt)
                   if i == 0 or rebuilt[i - 1] != p]
        saved = pe.points
        pe.points = rebuilt
        if not _run_oracle(candidate).clean:
            pe.points = saved                     # rebuild broke a rule → revert
    return candidate


def _finish(spec: DiagramSpec, candidate: "PlacedDiagram") -> "PlacedDiagram":
    """Run the bounded repair loop and the final origin normalisation on a routed
    ``candidate`` (the finishing stage shared by the legacy and scored paths).

    On each pass, run the oracle (:func:`_run_oracle`); if it is clean, normalise
    the origin and return; otherwise apply one deterministic repair per fixable
    finding (:func:`_repair`), re-align (:func:`orthogonalise_candidate`), and
    retry. After :data:`MAX_REPAIR_ITERS` passes with a blocking finding still
    present, raise :class:`LayoutError` naming the first unresolved finding
    (Req 9.3). Deterministic: the oracle's finding order is stable and each
    repair is a fixed transform, so the same candidate finishes identically every
    time (Req 11.1, 11.4)."""
    # Reserve a title band above the top container so the diagram title never
    # overlaps the container border / its top-left badge (Req 12.4 + title cell).
    margins = (CONTAINER_PAD, CONTAINER_PAD + TITLE_BAND)

    # 1.10.4: clear any long leg that rides a container border BEFORE the oracle
    # runs, so the finished geometry (from either the scored or the legacy path)
    # keeps the ``edge-on-container-border`` gate clean. A grid-aligned corridor
    # allocated beside a non-grid-aligned border (region right edge at 728,
    # corridor at 730) reads as riding it; step it one grid line into the gap,
    # away from the box (diagram-standards: *a long vertical never coincides with
    # a container border*). The pass is shared here because both routing paths
    # funnel through ``_finish``, and it must precede the oracle so the repair
    # loop validates the nudged route. A route with no border-riding leg is
    # byte-unchanged, so only diagrams with this precise defect move.
    candidate = _clear_container_border_rides(candidate)

    findings = _run_oracle(candidate)
    for _ in range(MAX_REPAIR_ITERS):
        if findings.clean:
            # The repair loop may leave a top-entry spine with a short zig-zag at
            # the contact (the OCI ``e9`` kink: a corridor bump separated it from
            # ``e4`` but the approach then stepped to a near-column, dropped a
            # stub, and stepped again into the target's top). Straighten such an
            # approach on the SETTLED geometry — corridors are final, so the
            # rebuilt single-corner drop is kept only when it stays oracle-clean.
            candidate = _straighten_top_entry_approaches(candidate)
            return _normalise_origin(candidate, margins)
        # Re-align after each repair: a corridor bump moves interior waypoints but
        # not the pinned contacts, so an aligned end leg comes back diagonal
        # (see orthogonalise_candidate).
        candidate = orthogonalise_candidate(_repair(candidate, findings))
        findings = _run_oracle(candidate)

    if findings.clean:
        candidate = _straighten_top_entry_approaches(candidate)
        return _normalise_origin(candidate, margins)
    rule, payload = findings.first_unresolved  # type: ignore[misc]
    raise LayoutError(
        f"layout({spec.diagram_id!r}) still has blocking finding {rule!r} on "
        f"{payload!r} after {MAX_REPAIR_ITERS} repair passes"
    )


def _finished_cost(placed: "PlacedDiagram"):
    """Return the shared graded ``route_cost`` of a finished :class:`PlacedDiagram`.

    Serializes the placed diagram through the engine's own serializer, re-parses
    it with the single ``.drawio`` parser, and measures it with
    :func:`rule_engine.geometry.route_cost` — the exact objective the ratchet and
    ``scripts/route_quality.py`` use (Decision D3). Used by the whole-diagram
    Property 4 guard in :func:`layout` to compare the finished scored diagram
    against the finished legacy diagram."""
    from ..geometry import build_geometry, route_cost  # local: avoid a load cycle
    from ..drawio_model import parse_drawio
    from .repair import _serialize_candidate

    text = _serialize_candidate(placed)
    return route_cost(build_geometry(parse_drawio(text, path="<layout-guard>.drawio")[0]))
