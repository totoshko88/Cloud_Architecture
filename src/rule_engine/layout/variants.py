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

**Placement seam (R5.4).** :func:`generate` is the per-edge *route*-variant
generator. Its boundary is deliberately shaped so a future
``generate_placement_variants()`` can be an **outer loop** over the same
score-and-commit machinery — placement variants would each fix a node/tier
position and then call this generator per edge. That outer generator is a
non-goal for 1.8.0 and is **not** implemented here; only the clean seam is left
in (see :func:`_placement_seam_note`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Dict, List

try:  # package-relative import when used as ``rule_engine.layout.variants``
    from .model import Contact, EdgeSpec
    from .contacts import (
        select_contacts,
        _box_directly_below,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
    )
except ImportError:  # pragma: no cover - fallback for flat-module execution
    from layout.model import Contact, EdgeSpec  # type: ignore[no-redef]
    from layout.contacts import (  # type: ignore[no-redef]
        select_contacts,
        _box_directly_below,
        _UPPER_QUARTER,
        _LOWER_QUARTER,
    )

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..geometry import Box  # noqa: F401
    from .model import DiagramSpec  # noqa: F401


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
            _variant(edge.id, "straight-drop", _EXIT_BOTTOM, _ENTRY_TOP,
                     RoutePlan.STRAIGHT_DROP, rank)
        )
        rank += 1

    # side-corridor, right gap: the default right-corridor + top-entry spine.
    variants.append(
        _variant(edge.id, "right-gap", _EXIT_RIGHT, _ENTRY_TOP,
                 RoutePlan.RIGHT_GAP, rank)
    )
    rank += 1

    # side-corridor, left gap: only when the source and target share a column and
    # the left gap is free — the reviewer's edge-4 route. Guarded so a layout with
    # no usable left gap does not offer a shape the router would have to reject.
    if _left_gap_available(src, tgt, others, containers):
        variants.append(
            _variant(edge.id, "left-gap", _EXIT_BOTTOM, _ENTRY_LEFT,
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


# ---------------------------------------------------------------------------
# Placement seam (R5.4) — documented, NOT implemented
# ---------------------------------------------------------------------------

def _placement_seam_note() -> None:  # pragma: no cover - documentation only
    """Placement-variant scoring is a non-goal for 1.8.0 (R5.4, Decision D2).

    :func:`generate` is the per-edge **route**-variant generator. A future
    release can add placement scoring as an **outer loop** over the *same*
    score-and-commit machinery, without re-architecting this module:

    * a ``generate_placement_variants(spec, placed, containers)`` would enumerate
      candidate node/tier positions (each a re-``place_nodes`` with one node or
      tier moved) as its own ranked, deterministic variant list;
    * the solver would, for each placement variant, run the existing per-edge
      route loop (this :func:`generate` + score + commit) and score the whole
      resulting diagram;
    * it would ``argmin`` over placements exactly as it ``argmin``s over routes.

    The two recorded placement defects (``gcp/01`` = ``(4, 0)``, the landscapes =
    ``(3, 2)``) are therefore **held, not fixed** in 1.8.0: no code here moves a
    node or a tier. Only this route-variant seam is in place; the placement outer
    loop is intentionally absent.
    """
