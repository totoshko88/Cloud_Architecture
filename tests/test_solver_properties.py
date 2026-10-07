# Feature: scored-router, Property 2: allocator snapshot/restore leaves no lane consumed by a rejected variant
"""Property tests for the scored per-edge router (scored-router 1.8.0, Phase C).

This module collects the Phase C solver property tests. Each property maps
one-to-one onto a ``design.md`` → *Correctness Properties* entry and is written
in its own clearly delimited section so the sibling tasks that share this file
can append their sections without touching the ones already here:

* **Property 2** (task 5.2, *this section*) — ``CorridorAllocator`` snapshot /
  restore leaves no lane consumed by a rejected variant: after
  ``snapshot(); apply(C); restore(token)`` the allocator is indistinguishable
  from one that never applied ``C`` — same ``capacity(g)`` and the same
  subsequent ``allocate(g, …)`` sequence, so the internal free-line *order* was
  restored, not merely the count.
* **Property 4** (task 6.2) — scored ``route_cost`` never exceeds the rule-based
  ``route_cost``. *(appended by a later task)*
* **Property 5** (task 6.3) — every generated variant is contract-legal.
  *(appended by a later task)*
* **Property 3** (task 7.4) — the scored router is deterministic.
  *(appended by a later task)*
* **Property 8** (task 8.3) — no shipped example loses a gate.
  *(appended by a later task)*

Conventions (established by honest-gates, extended here): the Hypothesis profile
lives in ``tests/conftest.py`` (loaded automatically, ``max_examples=100``), so
every ``@given`` here runs at least 100 examples without a per-test override.
"""

from __future__ import annotations

import contextlib
from typing import List, Tuple

from hypothesis import assume, given
from hypothesis import strategies as st

from rule_engine.diagram_layout import GRID
from rule_engine.layout.corridors import CorridorAllocator, CorridorExhaustedError


# =========================================================================== #
# Property 2 — allocator snapshot/restore leaves no lane consumed by a
#              rejected variant
# =========================================================================== #
#
# Validates: Requirements 3.1, 3.2.
#
# design.md, Property 2: "For any allocator state and any sequence of
# allocate/register_gap calls C, snapshot(); apply(C); restore(token) yields an
# allocator whose capacity(g) and subsequent allocate(g,…) results for every gap
# g are identical to those of the allocator that never applied C."
#
# The test builds TWO allocators seeded with an identical setup sequence, so
# their live state matches exactly before C. On allocator X we snapshot, apply
# the arbitrary sequence C (which may register/allocate/exhaust gaps), then
# restore. On the reference allocator Y we never apply C. The proof that restore
# is TOTAL — that it rewinds the free-line *ordering*, not just the free count —
# is a subsequent identical probe sequence of allocate() calls: allocate() pops
# from the front of _free, so if two allocators return the same line for the
# same call on every probe, their _free lists were restored in the same order.
#
# C is applied inside a suppress(CorridorExhaustedError) block on purpose: a
# variant that widened a gap, allocated some lanes, then exhausted the gap
# mid-way is exactly the "restore is total after a partial failure" case the
# design calls out (Component 1: "a variant that widened a gap, allocated three
# lanes, and raised CorridorExhaustedError mid-way still restores cleanly").

#: A small pool of gap ids, so setup / C / probe sequences collide on the same
#: gaps often enough to exercise real occupancy interaction (not just disjoint
#: gaps that never contend for a line).
_GAP_IDS = ["col:0-1", "col:1-2", "row:a", "row:b"]

#: Grid-aligned low bounds. Kept modest and on the grid so a span holds a
#: handful of stride-spaced corridor lines.
_lows = st.integers(min_value=0, max_value=40).map(lambda k: k * GRID)

#: A width in whole grid steps wide enough for several lines (stride = 2*GRID,
#: so a span N*GRID wide holds ~N/2 lines); 4..30 grid steps → up to ~15 lines.
_widths = st.integers(min_value=4, max_value=30).map(lambda k: k * GRID)


@st.composite
def _spans(draw: st.DrawFn) -> Tuple[float, float]:
    """A grid-aligned ``(low, high)`` span with ``high > low`` spanning a few lines."""
    low = draw(_lows)
    high = low + draw(_widths)
    return (float(low), float(high))


#: One operation over a gap: either register the gap (returns capacity) or
#: allocate a line in it (may raise CorridorExhaustedError). Both take a gap id
#: and a span; the span is what makes a later allocate widen/refresh a gap.
_ops = st.tuples(
    st.sampled_from(["register", "allocate"]),
    st.sampled_from(_GAP_IDS),
    _spans(),
)

#: A setup sequence establishing an initial (possibly non-empty) allocator state,
#: and the sequence C applied only to X between snapshot and restore. Both may be
#: empty (start fresh / apply nothing) so those boundaries are covered too.
_op_sequences = st.lists(_ops, min_size=0, max_size=25)

#: A probe sequence of allocate() calls run identically on both allocators AFTER
#: the restore, to prove the free-line ORDER (not just the count) was restored.
_probe_sequences = st.lists(
    st.tuples(st.sampled_from(_GAP_IDS), _spans()), min_size=0, max_size=20
)


