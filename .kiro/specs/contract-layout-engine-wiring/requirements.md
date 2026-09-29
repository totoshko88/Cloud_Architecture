# Requirements Document

## Introduction

The Rule Engine Contract (`contract.py`) is the high-level orchestrator that an
agent calls to produce the artifact triple from validated inputs. Today its
diagram path emits **a set of resolved nodes with no relationship information** —
it does not place nodes on the shared grid, size their containers, or route
edges. That work lives in the Layout Engine (`layout()` in
`rule_engine.layout.pipeline`), which turns a coordinate-free `DiagramSpec` into
a placed, container-sized, edge-routed `PlacedDiagram` and is already exercised
by two consumers: the HA example generators (`scripts/build_*_ha_example.py` via
`ha_multiregion_spec.py`) and the `rule-engine-draw` snapshot autogenerator
(`draw.py`, spec `provider-diagram-conventions` item J). `docs/ARCHITECTURE.md`
records the gap explicitly: "Today it drives the HA example generators;
`contract.py` does not use it yet — wiring an inventory snapshot through it is
planned work."

This feature closes that gap: the Contract's diagram generation SHALL delegate
placement and routing to the Layout Engine through the same `DiagramSpec` →
`layout()` → `build_diagram()` pipeline the autogenerator uses, so a diagram
produced by the Contract is placed and routed to the same standard as a
hand-authored golden — not a coordinate-free node set — and passes the same
geometry lint rules (`edge-direction`, `entry-thirds`, `node-overlap`,
`container-padding`) without manual coordinate authoring.

Primary outputs:

- A Contract diagram path that produces a lint-clean, geometry-conformant
  `.drawio` via the Layout Engine, with no hand-set node coordinates.
- A single shared Snapshot → `DiagramSpec` assembly reused by both the Contract
  and `rule-engine-draw` (no second copy of the role-resolve-and-lane logic).
- A decision, recorded in `docs/REVIEW.md`, on whether the Contract's legacy
  low-level `diagram_layout.build_diagram()` node-set path is retained behind a
  flag or removed once the Layout Engine path is the default.

## Glossary

- **Rule Engine Contract**: `contract.py`; validates inputs, orchestrates the
  core components, and returns the artifact set (or a blocking error).
- **Layout Engine**: `layout()` in `rule_engine.layout.pipeline`; maps a
  `DiagramSpec` to a `PlacedDiagram` with placed nodes, sized containers, and
  routed edges, checked by a geometry oracle.
- **DiagramSpec**: the coordinate-free diagram description
  (`rule_engine.layout.model.DiagramSpec`) — nodes, edges, containers, lane
  order, and diagram class, with no `x`/`y` or waypoints.
- **PlacedDiagram**: the Layout Engine output — every node placed, every
  container sized, every edge routed.
- **build_diagram()**: the low-level `.drawio` serializer in
  `diagram_layout.py`; the caller supplies every node `x`/`y` and edge waypoint.
- **rule-engine-draw**: the Snapshot → triple autogenerator (`draw.py`,
  `draw_cli.py`) that already assembles a `DiagramSpec` from a Snapshot and runs
  it through `layout()` + `build_diagram()`.
- **Snapshot**: a committed, read-only inventory folder
  (`inventory-<provider>-<boundary>-<region>-<timestamp>`), one JSON per service
  domain plus per-resource subfolders.
- **Diagram class**: `flow` (≤ 12 nodes, summary) or `landscape` (as-built,
  relaxed node cap), governing node-count severity and the pair contract.

## Requirements

### Requirement 1: Contract diagram placement via the Layout Engine

**User Story:** As an agent calling the Contract, I want the diagram it returns
to be fully placed and routed, so that I do not author node coordinates by hand
and the result passes the geometry lint rules on the first try.

#### Acceptance Criteria

