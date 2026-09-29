# Architecture Review — Findings Register

This is the register of findings from the architecture review of the Rule Engine.
Each finding has a stable code (`C*` correctness, `D*` diagram-standard, `U*`
uniqueness/duplication, `G*` governance) so that code comments, CI steps, and
steering docs can cite the exact item. Codes are permanent once assigned; a
resolved finding keeps its code and is marked **Resolved** rather than deleted,
so the citations scattered through the codebase stay meaningful.

Status legend: **Resolved** — fixed and regression-tested; **Scheduled** — a
gap with an approved spec targeting a named release; **Open** — a known,
documented gap that does not block publication.

## Correctness (C)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| C1 | Terminology was hard-coded in several modules instead of one source. Consolidated into `profiles/terminology.yaml`, read via `rule_engine.constants`. | Resolved | `constants.py`, `tests/test_terminology_source.py` |
| C2 | `icon-resolved` must fire on a real placeholder style, not merely a missing id. Unresolved-style markers are matched explicitly. | Resolved | `cli.py`, `tests/test_cli_drawio_parser.py` |
| C3 | Inventory Snapshot JSON must be routed through the `secret-safety` CRITICAL gate; a snapshot must record metadata only. | Resolved | `cli.py`, `collector.py`, `tests/test_review_fixes.py` |
| C4 | An AWS group container must not be counted as a node. Container detection is shared by the parser and the geometry model so it cannot drift. | Resolved | `constants.is_boundary_container_style`, `geometry.py`, `cli.py` |
| C5 | **Routing was rule-driven with no feedback loop.** The ten sequential global contact passes had no per-edge decision point, so two patterns wanting the same plane could not be scored against each other. Routing is now inverted into a most-constrained-first order-score-commit solver over sanctioned per-edge variants, scored by the shared graded `route_cost` (allocator snapshot/restore per trial, deterministic argmin); the scored router is the default and the `--legacy` ten-pass path is retained. | Resolved (1.8.0) | `layout/solver.py`, `layout/variants.py`, `layout/pipeline.py`, `tests/test_solver_properties.py` |
| C6 | **Placement was fixed while routing was scored (1.8.0, D2).** The scored per-edge router reached hand-route quality on every *routing* choice but scored routes only, so two rails and three crossings on the landscapes / `gcp/01` were held unchanged — placement defects surfacing as routing ones. Routing is now scored over a placement loop: `solve_placement` runs the full 1.8.0 inner pipeline for each sanctioned `PlacementVariant` (`widen-gap` / `shift-neighbour` / `reorder-tier`, identity always rank 0) and keeps the argmin under `(RouteCost.as_tuple(), rank, id)`; the placement loop is the default `layout()`, `--legacy` retained, ratchet re-baselined tighter (widen-gap improves the landscapes; `gcp/01` held). | Resolved (1.9.0) | `layout/solver.solve_placement`, `layout/variants.generate_placement_variants`, `layout/pipeline.py`, `tests/test_placement_properties.py` |