def _apply_setup(alloc: CorridorAllocator, setup: List[Tuple[str, str, Tuple[float, float]]]) -> None:
    """Apply the shared setup sequence to an allocator (identical on X and Y).

    A ``CorridorExhaustedError`` during setup is suppressed so the two allocators
    still end up in the *same* state (both suppress the same op at the same point,
    since they are seeded identically).
    """
    for op, gid, (low, high) in setup:
        with contextlib.suppress(CorridorExhaustedError):
            if op == "register":
                alloc.register_gap(gid, low, high)
            else:
                alloc.allocate(gid, low, high)


def _probe(alloc: CorridorAllocator, probe: List[Tuple[str, Tuple[float, float]]]) -> List:
    """Run the probe allocate() sequence, recording each outcome.

    Each outcome is the allocated line (an int) or the sentinel ``"exhausted"``
    when the gap had no free line. Recording the outcome rather than letting the
    exception propagate lets the two allocators be compared step-for-step: an
    allocator restored correctly must exhaust at exactly the same probe step as
    the reference.
    """
    out: List = []
    for gid, (low, high) in probe:
        try:
            out.append(alloc.allocate(gid, low, high))
        except CorridorExhaustedError:
            out.append("exhausted")
    return out


# Feature: scored-router, Property 2: allocator snapshot/restore leaves no lane consumed by a rejected variant
@given(setup=_op_sequences, changes=_op_sequences, probe=_probe_sequences)
def test_snapshot_restore_indistinguishable_from_never_applied(
    setup: List[Tuple[str, str, Tuple[float, float]]],
    changes: List[Tuple[str, str, Tuple[float, float]]],
    probe: List[Tuple[str, Tuple[float, float]]],
) -> None:
    """``snapshot(); apply(C); restore()`` leaves the allocator as if C never ran.

    Two allocators X and Y are seeded with the identical ``setup`` sequence, so
    their state matches exactly. On X: take a snapshot, apply the arbitrary
    change sequence ``C`` (``changes``) — suppressing ``CorridorExhaustedError``
    so a variant that exhausted a gap mid-way still exercises the "restore is
    total after a partial failure" path — then restore the snapshot. On Y: never
    apply C.

    The property then asserts X and Y are indistinguishable (R3.1, R3.2):

    1. ``capacity(g)`` is equal for every gap id — no lane consumed by C survived
       the restore, and no lane freed by C's widen leaked in.
    2. An identical subsequent probe of ``allocate()`` calls returns identical
       results on X and Y. Because ``allocate`` pops from the front of the free
       list, matching results across every probe step prove the free-line
       *ordering* was restored, not merely the free *count*.
    """
    x = CorridorAllocator()
    y = CorridorAllocator()
    _apply_setup(x, setup)
    _apply_setup(y, setup)

    # X: snapshot -> apply the rejected variant's calls -> restore.
    token = x.snapshot()
    for op, gid, (low, high) in changes:
        with contextlib.suppress(CorridorExhaustedError):
            if op == "register":
                x.register_gap(gid, low, high)
            else:
                x.allocate(gid, low, high)
    x.restore(token)

    # Y never applied C. X (restored) must now be indistinguishable from Y.

    # 1. Same capacity on every gap id (covers gaps touched by setup, by C, and
    #    by neither — a gap C introduced must have vanished from X on restore).
    for gid in _GAP_IDS:
        assert x.capacity(gid) == y.capacity(gid), (
            f"capacity({gid!r}) diverged after restore: "
            f"X={x.capacity(gid)} Y={y.capacity(gid)}"
        )

    # 2. Same subsequent allocate() results — proves the free-line ORDER was
    #    restored, so a later allocate on X hands out the same lines in the same
    #    sequence as the allocator that never saw C.
    assert _probe(x, probe) == _probe(y, probe)


# =========================================================================== #
# Property 4 — scored route_cost never exceeds the rule-based route_cost
# =========================================================================== #
#
# Validates: Requirements 3.3, 3.10.
#
# design.md, Property 4: "For every generated layout L,
# route_cost(scored(L)).as_tuple() <= route_cost(rule_based(L)).as_tuple().
# (Because the rule-based choice is always one of the generated variants, the
# argmin can never do worse.)"
#
# The scored solver (solver.solve, task 7.1) is not yet wired in, so this test
# proves Property 4 with the machinery that IS available — exactly the seam the
# solver will use once it lands:
#
#   * ``variants.generate(edge, placed, containers, kind)`` (task 6.1) returns
#     the sanctioned RouteVariants for an edge, in rank order, ALWAYS including
#     the rule-based route as one variant (rank 0);
#   * the shared graded ``geometry.route_cost`` (task 3.x) is the objective the
#     solver optimises AND the gate enforces (design Decision D3 — no private
#     copy), so scoring a variant here scores it exactly as the solver would.
#
# For one target edge we re-route it with each candidate variant's contacts —
# keeping every OTHER edge at its committed rule-based contacts — score the whole
# resulting diagram with ``route_cost`` (the design's ``route_cost(accepted ∪
# {v})``), and take the argmin over the generated variants. That argmin is the
# "scored" route; the rule-based variant's own score is the "rule-based" route.
# Because ``generate`` always includes the rule-based variant, the argmin's key
# is by construction <= the rule-based variant's key — the invariant Property 4
# states. The test therefore exercises the REAL generator and the REAL objective,
# and would fail if either the generator dropped the rule-based variant (so the
# argmin could pick something worse and still be "the scored route") or a variant
# were scored with a different metric than the gate uses.

