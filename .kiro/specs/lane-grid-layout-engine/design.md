# Design — Declarative Lane-Grid Layout Engine

## Overview

The engine turns a **coordinate-free declaration** into placed `Node` / `Boundary` / `Edge` objects that `build_diagram` already knows how to serialize. It sits **between** the declaration and the existing assembler, and reuses the existing `geometry.check_*` validators as its acceptance oracle.

```
declaration (no coords)
        │
        ▼
┌───────────────────────────── layout_engine ─────────────────────────────┐
│  1. lane model      → resolve each node's (row, col) from (lane, slot)    │
│  2. placement       → (row,col,region) → x,y  (grid-aligned)              │
│  3. containers      → size account/vpc/az around child footprints + PAD  │
│  4. centre + equal  → equal-width bands, centre each block in its VPC     │
│  5. contact points  → exit/entry per the priority ladder                 │
│  6. corridors       → reserve a grid-step lane per edge segment          │
│  7. routing         → per edge class, emit waypoints                     │
│  8. legend place    → right margin, past the account box                 │
│  9. repair loop     → run check_*; widen/re-centre; re-validate          │
└──────────────────────────────────────────────────────────────────────────┘
        │  Node[], Boundary[], Edge[]  (fully placed)
        ▼
build_diagram(...)  →  .drawio   (unchanged)
```

**Key principle (ponytail):** the engine does not re-implement the constraints — the `check_*` functions already encode them. The engine *produces* a candidate and *asks* the validators; where a validator says "bad," a small, named repair adjusts the candidate. No new validation logic, no duplicated thresholds.

## Module layout

New module `src/rule_engine/layout_engine.py`. It imports the canonical constants and the data model from `diagram_layout.py`, and the validators from `geometry.py`. It exposes one entry point:

```python
def layout(spec: DiagramSpec) -> PlacedDiagram: ...
```

`PlacedDiagram` holds the placed `Node`/`Boundary`/`Edge` lists plus the legend x/width, ready to pass straight into `build_diagram`. `scripts/ha_multiregion_common.py` shrinks to: (a) the two `DiagramSpec` declarations (summary + landscape), (b) the `ProviderSkin` (icons + labels), (c) a thin `build_summary`/`build_landscape` that calls `layout(...)` then `build_diagram(...)`.

Nothing in `diagram_layout.py` (the assembler) or `geometry.py` (the validators) changes behaviourally; `diagram_layout.py` may gain small pure helpers the engine reuses (e.g. a footprint size helper) but its output format is untouched.

## Data model (the declaration)

All coordinate-free. Lives in `layout_engine.py`.

```python
Axis = Literal["north-south", "left-right"]

@dataclass(frozen=True)
class NodeSpec:
    id: str
    role: str            # resolves to an icon via the skin / icon-index
    lane: str            # one of the 8 canonical lanes
    region: str          # "a" | "b" | "" (account-level, e.g. edge row)
    slot: int            # 0-indexed position within (lane, region)
    sub: int = 0         # optional secondary offset for a sub-row (api/mon)

@dataclass(frozen=True)
class EdgeSpec:
    id: str
    source: str
    target: str
    marker: str
    dashed: bool = False
    # class is DERIVED, not declared (Req 7.1); an optional hint may override.
    kind_hint: Optional[str] = None

@dataclass(frozen=True)
class ContainerSpec:
    id: str
    kind: str            # "account" | "vpc" | "az"
    region: str
    parent: Optional[str]     # nesting: az.parent = vpc, vpc.parent = account
    label_key: str            # skin fills the concrete label

@dataclass(frozen=True)
class DiagramSpec:
    diagram_id: str
    diagram_name: str
    axis: Axis
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeSpec, ...]
    containers: tuple[ContainerSpec, ...]
    flow_lines: tuple[str, ...]
    title: str
```

`Req 1.4` (reject coordinates): the dataclasses simply have no coordinate fields, so a coordinate cannot be expressed. A declaration is validated on entry (`_validate_spec`) for unknown lanes (`Req 2.4`), duplicate slots, and dangling edge endpoints.

## 1. Lane model (Req 2)

