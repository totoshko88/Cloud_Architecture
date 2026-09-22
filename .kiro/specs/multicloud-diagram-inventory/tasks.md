# Implementation Plan: Multi-cloud Diagram & Inventory Rule Engine

## Overview

This plan builds the reusable, cloud-agnostic **Diagram & Inventory Rule Engine** as a Kiro project. The implementation language is **Python** (property-based tests use Hypothesis; JSON Schema validation uses `jsonschema`; YAML mapping files use `PyYAML`).

The build sequence follows the natural dependency order: scaffold the repository, ingest and enumerate the official icon/style asset packs, encode the per-provider icon mapping tables, author the always-on steering docs, define the normalized inventory schema, then implement the provider-neutral core components (Linter, Icon Resolver, Inventory Collector, Normalizer, Delta Engine). Property-based tests validate the 15 Correctness Properties over the three pure/logic components. Golden examples, Kiro hooks, the spec template, the Rule Engine Contract, the CI pipeline, and the documentation/runbook close out the plan.

Each task builds on the previous ones and ends by wiring the new work into the whole. Test sub-tasks are marked `*` (optional). Property-based test sub-tasks are IDE-only and optional by default. Every property task references its design property number and the requirement clause it validates.

## Tasks

- [x] 1. Scaffold repository layout and root documentation placeholders
  - Create the directory tree: `.kiro/steering/`, `.kiro/hooks/`, `.kiro/specs/_template/`, `mappings/`, `schemas/`, `examples/{aws,azure,gcp,oci,generic}/`
  - Create root placeholder files: `README.md`, `INSTALL.md`, `CHANGELOG.md`, and the CI definition placeholder `.gitlab-ci.yml`
  - Add a Python project scaffold: `pyproject.toml` (declare `jsonschema`, `PyYAML`, `hypothesis`, `pytest` as dependencies), `src/rule_engine/__init__.py`, and `tests/__init__.py`
  - Add `.gitignore` entries for Python build artifacts and downloaded asset packs
  - _Requirements: 9.1, 9.2, 9.4, 9.5, 10.1, 10.8, 10.9_

- [x] 2. Ingest and enumerate official asset packs
  - [x] 2.1 Download and unpack the provider asset packs into a local `assets/` staging area
    - OCI draw.io style guide; AWS `mxgraph.aws4` built-in library plus the AWS architecture icon set; Azure V24 icon set; GCP category and core-products icon sets
    - Write `src/rule_engine/assets/fetch.py` to download and unpack each pack into `assets/<provider>/`
    - _Requirements: 2.9_
  - [x] 2.2 Enumerate each pack's icon inventory, naming scheme, and brand palette
    - Write `src/rule_engine/assets/enumerate.py` producing `assets/<provider>/inventory.json` (icon id/file, name, brand hex per icon)
    - Record the authoritative asset-pack identifier and icon reference source (`custom` vs `builtin`) per provider
    - _Requirements: 2.9_
  - [x] 2.3 Write unit tests for asset enumeration
    - Assert each provider's `inventory.json` is non-empty and every entry carries an icon id and a `#RRGGBB` brand hex
    - _Requirements: 2.9_

- [x] 3. Build per-provider icon mapping tables
  - [x] 3.1 Author `mappings/aws-icons.yaml`
    - Map each of the 9 neutral resource types → icon id/file → brand hex → complete draw.io style string using the `shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.<service>` form
    - Declare `boundary` and `network_boundary` container group styles (`shape=mxgraph.aws4.group` with `group_account` and a VPC group icon); declare `asset_pack` and `icon_source: builtin`
    - _Requirements: 2.3, 2.4, 2.6, 2.9, 9.3_
  - [x] 3.2 Author `mappings/azure-icons.yaml`, `mappings/gcp-icons.yaml`, `mappings/oci-icons.yaml`
    - Map the 9 neutral resource types → icon id/file → brand hex → draw.io style string per provider (Azure `#0078D4`, GCP `#4285F4`, OCI `#F80000` as brand anchors)
    - Declare exactly one `boundary` and one `network_boundary` container style each; declare `asset_pack` and `icon_source` as exactly one of `custom` or `builtin`
    - _Requirements: 2.5, 2.6, 2.9, 9.3_
  - [x] 3.3 Author `mappings/generic-icons.yaml`
    - Map the 9 neutral resource types to plain rectangle/UML shapes using grayscale fill/stroke only and no vendor icons (e.g. `rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000`)
    - Declare one `boundary` and one `network_boundary` grayscale container style
    - _Requirements: 2.6, 2.7, 9.3_
  - [x] 3.4 Write unit tests for the mapping tables
    - Assert every mapping file defines all 9 neutral resource types, exactly one boundary and one network-boundary container style, and a `#RRGGBB` brand hex per resource
    - Assert AWS resource styles carry the `mxgraph.aws4.resourceIcon` prefix and generic styles contain no vendor icon token
    - _Requirements: 2.3, 2.6, 2.7, 9.3_

