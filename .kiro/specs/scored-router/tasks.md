# Implementation Plan: Scored Diagram Router (release 1.8.0)

## Overview

This plan implements `design.md` in Python (the project language). Work follows
the design's three sequenced, independently reviewable pieces, in order, with a
checkpoint after each:

1. **Phase A — behavior-preserving `layout/` package split** (Requirement 1;
   Property 1). Relocate `layout_engine.py` into a `layout/` package behind
   stable names, add `variants.py`/`solver.py` **unwired**, keep the `--legacy`
   ten-pass path, and prove every shipped `.drawio` is byte-identical with the
   solver off.
2. **Phase B — graded rails metric + ratchet re-baseline** (Requirement 2;
   Properties 6, 7). Add `RouteCost.rail_penalty` (keep the binary `rails`),
   re-order `as_tuple()`, and re-baseline `tests/test_route_quality.py` in the
   **same** change so the two 1.7.0 improvements register as a strictly lower
   penalty.
3. **Phase C — scored per-edge router** (Requirement 3; Properties 2, 3, 4, 5,
   and a re-confirm of 7, 8). Add allocator snapshot/restore, the rank-ordered
   contract-legal variant generator, and the order-score-commit solver; wire it
   in as the default while keeping `--legacy`.
4. **Phase D — release wrap** (Requirement 6; Requirement 4 cross-cutting). Bump
   the 1.8.0 version triple and CHANGELOG, keep the CI matrix 3.11–3.14, and run
   every new property test in CI.

Cross-cutting gates (Requirement 4) hold **throughout**, not only at the end:
determinism (`generator --check`), no weakened lint rule in `diagram-lint.md`,
draw.io as the only publishable source (D1), and a tightened-never-regressed
ratchet. Placement-variant scoring is a **non-goal** for 1.8.0 (Requirement 5,
Decision D2): the two recorded placement defects (`gcp/01` = `(4,0)`,
landscapes = `(3,2)`) are **held, not fixed** — no task moves a node or tier;
only the `generate()` seam is left in for a later release.

Conventions:

- Requirement references use the form R*n*.*m*. Property references (P*n*) point
  to `design.md` → *Correctness Properties*.
- Each property test uses Hypothesis with `max_examples >= 100` and carries the
  tag comment `# Feature: scored-router, Property N: <title>`. Shared strategies
  live in `tests/strategies.py` and the Hypothesis profile in `tests/conftest.py`
  (both already established by honest-gates; this plan extends them).
- The version triple is `VERSION`, `pyproject.toml` and `CHANGELOG.md`, checked
  by `rule_engine.version_guard` / `tests/test_version_triple.py`.

## Tasks

