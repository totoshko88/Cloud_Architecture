# Requirements — Declarative Lane-Grid Layout Engine

## Introduction

Today the golden HA multi-region diagrams (`examples/{aws,azure,gcp,oci}/02-*-ha-multiregion-{summary,landscape}.drawio`) are produced from **hand-authored coordinate tables**: every node `(x, y)` and every edge waypoint in `scripts/ha_multiregion_common.py` is a literal integer a human placed and tuned by eye. The repo has strong declarative primitives (`Node` / `Edge` / `Boundary`, the `build_diagram` assembler) and a strong validation layer (the `check_*` geometry rules), but **no generative layout layer**. As a result, every readability fix has meant another round of manual waypoint tuning — the exact over-engineering the project set out to avoid.

This feature adds a **deterministic layout engine** that generates node placement and edge routing **from a declaration** (nodes with a role + lane + region, and edges with a type), with **no coordinates in the input**. The engine places nodes on a lane grid, sizes containers around them, selects contact points, allocates corridors, routes edges orthogonally by edge class, and repairs the layout against the existing `check_*` validators until it is publication-eligible. The four provider skins keep supplying only icons and labels; geometry is derived, not written.

Scope is the **HA landscape/summary diagram class** (the shipped golden pair). It is not a universal auto-router for arbitrary graphs. The current hand-authored diagrams are preserved as `-reference` artifacts and the engine's output is compared against them.

### Goals

- Replace the hand-authored coordinate tables with a declaration + engine.
- Encode the routing rules that today live only in prose (`.kiro/steering/diagram-standards.md` → Edge Routing) as executable placement/routing logic.
- Reuse the existing `check_*` validators as the acceptance oracle and repair signal — do not duplicate their constraints.
- Keep every provider's diagram identical in geometry (skin = icons + labels only).

### Non-goals

- A general-purpose graph auto-router for any diagram type.
- Changing the `.drawio` output format, the icon-index, or the provider skins.
- Re-deriving the summary/landscape **topology** (which nodes/edges exist) — that stays declared; only geometry is generated.

### Terminology

- **Lane** — one of the eight canonical tiers (actors → edge → router → async → workers → platform → data → on-premises). Maps to a row (North–South infra layout) or a column (left→right flow layout).
- **Slot** — a node's position within its lane (0-indexed).
- **Corridor** — a reserved grid-step-aligned lane in an inter-column or inter-row gap through which exactly one edge segment runs.
- **Contact point** — an edge's `exit`/`entry` unit-square fraction on a node face.
- **Edge class** — one of: `spine`, `fan-out-row`, `cross-region`, `back-edge`, `straight` (chosen from the source/target lane+region relationship).
- **Reference artifact** — the current committed `.drawio`, saved as `NN-...-reference.drawio`, that the engine's output is compared against.

---

## Requirement 1 — Coordinate-free declaration

**User story:** As a diagram author, I want to declare a diagram as nodes (role + lane + region + slot) and edges (source, target, type), with no pixel coordinates, so that geometry is derived by the engine and I never hand-tune waypoints.

#### Acceptance criteria