```python
LANES = ("actors", "edge", "router", "async", "workers",
         "platform", "data", "on-premises")
LANE_INDEX = {name: i for i, name in enumerate(LANES)}
```

The lane index maps to the **primary** axis; the slot maps to the **secondary** axis:

| Axis | lane index → | slot → |
|---|---|---|
| `north-south` (landscape/infra) | row (top→bottom) | column (left→right) |
| `left-right` (summary/flow) | column (left→right) | row (top→bottom) |

Note the HA landscape's real structure is region → AZ tiers rather than a literal 8-lane column; lanes are still the *ordering* device (edge row at top, service row, AZ rows below). The engine treats `(region, tier, slot)` as the placement key; `tier` is derived from the lane + AZ membership. This keeps the model faithful to the shipped diagram without forcing an artificial 8-row grid.

## 2. Placement (Req 3)

Pure function `place_nodes(spec) -> dict[str, Box]`. For each node:

```
col_index = slot
row_index = tier_of(node)          # derived from lane + AZ
x = REGION_ORIGIN[region] + col_index * COL_STEP
y = TIER_ORIGIN[tier]    + node.sub * SUB_ROW_STEP
snap x, y to GRID
```

`REGION_ORIGIN`, `TIER_ORIGIN`, `COL_STEP`, `SUB_ROW_STEP` are derived from the `diagram_layout` constants (`COL_STEP`, `ROW_STEP`, `ICON_SIZE`, `GRID`). Region B's origin = region A's origin + `REGION_STEP` (a fixed, grid-aligned offset), giving mirror-symmetry (`Req 3.3`). All origins are grid multiples so `check_grid_alignment` is clean by construction (`Req 3.2`).

## 3–4. Containers, equal width, centring (Req 4, Req 3.4)

`size_containers(placed, spec)`:
- For each `az`/`vpc`/`account` container (deepest first), compute the bounding box of its children's **footprints** (icon + `LABEL_BAND`), then expand by `CONTAINER_PAD` on every side. Bottom-up so a parent wraps already-sized children (`Req 4.1, 4.4`).
- **Equal width:** peer containers (vpc-a/vpc-b, az-a*/az-b*) take the **max** width across the pair, applied to both (`Req 4.3`). Widen toward the shared centre so outer edges stay put.
- **Centre the block:** after sizing, `centre_block_in_vpc` shifts each region's whole node block (and later its edge waypoints) by the grid-rounded delta between block-centre and vpc-centre (`Req 3.4`). This is the one transform kept from today's code, now driven by the computed boxes rather than hand tables.
- **Account envelope:** wrap all VPC bands + `CONTAINER_PAD`, no trailing margin (`Req 4.5`).

`check_container_padding` / `check_container_overlap` are run after sizing as the oracle.

## 5. Contact-point selection (Req 5)

`select_contacts(edge, placed) -> (exit, entry)` implements the priority ladder as pure geometry from the two node boxes:

- **Exit:** if target is directly opposite on the same row and adjacent → right-centre `(1.0, 0.5)`; if target is directly below and nothing lies between → bottom-centre `(0.5, 1.0)`; otherwise right, biased toward the target's vertical direction (upper third for a target above, lower third for below).
- **Entry:** side chosen by the incoming segment orientation (horizontal → left `(0.0, y)`, vertical → top `(x, 0.0)`), centred.
- **Fan-out spread:** when several edges share a source side, `spread_contacts` assigns distinct band coordinates ≥ the merge threshold apart, keeping a straight-line edge on the centre (`Req 5.3`). Over three on a side → raise `OverConnectedError` (`Req 5.4`).

Validated by `check_edge_direction`, `check_exit_thirds`, `check_edge_float`.

## 6. Corridor allocation (Req 6)

`CorridorAllocator` reserves grid-step lines in the inter-column / inter-row gaps.

- The plane between two adjacent columns is a **gap** of width `COL_STEP - ICON_SIZE`; corridor lines are `gap_left + k*GRID` for k = 1, 2, …
- Each edge segment that needs a shared gap requests a corridor; the allocator hands out the next free line, tracking occupancy per gap (`Req 6.1, 6.2`).
- Over-row / under-row corridors (for cross-region and fan-out) are allocated the same way in the inter-row gaps.
- If a gap runs out of lines, the allocator signals "widen" → the repair loop pushes the neighbouring column/container out one `COL_STEP`/`GRID` and retries (`Req 6.4`).

