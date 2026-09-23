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

## Verification

The linter enforces the geometry rules (`grid-alignment`, `node-overlap`,
`container-padding`, `container-overlap`, `edge-routing`, `edge-direction`, `edge-float`,
`corridor-sharing`, `text-padding`) from the parsed `.drawio`; the raster gate enforces the
export budget; `rule-engine-verify-icon` confirms every icon reference resolves. From-scratch
regeneration of every example, followed by the full gate, is the acceptance check that the
steering is unambiguous — the generator reproduces clean diagrams with no hand edits.
