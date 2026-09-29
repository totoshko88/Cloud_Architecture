# Implementation Plan: Contract ↔ Layout Engine wiring

## Overview

Python. Build in dependency order: first extract the shared assembler from
`draw.py` (no behaviour change, proven by byte-identity of the existing
`rule-engine-draw` output), then re-point the Contract's diagram step onto
`layout()`, then record the decision and update the docs. Test sub-tasks marked
`*` are optional-but-recommended; property tests name their design property.

## Tasks

- [ ] 1. Extract the shared Snapshot → DiagramSpec assembler
  - [ ] 1.1 Lift the role-resolve-and-lane logic out of `draw.py` into an
        importable `assemble_spec(resources, profile, diagram_class)`, leaving
        `draw.py` as a thin caller.
    - _Requirements: 2.1_
  - [ ] 1.2 *Assert `rule-engine-draw` output is byte-identical before/after the
        extraction (the existing `test_draw_e2e.py` corpus).
    - _Requirements: 2.2, 3.1_

- [ ] 2. Re-point the Contract's diagram step onto the Layout Engine
  - [ ] 2.1 Replace the coordinate-free node-set emit with: call
        `assemble_spec(...)`, run `layout()`, serialize with `build_diagram()`
        using the `PlacedDiagram` coordinates.
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 2.2 Keep the fail-closed contract: an invalid `DiagramSpec` raises
        `ContractGenerationError` naming the field, no partial artifact.
    - _Requirements: 1.5_
  - [ ] 2.3 *Property test — no caller coordinates
    - **Property 1: every node x/y and edge waypoint in the output equals the
      value layout() assigned; the Contract sets none.**
    - **Validates: Requirements 1.2, 1.3**
  - [ ] 2.4 *Property test — lint-clean placement
    - **Property 4: the Contract .drawio has zero CRITICAL/ERROR findings
      including edge-direction, entry-thirds, node-overlap, container-padding.**
    - **Validates: Requirements 1.4, 3.2**

- [ ] 3. Prove parity and determinism
  - [ ] 3.1 *Property test — assembler parity
    - **Property 2: for every Snapshot S and class C, the Contract's DiagramSpec
      equals rule-engine-draw's for (S, C).**
    - **Validates: Requirements 2.1, 2.2**
  - [ ] 3.2 *Property test — determinism
    - **Property 3: two Contract runs on identical input produce byte-identical
      .drawio.**
    - **Validates: Requirement 3.1**
  - [ ] 3.3 Regression: assert every committed `examples/` `.drawio` is unchanged
        (or review each deliberate diff); confirm reconcile still blocks a
        silent landscape omission through the shared assembler.
    - _Requirements: 2.3, 3.2, 3.3_

- [ ] 4. Record the decision and update docs
  - [ ] 4.1 Decide: retain the legacy `build_diagram()`-with-manual-coordinates
        path behind an explicit flag, or remove it once `layout()` is default;
        record it in `docs/REVIEW.md` under a new stable finding code.
    - _Requirements: 4.1_
  - [ ] 4.2 Update `docs/ARCHITECTURE.md` so the Layout Engine row no longer says
        "`contract.py` does not use it yet".
    - _Requirements: 4.2_
  - [ ] 4.3 Mark the `docs/REVIEW.md` "Open gaps" Layout-Engine-wiring item
        Resolved with its release.
    - _Requirements: 4.3_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3"] }
  ]
}
```
