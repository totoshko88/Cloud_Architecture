# Requirements Document

**Feature:** Scored Diagram Router (release 1.8.0)

> **Status: draft for review.** These requirements are derived from the
> approved `design.md` (Design-First workflow). Each requirement traces back to
> the design's three scoped pieces, its Correctness Properties (Properties 1–8),
> and its Design Decisions (D1–D4). Markers such as *(Property 4)* and
> *(Component 3)* point to the design element the requirement grew out of. Two
> review-gate resolutions are already baked in: the binary `rails` count is kept
> alongside the graded `rail_penalty` (design already reflects this), and the
> exact penalty curve is left a task detail (design requires only monotonicity
> and `penalty(d) = 0` for `d >= RAIL_CLEARANCE`).

## Introduction

Routing today is rule-driven with no feedback loop: each of the ~25 named
routing patterns applies in isolation, with no view of the diagram as a whole,
so two patterns can want the same plane. `route_cost` already measures the
objective (crossings, rails, turns, ink) and a ratchet pins each shipped
diagram's ceiling, but nothing optimises against that objective. This is the
largest engineering Open gap recorded in `docs/REVIEW.md`.

Release 1.8.0 closes it in three sequenced, independently reviewable pieces:

- a **behavior-preserving `layout/` package split** that exposes a per-edge
  decision point (Requirement 1);
- a **graded rails metric** that replaces the binary rail count with a penalty
  inversely proportional to clearance, re-baselining the ratchet in the same
  change (Requirement 2);
- a **scored per-edge router** that generates each edge's sanctioned variants,
  scores them with the shared graded `route_cost` against already-accepted
  edges, and commits the minimum deterministically (Requirement 3).

Cross-cutting gates — determinism, no weakened lint rule, draw.io as the only
publishable source, and a tightened-never-regressed ratchet — must remain true
throughout (Requirement 4). Placement-variant scoring is deferred (Requirement
5). The 1.8.0 version bump and CHANGELOG are a task sequenced last (Requirement
6).

### Out of scope (1.8.0)

- **Scoring placement variants** (moving a node or tier to relieve a defect) is
  a design-noted future step, not built in 1.8.0 (*Decision D2*). The two
  recorded placement defects are held, not fixed.
- The four smaller Open gaps: inventory→diagram reconciliation, container
  dead-space, and icon-index slug-collision disambiguation. Each is a separate
  future spec.

## Glossary

- **Layout_Engine**: the current `src/rule_engine/layout_engine.py` module
  (≈3,960 lines) that decides every edge's contacts in ten sequential global
  passes before routing.
- **Layout_Package**: the `src/rule_engine/layout/` package the split produces
  (`model`, `place`, `contacts`, `corridors`, `routers`, `variants`, `solver`,
  `pipeline`).
- **Public_Import_Surface**: the import path callers use, both
  `from rule_engine.layout_engine import layout` and
  `from rule_engine.layout import layout`, resolving to the same `layout(spec)`.
- **Layout_Function**: `layout(spec) -> PlacedDiagram`, the package entry point.
- **Shipped_Diagram**: a `.drawio` in `examples/` produced by a generator.
- **Generator_Check**: the `generator --check` freshness mode that compares a
  generated `.drawio` against the committed file without writing.
- **Legacy_Path**: the retained ten-pass `_place_and_route` code path, selected
  by a `--legacy` flag, used to prove the split is equivalent.
- **CorridorAllocator**: the component that hands out distinct grid-aligned
  corridor lanes.
- **AllocatorState**: the opaque deep-copied snapshot token of all lane
  occupancy (`spans`, `free`, `taken`), produced by `snapshot()` and consumed
  by `restore()`.
- **Route_Cost**: `geometry.route_cost(geo) -> RouteCost`, the shared objective
  function used by the solver, `scripts/route_quality.py`, and the ratchet.
- **RouteCost**: the value returned by Route_Cost: `crossings`, `rails`,
  `rail_penalty`, `turns`, `ink`, and the offender pair tuples.
- **RAIL_CLEARANCE**: the 40px clearance threshold at which a rail run stops
  being penalised.
- **Rail_Penalty**: the `rail_penalty` field of RouteCost: the sum of the
  graded penalty over rail runs.
- **Ordering_Key**: `RouteCost.as_tuple()`, ordered crossings ≫ rail_penalty ≫
  turns ≫ ink.
- **Ratchet**: `tests/test_route_quality.py`, which pins each Shipped_Diagram's
  recorded RouteCost ceiling.
- **RouteVariant**: one sanctioned `(exit, entry, plan, rank)` shape for an
  edge, produced by the variant generator.
- **Variant_Generator**: `variants.generate(edge, placed, containers, kind)`,
  which returns an edge's RouteVariants in rank order.
- **Scored_Solver**: `solver.solve(...)`, the per-edge order-score-commit loop.
- **Rule_Based_Route**: the route the current rule-driven passes produce for an
  edge; always one of the generated RouteVariants.
