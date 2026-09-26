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
| D8 | **Edge-less nodes.** Every HA landscape drew 34 nodes joined by 12 edges, leaving 20 unconnected — the engine drew an inventory, not an architecture. Now enforced by `node-connectivity`, with the landscapes re-connected (21 edges) and the passive region's mirror peers marked `standby`. | Resolved | `geometry.check_node_connectivity`, `ha_multiregion_spec.py`, `tests/test_new_rules_1_6_0.py` |
| D9 | **North–South infrastructure golden example.** The N–S axis was specified but unregressed: no shipped golden exercised it, nor an external actor / on-premises boundary outside the cloud, nor peer AZ containers. | Resolved | `examples/aws/03-aws-hybrid-infrastructure.*`, `scripts/build_aws_infra_example.py` |
| D10 | **Directional contract read the half-plane, not the face.** `exitX >= 0.5` admitted the top-*centre* point, so an edge leaving the top of its own glyph linted clean (and the mirror on the entry side). `check_edge_direction` now classifies the contact face. | Resolved | `geometry.contact_faces`, `geometry.check_edge_direction` |
| D11 | **Flow/Legend placement unenforced.** The furniture belongs in the right margin; a clean-room diagram parked both blocks in the left margin and linted clean. Now `legend-placement`. | Resolved | `geometry.check_legend_placement`, `linter.py` |
| D12 | **`flow-legend` documented but not implemented.** Specified from the first ruleset; the generator always emitted the Flow cell, so the missing check only bit hand-authored diagrams. | Resolved | `linter._check_flow_legend`, `cli._parse_flow_legend_lines` |
| D13 | **Container caption strip.** A group's caption is drawn inside its own top edge, so a uniform pad left no corridor lane above the first content row and descending edges ran through the caption. Top padding now reserves the strip. | Resolved | `layout_engine.size_containers`, `layout_engine._caption_free_band` |

## Uniqueness / duplication (U)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| U1 | Duplicated provider/type enums across modules. Collapsed into `rule_engine.constants` as the single declaration. | Resolved | `constants.py` |
| U2 | Duplicated secret-marker vocabulary. Single shared list consumed by the linter's content scan and the collector's redaction. | Resolved | `constants.SECRET_MARKERS`, `linter.py`, `collector.py` |

## Governance (G)

| Code | Finding | Status | Where |
| --- | --- | --- | --- |
| G3 | Test/dev tooling must not be a runtime dependency of the engine. Kept in the `dev` extra. | Resolved | `pyproject.toml` |
| G4 | **Snapshot folder shape unchecked.** The linter checks snapshot file *content* (frontmatter, secret-safety) but nothing checked the folder: a hand-written snapshot shipped with an empty `resources/` and a wrong `file_count` and linted clean. Now the snapshot gate, wired into both CI pipelines. | Resolved | `snapshot_gate.py`, `scripts/build_example_snapshots.py`, CI |
| G5 | **Version recorded in three places, drifting.** `VERSION`, `pyproject.toml`, and the newest `CHANGELOG.md` heading disagreed at 1.5.4; CI rewrites `VERSION` at tag time, so nothing surfaced it. Now a checked contract. | Resolved | `version_guard.assert_version_triple_consistent`, `tests/test_version_triple.py` |
| G6 | **Duplicated artifacts drifting unguarded.** The `.kiro/skills` and Power `SKILL.md` copies had diverged across four wording hunks, and `powers/…/plugin.json` sat at 1.0.0 through nine engine releases. A clean-room install also received the steering rules but none of the three agents that apply them. | Resolved | `build_backend._PAYLOAD` (`.kiro/agents`), `tests/test_bootstrap_payload_sync.py` |

## Open gaps

These are documented and accepted; they do not block publication.