- [x] 1. Phase A — `layout/` package skeleton and relocation
  - [x] 1.1 Create the `layout/` package and move the model types
    - Create `src/rule_engine/layout/__init__.py` and move `DiagramSpec`, `EdgeSpec`, `NodeSpec`, `PlacedDiagram` and `Contact` into `src/rule_engine/layout/model.py` (design §layout/ package seam).
    - `__init__.py` re-exports `layout`, `DiagramSpec` and `PlacedDiagram` so `from rule_engine.layout import layout` resolves to the entry point.
    - Do not change any type field, name or default — this is a mechanical relocation.
    - _Requirements: R1.1_
  - [x] 1.2 Relocate placement, contacts, corridors and routers behind stable names
    - Move `place_nodes`, `size_containers`, `centre_block_in_vpc` into `layout/place.py`.
    - Move `select_contacts` and the contact-ladder helpers into `layout/contacts.py`.
    - Move `CorridorAllocator` into `layout/corridors.py` (snapshot/restore added later in Phase C — not here).
    - Move the per-edge routers (`route_cross_region`, spine, back-edge, fan-out, …) into `layout/routers.py`.
    - Keep every symbol name identical so internal call sites move without semantic change.
    - _Requirements: R1.1, R1.6_
  - [x] 1.3 Assemble `pipeline.py` and retain the `--legacy` ten-pass path
    - Add `layout/pipeline.py` with `layout(spec) -> PlacedDiagram`: `place → size → centre → (solver | legacy) → repair`.
    - Move the current ten-pass `_place_and_route` into `pipeline.py` as the `Legacy_Path`, selected by a `--legacy` flag threaded from the generator entry points.
    - With the solver absent, `layout()` MUST route via the retained rule-driven path so output is unchanged.
    - _Requirements: R1.1, R1.5, R1.6_
  - [x] 1.4 Turn `layout_engine.py` into a re-export shim
    - Rewrite `src/rule_engine/layout_engine.py` to re-export `layout`, `DiagramSpec`, `PlacedDiagram` (and any previously public symbol) from `rule_engine.layout`, so `from rule_engine.layout_engine import layout` keeps working with no caller edit.
    - Add `layout/variants.py` and `layout/solver.py` as **stubs present but unwired** (module-level `generate`/`solve` signatures per design Components 2, 3), imported by nothing in the default path.
    - _Requirements: R1.1, R1.6_
  - [x] 1.5 Write the byte-identity / behavior-preserving property test
    - **Property 1: the split is behavior-preserving**
    - **Validates: Requirements 1.2, 1.3, 1.4**
    - Assert that `layout(s)` (solver off) produces a `.drawio` byte-identical to the committed file for every shipped spec, that `generator --check` reports no difference, and that the `--legacy` path is byte-identical to the pre-split output (R1.5).
    - Use `max_examples >= 100` over the shipped-spec corpus plus generated small specs; tag `# Feature: scored-router, Property 1: the split is behavior-preserving`.
    - File: `tests/test_layout_split_properties.py`
  - [x] 1.6 Write example tests for the public import surface and the unwired seam
    - Both `from rule_engine.layout_engine import layout` and `from rule_engine.layout import layout` resolve to the same function object (R1.1).
    - `layout.variants` and `layout.solver` import cleanly but are not referenced by the default `layout()` (R1.6).
    - Confirm the existing suite passes with no test change forced by the relocation (R1.4).
    - File: `tests/test_layout_package.py`
    - _Requirements: R1.1, R1.4, R1.6_

- [x] 2. Checkpoint A — split landed, byte-identical, gates green, solver off
  - Run `pytest`, `rule-engine-lint --all`, and the seven generator `--check` runs. Every shipped `.drawio` must be byte-identical and the solver must still be off. Ensure all tests pass, ask the user if questions arise.

- [x] 3. Phase B — graded rails metric in `route_cost`
  - [x] 3.1 Extend `RouteCost` with `rail_penalty` and re-order the key
    - In `src/rule_engine/geometry.py`, add `rail_penalty: float = 0.0` to `RouteCost` and keep the binary `rails` count field for ratchet readability (R2.1, R2.2).
    - Change `as_tuple()` to `(crossings, round(rail_penalty, 3), turns, round(ink))` so the ordering key is crossings ≫ rail_penalty ≫ turns ≫ ink, using the graded penalty as the second component (R2.5).
    - Record each rail run's clearance in `rail_pairs` as `(eid, nid, span, clearance)` so a `--detail` view can display it (R2.7).
    - _Requirements: R2.1, R2.2, R2.5, R2.7_
  - [x] 3.2 Implement the graded penalty function
    - Add `rail_penalty(clearance)` (monotonically non-increasing, `0` for `clearance >= RAIL_CLEARANCE`), choosing the concrete curve against real corpus numbers — e.g. `max(0, (RAIL_CLEARANCE - d) / RAIL_CLEARANCE)` clamped — and sum it over rail runs into `RouteCost.rail_penalty` (R2.3, R2.4).
    - Ensure `route_cost` computes `rail_penalty` from the same rail-run detection that produces the binary `rails` count, so the two stay consistent.
    - _Requirements: R2.3, R2.4_
  - [x] 3.3 Re-baseline the ratchet in the same change
    - Update `tests/test_route_quality.py` to record a `rail_penalty` ceiling per Shipped_Diagram alongside the existing crossing/rail ceilings (R2.8).
    - Measure the corpus with the graded metric and commit the tightened ceilings so the two 1.7.0 improvements invisible under the binary count register as a **strictly lower** recorded penalty on their diagrams (R2.8, tightened-not-regressed).
    - Keep the recorded placement defects unchanged: `gcp/01` stays `(4,0)` and the landscapes stay `(3,2)` (R5.2, R5.3).
    - _Requirements: R2.8, R5.2, R5.3_
  - [x] 3.4 Write the property test for penalty monotonicity
    - **Property 6: graded rail penalty is monotonic in clearance**
    - **Validates: Requirements 2.3, 2.4, 2.6**
    - For clearances `d1 <= d2`, assert `penalty(d1) >= penalty(d2)` and `penalty(d) == 0` for `d >= RAIL_CLEARANCE`; assert two otherwise-equal routes order by larger clearance = lower cost.
    - Tag `# Feature: scored-router, Property 6: graded rail penalty is monotonic in clearance`; `max_examples >= 100`.
    - File: `tests/test_route_cost_properties.py`
  - [x] 3.5 Write the property test for the tightened-not-regressed ratchet
    - **Property 7: the ratchet is not regressed (and is tightened)**
    - **Validates: Requirements 2.8**
    - Assert every shipped diagram satisfies `crossings <= ceiling` and `rail_penalty <= recorded_ceiling`, and that the two flagged diagrams record a strictly lower penalty than their pre-graded value.
    - Tag `# Feature: scored-router, Property 7: the ratchet is not regressed (and is tightened)`; `max_examples >= 100`.
    - File: `tests/test_route_cost_properties.py`

