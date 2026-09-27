# Design Document

**Feature:** Provider Diagram Conventions & Best-Practice Alignment (release 1.10.0)

> **Status: draft for review.** Requirements-first workflow: this design realises
> `requirements.md` (Requirements 1–11, items A–I). Each Component names the file
> it lives in and the Requirement/AC it satisfies. Correctness Properties are the
> checkable invariants the tasks turn into tests.

## Overview

Three new **WARNING** lint rules (`edge-bidirectional`, `node-label-length`,
`ip-range`), one companion-driven raster mode (`raster_background`), two optional
companion frontmatter keys (`change_log`, `external_refs`), one overlay term
(`callout`), and a set of steering-only guidance blocks (C4 layering, diagram-type
taxonomy, retire-inaccurate, grouping strategies). No geometry constant, no
solver, and no existing rule changes. All enforcement is additive and advisory.

The design deliberately splits into **enforced** parts (A–D, G) and
**guidance** parts (E, F, H, I). The enforced parts get code + tests + a
rule-table row; the guidance parts are steering edits verified only by the
existing structural/sync checks.

## Architecture

```
diagram-lint.md (rule table) ──sync test── linter.py (rule registry)
                                              ├─ edge-bidirectional (A)   ← geometry edge arrow tokens
                                              ├─ node-label-length  (B)   ← artifact node_names
                                              └─ ip-range           (C)   ← artifact on-diagram text (network only)
raster_gate.py ── reads Companion raster_background (D) ── white|transparent check
kb-frontmatter.md ── documents change_log / external_refs (G) ── linter frontmatter date check
diagram-standards.md ── C4 layering (E), diagram-type taxonomy (F),
                        retire-inaccurate (H), grouping strategies (I),
                        bidirectional convention (A), callout+label (B),
                        IP ranges (C), raster mode (D)

rule-engine-draw (J):  Snapshot ──reconcile.role_of──▶ roles
                            │  lane-assign (role→lane) + containers (boundary meta)
                            ▼
                        DiagramSpec ──layout()──▶ PlacedDiagram ──build_diagram()──▶ triple
                            │                                     (reconcile-clean for landscape)
                            └─ companion .diagram.md (frontmatter, summary_of/detailed_view)
```

## Components and Interfaces

### Part A — `edge-bidirectional` (Requirement 1)

- **A1. Rule predicate** (`linter.py`): `_check_edge_bidirectional(a)` reads each
  parsed edge's arrow tokens. A Bidirectional_Edge has both a non-`none`
  `startArrow` and a non-`none` `endArrow` (defaults resolved: an unspecified
  `startArrow` is `none`, an unspecified `endArrow` defaults to a head, so the
  common single-head edge — start `none`, end set — is **not** flagged). Requires
  the CLI parser to expose `start_arrow`/`end_arrow` per edge; `geometry.py`
  already parses `end_arrow`/`end_fill` for `arrow-style`, so A1 extends it with
  `start_arrow`. *(AC 1.1, 1.2)*
- **A2. Rule registration + table** (`linter.py`, `diagram-lint.md`): register
  `RULE_EDGE_BIDIRECTIONAL` (WARNING) and add the table row. *(AC 1.4)*
- **A3. Steering convention** (`diagram-standards.md`, Edge Routing): two
  single-ended edges preferred; never a double head. *(AC 1.3)*

### Part B — callouts + `node-label-length` (Requirement 2)

- **B1. Rule predicate** (`linter.py`): `_check_node_label_length(a)` flags a
  Node_Label with > 4 whitespace-delimited words or > 40 characters. Applies to
  service-node labels only (`_is_diagram` and the node came from an icon cell);
  Legend/Flow/title/Callout text cells are not in `node_names`. *(AC 2.1, 2.2)*
- **B2. `callout` overlay term** (`diagram-standards.md` Overlay Vocabulary):
  add `callout` to the vocabulary; a `callout` cell carries `overlay=callout`,
  is a text cell (not counted as a node), and is covered by
  `overlay-legend-coverage` when used. *(AC 2.3)*
- **B3. Steering + table** (`diagram-standards.md`, `diagram-lint.md`): short
  labels; explanation in a callout. Register the rule row. *(AC 2.4, 2.5)*

### Part C — `ip-range` (Requirement 3)

