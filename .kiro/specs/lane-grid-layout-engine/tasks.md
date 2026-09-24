# Implementation Plan — Declarative Lane-Grid Layout Engine

Each task is incremental, test-backed, and cites the requirements it satisfies.
Build the engine bottom-up (pure placement → routing → repair), keep the gate
green after every task, and migrate the generator only once the engine
reproduces the reference. Do not add tests beyond what a task states.

- [x] 1. Scaffold the module and declaration data model
  - Create `src/rule_engine/layout_engine.py` with the `NodeSpec`, `EdgeSpec`,
    `ContainerSpec`, `DiagramSpec` frozen dataclasses (no coordinate fields) and
    the `LANES` / `LANE_INDEX` table.
  - Add `_validate_spec(spec)` that rejects unknown lanes, duplicate
    `(lane, region, slot)`, and dangling edge endpoints with a named error.
  - Import canonical constants from `diagram_layout` (`ICON_SIZE`, `GRID`,
    `COL_STEP`, `ROW_STEP`, `CONTAINER_PAD`) — do not redefine them.
  - Unit tests: valid spec passes; unknown lane, duplicate slot, and dangling
    edge each raise with the offending field named.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.4_

- [x] 2. Node placement on the lane grid
  - Implement `place_nodes(spec) -> dict[str, Box]`: derive `(tier, col)` from
    `(lane, region, slot, sub)` and compute grid-aligned `x, y` from the
    constants and `REGION_STEP`; region B mirrors region A.
  - Implement the axis rule (north-south vs left-right) from `spec.axis`.
  - Unit tests: every origin is a `GRID` multiple; region B is region A + a
    fixed step (mirror-symmetric); no two footprints overlap
    (assert `check_node_overlap` clean on the placed boxes).
  - _Requirements: 2.2, 2.3, 2.5, 3.1, 3.2, 3.3, 3.5_

- [x] 3. Container sizing, equal width, and block centring
  - Implement `size_containers(placed, spec)`: bottom-up footprint bounding box
    + `CONTAINER_PAD`; peer containers take the pair's max width (equal-width
    bands); account envelope wraps all bands with no trailing margin.
  - Implement `centre_block_in_vpc(placed, containers)`: shift each region's
    whole node block by the grid-rounded (block-centre → vpc-centre) delta.
  - Unit tests: `check_container_padding` and `check_container_overlap` clean;
    peer VPC/AZ widths equal; each region's block centred (equal left/right
    padding, on grid).
  - _Requirements: 3.4, 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 4. Contact-point selection (exit/entry ladder)
  - Implement `select_contacts(edge, placed)` for the exit priority ladder
    (right-centre → straight-down-if-shortest → right-biased) and the
    entry-by-incoming-line rule.
  - Implement `spread_contacts(edges_on_side)`: distinct band coords ≥ merge
    threshold apart, straight-line edge keeps the centre; raise
    `OverConnectedError` on a 4th same-side edge.
  - Unit tests: each ladder branch returns the expected contact; a fan-out of
    three passes `check_exit_thirds`; all emitted contacts pass
    `check_edge_direction` and `check_edge_float`; a 4th same-side edge raises.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 5. Corridor allocator
  - Implement `CorridorAllocator`: per inter-column / inter-row gap, hand out
    grid-step-aligned corridor lines, tracking occupancy; signal "needs widen"
    when a gap is exhausted.
  - Unit tests: distinct requests get distinct grid-aligned lines; two unrelated
    long edges routed through it pass `check_corridor_sharing`; exhausting a gap
    raises the widen signal.
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 6. Edge classifier and per-class routers
  - Implement `classify_edge(edge, placed)` → one of
    `{straight, spine, fan-out-row, cross-region, back-edge}`.
  - Implement each `route_<kind>(edge, exit, entry, allocator, obstacles)` as a
    pure function emitting corridor-aligned waypoints, with the stair step and
    clockwise obstacle detour (reuse the `check_edge_routing` segment-sampling
    predicate as the obstacle test).
  - An edge that classifies as none raises (fail-honest, no guessed route).
  - Unit tests: each class produces the expected shape and crosses no obstacle
    (`check_edge_routing` clean); the first waypoint changes both axes off the
    exit point (no collapse); an unclassifiable edge raises.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

