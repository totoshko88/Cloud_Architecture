# Design — Placement Scoring & the Remaining Gates (release 1.9.0)

## Overview

Release 1.8.0 closed the largest engineering Open gap in `docs/REVIEW.md` — it
inverted routing into a scored per-edge solver (finding **C5**) and made the
rails metric graded (finding **D14**). It deliberately scored **routes only**,
holding the recorded placement defects unchanged (`gcp/01` = `(4,0)`, the
landscapes = `(3,2)`) and leaving a documented seam for placement scoring
(`variants._placement_seam_note`, *Decision D2*).

Release 1.9.0 closes the **four remaining Open gaps** recorded in
`docs/REVIEW.md`, as four independently reviewable pieces:

1. **Scored placement loop (Part A).** Layer a placement variant loop *over* the
   1.8.0 order-score-commit machinery: enumerate a small, sanctioned set of
   node/tier moves, score each finished candidate diagram with the shared
   `route_cost`, and keep the minimum. This is the design-noted next step from
   1.8.0 and the only thing that can retire the three held placement defects,
   because each is a placement problem surfacing as a routing defect.
2. **Inventory → diagram reconciliation gate (Part B).** A new gate that compares
   a Snapshot against the diagram generated from it and fails when a role-bearing,
   enumerated resource is silently absent from the diagram — the "ten KMS keys
   omitted while the companion asserted completeness" defect.
3. **Container dead-space lint (Part C).** A new advisory lint rule that flags a
   Boundary container sized far larger than its children (the opposite of the
   existing `container-padding` minimum-clearance check), with the threshold
   calibrated across the corpus first so no shipped diagram false-positives.
4. **Icon-index slug-collision disambiguation (Part D).** The icon-set builder
   currently keeps last-writer-wins and emits a WARNING when two distinct vendor
   icons normalise to one slug; 1.9.0 disambiguates deterministically so the
   collision resolves rather than merely reports.

Every part respects the honest-gates contract now in force: **determinism**
(same inputs → byte-identical `.drawio`), **no weakened lint rule**, **draw.io as
the only publishable source** (D1), and a **tightened — never regressed —
route-quality ratchet**. The parts are independent and can land and review in any
order; only Part A depends on 1.8.0 machinery.

### Non-goals

- **No new provider** and no change to the nine neutral resource types or the
  presentation roles — Parts B/C/D read the existing role vocabulary.
- **No re-architecture of the 1.8.0 solver.** Part A is an *outer loop* over the
  existing `solver.solve` / `variants.generate`; the per-edge scoring path is
  unchanged.
- **The version bump to 1.9.0** (CHANGELOG, version triple, pack pins,
  `plugin.json` / `bootstrap.sh`) is a task in `tasks.md`, not spec-creation work.

## Architecture

### Part A — the placement outer loop

1.8.0 scores routes for a *fixed* placement:

```
DiagramSpec → place → size → centre → [ solver.solve: per-edge score+commit ] → repair → PlacedDiagram
```

1.9.0 wraps this in a placement loop that reuses the whole 1.8.0 stage as its
inner "score one placement" step:

```
DiagramSpec
   │
   ▼
generate_placement_variants(spec)            # a small, ranked, deterministic set
   │   each variant = the base placement with ONE sanctioned move applied
   ▼
for each placement variant P (most-constrained-first over placements):
   │
   ├─ place(P) → size → centre → solver.solve → repair → finished candidate
   ├─ score the FINISHED candidate with the shared route_cost
   └─ keep the argmin over (RouteCost.as_tuple(), placement_rank, placement_id)
   │
   ▼
best finished PlacedDiagram → build_diagram → .drawio
```

The base placement (no move) is **always** variant rank 0, so the loop's argmin
can never do worse than 1.8.0 — exactly the guarantee 1.8.0's rule-based route
gives at the edge level, lifted to placement (the Part A analogue of Property 4).

**Sanctioned placement moves (the only ones enumerated), each keyed off a
recorded defect:**

- **widen-gap** — grow a Network-Boundary's side gap by whole `COL_STEP`
  multiples so a tier-skip corridor clears an icon column by ≥ `RAIL_CLEARANCE`
  (the *tier-skip rail*).
- **shift-neighbour** — move one hub neighbour one column so the hub's free
  approach column no longer lies inside its own fan-out (the *GCP/OCI hub*).
