# Changelog

All notable changes to the Rule Engine are recorded here, per released version, in reverse chronological order.

## [1.1.0] - 2026-09-22

Diagram routing quality, an official-asset icon fallback, the steering rules that codify both, and a diagram-rules review pass (REVIEW.md findings D1–D7): accessibility, a real geometry model, and layout-quality lint enforcement.

### Added

- **Asset Index & Icon Fallback** (`src/rule_engine/asset_index.py`, CLI `rule-engine-index-assets`): indexes the official provider icon packs (AWS, Azure, GCP SVG/PNG; OCI draw.io library) and resolves a specific service name to a built-in stencil, else an official SVG/PNG, else a fail-honest `unresolved`. This covers services with no built-in stencil yet — for example AWS DevOps / FinOps / Security agents — which now resolve to their official SVGs.
- New steering document `.kiro/steering/asset-packs.md`: official pack sources, per-provider layouts, and the built-in → official-asset → unresolved order.
- Diagram-standards additions: **Edge Routing** now requires grid-step-separated parallel runs (no shared corridors), no edge–node / edge–label crossings, and a **Container Padding** rule (≥ 1 grid step around child nodes).
- Edge Routing additions distilled from the AWS golden example: a **shared trunk with branches in opposite directions** for fan-out from one node (fewer crossings and corners than several near-parallel detours), and a **clean arrow start** convention (`exitPerimeter=0`, exit just past the source perimeter) so arrow stubs do not bite into the icon glyph.
- **Diagram geometry model** (`src/rule_engine/geometry.py`, REVIEW.md D3/D6): the CLI `.drawio` parser now builds absolute-coordinate node/container boxes and edge contact points/waypoints and attaches them to the linted artifact, so layout rules evaluate the real file instead of being prose-only.
- **Geometry-enforced lint rules** (all WARNING): `grid-alignment` (node origins are grid multiples, D2), `node-overlap` (no overlapping icon boxes), `arrow-style` (D5: flags filled/heavy arrowheads, unspecified heads that default to filled, and sub-1pt strokes), plus real implementations of `container-padding` and `edge-routing` — previously documented but never evaluated on a file. `edge-routing` is deliberately conservative (flags non-orthogonal edges and waypoint-free edges that run straight through an unrelated node; edges with explicit waypoints are treated as deliberately routed) to avoid false positives on validly routed diagrams. Regression tests in `tests/test_review_fixes.py` cover both the clean golden examples and firing cases.
- `min-font-size`** lint rule** (WARNING, REVIEW.md D1): flags any diagram whose parsed `fontSize=<n>` tokens fall below the 12px accessibility floor; the CLI parser harvests `font_sizes`. `flow-legend` advisory rule backs the numbered-flow legend.
- New steering section **Accessibility & Contrast** (REVIEW.md D1) in `.kiro/steering/diagram-standards.md`: 12px minimum font, ≥ 4.5:1 text/line contrast, defined white background, never-color-alone (double-encode), and line/arrow weight guidance. Documented as the `min-font-size` / `arrow-style` rules in `diagram-lint.md`.
- New steering section **Diagram Orientation** (REVIEW.md D4): picks the layout axis deterministically by diagram type — **North–South** (external/users at top, internal at bottom; East–West for AZ redundancy) for infrastructure/network/deployment, **left→right** for flow/application. The Lane Order is now axis-aware. Authoring guidance (not lint-enforced: node external/internal role is not inferable from geometry).
- New steering section **Raster Export Dimensions** (REVIEW.md D7): the exported `.drawio.png` budget — ≤ 1200px wide, legible at 700px, < 500KB, 72–96 DPI, white background, 8px padding — and directs oversize diagrams to be split. Authoring guidance (the linter checks source + companion, not the rendered PNG); a CI raster gate is the suggested enforcement point.
- Numbered flow markers on diagram edges with a right-side `Flow` legend, and an explicit edge-routing convention (orthogonal routing; entries left/top, exits right/bottom; distinct contact points when a node side carries more than one edge).
- `rule_engine.diagram_layout.MIN_FONT_SIZE` (= 12) and `EDGE_STROKE_WIDTH` (= 1.5) as the single numeric sources for label/text font size and edge stroke width.

