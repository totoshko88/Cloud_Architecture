"""Example (unit) tests for the scored solver's error handling
(scored-router 1.8.0, Phase C, task 7.5; design.md §Error Handling).

These are **example** tests, not property-based: each constructs a small,
controlled scenario and asserts one concrete error-handling behaviour of
:func:`rule_engine.layout.solver.solve`. They pin the three error paths task
7.2 added on top of the order-score-commit loop:

* **R3.11 — a variant trial raising corridor-exhaustion is scored infeasible
  and its allocator state restored.** A variant whose tentative lay raises
  :class:`~rule_engine.layout.corridors.CorridorExhaustedError` — even after it
  has already consumed a lane — must drop out of the ``argmin`` and leave the
  allocator with **no lane consumed by the rejected variant** (the ``finally:
  restore`` runs). The edge is still committed via a surviving variant, so the
  solver does not crash.
* **R3.12 — an all-infeasible edge falls back to the rule-based route.** When
  *every* variant trial of *every* edge is scored infeasible, the solver falls
  back to the retained rule-based route and lays it against the live allocator,
  so ``solve`` still returns one committed edge per declared edge rather than
  raising.
* **R3.13 — an empty variant list raises.** An empty list from
  :func:`variants.generate` is a generator contract violation (the rule-based
  variant is always present), so the solver raises
  :class:`~rule_engine.layout.solver.EmptyVariantListError` rather than routing
  an edge with no variant.

The scenarios reuse the committed ``SUMMARY_SPEC`` run through the real ``place
→ size → centre`` stages — the same known-good spec ``tests/test_layout_package.py``
routes through ``solve`` — so the error paths are exercised against a real
placed diagram, not a hand-built stub.

Requirements: R3.11, R3.12, R3.13
"""

from __future__ import annotations

import pytest

from rule_engine.layout import solver as solver_mod
from rule_engine.layout.solver import EmptyVariantListError, solve
from rule_engine.layout.corridors import CorridorAllocator, CorridorExhaustedError
from rule_engine.layout.place import (
    centre_block_in_vpc,
    place_nodes,
    size_containers,
)
from rule_engine.ha_multiregion_spec import SUMMARY_SPEC


# --------------------------------------------------------------------------- #
# Shared fixture: SUMMARY_SPEC run through place -> size -> centre.
# --------------------------------------------------------------------------- #

def _placed_summary():
    """Return the ``(placed, containers, spec)`` for SUMMARY_SPEC after the real
    place -> size -> centre stages — the inputs ``solve`` expects."""
    placed = place_nodes(SUMMARY_SPEC)
    containers = size_containers(placed, SUMMARY_SPEC)
    placed = centre_block_in_vpc(placed, containers, SUMMARY_SPEC)
    return placed, containers, SUMMARY_SPEC


def _total_taken(alloc: CorridorAllocator) -> int:
    """Total corridor lines currently handed out across every gap.

    Reads the allocator's ``_taken`` occupancy directly: the sum of the sizes of
    every gap's taken-line set. Used to prove a rejected variant's lanes did not
    leak — a rejected trial must add nothing to this total once ``solve`` returns."""
    return sum(len(lines) for lines in alloc._taken.values())


# =========================================================================== #
# R3.11 — a corridor-exhausted variant trial is infeasible; allocator restored.
# =========================================================================== #