- [x] 4. Checkpoint B — graded metric in, ratchet re-baselined, corpus measured
  - Run `pytest` and `rule-engine-lint --all`. The graded metric is in, the ratchet is re-baselined, and the placement defects are held. Ensure all tests pass, ask the user if questions arise.

- [x] 5. Phase C — allocator snapshot/restore
  - [x] 5.1 Implement `CorridorAllocator.snapshot()` / `restore()`
    - In `src/rule_engine/layout/corridors.py`, add `snapshot() -> AllocatorState` returning a deep copy of `_spans`, `_free` (order preserved) and `_taken` that does not alias live state, and `restore(token)` that resets occupancy wholesale to the token (design Component 1).
    - `restore` must be total: a variant that widened a gap, allocated lanes, then raised mid-way restores cleanly.
    - _Requirements: R3.1, R3.2_
  - [x] 5.2 Write the property test for snapshot/restore
    - **Property 2: allocator snapshot/restore leaves no lane consumed by a rejected variant**
    - **Validates: Requirements 3.1, 3.2**
    - For any allocator state and any `allocate`/`register_gap` sequence `C`, assert `snapshot(); apply(C); restore(token)` yields `capacity(g)` and subsequent `allocate(g, …)` results identical to an allocator that never applied `C`.
    - Tag `# Feature: scored-router, Property 2: allocator snapshot/restore leaves no lane consumed by a rejected variant`; `max_examples >= 100`.
    - File: `tests/test_solver_properties.py`

- [x] 6. Phase C — variant generator
  - [x] 6.1 Implement `variants.generate()` returning rank-ordered contract-legal variants
    - In `src/rule_engine/layout/variants.py`, implement `RouteVariant(id, exit, entry, plan, rank)` and `generate(edge, placed, containers, kind) -> list[RouteVariant]` (design Component 2, Data Models RouteVariant).
    - Cover the variant families from the design table: lane side (above/below), back-edge shape (loop-above/descend-near), spine (straight-drop/side-corridor), corridor side (left-gap/right-gap).
    - Always include the `Rule_Based_Route` as one variant so the list is never empty (R3.3), and construct every variant contract-legal (exit right/bottom, entry left/top) so no variant can introduce an `edge-direction` finding (R3.4).
    - Leave the `generate()` boundary structured so a future `generate_placement_variants()` is an outer loop over the same machinery — do **not** implement placement variants (R5.4).
    - _Requirements: R3.3, R3.4, R5.4_
  - [x] 6.2 Write the property test for scored route_cost never exceeding rule-based
    - **Property 4: scored route_cost never exceeds the rule-based route_cost**
    - **Validates: Requirements 3.3, 3.10**
    - For every generated layout, assert `route_cost(scored(L)).as_tuple() <= route_cost(rule_based(L)).as_tuple()` (the rule-based choice is always a generated variant, so argmin can never do worse).
    - Tag `# Feature: scored-router, Property 4: scored route_cost never exceeds the rule-based route_cost`; `max_examples >= 100`.
    - File: `tests/test_solver_properties.py`
  - [x] 6.3 Write the property test for every variant being contract-legal
    - **Property 5: every variant is contract-legal**
    - **Validates: Requirements 3.4**
    - For every edge and every variant `v` from `generate`, assert `v.exit` lies on the right or bottom face and `v.entry` on the left or top face.
    - Tag `# Feature: scored-router, Property 5: every variant is contract-legal`; `max_examples >= 100`.
    - File: `tests/test_solver_properties.py`

