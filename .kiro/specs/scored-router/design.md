# Design — Scored Diagram Router (release 1.8.0)

## Overview

Routing today is **rule-driven with no feedback loop**. Each of the ~25 named
routing patterns in `diagram-standards.md` was distilled from a reviewer hand-edit,
and each router applies its pattern with no view of the diagram as a whole. That
works until two patterns want the same plane. `geometry.route_cost` already
measures the objective (crossings, rails, turns, ink) and a ratchet in
`tests/test_route_quality.py` pins each shipped diagram's ceiling — but nothing
*optimises* against that objective. This is the largest engineering Open gap in
`docs/REVIEW.md`.

This spec closes it in three sequenced, independently reviewable pieces for
release 1.8.0:

1. **`layout/` package split (prerequisite).** `layout_engine.py` (≈3,960 lines)
   decides every edge's contacts in **ten sequential global passes**
   (`1`, `1b`, `1c`, `1c2`, `1d`, `2`, `2b`, `2b3`, `2b4`, `2c`) *before* any edge
   is routed, so there is no per-edge decision point to score. We split the module
   into a `layout/` package whose seam exposes a **per-edge decision point** where
   contacts *and* route are chosen together. This is a **behavior-preserving
   refactor**: every shipped `.drawio` stays byte-identical (`generator --check`
   green) and every test passes *before* any output changes.
2. **Graded rails metric.** `route_cost` counts a rail as a binary at
   `RAIL_CLEARANCE = 40px`: a run 39px from an icon and one 2px away score
   identically, even though the second is the defect a reviewer objects to. We
   replace the binary count with a penalty **inversely proportional to clearance**,
   and re-baseline the ratchet in the same change so the two real 1.7.0
   improvements that were invisible to the score now register.
3. **Scored router.** Invert the pipeline per the REVIEW.md design: for each edge,
   generate the router's **sanctioned variants** as `(contacts + route)` pairs,
   score each with the (now graded) `route_cost` against the edges already
   accepted, take the minimum, and **snapshot/restore the `CorridorAllocator`** so
   a rejected variant consumes no lanes. Order edges **most-constrained-first**.
   Deterministic: same inputs → same `.drawio`.

**Placement variants are explicitly deferred** (see *Decision D2*). The two
remaining placement defects (the tier-skip rail, the GCP/OCI hub) are placement
problems, not routing ones; 1.8.0 scores **routes only** and leaves the placement
seam in the architecture for a later release.

This design satisfies the requirements in `requirements.md` (authored next) and
respects every honest-gates gate now in force: determinism, no weakened lint rule,
draw.io as the only publishable source (D1), and a tightened — never regressed —
route-quality ratchet.

### Non-goals

- The four smaller Open gaps are **out of scope**: inventory→diagram
  reconciliation, container dead-space, and icon-index slug-collision
  disambiguation. Each is a separate future spec.
- **Scoring placement variants** (moving a node/tier to relieve a defect) is a
  design-noted future step, not built in 1.8.0 (*Decision D2*).
- The **version bump to 1.8.0** (CHANGELOG, version triple, pack pins) is a task in
  `tasks.md`, not work performed during spec creation.

## Architecture

### Before → after (the pipeline inversion)

Today `_place_and_route` runs the contact passes globally, then routes:

```
DiagramSpec
   │
   ▼
place → size → centre
   │
   ▼
contacts: pass 1 → 1b → 1c → 1c2 → 1d → 2 → 2b → 2b3 → 2b4 → 2c   (GLOBAL, all edges)
   │
   ▼
route every edge (CorridorAllocator hands out lanes greedily, in declared order)
   │
   ▼
repair loop (widen / re-centre) → PlacedDiagram → build_diagram → .drawio
```

The scored router **inverts** the contacts+route stage into a per-edge loop while
leaving place/size/centre and the repair loop unchanged:

```
DiagramSpec
   │
   ▼
place → size → centre                          (unchanged)
   │
   ▼
order edges MOST-CONSTRAINED-FIRST
   │
   ▼
for each edge e, in that order:
   ├─ generate SANCTIONED VARIANTS of e   →  [(contacts, route), …]
   ├─ for each variant v:
   │     ├─ allocator.snapshot()
   │     ├─ tentatively route v (may consume lanes)
   │     ├─ score = route_cost(accepted ∪ {v})     (graded rails)
   │     └─ allocator.restore(snapshot)            (rejected v frees its lanes)
   ├─ pick argmin(score)  (deterministic tie-break)
   ├─ commit the winner   (its lanes are re-allocated for real)
   └─ accepted += winner
   │
   ▼
repair loop (widen / re-centre)                 (unchanged)
   │
   ▼
PlacedDiagram → build_diagram → .drawio
```

