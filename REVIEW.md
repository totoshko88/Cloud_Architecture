# Architecture Review — Diagram & Inventory Rule Engine

**Reviewed version:** 1.1.0 **Review date:** 2026-09-22 **Scope:** `src/rule_engine/` core, `.kiro/steering/` rules, `mappings/`, `schemas/`, `examples/`, CI pipeline, packaging.

---

## 1. Summary

The project is a mature, well-structured, cloud-agnostic Kiro engine for deterministic generation of architecture diagrams and inventory documents across five provider profiles (`aws`, `azure`, `gcp`, `oci`, `generic`).

Strengths:

- Clean separation of a **provider-neutral core** (`linter`, `icon_resolver`, `collector`, `normalizer`, `delta`, `contract`, `version_guard`) from **per-provider profile data**.
- Authoritative, always-on steering documents with explicit requirement traceability (e.g. R7 AC14 ruleset-unavailable fail-closed behavior).
- Deterministic, order-independent `config_digest` canonicalization (sorted keys, sorted array elements, secret-field stripping).
- Strong property-based test coverage (`hypothesis`) across normalizer, icon resolver, and delta engine.
- Fail-closed CI gating (`--fail-on error,critical`, `version-guard` before `build`).

The findings below are ordered by severity. Line references are approximate and should be re-confirmed at edit time.

---

## 2. Critical findings

### C1 — Terminology / provider table duplicated in four places (DRY violation)

The neutral-concept → per-provider mapping is maintained independently in:

- `.kiro/steering/provider-profiles.md` — Terminology Normalization Table (declared authoritative)
- `src/rule_engine/normalizer.py` — `_NATIVE_ALIASES`
- `src/rule_engine/contract.py` — `_PROVIDER_LABELS`
- `src/rule_engine/assets/enumerate.py` — `_SEED`

This directly contradicts the project's stated principle: *"a new provider is added by data, not by changing core code."* Today, adding a provider requires editing at least three Python modules plus the mapping YAML and steering doc, with no mechanism guaranteeing they stay consistent.

**Recommendation:** introduce a single machine-readable source of truth (e.g. `profiles/<provider>.yaml` or one `terminology.yaml`) and have the normalizer, contract, and asset seed **read** from it. The steering table can be generated from (or validated against) the same source in CI.

### C2 — `icon-resolved` rule is effectively dead for real `.drawio` files

In `cli._parse_drawio`, every vertex carrying a `style` attribute is appended to `icons` as `{"style": style, "resolved": True}` unconditionally. Because the parser never emits an unresolved descriptor, the `icon-resolved` (ERROR) rule can never fire on a parsed `.drawio` file — it only fires on `Artifact` objects constructed programmatically (i.e. in unit tests). The primary CI/CLI path (`rule-engine-lint --all`) cannot catch a placeholder icon.

**Recommendation:** detect unresolved/placeholder styles during parsing (e.g. empty style, `shape=none`, a placeholder marker, or a style not matching any known provider stencil prefix) and mark those descriptors `resolved: False`.

### C3 — `secret-safety` (CRITICAL) is never applied by CI/CLI

`cli.discover_artifacts` collects only `.drawio` files and *generated* Markdown documents. Snapshot files are JSON (`examples/**/sample-resource.json`, `inventory-*/` snapshot folders) and are therefore never linted under `--all`. The `secret-safety` rule — the most important CRITICAL gate — thus never runs in the pipeline. Its `_content_has_secret` heuristic and the `contains_secret` flag are exercised only by unit tests.

**Recommendation:** either (a) extend `discover_artifacts` to include snapshot JSON files and route them through the linter as `kind="snapshot"`, or (b) add a dedicated CI step that scans snapshot files for secret material. Option (a) keeps the linter as the single gate.

### C4 — Fragile boundary-container detection can inflate `node-count`

