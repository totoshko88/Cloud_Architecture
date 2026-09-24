# Diagram design notes — rationale for the routing & icon rules

This document records the *why* behind the diagram-generation rules that are enforced by
the steering docs (`.kiro/steering/diagram-standards.md`, `diagram-lint.md`,
`asset-packs.md`) and the shared builder (`src/rule_engine/diagram_layout.py`,
`scripts/ha_multiregion_common.py`). The rules themselves are authoritative in steering;
this file explains the reasoning, distilled from building and hand-reviewing the
HA multi-region `landscape` as-built across all four clouds.

## Two diagram scales, one contract

A summary and an as-built answer different questions and cannot share one node cap:

- a **`flow`** summary keeps the 12-node ERROR cap and numbered flow markers — it is the
  "shape" of the system a reviewer reads first;
- a **`landscape`** as-built relaxes the node cap (WARNING > 30, ERROR > 50) because its
  value is completeness on one canvas. Readability is instead held by *other* rules that
  tighten: container padding becomes an ERROR, and the geometry rules (grid, overlap,
  routing, direction) do the work the cap used to.

The pair is a checked contract (`summary_of` / `detailed_view`, the `orphan-landscape`
rule), so a large system always ships as one summary + one as-built, cross-linked.

## Icon fidelity is a data problem, not a per-diagram edit

A node's icon is only as correct as the **role** it maps to. Distinct services get distinct
roles (`cdn` ≠ object store, `dns` ≠ load balancer, `waf` ≠ secrets store). Roles resolve to
official vendor glyphs through a committed index (`mappings/icon-index.json`) built at
install time from the official packs by `rule-engine-build-icon-sets`. This makes a wrong or
renamed icon a re-index, not a code edit, and lets CI verify wiring without the packs
present. GCP follows Google's own docs taxonomy (product-first, category-fallback — Cloud
CDN has no product glyph, so it uses the Networking category icon). OCI embeds official
stencils. The draw.io-internal `aws4`/`azure2` names are validated against extracted
allow-lists (`aws4-icons.json`, `azure2-shapes.json`) so a well-formed-but-nonexistent id
(which renders as an empty/broken box) is caught, not shipped.

## Edge routing — the readability rules and their reasons

These were distilled from a reviewer moving the lines by hand until the diagram read
without effort. Each is now a rule.

- **Directional contract.** Exit right/bottom, enter left/top. One rule that removes most
  crossings, because every edge then reads along the left-to-right, top-to-bottom flow.
- **Pin every contact point (no floats).** A floated endpoint lets draw.io's perimeter
  router pick a side and drift; a hand-drag can even detach an arrowhead onto empty canvas.
  Both are defects the eye catches immediately.
- **Step sideways before turning (stair).** A right-angle bend glued to the glyph reads as
  a kink; stepping one gap-column off the node first, then turning, reads as a clean stair.
  Symmetric for up-turns: step out, then rise.
- **Spine via a side corridor, not down the node column.** A vertical dropped straight
  through a column collides with the icons and labels stacked there. Route it in the empty
  gap beside the column instead.
- **Fan-out: turn up in the gap before each target; one lane per edge.** When one node
  fans out along a row, dropping all the verticals beside the source stacks them into one
  merged line and forces long horizontals. Turning up in the gap just before each target
  spreads the verticals across the row and keeps each horizontal short.
- **Distinct exit points (thirds).** Two edges leaving one side must be ≥ a third apart
  (0.25 / 0.5 / 0.75); a third edge moves to another face (e.g. the bottom). Adjacent
  fractions (0.5 and 0.6) read as one doubled line at the glyph.
- **A tier-skip takes the one crossing-free corridor.** When a long edge would cross a
  tier's fan-out lanes, route it down the corridor on the side the fan-out does *not*
  occupy — choosing the crossing-free lane beats a "prettier" central drop that cuts every
  fan-out line.
- **One edge per corridor; shared trunk exempt.** Two unrelated long edges on the same grid
  line merge into one; offset them. Edges from the same source (or to the same target) may
  share a stub before branching — that is a trunk, not a merge.
- **Turn near the source.** A back-edge or cross-region run turns one column beyond its
  source, not at the far canvas edge — the latter is the longest, most border-crossing line
  on the canvas.

## Layout & furniture

- **Label-aware geometry.** A node's footprint is the icon *plus* its caption band; padding
  and overlap are measured against the footprint, not the bare icon, so a label that crowds
  a border or the next row is caught.
- **Size parents from the deepest child's footprint.** A container's bottom/right clears its
  deepest child by ≥ 1 grid step; grow the parent rather than shrink a child until its label
  touches the border. No flush borders.
- **Text boxes.** Flow and Legend share one width sized tight to the longest line (no wrap),
  each height fit to its own content, with uniform inner padding — so the pair reads as one
  aligned block and no text abuts a border.
- **Class-aware raster budget.** A `flow` raster stays ≤ 1600px; a `landscape` exports wide
  (≤ 3600px) so a 30-plus-node as-built stays legible instead of being shrunk illegibly.