- [x] 7. Legend placement
  - Implement `place_legend(account_box, flow_lines) -> (legend_x, legend_w)`:
    `legend_x = account.right + CONTAINER_PAD`, `legend_w` pinned narrow (reuse
    the existing `build_diagram` `legend_w` wrap-aware sizing).
  - Unit tests: `legend_x` is past the account box; the blocks do not overlap
    any node/container box or each other.
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 8. Oracle adapter and repair loop
  - Implement `_run_oracle(candidate)`: serialize the candidate via
    `build_diagram` (stub icons) and `build_geometry` it back, then run the
    geometry `check_*` set; classify findings as blocking vs fixable.
  - Implement `_repair(candidate, findings)`: one deterministic fix per finding
    type (corridor-sharing → next lane; container-padding → grow; off-centre →
    re-centre; over-connected → raise).
  - Implement `layout(spec)`: place → size → centre → contacts → corridors →
    route → legend, then the bounded repair loop; return `PlacedDiagram`.
  - Unit tests: a deliberately colliding candidate is repaired to zero blocking
    findings; an unfixable candidate raises after the bound; `layout` is
    deterministic (same spec → identical output twice).
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 11.1, 11.4_

- [x] 9. Property-based invariant test
  - Add a property test: for a generated family of small valid `DiagramSpec`s,
    `layout(spec)` output passes every geometry `check_*` validator (zero
    ERROR/CRITICAL).
  - _Requirements: 9.3, 10.3_

- [x] 10. Preserve the reference diagrams
  - Copy each committed `NN-...-{summary,landscape}.drawio` (+ `.drawio.png`,
    `.diagram.md`) to a `-reference` sibling; add the `-reference` pattern to the
    discovery/scan exclusion so they are neither linted nor regenerated.
  - Verify the reference files still lint-skip and the gate stays green.
  - _Requirements: 10.1_

- [x] 11. Author the HA declarations
  - Write the `DiagramSpec` for the summary and the landscape (nodes with
    role/lane/region/slot, edges with source/target/type, containers) — no
    coordinates. Encode the same topology the current tables express.
  - Unit test: both specs pass `_validate_spec`.
  - _Requirements: 1.5, 2.5_

- [x] 12. Migrate the generator to the engine
  - Replace the `SUMMARY_*` / `LANDSCAPE_*` coordinate tables and the
    `_compact_landscape` / `_centre_regions_in_vpc` transforms in
    `ha_multiregion_common.py` with the two `DiagramSpec`s and a thin
    `build_summary`/`build_landscape` that calls `layout(spec)` then
    `build_diagram(...)`. Keep `ProviderSkin` (icons + labels) unchanged.
  - Regenerate all four providers × two classes.
  - Verify geometry is identical across the four providers (parity).
  - _Requirements: 1.5, 11.2, 11.3_

- [x] 13. Full verification and reference comparison
  - Export all eight rasters; run the full gate: `pytest`,
    `rule-engine-lint --all`, `rule-engine-check-rasters`,
    `rule-engine-check-asset-paths` — all clean.
  - Confirm each generated diagram is publication-eligible and within the raster
    budget; compare each generated raster against its `-reference` to confirm no
    routing-quality regression.
  - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 14. Documentation and changelog
  - Update `docs/DIAGRAM-DESIGN-NOTES.md` with the engine's placement/routing
    model; add a CHANGELOG entry describing the declarative layout engine and
    the migration off hand-authored coordinate tables.
  - _Requirements: (documentation of 1–11)_

- [x] 15. Stack availability zones vertically with equal width
  - In `src/rule_engine/layout_engine.py`, change the placement/sizing so peer
    `az` containers of one VPC occupy **successive primary-axis tier bands**
    (north-south: `az-1` above `az-2`), never side-by-side on the secondary
    axis. Map declared-`container` AZ membership to a distinct tier band per AZ.
  - Extend the equal-width peer-band pass (`_equalize_peer_widths`) to `az`
    peers within a VPC so `az-a1` width == `az-a2` width (and mirror in region B).
  - Keep North–South tiering: account-edge row at the top, then descending.
  - Unit tests: for a two-AZ VPC, the two AZ boxes share an x-range and have
    disjoint y-ranges (stacked) and equal width; `check_container_overlap` and
    `check_container_padding` stay clean.
  - _Requirements: 12.1, 12.2, 12.5_