- **reorder-tier** — swap two peers within a row so two opposed long runs leaving
  the top row no longer overlap in extent (the *edge-tier band*).

Every move is a whole-grid translation of a node/tier and is re-fed through the
same `place → size → centre` so the result stays grid-aligned and lint-clean by
construction. A move that would break a container's nesting or padding is not
enumerated.

### Part B — the reconciliation gate

A new `rule-engine-reconcile` gate (and CI step) reads a Snapshot folder and its
generated diagram triple, maps each **role-resolvable** enumerated resource to
the role it would draw as, and asserts the diagram contains a node for it:

```
inventory-<...>/*.json  ──▶ raw-provider-JSON → role mapper ──▶ expected role set
examples/.../NN-*.drawio ──▶ parsed node role set (via the icon-index roles layer)
                                   │
                                   ▼
             every expected role-bearing resource has a node  ? OK : BLOCK (names the omission)
```

The mapper is the new subsystem the gap calls for: it reads native provider
responses (the Snapshot records raw JSON) and resolves them to the neutral
types + presentation roles already declared in `mappings/roles.yaml`. Scope is
governed by the diagram class: a `landscape` requires **total** coverage
(every role-bearing resource is a node); a `simple`/`summary` `flow` requires
only that no resource *in the flow it claims to show* is silently dropped.

### Part C — the dead-space lint rule

A new advisory `container-dead-space` rule (WARNING on both classes) measures the
ratio of a Boundary container's area to the summed footprint of its direct
children plus mandated padding, and flags a container above a calibrated
threshold. It is the mirror of `container-padding` (which checks the *minimum*
clearance). The threshold is **measured across the shipped corpus first** and set
above the sparsest legitimate tier, so no Shipped_Diagram false-positives.

### Part D — deterministic slug disambiguation

`build_icon_index` currently resolves a slug collision by last-writer-wins + a
WARNING. 1.9.0 replaces this with a **total, deterministic disambiguation order**
(the same ranking philosophy the 1.6.1 icon-index determinism fix used: prefer
SVG over PNG, base over Dark/Light variant, then size, then a path tie-break),
so two distinct vendor icons that normalise to one slug resolve to a stable,
documented winner and the loser is recorded under a disambiguated slug rather
than shadowed. The committed `mappings/icon-index.json` becomes a pure function
of the pack contents with no collision left to a WARNING.

## Components and Interfaces

### Component A1: `variants.generate_placement_variants(spec)`

Returns a rank-ordered, deterministic list of `PlacementVariant` descriptors,
rank 0 being the identity (no move). Pure function of the spec; enumerates only
the three sanctioned moves above, each guarded so it is emitted only where its
target defect can occur.

### Component A2: `solver.solve_placement(spec)`

The outer order-score-commit loop. For each placement variant it runs the full
1.8.0 inner pipeline to a finished candidate, scores it with `route_cost`, and
returns the argmin under `(RouteCost.as_tuple(), placement_rank, placement_id)`.
Deterministic; the base placement is always a candidate.

### Component B1: the raw-JSON → role mapper (`reconcile.role_of`)

Reads a Snapshot's per-domain JSON and resolves each resource to a role via the
existing `mappings/roles.yaml` vocabulary. No provider state is read — it is a
pure function of the committed Snapshot files.

### Component B2: `rule-engine-reconcile` CLI + CI step

Compares the mapped role set against the diagram's node role set and blocks on a
silent omission, naming the offending resource(s).

### Component C1: `geometry.check_container_dead_space` + `container-dead-space` rule

Geometry-enforced from the parsed `.drawio`; advisory WARNING.

### Component D1: `asset_index` disambiguation

A total ordering over colliding candidates; the index records the disambiguated
winner and loser deterministically.

## Data Models

- **PlacementVariant** — `(id, move, rank)` where `move` is one of `widen-gap` /
  `shift-neighbour` / `reorder-tier` (or the identity), `id` is
  `"<spec>/<move>/<target>"`, and `rank` is a deterministic preference (0 =
  identity).
- **ReconcileReport** — `{expected_roles, drawn_roles, omissions[]}`; eligible
  when `omissions` is empty for the diagram's coverage class.
- No change to `RouteCost`, the Snapshot schema, or `mappings/roles.yaml`.

## Design Decisions

