# Implementation Plan

Derived from `design.md` and `requirements.md`. Items A–I map to eight tasks:
four enforced code parts (A–D), one frontmatter part (G), one guidance bundle
(E/F/H/I), a corpus-regression checkpoint, and the release wrap. The enforced
parts (1–5) are mutually independent; the guidance bundle (6) is independent of
all; the regression checkpoint (7) depends on 1–6; the release wrap (8) is last.
Requirement references are in parentheses / the `_Requirements_` trailer.

## Overview

This release aligns the engine with the official provider diagramming guidance
(AWS `diagram-as-code`, AWS Networking conventions, Azure Well-Architected, C4).
It adds three advisory WARNING lint rules (`edge-bidirectional`,
`node-label-length`, `ip-range`), a companion-driven raster mode
(`raster_background`), two optional companion frontmatter keys (`change_log`,
`external_refs`) and a `callout` overlay term, plus steering-only guidance
(C4 layering, diagram-type taxonomy, retire-inaccurate, grouping strategies),
and a **snapshot→diagram autogenerator** (`rule-engine-draw`, item J) that
closes the deferred `docs/REVIEW.md` gap G8 by reusing `reconcile.role_of`, the
coordinate-free `DiagramSpec`, and the existing `layout()`/`build_diagram()`
pipeline. No geometry constant, solver, or existing rule changes; every new
lint rule is advisory, and the autogenerator adds no rule — it produces
artifacts the existing gates judge.

## Tasks

- [x] 1. Add `edge-bidirectional` lint rule (Part A)
  - Extend `geometry.py` edge parsing to expose `start_arrow` (alongside the existing `end_arrow`/`end_fill` used by `arrow-style`).
  - Add `_check_edge_bidirectional(a)` in `linter.py`: WARNING when an edge sets both a non-`none` `startArrow` and a non-`none` `endArrow`; a single-head edge is never flagged.
  - Register `RULE_EDGE_BIDIRECTIONAL` (WARNING, both classes) and add its row to the `diagram-lint.md` rule table.
  - Add the convention to `diagram-standards.md` (Edge Routing): two single-ended edges preferred; never a double head.
  - Property test (Property 1): a two-head edge trips it; a single-head edge does not.
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Add `node-label-length` lint rule and the `callout` overlay term (Part B)
  - Add `_check_node_label_length(a)` in `linter.py`: WARNING when a service-node label exceeds 4 words or 40 characters; Legend/Flow/title/callout cells are not node labels and are exempt.
  - Add `callout` to the Overlay Vocabulary in `diagram-standards.md`; a callout cell carries `overlay=callout`, is a text cell (not a node), and is covered by `overlay-legend-coverage` when used.
  - Register `RULE_NODE_LABEL_LENGTH` (WARNING) and add its `diagram-lint.md` row; add the short-label/callout guidance to `diagram-standards.md`.
  - Property test (Property 2): a long service-node label trips it; a long Legend/Flow/callout cell does not.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 3. Add `ip-range` lint rule (Part C)
  - Add `_is_documentation_ip` / `_is_private_ip` helpers in `linter.py` using stdlib `ipaddress`, with the explicit Documentation_Range set (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32) plus RFC1918/6598/6815.
  - Add `_check_ip_range(a)`: WARNING when a Network_Diagram's on-diagram text contains a Public_IP_Literal; scoped to `diagram_class == landscape` OR companion `diagram_type` in {network, infrastructure, deployment}; a non-parseable address-like token is ignored.
  - Register `RULE_IP_RANGE` (WARNING) and add its `diagram-lint.md` row; list the Documentation_Ranges and require RFC5952 IPv6 in `diagram-standards.md`.
  - Property test (Property 3): a documentation/private IP never trips it; a public literal trips it only in a Network_Diagram.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Add `raster_background` companion mode (Part D)
  - Read `raster_background` (default `white`) from the companion in `raster_gate.py`; any value other than `transparent` falls back to `white`.
  - Branch the gate: `white`/absent keeps the existing opaque-white check unchanged; `transparent` requires an alpha (transparent) background. Extend `read_png_facts` to report alpha.
  - Branch `export_raster.py`: `transparent` exports without forcing white; `white`/absent unchanged.
  - Document white (default) vs transparent+`#7E7E7E` in `diagram-standards.md`.
  - Property test (Property 4): white/absent is byte-for-byte the pre-1.10.0 check; transparent requires alpha.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 5. Add optional companion metadata keys `change_log` and `external_refs` (Part G)
  - Recognise optional `change_log` (list of `{date, note}`) and `external_refs` (list) in the frontmatter handling; reuse the existing ISO-8601 date validator for each `change_log[].date`.
  - Absent keys raise no finding; a bad `change_log` date or shape raises a `frontmatter` finding naming the key.
  - Document both keys and formats in `kb-frontmatter.md`.
  - Test (Property 5): present-valid is clean; present-bad-date warns; absent is clean.
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 6. Steering guidance blocks E, F, H, I (guidance only)
  - `diagram-standards.md` — C4 layering / progressive disclosure (E): map context → container (≈ flow summary) → component/deployment (≈ landscape); reference `summary_of`/`detailed_view`.
  - `diagram-standards.md` — diagram-type taxonomy (F): define the optional `diagram_type` key, enumerate the types with each one's primary axis, note east-west vs north-south network split; keep `diagram_class` as the enforced class.
  - `diagram-standards.md` — retire-inaccurate + accuracy-over-simplicity (H): the PaaS-in-subnet example; retire stale diagrams; cross-reference the inventory→diagram completeness rule.
  - `diagram-standards.md` — grouping strategies (I): function / environment / availability zone / security boundary, tied to boundary-nesting and lane order.
  - No code; verify the steering document stays structurally valid.
  - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 8.1, 8.2, 8.3, 9.1, 9.2_