- **Most_Constrained_First**: the edge ordering — fewest variants first, then
  longest Manhattan span, then declared order.
- **Contract_Legal**: an edge whose exit lies on the right or bottom face and
  whose entry lies on the left or top face (no `edge-direction` finding).
- **Gate_Suite**: `rule-engine-lint --all`, `rule-engine-verify-icon --all
  --strict`, `rule-engine-check-rasters`, and the golden-example tests.
- **CI_Pipeline**: the repository's continuous-integration workflow.
- **Test_Suite**: the repository's automated test suite.
- **Package_Metadata**: `pyproject.toml`.
- **Release**: the published 1.8.0 package together with its `examples/` and
  `CHANGELOG.md`.

## Requirements

### Requirement 1: Behavior-preserving `layout/` package split

**User Story:** As a maintainer, I want the Layout_Engine split into a
Layout_Package that exposes a per-edge decision point without changing any
output, so that the scored router has a seam to hook into and the refactor can
be proven safe before any routing behavior changes. *(Property 1; Components 1,
5; §Architecture seam)*

#### Acceptance Criteria

1. THE Layout_Package SHALL preserve the Public_Import_Surface, so that both
   `from rule_engine.layout_engine import layout` and
   `from rule_engine.layout import layout` resolve to the same Layout_Function.
2. WHEN the split is complete and the Scored_Solver is off, THE Layout_Function
   SHALL produce, for every Shipped_Diagram, a `.drawio` file byte-identical to
   the file produced before the split.
3. WHEN the split is complete and the Scored_Solver is off, THE Generator_Check
   SHALL report no difference for every Shipped_Diagram.
4. WHEN the split is complete and the Scored_Solver is off, THE Test_Suite SHALL
   pass with no test change required by the relocation.
5. THE Layout_Package SHALL retain the Legacy_Path selectable by a `--legacy`
   flag, and THE Legacy_Path SHALL produce a `.drawio` file byte-identical to
   the pre-split output for every Shipped_Diagram.
6. WHEN the split is complete, THE Layout_Package SHALL contain the
   Variant_Generator and the Scored_Solver modules without wiring them into the
   default Layout_Function.

### Requirement 2: Graded rails metric and ratchet re-baseline

**User Story:** As a reviewer, I want the rail metric to grade a run by how
close it passes an icon rather than counting it as a binary at RAIL_CLEARANCE,
so that a run 2px from an icon is ranked worse than one 30px away and the two
real 1.7.0 improvements that were invisible to the binary count now register.
*(Properties 6, 7; Component 4; §Data Models RouteCost)*

#### Acceptance Criteria

1. THE RouteCost SHALL include a `rail_penalty` field equal to the sum of the
   graded penalty over all rail runs.
2. THE RouteCost SHALL retain the binary `rails` count field for Ratchet
   readability.
3. THE Route_Cost SHALL compute the graded penalty as monotonically
   non-increasing in clearance, so that for rail clearances `d1 <= d2` the
   penalty for `d1` is greater than or equal to the penalty for `d2`.
4. THE Route_Cost SHALL compute a penalty of zero for every clearance greater
   than or equal to RAIL_CLEARANCE.
5. THE Ordering_Key SHALL order RouteCost fields crossings ≫ rail_penalty ≫
   turns ≫ ink, using the graded `rail_penalty` rather than the binary `rails`
   count as the second component.
6. WHERE two routes have equal crossings, turns, and ink but different rail
   clearances, THE Ordering_Key SHALL rank the route with the larger clearance
   as lower cost.
7. THE RouteCost SHALL record the clearance of each rail run in its rail offender
   pairs so that a `--detail` view can display it.
8. WHEN the graded metric is introduced, THE Ratchet SHALL be re-baselined in
   the same change so that each Shipped_Diagram records a `rail_penalty`
   ceiling, and THE two 1.7.0 improvements invisible under the binary count
   SHALL register as a strictly lower recorded penalty on their diagrams.

### Requirement 3: Scored per-edge router

**User Story:** As a diagram author, I want the routing stage inverted to a
scored per-edge loop that picks each edge's lowest-cost sanctioned variant
against the edges already placed, so that coupled routing defects dissolve on
their own while output stays deterministic and never worse than today.
*(Properties 2–5, 7, 8; Components 1, 2, 3; §control flow; Decision D4)*

#### Acceptance Criteria

1. THE CorridorAllocator SHALL provide a `snapshot()` operation that returns an
   AllocatorState deep copy that does not alias live state, and a
   `restore(token)` operation that resets occupancy wholesale to the token.
2. WHEN a sequence of `allocate` or `register_gap` calls is applied between a
   `snapshot()` and its `restore(token)`, THE CorridorAllocator SHALL, after the
   restore, return `capacity(g)` and subsequent `allocate(g, …)` results for
   every gap `g` identical to those of an allocator that never applied the
   sequence.