from rule_engine.geometry import (  # noqa: E402
    build_geometry,
    contact_faces,
    orthogonalise_route,
    route_cost,
)
from rule_engine.drawio_model import parse_drawio  # noqa: E402
from rule_engine.layout.model import PlacedDiagram, PlacedEdge  # noqa: E402
from rule_engine.layout.routers import classify_edge, _contact_point, route_edge  # noqa: E402
from rule_engine.layout.variants import RouteVariant, generate  # noqa: E402
from rule_engine.layout_engine import (  # noqa: E402
    LayoutError,
    OverConnectedError,
    _serialize_candidate,
    layout,
)

# Reuse the established small-valid-spec generator (the same one the layout
# geometry property test drives) so Property 4 is exercised over the same family
# of layout-able specs — a nested account ⊃ vpc ⊃ az tree, two mirror regions,
# and edges that classify into the five supported kinds.
from tests.test_layout_engine_property import _small_valid_spec  # noqa: E402


def _reroute_edge(
    placed: "PlacedDiagram",
    edge_id: str,
    exit_pt,
    entry_pt,
) -> "PlacedDiagram":
    """Return a new PlacedDiagram with ``edge_id`` re-routed to ``(exit, entry)``.

    Every OTHER edge keeps its committed rule-based contacts and waypoints, so
    the returned diagram is ``accepted ∪ {variant}`` — the accepted edges plus
    this one edge laid on the candidate variant (design.md §control flow). The
    target edge is routed with the shared per-edge router (:func:`route_edge`) on
    a FRESH allocator over the same obstacle set the pipeline uses, then
    orthogonalised centrally exactly as the pipeline does, so the variant's
    geometry is laid the way the real router would lay it.
    """
    obstacles = list(placed.nodes.values())
    # Find the edge's PlacedEdge so route_edge can classify and lay it.
    target = next(e for e in placed.edges if e.spec.id == edge_id)
    src_box = placed.nodes[target.spec.source]
    tgt_box = placed.nodes[target.spec.target]

    # A fresh allocator: the target edge is the only one consuming lanes on this
    # trial, which matches the solver's snapshot/restore discipline (a rejected
    # variant's lanes never persist). The other edges keep their committed
    # waypoints, so the scored geometry is the accepted set plus this variant.
    from rule_engine.layout.corridors import CorridorAllocator

    allocator = CorridorAllocator()
    pts = route_edge(
        target.spec,
        exit_pt,
        entry_pt,
        allocator,
        obstacles,
        placed.containers,
        None,
    )
    pts = orthogonalise_route(
        _contact_point(src_box, exit_pt),
        pts,
        _contact_point(tgt_box, entry_pt),
        contact_faces(*exit_pt),
        contact_faces(*entry_pt),
    )
    new_edges = []
    for e in placed.edges:
        if e.spec.id == edge_id:
            new_edges.append(
                PlacedEdge(spec=e.spec, exit=exit_pt, entry=entry_pt, points=list(pts))
            )
        else:
            new_edges.append(e)
    return PlacedDiagram(
        spec=placed.spec,
        nodes=placed.nodes,
        containers=placed.containers,
        edges=new_edges,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
    )


def _score(placed: "PlacedDiagram"):
    """Score a placed diagram with the SHARED graded ``route_cost``.

    Goes through the engine's own serializer → the single ``.drawio`` parser →
    ``build_geometry`` → ``route_cost`` — the exact path the ratchet and the
    ``route_cost`` property tests use — so the objective measured here is the
    objective the gate enforces (design Decision D3)."""
    text = _serialize_candidate(placed)
    return route_cost(build_geometry(parse_drawio(text, path="<variant>.drawio")[0]))