## Diagram standards (D)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| D1 | On-diagram text below the 12px accessibility floor. Enforced by `min-font-size`. | Resolved | `cli.py`, `linter.py` |
| D2 / D3 / D6 | Geometry-aware layout rules (grid alignment, container padding, node overlap, edge routing) evaluated from the parsed `.drawio`. | Resolved | `linter.py`, `geometry.py` |
| D4 | Directional edge contract (exit right/bottom, enter left/top). Enforced by `edge-direction`. | Resolved | `geometry.check_edge_direction` |
| D5 | Arrow style — open heads, ≥ 1pt stroke. Enforced by `arrow-style`. | Resolved | `geometry.py`, `linter.py` |
| D7 | Class-aware raster budget (flow ≤ 1600px / < 500KB, landscape ≤ 3600px / < 2MB), enforced by the raster gate, not the linter. | Resolved | `raster_gate.py`, CI |
| D8 | **Edge-less nodes.** Every HA landscape drew 34 nodes joined by 12 edges, leaving 20 unconnected — the engine drew an inventory, not an architecture. Now enforced by `node-connectivity`, with the landscapes re-connected (21 edges) and the passive region's mirror peers marked `standby`. | Resolved | `geometry.check_node_connectivity`, `ha_multiregion_spec.py`, `tests/test_new_rules_1_6_0.py` |
| D9 | **North–South infrastructure golden example.** The N–S axis was specified but unregressed: no shipped golden exercised it, nor an external actor / on-premises boundary outside the cloud, nor peer AZ containers. | Resolved | `examples/aws/03-aws-hybrid-infrastructure.*`, `scripts/build_aws_infra_example.py` |
| D10 | **Directional contract read the half-plane, not the face.** `exitX >= 0.5` admitted the top-*centre* point, so an edge leaving the top of its own glyph linted clean (and the mirror on the entry side). `check_edge_direction` now classifies the contact face. | Resolved | `geometry.contact_faces`, `geometry.check_edge_direction` |
| D11 | **Flow/Legend placement unenforced.** The furniture belongs in the right margin; a clean-room diagram parked both blocks in the left margin and linted clean. Now `legend-placement`. | Resolved | `geometry.check_legend_placement`, `linter.py` |
| D12 | **`flow-legend` documented but not implemented.** Specified from the first ruleset; the generator always emitted the Flow cell, so the missing check only bit hand-authored diagrams. | Resolved | `linter._check_flow_legend`, `cli._parse_flow_legend_lines` |
| D13 | **Container caption strip.** A group's caption is drawn inside its own top edge, so a uniform pad left no corridor lane above the first content row and descending edges ran through the caption. Top padding now reserves the strip. | Resolved | `layout_engine.size_containers`, `layout_engine._caption_free_band` |
| D14 | **Rails metric was binary where it should be graded.** `route_cost` scored a run at 39px and one at 2px identically, so real clearance improvements registered as no change. `RouteCost` now carries a graded `rail_penalty` (inversely proportional to clearance, `0` at/above `RAIL_CLEARANCE`=40px), `as_tuple()` orders crossings ≫ rail_penalty ≫ turns ≫ ink, and the ratchet was re-baselined. | Resolved (1.8.0) | `geometry.rail_penalty`, `geometry.RouteCost`, `tests/test_route_cost_properties.py` |
| D15 | **Container dead space was unmeasured.** `container-padding` checks the *minimum* clearance; nothing flagged the opposite defect, a container sized far larger than its children (a clean-room VPC was 840×460 around four nodes in one row). The advisory `container-dead-space` rule (WARNING both classes) now flags a Boundary container whose area exceeds the summed child footprint-plus-padding demand by more than a calibrated ratio, measured across the corpus first: threshold `DEAD_SPACE_RATIO` = 5.0, above the sparsest legitimate tier (~4.536), so 0 of 57 shipped containers false-positive; a childless container is skipped. | Resolved (1.9.0) | `geometry.check_container_dead_space`, `linter.py`, `tests/test_dead_space_properties.py` |
| D16 | **Nested-stencil glyph rendered off-centre from its label.** An OCI stencil that wraps its glyph in an intermediate offset group (`object-storage` — the visible "model-storage" shift — and `cdn`) had its glyph bounding box measured in each cell's LOCAL frame, so the wrapper group's ~14px offset was not accumulated into the centering pad. The glyph rendered ~14px right of the node's 78px box while the bottom label (anchored to that box) centred at 39px — a visible caption shift on every OCI diagram carrying those slugs. `embed_oci_stencil` now accumulates every ancestor group's offset into a root-frame origin before taking the bbox, so the pad centres the glyph for a flat OR a nested stencil; flat stencils are unaffected (the accumulation is a no-op). | Resolved (1.10.3) | `diagram_layout.embed_oci_stencil`, `tests/test_diagram_layout.py::test_nested_stencil_glyph_is_centered_in_box` |
| D17 | **OCI diagrams followed only the icons, not the v24.2 styling system.** The OCI Style Guide for draw.io ships two reference `.drawio` files (Toolkit + Read-ME) whose Physical templates define a nested neutral-grey nesting system — Tenancy/Compartment (dashed, terracotta `#AE562C`) ⊃ OCI Region (fill `#F5F4F2`, neutral `#9E9892` stroke, rounded) ⊃ Availability Domain (fill `#DFDCD8`) ⊃ Fault Domain (fill `#FCFBFA`, italic) ⊃ Subnet (dashed terracotta), every level `fontFamily=Oracle Sans` + `fontColor=#312D2A`. The engine had collapsed all of this to one flat all-red style (`#F80000`/`#C74634` stroke AND red text on every container), and the two example builders hardcoded the red palette (the genai-stack even used generic green/blue boundary strokes). Now: `mappings/oci-icons.yaml` carries the canonical per-level palette (with new `region`/`availability_domain`/`fault_domain`/`subnet` container kinds), `CONTAINER_KINDS` gains those optional levels while `REQUIRED_CONTAINER_KINDS` keeps the mandatory `boundary`+`network_boundary` pair, `draw_cli._container_style` maps `az`→`availability_domain` (falling back to `network_boundary` for providers that declare no level style, so aws/azure/gcp/generic are unchanged), and both OCI builders resolve their container styles from the mapping instead of hardcoding. Node captions switched from red to `Oracle Sans` + `#312D2A`. Source-guarded by two mapping tests (no legacy red; canonical stroke/fill per level; Oracle Sans captions). | Resolved (1.10.3) | `mappings/oci-icons.yaml`, `constants.CONTAINER_KINDS`/`REQUIRED_CONTAINER_KINDS`, `draw_cli._container_style`, `scripts/build_oci_example.py`, `scripts/build_oci_ha_example.py`, `tests/test_mappings.py` |