### `layout/` package seam

The split turns one module into a package with a clean seam. The **variant
generator** and **scored solver** are new; everything else is the existing code
relocated behind stable names.

```
src/rule_engine/layout/
├── __init__.py         # re-exports layout(), DiagramSpec, PlacedDiagram — the
│                       #   public surface is UNCHANGED (callers keep importing
│                       #   `from rule_engine.layout_engine import layout`; the
│                       #   old module path becomes a shim that re-exports).
├── model.py            # DiagramSpec, EdgeSpec, NodeSpec, PlacedDiagram, Contact
├── place.py            # place_nodes, size_containers, centre_block_in_vpc
├── contacts.py         # select_contacts + the contact-ladder helpers
├── corridors.py        # CorridorAllocator (+ snapshot/restore, new)
├── routers.py          # the per-edge routers (route_cross_region, spine, …)
├── variants.py         # NEW: per-edge sanctioned-variant generator
├── solver.py           # NEW: scored per-edge loop (order, score, commit)
└── pipeline.py         # layout(): place→centre→(solver | legacy)→repair
```

**Behavior-preserving contract.** Steps 1–2 (the split) MUST NOT change any
output. The relocation is mechanical; `variants.py`/`solver.py` are added but
**not wired in** until step 3. A `--legacy` code path (the current
ten-pass `_place_and_route`) is retained behind the seam so the split can be
proven equivalent (byte-identical `.drawio`, all tests green) before the scored
solver becomes the default.

### Control flow of one edge in the solver

```
                       ┌──────────────────────────┐
  edge e (constrained) │  variants.generate(e)     │→ [(contacts, route)…]
                       └────────────┬─────────────┘
                                    ▼
                       ┌──────────────────────────┐
                       │ for v in variants:        │
                       │   snap = alloc.snapshot() │
                       │   route v (tentative)     │
                       │   c = route_cost(A ∪ {v}) │   A = accepted edges
                       │   alloc.restore(snap)     │
                       │   record (c, v)           │
                       └────────────┬─────────────┘
                                    ▼
                       argmin by (RouteCost.as_tuple(), variant_rank, v.id)
                                    ▼
                       commit winner (re-route for real, keep its lanes)
```

## Components and Interfaces

### Component 1: `CorridorAllocator` snapshot / restore (`corridors.py`)

- **Responsibility:** hand out distinct grid-aligned corridor lines (unchanged),
  and let the solver **try a variant then undo it** so a rejected variant consumes
  no lanes.
- **Inputs:** the existing `allocate` / `register_gap` calls; new `snapshot()` /
  `restore(token)`.
- **Outputs / Interface:**

```python
class CorridorAllocator:
    # existing:
    def allocate(self, gap_id: str, low: float, high: float) -> int: ...
    def register_gap(self, gap_id: str, low: float, high: float) -> int: ...
    def capacity(self, gap_id: str) -> int: ...

    # new (1.8.0):
    def snapshot(self) -> AllocatorState:
        """Return an opaque, deep-copied token of all lane occupancy
        (_spans, _free, _taken). O(state) copy; no aliasing with live state."""
    def restore(self, token: AllocatorState) -> None:
        """Reset occupancy to exactly the token. After restore, capacity() and
        every subsequent allocate() behave as if the calls made since the
        snapshot never happened."""
```

The token is an immutable deep copy of the three occupancy dicts. `restore` must
be **total**: it replaces live state wholesale, so a variant that widened a gap,
allocated three lanes, and raised `CorridorExhaustedError` mid-way still restores
cleanly.

### Component 2: Variant generator (`variants.py`)

- **Responsibility:** for one edge, enumerate the router's **sanctioned** shapes as
  `(contacts, route-plan)` pairs — the discrete choices the ten passes make
  implicitly today, made explicit and enumerable.
- **Inputs:** the edge, the placed nodes/containers, the edge's classification
  (`classify_edge`: `spine` / `cross-region` / `back-edge` / `fan-out` / …).
- **Outputs / Interface:**