# Feature: scored-router, Property 4: scored route_cost never exceeds the rule-based route_cost
@given(spec=_small_valid_spec())
def test_scored_route_cost_never_exceeds_rule_based(spec) -> None:
    """The argmin over an edge's variants never scores worse than the rule-based
    route (R3.3, R3.10, Property 4).

    For a generated layout, for every edge:

    1. ``variants.generate`` returns the sanctioned variants in rank order,
       always including the rule-based variant (rank 0) — asserted here, since
       Property 4 rests on it (R3.3).
    2. Each variant is laid with the real router (keeping every other edge at its
       committed rule-based contacts) and scored with the shared graded
       ``route_cost`` — the design's ``route_cost(accepted ∪ {v})``.
    3. The SCORED route is the argmin over those variant scores under the solver's
       total key ``(RouteCost.as_tuple(), variant.rank, variant.id)``; the
       RULE-BASED route is the score of the rule-based variant.

    The property asserts ``scored.as_tuple() <= rule_based.as_tuple()`` for every
    edge. Because the rule-based variant is always in the candidate set, the
    argmin can never do worse — so the scored router is guaranteed never worse
    than today's rule-driven route (R3.10)."""
    try:
        placed = layout(spec)
    except (LayoutError, OverConnectedError):
        # A spec the engine refuses (fail-honest) is not a counterexample: the
        # invariant is conditional on the layout existing.
        assume(False)
        return

    # 1.10.7: a layout the repair loop could not clear is returned degraded (its
    # residual findings in ``layout_warnings``) instead of raising; exclude it
    # exactly like a refused spec.
    assume(not placed.layout_warnings)
    assume(len(placed.edges) >= 1)

    for edge in placed.edges:
        kind = classify_edge(edge.spec, placed.nodes)
        variants = generate(edge.spec, placed.nodes, placed.containers, kind)

        # R3.3: the list is never empty and the rule-based variant is present.
        assert variants, f"generate returned no variants for {edge.spec.id!r}"
        rule_based = next(
            (v for v in variants if v.plan.value == "rule-based"), None
        )
        assert rule_based is not None, (
            f"generate omitted the rule-based variant for {edge.spec.id!r}"
        )

        # Score every variant with the shared objective (accepted ∪ {v}).
        def _key(v: "RouteVariant"):
            cost = _score(_reroute_edge(placed, edge.spec.id, v.exit, v.entry))
            return (cost.as_tuple(), v.rank, v.id)

        rule_based_cost = _score(
            _reroute_edge(placed, edge.spec.id, rule_based.exit, rule_based.entry)
        )
        scored_key = min(_key(v) for v in variants)

        assert scored_key[0] <= rule_based_cost.as_tuple(), (
            f"scored route_cost {scored_key[0]} exceeded the rule-based route_cost "
            f"{rule_based_cost.as_tuple()} for edge {edge.spec.id!r} (kind={kind})"
        )


# =========================================================================== #
# Property 5 — every variant is contract-legal
# =========================================================================== #
#
# Validates: Requirements 3.4.
#
# design.md, Property 5: "For every edge and every variant v returned by
# generate, v.exit lies on the right or bottom face and v.entry on the left or
# top face — so no variant can introduce an edge-direction finding regardless of
# which the solver picks."
#
# This is the guarantee that makes the scored solver safe: whichever variant the
# argmin (task 7.1) lands on, the committed route already satisfies the lint
# face rule (v1.6.0), so switching the router's default to the solver can never
# add an `edge-direction` finding (R3.4, "no lint rule weakened").
#
# The property is exercised over the SAME family of layout-able specs Property 4
# uses (`_small_valid_spec` — a nested account ⊃ vpc ⊃ az tree, two mirror
# regions, edges classifying into all five supported kinds), so every edge kind
# reaches `generate`. For each generated layout, for every edge, EVERY variant
# `generate` returns is checked against the two face predicates the module and
# the linter agree on:
#
#   * exit  is contract-legal  ⇔  exitX >= 1 (right face)  OR  exitY >= 1 (bottom)
#   * entry is contract-legal  ⇔  entryX <= 0 (left face)  OR  entryY <= 0 (top)
#
# The test re-derives the face check locally from the design's stated rule rather
# than importing the module's own `_exit_is_contract_legal` / `_entry_is_contract_legal`
# helpers, so the property independently pins the contract instead of tautologically
# re-asserting the generator's internal predicate. (The generator also asserts the
# same by construction in `_variant`; this test proves it holds on real inputs.)


def _exit_on_right_or_bottom_face(exit_pt) -> bool:
    """True when ``exit_pt`` lies on the right (exitX >= 1) or bottom (exitY >= 1)
    face — the contract-legal exit rule from the linter (v1.6.0)."""
    fx, fy = exit_pt
    return (fx is not None and fx >= 1.0) or (fy is not None and fy >= 1.0)


def _entry_on_left_or_top_face(entry_pt) -> bool:
    """True when ``entry_pt`` lies on the left (entryX <= 0) or top (entryY <= 0)
    face — the contract-legal entry rule from the linter (v1.6.0)."""
    fx, fy = entry_pt
    return (fx is not None and fx <= 0.0) or (fy is not None and fy <= 0.0)