`check_corridor_sharing` is the oracle; the allocator is its inverse (assign free lanes so the check is clean).

## 7. Routing by edge class (Req 7)

`classify_edge(edge, placed) -> EdgeKind` from the source/target tier + region + column relationship:

| Condition | Kind | Route shape |
|---|---|---|
| same row, adjacent, nothing between | `straight` | single centred segment |
| tier hop within a region | `spine` | exit right → side corridor beside the column → enter target top |
| source → several same-row targets to its right | `fan-out-row` | own below-row lane each → turn up in the gap just before the target |
| source region A → target region B | `cross-region` | step out → own over-row corridor → across → enter target top |
| target column left of source | `back-edge` | exit right → dedicated loop corridor → enter target left |

Each router is a pure function `route_<kind>(edge, exit, entry, allocator, obstacles) -> list[point]`:
- **stair:** first waypoint steps one `GRID` into the gap corridor before any turn (`Req 7.7`).
- **obstacle avoidance:** the set of other node footprints + container borders is the obstacle set; a candidate straight run is tested with the same segment-sampling predicate `check_edge_routing` uses; on a hit, the router detours **clockwise** by one corridor (`Req 7.7`).
- **waypoint coords** land on allocated corridor lines, so `check_corridor_sharing` and `check_edge_routing` are clean.

Open arrowheads / stroke width are already fixed by `edge_cell`; `check_arrow_style` stays clean (`Req 7.8`).

## 8. Legend placement (Req 8)

`place_legend(account_box, flow_lines) -> (legend_x, legend_w)`:
- `legend_x = account_box.right + CONTAINER_PAD` (`Req 8.1`).
- `legend_w` pinned narrow (a fixed narrow width); `build_diagram`'s existing wrap-aware `_text_h` grows the boxes taller (`Req 8.2`). This reuses the `legend_w` parameter already added to `build_diagram`.
- Flow/Legend never overlap nodes/containers because they start past the account box (`Req 8.3`).

## 9. Repair loop (Req 9)

```python
def layout(spec):
    cand = _place_and_route(spec)          # steps 1–8
    for _ in range(MAX_REPAIR_ITERS):
        findings = _run_oracle(cand)        # geometry.check_* on the candidate
        if not findings.blocking:           # zero ERROR/CRITICAL
            return cand
        cand = _repair(cand, findings)      # named repair per finding type
    raise LayoutError(findings.first_unresolved)
```

- `_run_oracle` builds a `DiagramGeometry` from the candidate (reusing `build_geometry` on a serialized draft, or a direct in-memory adapter) and runs the `check_*` set.
- `_repair` maps each finding to one deterministic fix: `corridor-sharing` → re-allocate the later edge to the next lane; `container-padding` → grow the container; block off-centre → re-centre; over-connected → raise (unfixable, `Req 9.3`).
- Bounded by `MAX_REPAIR_ITERS`; deterministic ordering of findings and repairs (`Req 9.4`).

## 10. Reference comparison & migration (Req 10)

- Before migrating, copy each committed `NN-...-{summary,landscape}.drawio` to `NN-...-{summary,landscape}-reference.drawio`. Reference files are excluded from generation and documented; the lint scan already skips non-topic patterns, and we add `-reference` to the discovery exclusion so they neither lint nor get regenerated.
- `build_summary`/`build_landscape` call `layout(spec)` then `build_diagram(...)`; the four `build_*_ha_example.py` scripts are unchanged (still supply the skin).
- Full gate (`pytest`, `rule-engine-lint --all`, `rule-engine-check-rasters`, `rule-engine-check-asset-paths`) is the acceptance (`Req 10.5`); rasters compared to `-reference` visually (`Req 10.6`).

## 11. Determinism & parity (Req 11)

- The engine is pure: same `DiagramSpec` → same placed geometry → byte-identical `.drawio` (`Req 11.1`). No randomness, no time, no dict-order reliance (sort by id).
- Geometry is computed from the spec + constants only; the skin is applied by `build_diagram` via each node's `render`, so two providers on one spec share geometry (`Req 11.2, 11.3`).
- All emitted coordinates are grid-aligned integers (`Req 11.4`).