- [x] 4. Author always-on steering documents
  - [x] 4.1 Author `.kiro/steering/diagram-standards.md`
    - Encode lane order (actors → edge → router → async messaging → workers → platform core → data → on-premises), 12-node limit and split rule, node quoting rule, mandatory edge labels, alt text, single `@startuml`/`@enduml` with no preprocessor directives, the mandatory `.drawio`/`.drawio.png`/`.diagram.md` triple, the title-cell format, the PlantUML-vs-Mermaid decision matrix, and the mandatory Legend block
    - Set `inclusion: always` in the front matter
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 5.9, 5.10, 5.11, 6.1, 6.2, 6.3, 6.4, 11.1_
  - [x] 4.2 Author `.kiro/steering/inventory-standards.md`
    - Encode read-only verbs per provider, the zero-mutation rule, snapshot folder naming, the manifest field set, one JSON file per service domain plus one subfolder per resource, secret-safety, non-fatal per-service failure handling, and the declared cost endpoint rule
    - Set `inclusion: always`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 11.1_
  - [x] 4.3 Author `.kiro/steering/provider-profiles.md`
    - Encode the terminology normalization table with a row for each of the 9 neutral terms across all five providers, plus per-provider container conventions, brand palette, and read-only verb list
    - Set `inclusion: always`
    - _Requirements: 9.10, 11.1_
  - [x] 4.4 Author `.kiro/steering/kb-frontmatter.md`
    - Encode required frontmatter keys and value formats/enumerations/bounds, the document length bounds, required sections and their bounds, the single-H1 rule, list-nesting and table-column limits, the anti-patterns rule, and the accept/reject behavior
    - Set `inclusion: always`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 11.1_
  - [x] 4.5 Author `.kiro/steering/diagram-lint.md`
    - Encode the full lint ruleset with each rule's condition and severity (CRITICAL/ERROR/WARNING), the publication-eligibility rule, and the ruleset-unavailable behavior
    - Set `inclusion: always`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12, 7.13, 7.14, 11.1_

- [x] 5. Define and validate the normalized inventory schema
  - [x] 5.1 Author `schemas/inventory.schema.json`
    - Define the JSON Schema (Draft 2020-12) for a Normalized Resource with the required fields, the `provider` and `resource_type` enums, the `config_digest` `^[a-f0-9]{64}$` pattern, and `additionalProperties: false`
    - _Requirements: 4.1, 4.2, 4.3_
  - [x] 5.2 Author and validate one sample Normalized Resource per provider
    - Create `examples/<provider>/sample-resource.json` for aws, azure, gcp, oci; validate each against `schemas/inventory.schema.json`
    - Write `src/rule_engine/schema.py` exposing `validate_resource(resource)` used by the samples and later by the Normalizer
    - _Requirements: 4.8_
  - [x] 5.3 Write unit tests for schema validation
    - Assert each provider sample validates; assert a resource with a missing required field or a malformed `config_digest` fails validation
    - _Requirements: 4.1, 4.2, 4.8_

- [x] 6. Implement the Linter
  - [x] 6.1 Implement the lint ruleset engine
    - Write `src/rule_engine/linter.py` implementing `lint(artifact) -> { findings: [{rule, severity}], eligible_for_publication: bool }`
    - Implement each rule from `diagram-lint.md` (node-count, edge-label, node-quote, legend-present, companion-doc, frontmatter, icon-resolved, secret-safety, title-versioned, mermaid-type) with its severity
    - Set `eligible_for_publication` true only when zero CRITICAL and zero ERROR findings exist; otherwise block
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12, 7.13_
  - [x] 6.2 Implement ruleset-unavailable handling and the lint CLI entry point
    - Return a ruleset-unavailable error and block every artifact when `diagram-lint.md` is missing or unreadable
    - Expose a `rule-engine-lint` console entry point (supports `--file`, `--all`, `--fail-on error,critical`) for hook and CI use
    - _Requirements: 7.14_
  - [x] 6.3 Write unit tests for lint severities and eligibility
    - Provide one artifact per rule that produces the expected severity; assert eligibility flips on the first ERROR/CRITICAL; assert missing-ruleset blocks everything
    - _Requirements: 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12, 7.13, 7.14_