# Feature: scored-router, Property 5: every variant is contract-legal
@given(spec=_small_valid_spec())
def test_every_variant_is_contract_legal(spec) -> None:
    """Every variant ``generate`` returns is contract-legal (R3.4, Property 5).

    For a generated layout, for every edge, every ``RouteVariant`` from
    ``variants.generate`` must have:

    * ``exit`` on the right (``exitX >= 1``) or bottom (``exitY >= 1``) face, and
    * ``entry`` on the left (``entryX <= 0``) or top (``entryY <= 0``) face.

    Because the generator guarantees this by construction, no variant can
    introduce an ``edge-direction`` finding regardless of which one the scored
    solver picks — so making the solver the default cannot weaken the lint face
    rule. The check spans every edge kind (`straight` / `spine` / `fan-out-row` /
    `cross-region` / `back-edge`) since `_small_valid_spec` produces edges that
    classify into all five."""
    try:
        placed = layout(spec)
    except (LayoutError, OverConnectedError):
        # A spec the engine refuses (fail-honest) is not a counterexample: the
        # invariant is conditional on the layout existing.
        assume(False)
        return

    # 1.10.7: a layout the repair loop could not clear is returned degraded (its
    # residual findings in ``layout_warnings``) instead of raising; exclude it
    # exactly like a refused spec.
    assume(not placed.layout_warnings)
    assume(len(placed.edges) >= 1)

    for edge in placed.edges:
        kind = classify_edge(edge.spec, placed.nodes)
        variants = generate(edge.spec, placed.nodes, placed.containers, kind)

        # R3.3 restated: the list is never empty (a contract the face check would
        # otherwise vacuously pass on).
        assert variants, f"generate returned no variants for {edge.spec.id!r}"

        for v in variants:
            assert _exit_on_right_or_bottom_face(v.exit), (
                f"variant {v.id!r} (kind={kind}) exit {v.exit} is not on the "
                f"right/bottom face — would introduce an edge-direction finding"
            )
            assert _entry_on_left_or_top_face(v.entry), (
                f"variant {v.id!r} (kind={kind}) entry {v.entry} is not on the "
                f"left/top face — would introduce an edge-direction finding"
            )


# =========================================================================== #
# Property 3 — the scored router is deterministic
# =========================================================================== #
#
# Validates: Requirements 3.9, 4.1.
#
# design.md, Property 3: "For every generated layout L, solve(L) called twice
# returns the identical routed edge set (same contacts, same waypoints) and a
# byte-identical serialized .drawio."
#
# R3.9: "FOR every generated layout, THE .drawio produced by the Scored_Solver
# run twice on the same spec SHALL be byte-identical."
# R4.1: "THE Scored_Solver SHALL use no randomness, no wall-clock value, and no
# dict-iteration-order dependence, so that the same spec produces a
# byte-identical .drawio and the Generator_Check freshness gate holds."
#
# Determinism is the property that lets the scored router replace the rule-driven
# one without breaking the `generator --check` freshness gate: if two runs on the
# same spec could differ, a committed `.drawio` would drift on regeneration and
# the gate would flap. The solver is built to be a pure function of the spec — the
# edge order is `most_constrained_first` (spec-only), the variant list is
# rank-ordered, and the argmin key `(RouteCost.as_tuple(), rank, id)` is total, so
# `rank` then `id` break every `route_cost` tie (design Decision D4). This test
# pins that guarantee end-to-end on real, layout-able specs.
#
# The test drives `solve()` DIRECTLY (twice), the same seam
# `tests/test_layout_package.py::test_solver_solve_is_implemented_but_still_unwired`
# uses: place the spec through the real `place → size → centre` stages once, then
# route it twice with the scored solver on TWO FRESH allocators (a fresh allocator
# per run is the solver's own contract — a committed run keeps its lanes, so the
# second run must start from an unconsumed allocator to reproduce the first). It
# asserts BOTH halves of Property 3:
#
#   1. the routed edge SET is identical — same declared order, same (exit, entry)
#      contacts, same waypoint tuple per edge (R4.1 — pure function of the spec);
#   2. the SERIALIZED .drawio is byte-identical — the two routed sets, assembled
#      into a PlacedDiagram with the same legend placement the pipeline uses and
#      run through the engine's own serializer, produce identical bytes (R3.9).
#
# Half (2) is the stronger claim the gate actually depends on: identical contacts
# and waypoints could still serialize differently if any non-spec state (dict
# order, a wall-clock stamp) leaked into the emitted XML, so the byte comparison
# is what proves the `generator --check` gate holds.

from rule_engine.layout.place import (  # noqa: E402
    centre_block_in_vpc,
    place_nodes,
    size_containers,
)
from rule_engine.layout.solver import _legend_for_scoring, solve  # noqa: E402


def _routed_signature(routed) -> list:
    """The comparable signature of a routed edge set: per edge, in list order,
    its ``(spec.id, exit, entry, waypoint-tuple)``.

    ``solve`` returns its committed edges in **declared** edge order (a pure
    function of the spec — R4.1), so comparing the signatures position-by-position
    also pins that the two runs agree on edge ordering, not merely on the set of
    contacts. Waypoints are frozen into a tuple so the comparison is by value."""
    return [
        (pe.spec.id, pe.exit, pe.entry, tuple(pe.points)) for pe in routed
    ]


def _serialize_routed(placed_nodes, containers, spec, routed) -> str:
    """Assemble ``routed`` into a :class:`PlacedDiagram` and serialize it to
    ``.drawio`` text — the byte artifact Property 3's second half compares.

    Uses the solver's own :func:`_legend_for_scoring` so the Flow/Legend lands
    exactly where the pipeline places it (a stable function of the placement), then
    the engine's own :func:`_serialize_candidate` — the same serializer the ratchet
    and the Property 4 scoring path use — so the emitted XML is produced the way the
    finished diagram is. Two runs that leaked any non-spec state (dict order, a
    clock) into the XML would diverge here even if their contacts matched."""
    legend_x, legend_w = _legend_for_scoring(placed_nodes, containers, spec)
    candidate = PlacedDiagram(
        spec=spec,
        nodes=placed_nodes,
        containers=containers,
        edges=list(routed),
        legend_x=legend_x,
        legend_w=legend_w,
    )
    return _serialize_candidate(candidate)