- **Inventory → diagram reconciliation is prose, not a gate.** `diagram-standards.md`
  requires every enumerated, role-resolvable resource to appear on the diagram,
  and the snapshot gate now checks the snapshot's own shape — but nothing compares
  the two. A clean-room diagram omitted the ten KMS keys its `secrets.json` had
  enumerated while its companion asserted completeness, and only a human reading
  both files could tell. Closing this needs a raw-provider-JSON → role mapper (the
  snapshot records native provider responses; the diagram records roles), which is
  a new subsystem rather than a gate fix. Deferred deliberately.
- **Routing is rule-driven with no feedback loop; route quality is measured but
  not optimised.** `diagram-standards.md` carries ~25 named routing patterns, each
  distilled from a hand-edit, and each router applies its pattern with no view of
  the diagram as a whole. That works until two patterns want the same plane. A
  reviewer's 2026-09-26 hand-edit of the AWS HA landscape is the worked example:
  four routes changed, none of them individually wrong by any rule, and the
  improvement only visible in aggregate —

  | Metric | generated | hand-edited |
  | --- | --- | --- |
  | edge-edge crossings | 7 | 6 |
  | **parallel rails** | **4** | **2** |
  | turns | 50 | 48 |
  | ink | 11.0k | 10.8k |

  The headline is *parallel rails* (a long vertical alongside a column of icons,
  which the standard already forbids), not crossings — the reviewer traded three
  crossings for four while removing two rails, so a crossing-only objective would
  have rejected the edit. `scripts/route_quality.py` measures all four numbers and
  is the instrumentation for the fix.

  A second hand-edit of the same diagram reached **3 crossings / 2 rails / 45
  turns / 10.0k ink** — better on every axis at once, which is what a scored
  router should be able to find. Its 13 changed routes fall into three groups:
  a *straight drop* replacing a corridor loop where the target sits directly
  below (4 edges), a *lane-side flip* using the free side of a row (5 edges), and
  a *turn-column shift* moving a vertical off an icon border (3 edges).

  **Why it needs design rather than another rule.** Three experiments, all run:

  1. *The straight drop cannot be a rule.* Enabling it for landscapes (it is gated
     to compact diagrams today) cut turns 50 → 41 and ink 11.0k → 10.5k but raised
     crossings **7 → 11**. The side corridor it replaces is doing real work on some
     edges and none on others, so the choice varies per edge and per layout.
  2. *The edits are coupled.* The back-edge's better shape only fits if the fan-out
     currently occupying that lane moves to the other side of its row. Implementing
     the back-edge change alone fails with a `corridor-sharing` finding the repair
     loop cannot resolve: two edges then compete for one ~40px band, and greedy
     per-edge allocation in declared order cannot see the conflict coming.
  3. *The pipeline has no per-edge decision point.* `_place_and_route` decides
     contacts in **eight sequential global passes** (`1`, `1b`, `1c`, `1d`, `2`,
     `2b`, `2b2`, `2b3`, `2c`), each reading the previous one's output across the
     whole edge set, and only then routes. Scoring needs contacts *and* route
     chosen together per edge, so it cannot be slotted into the current order.

  **The design.** Invert the pipeline: for each edge, generate its router's
  **sanctioned variants** (above vs below lane, loop-above vs descend-near,
  straight-drop vs side-corridor, left vs right corridor) as (contacts + route)
  pairs, score each with `geometry.route_cost` against the edges already accepted,
  and take the minimum — snapshotting the `CorridorAllocator` so a rejected
  variant does not consume lanes. Order edges most-constrained-first so inflexible
  long-haul runs claim their lanes before two-sided fan-outs. Candidate choice
  largely dissolves the coupling in (2): the later edge can pick the variant that
  avoids the earlier one's lane. This is far more tractable once
  `layout_engine.py` is split into a `layout/` package (the A1 follow-up item), so
  the two are sequenced together.

  **Already landed toward it:** `geometry.route_cost` (the objective, with rails
  weighted above turns/ink because the first hand-edit traded a crossing for two
  rails), `scripts/route_quality.py` (reporting), and a ratchet in
  `tests/test_route_quality.py` that pins each shipped diagram's crossing/rail
  ceiling so routing cannot silently regress before the scored router exists.

  **Update (2026-09-25): measuring it closed most of the gap by rule after all.**
  Two of the three experiments above stay true — the straight drop and the coupled
  edits do not work as isolated rules, and the pipeline still has no per-edge
  decision point. What changed is that the *metric itself* was wrong in a way that
  hid the actual defect. It exempted any two edges sharing an endpoint, reasoning
  that the standard sanctions a shared trunk; but sharing a trunk makes two
  branches **touch**, which `segments_cross` already excludes, so the exemption
  protected nothing and hid four crossings per landscape. With it lifted the
  hand-route still measured **zero** co-sourced crossings — which pointed straight
  at exit-band ordering, not at the need for search. Three rules followed
  (`decide_lane_sides`, `_exit_band_rank`, `_free_drop_column`; see CHANGELOG
  1.6.0), and the generated landscape now measures **3 crossings / 2 rails / 42
  turns / 10.2k ink** against the hand-route's 3 / 2 / 45 / 10.0k — parity on the
  two weighted axes, three fewer turns. The remaining three crossings are the ones
  the hand-route kept too.

  So the scored router is no longer needed to *reach* hand-quality on this corpus;
  it is needed for the cases a rule cannot see, of which two are now concrete and
  recorded below (the tier-skip rail, and the GCP/OCI hub). Both are **placement**
  problems surfacing as routing defects, which argues for scoring placement
  variants alongside routes when that work happens.
