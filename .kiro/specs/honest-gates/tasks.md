# Implementation Plan: Honest Gates (release 1.7.0)

## Overview

This plan implements `design.md` in Python (the project language). Work follows the
design's order of work:

1. Shared single-source modules land first, each with its property tests:
   `drawio_model`, `secret_safety`, `identity`, `icon_refs`, `kb_validator`, `ruleset`.
2. Consumers switch over next: `cli`/`geometry`/`linter`, `verify_icon`,
   `collector`/`normalizer`/`delta`/`snapshot_gate`,
   `fetch_assets`/`asset_index`/`build_icon_sets_cli`, `init_workspace`,
   `export_raster`/`raster_gate`, generator `--check`, and `contract`.
3. Docs, steering, CHANGELOG, `pyproject.toml` and CI follow.
4. `examples/` is migrated last, so every example passes the tightened gates.

Decisions D1–D8 are adopted working assumptions, as the design records:

- D1: draw.io is canonical. Both `.puml` examples become `.drawio` triples.
- D2: every new or tightened check ships at final severity.
- D3: the 1.6.1 bare-`key` rule stays, plus a `METADATA_KEYS` allow-list.
- D4: the `resource_type` enum grows to 16 values.
- D5: `inventory-*/00-MANIFEST.md` is exempt from the KB rule and owned by `snapshot_gate`.
- D6: `requires-python >= 3.11`.
- D7: `--update-pins` is a command now; a scheduled job comes later.
- D8: the five over-budget flow layouts are tightened rather than the budget raised.

If any of these decisions is overturned, the affected tasks change as the design's "If overturned" column describes.

Conventions:

- Requirement references use the form R*n*.*m*. Property references (P*n*) point to
  `design.md` → *Correctness Properties*.
- Each property test uses Hypothesis with `max_examples >= 100` and carries the tag
  comment `# Feature: honest-gates, Property N: <title>`.
- Each steering edit is applied to all three copies: `.kiro/steering/`, the Power copy
  under `powers/`, and `src/rule_engine/_bootstrap/kiro/steering/`. After each such
  edit, `tests/test_bootstrap_payload_sync.py` must pass.

## Tasks

- [x] 1. Shared test infrastructure
  - [x] 1.1 Create `tests/strategies.py` and a Hypothesis profile
    - Add a Hypothesis profile in `tests/conftest.py` with `max_examples=100`, plus a `deadline=None` variant for the filesystem-backed properties.
    - Add a `.drawio` diagram-model strategy with a test-only serializer. It must support plain, compressed (`base64(deflateRaw(encodeURIComponent(...)))`), multi-page, `UserObject`/`object`-wrapped cells, HTML labels with entities and `<br>`, omitted geometry coordinates, and an optional `gridSize`.
    - Add a KB-document strategy built from a structure model: section word counts, the four required sections, H1 count, list depth, table widths and row cell counts, fenced blocks, and an Anti-patterns section.
    - Add JSON-value strategies: a benign-metadata generator and a plant-a-secret combinator that returns `(value, json_pointer)`.
    - Add a native-resource strategy with key-case and separator transforms.
    - Add strategies for init source, target and lock trees.
    - Add a minimal PNG encoder (IHDR/IDAT/tEXt/tRNS/IEND, selectable colour type and row-0 filter). This is test-only code.
    - _Requirements: supports R1–R8 property tests_

- [x] 2. `drawio_model`: one XML parser for `.drawio`
  - [x] 2.1 Implement `src/rule_engine/drawio_model.py`
    - Add the `Geom`, `Cell`, `Page` and `DrawioParseError` types, `parse_drawio(data, *, path)`, `absolute_origin(page, cell_id)` and `decode_compressed(text)`, with the signatures given in design §1.
    - Build on `xml.parsers.expat` with a small tree builder. Doctype, entity-declaration and external-entity handlers raise `DrawioParseError("dtd-or-entity-declaration")`. Set `XML_PARAM_ENTITY_PARSING_NEVER`. Use the same guarded parse for the decompressed inner model.
    - Accept roots `<mxfile>` with 1..n `<diagram>`, or a bare `<mxGraphModel>` (page named after the file stem). De-duplicate page names as `name`, `name (2)`, and so on.
    - Wrappers: take `id` and `label` from the `UserObject`/`object`, and put other attributes into `wrapper_attrs`. A wrapper with zero or several `mxCell` children raises `DrawioParseError`.
    - Labels: when `html=1`, convert `<br>`, `</div>`, `</p>` and `</li>` to line breaks, strip tags with an `html.parser.HTMLParser` subclass, apply `html.unescape`, and strip each line.
    - `style_map`: store a bare leading token as `{token: ""}` and keep `shape=stencil(...)` whole (split on `;` only outside parentheses).
    - Read waypoints only from `<Array as="points">`, keep `sourcePoint`/`targetPoint` separately, and ignore the label `offset`. A missing coordinate is 0. `grid_size` comes from `gridSize`, else 10.
    - `absolute_origin` raises `DrawioParseError("parent-cycle:<id>")` on a parent cycle.
    - Map `ExpatError`, `binascii.Error`, `zlib.error`, `UnicodeDecodeError`, a missing `<root>` and non-numeric geometry to `DrawioParseError`, each with a machine-readable cause string.
    - Move `_decode_drawio_payload` from `src/rule_engine/fetch_assets.py` to `drawio_model.decode_compressed` and import it back into `fetch_assets`.
    - _Requirements: R1.1, R1.2, R1.4, R1.5, R1.6, R1.7, R1.8, R1.9_
  - [x] 2.2 Write the property test for the `.drawio` round trip
    - **Property 1: `.drawio` round trip**
    - **Validates: Requirements 1.1, 1.2, 1.4, 1.5, 1.7**
    - File: `tests/test_drawio_model_properties.py`
  - [x] 2.3 Write example tests for XML safety and real draw.io files
    - Billion-laughs and external-entity documents raise `DrawioParseError("dtd-or-entity-declaration")`.
    - Add fixtures under `tests/fixtures/drawio/`: one multi-page file exported from draw.io desktop, one compressed page, and one `UserObject`-wrapped node. Assert the parsed ids, labels and pages.
    - A parent-cycle fixture raises `parent-cycle:<id>`.
    - File: `tests/test_drawio_model.py`
    - _Requirements: R1.2, R1.3, R1.4, R1.8, R1.9_