## 12. Landscape shape parity with the reference (Req 12)

The 2026-09-23 review found the generated `landscape` publication-eligible but structurally worse than its `-reference`. Root cause is the placement model: `place_nodes` offsets a node's `sub`/`slot` along the **secondary** axis, and the AZ leaf partition spread peer zones sideways at unequal widths. The fix keeps routing untouched and changes how declared containers map to tier bands.

- **AZ stacking (Req 12.1):** peer AZ containers of one VPC are assigned **successive primary-axis tier bands** — for North–South, `az-1` then `az-2` in the band below it — so their boxes are disjoint and stacked, never side by side. `tier_of` maps declared-`container` AZ membership to a distinct tier band per AZ rather than a shared band split along the secondary axis.
- **Equal-width AZ (Req 12.2):** peer AZ boxes run through the same equal-width peer-band pass as the VPCs — `_equalize_peer_widths` is extended to `az` peers — so `az-a1` width == `az-a2` width (`Req 4.3` applied to AZs).
- **Service-row tier (Req 12.3):** nodes whose declared `container` is the VPC itself (not an AZ) are placed in a dedicated tier band **between** the VPC top border and the first AZ band. `size_containers` sizes each AZ box from its own children only, so no AZ box wraps a VPC-direct service-row node.
- **Non-negative origins (Req 12.4):** after sizing, a final `_normalise_origin` pass translates the whole layout (all nodes, containers, and edge waypoints) by one grid-aligned delta so `min(x) == min(y) == CONTAINER_PAD`. The account-edge row can therefore never pull a coordinate negative. The translation is a single deterministic, grid-aligned shift.
- **North–South tiering (Req 12.5):** placement keeps lane index → row and AZ tiers descending, so the account-edge row is the top tier and the service row, then `az-1`, then `az-2`/data descend below it — vertical tiering, not horizontal spread.
- **Structural-shape check (Req 12.6):** a new **test-time predicate** (not a new linter rule) asserts on the generated `landscape` geometry that peer AZ boxes are stacked (shared x-range, disjoint y-range for N–S) and equal-width, the VPC service-row nodes sit above the first AZ band, and every origin is non-negative on-grid. It compares structural invariants, not byte coordinates, so the engine stays free to choose absolute positions.

## Testing strategy

- **Unit (pure functions):** `place_nodes` (grid alignment, symmetry), `size_containers` (padding, equal width), `select_contacts` (ladder cases), `CorridorAllocator` (distinct lanes, widen-on-exhaust), each `route_<kind>` (shape + no-crossing), `place_legend` (past account box).
- **Property-based:** for a generated family of small specs, the engine's output passes every `check_*` validator (the oracle is the invariant).
- **Golden/parity:** the four providers × two classes generate publication-eligible triples; geometry identical across providers; regeneration is byte-stable.
- **Reference gate:** generated landscape/summary pass the same geometry checks the hand-authored reference passed (no regression in routing quality).
- **Reference-shape parity:** a structural check on the generated `landscape` asserts peer AZ boxes are stacked and equal-width, the VPC service row forms a distinct tier above the zones, and all origins are non-negative on-grid (Req 12).
- Reuse the existing gate commands; add `tests/test_layout_engine.py`.

## Integration points & risks

- **draw.io orthogonal router drift** (seen during hand-tuning): the engine emits explicit waypoints on allocated corridor lines and pins exit/entry, exactly as today, so the renderer has no freedom to drift. The first waypoint always changes both axes from the exit point (learned: a waypoint on the exit's own axis collapses).
- **`_run_oracle` adapter:** cheapest correct path is to serialize the candidate with `build_diagram` (icons stubbed) and `build_geometry` it back — reuses parsing exactly as the linter sees it. A direct in-memory `DiagramGeometry` builder is an optimization if needed.
- **Scope guard:** the routers cover the five classes present in the HA diagrams; an edge that classifies as none raises rather than emitting a guessed route (fail-honest, matching the icon-resolution philosophy).