1. WHEN the engine receives a diagram declaration, THEN each node SHALL be specified by `id`, `role`, `lane`, `region`, and `slot` only — no `x`/`y`.
2. WHEN the engine receives a diagram declaration, THEN each edge SHALL be specified by `id`, `source`, `target`, `marker`, and `dashed` only — no `exit`/`entry`/`points`.
3. WHEN the declaration includes containers, THEN each container SHALL be specified by `id`, `kind` (account/vpc/az), `region`, and its parent/child nesting only — no `x`/`y`/`w`/`h`.
4. IF a declaration contains any explicit coordinate, waypoint, or contact-point value, THEN the engine SHALL reject it with an error naming the offending field (coordinates are the engine's output, never its input).
5. WHEN `ha_multiregion_common.py` is migrated, THEN its `SUMMARY_*` and `LANDSCAPE_*` tables SHALL be replaced by coordinate-free declarations, and the provider skins SHALL remain icons + labels only.

## Requirement 2 — Lane model and axis

**User story:** As the engine, I want a canonical lane model in code, so that a node's tier deterministically maps to a grid row/column and matches the convention reviewers expect.

#### Acceptance criteria

1. WHEN the engine initializes, THEN the eight lanes SHALL be encoded as an ordered table (`actors, edge, router, async, workers, platform, data, on-premises`) with a stable index each.
2. WHEN the diagram class is infrastructure/landscape (North–South), THEN lane index SHALL map to a **row** (top→bottom) and slot to a **column** (left→right).
3. WHEN the diagram class is flow/summary (left→right), THEN lane index SHALL map to a **column** (left→right) and slot to a **row**.
4. WHERE a node declares a lane not in the canonical table, THEN the engine SHALL reject the declaration naming the unknown lane.
5. WHEN two nodes share a lane and region, THEN their slots SHALL order them along the secondary axis without overlap.

## Requirement 3 — Deterministic node placement

**User story:** As the engine, I want to compute every node's coordinates from its (lane, slot, region) using the canonical constants, so that placement is reproducible and on-grid.

#### Acceptance criteria

1. WHEN the engine places a node, THEN its `x` and `y` SHALL be computed from the canonical `COL_STEP`, `ROW_STEP`, `ICON_SIZE`, and `GRID` constants (from `diagram_layout.py`) and its (lane, slot, region) indices.
2. WHEN the engine places any node, THEN its `x` and `y` SHALL each be a whole multiple of `GRID` (i.e. `check_grid_alignment` returns clean).
3. WHEN two regions of the same diagram are placed, THEN their node blocks SHALL be laid out identically (mirror-symmetric), region B offset from region A by a fixed region step.
4. WHEN a region's node block is placed inside its VPC container, THEN the block SHALL be **centred** with equal left/right padding, snapped to the grid (per diagram-standards → symmetric on-grid placement).
5. WHEN placement completes, THEN no two node footprints (icon + label band) SHALL overlap (`check_node_overlap` returns clean).

## Requirement 4 — Container sizing and equal-width bands

**User story:** As the engine, I want to size and nest containers around their children, so that boundaries have correct padding and sibling regions are equal-width.

#### Acceptance criteria

1. WHEN the engine sizes a container, THEN it SHALL wrap all its child nodes' **footprints** (icon + label band) plus at least `CONTAINER_PAD` on every side (`check_container_padding` returns clean; ERROR for landscape).
2. WHEN containers nest (account ⊃ vpc ⊃ az), THEN each child SHALL sit fully inside its parent with `CONTAINER_PAD`, and no two sibling containers SHALL overlap (`check_container_overlap` returns clean).
3. WHEN two peer region containers (primary/passive VPC, and their matching AZ boxes) are sized, THEN they SHALL be the **same width**.
4. WHEN a parent's envelope is sized, THEN its bottom/right SHALL clear its deepest/rightmost child's footprint by ≥ `CONTAINER_PAD`, growing the parent rather than shrinking a child.
5. WHEN the outermost container is sized, THEN it SHALL wrap all region bands with `CONTAINER_PAD`, with no trailing empty margin.

## Requirement 5 — Contact-point selection

**User story:** As the engine, I want to choose each edge's exit/entry contact points by rule, so that edges are label-safe and fan-outs are distinct — without me hand-picking fractions.

#### Acceptance criteria

1. WHEN the engine selects an exit point, THEN it SHALL apply the exit priority ladder: right-centre by default; right, biased toward the run's direction; straight down the bottom only when that is the shortest path and no label lies between source and target.
2. WHEN the engine selects an entry point, THEN it SHALL choose the side by the incoming line (horizontal → left, vertical → top), centred, biasing extra entries toward their own line.
3. WHEN a node has two or three edges on one side, THEN the engine SHALL space their contact points so no two are closer than the merge threshold, and an edge to a directly-opposite target SHALL keep the centre (`check_exit_thirds` returns clean).
4. WHEN a node would have more than three edges on one side, THEN the engine SHALL report an over-connected error rather than emit a fourth contact point.
5. WHEN the engine emits any edge, THEN both its exit and entry contact points SHALL be explicitly set (`check_edge_float` returns clean) and obey the directional contract (`check_edge_direction` returns clean).

## Requirement 6 — Corridor allocation

**User story:** As the engine, I want to reserve a distinct corridor for each edge segment in the inter-column/inter-row gaps, so that parallel runs never merge and no waypoint is hand-picked.

#### Acceptance criteria

1. WHEN the engine routes edges through a shared gap, THEN it SHALL assign each edge segment its own corridor line offset from neighbours by ≥ one `GRID` step.
2. WHEN corridors are allocated, THEN every corridor line SHALL be a whole multiple of `GRID`.
3. WHEN two unrelated long edges are routed, THEN they SHALL NOT share a straight corridor (`check_corridor_sharing` returns clean); a shared trunk from a common source/target (or a chained node) is exempt.
4. WHERE a gap cannot hold every parallel run at one `GRID` step apart, THEN the engine SHALL widen the gap (push nodes/containers out a step) rather than place runs closer than one step.

## Requirement 7 — Orthogonal routing by edge class

**User story:** As the engine, I want to route each edge with the pattern for its class, so that the shapes match the reviewed reference and cross no icons.

#### Acceptance criteria

1. WHEN the engine classifies an edge, THEN it SHALL choose one class from `{straight, spine, fan-out-row, cross-region, back-edge}` based on the source/target lane + region relationship.
2. WHEN an edge is `straight` (target directly opposite, no obstacle between), THEN the engine SHALL emit a single straight segment through the centre.
3. WHEN an edge is `spine` (tier hop within a region), THEN the engine SHALL route it through a side corridor beside the column and enter the target's near face — never straight down the node column.
4. WHEN an edge is `fan-out-row` (source to several same-row targets), THEN each edge SHALL run its own below-row lane and turn up in the gap just before its target.
5. WHEN an edge is `cross-region`, THEN it SHALL step out sideways, rise into its own over-row corridor, run across, and enter the target's top.
6. WHEN an edge is `back-edge` (target left of source), THEN it SHALL exit right, loop in a dedicated corridor, and enter the target's left — never exit the side it enters.
7. WHEN the engine routes any edge, THEN it SHALL step one `GRID` into the gap before its first turn (stair), and route around any intervening node footprint or container border (clockwise), so the edge crosses no unrelated icon (`check_edge_routing` returns clean).
8. WHEN the engine routes any edge, THEN it SHALL use orthogonal segments and open arrowheads at ≥ 1pt stroke (`check_arrow_style` returns clean).

## Requirement 8 — Right-margin Flow/Legend placement

**User story:** As the engine, I want to place the Flow and Legend blocks in the right margin, so that they never overlap the cloud and stay readable.

#### Acceptance criteria

1. WHEN the engine places the Flow/Legend blocks, THEN their left edge SHALL be at least one `GRID` step past the outermost container's right edge.
2. WHEN the diagram is wide, THEN the engine SHALL pin the Flow/Legend blocks narrow and let them wrap taller (wrap-aware height) rather than run wide into the diagram body.
3. WHEN the Flow/Legend blocks are placed, THEN they SHALL NOT overlap any node, container border, or each other.
4. WHEN a diagram uses numeric flow markers, THEN the Flow block SHALL cover every marker in ascending order (`flow-legend` rule clean).

## Requirement 9 — Repair loop against the validators

**User story:** As the engine, I want to validate a candidate layout with the existing `check_*` rules and repair it, so that output is publication-eligible without manual inspection.

#### Acceptance criteria

1. WHEN the engine produces a candidate layout, THEN it SHALL run the geometry `check_*` validators as its acceptance oracle.
2. IF a validator reports a fixable finding (corridor collision, tight container padding, off-centre block), THEN the engine SHALL apply the corresponding repair (widen corridor, grow container, re-centre) and re-validate.
3. WHEN the repair loop terminates, THEN the layout SHALL have zero ERROR and zero CRITICAL findings, OR the engine SHALL fail with an error naming the unresolved finding.
4. WHEN the repair loop runs, THEN it SHALL be bounded (terminate in a fixed number of iterations) and deterministic (same input → same output).

## Requirement 10 — Reference comparison and verification

**User story:** As a maintainer, I want the engine's output compared against the preserved hand-authored reference, so that I can confirm the generated diagram is at least as good.

#### Acceptance criteria

1. WHEN the migration begins, THEN each current `NN-...-{summary,landscape}.drawio` SHALL be copied to `NN-...-{summary,landscape}-reference.drawio` (kept out of the lint scan like other non-golden artifacts, or documented as reference-only).
2. WHEN the engine generates a diagram, THEN it SHALL produce the full artifact triple (`.drawio`, `.drawio.png`, `.diagram.md`) for each of the four providers × two classes.
3. WHEN a generated diagram is linted, THEN it SHALL be publication-eligible (zero CRITICAL/ERROR) under `rule-engine-lint --all`.
4. WHEN generated rasters are checked, THEN they SHALL be within the class raster budget (`rule-engine-check-rasters`).
5. WHEN the full gate runs, THEN `pytest`, `rule-engine-lint --all`, `rule-engine-check-rasters`, and `rule-engine-check-asset-paths` SHALL all pass.
6. WHEN the generated output is compared to the reference, THEN a maintainer SHALL be able to view both rasters side by side and confirm the generated one meets every routing rule the reference was hand-tuned to satisfy.

## Requirement 11 — Determinism and provider parity

**User story:** As a maintainer, I want the engine to be deterministic and skin-agnostic, so that all four providers share one geometry and regeneration is reproducible.

#### Acceptance criteria

1. WHEN the engine runs twice on the same declaration, THEN it SHALL produce byte-identical `.drawio` geometry (nodes, containers, edge waypoints).
2. WHEN two providers use the same declaration, THEN their generated geometry SHALL be identical; only the icon renderer and labels SHALL differ.
3. WHEN a new provider is added, THEN it SHALL require only a skin (icon renderers + labels), no geometry.
4. WHEN the engine emits coordinates, THEN they SHALL be integers on the `GRID`.

## Requirement 12 — Landscape as-built matches the reference layout shape

**User story:** As a maintainer comparing the engine's landscape output to the preserved `-reference`, I want the generated as-built to reproduce the reference's structural *shape* — availability zones stacked vertically within a VPC, equal-width peer zones, a distinct VPC service row above the zones, and a canvas that starts at the origin — so that the engine is not merely lint-clean but reads as well as the hand-tuned original.

**Rationale (2026-09-23 review):** the first engine-generated AWS landscape was publication-eligible and lint-identical to the reference, yet read worse. A side-by-side of `examples/aws/02-aws-ha-multiregion-landscape.drawio.png` against its `-reference` showed four structural regressions, all traced to the placement model rather than the routing model:

- the two AZ boxes were laid out **side by side along the secondary axis and at different widths** (`az-a1` w=578 vs `az-a2` w=358) instead of stacked vertically at equal width (reference: both w=980, `az-a1` above `az-a2`);
- the VPC **service row** (lb / queue / fn / secrets) merged into the AZ rows instead of forming a distinct tier **above** the zones;
- the account envelope extended into **negative canvas coordinates** (`x=-220`) because the account-level edge row skewed the extent;
- the North–South vertical tiering was compressed and the diagram spread wide instead.

This requirement pins the reference's structural shape as a checked contract so the engine cannot drift from it. It refines Requirements 3 and 4 for the `landscape` class specifically; it does not relax any existing acceptance criterion.

#### Acceptance criteria

1. WHEN the engine lays out a `landscape` diagram whose VPC declares two or more AZ containers, THEN those peer AZ containers SHALL be stacked along the **primary** (tier) axis — one below the other for a North–South diagram — never placed side by side along the secondary axis.
2. WHEN two peer AZ containers of the same VPC are sized, THEN they SHALL have the **same** secondary-axis size (equal width for a North–South diagram), consistent with the peer-band equal-width rule (Req 4.3).
3. WHEN a region declares service-row nodes that belong to the VPC directly (declared membership = the VPC, not an AZ), THEN those nodes SHALL be placed in a distinct tier **between** the region's VPC boundary edge and its first AZ box, and no AZ box SHALL wrap or overlap a VPC service-row node.
4. WHEN the engine sizes the outermost (account) container and emits the page, THEN every container and node origin SHALL have non-negative `x` and `y`, and the layout's minimum `x`/`y` SHALL be a small fixed margin (e.g. `CONTAINER_PAD`) from the origin — the account-level edge row SHALL NOT pull any coordinate negative.
5. WHEN a `landscape` diagram is laid out North–South, THEN its tiers (account-edge row → VPC service row → AZ-1 → AZ-2) SHALL descend top→bottom, preserving the North–South convention (external/edge at the top, zones/data below), rather than compressing vertically and spreading horizontally.
6. WHEN the engine's `landscape` output is compared against its `-reference` sibling, THEN a structural-shape check SHALL confirm the reference invariants hold on the generated diagram: peer AZ boxes stacked (AC1) and equal-width (AC2), a distinct service-row tier (AC3), and non-negative on-grid origins (AC4). This check compares structural invariants, not exact byte coordinates (the engine remains free to choose absolute positions).