## Uniqueness / duplication (U)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| U1 | Duplicated provider/type enums across modules. Collapsed into `rule_engine.constants` as the single declaration. | Resolved | `constants.py` |
| U2 | Duplicated secret-marker vocabulary. Single shared list consumed by the linter's content scan and the collector's redaction. | Resolved | `constants.SECRET_MARKERS`, `linter.py`, `collector.py` |
| U3 | **Icon-index slug collisions were reported, not resolved.** When two distinct vendor icons normalized to one slug (e.g. AWS `Database … Light`/`Dark`, Azure `Groups`/`Service Groups`), the builder kept last-writer-wins and emitted a WARNING. `build_icon_index` now disambiguates by a total, deterministic order (SVG over PNG, base over Dark/Light, then size, then a path tie-break): the winner keeps the bare slug, the loser is recorded under `<slug>--<disambiguator>` rather than shadowed, no collision WARNING is emitted, and the index is byte-stable across re-runs. Role resolution is unaffected. | Resolved (1.9.0) | `asset_index.build_icon_index`, `tests/test_slug_disambiguation_properties.py` |

## Governance (G)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| G3 | Test/dev tooling must not be a runtime dependency of the engine. Kept in the `dev` extra. | Resolved | `pyproject.toml` |
| G4 | **Snapshot folder shape unchecked.** The linter checks snapshot file *content* (frontmatter, secret-safety) but nothing checked the folder: a hand-written snapshot shipped with an empty `resources/` and a wrong `file_count` and linted clean. Now the snapshot gate, wired into both CI pipelines. | Resolved | `snapshot_gate.py`, `scripts/build_example_snapshots.py`, CI |
| G5 | **Version recorded in three places, drifting.** `VERSION`, `pyproject.toml`, and the newest `CHANGELOG.md` heading disagreed at 1.5.4; CI rewrites `VERSION` at tag time, so nothing surfaced it. Now a checked contract. | Resolved | `version_guard.assert_version_triple_consistent`, `tests/test_version_triple.py` |
| G6 | **Duplicated artifacts drifting unguarded.** The `.kiro/skills` and Power `SKILL.md` copies had diverged across four wording hunks, and `powers/…/plugin.json` sat at 1.0.0 through nine engine releases. A clean-room install also received the steering rules but none of the three agents that apply them. | Resolved | `build_backend._PAYLOAD` (`.kiro/agents`), `tests/test_bootstrap_payload_sync.py` |
| G7 | **Inventory → diagram reconciliation was prose, not a gate.** `diagram-standards.md` requires every enumerated, role-resolvable resource to appear on the diagram, and the snapshot gate checks the snapshot's own shape, but nothing compared the two: a clean-room diagram omitted the ten KMS keys its `secrets.json` enumerated while its companion asserted completeness. The `rule-engine-reconcile` gate now maps each enumerated resource to its role (`reconcile.role_of`, reading only committed Snapshot JSON, never provider state) and blocks a silent omission, naming it — total coverage for `landscape`, scoped for `flow`; wired into CI. | Resolved (1.9.0) | `reconcile.role_of`, `reconcile.reconcile`, `cli.py`, CI, `tests/test_reconcile_properties.py` |
| G9 | **Docs Python floor drifted from `requires-python`.** The floor is authoritative in `pyproject.toml` (`>=3.11` since 1.7.0), but the same floor is repeated as prose in `CONTRIBUTING.md` / `INSTALL.md` / `README.md`, and `CONTRIBUTING.md` still said "Python 3.14+" and told contributors to run `python3.14 -m venv` long after the floor moved to 3.11 — the same single-source-of-truth failure G5 fixed for the release version. A `version_guard --python-docs` gate now reads `requires-python` and blocks any doc that names a REQUIREMENT floor (`Python X.Y+`, `python_requires >= X.Y`, `requires-python … >= X.Y`) different from it; a plain CI-matrix list ("3.11, 3.12, 3.13, 3.14") is not a floor claim and is not flagged. Wired into both CI pipelines' always-run stages. | Resolved (1.10.3) | `version_guard.python_floor_doc_problems`, `.github/workflows/ci.yml`, `.gitlab-ci.yml`, `tests/test_version_guard.py` |
| G10 | **The Contract does not use the Layout Engine.** `contract.py` emits a coordinate-free set of resolved nodes with no relationship information; placement/routing (`layout()`) is used only by the HA example generators and the `rule-engine-draw` autogenerator (G8). `docs/ARCHITECTURE.md` records the gap ("`contract.py` does not use it yet — wiring an inventory snapshot through it is planned work"). The `contract-layout-engine-wiring` spec re-points the Contract's diagram step onto the shared Snapshot → `DiagramSpec` → `layout()` → `build_diagram()` pipeline and extracts one assembler shared with `rule-engine-draw`. | Scheduled (`.kiro/specs/contract-layout-engine-wiring/`) | `contract.py`, `draw.py`, `layout/pipeline.layout` |
| G8 | **No high-level "draw from inventory" generator.** `collector.collect()` produces a Snapshot and `diagram_layout.build_diagram()` is a *low-level* builder (the author sets every node x/y and every edge waypoint by hand), so authoring a landscape from a snapshot is manual and edge routing takes several lint iterations (`edge-direction`, `entry-thirds`, `edge-crosses-label`). `reconcile.role_of` already maps a resource → role but only to *check* coverage, not to *place* nodes. A snapshot→diagram autogenerator (role-resolve every enumerated resource, place by lane order, route with the existing solver, emit the triple) would collapse that path. **Resolved (1.10.0)** as item **J** of the `provider-diagram-conventions` spec: the `rule-engine-draw` command role-resolves every enumerated resource via `reconcile.role_of`, assigns a lane via the pure `draw.lane_of`, emits the coordinate-free `DiagramSpec`, and delegates placement/routing to `layout()` and serialization to `build_diagram()`, writing the mandatory triple with a complete companion (`diagram_class` + `summary_of`/`detailed_view`). It is offline (Decision D5), deterministic (two runs byte-identical), and covers every role-bearing resource on a `landscape` (so `rule-engine-reconcile` passes). **Accepted limitation:** the best-effort LIVE raster export of a narrow-tall snapshot (the committed AWS example) lands ~3803px tall, over the `LANDSCAPE_MAX_HEIGHT_PX` (3600) ceiling — width and file size are within budget. This is a first-pass layout concern of the autogenerator on a tall inventory, not a gate defect and not a shipped artifact (the PNG is generated to a temp dir in the e2e test, never into `examples/`), so the raster export is best-effort: `rule-engine-draw` still writes the `.drawio` + companion, and the `check-rasters` gate is exercised over a conforming synthetic raster (`test_draw_e2e.py`). Every shipped `examples/` landscape raster stays within its class budget. A future pass can tighten the autogenerator's tall-snapshot layout (split rows, denser packing) without weakening the ceiling. | Resolved (1.10.0) | `rule_engine/draw.py`, `rule_engine/draw_cli.py`, reuses `reconcile.role_of`, `layout/pipeline.layout`, `diagram_layout.build_diagram`; `tests/test_draw_*` |
| G11 | **Diagram guidance cited only AWS; the `diagram_type` taxonomy was incomplete.** The standards were cross-checked against **Azure Well-Architected → *Architecture design diagrams*** (learn.microsoft.com, updated 2025-08-14) and Google Cloud's architecture guidance. Result: the enforced rules already cover the WAF recommendations provider-neutrally (single-ended arrows = `edge-bidirectional`; consistent icon sizes/line weights = the 78×78 + stroke rules; accuracy incl. "PaaS not in a subnet" and "retire stale diagrams" = the *Accuracy over simplicity* section; official-icons/no-recolor = *Icon Fidelity*; legend, contrast/no-color-only, layer-don't-overload = existing sections; metadata title+date+version + `change_log`/`external_refs` = the title format + companion frontmatter). Two provider-neutral **gaps** were closed in the `diagram_type` taxonomy: the **`block`/`functional`** technology-agnostic capability level (C4 + WAF), and the specialized **`resilience`/`residency`/`identity`** views (DR-SLO, regulated-data, security reviews — named by all three clouds). The taxonomy intro now records its provenance as the union of AWS `diagram-as-code` + Azure WAF + GCP guidance, reconciled with C4. Guidance-only: `diagram_type` remains descriptive metadata (only `network`/`infrastructure`/`deployment` are read, by `ip-range`); no lint rule reads the new values as a class, so nothing is enforced or weakened. `author` deliberately stays in companion frontmatter (a required key) rather than bloating the title cell. | Resolved (1.10.3) | `.kiro/steering/diagram-standards.md` (`diagram_type` taxonomy), cross-checked against Azure WAF design-diagrams + GCP architecture guidance |