- [x] 7. Implement the provider-neutral core components
  - [x] 7.1 Implement the Icon Resolver
    - Write `src/rule_engine/icon_resolver.py` implementing `resolve_icon(resource_type, provider) -> {style_string, brand_hex, icon_source}` and `resolve_container(kind, provider) -> {style_string}` reading from `mappings/<provider>-icons.yaml`
    - Return exactly one container style per boundary kind; format brand color as `#RRGGBB`; source every id/color from the declared asset pack
    - On an unmapped type return an unresolved-type error with no style string and no placeholder, input unchanged; on a missing/unreadable asset pack return an asset-source error
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_
  - [x] 7.2 Write property test — Icon Resolver totality over mapped domain
    - **Property 1: Resolve is total over the mapped domain**
    - **Validates: Requirements 2.1**
  - [x] 7.3 Write property test — brand color format
    - **Property 2: Brand color is always #RRGGBB**
    - **Validates: Requirements 2.2**
  - [x] 7.4 Write property test — AWS aws4 resource-icon form
    - **Property 3: AWS style strings use the aws4 resource-icon form**
    - **Validates: Requirements 2.3**
  - [x] 7.5 Write property test — non-AWS icon source is one of two values
    - **Property 4: Non-AWS icon source is exactly one of two values**
    - **Validates: Requirements 2.5**
  - [x] 7.6 Write property test — one container style per boundary/network boundary
    - **Property 5: Exactly one container style per boundary and per network boundary**
    - **Validates: Requirements 2.6**
  - [x] 7.7 Write property test — generic profile grayscale and vendor-icon-free
    - **Property 6: Generic profile is grayscale and vendor-icon-free**
    - **Validates: Requirements 2.7**
  - [x] 7.8 Write property test — unresolved types never yield a placeholder
    - **Property 7: Unresolved types never yield a placeholder**
    - **Validates: Requirements 2.8**
  - [x] 7.9 Write property test — icon and color provenance
    - **Property 8: Icon and color provenance**
    - **Validates: Requirements 2.9**
  - [x] 7.10 Implement the Inventory Collector
    - Write `src/rule_engine/collector.py` implementing `collect(provider, boundary_id, region) -> {snapshot_folder, manifest}` executing only the profile's read-only verbs
    - Write the snapshot folder with the mandated name, `00-MANIFEST.md` with all non-empty fields, one JSON file per service domain, and one subfolder per resource; record secret-free metadata only
    - On a single-service enumeration failure record the service and reason and continue; use only the declared cost endpoint for cost/billing data
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_
  - [x] 7.11 Write unit/integration tests for the Collector
    - Assert zero state-mutating verbs execute; assert manifest fields are non-empty; assert a simulated single-service failure is recorded and collection continues; assert no snapshot file contains a secret value
    - _Requirements: 3.1, 3.3, 3.6, 3.8, 3.9_
  - [x] 7.12 Implement the Normalizer
    - Write `src/rule_engine/normalizer.py` implementing `normalize(native_resource, provider) -> NormalizedResource` and `compute_config_digest(config) -> hex64`
    - Populate all mandatory fields, draw `resource_type` from the neutral enum, and compute an order-independent SHA-256 `config_digest` via canonicalization (drop secret fields, recursively sort keys and array elements, serialize, hash)
    - Record unmapped-type, missing-field, and schema-validation errors and exclude the offending resource
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
  - [x] 7.13 Write property test — schema conformance of emitted resources
    - **Property 9: Every emitted resource validates against the schema**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.7**
  - [x] 7.14 Write property test — config_digest deterministic and order-independent
    - **Property 10: config_digest is deterministic and order-independent**
    - **Validates: Requirements 4.4**
  - [x] 7.15 Write property test — unmapped resources excluded with an error
    - **Property 11: Unmapped resources are excluded with an error**
    - **Validates: Requirements 4.5**
  - [x] 7.16 Write property test — missing mandatory field excludes with an error
    - **Property 12: Missing mandatory field excludes the resource with an error**
    - **Validates: Requirements 4.6**
  - [x] 7.17 Implement the Delta Engine
    - Write `src/rule_engine/delta.py` implementing `compute_delta(current_snapshot, previous_snapshot?) -> [DeltaRecord]` matching on the identity tuple `(provider, resource_type, identity)` where identity is `id` when present else `name`
    - Classify each resource added/changed/removed/unchanged with the correct change marker; with no previous snapshot classify all as added; on a missing/malformed snapshot return a snapshot-input error and no classification
    - Supply the classification to both the versioned document and the diagram change markers
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_
  - [x] 7.18 Write property test — classification partitions the identity set
    - **Property 13: Classification partitions the identity set**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
  - [x] 7.19 Write property test — change markers match classification
    - **Property 14: Change markers match classification**
    - **Validates: Requirements 5.2, 5.3, 5.4**
  - [x] 7.20 Write property test — no previous snapshot implies all added
    - **Property 15: No previous snapshot implies all added**
    - **Validates: Requirements 5.6**

