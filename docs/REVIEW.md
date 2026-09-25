# Architecture Review — Findings Register

This is the register of findings from the architecture review of the Rule Engine.
Each finding has a stable code (`C*` correctness, `D*` diagram-standard, `U*`
uniqueness/duplication, `G*` governance) so that code comments, CI steps, and
steering docs can cite the exact item. Codes are permanent once assigned; a
resolved finding keeps its code and is marked **Resolved** rather than deleted,
so the citations scattered through the codebase stay meaningful.

Status legend: **Resolved** — fixed and regression-tested; **Open** — a known,
documented gap that does not block publication.

## Correctness (C)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| C1 | Terminology was hard-coded in several modules instead of one source. Consolidated into `profiles/terminology.yaml`, read via `rule_engine.constants`. | Resolved | `constants.py`, `tests/test_terminology_source.py` |
| C2 | `icon-resolved` must fire on a real placeholder style, not merely a missing id. Unresolved-style markers are matched explicitly. | Resolved | `cli.py`, `tests/test_cli_drawio_parser.py` |
| C3 | Inventory Snapshot JSON must be routed through the `secret-safety` CRITICAL gate; a snapshot must record metadata only. | Resolved | `cli.py`, `collector.py`, `tests/test_review_fixes.py` |
| C4 | An AWS group container must not be counted as a node. Container detection is shared by the parser and the geometry model so it cannot drift. | Resolved | `constants.is_boundary_container_style`, `geometry.py`, `cli.py` |

## Diagram standards (D)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| D1 | On-diagram text below the 12px accessibility floor. Enforced by `min-font-size`. | Resolved | `cli.py`, `linter.py` |
| D2 / D3 / D6 | Geometry-aware layout rules (grid alignment, container padding, node overlap, edge routing) evaluated from the parsed `.drawio`. | Resolved | `linter.py`, `geometry.py` |
| D4 | Directional edge contract (exit right/bottom, enter left/top). Enforced by `edge-direction`. | Resolved | `geometry.check_edge_direction` |
| D5 | Arrow style — open heads, ≥ 1pt stroke. Enforced by `arrow-style`. | Resolved | `geometry.py`, `linter.py` |
| D7 | Class-aware raster budget (flow ≤ 1600px / < 500KB, landscape ≤ 3600px / < 2MB), enforced by the raster gate, not the linter. | Resolved | `raster_gate.py`, CI |

## Uniqueness / duplication (U)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| U1 | Duplicated provider/type enums across modules. Collapsed into `rule_engine.constants` as the single declaration. | Resolved | `constants.py` |
| U2 | Duplicated secret-marker vocabulary. Single shared list consumed by the linter's content scan and the collector's redaction. | Resolved | `constants.SECRET_MARKERS`, `linter.py`, `collector.py` |

## Governance (G)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| G3 | Test/dev tooling must not be a runtime dependency of the engine. Kept in the `dev` extra. | Resolved | `pyproject.toml` |

## Open gaps

These are documented and accepted; they do not block publication.

- **No North–South (infrastructure/deployment) golden example.** All four
  shipped golden examples are left→right flow layouts. The North–South
  reference geometry is specified in `diagram-standards.md`, and the
  geometry-enforced lint rules are orientation-agnostic (they measure absolute
  coordinates), but no infrastructure-axis golden example ships yet. Referenced
  from `.kiro/steering/diagram-standards.md`.
- **Icon-index slug collisions are reported, not resolved.** When two distinct
  vendor icons normalize to one slug (e.g. AWS `Database … Light`/`Dark`, Azure
  `Groups`/`Service Groups`), the icon-set builder keeps last-writer-wins and
  emits a WARNING rather than disambiguating. The engine's own roles are
  unaffected; the warning surfaces the shadowing for a future mapping edit.