- **Two rails and three crossings remain on the landscapes, and they are placement
  defects, not routing ones.** Worth stating plainly so they are not re-litigated
  as routing bugs:
  * the *tier-skip rail* — the load balancer's hop to the second AZ's application
    tier descends 540px in the VPC's left gap, which is the only corridor that
    crosses none of the fan-out lanes, and that gap is 60px wide, so the run sits
    30px from a column of icons whichever line it takes. The hand-route has the
    identical rail. Widening the gap (or moving the tier) fixes it; no routing
    choice does.
  * the *GCP / OCI hub* — `vertex-ai` / `generative-ai` carries four edges and its
    one free approach column lies **inside its own fan-out**, so the back-edge
    reaching it crosses two stubs. Every alternative was measured and none is
    better. Moving one neighbour fixes it.
  * the *edge-tier band* — two long runs leave the account's top row heading in
    opposite directions with overlapping extents, and that row has no band above
    it (it is the top row), so they cannot be put on opposite sides. The hand-route
    keeps this crossing as well.
- **The rails metric is binary where it should be graded.** `route_cost` counts a
  rail when a long vertical passes within `RAIL_CLEARANCE` (40px) of an unrelated
  node's border, so a run at 39px and one at 2px score identically — yet the second
  is the defect a reviewer actually objects to, and improving 2px → 10px → 30px
  registers as no change at all. Two real improvements this release (the back-edge
  drop column, the tier-skip centring) were invisible to the score for exactly this
  reason. A penalty inversely proportional to clearance would rank them correctly,
  and is a prerequisite for the scored router being able to choose between two
  routes that both technically clear the threshold.
- **Container dead space is unmeasured.** `container-padding` checks the *minimum*
  clearance; nothing flags the opposite defect, a container sized far larger than
  its children (the clean-room VPC was 840×460 around four nodes in one row). A
  threshold would need measuring across the corpus first to avoid false positives
  on a deliberately sparse tier.
- **Icon-index slug collisions are reported, not resolved.** When two distinct
  vendor icons normalize to one slug (e.g. AWS `Database … Light`/`Dark`, Azure
  `Groups`/`Service Groups`), the icon-set builder keeps last-writer-wins and
  emits a WARNING rather than disambiguating. The engine's own roles are
  unaffected; the warning surfaces the shadowing for a future mapping edit.