1. WHEN the Contract generates a diagram from validated inputs, THE Rule Engine
   Contract SHALL assemble a coordinate-free `DiagramSpec` and obtain placement
   and routing from `layout()`, not from caller-supplied coordinates.
2. THE Rule Engine Contract SHALL NOT set any node `x`/`y` or edge waypoint
   directly; every coordinate SHALL originate from the `PlacedDiagram` returned
   by `layout()`.
3. WHEN the Contract serializes the placed diagram, THE Rule Engine Contract
   SHALL call `build_diagram()` with the coordinates from the `PlacedDiagram`.
4. THE `.drawio` produced by the Contract path SHALL lint clean (zero CRITICAL,
   zero ERROR) under the authoritative `diagram-lint.md` ruleset, including the
   geometry rules `edge-direction`, `entry-thirds`, `node-overlap`, and
   `container-padding`.
5. IF the assembled `DiagramSpec` is invalid, THEN THE Rule Engine Contract
   SHALL raise `ContractGenerationError` naming the offending field, and SHALL
   produce no partial artifact (fail-closed, unchanged from the current
   contract).

### Requirement 2: One shared Snapshot → DiagramSpec assembly

**User Story:** As a maintainer, I want a single Snapshot → `DiagramSpec`
assembler shared by the Contract and `rule-engine-draw`, so that the
role-resolve-and-lane logic does not drift between two copies (a G6-class
duplication risk).

#### Acceptance Criteria

1. THE Snapshot → `DiagramSpec` assembly (role-resolve every enumerated resource
   via `reconcile.role_of`, assign a lane via `draw.lane_of`, emit the
   coordinate-free `DiagramSpec`) SHALL exist as one importable unit consumed by
   both the Contract path and `rule-engine-draw`.
2. WHEN the Contract generates a diagram from a committed Snapshot, THE Rule
   Engine Contract SHALL produce a `DiagramSpec` byte-identical to the one
   `rule-engine-draw` produces from the same Snapshot and diagram class.
3. IF an enumerated, role-bearing resource is absent from the assembled
   `DiagramSpec` for a `landscape`, THEN the reconciliation gate
   (`rule-engine-reconcile`) SHALL block, unchanged (Requirement G7).

### Requirement 3: Determinism and parity with existing goldens

**User Story:** As a reviewer, I want the Layout-Engine-backed Contract path to
stay deterministic and not regress the shipped goldens, so that the same inputs
still yield the same reviewable artifact.

#### Acceptance Criteria

1. WHEN the Contract generates a diagram twice from identical inputs, THE Rule
   Engine Contract SHALL produce byte-identical `.drawio` output.
2. THE change SHALL NOT weaken any lint rule, raster budget, or gate; every
   shipped `examples/` artifact SHALL remain publishable (zero CRITICAL, zero
   ERROR) and within its class raster budget.
3. WHERE the Contract previously produced a coordinate-free node set for an
   input with no relationship information, THE Rule Engine Contract SHALL place
   those nodes by lane order via `layout()` and connect them per the assembled
   `DiagramSpec`.

### Requirement 4: Recorded decision on the legacy node-set path

**User Story:** As a maintainer, I want a recorded decision on the fate of the
Contract's legacy low-level path, so that a future reader is not left with two
undocumented diagram paths.

#### Acceptance Criteria

1. THE feature SHALL record, in `docs/REVIEW.md` under a stable finding code,
   whether the Contract's legacy `build_diagram()`-with-manual-coordinates path
   is retained behind an explicit flag or removed once `layout()` is the
   default.
2. WHERE the legacy path is retained, THE `docs/ARCHITECTURE.md` note that
   "`contract.py` does not use [the Layout Engine] yet" SHALL be updated to state
   that the Contract now uses the Layout Engine by default.
3. THE `docs/REVIEW.md` "Open gaps" section SHALL be updated so the
   "wiring an inventory snapshot through [the Layout Engine] is planned work"
   gap is marked Resolved with its release.