```python
@dataclass(frozen=True)
class RouteVariant:
    id: str                      # stable, e.g. "e12/straight-drop"
    exit: Contact                # (exitX, exitY)
    entry: Contact               # (entryX, entryY)
    plan: RoutePlan              # how routers.py should lay the waypoints
    rank: int                    # deterministic preference for tie-breaks

def generate(edge: EdgeSpec, placed, containers, kind: str) -> list[RouteVariant]:
    """Return the sanctioned variants for `edge`, in rank order. Every variant
    is contract-legal by construction (exit right/bottom, enter left/top), so no
    variant can introduce an edge-direction finding. Never empty: the current
    rule-based choice is always included as one variant (so the solver can never
    do worse than today — Property 5)."""
```

The variant families come straight from the REVIEW.md worked design and the
existing passes:

| Family | Variants | Sourced from |
| --- | --- | --- |
| lane side | above-lane, below-lane | `decide_lane_sides`, pass 2b |
| back-edge shape | loop-above, descend-near | REVIEW.md experiment 2 |
| spine | straight-drop, side-corridor | pass 1c / `_box_directly_below` |
| corridor side | left-gap, right-gap | `_free_left_corridor_x`, pass 1d |

### Component 3: Scored solver (`solver.py`)

- **Responsibility:** order edges, score each edge's variants against accepted
  edges, commit the minimum, keep the allocator consistent.
- **Inputs:** placed diagram, per-edge variants, `route_cost`, the allocator.
- **Outputs / Interface:**

```python
def solve(placed, containers, spec, alloc) -> RoutedEdges:
    """Deterministic scored routing (design §Architecture).

    order = most_constrained_first(spec.edges, placed)   # fewest variants first,
                                                          # then longest span,
                                                          # then declared order
    accepted = []
    for e in order:
        best = None                       # (RouteCost, rank, variant, geom)
        for v in variants.generate(e, placed, containers, classify_edge(e)):
            snap = alloc.snapshot()
            geom = routers.lay(v, placed, containers, alloc)   # tentative
            cost = route_cost(geometry_of(accepted + [geom]))  # graded rails
            alloc.restore(snap)
            key = (cost.as_tuple(), v.rank, v.id)
            if best is None or key < best[0]:
                best = (key, v, geom)
        commit(best.v, alloc)             # re-lay for real; keep its lanes
        accepted.append(best.geom)
    return accepted
    """
```

- **most-constrained-first:** an edge with **fewer variants** is placed first
  (inflexible long-haul runs claim lanes before two-sided fan-outs), tie-broken by
  **longer Manhattan span**, then **declared order**. This ordering is itself a
  pure function of the spec, preserving determinism.
- **incremental scoring:** `route_cost` is recomputed over `accepted ∪ {candidate}`
  each trial. This is the honest objective (the same function the ratchet and
  `route_quality.py` use), so the solver and the gate cannot drift.

### Component 4: Graded rails in `route_cost` (`geometry.py`)

- **Responsibility:** turn the binary rail count into a graded penalty so two
  routes that both clear 40px are still ranked by how close they run.
- **Inputs / Outputs:** `route_cost(geo) -> RouteCost`, with `RouteCost` gaining a
  graded field while keeping `crossings` first in the comparison key.

```python
@dataclass(frozen=True)
class RouteCost:
    crossings: int = 0
    rails: int = 0                 # kept: count of runs within RAIL_CLEARANCE
    rail_penalty: float = 0.0      # NEW: Σ penalty(clearance) over rail runs
    turns: int = 0
    ink: float = 0.0
    crossing_pairs: tuple = ()
    rail_pairs: tuple = ()

    def as_tuple(self):
        # crossings ≫ rail_penalty ≫ turns ≫ ink. `rails` (the binary count)
        # stays reported for the ratchet's readability but the *ordering* key
        # uses the graded penalty so 2px << 10px << 30px << clears.
        return (self.crossings, round(self.rail_penalty, 3), self.turns, round(self.ink))
```

The penalty is **monotonically non-increasing in clearance** and reaches 0 at
`RAIL_CLEARANCE`: a candidate `penalty(d) = max(0, (RAIL_CLEARANCE - d) / RAIL_CLEARANCE)`
(clamped, so `d ≥ 40 → 0`, `d = 2 → 0.95`, `d = 20 → 0.5`). The exact shape is a
task detail; the **required property** is monotonicity (Property 6). Beyond
`RAIL_CLEARANCE` the penalty is 0 but the run may still be scored on turns/ink, so
a route that avoids a near-icon rail is preferred even when both technically clear.

### Component 5: `layout/` package + shim (`__init__.py`, `layout_engine.py`)

- **Responsibility:** relocate the module into a package without changing the
  public import surface.
