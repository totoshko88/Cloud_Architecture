# Feature: placement-and-gates, Property 1 (legality aspect): every placement variant applied → re-place → size → centre stays grid-aligned and lint-clean; the identity is always present at rank 0.
"""Property tests for the placement-variant generator (placement-and-gates 1.9.0,
Part A, task 1.1; design.md §Component A1, Property 1's legality aspect).

This module owns the Part A *variant-generator* property — the legality and
non-emptiness contract of
:func:`rule_engine.layout.variants.generate_placement_variants`. It is kept
separate from ``tests/test_placement_properties.py`` (which owns the placement
*loop* properties — argmin-never-worse-than-base and determinism, tasks 2.1 /
2.2) because it tests a different component (the generator + applier), not the
solver loop.

* **Property 1 (legality aspect)** (task 1.1, *this module*) — every
  :class:`~rule_engine.layout.variants.PlacementVariant`
  :func:`~rule_engine.layout.variants.generate_placement_variants` returns is a
  *legal* placement: applying its move
  (:func:`~rule_engine.layout.variants.apply_placement_move`) and re-running the
  full ``place → size → centre → solve → repair`` pipeline yields a grid-aligned,
  lint-clean (oracle-clean) layout; and the generated list is **never empty**
  with the **identity always present at rank 0** (R1.1, R1.6).

Conventions (established by honest-gates / scored-router): the Hypothesis profile
lives in ``tests/conftest.py`` (loaded automatically, ``max_examples=100``), so
every ``@given`` here runs at least 100 examples without a per-test override.

Two strategies drive the property so both branches of the legality claim get
real coverage:

* ``_small_valid_spec`` (reused) — the broad family of layout-able specs the
  layout-geometry and solver properties use. Its mirror worker/data shape never
  triggers a guarded move, so it exercises the **non-emptiness + identity-at-rank-0**
  branch on every example and the **identity legality** branch.
* ``_move_triggering_spec`` (local) — a shape carrying a within-region tier-skip
  and a ``platform`` fan-out hub, so ``generate_placement_variants`` actually
  emits ``widen-gap`` / ``shift-neighbour`` moves and the **legality-of-a-real-move**
  branch runs.
"""

from __future__ import annotations

from typing import List

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import build_geometry, check_grid_alignment
from rule_engine.layout.variants import (
    PlacementMove,
    PlacementVariant,
    apply_placement_move,
    generate_placement_variants,
)
from rule_engine.layout_engine import (
    ContainerSpec,
    DiagramSpec,
    EdgeSpec,
    GRID,
    LayoutError,
    NodeSpec,
    OverConnectedError,
    _run_oracle,
    _serialize_candidate,
    _validate_spec,
    layout,
)

# Reuse the established small-valid-spec generator (the same one the layout
# geometry and solver property tests drive) so the non-emptiness / identity
# contract and the identity legality are exercised over the broad family of
# layout-able specs the engine can place.
from tests.test_layout_engine_property import _small_valid_spec


@st.composite
def _move_triggering_spec(draw: st.DrawFn) -> DiagramSpec:
    """Generate a valid, layout-able spec that also *triggers a sanctioned move*.

    ``_small_valid_spec`` (reused for breadth) deliberately keeps every source
    side well under the exit cap and uses only mirror workers/data lanes, so it
    never produces a ``platform`` hub, a within-region tier-skip, or a top-tier
    long-run peer pair — i.e. it never triggers one of the three
    :class:`PlacementMove`\\ s, so the legality-of-a-*move* branch would go
    unexercised. This strategy fills that gap: a single-region ``account ⊃ vpc``
    tree carrying

    * a **within-region tier-skip** (``router`` → ``data``, with ``workers`` and
      ``platform`` nodes occupying the lanes between) — the ``widen-gap``
      trigger; and
    * a **``platform`` hub with a fan-out** (a ``platform`` node with ≥ 2 outgoing
      edges) plus an **adjacent same-container neighbour** one slot away — the
      ``shift-neighbour`` trigger.

    The data-slot count (and so the hub fan-out width) is Hypothesis-chosen, so
    the family covers a range of move-triggering shapes rather than one fixed
    spec. Every node names the region VPC as its container (a VPC-direct service
    row), so a move keeps it inside its declared box, and the shape lays out
    oracle-clean.
    """
    data_slots = draw(st.integers(min_value=2, max_value=3))
    # slot 0 = hub (h0), slot 1 = its adjacent same-container neighbour (h1), so a
    # one-slot ``shift-neighbour`` keeps the neighbour inside the VPC.
    nodes: List[NodeSpec] = [
        NodeSpec(id="r0", role="cdn", lane="router", region="a", slot=0, container="vpc-a"),
        NodeSpec(id="w0", role="serverless_fn", lane="workers", region="a", slot=0, container="vpc-a"),
        NodeSpec(id="h0", role="managed_k8s", lane="platform", region="a", slot=0, container="vpc-a"),
        NodeSpec(id="h1", role="managed_k8s", lane="platform", region="a", slot=1, container="vpc-a"),
    ]
    for slot in range(data_slots):
        role = "managed_sql" if slot == 0 else "object_store"
        nodes.append(
            NodeSpec(id=f"d{slot}", role=role, lane="data", region="a", slot=slot, container="vpc-a")
        )

    # router -> data-0 skips the workers/platform lanes between them (w0/h0 sit in
    # the intervening lanes) → a within-region tier-skip.
    edges: List[EdgeSpec] = [
        EdgeSpec(id="skip", source="r0", target="d0", marker="1"),
    ]
    # The hub fans out to every data node (≥ 2 outgoing edges → a fan-out hub).
    for slot in range(data_slots):
        edges.append(
            EdgeSpec(id=f"fan{slot}", source="h0", target=f"d{slot}", marker=str(slot + 2))
        )

    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
    )
    flow_lines = tuple(["Flow"] + [f"{i + 1}. step" for i in range(len(edges))])
    spec = DiagramSpec(
        diagram_id="moveprop",
        diagram_name="move property",
        axis="north-south",
        nodes=tuple(nodes),
        edges=tuple(edges),
        containers=containers,
        flow_lines=flow_lines,
        title="moveprop workload — acct / a | 2025-01-15 | v1",
    )
    # Valid by construction; assert loudly if a future edit breaks the contract.
    _validate_spec(spec)
    return spec