- [x] 8. Checkpoint — core components and property tests
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Author golden examples (one per provider plus cross-cloud)
  - [x] 9.1 Author the aws golden example — `aws-agent-platform`
    - Create the `.drawio` + `.diagram.md` pair, a matching inventory `00-MANIFEST.md` snippet, and a delta example (one added/changed/removed); ensure it passes every CRITICAL/ERROR lint rule
    - _Requirements: 1.10, 2.1, 5.8, 7.2, 9.4_
  - [x] 9.2 Author the azure golden example — `azure-openai-rag`
    - Create the `.drawio` + `.diagram.md` pair, matching manifest snippet, and a delta example; pass all CRITICAL/ERROR lint rules
    - _Requirements: 1.10, 2.1, 5.8, 7.2, 9.4_
  - [x] 9.3 Author the gcp golden example — `gcp-vertex-pipeline`
    - Create the `.drawio` + `.diagram.md` pair, matching manifest snippet, and a delta example; pass all CRITICAL/ERROR lint rules
    - _Requirements: 1.10, 2.1, 5.8, 7.2, 9.4_
  - [x] 9.4 Author the oci golden example — `oci-genai-stack`
    - Create the `.drawio` + `.diagram.md` pair, matching manifest snippet, and a delta example; pass all CRITICAL/ERROR lint rules
    - _Requirements: 1.10, 2.1, 5.8, 7.2, 9.4_
  - [x] 9.5 Author the generic golden example — `generic-reference-architecture.puml`
    - Create the `.puml` source + `.diagram.md` companion using grayscale/no-vendor-icon shapes, matching manifest snippet, and a delta example; pass all CRITICAL/ERROR lint rules
    - _Requirements: 1.10, 2.7, 5.8, 7.2, 9.4_
  - [x] 9.6 Author the cross-cloud composition example — `cross-cloud-composition.puml`
    - Create a C4 container `.puml` + `.diagram.md` spanning multiple providers, each rendered with its profile's icon/color and boundary styles, ≤12 nodes, every cross-provider edge labeled with its data flow; pass all CRITICAL/ERROR lint rules
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [x] 9.7 Write integration test validating golden examples against the Linter
    - Run the Linter over every golden example and assert each is eligible for publication (zero CRITICAL/ERROR)
    - _Requirements: 7.2, 9.4_

- [x] 10. Author Kiro hooks
  - [x] 10.1 Author `.kiro/hooks/lint-on-save.kiro.hook`
    - `PostFileSave` trigger with matcher `\.(drawio|md)$` running `rule-engine-lint --file "$KIRO_FILE_PATH" --fail-on error,critical`; surface a blocking failure reason to the session
    - _Requirements: 11.2, 11.4_
  - [x] 10.2 Author `.kiro/hooks/validate-on-task.kiro.hook`
    - `PostTaskExec` trigger running the Linter (`--all`) and schema validation (`rule-engine-validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json'`); surface a blocking failure reason to the session
    - Write the `rule-engine-validate-schema` console entry point used by this hook and by CI
    - _Requirements: 11.3, 11.4_