## The layout is generated, not hand-authored

Every rule above describes how a *good* diagram is shaped. For a long time the HA
multi-region pair encoded that shape as **hand-authored coordinate tables** — every node
`(x, y)` and every edge waypoint was a literal integer a human placed and tuned by eye in
`scripts/ha_multiregion_common.py`. That worked, but it meant each readability fix was
another round of manual waypoint tuning: exactly the over-engineering the routing rules
exist to prevent. The declarative **layout engine** (`src/rule_engine/layout_engine.py`)
replaces those tables. The two HA diagrams are now **declarations** with no coordinates in
them at all (`src/rule_engine/ha_multiregion_spec.py`: `SUMMARY_SPEC`, `LANDSCAPE_SPEC`);
the engine derives the geometry.

The declaration is deliberately small. A node is a role + lane + region + slot; an edge is
a source + target + marker; a container is a kind + region + parent. There is no field in
which a coordinate *could* be written — coordinates are the engine's output, never its
input. The four provider skins keep supplying only icons and labels, so the geometry is now
identical across AWS, Azure, GCP, and OCI; only the glyphs differ.

### The placement model — lane grid, not a coordinate table

Placement is coordinate-free by construction. A node's **lane** (one of the eight canonical
tiers) picks its position on the *primary* axis, and its **slot** picks its position on the
*secondary* axis — rows-down-columns-across for a north-south landscape, columns-across-
rows-down for a left-right flow. Origins are computed from the canonical `diagram_layout`
constants (`COL_STEP`, `ROW_STEP`, `ICON_SIZE`, `GRID`), so every origin lands on the grid
by construction and the two regions come out mirror-symmetric. Containers are then sized
**bottom-up** around their children's footprints plus `CONTAINER_PAD`, peer bands are
equalised to a common width, and each region's block is re-centred inside its VPC — the same
"size a parent from its deepest child" and "equal-width bands" rules above, now executed
rather than typed. Which node belongs to which AZ is **declared** on the node
(`NodeSpec.container`), not inferred.

### The routing model — the prose rules, made executable

The contact-point ladder, corridor allocation, and per-class routing are the executable form
of the edge-routing prose above. `select_contacts` / `spread_contacts` apply the exit/entry
priority ladder and the distinct-same-side-exit rule (and raise on an over-connected fourth
edge, rather than emitting a merged line). A `CorridorAllocator` hands out one grid-step
corridor line per gap and widens the gap when it runs out, so parallel runs never merge.
`classify_edge` sorts each edge into one of `straight` / `spine` / `fan-out-row` /
`cross-region` / `back-edge`, and the matching `route_*` function emits corridor-aligned
waypoints with the stair step and the clockwise obstacle detour — reusing the same
`geometry.segment_crosses_box` predicate the linter uses, so "the edge crosses no icon" is
tested with the same code that would later flag it. An edge that classifies as none *raises*
(fail-honest), the same philosophy as an unresolved icon: no guessed route ever ships.

### The engine produces a candidate and asks the validators

The engine does **not** re-implement the constraints. It produces a candidate layout, then
`_run_oracle` serialises it (via `build_diagram` + `build_geometry`) and runs the existing
geometry `check_*` set — the very validators the linter uses — as the acceptance oracle.
Where a validator reports a fixable finding, a small named repair adjusts the candidate
(`corridor-sharing` → next lane; `container-padding` → grow the box; off-centre →
re-centre) and the loop re-validates; an over-connected node is unfixable and raises. The
loop is bounded and deterministic, so the same declaration yields byte-identical geometry
every time. This is the key design choice: the routing rules live in one place — the
validators — and the engine is their inverse, not a second copy of them.

### Two lessons the migration surfaced

Building the engine against the reference exposed two placement defects worth recording,
because both are non-obvious and both are now encoded:

- **Region B must offset along the *secondary* axis by a content-derived step.** A fixed
  region step cannot clear a region whose block spans several lanes on the secondary axis —
  the passive band collided with the active one. The offset is computed from region A's
  actual extent (`_region_secondary_offset`) and grid-aligned, so the two bands always sit
  disjoint regardless of how many nodes a lane holds.
- **AZ membership must be *declared*, not guessed from tier geometry.** Inferring which AZ a
  node belongs to from its tier produced overlapping AZ boxes when two tiers shared a band.
  Membership is now an explicit `NodeSpec.container`, with a geometric fallback only when a
  node declares none.

## Verification

The linter enforces the geometry rules (`grid-alignment`, `node-overlap`,
`container-padding`, `container-overlap`, `edge-routing`, `edge-direction`, `edge-float`,
`corridor-sharing`, `text-padding`) from the parsed `.drawio`; the raster gate enforces the
export budget; `rule-engine-verify-icon` confirms every icon reference resolves. From-scratch
regeneration of every example, followed by the full gate, is the acceptance check that the
steering is unambiguous — the generator reproduces clean diagrams with no hand edits.