`cli._parse_drawio` classifies a vertex as a Boundary/Network-Boundary container only when its `id` starts with `boundary` **or** its style contains both `dashed=1` and `fillcolor=none`. But the AWS profile container style (`mappings/aws-icons.yaml`) is `shape=mxgraph.aws4.group;...;dashed=0`. Such a container is **not** added to `boundary_ids`, is not a text cell, and is parented to the root layer — so it is counted as a regular node. This can push a valid AWS diagram over the 12-node cap and raise a false `node-count` ERROR, and it also breaks the "children parented to a container are top-level nodes" logic (their parent won't be in `node_container_parents`).

**Recommendation:** detect containers more robustly — e.g. any style containing `;group` / `shape=...group`, any vertex that has child vertices parented to it, or an explicit `container=1` — rather than relying on `dashed=1;fillColor=none` alone.

---

## 3. Unification / consistency

### U1 — `PROVIDERS` and `RESOURCE_TYPES` constants duplicated across modules

The five-provider tuple and the nine neutral resource types are re-declared in `icon_resolver.py`, `normalizer.py`, `contract.py`, `collector.py`, and `asset_index.py`.

**Recommendation:** centralize in a single `rule_engine/constants.py` and import everywhere. Removes drift risk when the enum changes (it already must stay in lockstep with `schemas/inventory.schema.json`).

### U2 — Two divergent secret-marker lists

`linter._SECRET_MARKERS` (raw-content scan) and `normalizer._SECRET_KEY_SUBSTRINGS` (config-key drop list) are different sets. A field could be dropped from the hash by the normalizer but missed by the linter's content scan, or vice versa — an inconsistent secret-safety surface.

**Recommendation:** define one shared secret-marker vocabulary (e.g. in `constants.py` or a small `secrets.py`) and consume it from both the linter and the normalizer.

### U3 — On-disk asset-pack duplication

Provider icons are materialized in more than one tree under `.build-tools/` (e.g. `assets-raw/*.zip` plus `assets-raw/unpacked/`, `oci-glyphs/`, and the large `asset-index.json` / `plantuml.jar`). This is tens of MB of local duplication.

**Recommendation:** confirm a single canonical unpacked path is used by `asset_index.py` and drop the redundant copies from the working tree. (These are already git-ignored — see G1 — so this is a local-hygiene / build-reproducibility concern, not a repo concern.)

---

## 4. Repository & packaging hygiene

### G1 — Most build artifacts are already git-ignored (corrected observation)

`.gitignore` already covers `*.egg-info/`, `.hypothesis/`, `release-dist/`, `.DS_Store`, and `assets/` / `asset-index.json` / `.build-tools/`. So these files are local-only and do **not** pollute the repository. The one gap:

- `examples/aws/.$01-aws-agent-platform.drawio.bkp` — a draw.io backup file, **not** matched by any `.gitignore` rule.

**Recommendation:** add a `*.bkp` (and `.$*.drawio.bkp`) rule to `.gitignore` and remove the stray backup file.

### G2 — `requires-python = ">=3.14"` is aggressive

`pyproject.toml` targets Python `>=3.14` and the CI image is `python:3.14-slim`. The core uses only stdlib plus `jsonschema` / `PyYAML` — no 3.14-specific language features are apparent. This bar excludes most current environments and risks image-availability issues.

**Recommendation:** lower to `>=3.11` (or `>=3.12`) unless a concrete 3.14-only dependency exists. Document the reason inline if 3.14 is intentional.

### G3 — Test-only dependencies declared as runtime

`pyproject.toml` lists `hypothesis` and `pytest` under `[project.dependencies]`. These are dev/test tools and should not be installed for downstream consumers of the engine.

**Recommendation:** move them to `[project.optional-dependencies].dev` (or a `test` extra) and install via `pip install -e ".[dev]"` in CI.

### G4 — Changelog: 1.0.0 and 1.1.0 share the same date

Both releases are dated `2026-09-22`. Formally valid, but it reads as synthetic history.

**Recommendation:** separate the dates or add a note explaining the same-day double release.

---

## 5. Minor / positive

- `version_guard` (duplicate-version fail-closed), severity separation, and the ruleset-unavailable behavior (R7 AC14) are implemented cleanly and well-tested.
- `config_digest` canonicalization is correct and deterministic. 👍
- The OCI embedded-stencil renderer (`diagram_layout.embed_oci_stencil`), which strips the stencil's baked-in caption and rescales the glyph square, is a neat solution for a provider with no built-in draw.io library.
- Note: the `contains_secret` field rendered as `[REDACTED_PASSWORD]` in some readers is a **display-time redaction artifact** of the viewer, not a real code issue — the field is a plain boolean in source.

---

## 6. Suggested remediation order

1. **C1** — single source of truth for the terminology/provider table (highest leverage; unblocks the "add a provider by data" promise).
2. **C2 + C4** — fix the `.drawio` parser so `icon-resolved` and `node-count` are correct on real files.
3. **C3** — route snapshot JSON through `secret-safety` in CI.
4. **U1 + U2** — extract shared `constants.py` / secret vocabulary.
5. **G1–G4** — packaging and hygiene cleanups.