- **Interface contract:** `from rule_engine.layout_engine import layout` and
  `from rule_engine.layout import layout` both continue to work; `layout(spec)`
  returns a `PlacedDiagram` identical to today's for every shipped spec **until**
  the scored solver is switched on.

## Data Models

### RouteVariant

| Field | Type | Constraint / Notes |
| --- | --- | --- |
| `id` | `str` | stable per edge, `"<edge-id>/<family>"`; used in tie-break |
| `exit` | `Contact` | `(exitX, exitY)`; contract-legal (right/bottom) by construction |
| `entry` | `Contact` | `(entryX, entryY)`; contract-legal (left/top) by construction |
| `plan` | `RoutePlan` | enum + params telling `routers.lay` how to place waypoints |
| `rank` | `int` | deterministic preference; lower = tried/preferred first |

### AllocatorState (snapshot token)

| Field | Type | Constraint / Notes |
| --- | --- | --- |
| `spans` | `dict[str, tuple[float,float]]` | deep copy of `_spans` |
| `free` | `dict[str, list[int]]` | deep copy of `_free` (order preserved) |
| `taken` | `dict[str, set[int]]` | deep copy of `_taken` |

Opaque to callers; only produced by `snapshot()` and consumed by `restore()`.

### RouteCost (extended)

| Field | Type | Constraint / Notes |
| --- | --- | --- |
| `crossings` | `int` | unchanged; first (heaviest) in `as_tuple` |
| `rails` | `int` | retained binary count, for ratchet readability |
| `rail_penalty` | `float` | **new**; Σ graded penalty, second in `as_tuple` |
| `turns` | `int` | unchanged |
| `ink` | `float` | unchanged |
| `rail_pairs` | `tuple[(eid,nid,span,clearance)]` | **clearance added** so `--detail` can show it |

## Design Decisions

### Decision D1: draw.io stays the only publishable source

Unchanged from the always-on standard. The scored router changes *how* waypoints
are chosen, never the artifact format. Every diagram remains a `.drawio` triple;
no lint rule is weakened.

### Decision D2: 1.8.0 scores routes only; placement is deferred (with the seam left in)

REVIEW.md records that the two remaining defects (tier-skip rail, GCP/OCI hub) are
**placement** problems and suggests scoring placement variants alongside routes.
We **defer placement scoring** to a later release, for three reasons:

1. **Blast radius.** Placement variants move nodes/tiers, which resizes containers
   and invalidates every already-scored route — the scoring loop stops being
   per-edge and becomes a joint placement+routing search. That is a much larger,
   higher-risk change than inverting the routing stage.
2. **The routing win is real and self-contained.** REVIEW.md's experiment 2
   (coupled edits) is a *routing* coupling the scored router dissolves on its own —
   the later edge picks the variant that avoids the earlier one's lane. Shipping
   that alone is valuable and independently verifiable.
3. **Honest gates.** The two placement defects are already *recorded and accepted*
   in the ratchet (`gcp/01` = `(4,0)`, landscapes = `(3,2)`). 1.8.0 must not
   regress them; it need not fix them.

**Seam left in:** the solver's `generate()` boundary is written so a future
`generate_placement_variants()` can be added without re-architecting — placement
becomes an outer loop over the same score-and-commit machinery. This is a
design note, not 1.8.0 code.

### Decision D3: the objective is the shared `route_cost` (no private copy)

The solver scores with `geometry.route_cost` — the exact function
`scripts/route_quality.py` and the ratchet use — so the thing being optimised is
the thing being gated. Adding the graded rail penalty there (not in a solver-local
copy) keeps them from drifting and makes the two invisible 1.7.0 improvements
register in the ratchet.

### Decision D4: determinism via explicit ordering and total tie-breaks

No randomness, no wall-clock, no dict-iteration order. Edge order is
most-constrained-first with total tie-breaks; variant choice is `argmin` over a
total key `(RouteCost.as_tuple(), rank, id)`. Same spec → same `.drawio`, which the
`generator --check` freshness gate depends on.

## Correctness Properties

*A property is a characteristic that holds across all valid executions — a
formal, machine-verifiable statement of what the system must do.*

**Property 1: the split is behavior-preserving**

For every shipped spec `s`, the `.drawio` produced by `layout(s)` after the
`layout/` split (scored solver **off**) is **byte-identical** to the `.drawio`
produced before the split.

**Validates: Requirements 1**

**Property 2: allocator snapshot/restore leaves no lane consumed by a rejected variant**