# =========================================================================== #
# Property 1 (legality aspect) — every placement variant is legal, and the
#              identity is always present at rank 0
# =========================================================================== #
#
# Validates: Requirements 1.1, 1.6.
#
# design.md, Component A1 / Property 1: generate_placement_variants(spec) returns
# a rank-ordered, deterministic list whose rank-0 member is ALWAYS the identity
# (the Base_Placement — no move), and whose every move is a whole-slot
# translation of a node / tier WITHIN its own declared container. Because each
# move is re-fed through the same pure ``place → size → centre`` (then the full
# ``solve → repair`` pipeline via ``layout``), the moved layout "stays
# grid-aligned and lint-clean by construction" (design.md §Architecture,
# "Sanctioned placement moves"), and a move that would break container nesting /
# padding is not enumerated in the first place (R1.6).
#
# The property proves TWO things over the real generator + applier + the real
# layout pipeline:
#
#   (a) NON-EMPTINESS + IDENTITY-AT-RANK-0 (R1.1) — for every spec,
#       generate_placement_variants is non-empty, its first member is the
#       identity, that identity holds rank 0, and it is the SOLE rank-0 / SOLE
#       identity variant (so the base is an unambiguous argmin floor); ranks form
#       a contiguous 0..N-1 sequence.
#
#   (b) LEGALITY of every variant (R1.6) — for every variant the generator emits,
#       applying its move (apply_placement_move) yields a still-VALID spec
#       (_validate_spec) and re-running the full pipeline (layout) produces a
#       finished PlacedDiagram that is GRID-ALIGNED (every node/container origin a
#       whole GRID multiple, check_grid_alignment empty) and LINT-CLEAN
#       (_run_oracle reports zero blocking findings).
#
# A spec (base or moved) the engine legitimately refuses to lay out raises
# LayoutError / OverConnectedError; per the design the invariant is conditional
# on the layout existing, so such a case is excluded with ``assume`` rather than
# counted as a counterexample.


def _assert_grid_aligned_and_clean(placed) -> None:
    """Assert a finished :class:`PlacedDiagram` is grid-aligned and lint-clean.

    Reuses the engine's own oracle so the property judges exactly the parsed
    geometry the linter sees:

    * ``_run_oracle(placed).clean`` — zero blocking (ERROR/CRITICAL) geometry
      findings, i.e. the moved layout is publication-eligible under the landscape
      rules the repair loop enforces (R1.6, "lint-clean by construction");
    * ``check_grid_alignment`` on the serialized geometry is empty AND every
      placed node/container origin is a whole ``GRID`` multiple — the moved layout
      "stays grid-aligned by construction" (design.md §Architecture).
    """
    findings = _run_oracle(placed)
    assert findings.clean, (
        f"moved layout has blocking geometry findings: {findings.blocking!r}"
    )

    geo = build_geometry(
        parse_drawio(_serialize_candidate(placed), path="<placement>.drawio")[0]
    )
    assert check_grid_alignment(geo) == [], "moved layout has off-grid nodes"
    for box in list(placed.nodes.values()) + list(placed.containers.values()):
        assert box.x % GRID == 0 and box.y % GRID == 0, (
            f"moved box {box.id!r} origin ({box.x}, {box.y}) is off the grid"
        )