- [x] 11. Author the spec template and wire the Rule Engine Contract
  - [x] 11.1 Author the spec template `.kiro/specs/_template/`
    - Create `requirements.md`, `design.md`, and `tasks.md` templates for an Arch-Assistant to copy when creating a new spec
    - _Requirements: 9.5_
  - [x] 11.2 Implement the Rule Engine Contract
    - Write `src/rule_engine/contract.py` implementing `invoke({provider, boundary_id, region, previous_doc_path, inventory_snapshot_path}) -> {drawio, drawio_png, diagram_md, existing_infrastructure_md}` orchestrating the Icon Resolver, Collector, Normalizer, Delta Engine, Diagram Generator, and Linter
    - Validate inputs: accept only when all required inputs are present and `provider` is in the enum; otherwise reject, produce no output documents, and return an error naming the missing/invalid input
    - Produce the `NN-topic.drawio`/`.drawio.png`/`.diagram.md` triple and the versioned `NN-existing-infrastructure.md` (with frontmatter, `NN` in `01`–`99`)
    - _Requirements: 9.6, 9.7, 9.8_
  - [x] 11.3 Write unit tests for the contract input validation and outputs
    - Assert a fully-specified valid invocation is accepted and produces the four outputs; assert each missing required input and an out-of-enum `provider` are rejected with a naming error and no output documents
    - _Requirements: 9.6, 9.7, 9.8_

- [x] 12. Author the CI pipeline
  - [x] 12.1 Implement `.gitlab-ci.yml` pipeline stages
    - Define `lint` (Linter over every diagram + document), `validate` (each `mappings/<provider>-icons.yaml` and the Inventory Schema), `build` (package the Release Bundle: steering docs, mappings, schema, examples, runbook), `changelog` (generate/update `CHANGELOG.md` reverse-chronological), `publish` (Release Bundle + Changelog as artifacts)
    - Name every Release Bundle with a Semantic Version
    - _Requirements: 10.1, 10.2, 10.4, 10.5, 10.6, 10.10_
  - [x] 12.2 Implement CI fail conditions
    - Fail the run and produce no Release Bundle when the Linter reports ≥1 CRITICAL/ERROR, or when the release trigger's Semantic Version already exists in the Changelog
    - _Requirements: 10.3, 10.7_
  - [x] 12.3 Write tests for the changelog/version guard logic
    - Assert a duplicate Semantic Version is rejected and a lint failure short-circuits the bundle step
    - _Requirements: 10.3, 10.7_

- [x] 13. Author documentation and the add-a-provider runbook
  - [x] 13.1 Author `README.md` and `INSTALL.md`
    - README: purpose, contents, quick start, and links to the steering documents and the Installation Guide
    - INSTALL: prerequisites and the ordered steps to install and activate the Rule Engine in a Kiro workspace
    - _Requirements: 10.8, 10.9_
  - [x] 13.2 Author the "add a new provider" runbook
    - Enumerate the ordered steps: add a Provider Profile row (all 9 terms), add an icon mapping, add inventory verbs, add a Golden Example, and complete a lint run reporting zero violations
    - _Requirements: 9.9_

- [x] 14. Final checkpoint — full pipeline
  - Ensure all tests pass and the Linter reports every golden example eligible for publication, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Property-based test sub-tasks are IDE-only (run in the workspace, not production) and optional by default; each runs a minimum of 100 iterations with a comment tag `Feature: multicloud-diagram-inventory, Property {number}: {property_text}`.
- Each task references the specific requirement clauses it satisfies for traceability.
- Checkpoints ensure incremental validation at natural breaks.
- Property tests validate the 15 universal Correctness Properties over the Icon Resolver, Normalizer, and Delta Engine; unit and integration tests cover fixed cases, wiring, and error paths.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "3.1", "3.2", "3.3", "5.1", "4.1", "4.2", "4.3", "4.4", "4.5"] },
    { "id": 4, "tasks": ["3.4", "5.2", "6.1"] },
    { "id": 5, "tasks": ["5.3", "6.2", "7.1", "7.10", "7.12"] },
    { "id": 6, "tasks": ["6.3", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9", "7.11", "7.13", "7.14", "7.15", "7.16", "7.17"] },
    { "id": 7, "tasks": ["7.18", "7.19", "7.20", "9.1", "9.2", "9.3", "9.4", "9.5", "9.6", "10.1", "10.2", "11.1", "11.2"] },
    { "id": 8, "tasks": ["9.7", "11.3", "12.1"] },
    { "id": 9, "tasks": ["12.2", "13.1", "13.2"] },
    { "id": 10, "tasks": ["12.3"] }
  ]
}
```