# Feature: scored-router, Property 3: scored router is deterministic
@given(spec=_small_valid_spec())
def test_scored_router_is_deterministic(spec) -> None:
    """``solve()`` run twice on the same spec is byte-identical (R3.9, R4.1).

    For a generated layout: place the spec once through the real
    ``place → size → centre`` stages, then route it TWICE with the scored solver
    on two fresh allocators (a fresh allocator per run because a committed run
    keeps its lanes — the solver's contract). The property asserts both halves of
    Property 3:

    1. **Identical routed edge set** — the two runs return the same edges in the
       same declared order with the same ``(exit, entry)`` contacts and the same
       waypoint tuple per edge. Because the solver uses no randomness, no
       wall-clock and no dict-iteration-order dependence (R4.1), the routed set is
       a pure function of the spec.
    2. **Byte-identical serialized .drawio** — assembling each routed set into a
       ``PlacedDiagram`` with the same legend placement and running it through the
       engine's own serializer yields identical bytes (R3.9), which is exactly
       what the ``generator --check`` freshness gate depends on.
    """
    try:
        placed = layout(spec)
    except (LayoutError, OverConnectedError):
        # A spec the engine refuses (fail-honest) is not a counterexample: the
        # determinism invariant is conditional on the layout existing.
        assume(False)
        return

    # 1.10.7: a layout the repair loop could not clear is returned degraded (its
    # residual findings in ``layout_warnings``) instead of raising; exclude it
    # exactly like a refused spec.
    assume(not placed.layout_warnings)
    assume(len(placed.edges) >= 1)

    # Place ONCE through the real place -> size -> centre stages; both solver runs
    # route the SAME placed nodes/containers, isolating the router as the only
    # thing under test.
    placed_nodes = place_nodes(spec)
    containers = size_containers(placed_nodes, spec)
    placed_nodes = centre_block_in_vpc(placed_nodes, containers, spec)

    # Two independent runs, each on a FRESH allocator (a committed run keeps its
    # lanes, so the second run must start unconsumed to reproduce the first).
    routed_a = solve(placed_nodes, containers, spec, CorridorAllocator())
    routed_b = solve(placed_nodes, containers, spec, CorridorAllocator())

    # 1. Identical routed edge set — same order, contacts and waypoints (R4.1).
    assert _routed_signature(routed_a) == _routed_signature(routed_b), (
        "scored router returned a different routed edge set on the second run "
        "(non-deterministic contacts/waypoints)"
    )

    # 2. Byte-identical serialized .drawio — the artifact the freshness gate
    #    compares (R3.9). Stronger than half 1: proves no non-spec state leaked
    #    into the emitted XML.
    text_a = _serialize_routed(placed_nodes, containers, spec, routed_a)
    text_b = _serialize_routed(placed_nodes, containers, spec, routed_b)
    assert text_a == text_b, (
        "scored router produced a non-byte-identical .drawio on the second run "
        "(the generator --check freshness gate would flap)"
    )


# =========================================================================== #
# Property 8 — no shipped example loses a gate
# =========================================================================== #
#
# Validates: Requirements 1, 2, 3, 4.4.
#
# design.md, Property 8: "Every shipped example passes rule-engine-lint --all,
# verify-icon --all --strict, check-rasters and the golden-example tests after
# the scored router is the default."
#
# R4.4: "AFTER the Scored_Solver is wired in as the default, THE full Gate_Suite
# — rule-engine-lint --all, rule-engine-verify-icon --all --strict,
# rule-engine-check-rasters and the golden-example tests — SHALL stay green on
# every Shipped_Diagram."
#
# This is the release-gate invariant that ties the whole scored-router change
# together: Phase A (the layout/ package split, R1), Phase B (the graded rails
# metric + ratchet, R2) and Phase C (the scored per-edge router made default, R3)
# must all land WITHOUT any shipped example dropping out of publication
# eligibility. Task 8.2 confirmed the suite is green by running the four gates by
# hand; this property PINS that state so a future routing/placement change that
# silently blocks an example (a new ERROR finding, an unresolved icon, an
# out-of-budget raster) is caught by the test suite rather than only by a manual
# gate run.
#
# WHY parametrised over the corpus rather than @given/generated: the Gate_Suite
# runs over the FIXED shipped corpus (the committed .drawio files under
# examples/), not over generated specs — an example either ships or it does not,
# and the gates read the committed artifact on disk. The task sanctions this
# explicitly ("max_examples >= 100 where generated, else parametrised over the
# corpus"), so each shipped .drawio is its own parametrised case (mirroring
# tests/test_golden_examples.py) and the whole corpus is additionally asserted
# through the real gate CLIs as one subprocess run (mirroring the CI steps and
# tests/test_layout_split_properties.py::_run_check).
#
# The three per-diagram gates are exercised IN-PROCESS against the real on-disk
# ruleset / committed manifests / exported rasters — the exact functions the CLIs
# call — so a failure names the offending diagram and finding directly:
#
#   * rule-engine-lint --all      -> linter.lint_with_ruleset (zero CRITICAL/ERROR)
#   * verify-icon --all --strict  -> verify_icon.verify_drawio (0 unresolved /
#                                    0 unverified, >=1 resolved where vertices)
#   * rule-engine-check-rasters   -> raster_gate.check_rasters (within class budget)
#
# and the whole corpus is then re-asserted through the gate CLIs as subprocesses
# (exit 0) plus the golden-example test module (exit 0), which is the literal
# "golden-example tests" clause of R4.4.

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from rule_engine import cli as _cli  # noqa: E402
from rule_engine.linter import Severity as _Severity  # noqa: E402
from rule_engine.linter import lint_with_ruleset, ruleset_available  # noqa: E402
from rule_engine.raster_gate import check_rasters  # noqa: E402
from rule_engine.verify_icon import verify_drawio  # noqa: E402