- [x] 7. Autogenerator core: role→lane + Snapshot→DiagramSpec (Part J)
  - Add `rule_engine/draw.py` with `lane_of(role)` — a pure, deterministic role→lane table consistent with the fixed lane order in `diagram-standards.md`.
  - Add `spec_from_snapshot(snapshot_dir, provider, diagram_type, relationships=None)`: resolve every resource via `reconcile.role_of` (skip `None`), assign lane via `lane_of`, derive account/region/az `ContainerSpec` from the manifest boundary metadata, build a `NodeSpec` per role-bearing resource (stable-sorted slots), and `EdgeSpec` per supplied relationship (none invented when absent).
  - Coverage by type: `landscape` includes every role-bearing resource; `simple`/`summary` the in-scope subset; a `landscape` over the `node-count` ERROR bound (> 50) raises a "split the Snapshot" error with no spec emitted.
  - Property test (Property 8 part 1): two runs on a fixture Snapshot yield identical specs; an unresolved-role resource is skipped; over-budget landscape reports split.
  - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

- [x] 8. Autogenerator command: `rule-engine-draw` + companion + triple (Part J)
  - Add `rule_engine/draw_cli.py:main` and the `rule-engine-draw` entry in `[project.scripts]` (shipped in the wheel and power); args: snapshot folder, provider, type (`simple`/`summary`/`landscape`), output basename, optional `--relationships <file>` (list of `{source, target, label}`).
  - Hand the `DiagramSpec` to `layout()` then `build_diagram()`; export the raster via the existing exporter; write a companion `.diagram.md` with required frontmatter (`diagram_class`, plus `summary_of`/`detailed_view` for a summary/landscape pair) so the triple is complete and a landscape is not `orphan-landscape`.
  - _Requirements: 10.1, 10.8, 10.9_

- [x] 9. Autogenerator end-to-end verification (Part J)
  - From a committed example Snapshot, run `rule-engine-draw --landscape` and confirm the produced triple passes the full Gate_Suite (lint, verify-icon, raster budget) AND `rule-engine-reconcile` (total coverage → Property 8 parts 2–4).
  - Confirm two runs are byte-identical and the command is offline (no provider calls).
  - _Requirements: 10.4, 10.6, 10.7_

- [x] 10. Corpus regression and rule-table sync (Requirement 11)
  - Run the full Gate_Suite over `examples/`; confirm every Shipped_Diagram stays eligible for publication (zero CRITICAL/ERROR).
  - Resolve any new WARNING (`edge-bidirectional`, `node-label-length`, `ip-range`) in the generators, or explicitly record it as accepted.
  - Confirm the `diagram-lint.md` rule-table sync test passes with the three new rows (Property 7) and generation stays byte-identical (Property 6).
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

- [x] 11. Version bump to 1.10.0 and CHANGELOG (Requirement 12)
  - Set `VERSION`, `pyproject.toml`, `plugin.json`, the bootstrap pin, and the SessionStart hook to `1.10.0`.
  - Add the `## [1.10.0]` CHANGELOG section describing items A–I (enforced A–D, G; guidance E, F, H, I).
  - Confirm the version-triple, version-pin, and bootstrap-payload-sync guards pass; run the full suite.
  - _Requirements: 12.1, 12.2, 12.3_

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "2", "3", "4", "5", "6", "7"] },
    { "wave": 2, "tasks": ["8"] },
    { "wave": 3, "tasks": ["9", "10"] },
    { "wave": 4, "tasks": ["11"] }
  ]
}
```

An ASCII view of the same dependencies:

```
Lint/frontmatter parts (independent):  1  2  3  4  5
Guidance bundle (independent):          6
Autogenerator core (independent):       7 → 8 (command) → 9 (e2e)
                                         \  \  \  \  \  \        /
                                          → 10 (corpus regression + sync)
                                                → 11 (release wrap: version + CHANGELOG)
```

- Tasks 1–7 have no cross-task dependencies and may proceed in parallel; task 8
  (the `rule-engine-draw` command) depends on the autogenerator core (7), and
  task 9 (end-to-end) depends on 8.
- Task 10 depends on 1–9 (it regresses the whole corpus against the new rules,
  the new steering, and a diagram produced by the autogenerator).
- Task 11 (release wrap) depends on task 10 being green.

## Notes

- **Every new rule is WARNING (Req 10.1).** `edge-bidirectional`,
  `node-label-length`, and `ip-range` surface a convention violation without
  blocking publication; none is CRITICAL or ERROR.
- **No existing rule weakened (Req 10.2).** All changes are additive: new rules,
  new optional keys, a new companion mode branch that defaults to today's
  behaviour.
- **Determinism preserved (Req 10.3).** Callouts and metadata are declarative and
  do not change layout; the same spec produces a byte-identical `.drawio`.
- **Backward-compatible defaults.** `raster_background` defaults to `white`,
  `diagram_type` is descriptive-only, and `change_log`/`external_refs` are
  optional — every current Shipped_Diagram and Companion stays valid untouched.
- **Guidance vs enforcement.** Items E, F, H, I are steering-only (task 6); items
  A, B, C, D, G are enforced (tasks 1–5) with property tests and, for A/B/C, a
  `diagram-lint.md` rule-table row kept in sync by the existing sync test.
- **Autogenerator closes G8 (Req 10).** `rule-engine-draw` is a translator over
  existing machinery (`reconcile.role_of` → `DiagramSpec` → `layout()` →
  `build_diagram()`); it adds no lint rule and invents no relationships. On
  release, `docs/REVIEW.md` finding **G8** flips from Open (deferred) to
  Resolved (1.10.0).
