# Changelog

All notable changes to the Rule Engine are recorded here, per released version, in
reverse chronological order.

## [1.1.0] - 2026-09-22

Diagram routing quality, an official-asset icon fallback, and the steering rules
that codify both.

### Added

- **Asset Index & Icon Fallback** (`src/rule_engine/asset_index.py`, CLI
  `rule-engine-index-assets`): indexes the official provider icon packs (AWS,
  Azure, GCP SVG/PNG; OCI draw.io library) and resolves a specific service name
  to a built-in stencil, else an official SVG/PNG, else a fail-honest
  `unresolved`. This covers services with no built-in stencil yet — for example
  AWS DevOps / FinOps / Security agents — which now resolve to their official
  SVGs.
- New steering document `.kiro/steering/asset-packs.md`: official pack sources,
  per-provider layouts, and the built-in → official-asset → unresolved order.
- Diagram-standards additions: **Edge Routing** now requires grid-step-separated
  parallel runs (no shared corridors), no edge–node / edge–label crossings, and
  a **Container Padding** rule (≥ 1 grid step around child nodes). Two advisory
  WARNING lint rules were added: `container-padding` (and the extended
  `edge-routing`).
- Edge Routing additions distilled from the AWS golden example: a **shared
  trunk with branches in opposite directions** for fan-out from one node
  (fewer crossings and corners than several near-parallel detours), and a
  **clean arrow start** convention (`exitPerimeter=0`, exit just past the source
  perimeter) so arrow stubs do not bite into the icon glyph.

### Changed

- Redrew the AWS, Azure, and GCP golden-example diagrams to remove line
  overlaps and edge–icon crossings: each fan-out edge now uses its own
  grid-aligned corridor with explicit waypoints, the right-side Flow/Legend
  blocks sit clear of the diagram body, and Network Boundary containers pad away
  from their child services. Regenerated all example PNGs.

### Removed

- _None recorded for this release._

## [1.0.0] - 2026-09-22

First public release of the Diagram & Inventory Rule Engine — a cloud-agnostic Kiro
project that deterministically produces architecture diagrams and inventory documents
across five provider profiles (`aws`, `azure`, `gcp`, `oci`, and a vendor-neutral
`generic` fallback).

### Added

- Provider-neutral core components under `src/rule_engine/`: Linter, Icon Resolver,
  Inventory Collector, Normalizer, Delta Engine, schema validator, and version guard.
- Five always-on steering documents in `.kiro/steering/`: `diagram-standards.md`,
  `inventory-standards.md`, `provider-profiles.md`, `kb-frontmatter.md`, and the
  authoritative `diagram-lint.md` ruleset.
- Two console entry points: `rule-engine-lint` and `rule-engine-validate-schema`, wired
  into the `lint-on-save` / `validate-on-task` hooks and the CI pipeline.
- Per-provider icon/shape mapping files under `mappings/` and the Normalized Resource
  JSON Schema at `schemas/inventory.schema.json`.
- One golden example per provider under `examples/` (`aws`, `azure`, `gcp`, `oci`,
  `generic`) plus a cross-cloud C4 composition, each shipping the full artifact triple
  (`.drawio`/`.puml` source, exported `.png`, and `.diagram.md` companion document).
- Exported raster images (`.png`) for every golden example, generated locally the same
  way the CI build stage packages them.
- Numbered flow markers on diagram edges with a right-side `Flow` legend, and an
  explicit edge-routing convention (orthogonal routing; entries left/top, exits
  right/bottom; distinct contact points when a node side carries more than one edge).
  Two advisory WARNING lint rules back this up: `flow-legend` and `edge-routing`.
- `.github/FUNDING.yml` sponsorship configuration.

### Changed

- Corrected the AWS `managed_k8s` (Amazon EKS) icon id from
  `mxgraph.aws4.elastic_kubernetes_service` to the resolvable `mxgraph.aws4.eks`, in
  `mappings/aws-icons.yaml` and the seed inventory in `src/rule_engine/assets/enumerate.py`.
- Rebuilt every golden-example diagram to the current diagram standards: resolvable
  provider stencils, numbered flow markers, orthogonal non-overlapping edge routing, and
  a right-side Flow legend. Set the reference date across all examples and the
  add-a-provider runbook to `2026-09-22`.
- Extended `diagram-standards.md` (Numbered Flow Legend, Edge Routing) and
  `diagram-lint.md` (the `flow-legend` and `edge-routing` rules).

### Removed

- _None recorded for this release._