- [x] 16. VPC service-row tier above the availability zones
  - Place nodes whose declared `container` is the VPC itself (not an AZ) in a
    dedicated tier band **between** the VPC top border and the first AZ band, so
    the service row (lb/queue/fn/secrets) reads as a distinct tier above the
    zones.
  - Ensure `size_containers` sizes each AZ box from its own AZ children only, so
    no AZ box wraps or overlaps a VPC service-row node.
  - Unit tests: every VPC-direct service-row node's footprint sits above the
    first AZ box's top and inside the VPC; no AZ box contains a service-row node.
  - _Requirements: 12.3_

- [x] 17. Normalise the layout origin to non-negative coordinates
  - Add a final `_normalise_origin` pass that translates the whole placed layout
    (all node boxes, container boxes, and edge waypoints) by one grid-aligned
    delta so `min(x) == min(y) == CONTAINER_PAD` — the account-level edge row can
    never pull a coordinate negative. Deterministic and grid-aligned.
  - Unit tests: after `layout(spec)`, every node and container origin has
    non-negative `x`/`y`, `min(x) == min(y) == CONTAINER_PAD`, all origins stay
    grid-aligned, and geometry is unchanged relative to the pre-normalise layout
    (a pure translation preserves the oracle result).
  - _Requirements: 12.4_

- [x] 18. Structural-shape parity check and regeneration
  - Add a test-time structural predicate (not a new linter rule) asserting on the
    generated `landscape` geometry: peer AZ boxes stacked (shared x-range,
    disjoint y-range) and equal-width, VPC service-row nodes above the first AZ
    band, and all origins non-negative on-grid. Run it on all four providers.
  - Regenerate the eight diagrams and re-export the eight rasters; run the full
    gate (`pytest`, `rule-engine-lint --all`, `rule-engine-check-rasters`,
    `rule-engine-check-asset-paths`) — all clean; confirm the landscape now
    reproduces the reference's structural shape.
  - _Requirements: 12.6_
- [x] 19. Compact the inter-tier vertical gaps (Req 12.5 quality refinement)
  - The Task-15/16 tier-band step (`_az_band_step`) is derived from the span of
    lane INDICES a band's nodes occupy, which over-reserves vertical space when
    the nodes actually stack in a narrow column (the shipped landscape leaves a
    ~482px empty gap between the VPC service row and az-1). Recompute the band
    step from the band content's ACTUAL vertical extent (the real footprint
    height a band occupies within one region) plus one `CONTAINER_PAD`, not the
    lane-index span, so successive tiers sit one grid-padded gap apart.
  - Keep every Req-12 invariant: AZs stacked & equal-width, service row a
    distinct tier above the AZs (gap ≥ `CONTAINER_PAD`, no overlap), non-negative
    on-grid origins; layout stays clean; gate stays green.
  - Regenerate the eight diagrams + rasters; full gate clean.
  - _Requirements: 12.5_
- [x] 20. Per-band packing to remove the inter-tier gap (Req 12.5 quality refinement)
  - Replace the uniform `band * _az_band_step` primary-axis offset with
    **per-band packing**: each tier band starts at the previous band's actual
    content bottom + one `CONTAINER_PAD`, and within a band a node's primary-axis
    position uses its lane index **relative to that band's own minimum lane**
    (not the absolute lane index), so a band is flush to its own top and no
    empty lanes are reserved above it. Removes the ~500px empty gap between the
    VPC service row and az-1 while keeping every tier ≥ `CONTAINER_PAD` apart.
  - Keep all Req-12 invariants (AZs stacked & equal-width, service row a distinct
    tier above the AZs, non-negative on-grid origins) and determinism.
  - Regenerate the eight diagrams + rasters; full gate clean.
  - _Requirements: 12.5_