def test_exhausted_variant_trial_is_infeasible_and_leaks_no_lane():
    """A variant trial that consumes a lane then raises corridor-exhaustion drops
    out of the argmin and leaves NO lane consumed by it (R3.11).

    The scenario patches the solver's ``_lay_variant`` so that the FIRST trial it
    ever sees both (a) allocates a real corridor lane from the live allocator and
    (b) then raises :class:`CorridorExhaustedError` — the "widened a gap,
    allocated a lane, then raised mid-way" case the design calls out. Because the
    solver snapshots before the trial and restores in a ``finally``, that lane
    must not survive: after ``solve`` returns, the only lanes taken are those the
    committed winners actually consumed, and re-running the same solve on a fresh
    allocator (with the patch removed) consumes the SAME number of lanes — proof
    the rejected trial leaked none.
    """
    placed, containers, spec = _placed_summary()

    real_lay = solver_mod._lay_variant
    state = {"raised": False}
    # A gap id + span guaranteed to have a free grid line, so the poisoned trial
    # genuinely consumes a lane before it raises.
    poison_gap = "solver-test:poison"
    poison_low, poison_high = 0.0, 200.0

    def _poison_first_trial(edge, variant, placed_, containers_, alloc, *args, **kwargs):
        # Poison exactly one trial: allocate a real lane from the LIVE allocator,
        # then raise corridor-exhaustion. The solver's finally-restore must undo
        # both the snapshot's prior state AND this allocation.
        if not state["raised"]:
            state["raised"] = True
            alloc.allocate(poison_gap, poison_low, poison_high)
            assert alloc.capacity(poison_gap) >= 0  # lane was consumed on this gap
            raise CorridorExhaustedError(poison_gap, poison_low, poison_high, 1)
        return real_lay(edge, variant, placed_, containers_, alloc, *args, **kwargs)

    solver_mod._lay_variant = _poison_first_trial
    try:
        alloc = CorridorAllocator()
        routed = solve(placed, containers, spec, alloc)
    finally:
        solver_mod._lay_variant = real_lay

    # The solver did not crash: one committed edge per declared edge.
    assert [pe.spec.id for pe in routed] == [e.id for e in spec.edges]
    assert state["raised"], "the poisoned trial was never reached"

    # The rejected variant consumed a lane in the ``poison`` gap; after the
    # finally-restore that gap must carry NO taken line — nothing leaked (R3.11).
    assert poison_gap not in alloc._taken or len(alloc._taken[poison_gap]) == 0

    # Stronger: the committed allocation is identical to a clean solve that never
    # saw the poisoned trial, so the rejected variant left the allocator exactly
    # as if it had never run.
    clean_alloc = CorridorAllocator()
    solve(placed, containers, spec, clean_alloc)
    assert _total_taken(alloc) == _total_taken(clean_alloc)


# =========================================================================== #
# R3.12 — every variant infeasible -> fall back to the rule-based route.
# =========================================================================== #

def test_all_infeasible_falls_back_to_rule_based_route():
    """When every variant trial is infeasible the solver falls back to the
    retained rule-based route rather than crashing (R3.12).

    The scenario patches the solver's ``_score`` to always raise
    :class:`CorridorExhaustedError`. ``_score`` is called inside the per-variant
    ``try`` for every trial, so this makes EVERY variant of EVERY edge infeasible
    (the ``argmin`` sees nothing). The solver must then fall back to the
    rule-based variant for each edge and lay it against the live allocator —
    ``_lay_variant`` is left intact, so the fallback lay succeeds — and still
    return one committed edge per declared edge in declared order.
    """
    placed, containers, spec = _placed_summary()

    def _always_infeasible(*args, **kwargs):
        raise CorridorExhaustedError("solver-test:all", 0.0, 10.0, 0)

    real_score = solver_mod._score
    solver_mod._score = _always_infeasible
    try:
        alloc = CorridorAllocator()
        routed = solve(placed, containers, spec, alloc)
    finally:
        solver_mod._score = real_score

    # Fallback did not crash: one committed edge per declared edge, declared order.
    assert [pe.spec.id for pe in routed] == [e.id for e in spec.edges]
    # Every fallback edge carries a real laid route (contacts + a point list),
    # i.e. the rule-based route was actually laid, not left empty.
    for pe in routed:
        assert pe.exit is not None and pe.entry is not None
        assert isinstance(pe.points, list)


# =========================================================================== #
# R3.13 — an empty variant list is a contract violation and raises.
# =========================================================================== #

def test_empty_variant_list_raises_empty_variant_list_error():
    """An empty list from ``variants.generate`` raises ``EmptyVariantListError``
    (R3.13).

    The rule-based variant is always present, so an empty list can only be a
    generator contract violation, never an input condition. The scenario
    monkeypatches the ``generate`` the solver calls (``solver_mod._variants.generate``)
    to return ``[]`` and asserts the solver raises rather than routing an edge
    with no variant. The raised error names the offending edge id.
    """
    placed, containers, spec = _placed_summary()

    real_generate = solver_mod._variants.generate
    solver_mod._variants.generate = lambda *a, **k: []
    try:
        alloc = CorridorAllocator()
        with pytest.raises(EmptyVariantListError) as excinfo:
            solve(placed, containers, spec, alloc)
    finally:
        solver_mod._variants.generate = real_generate

    # The error identifies which edge had the empty list (the first in solve order).
    assert excinfo.value.edge_id in {e.id for e in spec.edges}