## Open gaps

The four gaps closed in 1.9.0 are tracked as coded, Resolved findings in the
tables above; they are kept below for continuity, each pointing at its stable
code. The last 1.9.0-era gap, **G8**, is **Resolved (1.10.0)** — the
`rule-engine-draw` autogenerator shipped (`.kiro/specs/provider-diagram-conventions/`,
item J). One **Scheduled** gap remains: **G10** — the Contract does not yet use
the Layout Engine (it emits a coordinate-free node set); the
`contract-layout-engine-wiring` spec re-points it onto the `layout()` pipeline.

- **No high-level "draw from inventory" generator.** → **Resolved (1.10.0), G8.**
  `collector.collect()` writes the Snapshot and `diagram_layout.build_diagram()`
  is a low-level builder (manual node x/y and edge waypoints), so a landscape was
  authored by hand and its routing took several lint iterations. The
  `rule-engine-draw` autogenerator (item **J** of the `provider-diagram-conventions`
  spec) role-resolves every enumerated resource via `reconcile.role_of`, assigns
  a lane per the fixed lane order, emits the coordinate-free `DiagramSpec`, routes
  with the existing `layout()` solver, and writes the mandatory triple — total
  coverage for a `landscape` (so `rule-engine-reconcile` passes), offline and
  deterministic. **Accepted limitation:** the best-effort live raster export of a
  narrow-tall snapshot overshoots the 3600px landscape height ceiling (the
  committed AWS example lands ~3803px tall; width/size within budget). Since that
  PNG is generated to a temp dir and is not a shipped artifact, the raster export
  stays best-effort and the height ceiling is unchanged; every shipped `examples/`
  landscape raster remains within budget. See the G8 row above.