- **C1. Documentation-range predicate** (`linter.py`): `_is_documentation_ip` /
  `_is_private_ip` using the stdlib `ipaddress` module (`ip_network`,
  `is_private`, and an explicit Documentation_Range set). A Public_IP_Literal is
  a parseable global IP not in either set. *(AC 3.1, 3.2)*
- **C2. Network-scope guard** (`linter.py`): the rule evaluates only a
  Network_Diagram — `diagram_class == landscape` OR companion `diagram_type` in
  {network, infrastructure, deployment}. A flow diagram is skipped. *(AC 3.3)*
- **C3. Text source**: scan the artifact's on-diagram text (node labels, edge
  labels, callouts, legend) with a conservative IPv4/IPv6 regex, then classify
  each match with C1. *(AC 3.1)*
- **C4. Steering + table** (`diagram-standards.md`, `diagram-lint.md`): list the
  Documentation_Ranges, require RFC5952 IPv6, register the row. *(AC 3.4, 3.5)*

### Part D — `raster_background` (Requirement 4)

- **D1. Companion key** (`raster_gate._diagram_background_of`): read
  `raster_background` from the companion (default `white`). *(AC 4.1)*
- **D2. Gate branch** (`raster_gate.py`): the existing opaque-white check runs
  WHERE background is `white`/absent; WHERE `transparent`, require an alpha
  channel with a transparent background instead. `read_png_facts` already reads
  the background; extend it to report alpha. *(AC 4.2, 4.4)*
- **D3. Exporter branch** (`export_raster.py`): WHERE `transparent`, export
  without forcing white (`--transparent` to the draw.io CLI) rather than the
  current white background. *(AC 4.3)*
- **D4. Steering** (`diagram-standards.md`, Accessibility & Raster): document
  white (default) vs transparent+`#7E7E7E` (adaptive target). *(AC 4.5)*

### Part G — companion metadata (Requirement 7)

- **G1. Frontmatter keys** (`linter.py` frontmatter handling,
  `kb-frontmatter.md`): recognise optional `change_log` (list of `{date, note}`)
  and `external_refs` (list). Reuse the existing ISO-8601 date validation for
  each `change_log[].date`; both keys optional. *(AC 7.1, 7.2, 7.3)*
- **G2. Docs** (`kb-frontmatter.md`): document both keys and formats. *(AC 7.4)*

### Parts E, F, H, I — guidance (Requirements 5, 6, 8, 9)

- **Steering-only edits** to `diagram-standards.md`: C4 layering + progressive
  disclosure (E); the `diagram_type` taxonomy table with per-type axis (F);
  retire-inaccurate + accuracy-over-simplicity (H); the four grouping strategies
  (I). No code; verified by the structural checks and human review. *(AC 5.*,
  6.*, 8.*, 9.*)*

### Part J — snapshot→diagram autogenerator `rule-engine-draw` (Requirement 10)

The autogenerator is a **thin front-end** over machinery that already exists; it
adds a Snapshot→`DiagramSpec` translator and a console script, nothing in the
layout/geometry core.

- **J1. Console script + CLI** (`rule_engine.draw_cli:main`, `[project.scripts]`
  `rule-engine-draw`): args are the Snapshot folder, the provider, the diagram
  type (`simple`/`summary`/`landscape`), an output basename, and an optional
  `--relationships <file>`. Packaged in the wheel and power like the other
  `rule-engine-*` gates. *(AC 10.1, 10.9)*
- **J2. Role resolution** (`reconcile.role_of`, reused verbatim): every resource
  in the Snapshot's per-domain JSON is mapped to one of the 16 roles; a `None`
  role is skipped (never a look-alike). Reads only committed Snapshot files,
  offline (Decision D5). *(AC 10.2)*
- **J3. Lane assignment** (`draw.lane_of`, new pure function): a deterministic
  role→lane table consistent with the fixed lane order
  (`actors → edge → router → async messaging → workers → platform core → data →
  on-premises`). E.g. `cdn`/`dns`/`waf`→edge, `lb`→router, `message_queue`→async
  messaging, `serverless_fn`/`managed_k8s`/`compute_instance`→workers,
  `llm_platform`→platform core, `object_store`/`managed_sql`/`file_system`/
  `cache`/`secrets_store`→data. Containers (account/region/az) are derived from
  the Snapshot boundary metadata (the manifest `boundary_id`, region set). *(AC
  10.3)*
