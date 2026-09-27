# Requirements Document

**Feature:** Placement Scoring & the Remaining Gates (release 1.9.0)

> **Status: draft for review.** Derived from the approved `design.md`
> (Design-First workflow). Each requirement traces to one design Part (A–D), its
> Components, and its Correctness Properties. Markers such as *(Property 1)* and
> *(Component A2)* point to the design element the requirement grew out of.

## Introduction

Release 1.8.0 inverted routing into a scored per-edge solver (`docs/REVIEW.md`
finding **C5**) and graded the rails metric (**D14**), but scored **routes
only** — holding the three recorded placement defects (`gcp/01` = `(4,0)`, the
landscapes = `(3,2)`) and leaving a documented seam for placement scoring
(*Decision D2*).

Release 1.9.0 closes the **four remaining Open gaps** in `docs/REVIEW.md`:

- a **scored placement loop** layered over the 1.8.0 order-score-commit
  machinery (Requirement 1);
- an **inventory → diagram reconciliation gate** (Requirement 2);
- a **container dead-space lint rule** (Requirement 3);
- **deterministic icon-index slug-collision disambiguation** (Requirement 4).

Cross-cutting gates — determinism, no weakened lint rule, draw.io as the only
publishable source, and a tightened-never-regressed ratchet — must hold
throughout (Requirement 5). The 1.9.0 version bump and CHANGELOG are sequenced
last (Requirement 6).

### Out of scope (1.9.0)

- No new provider; no change to the nine neutral resource types or the
  presentation roles.
- No re-architecture of the 1.8.0 per-edge solver — Part A is an outer loop.

## Glossary

- **Placement_Loop**: `solver.solve_placement(spec)`, the outer
  order-score-commit loop over placement variants.
- **PlacementVariant**: one sanctioned `(id, move, rank)` node/tier move; rank 0
  is the identity (no move).
- **Sanctioned_Move**: one of `widen-gap`, `shift-neighbour`, `reorder-tier`.
- **Base_Placement**: the placement with no move applied; always a candidate.
- **Route_Cost / Ordering_Key**: the shared `geometry.route_cost` objective and
  its `as_tuple()` key, unchanged from 1.8.0.
- **Reconcile_Gate**: `rule-engine-reconcile`, comparing a Snapshot to the
  diagram generated from it.
- **Role_Mapper**: `reconcile.role_of`, mapping raw provider-JSON to a diagram
  role via `mappings/roles.yaml`.
- **Coverage_Class**: `landscape` (total coverage) vs `flow` (scoped coverage).
- **Dead_Space_Rule**: the new advisory `container-dead-space` lint rule.
- **Icon_Index**: the committed `mappings/icon-index.json`.
- **Shipped_Diagram**: a `.drawio` in `examples/` produced by a generator.
- **Gate_Suite**: `rule-engine-lint --all`, `rule-engine-verify-icon --all
  --strict`, `rule-engine-check-rasters`, `rule-engine-reconcile`, and the
  golden-example tests.
- **Ratchet**: `tests/test_route_quality.py`, pinning each Shipped_Diagram's
  recorded RouteCost ceiling.

## Requirements

### Requirement 1: Scored placement loop

**User Story:** As a maintainer, I want a scored placement loop over the 1.8.0
routing machinery, so that the three held placement defects can be relieved by a
sanctioned node/tier move without hand-editing. *(Part A; Components A1, A2;
Properties 1, 2, 3)*

#### Acceptance Criteria

1. THE Placement_Loop SHALL enumerate a rank-ordered, deterministic set of
   PlacementVariants via `generate_placement_variants(spec)`, with the
   Base_Placement always present as rank 0.
2. THE Placement_Loop SHALL enumerate only the three Sanctioned_Moves, each
   emitted only where its target defect can occur.
3. FOR each PlacementVariant, THE Placement_Loop SHALL run the full 1.8.0 inner
   pipeline (place → size → centre → scored route → repair) to a finished
   candidate and score it with Route_Cost.
4. THE Placement_Loop SHALL select the argmin over
   `(Ordering_Key, placement_rank, placement_id)`, so the selected placement's
   Route_Cost SHALL NOT exceed the Base_Placement's Route_Cost (Property 1).
5. THE Placement_Loop SHALL be deterministic: run twice on the same spec it
   SHALL produce a byte-identical `.drawio` (Property 2).
6. A Sanctioned_Move that would break container nesting or padding SHALL NOT be
   enumerated.
7. AFTER Part A, the recorded `gcp/01` and landscape defects SHALL be at or below
   their 1.8.0 ceilings, and the Ratchet SHALL be re-baselined tighter wherever a
   move improves them (Property 3).

### Requirement 2: Inventory → diagram reconciliation gate