def _assert_variants_legal_and_identity_rank_zero(spec) -> None:
    """The shared body of Property 1's legality aspect (R1.1, R1.6).

    Proves, for a layout-able ``spec``: (a) ``generate_placement_variants`` is
    non-empty with the identity the sole rank-0 / sole identity variant and ranks
    a contiguous ``0..N-1``; and (b) every variant applied
    (``apply_placement_move``) is a still-valid spec that lays out grid-aligned
    and lint-clean. A base or moved spec the engine refuses is excluded via
    ``assume`` — the invariant is conditional on the layout existing."""
    # The base placement must itself be layout-able for the legality claim to be
    # meaningful (every variant is a move ON the base); a base the engine refuses
    # is not a counterexample.
    try:
        layout(spec)
    except (LayoutError, OverConnectedError):
        assume(False)
        return

    variants = generate_placement_variants(spec)

    # --- (a) non-emptiness + identity at rank 0 (R1.1) ---------------------- #
    assert variants, "generate_placement_variants returned an empty list"

    first = variants[0]
    assert first.move is PlacementMove.IDENTITY, (
        f"the rank-0 variant is not the identity: {first.move!r}"
    )
    assert first.rank == 0, f"the identity variant is not at rank 0: rank={first.rank}"

    # The identity is the SOLE rank-0 variant and the SOLE identity variant, so
    # the base is an unambiguous argmin floor (an equal-cost move cannot sort
    # before rank 0, so it never displaces the base).
    rank_zero = [v for v in variants if v.rank == 0]
    assert rank_zero == [first], (
        f"expected exactly one rank-0 variant (the identity); got {rank_zero!r}"
    )
    identities = [v for v in variants if v.move is PlacementMove.IDENTITY]
    assert identities == [first], (
        f"expected exactly one identity variant; got {identities!r}"
    )

    # Ranks are a contiguous 0..N-1 sequence (deterministic, rank-ordered) — no
    # duplicate or gapped rank that would make the argmin tie-break ambiguous.
    ranks = sorted(v.rank for v in variants)
    assert ranks == list(range(len(variants))), (
        f"ranks are not a contiguous 0..N-1 sequence: {ranks!r}"
    )

    # --- (b) legality of every variant (R1.6) ------------------------------ #
    for variant in variants:
        assert isinstance(variant, PlacementVariant)
        moved = apply_placement_move(spec, variant)

        # The identity returns the base spec unchanged; a real move returns a
        # transformed-but-still-VALID spec (a malformed spec would be an illegal
        # move the generator must never enumerate).
        if variant.move is PlacementMove.IDENTITY:
            assert moved is spec, "the identity move must return the spec unchanged"
        _validate_spec(moved)

        # Re-run the full pipeline on the moved spec. The move keeps every node in
        # its container, so a moved spec the engine now refuses is a genuine
        # routing dead-end (dropped by the loop's argmin), not a malformed move —
        # exclude it rather than count it as a legality counterexample.
        try:
            placed = layout(moved)
        except (LayoutError, OverConnectedError):
            assume(False)
            return

        _assert_grid_aligned_and_clean(placed)


# Feature: placement-and-gates, Property 1 (legality aspect): variants legal + identity at rank 0 (broad family)
# Each example runs the full placement + routing pipeline once per variant, so
# per-example wall time depends on machine load; under the full suite this
# tripped Hypothesis' default 200ms deadline (a timing flake, not a defect).
# The example budget and the property are unchanged; only the deadline is off.
@settings(deadline=None)
@given(spec=_small_valid_spec())
def test_placement_variants_legal_and_identity_rank_zero(spec) -> None:
    """Every generated placement variant is legal, and the identity is rank 0
    (R1.1, R1.6), over the broad family of layout-able specs.

    For a generated layout-able spec: ``generate_placement_variants`` is never
    empty with the identity as the sole rank-0 / sole identity variant, and every
    variant applied (``apply_placement_move``) lays out grid-aligned and
    lint-clean. This family exercises the non-emptiness + identity contract on
    every example and the identity-legality branch."""
    _assert_variants_legal_and_identity_rank_zero(spec)


# Feature: placement-and-gates, Property 1 (legality aspect): variants legal + identity at rank 0 (move-triggering)
# Each example runs the full placement + routing pipeline once per variant, so
# per-example wall time depends on machine load; under the full suite this
# tripped Hypothesis' default 200ms deadline (a timing flake, not a defect).
# The example budget and the property are unchanged; only the deadline is off.
@settings(deadline=None)
@given(spec=_move_triggering_spec())
def test_placement_move_variants_are_legal(spec) -> None:
    """The same legality contract holds when the generator actually emits a
    sanctioned MOVE (R1.1, R1.6).

    ``_move_triggering_spec`` carries a within-region tier-skip and a ``platform``
    fan-out hub, so ``generate_placement_variants`` emits ``widen-gap`` /
    ``shift-neighbour`` variants in addition to the identity. Applying each move
    and re-running the full pipeline still yields a grid-aligned, lint-clean
    layout — proving the legality claim on real moves, not only on the identity."""
    _assert_variants_legal_and_identity_rank_zero(spec)