- [x] 3. `secret_safety`: one secret vocabulary
  - [x] 3.1 Implement `src/rule_engine/secret_safety.py`
    - Add `REDACTED`, `normalize_key`, `CREDENTIAL_SUFFIXES` (full list from design §5) and `METADATA_KEYS` (D3).
    - Move `PAIR_NAME_KEYS`, `PAIR_VALUE_KEYS` and `pair_redactions` here from `collector.py`.
    - Add `is_credential_key`, `value_secret_kind`, `SecretHit`, `redact`, `find_secrets` (RFC 6901 pointers) and `scan_text` (`line:<n>` locations; handles `key: value`, `key=value` and `| key | value |` shapes).
    - Key rule, in order:
      - a name in `METADATA_KEYS` is not a secret;
      - `key`/`keys` is a secret, except the `Key` field of a pure `{Key, Value}` record;
      - a raw `_key`/`-key` suffix is a secret;
      - a normalized name ending in a credential suffix is a secret.
    - A key counts as a leak only when its value is a non-empty string or bytes other than `REDACTED`.
    - Value shapes:
      - PEM/OpenSSH/PGP `PRIVATE KEY` blocks;
      - `AccountKey=`, `SharedAccessKey=`, `SharedAccessSignature=`;
      - a SAS `sig=`;
      - a password in URL userinfo;
      - a JWT;
      - the 1.6.1 inline assignments;
      - an AWS `AKIA`/`ASIA` id with a 40-character sibling secret, detected at the mapping level;
      - `Type: SecureString` with a non-redacted `Value`, detected through the pair rule.
    - Do not match public certificates, `PUBLIC KEY` blocks or the bare label `SecureString`.
    - In `src/rule_engine/constants.py`, replace `SECRET_MARKERS`/`SECRET_CONTENT_MARKERS` with a module `__getattr__` that re-exports `secret_safety.CREDENTIAL_SUFFIXES` and raises a `DeprecationWarning` on access.
    - _Requirements: R3.1, R3.2, R3.3, R3.4, R3.6_
  - [x] 3.2 Write the property test for planted secrets
    - **Property 11: Planted secrets are found where they were planted**
    - **Validates: Requirements 3.1, 3.2, 3.3**
    - File: `tests/test_secret_safety_properties.py`
  - [x] 3.3 Write the property test for metadata never being reported
    - **Property 12: Metadata is never reported**
    - **Validates: Requirements 3.4**
    - File: `tests/test_secret_safety_properties.py`
  - [x] 3.4 Write the property test for redactor/Linter agreement
    - **Property 13: The redactor and the Linter agree**
    - **Validates: Requirements 3.6, 3.4**
    - File: `tests/test_secret_safety_properties.py`

- [x] 4. Resource types and `identity`
  - [x] 4.1 Extend the resource-type vocabulary
    - In `src/rule_engine/constants.py`, add `NEUTRAL_RESOURCE_TYPES` (the nine), `DIAGRAM_ROLE_TYPES` (`compute_instance`, `file_system`, `cdn`, `dns`, `waf`, `lb`, `cache`) and `RESOURCE_TYPES`.
    - Set `schemas/inventory.schema.json` → `resource_type.enum` to the 16 values.
    - Add seven rows to `profiles/terminology.yaml`, each with a label and native-type aliases for aws, azure, gcp and oci, and a label for generic (design §7 table).
    - _Requirements: R5.1, R5.2_
  - [x] 4.2 Implement `src/rule_engine/identity.py`
    - `flat(name)` delegates to `secret_safety.normalize_key`.
    - `IDENTITY_KEYS` holds the per-provider flat keys in priority order (aws list from design §7; azure `id`; gcp `selflink`, `id`; oci `id`, `ocid`; generic `id`, `address`).
    - Add `native_identity(resource, provider)`, which is case- and separator-insensitive, and `content_identity(resource)`, which returns `"sha256:"` followed by 12 hex characters of the canonical JSON.
    - _Requirements: R5.3, R5.5, R5.8_
  - [x] 4.3 Write example tests for resource types and identity keys
    - Loop over every value and assert that the schema enum, `constants.RESOURCE_TYPES` and the `mappings/roles.yaml` roles are the same set.
    - Every role × vendor has aliases that resolve back to that role through the terminology loader.
    - `native_identity` matches `InstanceId`, `instance_id` and `instanceId`.
    - File: `tests/test_resource_types.py`
    - _Requirements: R5.1, R5.2, R5.3_

- [x] 5. `icon_refs`: shared icon extraction and resolution
  - [x] 5.1 Implement `src/rule_engine/icon_refs.py`
    - Add `IconRef`, `IconSources`, `load_sources(workspace_root)`, `service_vertices(page)`, `extract_refs(page)` and `resolve(ref, sources)`. `resolve` returns a status from `resolved`/`unresolved`/`skipped`/`unverified`.
    - Ref kinds: `resIcon`, `grIcon`, `azure2`, `image`, `oci-slug`, `oci-glyph` (sha256 of the `shape=stencil(...)` payloads in document order) and `generic-shape` (shapes declared in `mappings/generic-icons.yaml`).
    - Image path rule: normalise with `posixpath.normpath`. The ref is `unresolved` when it is absolute, still contains `..` after normalisation, lies outside `assets/`, has a suffix other than `.svg`/`.png`, or is a `data:` URI. Check `img/lib/azure2/…` against the azure2 manifest first.
    - OCI: resolve a slug against `stencils.json` when it is present, else against `oci_digests`. When both a slug and a glyph are present, the glyph digest must equal `oci_digests[slug]`. A glyph without a slug is resolved by reverse lookup.
    - _Requirements: R4.1, R4.2, R4.4_
  - [x] 5.2 Emit the `ociSlug=` marker from `OciStencilIcon`
    - In `src/rule_engine/diagram_layout.py`, have `OciStencilIcon.__call__` add `ociSlug=<slug>` to the container group style.
    - Add a helper `oci_glyph_digest(stencil_payloads)` in `icon_refs` and use it from both the builder and the verifier.
    - _Requirements: R4.1_
  - [x] 5.3 Build the committed `mappings/oci-stencil-digests.json` manifest
    - In `src/rule_engine/build_icon_sets_cli.py`, write `{slug: sha256}` (hashes only, no vendor content) next to `aws4-icons.json`, derived from `stencils.json`.
    - Include this manifest in `--check`.
    - _Requirements: R4.1_
  - [x] 5.4 Write the property test for image paths outside the asset root
    - **Property 15: Image paths outside the asset root are unresolved**
    - **Validates: Requirements 4.4**
    - File: `tests/test_icon_refs_properties.py`