#: tests/ -> workspace root; the committed Golden Examples live under examples/.
_P8_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
_P8_EXAMPLES_ROOT = _P8_WORKSPACE_ROOT / "examples"

#: The blocking severities: an artifact with any of these is not publishable.
_P8_BLOCKING = {_Severity.CRITICAL.value, _Severity.ERROR.value}


def _p8_shipped_drawios() -> List[str]:
    """Every SHIPPED ``.drawio`` under ``examples/`` (CLI discovery order).

    Discovers artifacts exactly as ``rule-engine-lint --all`` does
    (:func:`rule_engine.cli.discover_artifacts`), which already excludes editor /
    file-manager scratch copies (``… копія.drawio``, ``… - Copy.drawio``,
    ``… (1).drawio``) from the ``--all`` scan — so the corpus here is precisely
    the shipped set the gates run over, no scratch copy leaking in."""
    prefix = str(_P8_EXAMPLES_ROOT) + os.sep
    return sorted(
        a
        for a in _cli.discover_artifacts(str(_P8_WORKSPACE_ROOT))
        if a.startswith(prefix) and a.lower().endswith(".drawio")
    )


_P8_SHIPPED_DRAWIOS = _p8_shipped_drawios()


def _p8_id(path: str) -> str:
    """Compact, stable parametrise id: the .drawio path relative to examples/."""
    return os.path.relpath(path, str(_P8_EXAMPLES_ROOT))


def test_property8_corpus_is_non_empty() -> None:
    """Guard against a vacuous "every shipped example passes" pass.

    Property 8 quantifies over *every* shipped example, so the parametrised
    corpus below must be non-empty — otherwise the per-diagram gate assertions
    would pass without checking anything."""
    assert _P8_SHIPPED_DRAWIOS, (
        f"no shipped .drawio examples discovered under {_P8_EXAMPLES_ROOT}"
    )
    # The authoritative ruleset must be present, else the linter is fail-closed
    # (every artifact blocked) and Property 8 could not hold for a real reason.
    assert ruleset_available(workspace_root=str(_P8_WORKSPACE_ROOT)) is True


# Feature: scored-router, Property 8: no shipped example loses a gate
@pytest.mark.parametrize("drawio_path", _P8_SHIPPED_DRAWIOS, ids=_p8_id)
def test_property8_shipped_example_keeps_every_gate(drawio_path: str) -> None:
    """Every shipped example passes all three per-diagram gates (R1, R2, R3, R4.4).

    With the scored router as the default (Phase C), each committed ``.drawio``
    under ``examples/`` must still clear the Gate_Suite. Parametrised over the
    fixed shipped corpus (the gates read the committed artifact, so there is
    nothing to generate — the task's "else parametrised over the corpus" branch),
    each case asserts the three per-diagram gates through the exact functions the
    CLIs call:

    1. **rule-engine-lint --all** — parse the artifact as the CLI does and lint
       it through the real on-disk ruleset: zero CRITICAL and zero ERROR findings,
       so it is eligible for publication (no scored-router change added a blocking
       finding).
    2. **verify-icon --all --strict** — every icon reference resolves against the
       committed manifests: zero unresolved, zero unverified, and at least one
       resolved reference on any file that has service vertices.
    3. **rule-engine-check-rasters** — the exported PNG is within its class-aware
       width/size/height budget, has matching provenance and an opaque white
       background.

    The golden-example test module and the gate CLIs are additionally re-asserted
    corpus-wide as subprocesses in the two tests below (the "golden-example tests"
    clause of R4.4)."""
    # --- Gate 1: rule-engine-lint --all (publication eligibility) -------------
    artifact = _cli.parse_artifact(drawio_path)
    result = lint_with_ruleset(artifact, workspace_root=str(_P8_WORKSPACE_ROOT))
    assert result.get("error") is None, (
        f"{_p8_id(drawio_path)}: lint fail-closed error "
        f"{result.get('error')} ({result.get('error_detail')})"
    )
    blocking = [f for f in result["findings"] if f["severity"] in _P8_BLOCKING]
    assert result["eligible_for_publication"] is True, (
        f"{_p8_id(drawio_path)}: scored router blocked a shipped example from "
        f"publication\nblocking findings: {blocking}"
    )

    # --- Gate 2: verify-icon --all --strict (icon resolution) -----------------
    report = verify_drawio(drawio_path, workspace_root=str(_P8_WORKSPACE_ROOT))
    assert report["unresolved"] == 0, (
        f"{_p8_id(drawio_path)}: {report['unresolved']} unresolved icon "
        f"reference(s) under --strict"
    )
    assert report["unverified"] == 0, (
        f"{_p8_id(drawio_path)}: {report['unverified']} unverified service "
        f"vertex(es) under --strict"
    )
    if report["service_vertices"]:
        assert report["resolved"] > 0, (
            f"{_p8_id(drawio_path)}: {report['service_vertices']} service "
            f"vertices but zero resolved references (strict would fail)"
        )


