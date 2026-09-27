# Feature: placement-and-gates, Property 1: placement argmin never worse than the base
"""Property tests for the scored PLACEMENT loop (placement-and-gates 1.9.0, Part A).

This module collects the Part A placement-loop property tests. Each property maps
one-to-one onto a ``design.md`` → *Correctness Properties* entry (Properties 1–3)
and is written in its own clearly delimited section so the sibling tasks that
share this file can append their sections without touching the ones already here:

* **Property 1** (task 2.1, *this section*) — the placement argmin never scores
  worse than the base: ``route_cost(solve_placement(spec)) <=
  route_cost(base placement)`` for every generated layout and for the shipped
  spec-level corpus. The Base_Placement (the identity, rank 0) is *always* one of
  the enumerated placement variants, so the ``argmin`` over
  ``(RouteCost.as_tuple(), placement_rank, placement_id)`` can never do worse
  than the base — the Part A analogue of the 1.8.0 route-level Property 4
  (R1.4).
* **Property 2** (task 2.2, *this module's second section*) — placement
  determinism: ``solve_placement(spec)`` twice yields a byte-identical
  ``.drawio``, for the generated ``_small_valid_spec()`` family and the shipped
  spec-level corpus. Serialised through the engine's own
  ``repair._serialize_candidate`` (the adapter over ``diagram_layout.build_diagram``)
  exactly as Property 1 scores through it.
* **Property 3** (task 3.1) — held defects improve or hold. *(appended by a later
  task)*

Conventions (established by honest-gates, followed by scored-router): the
Hypothesis profile lives in ``tests/conftest.py`` (loaded automatically,
``max_examples=100``), so every ``@given`` here runs at least 100 examples
without a per-test override. The shared graded ``geometry.route_cost`` is the
objective the placement loop optimises AND the gate enforces (design Decision D3
/ R5.6 — no private copy), so scoring a finished diagram here scores it exactly
as :func:`rule_engine.layout.solver.solve_placement` does.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given

from rule_engine.layout.pipeline import LayoutError, layout
from rule_engine.layout.solver import _placement_cost, solve_placement
from rule_engine.layout.contacts import OverConnectedError

# Reuse the established small-valid-spec generator (the same family the layout
# geometry property test and the scored-router Properties 3–5 drive) so
# Property 1 is exercised over the same nested ``account ⊃ vpc ⊃ az`` shape the
# placement moves are guarded against — two mirror regions, a small number of
# worker / data slots, and edges classifying into the five supported kinds.
from tests.test_layout_engine_property import _small_valid_spec

# The two shipped HA diagrams that exist as coordinate-free ``DiagramSpec`` values
# (``ha_multiregion_spec``): the ``flow`` summary and the ``landscape`` as-built.
# These are the spec-level slice of the shipped corpus — the only Shipped_Diagrams
# reconstructable as a spec ``solve_placement`` can consume (the rest of the corpus
# ships only as committed ``.drawio`` and has no public spec to re-solve) — so the
# task's "plus the shipped corpus" clause runs Property 1 over them directly.
from rule_engine.ha_multiregion_spec import LANDSCAPE_SPEC, SUMMARY_SPEC


# =========================================================================== #
# Property 1 — placement argmin never worse than the base
# =========================================================================== #
#
# Validates: Requirements 1.4.
#
# design.md, Property 1: "For every spec,
# route_cost(solve_placement(spec)) <= route_cost(base placement) — the base is
# always a candidate (the Part A analogue of 1.8.0 Property 4)."
#
# The guarantee rests on one structural fact: ``generate_placement_variants``
# always emits the identity (no move) as rank 0, ``apply_placement_move`` on the
# identity returns the spec unchanged, and ``solve_placement`` selects the argmin
# over the TOTAL key ``(RouteCost.as_tuple(), placement_rank, placement_id)`` —
# with the base at rank 0, an equal-cost move can only win if it sorts before the
# base, which it cannot. So the base placement is always in the candidate set and
# the winner's route_cost is by construction <= the base's.
#
# The base placement is the SAME finished diagram ``solve_placement`` would score
# for the identity variant: ``layout(spec, legacy=False)`` runs the identical
# ``place → size → centre → scored solve → repair`` inner pipeline the loop runs
# per variant. Both the winner and the base are then scored with the shared
# ``_placement_cost`` (→ ``geometry.route_cost``), so the comparison is
# like-with-like on the exact objective the argmin uses (Decision D3).
#
# The test would FAIL if the loop ever dropped the base from its candidate set,
# scored a move with a different objective than the base, or selected a non-argmin
# winner — the three ways Property 1 could break.


def _base_cost(spec):
    """Score the BASE placement — the identity variant's finished diagram.

    ``layout(spec, legacy=False)`` runs the exact ``place → size → centre →
    scored solve → repair`` inner pipeline ``solve_placement`` runs for the
    rank-0 identity variant (``apply_placement_move`` on the identity is a no-op),
    so this is the same finished candidate the loop scores as the base. Scored
    through the shared :func:`_placement_cost` so the base and the winner are
    measured with the one objective the argmin keys on (Decision D3 / R5.6)."""
    return _placement_cost(layout(spec, legacy=False))


def _assert_placement_not_worse_than_base(spec) -> None:
    """The winning placement's route_cost never exceeds the base's (Property 1).

    Both the winner (:func:`solve_placement`) and the base (:func:`_base_cost`)
    are finished diagrams scored with the shared graded ``route_cost``. Compared
    on ``RouteCost.as_tuple()`` — the exact ordering key the argmin minimises — so
    the assertion is the invariant Property 1 states, on the objective the loop
    optimises. A spec the 1.8.0 path cannot lay out is excluded (the invariant is
    conditional on a base placement existing), never counted as a counterexample.
    """
    try:
        base = _base_cost(spec)
    except (LayoutError, OverConnectedError):
        # No base placement exists (the engine refuses this spec, fail-honest);
        # Property 1 is conditional on the base laying out, so this is not a
        # counterexample.
        assume(False)
        return

    winner = _placement_cost(solve_placement(spec))

    assert winner.as_tuple() <= base.as_tuple(), (
        f"placement argmin scored WORSE than the base placement: "
        f"winner={winner.as_tuple()} > base={base.as_tuple()} "
        f"(spec {spec.diagram_id!r}) — the base is always a rank-0 candidate, so "
        f"the argmin can never do worse (Property 1, R1.4)"
    )


# Feature: placement-and-gates, Property 1: placement argmin never worse than the base
@given(spec=_small_valid_spec())
def test_placement_argmin_never_worse_than_base(spec) -> None:
    """``route_cost(solve_placement(spec)) <= route_cost(base)`` for every
    generated layout (R1.4, Property 1).

    Over the same family of small, valid, layout-able specs the layout-geometry
    and scored-router properties use, the winning placement's ``route_cost`` never
    exceeds the base placement's. Because the Base_Placement (the identity, rank
    0) is always one of the enumerated variants and the argmin keys on
    ``(RouteCost.as_tuple(), placement_rank, placement_id)``, an equal-cost move
    can only win by sorting before the base — which the rank-0 base forbids — so
    the selected placement is never worse than the base."""
    _assert_placement_not_worse_than_base(spec)


# Feature: placement-and-gates, Property 1: placement argmin never worse than the base
@pytest.mark.parametrize(
    "spec",
    [SUMMARY_SPEC, LANDSCAPE_SPEC],
    ids=["ha-summary", "ha-landscape"],
)
def test_placement_argmin_never_worse_than_base_on_corpus(spec) -> None:
    """Property 1 holds on the shipped spec-level corpus (R1.4).

    The two shipped HA diagrams reconstructable as coordinate-free ``DiagramSpec``
    values — the ``flow`` summary and the ``landscape`` as-built — are exactly the
    Shipped_Diagrams a placement move is meant to relieve (the recorded landscape
    ``(3, 2)`` defect, docs/REVIEW.md). Running Property 1 over them directly pins
    that the loop never regresses a shipped diagram below its base placement: the
    winner's ``route_cost`` is at or below the base's on every real corpus spec,
    not only on the generated family."""
    _assert_placement_not_worse_than_base(spec)


# The engine's own candidate serializer — the adapter over
# ``diagram_layout.build_diagram`` with stub icons — is the exact byte-producing
# path Property 1 scores through (``_placement_cost`` → ``_serialize_candidate`` →
# parse → ``route_cost``) and the ratchet publishes through. Serialising Property
# 2's two runs with the *same* serializer means the byte comparison is over
# exactly the ``.drawio`` the loop would emit, independent of any provider skin.
from rule_engine.layout.repair import _serialize_candidate


# =========================================================================== #
# Property 2 — placement determinism (byte-identical .drawio across two runs)
# =========================================================================== #
#
# Validates: Requirements 1.5, 5.1.
#
# design.md, Property 2: "Placement determinism. solve_placement(spec) run twice
# yields a byte-identical .drawio."
#
# The guarantee rests on the loop being a PURE, deterministic function of the
# spec (Decision D4 / R5.1): ``generate_placement_variants`` is pure, each
# ``apply_placement_move`` is a pure spec transform, ``layout`` is a deterministic
# function of its spec, and the argmin key
# ``(RouteCost.as_tuple(), placement_rank, placement_id)`` is TOTAL — the rank
# then the id break every ``route_cost`` tie — so the same spec always selects the
# same winning placement. Serialising that winner through the engine's own
# ``_serialize_candidate`` (the adapter over ``diagram_layout.build_diagram``,
# the same path Property 1 scores through) therefore produces byte-identical text
# run-to-run.
#
# The test would FAIL if the loop ever leaked non-spec state into its result — a
# dict-iteration-order-dependent placement choice, a wall-clock or random tie
# break, or a serializer that emitted an unstable ordering — which is exactly the
# determinism contract R1.5 / R5.1 forbids and ``generator --check`` relies on.


def _assert_placement_deterministic(spec) -> None:
    """``solve_placement(spec)`` serialises byte-identically across two runs (Property 2).

    Runs the whole placement loop twice and serialises each winner through the
    engine's own :func:`_serialize_candidate` — the adapter over
    ``diagram_layout.build_diagram`` Property 1 scores through and the ratchet
    publishes through — then asserts the two ``.drawio`` strings are equal byte
    for byte. A spec the engine refuses (no base placement lays out) is excluded
    with :func:`hypothesis.assume`, exactly as Property 1 does: determinism is
    only meaningful for a spec that produces a diagram at all, so a refused spec
    is not a counterexample."""
    try:
        first = _serialize_candidate(solve_placement(spec))
    except (LayoutError, OverConnectedError):
        # The engine refuses this spec (fail-honest); Property 2 is conditional on
        # a placement existing, so this is not a counterexample.
        assume(False)
        return

    # The spec laid out once, so it must lay out again identically — a second
    # failure here would itself be a determinism defect, so it is NOT swallowed.
    second = _serialize_candidate(solve_placement(spec))

    assert first == second, (
        f"solve_placement was NOT deterministic: two runs serialised to "
        f"different .drawio bytes (spec {spec.diagram_id!r}) — the placement loop "
        f"must be a pure function of the spec so every Shipped_Diagram stays "
        f"byte-identical run-to-run (Property 2, R1.5 / R5.1)"
    )


# Feature: placement-and-gates, Property 2: placement determinism
@given(spec=_small_valid_spec())
def test_placement_deterministic(spec) -> None:
    """``solve_placement(spec)`` twice → byte-identical ``.drawio`` for every
    generated layout (R1.5, R5.1, Property 2).

    Over the same family of small, valid, layout-able specs Property 1 uses, two
    independent runs of the placement loop serialise to identical ``.drawio``
    bytes. Because ``generate_placement_variants`` / ``apply_placement_move`` /
    ``layout`` are pure deterministic functions of the spec and the argmin key is
    total (rank then id break every ``route_cost`` tie), the same spec always
    selects the same winning placement and the engine's serializer emits it
    identically — no dict-order, wall-clock, or random dependence leaks in."""
    _assert_placement_deterministic(spec)


# Feature: placement-and-gates, Property 2: placement determinism
@pytest.mark.parametrize(
    "spec",
    [SUMMARY_SPEC, LANDSCAPE_SPEC],
    ids=["ha-summary", "ha-landscape"],
)
def test_placement_deterministic_on_corpus(spec) -> None:
    """Property 2 holds on the shipped spec-level corpus (R1.5, R5.1).

    The two shipped HA diagrams reconstructable as coordinate-free ``DiagramSpec``
    values — the ``flow`` summary and the ``landscape`` as-built — serialise to
    byte-identical ``.drawio`` across two placement-loop runs. This pins the
    determinism contract on the real corpus specs the loop is meant to publish,
    not only on the generated family: the exact guarantee ``generator --check``
    depends on to keep every Shipped_Diagram byte-stable run-to-run."""
    _assert_placement_deterministic(spec)