- [x] 6. `kb_validator`: frontmatter and document structure
  - [x] 6.1 Implement `src/rule_engine/kb_validator.py`
    - Add `KbViolation`, `split_frontmatter` (strips a leading `\ufeff`, CRLF-tolerant), `load_frontmatter`, `validate_frontmatter`, `validate_structure` and `validate_document`.
    - `load_frontmatter` uses a `_KbLoader(yaml.SafeLoader)` with the implicit `timestamp` resolver removed. A `YAMLError` or a non-mapping document produces `yaml-parse` with the problem mark.
    - Frontmatter constraints:
      - `missing-key:<k>` and `empty-key:<k>`, with `related_docs: []` allowed;
      - `status-enum`;
      - `date-format:<k>`, which uses a regex plus `date.fromisoformat`;
      - `list-type:<k>`;
      - `tags-count` (1–20) and `related_docs-count` (0–20).
    - Structure constraints, evaluated with fenced blocks (```` ``` ```` and `~~~`) masked:
      - `doc-length`: 300–2000 words;
      - `section-missing:<S>` and `section-length:<S>`: 100–200 words for each of Overview, Main Content, Troubleshooting and See Also;
      - `h1-count`: ATX or Setext;
      - `list-depth`: more than 2 levels;
      - `table-columns`: more than 5 columns;
      - `table-merged-cell`;
      - `anti-patterns-missing`.
    - Every violation names its key or section where one applies.
    - _Requirements: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7_
  - [x] 6.2 Write the property test for frontmatter validation
    - **Property 8: Frontmatter validation matches the contract**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.7**
    - File: `tests/test_kb_validator_properties.py`
  - [x] 6.3 Write the property test for structural validation
    - **Property 9: Structural validation matches a document model**
    - **Validates: Requirements 2.4**
    - File: `tests/test_kb_validator_properties.py`
  - [x] 6.4 Write the property test for BOM invariance
    - **Property 10: A BOM does not change the verdict**
    - **Validates: Requirements 2.6**
    - File: `tests/test_kb_validator_properties.py`

- [x] 7. `ruleset`: one ruleset location and a rule-table parser
  - [x] 7.1 Implement `src/rule_engine/ruleset.py`
    - Move `find_ruleset` and `ruleset_available` here from `src/rule_engine/linter.py` and keep re-exports in `linter.py`.
    - Resolution order:
      1. `RULE_ENGINE_RULESET`. A path that is set but missing means the ruleset is unavailable; there is no fallthrough.
      2. `<workspace_root or cwd>/.kiro/steering/diagram-lint.md`.
      3. The repository checkout (`parents[2]`).
      4. `_bootstrap/kiro/steering/diagram-lint.md`.
    - Add `RulesetUnavailableError` and `require_ruleset(workspace_root=None)`.
    - Add `parse_rule_table(text) -> dict[str, RuleRow]`, which reads the `## Lint Rules` table (severity cells such as `WARNING/ERROR`) and the `## Diagram Class` escalation table.
    - _Requirements: R10.1, R10.2_
  - [x] 7.2 Write unit tests for `ruleset`
    - Cover each step of the resolution order, a set-but-missing env var, and `parse_rule_table` on the current `diagram-lint.md` and on a malformed table.
    - File: `tests/test_ruleset.py`
    - _Requirements: R10.1, R10.2_

- [x] 8. Checkpoint: shared modules
  - Run `pytest` and `rule-engine-lint --all`. Ensure all tests pass, ask the user if questions arise.

- [x] 9. Geometry and CLI parsing on the parsed model
  - [x] 9.1 Switch `geometry.build_geometry` to take a `Page`
    - In `src/rule_engine/geometry.py`, remove `_CELL_RE`, `_attr` and `_POINT_RE`. Read cells from `Page.cells`.
    - Add `absolute_origin(page, edge.parent)` to every waypoint.
    - Take the grid from `page.grid_size`.
    - Replace the silent `(0, 0)` parent-cycle fallback with `DrawioParseError`.
    - _Requirements: R1.6, R1.7, R1.8_
  - [x] 9.2 Write the property test for waypoints
    - **Property 2: Waypoints are exactly the authored points in page coordinates**
    - **Validates: Requirements 1.6**
    - File: `tests/test_drawio_model_properties.py`
  - [x] 9.3 Implement `cli.parse_artifacts` on `drawio_model`
    - In `src/rule_engine/cli.py`, remove the regex `.drawio` parser and the `except Exception: geo = None` branch.
    - Add `parse_artifacts(path) -> list[Artifact]`, which returns one Artifact per page, labelled `file#page` for multi-page files and `file` for a single page.
    - Keep `parse_artifact` as a compat wrapper that raises `ValueError("multi-page: use parse_artifacts")` for a multi-page file.
    - A `DrawioParseError` or geometry exception becomes `Artifact(parse_errors=[...])`, with the cause `geometry:<Type>:<msg>` for a geometry exception.
    - Add the Artifact fields to `src/rule_engine/linter.py`: `page`, `label`, `parse_errors`, `grid_size`, `legend_lines`, `edge_endpoints`, `in_snapshot`, `text`.
    - Detect the Legend and Flow cells structurally (first non-empty line, casefolded, is `legend`/`flow`). Detect the title cell with `TITLE_RE` plus `date.fromisoformat`. Read overlay markers from `style_map["overlay"]`.
    - Record edge endpoints as `missing-source`, `missing-target`, `dangling-source:<id>` or `dangling-target:<id>`.
    - Read companion frontmatter (`diagram_class`, `summary_of`) with `kb_validator.load_frontmatter`. An unparsable companion makes the diagram artifact carry a `parse-error`.
    - Delete `_parse_frontmatter_fallback`.
    - _Requirements: R1.3, R1.8, R1.10, R1.11, R1.12, R2.5_
  - [x] 9.4 Implement discovery in `cli.py`
    - Add `_is_snapshot_manifest`, which is true for `00-MANIFEST.md` under an `inventory-*` ancestor. Define `_is_kb_document = _is_generated_markdown and not _is_snapshot_manifest` (D5).
    - `.puml`/`.mmd` files become diagram Artifacts with `source_format` set (D1).
    - Every UTF-8 text file under `inventory-*` becomes a snapshot Artifact with `in_snapshot=True` and `text`. A binary file becomes `parse-error: not-text`.
    - A `.json` file whose content is a Normalized Resource becomes a snapshot Artifact.
    - _Requirements: R2.8, R3.5, R10.3_
  - [x] 9.5 Write the property test for one artifact per page
    - **Property 3: One artifact per page with unique labels**
    - **Validates: Requirements 1.3**
    - File: `tests/test_drawio_model_properties.py`
  - [x] 9.6 Write example tests for discovery
    - Steering, `SKILL.md` and README files are not KB documents. `inventory-*/00-MANIFEST.md` is exempt from the KB rule. `examples/azure/00-MANIFEST.md` and companions are KB documents.
    - `.md`, `.yaml`, `.txt` and `.csv` files inside `inventory-*` are snapshots. A binary file there produces `parse-error`.
    - `.puml`/`.mmd` files are discovered by `--all`.
    - File: `tests/test_cli_discovery.py`
    - _Requirements: R2.8, R3.5, R10.3_

- [x] 10. Linter rule registry and rule changes
  - [x] 10.1 Introduce `RuleSpec` and `RuleHit` in `src/rule_engine/linter.py`
    - Add `RuleSpec(name, default, landscape, reason_escalations)` with `severity_for`, and `RuleHit(offenders, reason, severity)`.
    - Add the `RULES` registry. Derive `RULE_SEVERITIES` and `CLASS_ESCALATIONS` from it.
    - Replace the per-predicate landscape branches (`container-padding`, `edge-direction`, `edge-float`, `entry-thirds`, `container-overlap`) with `RuleSpec.landscape`. Model the `edge-routing` `*-through-*`/`pierces-target-*` escalation as `reason_escalations`.
    - Predicates return `RuleHit`s carrying the offender ids the geometry checks already compute. `bool`/`Severity` returns stay accepted.
    - The finding shape becomes `{rule, severity, offenders, reason}`, and each result carries `label`.
    - _Requirements: R1.13, R10.1_
  - [x] 10.2 Add new rules and make the Legend, title and overlay checks structural
    - New rules:
      - `parse-error` (ERROR): fires on `parse_errors`, and all other rules are skipped for that artifact.
      - `edge-endpoint`: WARNING for `flow`, ERROR for `landscape`.
      - `source-format` (ERROR) for `.puml`/`.mmd`.
    - Rewrite `legend-present`, `title-versioned` and `overlay-legend-coverage` to use `legend_lines`, the title match and whole-token Legend-line coverage.
    - _Requirements: R1.8, R1.10, R1.11, R1.12, R10.3_
  - [x] 10.3 Wire the `frontmatter` and `secret-safety` rules to the shared modules
    - `_check_frontmatter` returns one CRITICAL `RuleHit` per `KbViolation` (`reason=constraint`, `offenders=(key,)`). Structural checks run only for KB documents.
    - `_check_secret_safety` parses JSON and calls `find_secrets`. Other text goes through `scan_text`. An unparsable snapshot `.json` is scanned as text and also gets `parse-error`. Offenders are pointers or line numbers only, never values.
    - _Requirements: R2.1–R2.8, R3.1, R3.4, R3.5, R3.6_
  - [x] 10.4 Resolve icons from the committed manifests in the `icon-resolved` rule
    - `_check_icon_resolved` keeps the placeholder markers and calls `icon_refs.resolve` for `resIcon`, `grIcon`, `azure2` and `oci-*` refs, using committed manifests only.
    - An unknown id is an ERROR with the cell id as offender. File-path refs are left to the verifier.
    - _Requirements: R4.5_
  - [x] 10.5 Update the Lint_CLI output and ruleset lookup
    - In `src/rule_engine/cli.py`, print `[BLOCKED] <label>: rule(SEV), …` followed by per-finding lines `- SEV rule [offenders]: reason`.
    - Add `--json` for the full result list and `--workspace-root`.
    - Locate the ruleset with `ruleset.require_ruleset`. `RulesetUnavailableError` exits with code 2.
    - _Requirements: R1.13, R10.2_
  - [x] 10.6 Write the property test for parse or block
    - **Property 4: Parse or block**
    - **Validates: Requirements 1.8, 1.9**
    - File: `tests/test_drawio_model_properties.py`
  - [x] 10.7 Write the property test for broken edge endpoints
    - **Property 5: Broken edge endpoints are reported by class**
    - **Validates: Requirements 1.10**
    - File: `tests/test_linter_structure_properties.py`
  - [x] 10.8 Write the property test for structural Legend, title and overlay detection
    - **Property 6: Legend, title and overlay coverage are structural**
    - **Validates: Requirements 1.11, 1.12**
    - File: `tests/test_linter_structure_properties.py`
  - [x] 10.9 Write the property test for self-explaining findings
    - **Property 7: Every finding explains itself**
    - **Validates: Requirements 1.13**
    - File: `tests/test_linter_structure_properties.py`
  - [x] 10.10 Write unit tests for the rewired rules
    - `status: bogus` and `updated: 2026-02-30` produce named CRITICAL findings.
    - A snapshot `.yaml` with `password: x` is flagged with `line:<n>` and without the value.
    - An unknown `resIcon` produces `icon-resolved` ERROR with the cell id.
    - `--json` output includes offenders.
    - Update the existing `tests/test_linter.py`, `tests/test_cli_drawio_parser.py` and `tests/test_new_rules_1_6_0.py` to the new finding shape and to `parse_artifacts`.
    - File: `tests/test_linter_1_7_0.py`
    - _Requirements: R1.13, R2.7, R3.5, R4.5_

- [x] 11. Icon_Verifier without blind spots
  - [x] 11.1 Rewrite `src/rule_engine/verify_icon.py` on `drawio_model` and `icon_refs`
    - Remove the local regexes. Report `unverified` with the cell id for a service vertex that has no verifiable ref.
    - Add `--strict`. Exit codes:
      - 1 on any `unresolved` ref;
      - 1 under `--strict` on any `unverified` ref, or when a file has service vertices and zero `resolved` refs (a `skipped` ref counts as not verified);
      - 3 on an I/O error or `DrawioParseError`.
    - Add `--all`, which walks `examples/` with the Lint_CLI discovery filters.
    - _Requirements: R4.1, R4.2, R4.3, R4.4_
  - [x] 11.2 Write the property test for Linter/verifier agreement and OCI binding
    - **Property 16: Linter and Icon_Verifier agree, and OCI glyphs are bound to their slug**
    - **Validates: Requirements 4.1, 4.5**
    - File: `tests/test_icon_refs_properties.py`
  - [x] 11.3 Write the property test for unverified vertices and strict exit codes
    - **Property 17: Unverified vertices and strict exit codes**
    - **Validates: Requirements 4.2, 4.3**
    - File: `tests/test_icon_refs_properties.py`

- [x] 12. Checkpoint: Linter and verifier
  - Run `pytest`, `rule-engine-lint --all` and `rule-engine-verify-icon --all`. New findings on `examples/` are expected at this point and are fixed in task 22. Ensure all tests pass, ask the user if questions arise.

- [x] 13. Inventory: Normalizer, Collector, snapshot gate, Delta
  - [x] 13.1 Normalizer: case-insensitive aliases and redaction
    - In `src/rule_engine/normalizer.py`, `_extract` builds `{flat(k): k}` once per resource. `_FIELD_ALIASES` become flat names. `id` consults `identity.native_identity` first.
    - Replace `_is_secret_key` with `secret_safety.is_credential_key` for the digest drop list.
    - Pass `tags` and extracted string fields through `secret_safety.redact` before building the record.
    - _Requirements: R3.6, R3.7, R5.3_
  - [x] 13.2 Write the property test for secret-free Normalized Resources
    - **Property 14: Normalized resources carry no secrets**
    - **Validates: Requirements 3.7**
    - File: `tests/test_secret_safety_properties.py`
  - [x] 13.3 Write the property test for key-case-insensitive normalization
    - **Property 18: Normalization ignores key case and separators**
    - **Validates: Requirements 5.3**
    - File: `tests/test_inventory_properties.py`
  - [x] 13.4 Collector: identity, input validation and collision-free layout
    - In `src/rule_engine/collector.py`, make `redact_secrets` an alias of `secret_safety.redact` and remove the moved marker lists and regexes.
    - `_resource_identity` returns `native_identity(...)`, else the resource name, else `content_identity(...)`. The `"resource"` fallback is removed.
    - Add `BOUNDARY_RE`, `CollectorInputError` and `_validate_target`, which runs before any filesystem call and also performs the resolve-inside-root check.
    - Add `_allocate_snapshot_dir`, which tries `folder`, `folder-2`, … with `mkdir(exist_ok=False)`.
    - Add `_resource_dirname` (at most 100 characters, with a `-<sha8>` suffix on a collision or a lossy slug). A same-identity duplicate gets a hashed subfolder and is listed under `duplicates` in the manifest. Never overwrite an existing `resource.json`.
    - _Requirements: R3.6, R5.4, R5.5, R5.6, R5.7_
  - [x] 13.5 Accept the folder suffix in `snapshot_gate`
    - In `src/rule_engine/snapshot_gate.py`, `_FOLDER_RE` accepts an optional `-<n>` suffix (n ≥ 2).
    - `parse_manifest_fields` tolerates the new `duplicates` section.
    - _Requirements: R5.4, R5.7_
  - [x] 13.6 Write the property test for the Collector passing its own gates
    - **Property 19: The Collector loses nothing and passes its own gates**
    - **Validates: Requirements 5.4, 5.5**
    - Include an assertion that `rule-engine-lint --all --workspace-root <tmp>` and `rule-engine-check-snapshot --strict` exit 0 on the collected folder.
    - File: `tests/test_inventory_properties.py`
  - [x] 13.7 Write the property test for refusing unsafe Collector inputs
    - **Property 20: Unsafe Collector inputs are refused before any write**
    - **Validates: Requirements 5.6**
    - File: `tests/test_inventory_properties.py`
  - [x] 13.8 Write the property test for repeated runs
    - **Property 21: Repeated runs never merge snapshots**
    - **Validates: Requirements 5.7**
    - File: `tests/test_inventory_properties.py`
  - [x] 13.9 Delta: boundary- and region-aware identity with explicit duplicates
    - In `src/rule_engine/delta.py`, add the `Identity(provider, resource_type, boundary, region, identity_key)` type, `DUPLICATE` and `CLASSIFICATIONS`.
    - `_index_snapshot` returns `(index, duplicates)`, and the last-writer-wins branch is removed.
    - `compute_delta` emits exactly one `duplicate` record (with `detail`) per repeated identity and does not classify it otherwise.
    - `marker_for(DUPLICATE)` returns `""`. A missing `boundary`/`region` raises `SnapshotInputError`.
    - List duplicates in the Troubleshooting section of the versioned document.
    - Update `tests/test_delta_duplicate_identity.py` and `tests/test_delta_partition_property.py` to the new behaviour.
    - _Requirements: R5.8_
  - [x] 13.10 Write the property test for the delta partition
    - **Property 22: Delta classification is a partition with explicit duplicates**
    - **Validates: Requirements 5.8**
    - File: `tests/test_inventory_properties.py`

- [x] 14. Pinned packs and a reproducible index
  - [x] 14.1 Fetcher: pins, HTTPS only, atomic download, fresh unpack
    - In `src/rule_engine/fetch_assets.py`, add `PackPinError`, `InsecureURLError`, `_https_opener` (checks the initial URL and every redirect), `_download_verified` (temp file in `cache_dir`, streaming sha256 and size, `os.replace` to `<sha256>.zip`, re-hash a cached file before reuse, ignore legacy `<key>.zip`) and `_unpack_fresh` (staging directory, zip-slip guard, swap into place).
    - Refuse a provider without a pin, with a message pointing at `--update-pins`.
    - Make the opener injectable for tests.
    - Keep `scripts/fetch_assets.py` a thin wrapper.
    - Add empty `sha256`/`size` keys per provider in `mappings/asset-sources.yaml`. They are populated in task 22.1.
    - _Requirements: R6.1, R6.2, R6.3_
  - [x] 14.2 Write the property test for pinned bytes over HTTPS
    - **Property 23: Only pinned bytes over HTTPS are unpacked**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - File: `tests/test_fetch_properties.py`
  - [x] 14.3 Write the property test for exact unpacking
    - **Property 24: Unpacking yields exactly the current pack**
    - **Validates: Requirements 6.3**
    - File: `tests/test_fetch_properties.py`
  - [x] 14.4 Asset index: meaningful slugs, ambiguity and pack digests
    - In `src/rule_engine/asset_index.py`, remove `service`, `cloud` and `public` from `_STRIP_TOKENS`.
    - `index_provider` keeps an `ambiguous` map next to `best`. Add `ResolvedAsset.candidates`. `resolve_asset` returns `unresolved` with candidates for an ambiguous exact slug.
    - `build_icon_index` writes `pack_summary[provider] = {"count", "sha256"}`, taking `sha256` from the verified pin.
    - _Requirements: R6.4, R6.6, R6.7_
  - [x] 14.5 Write the property test for slugs and ambiguity
    - **Property 26: Slugs keep meaningful words, ambiguity is never guessed**
    - **Validates: Requirements 6.6, 6.7**
    - File: `tests/test_fetch_properties.py`
  - [x] 14.6 `rule-engine-build-icon-sets`: `--update-pins` and `--manifests-dir`
    - In `src/rule_engine/build_icon_sets_cli.py`, `--update-pins [--only …]` downloads each pack over HTTPS without a pin and computes size and sha256.
    - Rewrite only the `sha256:`/`size:` lines inside each provider block with a pure function `rewrite_pins(text, updates) -> str`, so comments survive. Print old → new digests, then run the normal fetch, index and manifest build.
    - Add `--manifests-dir`, which defaults to the directory of `--out`. The aws4, azure2 and OCI-digest manifests are written there.
    - A pin mismatch fails the build with no `|| echo` fallback.
    - _Requirements: R6.5, R7.6_
  - [x] 14.7 Write the property test for pin rewriting
    - **Property 25: Pin rewriting preserves everything else**
    - **Validates: Requirements 6.5**
    - File: `tests/test_fetch_properties.py`

- [x] 15. `rule-engine-init` with a lock file
  - [x] 15.1 Implement the lock-file state machine in `src/rule_engine/init_workspace.py`
    - Write `.kiro/rule-engine-init.lock.json` (`lock_version`, `engine_version`, `source`, `files`).
    - Classify each file as missing, current, stale, edited or extra per design §9. A missing lock means any differing file is edited.
    - `--check` reports all five groups, exits 1 on missing or stale, and never creates the target (no `mkdir`).
    - A default run copies missing files, updates stale ones, keeps edited ones with their old lock hash, and writes the lock.
    - `--force` backs up each edited file to `.kiro/rule-engine-init-backup/<UTC ts>/<rel>` before overwriting it.
    - `resolve_source` order: explicit `--source`, then the repo checkout (`pyproject.toml` with `name = "rule-engine"` plus `.kiro/steering`), then the bundle, then the Power.
    - `--with-assets` passes `--manifests-dir target/mappings`. A `_within(target, path)` assertion guards every write.
    - _Requirements: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7_
  - [x] 15.2 Write the property test for the lock-file state machine
    - **Property 27: `rule-engine-init` follows the lock-file state machine**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**
    - File: `tests/test_init_properties.py`
  - [x] 15.3 Write example tests for init target and source handling
    - `--check` on a non-existent target leaves it non-existent (R7.5).
    - `--with-assets` with a monkeypatched fetch writes only under the target (R7.6).
    - With fake trees, the repo checkout wins over a stale `_bootstrap` (R7.7).
    - File: `tests/test_init_workspace.py`
    - _Requirements: R7.5, R7.6, R7.7_

- [x] 16. Checkpoint: inventory, packs, init
  - Run `pytest` and `rule-engine-lint --all`. Ensure all tests pass, ask the user if questions arise.

- [x] 17. Raster freshness and budgets
  - [x] 17.1 Exporter: provenance, scale ≥ 1, hygiene
    - In `scripts/export_raster.py`, parse the page with `drawio_model` and compute the natural width `W` as the union of vertex boxes.
    - Add a pure function `compute_scale(W, diagram_class) -> float`. It returns `clamp(target / W, 1, max / W)` and raises the split-the-diagram error when `W + 16 > max`.
    - Call draw.io with `--scale` and `timeout=180`. `TimeoutExpired` is a failure.
    - Put the temp copy under `.build-tools/export-tmp` (via `mkdtemp`) and remove it in `finally`.
    - Fail with a list of missing assets referenced by `inline_local_images`.
    - After export, insert a `tEXt` chunk `rule-engine:source-sha256` before `IEND`, built with `struct` and `zlib.crc32`. The helper `insert_provenance(png_bytes, digest)` lives in `src/rule_engine/raster_gate.py` and is shared with the checker.
    - _Requirements: R8.2, R8.4, R8.5_
  - [x] 17.2 Raster gate: provenance, height, opaque white background, no silent zero
    - In `src/rule_engine/raster_gate.py`, read all chunks. Report `stale-raster` when the chunk is missing or its digest does not match the sibling `.drawio` sha256.
    - Read the IHDR height and apply the class height ceiling (flow 1600, landscape 3600).
    - Require colour type 0 or 2 and no `tRNS`, and require row 0 (reconstructed from its filter byte) to be entirely `#FFFFFF`.
    - Exit 2 when no `.drawio` is found under `--examples`.
    - _Requirements: R8.2, R8.3_
  - [x] 17.3 Write the property test for the PNG provenance round trip
    - **Property 28: PNG provenance round trip**
    - **Validates: Requirements 8.2**
    - File: `tests/test_raster_properties.py`
  - [x] 17.4 Write the property test for raster verdicts
    - **Property 29: Raster verdicts follow the budget model**
    - **Validates: Requirements 8.3**
    - File: `tests/test_raster_properties.py`
  - [x] 17.5 Write the property test for export scale
    - **Property 30: Export scale is at least 1 or the export fails**
    - **Validates: Requirements 8.4**
    - File: `tests/test_raster_properties.py`
  - [x] 17.6 Write example tests for exporter hygiene
    - A mocked `subprocess.run` raising `TimeoutExpired` makes the export fail. A missing asset fails with a list. The temp dir is outside `examples/` and is removed afterwards.
    - Update `tests/test_raster_gate.py` for provenance and exit code 2.
    - File: `tests/test_export_raster.py`
    - _Requirements: R8.3, R8.5_

- [x] 18. Generator `--check` mode
  - [x] 18.1 Add `--check` to the HA generators
    - `scripts/ha_multiregion_common.py` → `run_cli` gains `--check`: render in memory, compare byte for byte with the committed landscape and summary files, print the first differing line, exit 1 on a difference and 2 on a missing input asset.
    - The four `build_*_ha_example.py` scripts pass the flag through.
    - Replace any `date.today()` in titles with the committed date constant.
    - _Requirements: R8.1_
  - [x] 18.2 Add `--check` to the single-example generators
    - Add the same `--check` semantics to `scripts/build_aws_infra_example.py`, `scripts/build_gcp_example.py` and `scripts/build_oci_example.py`. For OCI, a missing `stencils.json` exits 2.
    - Make the output deterministic (fixed dates, stable ordering).
    - _Requirements: R8.1_
  - [x] 18.3 Write the generator freshness smoke test
    - `tests/test_generators_fresh.py` runs all seven `--check` invocations when their assets are present and skips otherwise locally. CI runs them unconditionally.
    - _Requirements: R8.1_

- [x] 19. The Contract lints what it writes
  - [x] 19.1 Rework `contract.invoke` in `src/rule_engine/contract.py`
    - Call `ruleset.require_ruleset(workspace_root)` before any I/O and map a failure to `ContractGenerationError`.
    - `_resolve_nodes` raises `ContractGenerationError("node-count", count, limit)` instead of slicing.
    - `_render_drawio` emits nodes only, with no invented "connects to" edges. It renders a structural Legend cell and a full-format title cell.
    - Write all outputs into `root/.staging-{nn}-{uuid}`. Lint them with `cli.parse_artifacts` and `linter.lint_with_ruleset`. Move them into `root` with `os.replace` only when every artifact is eligible; otherwise remove the staging dir and raise with the per-file findings.
    - Delete `_frontmatter_dict`.
    - `related_docs` lists the real sibling file names.
    - Replace the `except SnapshotInputError` fallback with `ContractGenerationError`.
    - Update `tests/test_contract.py` for the removed edges and the new errors.
    - _Requirements: R9.1, R9.2, R9.3, R9.4, R10.2, R5.8_
  - [x] 19.2 Write the property test for the Contract publishing only gated output
    - **Property 31: The Contract publishes only what the gate passed**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - File: `tests/test_contract_properties.py`
  - [x] 19.3 Write the property test for one ruleset location
    - **Property 32: One ruleset location for CLI and Contract**
    - **Validates: Requirements 10.2**
    - File: `tests/test_ruleset_properties.py`
  - [x] 19.4 Write the example test for the Contract linting its written frontmatter
    - A monkeypatched companion renderer that writes `status: bogus` makes `invoke` raise `ContractGenerationError`, and no file lands in the output root.
    - File: `tests/test_contract_frontmatter.py`
    - _Requirements: R9.4_

- [x] 20. Checkpoint: all consumers switched over
  - Run `pytest`, `rule-engine-lint --all`, `rule-engine-verify-icon --all`, `rule-engine-check-rasters` and `rule-engine-check-snapshot --strict`. Example failures are expected until task 22. Ensure all tests pass, ask the user if questions arise.

- [x] 21. Steering, docs, packaging and CI
  - [x] 21.1 Update the `diagram-lint.md` rule and class tables
    - Add rows for `parse-error` (ERROR), `edge-endpoint` (WARNING/ERROR) and `source-format` (ERROR), with Rule Detail entries.
    - Update `frontmatter` (full contract), `secret-safety` (parsed content, all text in `inventory-*`), `icon-resolved` (committed manifests incl. OCI digests), `legend-present`/`title-versioned`/`overlay-legend-coverage` (structural), and the finding shape (offenders and reason).
    - Add `edge-endpoint` to the `## Diagram Class` table.
    - Apply the edit to all three copies.
    - _Requirements: R10.1, R10.4_
  - [x] 21.2 Write the rule-table sync test
    - `tests/test_ruleset_sync.py` parses `.kiro/steering/diagram-lint.md` with `ruleset.parse_rule_table` and asserts:
      - every table rule is in `RULES`, and every rule in code is in the table;
      - each rule's first severity equals `RuleSpec.default`;
      - each `/ERROR` matches a `landscape` or `reason_escalations` entry;
      - the escalated rules in the `## Diagram Class` table equal `CLASS_ESCALATIONS`.
    - _Requirements: R10.1_
  - [x] 21.3 Update the other steering documents and `INSTALL.md`
    - `diagram-standards.md`:
      - the Source Format matrix maps every diagram type to draw.io, with Mermaid/PlantUML not publishable (D1);
      - the raster export table gets a height ceiling row;
      - the Quick Checklist is updated to match.
    - `inventory-standards.md`: §3 documents the `-<n>` folder suffix, and the domain table mentions the role types.
    - `provider-profiles.md`: add a second table of the seven role types with per-provider native labels.
    - `asset-packs.md`: document pack pins, the digest-keyed cache, `--update-pins`, `oci-stencil-digests.json` and `verify-icon --strict`.
    - `INSTALL.md`: document `--update-pins` and the init lock file (`--check`, `--force` backups).
    - Apply the edits to all three copies.
    - _Requirements: R6.5, R7, R10.3, R5.1_
  - [x] 21.4 Update packaging and version
    - In `pyproject.toml`, set `requires-python = ">=3.11"` and rewrite the 3.14-floor comment.
    - Bump the version to 1.7.0 everywhere `tests/test_version_triple.py` and `version_guard` check.
    - _Requirements: R11.1_
  - [x] 21.5 Update the CI workflow
    - In `.github/workflows/ci.yml`:
      - set the test matrix to `["3.11", "3.12", "3.13", "3.14"]`;
      - make a pinned-fetch failure fail the job (remove `|| echo WARNING`);
      - add `rule-engine-verify-icon --all --strict`;
      - add the seven generator `--check` invocations;
      - make the raster gate run strict;
      - add `rule-engine-init --check` on a workspace with one edited file (expects "edited" and exit 0).
    - Update `tests/test_hooks_and_ci_gates.py` to assert these steps.
    - _Requirements: R4.3, R8.1, R11.2_
  - [x] 21.6 Write the CHANGELOG 1.7.0 section
    - Add a 1.7.0 section to `CHANGELOG.md` with a **Breaking changes for hand-authored artifacts** subsection. It lists every row of the design's Migration table: parser, `parse-error`, structural Legend/title, `edge-endpoint`, `source-format`, KB structure, frontmatter strictness, `secret-safety`, secret vocabulary and digests, the resource-type enum, delta identity/`duplicate`, Collector folder and naming, OCI marker and `--strict`, pins and cache, slugs, the init lock, raster provenance and scale, the Contract, Python 3.11, and the steering updates.
    - The section must pass `tests/test_changelog_section.py`.
    - _Requirements: R10.4_

- [x] 22. Migrate `examples/` to the tightened gates
  - [x] 22.1 Populate pack pins and rebuild the committed manifests
    - Run `rule-engine-build-icon-sets --update-pins` to fill `sha256`/`size` in `mappings/asset-sources.yaml`.
    - Rebuild `mappings/icon-index.json`, `mappings/oci-stencil-digests.json`, `aws4-icons.json` and `azure2-shapes.json`.
    - Re-check the `mappings/roles.yaml` queries after the slug change. `rule-engine-build-icon-sets --check` must pass, and golden resolutions must be unchanged.
    - _Requirements: R6.1, R6.4, R6.6, R4.1_
  - [x] 22.2 Regenerate the example snapshots and fix the delta documents
    - Run `scripts/build_example_snapshots.py` for `examples/aws/inventory-…` and `examples/generic/inventory-…`, with `boundary`/`region` recorded and the new digests.
    - Fix `10-delta-example.md` in both folders so every section is 100–200 words and the full KB contract is met.
    - The folders must pass `rule-engine-check-snapshot --strict` and `secret-safety`.
    - _Requirements: R3.1, R3.5, R5.4, R5.8, R10.4_
  - [x] 22.3 Fix KB structure findings in the example documents
    - Bring every companion `.diagram.md` and every other KB document under `examples/` (for example `examples/{azure,gcp,oci}/00-MANIFEST.md`) to zero `frontmatter` findings: word counts, sections, H1, lists, tables and Anti-patterns.
    - Where a generator writes the companion, fix the generator's template rather than the file, then re-run the generator. Its `--check` must still pass.
    - _Requirements: R2.1–R2.8, R10.4_
  - [x] 22.4 Convert `examples/cross-cloud/cross-cloud-composition.puml` to a `.drawio` triple (D1)
    - Author `NN-cross-cloud-composition.drawio` (C4 container, at most 12 nodes, per-profile icons and boundaries, labelled cross-provider edges, Flow/Legend in the right margin, full title), `.diagram.md` and `.drawio.png`.
    - Remove the `.puml` and update references in docs and tests.
    - _Requirements: R10.3, R10.4_
  - [x] 22.5 Convert `examples/generic/generic-reference-architecture.puml` to a `.drawio` triple (D1)
    - Author the grayscale generic-profile `.drawio` with dashed green and blue boundaries, plus its `.diagram.md` and `.drawio.png`.
    - Remove the `.puml` and update references in docs and tests.
    - _Requirements: R10.3, R10.4_
  - [x] 22.6 Tighten the hand-authored flow layouts (D8) and fix new routing findings
    - In `examples/aws/01-aws-agent-platform.drawio` and `examples/azure/01-azure-openai-rag.drawio`, pin the Flow/Legend block narrower (the sanctioned wrap-taller exception) so `W + 16 ≤ 1600`.
    - Fix any `edge-routing`, `edge-approach` or `edge-endpoint` findings exposed by the Array-only waypoints and parent-offset parsing. Use `scripts/orthogonalise_drawio.py` where applicable.
    - _Requirements: R8.4, R1.6, R10.4_
  - [x] 22.7 Tighten the generated flow layouts (D8) and regenerate
    - Narrow the pinned `legend_w` (or equivalent) in `scripts/build_aws_infra_example.py` (`aws/03`), `scripts/build_gcp_example.py` (`gcp/01`) and `scripts/build_oci_example.py` (`oci/01`, which also gains the `ociSlug=` marker) so each canvas fits 1600 px at scale 1.
    - Regenerate each output. `--check` passes afterwards.
    - _Requirements: R8.1, R8.4, R4.1, R10.4_
  - [x] 22.8 Regenerate the four HA pairs and confirm overlay coverage
    - Run the four `build_*_ha_example.py` scripts (OCI HA gains `ociSlug=`).
    - Confirm that each of the 11 `overlay=` terms per landscape appears as a Legend line.
    - `--check` passes afterwards.
    - _Requirements: R1.12, R4.1, R8.1, R10.4_
  - [x] 22.9 Re-export every example PNG with provenance
    - Run `scripts/export_raster.py` for all 15 `.drawio` files (13 existing plus 2 converted).
    - `rule-engine-check-rasters` must pass with provenance, width, height and white-background checks.
    - _Requirements: R8.2, R8.3, R8.4, R10.4_
  - [x] 22.10 Extend the golden-example tests
    - `tests/test_golden_examples.py` asserts zero blocking findings for every example artifact.
    - It also asserts that `verify_icon --strict` passes on every committed `.drawio` using the committed manifests (OCI via digests; GCP file paths skipped when assets are absent locally).
    - Remove `.puml` expectations from `tests/test_golden_examples.py` and `tests/test_ha_generator_parity.py` where present.
    - _Requirements: R4.3, R10.4_

- [x] 23. Final checkpoint: release gates green
  - Run `pytest`, `rule-engine-lint --all`, `rule-engine-verify-icon --all --strict`, the seven generator `--check` runs, `rule-engine-check-rasters`, `rule-engine-check-snapshot --strict` and `rule-engine-build-icon-sets --check`. All must be green. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP. The 32 property sub-tasks map one-to-one onto design Properties 1–32.
- Decisions D1–D8 are adopted working assumptions. Overturning D1 removes tasks 22.4 and 22.5 and the `source-format` rule. Overturning D8 replaces tasks 22.6 and 22.7 with a flow-budget change in `raster_gate`, `export_raster` and `diagram-standards.md`.
- Property sub-tasks that share a test file are placed in different waves below to avoid write conflicts.
- Tasks 22.1, 22.9 and parts of 22.7 and 22.8 need network access (vendor packs) and a local draw.io install for export.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1", "6.1", "7.1"] },
    { "id": 1, "tasks": ["2.2", "3.2", "4.1", "4.2", "5.1", "6.2", "7.2", "2.3"] },
    { "id": 2, "tasks": ["3.3", "4.3", "5.2", "5.4", "6.3", "9.1"] },
    { "id": 3, "tasks": ["3.4", "5.3", "6.4", "9.2", "9.3"] },
    { "id": 4, "tasks": ["9.4", "10.1"] },
    { "id": 5, "tasks": ["9.5", "9.6", "10.2"] },
    { "id": 6, "tasks": ["10.3", "10.5", "11.1", "13.1", "14.1"] },
    { "id": 7, "tasks": ["10.4", "10.6", "13.2", "13.3", "13.4", "14.2", "14.4"] },
    { "id": 8, "tasks": ["10.7", "10.10", "11.2", "13.5", "13.9", "14.3", "14.6"] },
    { "id": 9, "tasks": ["10.8", "11.3", "13.6", "14.5", "15.1", "17.1", "18.1"] },
    { "id": 10, "tasks": ["10.9", "13.7", "14.7", "15.2", "17.2", "18.2", "19.1"] },
    { "id": 11, "tasks": ["13.8", "15.3", "17.3", "17.6", "18.3", "19.2", "19.3", "19.4"] },
    { "id": 12, "tasks": ["13.10", "17.4", "21.1", "21.3", "21.4"] },
    { "id": 13, "tasks": ["17.5", "21.2", "21.5", "21.6", "22.1"] },
    { "id": 14, "tasks": ["22.2", "22.4", "22.6", "22.7", "22.8"] },
    { "id": 15, "tasks": ["22.3", "22.5"] },
    { "id": 16, "tasks": ["22.9"] },
    { "id": 17, "tasks": ["22.10"] }
  ]
}
```