- **Inventory → diagram reconciliation is prose, not a gate.** → **Resolved (1.9.0),
  G7.** `diagram-standards.md` required every enumerated, role-resolvable resource
  to appear on the diagram, and the snapshot gate checked the snapshot's own shape,
  but nothing compared the two: a clean-room diagram omitted the ten KMS keys its
  `secrets.json` had enumerated while its companion asserted completeness. The
  `rule-engine-reconcile` gate (raw-provider-JSON → role mapper `reconcile.role_of`,
  reading only committed Snapshot files) now compares the two and blocks a silent
  omission, naming it.
- **Two rails and three crossings remain on the landscapes, and they are placement
  defects, not routing ones (held by 1.8.0, Decision D2).** → **Resolved (1.9.0),
  C6.** The scored per-edge router (1.8.0, C5) reached hand-route quality on every
  *routing* choice but scored routes only — not node/tier placement — so these three
  were held unchanged (`gcp/01` = (4,0), the landscapes = (3,2)). The scored
  *placement* loop (`solve_placement` over `generate_placement_variants`, the seam
  left in 1.8.0) now layers over the same order-score-commit machinery and relieves
  them via a sanctioned move (widen-gap improves the landscapes; `gcp/01` held). For
  the record, so they are not re-litigated as routing bugs:
  * the *tier-skip rail* — the load balancer's hop to the second AZ's application
    tier descends 540px in the VPC's left gap, which is the only corridor that
    crosses none of the fan-out lanes, and that gap is 60px wide, so the run sits
    30px from a column of icons whichever line it takes. The hand-route has the
    identical rail. Widening the gap (or moving the tier) fixes it; no routing
    choice does — which is the `widen-gap` move.
  * the *GCP / OCI hub* — `vertex-ai` / `generative-ai` carries four edges and its
    one free approach column lies **inside its own fan-out**, so the back-edge
    reaching it crosses two stubs. Every alternative was measured and none is
    better. Moving one neighbour fixes it — the `shift-neighbour` move.
  * the *edge-tier band* — two long runs leave the account's top row heading in
    opposite directions with overlapping extents, and that row has no band above
    it (it is the top row), so they cannot be put on opposite sides. Reordering the
    tier separates their extents — the `reorder-tier` move.
- **Container dead space is unmeasured.** → **Resolved (1.9.0), D15.**
  `container-padding` checked the *minimum* clearance; nothing flagged the opposite
  defect, a container sized far larger than its children (the clean-room VPC was
  840×460 around four nodes in one row). The advisory `container-dead-space` rule
  now flags it, with the threshold (`DEAD_SPACE_RATIO` = 5.0) measured across the
  corpus first so no shipped container false-positives.
- **Icon-index slug collisions are reported, not resolved.** → **Resolved (1.9.0),
  U3.** When two distinct vendor icons normalized to one slug (e.g. AWS
  `Database … Light`/`Dark`, Azure `Groups`/`Service Groups`), the icon-set builder
  kept last-writer-wins and emitted a WARNING. `build_icon_index` now disambiguates
  by a total, deterministic order: the winner keeps the bare slug, the loser is
  recorded under `<slug>--<disambiguator>`, no WARNING is emitted, and the index is
  byte-stable. The engine's own roles remain unaffected.