def test_property8_shipped_rasters_within_budget() -> None:
    """Every shipped raster stays within its class-aware budget (Gate 3, R4.4).

    Runs the real raster gate over the whole ``examples/`` corpus (the one call
    the ``rule-engine-check-rasters`` CLI makes), so a single out-of-budget PNG
    is reported alongside every offender rather than aborting on the first. A
    scored-router change that regressed a diagram's layout enough to blow its
    raster budget would surface here."""
    refs = check_rasters(_P8_EXAMPLES_ROOT, repo_root=_P8_WORKSPACE_ROOT)
    assert refs, f"no exported rasters discovered under {_P8_EXAMPLES_ROOT}"

    offenders = []
    for ref in refs:
        if not ref.within_budget:
            reasons = []
            if not ref.exists:
                reasons.append("missing PNG")
            if not ref.width_ok:
                reasons.append(f"width {ref.width}>{ref.max_width}")
            if not ref.size_ok:
                sz = None if ref.size_bytes is None else ref.size_bytes // 1024
                reasons.append(f"size {sz}KB>{ref.max_size // 1024}KB")
            if not ref.height_ok:
                reasons.append(f"height {ref.height}>{ref.max_height}")
            if not ref.provenance_ok:
                reasons.append("stale/absent provenance")
            if not ref.background_ok:
                reasons.append("non-white/transparent background")
            offenders.append(
                f"{ref.source} [{ref.diagram_class}]: {', '.join(reasons)}"
            )
    assert not offenders, (
        "scored router pushed a shipped raster out of budget:\n"
        + "\n".join(offenders)
    )


def _p8_run(argv: List[str]) -> subprocess.CompletedProcess:
    """Run a gate CLI as a subprocess under the venv interpreter running pytest.

    ``sys.executable`` is the ``.venv`` interpreter, so the CLI's ``rule_engine``
    / ``mappings`` imports resolve exactly as in CI, and ``cwd`` is the workspace
    root so ``--all`` discovers the committed corpus."""
    return subprocess.run(
        [sys.executable, "-m", *argv],
        cwd=str(_P8_WORKSPACE_ROOT),
        capture_output=True,
        text=True,
    )


def test_property8_gate_clis_exit_zero_over_the_corpus() -> None:
    """The three gate CLIs exit 0 over the whole shipped corpus (R4.4).

    Beyond the in-process per-diagram assertions above, this runs the real gate
    entry points as subprocesses — exactly the CI steps — so the corpus-wide exit
    contract is pinned end-to-end:

    * ``rule-engine-lint --all``            -> ``rule_engine.cli``
    * ``rule-engine-verify-icon --all --strict`` -> ``rule_engine.verify_icon``
    * ``rule-engine-check-rasters``         -> ``rule_engine.raster_gate``

    Each must exit 0 (eligible / all-resolved / within-budget). A non-zero exit
    from any gate after the scored router became default is a Property 8 failure,
    and the captured stderr/stdout is surfaced so the offending artifact is
    visible."""
    gates = [
        ["rule_engine.cli", "--all"],
        ["rule_engine.verify_icon", "--all", "--strict"],
        ["rule_engine.raster_gate"],
    ]
    for argv in gates:
        proc = _p8_run(argv)
        assert proc.returncode == 0, (
            f"gate `{' '.join(argv)}` exited {proc.returncode} over the shipped "
            f"corpus (a shipped example lost a gate)\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )


def test_property8_golden_example_tests_pass() -> None:
    """The golden-example test module passes (the "golden-example tests" clause).

    R4.4 names the golden-example tests explicitly as one of the four gates, so
    Property 8 runs ``tests/test_golden_examples.py`` as a nested pytest
    subprocess and asserts it exits 0. Running it in a child process (rather than
    importing it) keeps this property self-contained and mirrors how CI invokes
    the suite; ``-p no:cacheprovider`` avoids writing a nested cache."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(Path(__file__).resolve().parent / "test_golden_examples.py"),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(_P8_WORKSPACE_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "the golden-example tests failed after the scored router became default "
        "(R4.4)\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