- **D1 (carried): draw.io is the only publishable source.** Unchanged.
- **D2 (now built): placement scoring.** 1.8.0 deferred it; Part A builds it as
  an outer loop, not a solver rewrite, so the 1.8.0 route-scoring path is
  untouched and its properties still hold.
- **D3 (carried): one shared `route_cost`.** Part A scores placements with the
  same objective the router and ratchet use — no private copy.
- **D4 (carried): determinism.** Every part is a pure, deterministic function of
  its inputs; no randomness, wall-clock, or dict-iteration-order dependence, so
  every Shipped_Diagram stays byte-identical run-to-run and `generator --check`
  holds.
- **D5 (new): reconciliation reads the Snapshot, never the provider.** Part B is
  strictly offline — it maps committed Snapshot JSON, honouring the read-only
  inventory contract.

## Correctness Properties

Property 1: Placement argmin never worse than the base. For every spec,
`route_cost(solve_placement(spec)) <= route_cost(base placement)` — the base is
always a candidate (the Part A analogue of 1.8.0 Property 4).
**Validates: Requirements 1.4**

Property 2: Placement determinism. `solve_placement(spec)` run twice yields a
byte-identical `.drawio`.
**Validates: Requirements 1.5, 5.1**

Property 3: Held defects improve or hold. After Part A the recorded landscape /
`gcp/01` defects are ≤ their 1.8.0 ceilings; the ratchet is re-baselined tighter
where a move improves them, never regressed.
**Validates: Requirements 1.7, 5.4**

Property 4: Reconciliation catches an omission. A Snapshot with a role-bearing
resource absent from its `landscape` diagram is blocked, naming the resource; a
complete diagram passes.
**Validates: Requirements 2.3, 2.5**

Property 5: Dead-space rule has no corpus false-positive. Every Shipped_Diagram
is clean under `container-dead-space` at the calibrated threshold.
**Validates: Requirements 3.3**

Property 6: Slug disambiguation is a pure function of the pack.
`build_icon_index` resolves every collision to a stable winner; re-running on the
same packs yields a byte-identical `mappings/icon-index.json` with no collision
WARNING.
**Validates: Requirements 4.4, 4.5**

Property 7: No gate weakened, no example regressed. The full Gate_Suite stays
green on every Shipped_Diagram, and no lint rule in `diagram-lint.md` is weakened.
**Validates: Requirements 5.2, 5.5**

## Error Handling

- **Placement loop.** A PlacementVariant whose inner pipeline raises
  (`LayoutError` / `OverConnectedError`) is scored infeasible and dropped from the
  argmin; the base placement always survives, so `solve_placement` never fails a
  spec the 1.8.0 path could lay out. A move that breaks container nesting/padding
  is not enumerated in the first place.
- **Reconciliation gate.** A Snapshot file that does not parse, or a diagram that
  does not parse, is reported as a gate error (not a silent pass); a resource with
  no resolvable role is skipped, not treated as an omission.
- **Dead-space rule.** Advisory only — it never blocks; a container with no
  children is skipped rather than divided by zero.
- **Slug disambiguation.** A collision with no total-order winner (identical
  candidates) is impossible by construction (the path tie-break is total); the
  builder records the deterministic winner and never raises.

## Testing Strategy

Each part ships its own property tests alongside example tests, mirroring the
1.8.0 layout (`tests/test_*_properties.py`, Hypothesis profile in
`tests/conftest.py`, `max_examples >= 100`):

- **Part A** — Properties 1–3 as Hypothesis properties over generated small specs
  plus the shipped corpus; determinism proven by a twice-run byte comparison.
- **Part B** — Property 4 as example tests over a crafted Snapshot/diagram pair
  (one omission, one complete) plus the shipped corpus.
- **Part C** — Property 5 parametrised over the shipped corpus at the calibrated
  threshold; a synthetic over-sized container proves the rule fires.
- **Part D** — Property 6 by rebuilding the index twice and comparing bytes.
- **Cross-cutting** — the full Gate_Suite (now including `rule-engine-reconcile`)
  and the re-baselined ratchet run in CI on Python 3.11–3.14.

## Sequencing & scope

The four parts are independent; a natural order is **A → B → C → D**, with the
version bump and CHANGELOG last. Part A carries the release theme; B/C/D each
close one recorded Open gap. `requirements.md` (authored next) derives the
acceptance criteria from these components and properties; `tasks.md` follows.
