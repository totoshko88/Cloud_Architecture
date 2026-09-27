# Implementation Plan — Placement Scoring & the Remaining Gates (1.9.0)

Derived from `design.md` and `requirements.md`. The four parts (A–D) are
independent; only Part A depends on 1.8.0 machinery. Each part ends with its own
property tests; the release wrap is sequenced last. Requirement references are in
parentheses.

## Overview

This plan closes the four remaining Open gaps from `docs/REVIEW.md` for release
1.9.0 in four independent parts (A–D) plus a release wrap (E). Part A is a scored
placement loop layered over the 1.8.0 routing machinery; Parts B/C/D each close
one recorded gap (reconciliation gate, dead-space lint, slug disambiguation).
Only Part A depends on 1.8.0 code; B, C and D are independent of A and of each
other. Each part ends with its own property tests and a checkpoint.

## Tasks

## Part A — Scored placement loop

- [x] 1. Implement `generate_placement_variants(spec)` in `layout/variants.py`
  - Return a rank-ordered, deterministic list of `PlacementVariant(id, move, rank)`; rank 0 is always the identity (no move).
  - Enumerate only the three Sanctioned_Moves (`widen-gap`, `shift-neighbour`, `reorder-tier`), each guarded so it is emitted only where its target defect can occur; do not enumerate a move that would break container nesting/padding.
  - Pure function of the spec (no allocator, no randomness). Replace `_placement_seam_note` with the real generator.
  - _Requirements: 1.1, 1.2, 1.6_

- [x] 1.1 Write the property test for placement-variant legality and non-emptiness
  - Property: every variant applied → re-`place → size → centre` stays grid-aligned and lint-clean; the identity is always present at rank 0.
  - _Requirements: 1.1, 1.6_

- [x] 2. Implement `solver.solve_placement(spec)` — the outer order-score-commit loop
  - For each PlacementVariant: apply the move, run the full 1.8.0 inner pipeline (place → size → centre → `solve` → repair) to a finished candidate, score it with the shared `route_cost`.
  - Select the argmin over `(RouteCost.as_tuple(), placement_rank, placement_id)`; the base placement is always a candidate.
  - _Requirements: 1.3, 1.4, 5.6_

- [x] 2.1 Write the property test: placement argmin never worse than the base
  - Property 1: `route_cost(solve_placement(spec)) <= route_cost(base)` for every generated layout.
  - _Requirements: 1.4_

- [x] 2.2 Write the property test: placement determinism
  - Property 2: `solve_placement(spec)` twice → byte-identical `.drawio`.
  - _Requirements: 1.5, 5.1_

- [x] 3. Wire the placement loop into the default `layout()`; keep `--legacy`
  - The placement loop is the default; `--legacy` and the 1.8.0 route-only path remain selectable. No lint rule weakened; artifact format unchanged.
  - _Requirements: 1.3, 5.1, 5.2, 5.3_

- [x] 3.1 Regenerate any Shipped_Diagram a move improves; re-baseline the Ratchet
  - Hold or improve `gcp/01` = (4,0) and landscapes = (3,2); tighten the ratchet where improved, never regress. Confirm byte-identity across two runs.
  - _Requirements: 1.7, 5.4_

- [x] 4. Checkpoint A — placement loop in, deterministic, defects held or improved, gates green

## Part B — Inventory → diagram reconciliation gate

- [x] 5. Implement the raw-JSON → role mapper `reconcile.role_of`
  - Map each enumerated resource in a Snapshot's per-domain JSON to a diagram role via `mappings/roles.yaml`; read only committed Snapshot files, never provider state.
  - A resource with no resolvable role is not an omission.
  - _Requirements: 2.1, 2.5, 5 (Decision D5)_

- [x] 6. Implement `rule-engine-reconcile` (CLI + `reconcile.reconcile`)
  - Compare the mapped expected role set against the diagram's drawn node role set; block and name omissions per Coverage_Class (total for `landscape`, scoped for `flow`).
  - _Requirements: 2.2, 2.3, 2.4_

- [x] 6.1 Wire `rule-engine-reconcile` into CI as part of the Gate_Suite
  - _Requirements: 2.6, 5.5_

- [x] 6.2 Write the property/example test: reconciliation catches an omission
  - Property 4: a landscape missing a role-bearing enumerated resource is blocked (names it); a complete diagram passes; an unresolvable-role resource is not flagged.
  - _Requirements: 2.3, 2.5_

- [x] 7. Checkpoint B — reconciliation gate blocks omissions, green on the shipped corpus

## Part C — Container dead-space lint rule

- [x] 8. Measure container area/child-footprint ratios across the shipped corpus
  - Record the distribution; pick a threshold above the sparsest legitimate tier so no Shipped_Diagram false-positives.
  - _Requirements: 3.3_