**User Story:** As a reviewer, I want a gate that compares a Snapshot to the
diagram generated from it, so that a role-bearing enumerated resource cannot be
silently dropped while the companion asserts completeness. *(Part B; Components
B1, B2; Property 4)*

#### Acceptance Criteria

1. THE Role_Mapper SHALL map each enumerated resource in a Snapshot's per-domain
   JSON to a diagram role using `mappings/roles.yaml`, reading only committed
   Snapshot files and never provider state (Decision D5).
2. THE Reconcile_Gate SHALL compare the mapped expected role set against the
   diagram's drawn node role set.
3. WHERE the Coverage_Class is `landscape`, IF a role-bearing enumerated resource
   has no corresponding node, THEN the Reconcile_Gate SHALL block and name the
   omitted resource(s) (Property 4).
4. WHERE the Coverage_Class is `flow`, THE Reconcile_Gate SHALL block only when a
   resource that is part of the flow the diagram claims to show is absent.
5. A resource with no resolvable role SHALL NOT be reported as an omission.
6. THE Reconcile_Gate SHALL run in the CI_Pipeline as part of the Gate_Suite.

### Requirement 3: Container dead-space lint rule

**User Story:** As a reviewer, I want a container that is sized far larger than
its children flagged, so that the opposite defect from `container-padding` is
also caught. *(Part C; Component C1; Property 5)*

#### Acceptance Criteria

1. THE Dead_Space_Rule SHALL measure the ratio of a Boundary container's area to
   the summed footprint of its direct children plus mandated padding, from the
   parsed `.drawio` geometry.
2. THE Dead_Space_Rule SHALL emit a WARNING on both diagram classes when the
   ratio exceeds a calibrated threshold.
3. THE threshold SHALL be measured across the shipped corpus first and set above
   the sparsest legitimate tier, so that every Shipped_Diagram is clean under the
   rule (Property 5).
4. THE Dead_Space_Rule SHALL be advisory (WARNING) and SHALL NOT block
   publication on its own.
5. THE rule and its severity SHALL be recorded in `diagram-lint.md` and kept in
   sync with the code by the existing rule-table/code sync test.

### Requirement 4: Deterministic icon-index slug-collision disambiguation

**User Story:** As a maintainer, I want a slug collision resolved deterministically
rather than by last-writer-wins, so that the Icon_Index is a stable pure function
of the pack contents. *(Part D; Component D1; Property 6)*

#### Acceptance Criteria

1. WHEN two distinct vendor icons normalise to one slug, THE icon-set builder
   SHALL resolve the winner by a total, deterministic order (SVG over PNG, base
   over Dark/Light variant, then size, then a path tie-break).
2. THE loser SHALL be recorded under a disambiguated slug rather than shadowed.
3. THE builder SHALL emit no collision WARNING once disambiguation is in place.
4. RE-running `build_icon_index` on the same packs SHALL produce a byte-identical
   Icon_Index (Property 6).
5. THE engine's own role resolution SHALL be unaffected by the disambiguation.

### Requirement 5: Cross-cutting gates hold throughout

**User Story:** As a maintainer, I want every honest-gates guarantee to remain
true across all four parts, so that closing these gaps introduces no regression.
*(Properties 2, 7; Decisions D1, D3, D4)*

#### Acceptance Criteria

1. Every part SHALL be deterministic (no randomness, wall-clock, or
   dict-iteration-order dependence), so every Shipped_Diagram stays byte-identical
   run-to-run and Generator_Check holds (Decision D4).
2. No lint rule in `diagram-lint.md` SHALL be weakened; Part C only adds a rule
   (Property 7).
3. draw.io SHALL remain the only publishable diagram source (Decision D1).
4. THE Ratchet SHALL be tightened where a placement move improves a diagram and
   SHALL never be regressed.
5. THE full Gate_Suite SHALL stay green on every Shipped_Diagram (Property 7).
6. Part A SHALL score placements with the shared Route_Cost, not a private copy
   (Decision D3).

### Requirement 6: Release wrap for 1.9.0

**User Story:** As a maintainer, I want the version triple and CHANGELOG updated
last, so that the release records exactly what shipped. *(§Sequencing & scope)*

#### Acceptance Criteria

1. THE version triple (`VERSION`, `pyproject.toml`, newest `CHANGELOG.md`
   heading) SHALL agree on `1.9.0`, keeping `version_guard` /
   `tests/test_version_triple.py` green.
2. THE power pins (`plugin.json`, `bootstrap.sh`, the workspace-init hook git
   tag) SHALL be bumped to `1.9.0`, keeping `tests/test_version_pins.py` green.
3. THE CHANGELOG SHALL carry a `## [1.9.0]` section describing all four parts.
4. THE `docs/REVIEW.md` register SHALL mark the four closed Open gaps as
   Resolved (1.9.0) with stable codes.
5. CI SHALL keep the Python 3.11–3.14 matrix and run the new tests.