- **J4. Spec assembly** (`draw.spec_from_snapshot`): build `NodeSpec` per
  role-bearing resource (id, role, lane, region, slot assigned by stable sort of
  the resource identity), `ContainerSpec` per boundary, and — WHERE a
  Relationship_Input is supplied — an `EdgeSpec` per given relationship; WHERE
  absent, no edges are invented (the nodes surface as `node-connectivity`
  WARNINGs). Deterministic: nodes and slots come from a stable sort, so two runs
  produce identical specs. *(AC 10.5, 10.6)*
- **J5. Coverage by type** (`draw`): `landscape` emits every role-bearing
  resource (total coverage → `rule-engine-reconcile` clean); `simple`/`summary`
  emit the in-scope subset. A `landscape` whose role-bearing count exceeds the
  `node-count` ERROR bound (> 50) is reported as "split the Snapshot", emitting
  no blocked diagram. *(AC 10.4, 10.7)*
- **J6. Companion + triple** (`draw`): hand the `DiagramSpec` to `layout()` then
  `build_diagram()` for the `.drawio`, export the raster via the existing
  exporter, and write a companion `.diagram.md` with the required frontmatter —
  `diagram_class`, and `summary_of`/`detailed_view` for a `summary`/`landscape`
  pair — so the triple is complete and a landscape is never `orphan-landscape`.
  *(AC 10.8)*

### Cross-cutting (Requirements 11, 12)

- All new rules WARNING; no existing rule touched; determinism preserved
  (callouts/metadata are declarative). Regenerate/verify every Shipped_Diagram
  against the new WARNINGs and resolve or record. Version bump + CHANGELOG last.

## Data Models

- **Companion frontmatter additions** (all optional):
  - `raster_background: white | transparent`
  - `diagram_type: <enumerated>` (descriptive)
  - `change_log: [{date: YYYY-MM-DD, note: str}]`
  - `external_refs: [str]`
- **Edge model addition**: `start_arrow: Optional[str]` alongside the existing
  `end_arrow` in `geometry.py`.
- **Overlay vocabulary addition**: `callout`.
- **No new geometry type for J**: the autogenerator emits the *existing*
  `DiagramSpec` (`NodeSpec`/`EdgeSpec`/`ContainerSpec`); the only new data is
  the role→lane table and the optional Relationship_Input file format
  (a list of `{source, target, label}`).

## Correctness Properties

Property 1: Bidirectional detection is exact. An edge with two non-`none`
arrowheads trips `edge-bidirectional`; a single-head edge (the common case) never
does. *(A)*
**Validates: Requirements 1.1, 1.2**

Property 2: Label cap is source-scoped. `node-label-length` fires only on
service-node labels; Legend, Flow, title, and callout cells never trip it,
regardless of length. *(B)*
**Validates: Requirements 2.1, 2.2**

Property 3: IP classification is correct and scoped. A Documentation_Range or a
private IP never trips `ip-range`; a public literal trips it only in a
Network_Diagram. *(C)*
**Validates: Requirements 3.1, 3.2, 3.3**

Property 4: Raster mode is backward-compatible. With `raster_background` absent
or `white`, the gate behaviour is byte-for-byte the pre-1.10.0 behaviour; only
`transparent` changes the check. *(D)*
**Validates: Requirements 4.2, 4.4**

Property 5: Optional metadata never breaks a clean document. A Companion with no
`change_log`/`external_refs` raises no finding; a `change_log` entry with a bad
date raises a `frontmatter` finding. *(G)*
**Validates: Requirements 7.2, 7.3**

Property 6: No regression. Every Shipped_Diagram stays eligible for publication
(zero CRITICAL/ERROR); generation stays byte-identical; the rule-table sync test
and the raster ratchet pass. *(Requirement 10)*
**Validates: Requirements 10.3, 10.4**

Property 7: Rule-table sync. Each new rule appears exactly once in the
`diagram-lint.md` table with its severity, and the sync test passes. *(A, B, C)*
**Validates: Requirements 10.5**

Property 8: Autogenerator is deterministic, offline, and coverage-correct. On
the same Snapshot and inputs `rule-engine-draw` produces a byte-identical
`.drawio`; it reads only committed Snapshot files; a `landscape` it produces
covers every role-bearing enumerated resource (so `rule-engine-reconcile`
passes) and, within the node budget, is publication-eligible. *(J)*
**Validates: Requirements 10.2, 10.4, 10.6, 10.7**

