"""Scored per-edge router — the order-score-commit loop (scored-router 1.8.0,
Phase C, task 7.1; design.md §Components → *Component 3: Scored solver*).

This module inverts the routing stage into a **per-edge decision point**. For
each edge, in a deterministic most-constrained-first order, it:

1. asks :func:`rule_engine.layout.variants.generate` for the edge's sanctioned,
   rank-ordered, contract-legal :class:`~rule_engine.layout.variants.RouteVariant`\\ s
   (always including the rule-based route, so the list is never empty — R3.3);
2. for each variant, **snapshots** the :class:`~rule_engine.layout.corridors.CorridorAllocator`,
   tentatively lays the variant's waypoints on the real per-edge router, scores
   the whole diagram (the edges already accepted **plus** this trial variant)
   with the shared graded :func:`rule_engine.geometry.route_cost`, then
   **restores** the allocator — so a rejected variant consumes no lanes (R3.6,
   R3.8, Property 2);
3. selects the winner as the ``argmin`` over the total key
   ``(RouteCost.as_tuple(), variant.rank, variant.id)`` (R3.7);
4. **commits** the winner by re-laying it for real against the live allocator,
   keeping its lanes, and appends it to the accepted set (R3.7).

**The objective is the shared ``route_cost`` (Decision D3).** Scoring goes
through the engine's own serializer → the single ``.drawio`` parser →
:func:`rule_engine.geometry.build_geometry` → :func:`rule_engine.geometry.route_cost`
— the exact path the ratchet and ``scripts/route_quality.py`` use — so the
objective the solver optimises is the objective the gate enforces; the two
cannot drift, and the graded rail penalty added in Phase B is what the argmin
sees.

**Determinism (R4.1, Decision D4).** No randomness, no wall-clock, no reliance
on dict iteration order: the edge order is a pure function of the spec
(:func:`most_constrained_first`), the variant list is rank-ordered, and the
argmin key is total (``rank`` then ``id`` break every ``RouteCost`` tie). The
same spec therefore yields the same routed edge set every time (Property 3).

**Scope of task 7.1 / 7.2.** Task 7.1 lands the core order-score-commit loop
and the most-constrained-first ordering. **Task 7.2 adds the error handling**
(design.md §Error Handling):

* a variant trial that raises
  :class:`~rule_engine.layout.corridors.CorridorExhaustedError` is scored
  **infeasible** — it drops out of the ``argmin`` — and its allocator state is
  restored in a ``finally`` so a partial allocation never leaks (R3.11);
* when **every** variant of an edge is infeasible, the solver falls back to the
  retained :data:`~rule_engine.layout.variants.RoutePlan.RULE_BASED` route (rank
  ``0``, always present) and lays it against the live allocator — accepting
  whatever geometry the router / the downstream widen-re-centre repair loop
  produces — so no diagram becomes unroutable, matching the current behaviour
  (R3.12);
* an **empty** variant list from :func:`variants.generate` is a generator
  contract violation (the rule-based variant is always present, so the list is
  never empty) and raises rather than routing an edge with no variant (R3.13).

Wiring :func:`solve` in as the pipeline default is task 7.3. Until then nothing
on the default :func:`rule_engine.layout.pipeline.layout` path imports this
module, so its presence changes no output (R1.6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

try:  # package-relative import when used as ``rule_engine.layout.solver``
    from ..geometry import (
        Box,
        build_geometry,
        contact_faces,
        orthogonalise_route,
        route_cost,
    )
    from ..drawio_model import parse_drawio
    from .model import Contact, DiagramSpec, EdgeSpec, PlacedDiagram, PlacedEdge
    from .corridors import CorridorAllocator, CorridorExhaustedError
    from .routers import classify_edge, route_edge, _contact_point
    from .repair import _serialize_candidate, place_legend
    from . import variants as _variants
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from geometry import (  # type: ignore[no-redef]
        Box,
        build_geometry,
        contact_faces,
        orthogonalise_route,
        route_cost,
    )
    from drawio_model import parse_drawio  # type: ignore[no-redef]
    from layout.model import Contact, DiagramSpec, EdgeSpec, PlacedDiagram, PlacedEdge  # type: ignore[no-redef]
    from layout.corridors import CorridorAllocator, CorridorExhaustedError  # type: ignore[no-redef]
    from layout.routers import classify_edge, route_edge, _contact_point  # type: ignore[no-redef]
    from layout.repair import _serialize_candidate, place_legend  # type: ignore[no-redef]
    from layout import variants as _variants  # type: ignore[no-redef]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..geometry import RouteCost  # noqa: F401
    from .variants import RouteVariant  # noqa: F401

#: The scored solver's return type: the routed edge set it commits, in the same
#: shape the pipeline's rule-driven stage produces (a list of ``PlacedEdge``),
#: so a caller can drop it straight into a :class:`PlacedDiagram`.
RoutedEdges = List["PlacedEdge"]


class EmptyVariantListError(RuntimeError):
    """An edge's :func:`variants.generate` returned an empty variant list.

    This is a **generator contract violation, not an input condition** (R3.13):
    the rule-based variant (:data:`~rule_engine.layout.variants.RoutePlan.RULE_BASED`,
    rank ``0``) is *always* one of the generated variants, so the list can never
    legitimately be empty. The solver raises this rather than silently routing an
    edge with no variant — an empty list is a programming error in the generator
    that must surface, not be papered over."""

    def __init__(self, edge_id: str):
        self.edge_id = edge_id
        super().__init__(
            f"variants.generate() returned an empty list for edge {edge_id!r}: "
            f"the rule-based variant is always present, so an empty list is a "
            f"generator contract violation (R3.13)"
        )


# ---------------------------------------------------------------------------
# Edge ordering — most-constrained-first (R3.5)
# ---------------------------------------------------------------------------

def _manhattan_span(edge: "EdgeSpec", placed: Dict[str, "Box"]) -> float:
    """Return the Manhattan distance between the edge's source and target centres.

    A longer span is a less flexible run (an inflexible long-haul edge should
    claim its lane before a short two-sided fan-out can crowd it), so it is the
    second ordering key. Measured centre-to-centre from the placed boxes, a pure
    function of the placement."""
    src = placed[edge.source]
    tgt = placed[edge.target]
    sx, sy = src.x + src.w / 2.0, src.y + src.h / 2.0
    tx, ty = tgt.x + tgt.w / 2.0, tgt.y + tgt.h / 2.0
    return abs(tx - sx) + abs(ty - sy)


def most_constrained_first(
    edges,
    placed: Dict[str, "Box"],
    containers: Optional[Dict[str, "Box"]] = None,
    seed_contacts: "Optional[dict]" = None,
) -> List["EdgeSpec"]:
    """Order ``edges`` most-constrained-first — a pure function of the spec (R3.5).

    The order is (design.md §Component 3):

    1. **fewest variants first** — an edge with fewer sanctioned shapes is less
       flexible, so it claims its lanes before a more flexible edge can crowd
       them (an inflexible long-haul run should not be forced onto a worse lane
       by a two-sided fan-out that had many options);
    2. then **longest Manhattan span** — among equally-flexible edges, the longer
       run is the more constraining, so it goes first (``-span`` sorts descending);
    3. then **declared order** — the edge's index in ``spec.edges``, a total,
       spec-only tiebreak so the ordering is fully deterministic (Decision D4).

    The variant *count* is obtained from the real :func:`variants.generate`, so
    the ordering reflects exactly the shapes the scoring loop will consider. This
    function performs no allocation and lays no waypoints — it only counts
    variants and measures spans, so it is a pure, side-effect-free function of
    ``(edges, placed, containers)``.
    """
    edge_list = list(edges)
    declared = {e.id: i for i, e in enumerate(edge_list)}

    def _key(edge: "EdgeSpec") -> Tuple[int, float, int]:
        kind = classify_edge(edge, placed)
        n_variants = len(
            _variants.generate(edge, placed, containers or {}, kind, seed_contacts)
        )
        return (n_variants, -_manhattan_span(edge, placed), declared[edge.id])

    return sorted(edge_list, key=_key)


# ---------------------------------------------------------------------------
# Laying a variant's waypoints on the real router
# ---------------------------------------------------------------------------

def _lay_variant(
    edge: "EdgeSpec",
    variant: "RouteVariant",
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
    alloc: "CorridorAllocator",
    lane_side_override: "Optional[bool]" = None,
    legacy_edge: "Optional[PlacedEdge]" = None,
) -> "PlacedEdge":
    """Lay ``variant``'s waypoints with the shared per-edge router and return a
    :class:`PlacedEdge`.

    Uses the same two-step the pipeline uses for every edge (design.md §control
    flow, and :func:`rule_engine.layout.pipeline._place_and_route` step 3):

    1. :func:`rule_engine.layout.routers.route_edge` classifies the edge and
       dispatches to the matching per-class router, consuming lanes from
       ``alloc`` — this is where a variant may raise
       :class:`~rule_engine.layout.corridors.CorridorExhaustedError`, which the
       caller (:func:`solve`) catches to score the variant infeasible (R3.11);
    2. :func:`rule_engine.geometry.orthogonalise_route` re-aligns the finished
       polyline centrally, exactly as the pipeline does, so a variant's geometry
       is laid the way the real router lays it.

    The variant's contract-legal ``exit`` / ``entry`` contacts (guaranteed by
    :func:`variants.generate`) are the pinned faces; ``route_edge`` lays the
    class-specific waypoints between them. Called both for a **tentative** trial
    (scored then discarded via ``restore``) and for the **commit** re-lay (its
    lanes kept), so the committed geometry is identical to the geometry scored.
    """
    RoutePlan = _variants.RoutePlan
    # The RULE_BASED variant IS the legacy route: when the precomputed legacy
    # geometry for this edge is available, return it verbatim rather than
    # re-routing. Re-routing per-edge in the solver's most-constrained-first order
    # hands out corridor lanes in a different order than the legacy declared-order
    # route, so a re-routed "rule-based" edge would NOT reproduce legacy geometry
    # and Property 4 would break. Returning the exact legacy PlacedEdge guarantees
    # that committing rule-based for every edge reproduces the legacy diagram
    # byte-for-byte, so ``route_cost(scored) <= route_cost(legacy)`` holds.
    if variant.plan is RoutePlan.RULE_BASED and legacy_edge is not None:
        return PlacedEdge(
            spec=edge,
            exit=legacy_edge.exit,
            entry=legacy_edge.entry,
            points=list(legacy_edge.points),
        )

    obstacles = list(placed.values())
    # For any other variant, honour the plan's lane side (:func:`_lane_above_for_plan`),
    # falling back to the global per-edge lane side only for a rule-based route
    # with no precomputed legacy geometry (a synthetic caller / property test).
    if variant.plan is RoutePlan.RULE_BASED and lane_side_override is not None:
        lane_above = lane_side_override
    else:
        lane_above = _lane_above_for_plan(variant.plan)
    pts = route_edge(
        edge,
        variant.exit,
        variant.entry,
        alloc,
        obstacles,
        containers,
        lane_above,
    )
    src_box = placed[edge.source]
    tgt_box = placed[edge.target]
    pts = orthogonalise_route(
        _contact_point(src_box, variant.exit),
        pts,
        _contact_point(tgt_box, variant.entry),
        contact_faces(*variant.exit),
        contact_faces(*variant.entry),
    )
    return PlacedEdge(
        spec=edge, exit=variant.exit, entry=variant.entry, points=list(pts)
    )


def _lane_above_for_plan(plan) -> Optional[bool]:
    """Map a :class:`~rule_engine.layout.variants.RoutePlan` to the router's
    ``lane_above`` argument.

    The lane-side family encodes its choice in the plan: ``LANE_ABOVE`` /
    ``LOOP_ABOVE`` run in the band above the row (``True``), ``LANE_BELOW`` /
    ``DESCEND_NEAR`` below it (``False``). Every other plan leaves the lane side
    to the router's own default (``None``), so a plan that does not concern the
    lane side (e.g. a spine straight-drop) is routed exactly as the pipeline
    would route it."""
    RoutePlan = _variants.RoutePlan
    if plan in (RoutePlan.LANE_ABOVE, RoutePlan.LOOP_ABOVE):
        return True
    if plan in (RoutePlan.LANE_BELOW, RoutePlan.DESCEND_NEAR):
        return False
    return None


# ---------------------------------------------------------------------------
# Scoring — the shared graded route_cost over accepted ∪ {variant}
# ---------------------------------------------------------------------------

def _score(
    accepted: List["PlacedEdge"],
    trial: "PlacedEdge",
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
    spec: "DiagramSpec",
    legend_x: int,
    legend_w: int,
) -> "RouteCost":
    """Score ``accepted ∪ {trial}`` with the SHARED graded ``route_cost`` (D3).

    Assembles a :class:`PlacedDiagram` from the placed nodes/containers plus the
    accepted edges and this trial edge, serializes it through the engine's own
    :func:`rule_engine.layout.repair._serialize_candidate`, re-parses it with the
    single ``.drawio`` parser, and measures it with
    :func:`rule_engine.geometry.route_cost` — the exact objective the ratchet and
    ``route_quality.py`` use (Decision D3, R3.8). Scoring the whole diagram (not
    the trial edge in isolation) is what lets the solver see a variant's
    interaction with the edges already accepted — the design's
    ``route_cost(accepted ∪ {v})``."""
    candidate = PlacedDiagram(
        spec=spec,
        nodes=placed,
        containers=containers,
        edges=list(accepted) + [trial],
        legend_x=legend_x,
        legend_w=legend_w,
    )
    text = _serialize_candidate(candidate)
    return route_cost(build_geometry(parse_drawio(text, path="<solver-trial>.drawio")[0]))


def _legend_for_scoring(
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
    spec: "DiagramSpec",
) -> Tuple[int, int]:
    """Compute a right-margin ``(legend_x, legend_w)`` for the scoring diagram.

    Mirrors :func:`rule_engine.layout.pipeline._place_and_route` step 4 so the
    scored geometry places the Flow/Legend exactly where the finished diagram
    will — past the account container (or the bounding box of all boxes when
    there is no account container). The legend position is stable for a given
    placement, so every trial of every edge scores against the same legend and
    the argmin compares like with like."""
    from ..geometry import LABEL_BAND  # local import: avoid a package cycle at load

    account = next(
        (containers[c.id] for c in spec.containers
         if c.kind == "account" and c.id in containers),
        None,
    )
    if account is None:
        right = max(
            [b.right for b in containers.values()]
            + [placed[n.id].footprint(LABEL_BAND).right for n in spec.nodes],
            default=0.0,
        )
        account = Box("_envelope", 0, 0, right, 0)
    return place_legend(account, spec.flow_lines)


# ---------------------------------------------------------------------------
# Rule-based fallback (R3.12)
# ---------------------------------------------------------------------------

def _rule_based_variant(edge_variants: List["RouteVariant"]) -> "RouteVariant":
    """Return the retained rule-based variant from ``edge_variants``.

    The rule-based route (:data:`~rule_engine.layout.variants.RoutePlan.RULE_BASED`,
    rank ``0``) is always the first variant :func:`variants.generate` emits, so
    when every variant scored infeasible the solver falls back to it (R3.12).
    Matched by its :class:`~rule_engine.layout.variants.RoutePlan` rather than by
    position so the fallback is explicit about *which* variant it lays; falls
    back to the first variant if — impossibly, given the generator contract — no
    rule-based member is present, so the fallback is total and never itself
    raises a lookup error."""
    RoutePlan = _variants.RoutePlan
    for variant in edge_variants:
        if variant.plan is RoutePlan.RULE_BASED:
            return variant
    return edge_variants[0]


# ---------------------------------------------------------------------------
# The order-score-commit loop (R3.5–R3.8)
# ---------------------------------------------------------------------------

def solve(
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
    spec: "DiagramSpec",
    alloc: "CorridorAllocator",
    global_contacts: "Optional[Tuple[dict, dict, dict]]" = None,
    legacy_edges: "Optional[List[PlacedEdge]]" = None,
) -> RoutedEdges:
    """Deterministic scored per-edge routing (design.md §Architecture).

    Orders ``spec.edges`` most-constrained-first (:func:`most_constrained_first`),
    then for each edge tries every sanctioned variant against the edges already
    accepted, snapshotting / restoring ``alloc`` around each trial so a rejected
    variant consumes no lanes, picks the ``argmin`` under the total key
    ``(RouteCost.as_tuple(), variant.rank, variant.id)``, and commits the winner
    by re-laying it for real (keeping its lanes). Returns the committed
    :class:`PlacedEdge` list, in **declared** edge order (the scoring order is an
    internal detail; the returned set is re-sorted to declared order so the
    serialized ``.drawio`` edge order is a pure function of the spec — R4.1).

    ``placed`` / ``containers`` are the placed node / container boxes
    (``Dict[str, Box]``) from ``place → size → centre``; ``alloc`` is the live
    corridor allocator the committed lanes are kept in.

    **Error handling (task 7.2, design.md §Error Handling).** A variant trial
    that raises :class:`~rule_engine.layout.corridors.CorridorExhaustedError` is
    scored infeasible (dropped from the ``argmin``) with its allocator state
    restored in a ``finally`` (R3.11). If *every* variant of an edge is
    infeasible, the solver falls back to the retained rule-based variant and lays
    it against the live allocator, accepting whatever the router / repair loop
    produces (R3.12). An empty variant list raises
    :class:`EmptyVariantListError` — a generator contract violation, never an
    input condition (R3.13).

    Wiring this in as the pipeline default is task 7.3.
    """
    legend_x, legend_w = _legend_for_scoring(placed, containers, spec)

    # Unpack the legacy global-pass result (exit/entry/lane_side per edge). When
    # present, the rule-based variant of every edge is seeded from these global
    # contacts (via ``variants.generate``) and laid with the global lane side, so
    # ``route_cost(RULE_BASED)`` equals the legacy per-edge geometry and the
    # solver's argmin can never do worse than legacy (Property 4 / R3.10).
    if global_contacts is not None:
        g_exits, g_entries, g_lane_sides = global_contacts
        seed_contacts: "Optional[dict]" = {
            eid: (g_exits[eid], g_entries[eid])
            for eid in g_exits
            if eid in g_entries
        }
    else:
        g_lane_sides = {}
        seed_contacts = None

    # The exact legacy geometry per edge (its committed waypoints), so the
    # rule-based variant is laid as the legacy route rather than re-routed
    # per-edge in the solver's own (different) allocation order. Committing
    # rule-based for every edge then reproduces the legacy diagram exactly, which
    # is what makes ``route_cost(scored) <= route_cost(legacy)`` hold (Property 4).
    legacy_by_id: Dict[str, "PlacedEdge"] = (
        {pe.spec.id: pe for pe in legacy_edges} if legacy_edges is not None else {}
    )

    order = most_constrained_first(spec.edges, placed, containers, seed_contacts)
    committed: Dict[str, "PlacedEdge"] = {}
    accepted: List["PlacedEdge"] = []

    for edge in order:
        kind = classify_edge(edge, placed)
        edge_variants = _variants.generate(
            edge, placed, containers, kind, seed_contacts
        )
        # An empty variant list is a generator contract violation: the rule-based
        # variant is always present, so ``generate`` is never empty (R3.3). Raise
        # rather than route an edge with no variant — this is a programming error
        # in the generator, not an input condition (R3.13).
        if not edge_variants:
            raise EmptyVariantListError(edge.id)

        best_key: Optional[Tuple] = None
        best_variant: Optional["RouteVariant"] = None
        for variant in edge_variants:
            # Snapshot → tentatively lay → score (accepted ∪ {variant}) →
            # restore, so this trial's lanes never persist (R3.6, Property 2).
            # A trial that raises CorridorExhaustedError is scored INFEASIBLE:
            # it drops out of the argmin (we ``continue`` past it), and the
            # ``restore`` runs in a ``finally`` so a partial allocation — a
            # variant that widened a gap and took some lanes before raising —
            # never leaks (R3.11).
            token = alloc.snapshot()
            try:
                trial = _lay_variant(
                    edge, variant, placed, containers, alloc,
                    g_lane_sides.get(edge.id), legacy_by_id.get(edge.id),
                )
                cost = _score(
                    accepted, trial, placed, containers, spec, legend_x, legend_w
                )
            except CorridorExhaustedError:
                # Infeasible variant — exclude it from the argmin and try the next.
                continue
            finally:
                alloc.restore(token)

            # argmin over the TOTAL key (RouteCost.as_tuple(), rank, id) — the
            # rank and id break every route_cost tie, so the winner is a pure,
            # reproducible function of the accepted set (R3.7, Decision D4).
            key = (cost.as_tuple(), variant.rank, variant.id)
            if best_key is None or key < best_key:
                best_key = key
                best_variant = variant

        if best_variant is None:
            # Every variant of this edge was infeasible (even the rule-based one
            # raised on its trial). Fall back to the retained rule-based route
            # (always present, rank 0) and lay it against the LIVE allocator,
            # accepting whatever geometry the router — and the downstream
            # widen/re-centre repair loop — produces, exactly as the current
            # rule-driven pipeline does. So no diagram becomes unroutable (R3.12).
            winner = _lay_variant(
                edge, _rule_based_variant(edge_variants), placed, containers, alloc,
                g_lane_sides.get(edge.id), legacy_by_id.get(edge.id),
            )
        else:
            # Commit the winner: re-lay it for real against the LIVE allocator so
            # its lanes are actually consumed and kept (R3.7). Re-laying (rather
            # than reusing the tentative geometry) is what turns the winner's
            # trial lanes into committed ones; the geometry is identical because
            # the lay is a pure function of the contacts + the allocator state,
            # and that state is the accepted set's state on both the winning
            # trial and this commit.
            winner = _lay_variant(
                edge, best_variant, placed, containers, alloc,
                g_lane_sides.get(edge.id), legacy_by_id.get(edge.id),
            )
        committed[edge.id] = winner
        accepted.append(winner)

    # Scored set in DECLARED edge order so the serialized edge order is spec-only
    # (the scoring order is an internal detail that must not leak into the
    # ``.drawio`` — R4.1, byte-identity determinism).
    #
    # The per-edge argmin is a GREEDY heuristic (it scores each edge against only
    # the edges accepted so far), so its pre-repair set can never do worse than
    # legacy — every rule-based variant carries the exact legacy geometry — but a
    # locally-cheaper choice can trip an oracle finding whose downstream *repair*
    # reshapes an edge. The whole-diagram Property 4 guarantee (R3.10) is therefore
    # enforced on the FINISHED diagrams in :func:`rule_engine.layout.pipeline.layout`
    # (which finishes both the scored and the legacy candidate and keeps the scored
    # one only when it does not score worse), not here — so this returns the
    # committed greedy set and leaves the hard guarantee to the pipeline.
    return [committed[e.id] for e in spec.edges]


# ===========================================================================
# The placement outer loop (1.9.0, Part A — design.md §Component A2)
# ===========================================================================


def _placement_cost(placed: "PlacedDiagram") -> "RouteCost":
    """Score a FINISHED :class:`PlacedDiagram` with the SHARED graded
    ``route_cost`` (Decision D3, R5.6).

    Serializes the finished diagram through the engine's own
    :func:`rule_engine.layout.repair._serialize_candidate`, re-parses it with the
    single ``.drawio`` parser, and measures it with the shared
    :func:`rule_engine.geometry.route_cost` — the exact objective the router, the
    ratchet and ``scripts/route_quality.py`` use. No private copy: the objective
    the placement loop optimises is the objective the gate enforces, so the two
    cannot drift (Decision D3). Identical in shape to the pipeline's own
    ``_finished_cost`` guard; kept here so :func:`solve_placement` has a
    self-contained scorer over finished candidates."""
    text = _serialize_candidate(placed)
    return route_cost(
        build_geometry(parse_drawio(text, path="<placement-trial>.drawio")[0])
    )


def solve_placement(spec: "DiagramSpec") -> "PlacedDiagram":
    """Deterministic scored PLACEMENT loop (design.md §Component A2, R1.3/R1.4).

    The outer order-score-commit loop layered over the 1.8.0 routing machinery.
    It enumerates a small, rank-ordered, deterministic set of placement variants
    (:func:`rule_engine.layout.variants.generate_placement_variants`), and for
    **each** variant:

    1. applies the variant's move to the spec
       (:func:`rule_engine.layout.variants.apply_placement_move`) — a pure,
       whole-slot spec transform that keeps every node inside its declared
       container (R1.6);
    2. runs the **full 1.8.0 inner pipeline** — ``place → size → centre → solve →
       repair`` — to a finished candidate (:func:`rule_engine.layout.pipeline.layout`,
       the default scored path), so the candidate is exactly the diagram that
       placement would publish (R1.3);
    3. scores the finished candidate with the shared graded ``route_cost``
       (:func:`_placement_cost`, Decision D3 / R5.6).

    It then selects the ``argmin`` over the total key
    ``(RouteCost.as_tuple(), placement_rank, placement_id)`` (R1.4). The
    **Base_Placement (the identity, rank 0) is always a candidate**, so the
    selected placement's ``route_cost`` can never exceed the base's — the Part A
    analogue of Property 1 (R1.4).

    **Error handling (design.md §Error Handling — the placement loop).** A
    variant whose inner pipeline raises (:class:`~rule_engine.layout.repair.LayoutError`
    — which subsumes an :class:`~rule_engine.layout.contacts.OverConnectedError`
    re-raised by :func:`layout`) is scored **infeasible** and **dropped** from the
    ``argmin``; it never becomes the winner. Because the identity is always
    enumerated first and the base spec is the one the 1.8.0 path could already lay
    out, at least one candidate always finishes — so ``solve_placement`` never
    fails a spec the 1.8.0 path could lay out. A move that would break container
    nesting / padding is not enumerated in the first place (the generator's
    guards), so an infeasible variant here is a genuine routing dead-end, not a
    malformed move.

    **Determinism (Decision D4, R1.5 / R5.1).** ``generate_placement_variants``
    is a pure function of the spec, ``apply_placement_move`` is a pure spec
    transform, :func:`layout` is a deterministic function of its spec, and the
    ``argmin`` key is **total** — ``placement_rank`` then ``placement_id`` break
    every ``RouteCost`` tie — so the same spec always selects the same placement
    and serializes to a byte-identical ``.drawio`` (Property 2). Ties never fall
    to dict/iteration order: with the base at rank 0, an equal-cost move can only
    win if it sorts before the base, which it cannot (rank 0 is minimal), so an
    equal-cost move never displaces the base.

    Returns the finished :class:`PlacedDiagram` of the winning placement, ready
    for :func:`rule_engine.diagram_layout.build_diagram`.
    """
    # Lazy import to avoid the pipeline ⇄ solver import cycle: ``pipeline``
    # imports ``solve`` from this module at load, so this module cannot import
    # ``pipeline`` at load time. The placement loop is not on the default per-edge
    # routing path, so importing ``layout`` here (only when a placement search is
    # requested) keeps the load-time graph one-directional.
    try:
        from .pipeline import layout as _layout, LayoutError
    except ImportError:  # pragma: no cover - flat-module execution fallback
        from layout.pipeline import layout as _layout, LayoutError  # type: ignore[no-redef]

    variants = _variants.generate_placement_variants(spec)

    best_key: Optional[Tuple] = None
    best_placed: Optional["PlacedDiagram"] = None

    for variant in variants:
        moved = _variants.apply_placement_move(spec, variant)
        try:
            # The full 1.8.0 inner pipeline to a FINISHED candidate (place → size →
            # centre → scored solve → repair). ``legacy=False`` keeps the scored
            # per-edge router as the inner routing stage; ``_placement=False``
            # selects the INNER route-only path so this call does NOT re-enter the
            # placement loop — the switch that breaks the layout ⇄ solve_placement
            # recursion (R1.3).
            candidate = _layout(moved, legacy=False, _placement=False)
        except LayoutError:
            # Infeasible placement (the moved layout could not be routed / repaired
            # within bounds, or is over-connected). Drop it from the argmin; the
            # identity always finishes, so the loop never fails (design.md §Error
            # Handling — the base always survives).
            continue

        cost = _placement_cost(candidate)
        # argmin over the TOTAL key (RouteCost.as_tuple(), rank, id): the rank and
        # id break every route_cost tie, so the winner is a pure, reproducible
        # function of the spec, and the rank-0 identity wins every tie it is part
        # of (R1.4, Property 2, Decision D4).
        key = (cost.as_tuple(), variant.rank, variant.id)
        if best_key is None or key < best_key:
            best_key = key
            best_placed = candidate

    if best_placed is None:  # pragma: no cover - the identity always finishes
        # Defensive: the identity (base placement) is always enumerated and always
        # finishes if the 1.8.0 path could lay out the spec at all, so this is
        # unreachable in practice. Fall back to the base layout so the loop never
        # returns ``None`` — again via the inner route-only path (``_placement=
        # False``) so the fallback cannot re-enter the placement loop.
        best_placed = _layout(spec, legacy=False, _placement=False)

    return best_placed