- [x] 7. Phase C — scored solver and wiring
  - [x] 7.1 Implement `solver.solve()` order-score-commit loop
    - In `src/rule_engine/layout/solver.py`, implement `most_constrained_first(edges, placed)` (fewest variants, then longest Manhattan span, then declared order) as a pure function of the spec (R3.5).
    - For each edge, for each variant: `snapshot` the allocator, tentatively route, score with the shared graded `route_cost` over the accepted edges plus the variant, then `restore` — so a rejected variant consumes no lanes (R3.6, R3.8).
    - Select the winner as argmin over `(RouteCost.as_tuple(), variant.rank, variant.id)` and commit by re-routing for real and keeping its lanes (R3.7).
    - _Requirements: R3.5, R3.6, R3.7, R3.8_
  - [x] 7.2 Implement solver error handling
    - Catch a corridor-exhaustion error in a variant trial, score that variant infeasible, exclude it from the argmin, and `restore` in a `finally` block so no partial allocation leaks (R3.11).
    - When every variant of an edge is infeasible, fall back to the retained `Rule_Based_Route` and hand the diagram to the existing widen/re-centre repair loop (R3.12).
    - Raise an error if `variants.generate()` returns an empty list — a contract violation, not an input condition (R3.13).
    - _Requirements: R3.11, R3.12, R3.13_
  - [x] 7.3 Wire the solver in as the default; keep `--legacy`
    - In `layout/pipeline.py`, make `solve()` the default routing stage; retain the `--legacy` ten-pass path behind the flag.
    - Use no randomness, no wall-clock, and no dict-iteration-order dependence, so the same spec produces a byte-identical `.drawio` and the `generator --check` gate holds (R4.1, R4.3).
    - Weaken no lint rule in `diagram-lint.md`; change only how waypoints are chosen, never the artifact format (R4.2, R4.3).
    - _Requirements: R3.7, R4.1, R4.2, R4.3_
  - [x] 7.4 Write the property test for solver determinism
    - **Property 3: scored router is deterministic**
    - **Validates: Requirements 3.9, 4.1**
    - For every generated layout, assert `solve(L)` called twice returns the identical routed edge set (same contacts, same waypoints) and a byte-identical serialized `.drawio`.
    - Tag `# Feature: scored-router, Property 3: scored router is deterministic`; `max_examples >= 100`.
    - File: `tests/test_solver_properties.py`
  - [x] 7.5 Write example tests for solver error handling
    - A variant trial raising corridor-exhaustion is scored infeasible and its allocator state restored (assert no consumed lane) (R3.11).
    - An all-infeasible edge falls back to the rule-based route and the repair loop (R3.12); an empty variant list raises (R3.13).
    - File: `tests/test_solver.py`
    - _Requirements: R3.11, R3.12, R3.13_

- [x] 8. Phase C — regenerate improved diagrams and confirm gates
  - [x] 8.1 Regenerate any Shipped_Diagram whose scored route improves
    - Run the seven generators; regenerate outputs whose scored `Ordering_Key` is lower than the rule-based route (R3.10), and update the re-baselined `rail_penalty` ceilings in `tests/test_route_quality.py` accordingly (tightened-not-regressed).
    - Confirm every regenerated `.drawio` is byte-identical on a second run (R3.9, R4.1) and that `generator --check` is green.
    - Do **not** move any node or tier; hold `gcp/01` = `(4,0)` and the landscapes = `(3,2)` (R5.1, R5.2, R5.3).
    - _Requirements: R3.9, R3.10, R4.1, R5.1, R5.2, R5.3_
  - [x] 8.2 Confirm the full Gate_Suite stays green
    - Run `rule-engine-lint --all`, `rule-engine-verify-icon --all --strict`, `rule-engine-check-rasters` and the golden-example tests; every Shipped_Diagram must pass (R4.4).
    - _Requirements: R4.4_
  - [x] 8.3 Write the property test for no shipped example losing a gate
    - **Property 8: no shipped example loses a gate**
    - **Validates: Requirements 1, 2, 3, 4.4**
    - Assert every shipped example passes `rule-engine-lint --all`, `verify-icon --all --strict`, `check-rasters` and the golden-example tests after the scored router is the default.
    - Tag `# Feature: scored-router, Property 8: no shipped example loses a gate`; `max_examples >= 100` where generated, else parametrised over the corpus.
    - File: `tests/test_solver_properties.py`

