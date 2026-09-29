"""Per-edge sanctioned-variant generator (scored-router 1.8.0, Phase C, task
6.1; design.md §Components → *Component 2: Variant generator*).

For one edge this module enumerates the router's **sanctioned** route shapes as
:class:`RouteVariant` descriptors — the discrete ``(exit, entry, plan)`` choices
the ten contact passes make implicitly today, made explicit and enumerable so
the scored solver (task 7.1) can try each, score it with the shared graded
``route_cost``, and commit the cheapest.

**Two invariants the generator guarantees by construction** (the properties the
solver leans on so it can never do worse than today):

* :func:`generate` is **never empty** — the current rule-based choice
  (:data:`RoutePlan.RULE_BASED`) is always one of the returned variants and is
  the preferred one (``rank == 0``), so the solver's ``argmin`` can never pick a
  route worse than the rule-driven pipeline would (R3.3, Property 4).
* every returned :class:`RouteVariant` is **contract-legal**: its ``exit`` lies
  on the right (``exitX >= 1``) or bottom (``exitY >= 1``) face and its ``entry``
  on the left (``entryX <= 0``) or top (``entryY <= 0``) face — matching the
  lint face rule (v1.6.0) — so no variant can introduce an ``edge-direction``
  finding regardless of which the solver picks (R3.4, Property 5).

**Variant families** (design.md variant-families table), keyed off the edge
``kind`` from :func:`rule_engine.layout.routers.classify_edge`:

| Family        | Variants                       | Sourced from                       |
| ------------- | ------------------------------ | ---------------------------------- |
| lane side     | above-lane, below-lane         | ``decide_lane_sides`` / pass 2b    |
| back-edge     | loop-above, descend-near       | REVIEW.md experiment 2             |
| spine         | straight-drop, side-corridor   | pass 1c / ``_box_directly_below``  |
| corridor side | left-gap, right-gap            | ``_free_left_corridor_x`` / 1d     |

**Pure function.** :func:`generate` reads only ``(edge, placed, containers,
kind)`` and returns descriptors — it lays no waypoints and touches no allocator.
The actual waypoint laying happens later in the solver / routers. It is a
deterministic function of its inputs (no randomness, no wall-clock, no
dict-iteration-order dependence), so the solver built on it stays deterministic
(R4.1).

**Placement variants (1.9.0, Part A).** :func:`generate` is the per-edge
*route*-variant generator. :func:`generate_placement_variants` is its
placement-level analogue (design.md §Component A1): a pure, spec-only function
that enumerates a small, rank-ordered, deterministic set of
:class:`PlacementVariant` descriptors — the identity (rank 0, no move) plus the
three :class:`PlacementMove` moves, each guarded so it is emitted only where its
target defect can occur. The outer :func:`solver.solve_placement` loop (task 2)
applies each move, re-runs the whole ``place → size → centre → solve → repair``
inner pipeline, scores the finished candidate with the shared ``route_cost``, and
keeps the ``argmin`` — with the identity always a candidate, so the loop can
never do worse than 1.8.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Tuple

try:  # package-relative import when used as ``rule_engine.layout.variants``
    from .model import Contact, EdgeSpec, DiagramSpec, NodeSpec
    from .base import LANE_INDEX
    from .contacts import (
        select_contacts,
        _box_directly_below,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
    )
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from layout.model import Contact, EdgeSpec, DiagramSpec, NodeSpec  # type: ignore[no-redef]
    from layout.base import LANE_INDEX  # type: ignore[no-redef]
    from layout.contacts import (  # type: ignore[no-redef]
        select_contacts,
        _box_directly_below,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
    )

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..geometry import Box  # noqa: F401


class RoutePlan(str, Enum):
    """How :mod:`rule_engine.layout.routers` should lay a variant's waypoints.

    The enum members name the sanctioned route shapes the ten contact passes
    choose between implicitly today (design.md §Components → *Component 2*, the
    variant-families table). The solver (task 7.1) maps each member to the
    concrete router call that lays its waypoints; :func:`generate` only chooses
    which members are sanctioned for a given edge and in what rank order.
    """

    RULE_BASED = "rule-based"       # the current rule-driven route (always present)
    LANE_ABOVE = "lane-above"       # fan-out / long run in the band above the row
    LANE_BELOW = "lane-below"       # fan-out / long run in the band below the row
    LOOP_ABOVE = "loop-above"       # back-edge looping in an over-row corridor
    DESCEND_NEAR = "descend-near"   # back-edge descending near the source column
    STRAIGHT_DROP = "straight-drop" # spine dropping straight into a below target
    SIDE_CORRIDOR = "side-corridor" # spine via the column's side gap corridor
    LEFT_GAP = "left-gap"           # corridor in the column's left gap
    RIGHT_GAP = "right-gap"         # corridor in the column's right gap


@dataclass(frozen=True)
class RouteVariant:
    """One sanctioned ``(exit, entry, plan, rank)`` shape for an edge.

    Fields (design.md §Data Models → *RouteVariant*):

    * ``id`` — stable per edge, ``"<edge-id>/<family>"``; used in the solver's
      total tie-break key so ``argmin`` is deterministic.
    * ``exit`` — the source contact ``(exitX, exitY)``; contract-legal
      (right/bottom face) by construction.
    * ``entry`` — the target contact ``(entryX, entryY)``; contract-legal
      (left/top face) by construction.
    * ``plan`` — the :class:`RoutePlan` telling the router how to lay the
      waypoints.
    * ``rank`` — deterministic preference; lower is tried/preferred first, so the
      solver's ``argmin`` over ``(RouteCost.as_tuple(), rank, id)`` is total and
      reproducible. The rule-based variant always has ``rank == 0``.
    """

    id: str
    exit: Contact
    entry: Contact
    plan: RoutePlan
    rank: int


# ---------------------------------------------------------------------------
# Contract-legality helpers (the face rule the lint / edge-direction uses)
# ---------------------------------------------------------------------------

def _exit_is_contract_legal(exit_pt: Contact) -> bool:
    """True when ``exit_pt`` lies on the right (fx>=1) or bottom (fy>=1) face."""
    fx, fy = exit_pt
    return (fx is not None and fx >= 1.0) or (fy is not None and fy >= 1.0)


def _entry_is_contract_legal(entry_pt: Contact) -> bool:
    """True when ``entry_pt`` lies on the left (fx<=0) or top (fy<=0) face."""
    fx, fy = entry_pt
    return (fx is not None and fx <= 0.0) or (fy is not None and fy <= 0.0)


#: The canonical contract-legal contacts every family reuses. Keeping them as
#: named constants (rather than re-typing the tuples per family) makes it
#: self-evident that every variant is built from a legal exit face (right or
#: bottom centre) and a legal entry face (left or top centre).
_EXIT_RIGHT: Contact = (1.0, 0.5)     # right-centre (the default exit)
_EXIT_BOTTOM: Contact = (0.5, 1.0)    # bottom-centre (a straight-drop / spill exit)
_ENTRY_LEFT: Contact = (0.0, 0.5)     # left-centre (a horizontal arrival)
_ENTRY_TOP: Contact = (0.5, 0.0)      # top-centre (a descending arrival)


# ---------------------------------------------------------------------------
# The rule-based route: what the ten passes pick for this edge today
# ---------------------------------------------------------------------------

def _rule_based_contacts(
    edge: "EdgeSpec",
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
    kind: str,
) -> Contact:
    """Return the ``(exit, entry)`` the rule-driven pipeline picks for ``edge``.

    This mirrors :func:`rule_engine.layout.pipeline._place_and_route`'s per-kind
    contact overrides (steps 1, 1b, 1c) at the single-edge granularity the
    variant generator needs — so the :data:`RoutePlan.RULE_BASED` variant is the
    *same* contact choice today's default path makes, guaranteeing the solver can
    reproduce (and never do worse than) the current route (R3.3).

    Only the per-edge, geometry-local overrides are reproduced here; the global
    fan-out spread and band-assignment passes (2, 2b, 2b4) reshape the *band*
    along a face, never the face itself, so they cannot change contract-legality
    and are applied later by the solver's real re-route, not needed to seed the
    variant.
    """
    src = placed[edge.source]
    tgt = placed[edge.target]
    exit_pt, entry_pt = select_contacts(edge, placed)

    if kind == "spine":
        # Exception I (pass 1b/1c): a spine to a target DIRECTLY BELOW in the same
        # column with nothing between drops STRAIGHT — bottom-centre → top-centre.
        others = [b for nid, b in placed.items()
                  if nid not in (edge.source, edge.target)]
        if _box_directly_below(src, tgt, others):
            return _EXIT_BOTTOM, _ENTRY_TOP
        # Adaptive LEFT corridor: a same-column tier-skip past an intermediate
        # node whose left gap is free drops in the left gap into the target's LEFT
        # face. Left-gap availability is a geometry test; the left-gap variant
        # below is the sanctioned alternative, so the rule-based seed keeps the
        # default right-corridor + top-entry when the straight drop is blocked.
        same_column_below = abs(src.x - tgt.x) < 1e-9 and tgt.y > src.y
        if same_column_below:
            return _EXIT_BOTTOM, _ENTRY_LEFT
        return exit_pt, entry_pt

    # cross-region / back-edge / fan-out-row / straight all keep the ladder's
    # exit (right-centre) and its entry face; the router lays the class-specific
    # waypoints. select_contacts already sets a contract-legal exit/entry, so no
    # override is needed for those kinds at the seed granularity.
    return exit_pt, entry_pt


# ---------------------------------------------------------------------------
# Variant families
# ---------------------------------------------------------------------------

def _variant(edge_id: str, family: str, exit_pt: Contact, entry_pt: Contact,
             plan: RoutePlan, rank: int) -> RouteVariant:
    """Build one :class:`RouteVariant`, asserting contract-legality by
    construction (a family that ever emits an illegal face is a coding bug, not
    an input condition)."""
    assert _exit_is_contract_legal(exit_pt), (
        f"variant {edge_id}/{family}: exit {exit_pt} is not on the right/bottom face"
    )
    assert _entry_is_contract_legal(entry_pt), (
        f"variant {edge_id}/{family}: entry {entry_pt} is not on the left/top face"
    )
    return RouteVariant(
        id=f"{edge_id}/{family}",
        exit=exit_pt,
        entry=entry_pt,
        plan=plan,
        rank=rank,
    )


def _lane_side_variants(edge: "EdgeSpec", rule_exit: Contact,
                        rule_entry: Contact, start_rank: int) -> List[RouteVariant]:
    """lane-side family: run a fan-out / long horizontal in the band ABOVE or
    BELOW the source row (``decide_lane_sides`` / pass 2b).

    The lane side is a whole-row *routing* decision that does not move the
    contact faces — both the above-lane and below-lane run leave the source's
    right (or a bottom spill) and arrive on the target's left/top, so both are
    contract-legal with the rule-based contacts. The solver picks the lane that
    scores lower; the router honours it via its ``lane_above`` argument."""
    return [
        _variant(edge.id, "lane-above", rule_exit, rule_entry,
                 RoutePlan.LANE_ABOVE, start_rank),
        _variant(edge.id, "lane-below", rule_exit, rule_entry,
                 RoutePlan.LANE_BELOW, start_rank + 1),
    ]


def _back_edge_variants(edge: "EdgeSpec", rule_exit: Contact,
                        rule_entry: Contact, start_rank: int) -> List[RouteVariant]:
    """back-edge family: loop-above vs descend-near (REVIEW.md experiment 2).

    A back-edge always exits the source's RIGHT and enters the target's LEFT/TOP
    (the directional back-edge). The two sanctioned shapes differ only in the
    loop corridor: loop-above rises into an over-row corridor and runs left;
    descend-near loops in the inter-row gap just below the source when the target
    sits a row or more below. Both keep the same contract-legal contacts."""
    return [
        _variant(edge.id, "loop-above", rule_exit, rule_entry,
                 RoutePlan.LOOP_ABOVE, start_rank),
        _variant(edge.id, "descend-near", rule_exit, rule_entry,
                 RoutePlan.DESCEND_NEAR, start_rank + 1),
    ]


def _face(pt: Contact) -> str:
    x, y = pt
    if y is not None and y <= 0.0:
        return "top"
    if y is not None and y >= 1.0:
        return "bottom"
    if x is not None and x <= 0.0:
        return "left"
    return "right"


def _keep_band(rule_pt: Contact, pt: Contact) -> Contact:
    """Keep the global spread band when an alternative uses the same face.

    The global pass spreads several arrivals (or departures) on one face apart;
    an alternative shape that lands on the SAME face must not snap back to the
    face centre, or two edges meet on one contact point (1.10.3: two spines into
    the GenAI hub's top both re-centred to 0.5, ``entry-thirds``)."""
    return rule_pt if _face(rule_pt) == _face(pt) else pt


def _spine_variants(edge: "EdgeSpec", placed: Dict[str, "Box"],
                    containers: Dict[str, "Box"], rule_exit: Contact,
                    rule_entry: Contact, start_rank: int) -> List[RouteVariant]:
    """spine family: straight-drop vs side-corridor (pass 1c / ``_box_directly_below``),
    plus the corridor-side sub-family (left-gap vs right-gap, pass 1d /
    ``_free_left_corridor_x``) for the side-corridor shape.

    * **straight-drop** — bottom-centre exit → top-centre entry, a single clean
      vertical. Only sanctioned when the target sits directly below in the same
      column with nothing between; otherwise the drop would cut an icon.
    * **side-corridor** — exit right, drop in a gap corridor beside the column,
      enter the target's near face. This is always available. Its corridor may
      run in the column's **right gap** (right-centre exit → top entry) or its
      **left gap** (bottom exit → left entry) when the left gap is free.

    Every shape leaves a right/bottom face and arrives on a left/top face."""
    src = placed[edge.source]
    tgt = placed[edge.target]
    others = [b for nid, b in placed.items()
              if nid not in (edge.source, edge.target)]

    variants: List[RouteVariant] = []
    rank = start_rank

    directly_below = _box_directly_below(src, tgt, others)
    if directly_below:
        # The straight drop is a genuine sanctioned alternative only when the
        # column is clear; emit it as its own variant.
        variants.append(
            _variant(edge.id, "straight-drop", _keep_band(rule_exit, _EXIT_BOTTOM),
                     _keep_band(rule_entry, _ENTRY_TOP),
                     RoutePlan.STRAIGHT_DROP, rank)
        )
        rank += 1

    # side-corridor, right gap: the default right-corridor + top-entry spine.
    variants.append(
        _variant(edge.id, "right-gap", _keep_band(rule_exit, _EXIT_RIGHT),
                 _keep_band(rule_entry, _ENTRY_TOP),
                 RoutePlan.RIGHT_GAP, rank)
    )
    rank += 1

    # side-corridor, left gap: only when the source and target share a column and
    # the left gap is free — the reviewer's edge-4 route. Guarded so a layout with
    # no usable left gap does not offer a shape the router would have to reject.
    if _left_gap_available(src, tgt, others, containers):
        variants.append(
            _variant(edge.id, "left-gap", _keep_band(rule_exit, _EXIT_BOTTOM),
                     _keep_band(rule_entry, _ENTRY_LEFT),
                     RoutePlan.LEFT_GAP, rank)
        )
        rank += 1

    return variants


def _left_gap_available(src: "Box", tgt: "Box", others: List["Box"],
                        containers: Dict[str, "Box"]) -> bool:
    """True when the column's LEFT gap is a usable vertical corridor for a spine
    tier-skip (a pure-geometry mirror of ``routers._free_left_corridor_x``'s
    precondition, kept local so :mod:`variants` does not import the router).

    The left-gap route only makes sense for a same-column tier-skip; the router's
    own :func:`_free_left_corridor_x` performs the full obstacle-clearance test at
    lay time and falls back to the right corridor if the gap is not clear, so this
    predicate only needs to gate on the same-column, has-a-left-gap shape."""
    if abs(src.x - tgt.x) > 1e-9 or tgt.y <= src.y:
        return False
    # Find the smallest container that encloses the source; the left gap is the
    # room between its left edge and the source column.
    left_edge = 0.0
    best_w = None
    for c in (containers or {}).values():
        if c.x <= src.x and c.y <= src.y and src.right <= c.right and src.bottom <= c.bottom:
            w = c.right - c.x
            if best_w is None or w < best_w:
                best_w = w
                left_edge = c.x
    # Need at least a corridor lane plus padding (two grid steps ~= 20px). Use a
    # conservative 20px floor to match ``_free_left_corridor_x``'s ``2 * GRID``.
    return (src.x - left_edge) >= 20.0


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------

def generate(
    edge: "EdgeSpec",
    placed: Dict[str, "Box"],
    containers: Dict[str, "Box"],
    kind: str,
    global_contacts: "Dict[str, tuple] | None" = None,
) -> List[RouteVariant]:
    """Return the sanctioned :class:`RouteVariant`\\ s for ``edge`` in rank order.

    ``kind`` is the edge's classification from
    :func:`rule_engine.layout.routers.classify_edge` (``straight`` / ``spine`` /
    ``fan-out-row`` / ``cross-region`` / ``back-edge``). ``placed`` and
    ``containers`` are the placed node / container boxes (``Dict[str, Box]``), as
    the pipeline passes them. ``global_contacts`` is the optional
    ``{edge_id: (exit, entry)}`` map from the legacy ten-pass global contact
    computation (:func:`rule_engine.layout.pipeline._global_contacts`); when
    present it seeds the rule-based variant (see below).

    The returned list:

    * is **never empty** — the rule-based variant (``rank == 0``,
      :data:`RoutePlan.RULE_BASED`) is always first (R3.3);
    * is **rank-ordered** (lower rank preferred / tried first);
    * has every member **contract-legal** by construction — a right/bottom exit
      and a left/top entry — so no variant can add an ``edge-direction`` finding
      (R3.4).

    Beyond the rule-based seed, the sanctioned alternatives are added per the
    edge ``kind``:

    * ``spine`` → straight-drop / side-corridor (right-gap / left-gap);
    * ``fan-out-row`` / ``cross-region`` → lane side (above / below);
    * ``back-edge`` → loop-above / descend-near, plus lane side;
    * ``straight`` → the single centred segment only (no alternative shape).

    Pure function of ``(edge, placed, containers, kind)`` — no waypoints laid, no
    allocator touched (that is the solver's / router's job).

    **The rule-based seed is the LEGACY GLOBAL result when available.** When
    ``global_contacts`` is passed (a ``{edge_id: (exit, entry)}`` map computed
    once by :func:`rule_engine.layout.pipeline._global_contacts` — the exit/entry
    the ten global passes produce for the whole diagram *seen together*), the
    :data:`RoutePlan.RULE_BASED` variant is seeded from *those* contacts rather
    than from the per-edge :func:`_rule_based_contacts` recomputed in isolation.
    This is the fix for the Property 4 regression: on a dense landscape the global
    fan-out-spread / overflow-valve / monotone-exit-band passes (2, 1c, 1c2, 1d,
    2b4) are what hold the crossing count down, and a per-edge seed cannot see
    them, so it produced a worse rule-based route and the solver's argmin
    ("never worse than rule-based") broke. Seeding from the global result makes
    ``route_cost(RULE_BASED)`` equal the legacy per-edge geometry, restoring
    Property 4 / R3.10. When ``global_contacts`` is absent (a synthetic caller or
    a property test) the local :func:`_rule_based_contacts` seed is used, so the
    generator is still a total function of its inputs.
    """
    if global_contacts is not None and edge.id in global_contacts:
        rule_exit, rule_entry = global_contacts[edge.id]
    else:
        rule_exit, rule_entry = _rule_based_contacts(edge, placed, containers, kind)

    # The rule-based variant is ALWAYS present and preferred (rank 0), so the
    # solver's argmin can never do worse than today (R3.3, Property 4).
    variants: List[RouteVariant] = [
        _variant(edge.id, "rule-based", rule_exit, rule_entry,
                 RoutePlan.RULE_BASED, 0)
    ]

    rank = 1
    if kind == "spine":
        spine = _spine_variants(edge, placed, containers, rule_exit, rule_entry, rank)
        variants.extend(spine)
        rank += len(spine)
    elif kind in ("fan-out-row", "cross-region"):
        lane = _lane_side_variants(edge, rule_exit, rule_entry, rank)
        variants.extend(lane)
        rank += len(lane)
    elif kind == "back-edge":
        back = _back_edge_variants(edge, rule_exit, rule_entry, rank)
        variants.extend(back)
        rank += len(back)
        lane = _lane_side_variants(edge, rule_exit, rule_entry, rank)
        variants.extend(lane)
        rank += len(lane)
    # kind == "straight": a directly-opposite adjacent target is a single centred
    # segment; there is no sanctioned alternative shape, so the rule-based variant
    # is the only one. The list is still non-empty.

    return _dedupe_by_id(variants)


def _dedupe_by_id(variants: List[RouteVariant]) -> List[RouteVariant]:
    """Drop any later variant that duplicates an earlier variant's ``id``,
    preserving rank order.

    A family can, for a particular geometry, propose a shape whose ``(exit,
    entry, plan)`` coincides with an already-emitted one; keeping ids unique
    keeps the solver's tie-break key total. The rule-based variant (id
    ``<edge>/rule-based``) is always retained because it is emitted first."""
    seen: set = set()
    out: List[RouteVariant] = []
    for v in variants:
        if v.id in seen:
            continue
        seen.add(v.id)
        out.append(v)
    return out


# ===========================================================================
# Placement variants (1.9.0, Part A — design.md §Component A1)
# ===========================================================================
#
# The three sanctioned placement moves, each keyed off a recorded placement
# defect (design.md §Architecture → "Sanctioned placement moves"):
#
#   * widen-gap      — grow a Network Boundary's (vpc) side gap by whole COL_STEP
#                      multiples so a tier-skip corridor clears an icon column
#                      (the *tier-skip rail*).
#   * shift-neighbour — move one hub neighbour one column so the hub's free
#                      approach column no longer lies inside its own fan-out (the
#                      *GCP/OCI hub*).
#   * reorder-tier   — swap two peers within a row so two opposed long runs
#                      leaving the top row no longer overlap in extent (the
#                      *edge-tier band*).
#
# generate_placement_variants(spec) is a PURE function of the spec: it reads only
# the coordinate-free declaration (nodes' lane/region/slot/container, edges'
# source/target, containers' kind/region/parent) — no allocator, no placement
# geometry, no randomness, no wall-clock, no dict-iteration-order dependence
# (Decision D4, R1.6). It emits DESCRIPTORS; the solver (task 2) applies each
# move and re-runs place → size → centre so the moved layout stays grid-aligned
# and lint-clean by construction. A move that would break container nesting or
# padding is NOT enumerated (R1.6): every move keeps a node inside its declared
# container, and a swap only pairs peers of the same container membership.


class PlacementMove(str, Enum):
    """The three sanctioned placement moves, plus the identity (design.md
    §Component A1). ``IDENTITY`` is the base placement (no move) and is always
    the rank-0 variant, so the placement loop's ``argmin`` can never do worse
    than 1.8.0."""

    IDENTITY = "identity"           # the base placement — no move (rank 0)
    WIDEN_GAP = "widen-gap"         # grow a vpc side gap (tier-skip rail)
    SHIFT_NEIGHBOUR = "shift-neighbour"  # move one hub neighbour one column
    REORDER_TIER = "reorder-tier"   # swap two peers within a row


@dataclass(frozen=True)
class PlacementVariant:
    """One sanctioned placement — a single node/tier move applied to the base
    placement (design.md §Data Models → *PlacementVariant*).

    Fields:

    * ``id`` — stable ``"<spec>/<move>/<target>"`` (``"<spec>/identity"`` for the
      base). Used, with ``rank``, in the solver's total argmin tie-break so the
      selected placement is a deterministic function of the spec.
    * ``move`` — the :class:`PlacementMove` this variant applies
      (``IDENTITY`` for the base).
    * ``rank`` — deterministic preference; ``0`` is always the identity, then the
      moves in a fixed family / target order. Lower is tried/preferred first.
    * ``params`` — a frozen tuple of ``(key, value)`` pairs the solver reads to
      **apply** the move (which container to widen, which neighbour to shift,
      which peers to swap, and by how much). Empty for the identity. Kept as a
      sorted tuple (not a dict) so the descriptor is hashable and its repr is
      order-stable — a byte-identity aid for determinism (Decision D4).
    """

    id: str
    move: PlacementMove
    rank: int
    params: Tuple[Tuple[str, object], ...] = field(default=())

    def param(self, key: str, default: object = None) -> object:
        """Read one applied-move parameter by ``key`` (``default`` if absent)."""
        for k, v in self.params:
            if k == key:
                return v
        return default


def _params(**kwargs: object) -> Tuple[Tuple[str, object], ...]:
    """Freeze move parameters into a sorted, hashable ``(key, value)`` tuple.

    Sorted by key so two calls with the same parameters produce the identical
    tuple regardless of keyword order — the descriptor is then a pure function of
    its inputs (Decision D4)."""
    return tuple(sorted(kwargs.items(), key=lambda kv: kv[0]))


# ---------------------------------------------------------------------------
# Spec-only structural helpers (no geometry — a pure read of the declaration)
# ---------------------------------------------------------------------------

def _nodes_by_id(spec: "DiagramSpec") -> Dict[str, "NodeSpec"]:
    return {n.id: n for n in spec.nodes}


def _lane_i(node: "NodeSpec") -> int:
    """The node's lane ordinal (its primary-axis tier index). Unknown lanes are
    validated away by :func:`_validate_spec` before layout, but this generator is
    a pure read that may run on a raw spec, so an unknown lane sorts last rather
    than raising."""
    return LANE_INDEX.get(node.lane, len(LANE_INDEX))


def _same_container(a: "NodeSpec", b: "NodeSpec") -> bool:
    """True when two nodes share the same declared container membership (both in
    the same ``az`` / ``vpc``, or both container-free). A move that reorders or
    shifts across a container boundary would change which box owns a node — which
    can break nesting / padding — so such a move is never enumerated (R1.6)."""
    return a.container == b.container and a.region == b.region


def _region_of_container(spec: "DiagramSpec") -> Dict[str, str]:
    return {c.id: c.region for c in spec.containers}


def _tier_skip_edges(spec: "DiagramSpec") -> List["EdgeSpec"]:
    """Edges that skip a tier **within one region**: source and target in the
    same region, at least two lanes apart, with an intermediate node occupying a
    lane strictly between them in that region.

    This is the spec-only signature of the *tier-skip rail* defect (a corridor
    that must pass an intervening icon column). It is pure structure — lane
    ordinals and region membership — never geometry."""
    nodes = _nodes_by_id(spec)
    out: List["EdgeSpec"] = []
    for edge in spec.edges:
        src = nodes.get(edge.source)
        tgt = nodes.get(edge.target)
        if src is None or tgt is None:
            continue
        if src.region != tgt.region:
            continue
        lo, hi = sorted((_lane_i(src), _lane_i(tgt)))
        if hi - lo < 2:
            continue
        # An intermediate node sits in a lane strictly between them, same region.
        if any(
            n.region == src.region and lo < _lane_i(n) < hi
            for n in spec.nodes
            if n.id not in (src.id, tgt.id)
        ):
            out.append(edge)
    return out


def _hub_neighbours(spec: "DiagramSpec") -> List[Tuple["NodeSpec", "NodeSpec"]]:
    """``(hub, neighbour)`` pairs where a fan-out hub has a same-region neighbour
    one slot away in the same lane.

    A *hub* is a ``platform``-lane node with a fan-out (≥ 2 outgoing edges); the
    defect is that the hub's free approach column lies inside its own fan-out, so
    shifting a neighbour one column opens the approach. The neighbour must share
    the hub's container (so shifting it one slot cannot spill it out of its box —
    R1.6)."""
    nodes = _nodes_by_id(spec)
    out_degree: Dict[str, int] = {}
    for edge in spec.edges:
        if edge.source in nodes:
            out_degree[edge.source] = out_degree.get(edge.source, 0) + 1

    pairs: List[Tuple["NodeSpec", "NodeSpec"]] = []
    for hub in spec.nodes:
        if hub.lane != "platform" or out_degree.get(hub.id, 0) < 2:
            continue
        for other in spec.nodes:
            if other.id == hub.id:
                continue
            if other.lane != hub.lane or other.region != hub.region:
                continue
            if abs(other.slot - hub.slot) != 1:
                continue
            if not _same_container(hub, other):
                continue
            pairs.append((hub, other))
    return pairs


def _top_tier_peers(spec: "DiagramSpec") -> List[Tuple["NodeSpec", "NodeSpec"]]:
    """Adjacent ``(a, b)`` peer pairs in the region's **top occupied tier** that
    each source a *long run* (an edge to a different region, or a tier-skip),
    where swapping the pair could separate two opposed long runs leaving the row.

    The pair must share a container and lane (a genuine row swap that cannot break
    nesting), sit one slot apart, and both be long-run sources — otherwise a swap
    changes nothing about the overlapping-extent defect it targets."""
    nodes = _nodes_by_id(spec)

    # Which nodes source a long run (cross-region edge, or a tier-skip)?
    tier_skip_sources = {e.source for e in _tier_skip_edges(spec)}
    long_run_source: set = set(tier_skip_sources)
    for edge in spec.edges:
        src = nodes.get(edge.source)
        tgt = nodes.get(edge.target)
        if src is not None and tgt is not None and src.region != tgt.region:
            long_run_source.add(edge.source)

    # The top occupied tier per region = the minimum lane ordinal present.
    top_lane_i: Dict[str, int] = {}
    for n in spec.nodes:
        li = _lane_i(n)
        if n.region not in top_lane_i or li < top_lane_i[n.region]:
            top_lane_i[n.region] = li

    pairs: List[Tuple["NodeSpec", "NodeSpec"]] = []
    for a in spec.nodes:
        if _lane_i(a) != top_lane_i.get(a.region):
            continue
        if a.id not in long_run_source:
            continue
        for b in spec.nodes:
            if b.id == a.id or _lane_i(b) != _lane_i(a) or b.region != a.region:
                continue
            if b.id not in long_run_source:
                continue
            if b.slot - a.slot != 1:  # adjacent, a left of b (ordered → no dup)
                continue
            if not _same_container(a, b):
                continue
            pairs.append((a, b))
    return pairs


# ---------------------------------------------------------------------------
# The placement-variant generator (Component A1)
# ---------------------------------------------------------------------------

def generate_placement_variants(spec: "DiagramSpec") -> List[PlacementVariant]:
    """Return the sanctioned :class:`PlacementVariant`\\ s for ``spec`` in rank
    order (design.md §Component A1, R1.1 / R1.2 / R1.6).

    The returned list:

    * **always begins with the identity** (``rank == 0``,
      :attr:`PlacementMove.IDENTITY`, no move) — the Base_Placement is always a
      candidate, so the placement loop's ``argmin`` can never do worse than 1.8.0
      (R1.1, the Part A analogue of Property 1);
    * enumerates **only the three sanctioned moves**, each **guarded** so it is
      emitted only where its target defect can occur (R1.2) — widen-gap only
      where a within-region tier-skip crosses an intervening column, shift-
      neighbour only for a fan-out hub with an adjacent same-container neighbour,
      reorder-tier only for two long-run peers in the region's top tier;
    * enumerates **no move that would break container nesting or padding** (R1.6):
      every move keeps a node inside its declared container, and a swap only
      pairs peers of the same container membership;
    * is **rank-ordered** and fully **deterministic** — a pure function of the
      spec with no randomness, wall-clock, or dict-iteration-order dependence
      (Decision D4): every guard iterates ``spec.nodes`` / ``spec.edges`` in
      declared order, and the emitted moves are sorted on a spec-only key before
      rank assignment.

    This is the placement-level analogue of :func:`generate`: it lays no
    coordinates and moves no node — it emits descriptors the solver
    (:func:`rule_engine.layout.solver.solve_placement`, task 2) applies by
    re-running ``place → size → centre`` with the move's parameters, so the moved
    layout stays grid-aligned and lint-clean by construction.
    """
    prefix = spec.diagram_id

    # The identity is ALWAYS rank 0 (R1.1). Its params are empty — the solver
    # runs the base placement unchanged for it.
    variants: List[PlacementVariant] = [
        PlacementVariant(id=f"{prefix}/identity", move=PlacementMove.IDENTITY, rank=0)
    ]

    # Collect each move family's descriptors as (sort_key, move, target, params)
    # so the whole set can be ordered by one spec-only key before ranking — the
    # family order (widen-gap, shift-neighbour, reorder-tier) is the primary key
    # so ranks are stable and grouped, then the target id breaks ties.
    pending: List[Tuple[Tuple[int, str], PlacementMove, str, Tuple[Tuple[str, object], ...]]] = []

    region_of = _region_of_container(spec)

    # --- widen-gap: one per vpc that owns / borders a within-region tier-skip ---
    # The corridor for a within-region tier-skip runs in the region's vpc side
    # gap; widening that gap by whole COL_STEP multiples clears the intervening
    # column. Emit one variant per vpc whose region has a tier-skip. Growing a
    # side gap only enlarges the container, so it can never break nesting/padding.
    tier_skip_regions = {
        _nodes_by_id(spec)[e.source].region for e in _tier_skip_edges(spec)
    }
    for c in spec.containers:
        if c.kind != "vpc" or c.region not in tier_skip_regions:
            continue
        pending.append((
            (0, c.id),
            PlacementMove.WIDEN_GAP,
            c.id,
            _params(container=c.id, columns=1),
        ))

    # --- shift-neighbour: one per (hub, neighbour) fan-out pair ---
    # Shift the neighbour one column AWAY from the hub (to the side that opens the
    # hub's approach). The neighbour shares the hub's container, so a one-slot
    # shift keeps it inside its box (re-placed and re-sized by the solver).
    for hub, neighbour in _hub_neighbours(spec):
        direction = 1 if neighbour.slot >= hub.slot else -1
        pending.append((
            (1, neighbour.id),
            PlacementMove.SHIFT_NEIGHBOUR,
            neighbour.id,
            _params(node=neighbour.id, hub=hub.id, columns=direction),
        ))

    # --- reorder-tier: one per adjacent long-run peer pair in the top tier ---
    # Swap the two peers' slots. Both share a container and lane, so the swap is a
    # pure within-row reorder that cannot change container membership.
    for a, b in _top_tier_peers(spec):
        target = f"{a.id}~{b.id}"
        pending.append((
            (2, target),
            PlacementMove.REORDER_TIER,
            target,
            _params(node_a=a.id, node_b=b.id),
        ))

    # Order by the spec-only key and assign consecutive ranks from 1 (the
    # identity holds rank 0). Sorting on the (family, target) key makes the rank
    # a deterministic function of the spec regardless of the order the guards ran.
    pending.sort(key=lambda item: item[0])
    for rank, (_key, move, target, params) in enumerate(pending, start=1):
        variants.append(
            PlacementVariant(
                id=f"{prefix}/{move.value}/{target}",
                move=move,
                rank=rank,
                params=params,
            )
        )

    return variants


# ---------------------------------------------------------------------------
# Applying a placement move (1.9.0, Part A — the solver's move-applier)
# ---------------------------------------------------------------------------
#
# A PlacementVariant is a coordinate-free DESCRIPTOR; the solver applies it by
# transforming the spec's node ``slot``s (never geometry) and re-running the pure
# ``place → size → centre`` pipeline. Because every move is expressed as a
# whole-slot translation of a node / tier within its own declared container, the
# re-placed layout stays grid-aligned and inside its container by construction —
# so a move can never break nesting or padding (R1.6), which is also why the
# generator only enumerates moves that keep a node in its box.
#
# The applier is a PURE function of ``(spec, variant)``: it reads only the
# coordinate-free declaration, rebuilds the frozen ``NodeSpec`` tuple in the
# spec's declared order, and returns a new frozen ``DiagramSpec``. No randomness,
# no wall-clock, no dict-iteration-order dependence (Decision D4), so the moved
# spec — and therefore the finished candidate the solver scores — is a
# deterministic function of the base spec and the variant.


def _replace_node(node: "NodeSpec", *, slot: int) -> "NodeSpec":
    """Return a copy of ``node`` with a new ``slot`` (every other field kept).

    A :class:`NodeSpec` is frozen, so a move rebuilds it rather than mutating it;
    keeping the rebuild in one helper makes it self-evident that a move touches
    **only** the slot (the secondary-axis position), never the lane, region, or
    container membership — which is what guarantees the node stays inside its
    declared box (R1.6)."""
    return NodeSpec(
        id=node.id,
        role=node.role,
        lane=node.lane,
        region=node.region,
        slot=slot,
        sub=node.sub,
        container=node.container,
        overlay=node.overlay,
    )


def _rebuild_spec(spec: "DiagramSpec", new_slots: Dict[str, int]) -> "DiagramSpec":
    """Return a copy of ``spec`` with the ``slot`` of every node in ``new_slots``
    replaced, preserving the declared node order (Decision D4).

    Nodes absent from ``new_slots`` are carried through unchanged. Only the
    ``nodes`` tuple is rebuilt — edges, containers, and every diagram-level field
    are shared by reference, since a placement move changes only where nodes sit
    on the secondary axis, never the topology or the container tree."""
    nodes = tuple(
        _replace_node(n, slot=new_slots[n.id]) if n.id in new_slots else n
        for n in spec.nodes
    )
    return DiagramSpec(
        diagram_id=spec.diagram_id,
        diagram_name=spec.diagram_name,
        axis=spec.axis,
        nodes=nodes,
        edges=spec.edges,
        containers=spec.containers,
        flow_lines=spec.flow_lines,
        title=spec.title,
        compact=spec.compact,
    )


def apply_placement_move(spec: "DiagramSpec", variant: "PlacementVariant") -> "DiagramSpec":
    """Apply ``variant``'s move to ``spec`` and return the moved spec (R1.3).

    The identity (rank 0) returns ``spec`` unchanged — the Base_Placement is run
    exactly as the 1.8.0 pipeline runs it, so the placement loop's ``argmin`` can
    never do worse than the base (R1.4). The three sanctioned moves are expressed
    as whole-slot translations of a node / tier within its own container:

    * **widen-gap** — open a side gap in the tier-skip region's VPC by shifting
      **every node in that region** one slot along the secondary axis
      (``columns`` slots). This grows the enclosing VPC and creates the clear
      side corridor the tier-skip rail needs, and — because it shifts the whole
      region block together — it never changes which container owns a node
      (R1.6).
    * **shift-neighbour** — move the hub's neighbour ``columns`` slot(s) away from
      the hub, opening the hub's free approach column. A collision with the slot
      the neighbour lands on is resolved by cascading every node at or beyond that
      slot (in the same lane+region) one further slot, so slots stay unique
      (:func:`_validate_spec`) and the shift stays within the container.
    * **reorder-tier** — swap the ``slot`` of the two named peers, a pure
      within-row reorder that leaves every container membership intact.

    Pure and deterministic (Decision D4): it reads only the coordinate-free
    declaration and rebuilds the frozen node tuple in declared order, so
    ``apply_placement_move`` run twice on the same inputs yields an identical
    spec. It moves no coordinate — the solver re-runs ``place → size → centre``
    on the returned spec to derive the moved geometry.
    """
    if variant.move is PlacementMove.IDENTITY:
        return spec

    nodes = _nodes_by_id(spec)

    if variant.move is PlacementMove.WIDEN_GAP:
        container_id = variant.param("container")
        columns = int(variant.param("columns", 1))
        region = next(
            (c.region for c in spec.containers if c.id == container_id), None
        )
        if region is None:
            return spec  # unknown container — no-op (guarded away by the generator)
        new_slots = {
            n.id: n.slot + columns for n in spec.nodes if n.region == region
        }
        return _rebuild_spec(spec, new_slots)

    if variant.move is PlacementMove.SHIFT_NEIGHBOUR:
        node_id = variant.param("node")
        columns = int(variant.param("columns", 1))
        node = nodes.get(node_id)
        if node is None or columns == 0:
            return spec
        target_slot = node.slot + columns
        # Cascade any node that would collide with target_slot in the same
        # lane+region, so slots stay unique. Nodes are pushed in the shift
        # direction (away from the hub), preserving their relative order.
        peers = [
            n for n in spec.nodes
            if n.lane == node.lane and n.region == node.region and n.id != node.id
        ]
        new_slots: Dict[str, int] = {node_id: target_slot}
        if columns > 0:
            for peer in sorted(peers, key=lambda p: p.slot):
                if peer.slot >= target_slot and peer.slot < target_slot + columns:
                    new_slots[peer.id] = peer.slot - columns
        else:
            for peer in sorted(peers, key=lambda p: -p.slot):
                if peer.slot <= target_slot and peer.slot > target_slot + columns:
                    new_slots[peer.id] = peer.slot - columns
        # Simplest total resolution: if the target slot is occupied, swap with the
        # occupant so both slots stay unique and inside the row.
        occupant = next((n for n in peers if n.slot == target_slot), None)
        if occupant is not None:
            new_slots = {node_id: target_slot, occupant.id: node.slot}
        return _rebuild_spec(spec, new_slots)

    if variant.move is PlacementMove.REORDER_TIER:
        a_id = variant.param("node_a")
        b_id = variant.param("node_b")
        a = nodes.get(a_id)
        b = nodes.get(b_id)
        if a is None or b is None:
            return spec
        return _rebuild_spec(spec, {a_id: b.slot, b_id: a.slot})

    return spec  # pragma: no cover - exhaustive over PlacementMove