### Changed

- Redrew the AWS, Azure, and GCP golden-example diagrams to remove line overlaps and edge–icon crossings: each fan-out edge now uses its own grid-aligned corridor with explicit waypoints, the right-side Flow/Legend blocks sit clear of the diagram body, and Network Boundary containers pad away from their child services.
- Corrected the AWS `managed_k8s` (Amazon EKS) icon id from `mxgraph.aws4.elastic_kubernetes_service` to the resolvable `mxgraph.aws4.eks`.
- **Accessibility (D1):** raised node-label and legend/text font size from 11 to 12 across the shared layout builder, all five `mappings/<provider>-icons.yaml` style strings, and the AWS/Azure/GCP/OCI golden-example `.drawio` sources, so every generated and reference diagram clears the 12px floor.
- **Arrow & line style (D5):** the shared builder now draws edges with an **open** arrowhead (`endArrow=open;endFill=0`) and a 1.5pt stroke (`EDGE_STROKE_WIDTH`); all four golden-example `.drawio` sources updated to match (33 edges).
- **Grid rhythm wording (D2):** Layout Geometry now states column step 220 and row step 160 as the reference rhythm, with the `grid-alignment` rule enforcing grid-multiple node origins (individual rows may differ but stay on the grid).

### Removed

- *None recorded for this release.*

> Note: the golden-example `.drawio.png` rasters were not regenerated after the D1 (font 11 → 12) and D5 (open arrowheads) source edits — that needs a draw.io export step. The `.drawio` sources are current; re-export the PNGs so the rasters match, and add a CI raster gate to enforce the D7 export budget.

## [1.0.0] - 2026-09-22

First public release of the Diagram & Inventory Rule Engine — a cloud-agnostic Kiro project that deterministically produces architecture diagrams and inventory documents across five provider profiles (`aws`, `azure`, `gcp`, `oci`, and a vendor-neutral `generic` fallback).

### Added

- Provider-neutral core components under `src/rule_engine/`: Linter, Icon Resolver, Inventory Collector, Normalizer, Delta Engine, schema validator, and version guard.
- Five always-on steering documents in `.kiro/steering/`: `diagram-standards.md`, `inventory-standards.md`, `provider-profiles.md`, `kb-frontmatter.md`, and the authoritative `diagram-lint.md` ruleset.
- Two console entry points: `rule-engine-lint` and `rule-engine-validate-schema`, wired into the `lint-on-save` / `validate-on-task` hooks and the CI pipeline.
- Per-provider icon/shape mapping files under `mappings/` and the Normalized Resource JSON Schema at `schemas/inventory.schema.json`.
- One golden example per provider under `examples/` (`aws`, `azure`, `gcp`, `oci`, `generic`) plus a cross-cloud C4 composition, each shipping the full artifact triple (`.drawio`/`.puml` source, exported `.png`, and `.diagram.md` companion document).
- Exported raster images (`.png`) for every golden example, generated locally the same way the CI build stage packages them.
- Numbered flow markers on diagram edges with a right-side `Flow` legend, and an explicit edge-routing convention (orthogonal routing; entries left/top, exits right/bottom; distinct contact points when a node side carries more than one edge). Two advisory WARNING lint rules back this up: `flow-legend` and `edge-routing`.
- `.github/FUNDING.yml` sponsorship configuration.

### Changed

- Rebuilt every golden-example diagram to the current diagram standards: resolvable provider stencils, numbered flow markers, orthogonal non-overlapping edge routing, and a right-side Flow legend. Set the reference date across all examples and the add-a-provider runbook to `2026-09-22`.
- Extended `diagram-standards.md` (Numbered Flow Legend, Edge Routing) and `diagram-lint.md` (the `flow-legend` and `edge-routing` rules).

### Removed

- *None recorded for this release.*