- [x] 9. Implement `geometry.check_container_dead_space` + the `container-dead-space` rule (WARNING)
  - Advisory on both classes; measured from parsed `.drawio` geometry; never blocks alone.
  - _Requirements: 3.1, 3.2, 3.4_

- [x] 9.1 Record the rule in `diagram-lint.md`; keep the rule-table/code sync test green
  - _Requirements: 3.5, 5.2_

- [x] 9.2 Write the property test: no corpus false-positive at the calibrated threshold
  - Property 5.
  - _Requirements: 3.3_

- [x] 10. Checkpoint C — dead-space rule added, corpus clean, no rule weakened

## Part D — Icon-index slug-collision disambiguation

- [x] 11. Implement a total, deterministic disambiguation order in `asset_index.build_icon_index`
  - SVG over PNG, base over Dark/Light variant, then size, then path tie-break; record the loser under a disambiguated slug rather than shadowing it; drop the collision WARNING.
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [x] 11.1 Rebuild and commit `mappings/icon-index.json`; confirm byte-identical re-run
  - Property 6: re-running on the same packs yields a byte-identical index with no collision WARNING.
  - _Requirements: 4.4_

- [x] 11.2 Write the property test for slug-disambiguation determinism
  - _Requirements: 4.4, 4.5_

- [x] 12. Checkpoint D — collisions resolved deterministically, index stable, roles unaffected

## Part E — Release wrap for 1.9.0

- [x] 13. Bump the version triple to 1.9.0 (`VERSION` via CI, `pyproject.toml`, CHANGELOG heading); keep `version_guard` / `test_version_triple` green
  - _Requirements: 6.1_

- [x] 13.1 Bump the power pins (`plugin.json`, `bootstrap.sh`, workspace-init hook tag) to 1.9.0; keep `test_version_pins` green
  - _Requirements: 6.2_

- [x] 13.2 Write the CHANGELOG 1.9.0 section (all four parts) and mark the four Open gaps Resolved (1.9.0) in `docs/REVIEW.md`
  - _Requirements: 6.3, 6.4_

- [x] 13.3 Keep CI 3.11–3.14 and run the new tests alongside the Gate_Suite
  - _Requirements: 6.5, 5.5_

- [x] 14. Final checkpoint — full suite, Gate_Suite (incl. `rule-engine-reconcile`), and version-triple guard green on 3.11–3.14


## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "5", "8", "11"] },
    { "wave": 2, "tasks": ["1.1", "2", "6", "9", "11.1", "11.2"] },
    { "wave": 3, "tasks": ["2.1", "2.2", "6.1", "6.2", "9.1", "9.2", "12"] },
    { "wave": 4, "tasks": ["3", "7", "10"] },
    { "wave": 5, "tasks": ["3.1"] },
    { "wave": 6, "tasks": ["4"] },
    { "wave": 7, "tasks": ["13"] },
    { "wave": 8, "tasks": ["13.1", "13.2", "13.3"] },
    { "wave": 9, "tasks": ["14"] }
  ]
}
```

An ASCII view of the same dependencies:

```
Part A:  1 → 1.1
         1 → 2 → 2.1
                 2.2
              2 → 3 → 3.1 → 4 (Checkpoint A)
Part B:  5 → 6 → 6.1
                 6.2 → 7 (Checkpoint B)
Part C:  8 → 9 → 9.1
                 9.2 → 10 (Checkpoint C)
Part D:  11 → 11.1
         11 → 11.2 → 12 (Checkpoint D)
Part E:  (after A–D) 13 → 13.1 → 13.2 → 13.3 → 14 (Final checkpoint)
```

- Parts A, B, C, D have no cross-part dependencies and may proceed in parallel.
- Part E (release wrap) depends on Checkpoints A, B, C, and D all being complete.
- Within Part A, task 3 (wire as default) depends on the loop (2) being scored
  and tested (2.1, 2.2); 3.1 (regenerate + re-baseline) depends on 3.

## Notes

- **Determinism is non-negotiable (Req 5.1).** Every new function is a pure,
  deterministic function of its inputs — no randomness, wall-clock, or
  dict-iteration-order dependence — so Shipped_Diagrams stay byte-identical and
  `generator --check` holds.
- **No lint rule weakened (Req 5.2).** Part C only *adds* the advisory
  `container-dead-space` rule; no existing severity changes.
- **Shared objective (Req 5.6).** Part A scores placements with the same
  `geometry.route_cost` the router and ratchet use — no private copy (Decision D3).
- **Read-only reconciliation (Req 2.1, Decision D5).** Part B reads only committed
  Snapshot files; it never touches provider state.
- **Ratchet is tightened, never regressed (Req 5.4).** A placement move that
  improves a diagram updates its recorded ceiling in the same change.