## Error Handling

- **Unparseable `.drawio`**: the new rules run only after the existing
  `parse-error` short-circuit, so a file that does not parse is blocked by
  `parse-error` and the new predicates are never evaluated (unchanged behaviour).
- **Malformed edge arrow tokens (A)**: an edge whose style omits `startArrow`
  resolves to `none` (no start head), so it is treated as single-headed — never a
  false `edge-bidirectional`. An unspecified `endArrow` keeps the draw.io default
  head, consistent with `arrow-style`.
- **Unparseable IP text (C)**: a token that looks address-like but does not parse
  under `ipaddress` is ignored (not a finding), so prose is never mis-flagged.
- **Bad `raster_background` value (D)**: any value other than `transparent` is
  treated as `white` (the safe default), so a typo never silently drops the
  opaque-white check.
- **Bad `change_log` shape (G)**: a `change_log` that is not a list, or an entry
  missing `date`, raises a `frontmatter` finding naming the key — consistent with
  the existing fail-closed frontmatter handling; a valid-but-absent key is clean.
- **Missing companion for `diagram_type`/`raster_background` (D, F)**: absent
  companion or key falls back to the documented default (`flow` class, `white`
  background), never an error.
- **Autogenerator over-budget landscape (J)**: a `landscape` whose role-bearing
  resource count exceeds the `node-count` ERROR bound (> 50) is reported as
  "split the Snapshot" with a non-zero exit and no `.drawio` written — never a
  blocked diagram (AC 10.7), mirroring the exporter's over-budget behaviour.
- **Autogenerator unresolved resource (J)**: a resource whose `role_of` is
  `None` is skipped, not drawn — consistent with the reconcile mapper; it is
  not an omission (AC 10.2).
- **Autogenerator no relationships (J)**: with no Relationship_Input the spec
  has nodes and no invented edges; the produced diagram trips
  `node-connectivity` WARNINGs (advisory, non-blocking), which is the honest
  signal that the author must add relationships (AC 10.5).

## Testing Strategy

- **Property tests** for the three predicates (bidirectional, label-length,
  ip-range) over generated edge/label inputs, asserting Properties 1–3.
- **Raster-gate tests** for `raster_background` white (unchanged) and transparent
  (alpha required), asserting Property 4.
- **Frontmatter tests** for optional `change_log`/`external_refs` present-valid,
  present-bad-date, and absent, asserting Property 5.
- **Corpus regression**: run the full Gate_Suite over `examples/`; every
  Shipped_Diagram stays publishable (Property 6). Resolve any new WARNING in the
  generators or record it.
- **Sync test**: the existing `diagram-lint.md` rule-table sync test covers the
  three new rows (Property 7).
- **Autogenerator** (J): property test that (1) two runs on a fixture Snapshot
  produce a byte-identical `.drawio` (Property 8); (2) a produced `landscape`
  passes `rule-engine-reconcile` for that Snapshot (total coverage); (3) an
  unresolved-role resource is skipped; (4) an over-budget landscape reports
  split rather than emitting. An end-to-end test generates from a committed
  example Snapshot and runs the full Gate_Suite over the produced triple.
- **Guidance parts** (E, F, H, I): no code test; covered by human review and the
  steering document's own structural validity.

## Decisions

- **All new rules are WARNING.** They encode provider *conventions*, not
  correctness failures; blocking on them would be heavier than the guidance
  itself is. Consistent with the advisory geometry rules.
- **`diagram_type` is descriptive, not enforced.** The enforced class stays
  `diagram_class` (flow/landscape); `diagram_type` records intent for authors and
  scopes `ip-range`, but does not gate.
- **Reuse, don't duplicate.** `ip-range` uses stdlib `ipaddress`; `change_log`
  dates reuse the existing ISO-8601 validator; `raster_background` extends the
  existing background read. No new parsing infrastructure.
- **The autogenerator is a translator, not a new engine (J).** It reuses
  `reconcile.role_of` (resource→role), emits the existing coordinate-free
  `DiagramSpec`, and delegates all placement/routing to `layout()` and all
  serialization to `build_diagram()`. The only genuinely new logic is the
  role→lane table and the Snapshot→spec assembly — both pure and deterministic.
  It invents no relationships: honest `node-connectivity` WARNINGs beat
  fabricated edges, and a supplied Relationship_Input is how real edges arrive.