- [x] 9. Checkpoint C — scored router default, deterministic, gates green, defects held
  - Run `pytest`, `rule-engine-lint --all`, `rule-engine-verify-icon --all --strict`, `rule-engine-check-rasters`, the golden-example tests and the seven generator `--check` runs. The scored router is the default, output is deterministic, and the two placement defects are held. Ensure all tests pass, ask the user if questions arise.

- [x] 10. Phase D — release wrap for 1.8.0
  - [x] 10.1 Bump the version triple to 1.8.0
    - Set `version = "1.8.0"` in `pyproject.toml`, add the top `## [1.8.0]` heading to `CHANGELOG.md`, and keep the triple consistent so `rule_engine.version_guard` / `tests/test_version_triple.py` pass (R6.1, R6.3).
    - _Requirements: R6.1, R6.3_
  - [x] 10.2 Write the CHANGELOG 1.8.0 section
    - Add a `## [1.8.0]` section to `CHANGELOG.md` describing the three pieces: the behavior-preserving `layout/` package split, the graded rails metric with ratchet re-baseline, and the scored per-edge router (R6.2).
    - The section must pass `tests/test_changelog_section.py`.
    - _Requirements: R6.2_
  - [x] 10.3 Keep CI 3.11–3.14 and run the new property tests
    - Confirm `.github/workflows/ci.yml` keeps the matrix `["3.11", "3.12", "3.13", "3.14"]` and that the new `tests/test_*_properties.py` files run in CI alongside the Gate_Suite (R4.5).
    - Update `tests/test_hooks_and_ci_gates.py` if it enumerates the test files or gate steps.
    - _Requirements: R4.5_

- [x] 11. Final checkpoint — release gates green on 3.11–3.14
  - Run `pytest`, `rule-engine-lint --all`, `rule-engine-verify-icon --all --strict`, the seven generator `--check` runs, `rule-engine-check-rasters` and the version-triple guard. All must be green on every Python 3.11 through 3.14. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP. The eight property sub-tasks (1.5, 3.4, 3.5, 5.2, 6.2, 6.3, 7.4, 8.3) map one-to-one onto design Properties 1–8.
- The four checkpoints match the design's three independently-reviewable pieces plus the release wrap: A (split, byte-identical, solver off), B (graded metric + re-baseline), C (scored router default, defects held), D (release).
- Cross-cutting gates hold throughout: determinism via `generator --check`, no weakened lint rule, draw.io-only (D1), tightened-never-regressed ratchet.
- **Placement scoring is a non-goal** (Requirement 5, Decision D2): no task moves a node or tier. Only the `variants.generate()` seam is left in for a future placement release; the two recorded defects (`gcp/01` = `(4,0)`, landscapes = `(3,2)`) are held.
- Property sub-tasks that share a test file are placed in different waves below to avoid write conflicts.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["1.4"] },
    { "id": 4, "tasks": ["1.5", "1.6"] },
    { "id": 5, "tasks": ["3.1"] },
    { "id": 6, "tasks": ["3.2"] },
    { "id": 7, "tasks": ["3.3"] },
    { "id": 8, "tasks": ["3.4", "3.5"] },
    { "id": 9, "tasks": ["5.1"] },
    { "id": 10, "tasks": ["5.2", "6.1"] },
    { "id": 11, "tasks": ["6.2", "6.3"] },
    { "id": 12, "tasks": ["7.1"] },
    { "id": 13, "tasks": ["7.2"] },
    { "id": 14, "tasks": ["7.3"] },
    { "id": 15, "tasks": ["7.4", "7.5"] },
    { "id": 16, "tasks": ["8.1"] },
    { "id": 17, "tasks": ["8.2"] },
    { "id": 18, "tasks": ["8.3"] },
    { "id": 19, "tasks": ["10.1"] },
    { "id": 20, "tasks": ["10.2", "10.3"] }
  ]
}
```