3. THE Variant_Generator SHALL return the sanctioned RouteVariants for an edge in
   rank order and SHALL always include the Rule_Based_Route as one variant, so
   the returned list is never empty.
4. THE Variant_Generator SHALL return only Contract_Legal RouteVariants, so that
   no variant can introduce an `edge-direction` finding regardless of which
   variant the Scored_Solver picks.
5. THE Scored_Solver SHALL order edges Most_Constrained_First, and THE ordering
   SHALL be a pure function of the spec.
6. WHEN scoring an edge's variants, THE Scored_Solver SHALL, for each variant,
   snapshot the CorridorAllocator, tentatively route the variant, score it with
   Route_Cost over the accepted edges plus the variant, and restore the
   CorridorAllocator, so that a rejected variant consumes no lanes.
7. THE Scored_Solver SHALL select each edge's winning variant as the argmin over
   the total key `(RouteCost.as_tuple(), variant.rank, variant.id)`, and SHALL
   commit the winner by re-routing it for real and keeping its lanes.
8. THE Scored_Solver SHALL score every trial with the shared Route_Cost rather
   than a solver-local copy, so that the objective optimised is the objective
   gated.
9. FOR every generated layout, THE `.drawio` produced by the Scored_Solver run
   twice on the same spec SHALL be byte-identical.
10. FOR every Shipped_Diagram, THE Ordering_Key of the scored route SHALL be less
    than or equal to the Ordering_Key of the Rule_Based_Route.
11. IF a variant trial raises a corridor-exhaustion error, THEN THE Scored_Solver
    SHALL score that variant as infeasible, exclude it from the argmin, and
    restore the CorridorAllocator in a `finally` block so no partial allocation
    leaks.
12. IF every variant of an edge is infeasible, THEN THE Scored_Solver SHALL fall
    back to the retained Rule_Based_Route and hand the diagram to the existing
    repair loop, so that no diagram becomes unroutable.
13. IF the Variant_Generator returns an empty list for an edge, THEN THE
    Scored_Solver SHALL raise an error rather than route the edge with no
    variant.

### Requirement 4: Cross-cutting gates remain true

**User Story:** As a maintainer, I want every honest-gates guarantee to hold
after the scored router becomes the default, so that closing the routing gap
does not open a regression in determinism, linting, or artifact format.
*(Property 8; Decisions D1, D3, D4)*

#### Acceptance Criteria

1. THE Scored_Solver SHALL use no randomness, no wall-clock value, and no
   dict-iteration-order dependence, so that the same spec produces a
   byte-identical `.drawio` and the Generator_Check freshness gate holds.
2. WHEN the scored router is the default, THE Release SHALL weaken no lint rule
   in `diagram-lint.md`.
3. THE scored router SHALL keep draw.io as the only publishable diagram source
   and SHALL change only how waypoints are chosen, never the artifact format
   (Decision D1).
4. WHEN the scored router is the default, every Shipped_Diagram SHALL pass the
   Gate_Suite.
5. THE CI_Pipeline SHALL run the Gate_Suite and the Test_Suite on every minor
   Python version from 3.11 up to 3.14.

### Requirement 5: Placement scoring is deferred

**User Story:** As a reviewer, I want 1.8.0 to score routes only and hold the
recorded placement defects rather than fix them, so that the routing win ships
self-contained and low-risk while the placement seam is left in the
architecture for a later release. *(Decision D2; §Non-goals)*

#### Acceptance Criteria

1. THE Release SHALL score routes only and SHALL NOT score placement variants in
   1.8.0.
2. WHEN the scored router is the default, THE Release SHALL NOT regress the
   recorded placement defect for `gcp/01`, whose recorded RouteCost stays at
   `(4, 0)`.
3. WHEN the scored router is the default, THE Release SHALL NOT regress the
   recorded placement defect for the landscapes, whose recorded RouteCost stays
   at `(3, 2)`.
4. THE Variant_Generator boundary SHALL be structured so that a future
   placement-variant generator can be added as an outer loop over the same
   score-and-commit machinery without re-architecting the Scored_Solver.

### Requirement 6: Version bump and CHANGELOG for 1.8.0

**User Story:** As a maintainer, I want release 1.8.0 to update the version
triple and CHANGELOG describing the three pieces, implemented as the last task,
so that the published package records the change. *(§Packaging / Version Notes)*

#### Acceptance Criteria

1. WHEN 1.8.0 is published, THE Package_Metadata SHALL declare the 1.8.0 version
   triple.
2. WHEN 1.8.0 is published, THE Release SHALL include a CHANGELOG entry that
   describes the `layout/` package split, the graded rails metric with ratchet
   re-baseline, and the scored router.
3. THE version bump and CHANGELOG update SHALL be implemented as a task
   sequenced last, after Requirements 1, 2, and 3 are complete.