For any allocator state and any sequence of `allocate`/`register_gap` calls `C`,
`snapshot(); apply(C); restore(token)` yields an allocator whose `capacity(g)` and
subsequent `allocate(g,…)` results for every gap `g` are identical to those of the
allocator that never applied `C`.

**Validates: Requirements 3**

**Property 3: scored router is deterministic**

For every generated layout `L`, `solve(L)` called twice returns the identical
routed edge set (same contacts, same waypoints), and the serialized `.drawio` is
byte-identical.

**Validates: Requirements 3, and the determinism gate**

**Property 4: scored route_cost never exceeds the rule-based route_cost**

For every generated layout `L`, `route_cost(scored(L)).as_tuple() <=
route_cost(rule_based(L)).as_tuple()`. (Because the rule-based choice is always one
of the generated variants, the `argmin` can never do worse.)

**Validates: Requirements 3**

**Property 5: every variant is contract-legal**

For every edge and every variant `v` returned by `generate`, `v.exit` lies on the
right or bottom face and `v.entry` on the left or top face — so no variant can
introduce an `edge-direction` finding regardless of which the solver picks.

**Validates: Requirements 3, and "no lint rule weakened"**

**Property 6: graded rail penalty is monotonic in clearance**

For rail clearances `d1 <= d2`, `penalty(d1) >= penalty(d2)`, and `penalty(d) = 0`
for all `d >= RAIL_CLEARANCE`. Two otherwise-equal routes are ordered by how close
their rail runs are.

**Validates: Requirements 2**

**Property 7: the ratchet is not regressed (and is tightened)**

For every shipped diagram, scored routing yields `crossings <= ceiling` and
`rail_penalty <= recorded_ceiling`; the two 1.7.0 improvements invisible under the
binary count register as a strictly lower recorded penalty on their diagrams.

**Validates: Requirements 2, 3**

**Property 8: no shipped example loses a gate**

After the scored router is the default, every shipped example still passes
`rule-engine-lint --all`, `verify-icon --all --strict`, `check-rasters`, and the
golden-example tests.

**Validates: Requirements 1, 2, 3, and the honest-gates gates**

## Error Handling

- **`CorridorExhaustedError` inside a variant trial** — caught by the solver, that
  variant is scored as infeasible (drops out of the `argmin`), and `restore` runs
  in a `finally` so a partial allocation never leaks. If **every** variant of an
  edge is infeasible, the solver falls back to the retained rule-based route and
  hands the diagram to the existing widen/re-centre repair loop — the current
  behavior, so no diagram becomes unroutable.
- **Empty variant list** — a `generate` contract violation; raises rather than
  silently routing nothing (the rule-based variant is always present, so this is a
  programming error, not an input condition).
- **Ratchet regression** — a CI failure by design; the change is rejected until the
  route improves or the ceiling is deliberately re-baselined in the same commit.

## Testing Strategy

- **Property-based (Hypothesis, house style).** Properties 2–6 map to Hypothesis
  tests over generated layouts / allocator call sequences / clearances. Strategies
  generate small placed diagrams (node boxes on a grid, a handful of edges) and
  allocator gap/allocate sequences.
- **Golden / byte-identity.** Property 1 and Property 3 are golden tests:
  `generator --check` over the shipped corpus must stay green after the split, and
  again after the solver with the re-baselined ratchet.
- **Ratchet.** `tests/test_route_quality.py` gains a graded-penalty ceiling
  alongside the crossing/rail ceilings; the re-baseline is committed with the
  metric change (Property 7).
- **Gate suite.** `rule-engine-lint --all`, `verify-icon --all --strict`,
  `check-rasters`, golden-example tests run in CI on 3.11–3.14 (Property 8).

## Requirements Traceability

| Requirement (to be authored) | Design element |
| --- | --- |
| 1 — `layout/` split, behavior-preserving | Components 1, 5; Property 1; §Architecture seam |
| 2 — graded rails metric + re-baseline | Component 4; Properties 6, 7; §Data Models RouteCost |
| 3 — scored router | Components 2, 3; Properties 2–5, 7, 8; §control flow |
| Cross-cutting — determinism / gates / version | Decisions D1, D3, D4; Properties 3, 8 |

## Packaging / Version Notes (implemented as tasks, not now)

- This is release **1.8.0**: bump the version triple, add a CHANGELOG entry
  describing the `layout/` split, the graded rails metric + re-baseline, and the
  scored router, and refresh pack pins only if a build touches them. The actual
  bump is a task in `tasks.md`, sequenced last.
- Python **3.11+**; CI matrix 3.11–3.14 (unchanged).
