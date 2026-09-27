# Requirements Document

**Feature:** Honest Gates (release 1.7.0)

> **Status: draft for review (2026-09-26).** This document builds on the
> project review of 2026-09-26 and on hotfix 1.6.1 (PR #5). Markers such as
> *(review H1)* point to the finding each requirement grew out of. The
> "Open decisions" section must be closed before the design phase.

## Introduction

This spec removes a class of defects where a gate reports "OK" without having
actually checked anything. This applies especially to hand-authored artifacts,
which are exactly what an agent produces for a user of the Power.

Why this is a separate minor release rather than a patch: every requirement
below makes a check stricter, so it may block an artifact that passes today.
Hotfix 1.6.1 deliberately made only safe-direction changes.

Release outcomes:

- an XML parser for `.drawio` that sees compressed, multi-page and wrapped
  diagrams and blocks them when it cannot parse them;
- a full validator for KB frontmatter and document structure;
- `secret-safety` that analyses parsed JSON rather than substrings;
- icon verification that covers OCI and does not accept "0 checked" as success;
- an inventory schema that accommodates every diagram role, and a collector
  manifest that passes its own linter;
- icon packs pinned by digest and a reproducible index;
- a `rule-engine-init` that detects edited and stale files;
- freshness control for generated examples and rasters;
- a contract that lints what it actually writes;
- a test that keeps the `diagram-lint.md` rule table in sync with the code.

### Out of scope (1.8.0)

- The "snapshot → layout engine → `.drawio`" CLI and moving the
  `scripts/ha_multiregion_common.py` adapter into the package.
- Generalising the layout engine to N regions, classifying edges by declared
  region, and an oracle with the same blocking set as the linter.
- Trimming the always-on steering (≈ 22.5k words) down to a normative core.
- Scored router (see `docs/REVIEW.md` → Open gaps).

## Glossary

- **Linter**: `rule_engine.linter` together with the parsers in
  `rule_engine.cli` (`rule-engine-lint`).
- **Lint_CLI**: the `rule-engine-lint` command-line entry point of the Linter.
- **Artifact**: a file evaluated by the Linter: a diagram (`.drawio`, `.puml`,
  `.mmd`), a KB document (`.md`) or a snapshot file (`.json`).
- **Diagram_Page**: one `<diagram>` element in a `.drawio` file.
- **Compressed_Page**: a `<diagram>` whose text content has the form
  `base64(deflateRaw(encodeURIComponent(<mxGraphModel>)))`.
- **Wrapper**: a `UserObject` or `object` element that contains an `mxCell` and
  holds the cell's `id` and `label`.
- **Blocking_Finding**: a finding with severity ERROR or CRITICAL.
- **Icon_Verifier**: `rule-engine-verify-icon`.
- **Pack_Pin**: a `sha256` + `size` pair for a vendor archive in
  `mappings/asset-sources.yaml`.
- **Workspace_Lock_File**: `.kiro/rule-engine-init.lock.json`: the engine
  version and the sha256 of every copied file.
- **Generated_Example**: a `.drawio` in `examples/` that has a generator in
  `scripts/`.
- **Example_Generator**: a script in `scripts/` that produces a
  Generated_Example.
- **Inventory_Schema**: `schemas/inventory.schema.json`, the Normalized
  Resource schema.
- **Terminology_Profile**: `profiles/terminology.yaml`.
- **Collector**: the Inventory Collector that writes snapshot folders.
- **Normalizer**: the component that converts provider responses into
  Normalized Resources.
- **Delta_Engine**: the component that computes the delta between snapshots.
- **Fetcher**: the vendor-pack downloader (`scripts/fetch_assets.py`).
- **Icon_Index**: `mappings/icon-index.json`.
- **Slug_Normalizer**: the function that normalizes service names to slugs in
  the asset index.
- **Resolver**: the component that resolves a service or role to an icon via
  the asset index.
- **Init_Command**: `rule-engine-init`.
- **Raster_Exporter**: `scripts/export_raster.py`.
- **Raster_Checker**: `rule-engine-check-rasters`.
- **Contract**: `contract.invoke`.
- **CI_Pipeline**: the repository's continuous-integration workflow.
- **Test_Suite**: the repository's automated test suite.
- **Release**: the published 1.7.0 package together with its `examples/` and
  `CHANGELOG.md`.
- **Package_Metadata**: `pyproject.toml`.

## Requirements

### Requirement 1: Parse `.drawio` with an XML parser

**User Story:** As a diagram author, I want the Linter to see the same model
that draw.io renders, so that a "clean" result means a clean diagram rather
than an unparsed file. *(review H1, H2, H4, M1–M3, M5)*

#### Acceptance Criteria

1. WHEN the Linter receives a `.drawio` file, THE Linter SHALL parse the file
   with an XML parser rather than with regular expressions.
2. WHEN a Diagram_Page is a Compressed_Page, THE Linter SHALL decompress the
   Diagram_Page and evaluate the decompressed model.
3. WHEN a file contains several Diagram_Pages, THE Linter SHALL evaluate each
   Diagram_Page as a separate Artifact and label its findings as
   `<file>#<page name>`.
4. WHEN an `mxCell` is enclosed in a Wrapper, THE Linter SHALL take the `id`
   and `label` from the Wrapper.
5. THE Linter SHALL decode XML entities and strip HTML markup from labels
   before evaluating the rules that check node names.
6. THE Linter SHALL read waypoints only from `<Array as="points">`, add the
   origin of the edge's parent cell to them, and treat a missing coordinate as
   zero.
7. THE Linter SHALL take the grid step from the model's `gridSize` attribute
   and, when that attribute is absent, use 10.
8. IF a file does not parse as XML, a Diagram_Page cannot be decompressed, or
   geometry construction raises an exception, THEN THE Linter SHALL emit a
   `parse-error` Blocking_Finding that names the file and the cause, instead of
   silently skipping the geometry rules.
9. IF a document contains a DTD or entity declaration, THEN THE Linter SHALL
   reject the document with a `parse-error` finding.
10. IF an edge references a non-existent `source` or `target`, or has neither,
    THEN THE Linter SHALL emit a finding (ERROR for `landscape`, WARNING for
    `flow`).
11. THE Linter SHALL identify the Legend and the title cell by structure (a
    text cell whose first line is `Legend`; the full title format) rather than
    by an occurrence of the word `legend` or of a `vN` token anywhere in the
    file.
12. THE Linter SHALL treat `overlay-legend-coverage` terms as documented only
    when the terms appear in Legend lines.
13. THE Linter SHALL include in every finding the identifiers of the offenders
    (node, edge or container id) and the reason, and THE Lint_CLI SHALL print
    them.

### Requirement 2: KB frontmatter and document-structure validator

**User Story:** As a knowledge-base owner, I want the `frontmatter` rule to
check the whole `kb-frontmatter.md` contract rather than only the presence of
keys, so that a document with `status: bogus` and the date `2026-02-30` is not
published. *(review H3)*

#### Acceptance Criteria

1. THE Linter SHALL accept `status` only with the values `draft`, `review` or
   `published`.
2. THE Linter SHALL accept `updated` and `next_review_date` only as real
   calendar dates in `YYYY-MM-DD` form.
3. THE Linter SHALL require `tags` to be a list of 1–20 entries and
   `related_docs` to be a list of 0–20 entries.
4. THE Linter SHALL check the total length (300–2000 words), the presence and
   length of the four required sections (100–200 words each), exactly one H1,
   list nesting no deeper than two levels, tables no wider than five columns,
   and an `Anti-patterns` section in any document that contains a fenced code
   block.
5. IF the frontmatter does not parse as YAML, THEN THE Linter SHALL emit a
   `frontmatter` finding rather than falling back to a lenient fallback parser.
6. THE Linter SHALL ignore a UTF-8 BOM before the opening `---`.
7. THE Linter SHALL name the key or the violated constraint in every
   `frontmatter` finding (AC 8.9, AC 8.10 of `kb-frontmatter.md`).
8. THE Linter SHALL apply the structural checks of criterion 4 only to
   generated KB documents, not to steering files, SKILL.md or repository
   documents.

### Requirement 3: `secret-safety` on parsed content

**User Story:** As an inventory operator, I want the Linter to find real
secrets in a snapshot without blocking metadata, so that the last line of
defence is neither leaky nor noisy. *(review H10)*

#### Acceptance Criteria

1. WHEN a snapshot file is JSON, THE Linter SHALL parse the file and
   recursively check key names and values.
2. THE Linter SHALL detect a secret when a value sits under a key that denotes
   credentials (password, secret, token, sessionToken, clientSecret,
   accountKey, sharedAccessKey, connectionString, privateKey, etc.), ignoring
   case and separators.
3. THE Linter SHALL detect a secret by the shape of a value: a PEM
   `PRIVATE KEY`, an AWS key identifier paired with a secret, `AccountKey=`,
   `SharedAccessKey=`, `sig=` in a SAS URL, a password in the userinfo of a
   URL, or a JWT.
4. THE Linter SHALL NOT emit a finding for the value `[REDACTED]`, for
   `Type: SecureString` metadata, for `privateKeyType`, or for a public
   certificate.
5. THE Linter SHALL check every text file in an `inventory-*` folder, not only
   `.json` files.
6. THE Collector, THE Normalizer and THE Linter SHALL take the secret
   vocabulary from one shared module.
7. THE Normalizer SHALL pass tags and values through the shared secret
   redactor before the Normalized Resource is written.

### Requirement 4: Icon verification without blind spots

**User Story:** As a reviewer, I want `rule-engine-verify-icon` to check every
icon of every provider, so that "0 unresolved" means a check happened rather
than that none did. *(review H4, M6)*

#### Acceptance Criteria

1. THE Icon_Verifier SHALL verify embedded OCI stencils by slug from
   `stencils.json` (via a marker in the style or a hash of the stencil
   content).
2. THE Icon_Verifier SHALL report a service vertex that has no verifiable
   reference as `unverified`.
3. WHERE `--strict` is passed, THE Icon_Verifier SHALL exit with a non-zero
   code if at least one vertex is `unverified` or if a file with service
   vertices has no verified reference, and THE CI_Pipeline SHALL run the
   Icon_Verifier with `--strict`.
4. IF an `image=` path escapes the `assets/` root or does not end in `.svg` or
   `.png`, THEN THE Icon_Verifier SHALL mark the reference as `unresolved`.
5. THE Linter SHALL, in the `icon-resolved` rule, check `resIcon`, `grIcon`
   and azure2 paths against the same committed manifests as the Icon_Verifier
   and emit an ERROR for an unknown id.

### Requirement 5: Inventory schema, normalization and collector manifest

**User Story:** As an inventory operator, I want every resource that has a
diagram role to be recordable validly, and the Collector's snapshot to pass its
own gates, so that "inventory → diagram" does not lose EC2, EFS or CDN.
*(review §6 Inventory, H5 of the inventory review)*

#### Acceptance Criteria

1. THE Inventory_Schema SHALL admit the seven diagram roles missing today:
   `compute_instance`, `file_system`, `cdn`, `dns`, `waf`, `lb`, `cache` (shape
   defined by decision D4).
2. THE Terminology_Profile SHALL contain native-type aliases for these roles
   for each of the four vendors.
3. THE Normalizer SHALL match field aliases case-insensitively, so that
   PascalCase SDK responses (`InstanceId`, `Tags`) are normalized.
4. THE Collector SHALL write a `00-MANIFEST.md` that passes `rule-engine-lint`
   and `rule-engine-check-snapshot` (shape defined by decision D5).
5. THE Collector SHALL determine resource identity by provider-specific keys,
   case-insensitively (`InstanceId`, `FunctionArn`, `FileSystemId`,
   `selfLink`, `ocid` …), and SHALL NOT overwrite another resource's
   subfolder.
6. IF `boundary_id` or `region` contains characters outside
   `[A-Za-z0-9._:-]`, or the snapshot path escapes `output_root`, THEN THE
   Collector SHALL refuse the run before writing any file.
7. IF a snapshot folder with the same name already exists, THEN THE Collector
   SHALL create a new folder (with a suffix) instead of merging with the old
   content.
8. THE Delta_Engine SHALL include `boundary` and `region` in resource identity
   and emit an explicit `duplicate` entry instead of a silent
   last-writer-wins.

### Requirement 6: Pinned icon packs and a reproducible index

**User Story:** As a maintainer, I want the downloaded vendor packs to be
exactly the ones that were indexed, so that a tampered or updated archive does
not silently change icons. *(review H13, M2 of the distribution review)*

#### Acceptance Criteria

1. THE `mappings/asset-sources.yaml` file SHALL contain a Pack_Pin for every
   provider, and THE Fetcher SHALL verify the Pack_Pin before unpacking.
2. THE Fetcher SHALL accept only HTTPS, including at every redirect step.
3. THE Fetcher SHALL download atomically (a temporary file and `os.replace`),
   key the cache by digest, and unpack into a fresh directory, so that stale
   files do not reach the index.
4. THE Icon_Index SHALL record the sha256 of every pack in `pack_summary`.
5. THE Rule Engine SHALL provide a documented command that updates the
   Pack_Pins and rebuilds the index in one step.
6. THE Slug_Normalizer SHALL NOT strip the words `service`, `cloud` or
   `public` from meaningful names, so that distinct services (*Private Link*
   and *Private Link Service*) remain reachable.
7. IF an exact slug match is ambiguous, THEN THE Resolver SHALL return
   `unresolved` with the list of candidates instead of an arbitrary one.

### Requirement 7: A `rule-engine-init` that detects changes

**User Story:** As a user of the Power, I want an engine upgrade to show which
rules in my workspace are stale or edited, so that `--check` does not report
"OK" over outdated rules. *(distribution review M3, M4)*

#### Acceptance Criteria

1. THE Init_Command SHALL write the Workspace_Lock_File.
2. WHEN `rule-engine-init --check` runs, THE Init_Command SHALL report missing,
   edited, stale and extra files separately, and SHALL exit with a non-zero
   code if any file is missing or stale.
3. WHEN the Init_Command runs without flags, THE Init_Command SHALL update only
   the files whose hash matches the Workspace_Lock_File and leave user-edited
   files unchanged.
4. WHERE `--force` is passed, THE Init_Command SHALL back up every edited file
   before overwriting it.
5. WHERE `--check` is passed, THE Init_Command SHALL NOT create the target
   directory.
6. WHERE `--with-assets` is passed, THE Init_Command SHALL write only inside
   the target workspace.
7. WHEN `rule-engine-init` runs from a repository checkout, THE Init_Command
   SHALL use the repository tree as its source rather than the built
   `_bootstrap`, which may be stale.

### Requirement 8: Freshness of generated examples and rasters

**User Story:** As a reviewer, I want CI to catch a divergence between a
generator, the committed `.drawio` and its PNG, so that examples do not go
stale silently after an engine change. *(review M3, M4, M5 of the layout
review)*

#### Acceptance Criteria

1. THE Example_Generator SHALL provide a `--check` mode that compares its
   output with the committed file without writing, and THE CI_Pipeline SHALL
   run that mode for all eleven Generated_Examples.
2. THE Raster_Exporter SHALL write the sha256 of the source `.drawio` into a
   PNG tEXt chunk, and THE Raster_Checker SHALL fail on a mismatch.
3. THE Raster_Checker SHALL also check the height and an opaque white
   background, and SHALL exit with a non-zero code if no source is found in
   CI.
4. THE Raster_Exporter SHALL export at a scale of at least 1, and SHALL fail
   with an error when a diagram does not fit the budget of its class at that
   scale (the "split the diagram" signal).
5. THE Raster_Exporter SHALL run with a timeout, keep its temporary copy
   outside `examples/`, and fail when an asset is missing instead of reporting
   "OK".

### Requirement 9: The Contract lints what it writes

**User Story:** As a user of `contract.invoke`, I want the generated artifact
set to be evaluated by the same gates as any other file, so that the Contract
does not publish invented relationships. *(review H11, M9)*

#### Acceptance Criteria

1. THE Contract SHALL lint the written files through the same parser as
   `rule-engine-lint --file` rather than through a synthetic `Artifact`.
2. THE Contract SHALL NOT create edges that are absent from the input data.
3. IF the node count exceeds the limit of the diagram class, THEN THE Contract
   SHALL return an error that names the count and the limit instead of
   silently dropping resources.
4. THE Contract SHALL lint the same frontmatter that the Contract writes to the
   file.

### Requirement 10: Rules, code and standards stay consistent

**User Story:** As a maintainer, I want the rule table, the severities in code
and the format matrix in the standards to be unable to diverge unnoticed.
*(review H5, H7)*

#### Acceptance Criteria

1. THE Test_Suite SHALL include a test that parses the rule table and the
   class-escalation table in `diagram-lint.md` and fails on any mismatch with
   `RULE_SEVERITIES` and the escalations in code.
2. THE Contract and THE Lint_CLI SHALL locate the ruleset the same way and
   SHALL fail closed when the ruleset is absent.
3. THE Linter SHALL lint every source format that the `diagram-standards.md`
   matrix requires for a diagram type, and `rule-engine-lint --all` SHALL
   include that format (shape defined by decision D1).
4. WHEN 1.7.0 is published, THE Release SHALL have every example in
   `examples/` passing all new and tightened checks, and a CHANGELOG that lists
   each of those checks as a breaking change for hand-authored artifacts.

### Requirement 11: Supported Python versions

**User Story:** As a user, I want to install the engine on a supported Python
that is no newer than the code requires. *(review M3)*

#### Acceptance Criteria

1. THE Package_Metadata SHALL declare the lower bound defined by decision D6.
2. THE CI_Pipeline SHALL run the tests on every minor Python version from the
   lower bound up to 3.14.

## Open decisions

| # | Question | Options | Recommendation |
| --- | --- | --- | --- |
| D1 | Format of architecture diagrams | (a) draw.io is canonical and the matrix is updated; (b) add PlantUML/Mermaid linting | (a): all examples and the triple are already draw.io |
| D2 | Severity of the new checks | final immediately; or WARNING for one release, then final | final, because the examples are fixed in the same release |
| D3 | Bare `key` key in the redactor | secret everywhere; except `{Key, Value}` pairs (1.6.1); a separate list of metadata keys | keep the 1.6.1 rule and add a metadata-key list |
| D4 | Roles in the schema | extend `resource_type`; add a separate `role` field | extend the enum: one source of truth |
| D5 | Collector manifest | frontmatter + sections; or exclude `inventory-*/00-MANIFEST.md` from the KB rule | exclude it and hand it to `snapshot_gate` |
| D6 | Python lower bound | 3.11; 3.12 | 3.11: the code uses no newer features |
| D7 | Updating pack pins | manually via a command; a scheduled CI job that opens a PR | the command now, the job later |
