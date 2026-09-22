---
inclusion: always
---

# Diagram Standards

These rules govern every architecture diagram the Diagram Generator produces, across
all five provider profiles (`aws`, `azure`, `gcp`, `oci`, `generic`). They are always
on: every agent turn inherits them. Given the same inputs, any conforming agent must
produce a diagram that passes the lint ruleset in `diagram-lint.md`.

## Source Format: PlantUML vs Mermaid Decision Matrix

Choose the diagram source deterministically from the diagram type and render target.

| Diagram type | Render target | Source |
| --- | --- | --- |
| C4 / architecture / component / deployment | any | **PlantUML** |
| sequence / flow / state | GitLab Markdown or Backstage TechDocs | Mermaid permitted |
| sequence / flow / state | any other target | **PlantUML** |

Rules:

- A C4, architecture, component, or deployment diagram is always authored in PlantUML,
  regardless of render target.
- A sequence, flow, or state diagram may be authored in Mermaid **only** when the render
  target is GitLab Markdown or Backstage TechDocs.
- A sequence, flow, or state diagram whose render target is neither GitLab Markdown nor
  Backstage TechDocs must be authored in PlantUML.
- Using Mermaid for any diagram type other than sequence, flow, or state is a lint
  WARNING (`mermaid-type`).

## PlantUML Syntax Constraints

- Every PlantUML diagram uses exactly one `@startuml` and exactly one `@enduml`, and all
  syntax lives inside that single pair.
- Exclude every preprocessor directive (no `!include`, `!define`, `!ifdef`, `%…`, or any
  other preprocessor construct).

## Lane Order

Arrange diagram lanes left to right in this fixed order:

1. actors
2. edge
3. router
4. asynchronous messaging
5. workers
6. platform core
7. data
8. on-premises

`actors → edge → router → async messaging → workers → platform core → data → on-premises`

## Node Limit and Split Rule

- Limit each diagram to a maximum of **12 nodes**. More than 12 nodes is a lint ERROR
  (`node-count`).
- When a system contains more than 12 nodes, split it into multiple diagrams so that each
  diagram holds at most 12 nodes, and produce one index document that references every
  split diagram.
- A cross-cloud composition diagram is also capped at 12 nodes.

## Node Quoting Rule

- Enclose a node name in double quotes whenever it contains a space character or any
  character outside the set of ASCII letters, ASCII digits, hyphen (`-`), and underscore
  (`_`). Allowed unquoted set: `[A-Za-z0-9_-]`.
- A special-character node name that is not quoted is a lint ERROR (`node-quote`).

## Mandatory Edge Labels

- Attach a non-empty, descriptive text label to **every** edge.
- An edge with no non-empty label is a lint WARNING (`edge-label`).
- **Numbered flow markers**: prefer a short **numeric marker** (`1`, `2`, `3`, …) as the
  on-edge label instead of a long prose sentence. The prose description of each step is
  moved to a dedicated **numbered Flow legend** placed to the right of the diagram (see
  "Numbered Flow Legend" below). This keeps edges readable and avoids labels overlapping
  nodes. A numeric marker `N` is a valid, non-empty edge label and satisfies `edge-label`.
- Numeric markers on edges within one diagram are unique and ordered along the primary
  data flow, starting at `1`.

## Numbered Flow Legend

When a diagram uses numbered flow markers, it includes a **Flow** legend cell placed to
the **right** of the diagram body (adjacent to, and separate from, the standard Legend
block). The Flow legend:

- Has a value whose first line is exactly `Flow`.
- Lists one line per marker in the form `N. <description of the step>`, in ascending
  numeric order, covering every numeric marker used on an edge.
- Is a text cell (`style` contains `text;`), so the Linter does not count it as a node.

The standard Legend block additionally documents the marker convention with the line
`Numbered markers (1..N) = ordered data flow steps; see Flow list`.

## Edge Routing

Route edges so that no edge crosses through a node icon and no two edges overlap where it
can be avoided. Use orthogonal routing (`edgeStyle=orthogonalEdgeStyle`) for `.drawio`
sources. Fix connection points explicitly with `exitX/exitY` and `entryX/entryY` rather
than relying on floating connections.

Directional convention (matches the lane order and provider reference diagrams):

- **Entry** into a node is on its **left** (`entryX=0`) or **top** (`entryY=0`).
- **Exit** from a node is on its **right** (`exitX=1`) or **bottom** (`exitY=1`).
- **Distinct contact points per edge**: when a single node has **more than one** edge on
  the same side, give each edge a different contact point along that side (for example
  `exitY=0.25`, `exitY=0.5`, `exitY=0.75`) so the edges fan out instead of stacking on one
  point. The same rule applies to multiple entries into one node.
- **Separated parallel runs (grid-step spacing)**: two edges must never share the same
  horizontal or vertical corridor. When parallel orthogonal segments would otherwise
  overlap, offset each run by at least **one grid step** (the model `gridSize`, default
  `10`) so the lines step apart with a visible gap. Give such edges explicit routing
  waypoints (`<mxPoint>` entries inside `<Array as="points">`) on distinct grid columns
  or rows; do not rely on the auto-router to separate them. Adjacent parallel runs should
  differ by a whole multiple of the grid step (`10`, `20`, …), never by a fraction.
- **No edge–node crossings**: an edge must not pass through any node it does not connect.
  Route the edge around intervening nodes using waypoints, or move the node out of the
  corridor. A line that visually overlaps an unrelated node icon is a defect.
- **No edge–label / edge–legend crossings**: keep every edge clear of the right-side
  `Flow` and `Legend` cells; reserve the right margin for those blocks and route edges
  within the diagram body.
- **Shared trunk, opposite branches (fan-out from one node)**: when a single source
  fans out to several targets stacked on the same side (for example a worker that writes
  to a store above it *and* a store below it), route the edges into **one shared vertical
  (or horizontal) trunk** just outside the source, then branch off it in **opposite
  directions** — one run goes up to the upper targets, the other goes down to the lower
  targets. Because the two branches leave the trunk in opposite directions they never
  overlap, the total ink and corner count stay low, and the picture reads as a clean tree
  rather than a bundle of near-parallel lines. Place the trunk one clear grid column (or
  row) beyond the source's edge, and keep any genuinely parallel branch on its own
  grid-step-separated corridor as above. Prefer this trunk-and-branch shape over giving
  every fan-out edge its own long detour corridor.
- **Clean arrow start (exit slightly past the perimeter)**: so an arrow does not visually
  bite into the source glyph, start it just outside the icon border. Set the exit point a
  hair beyond the perimeter (for example `exitX=1.02` with `exitPerimeter=0`, or the
  matching `exitY`) rather than exactly on it. This keeps the stub clear of the icon while
  the arrowhead still lands cleanly on the target's entry point.

A node should not sit directly between two other nodes on a straight horizontal or
vertical line that an edge must traverse; stagger nodes across lanes (vary the row) so
edges route around icons rather than through them.

## Container Padding

A Boundary or Network Boundary container must leave a margin of at least **one grid step
on every side** between the container edge and the nodes inside it, and between a nested
container (for example a Network Boundary inside a Boundary) and its parent. Do not place
a node flush against, or straddling, a container border. Size containers so their
children plus this padding fit without the border clipping a node or its label.

## Raster Alt Text

- Whenever a diagram includes a raster image, provide non-empty alt text describing the
  raster image content.

## The Mandatory Artifact Triple

For each `.drawio` diagram named `NN-topic.drawio`, always produce the full triple:

- `NN-topic.drawio` — the draw.io source
- `NN-topic.drawio.png` — the exported raster image
- `NN-topic.diagram.md` — the Companion Document

A `.drawio` file with no matching `.diagram.md` Companion Document is a lint ERROR
(`companion-doc`).

If any required output file for a diagram cannot be produced, return a generation error
that identifies the diagram and the missing output file, and exclude the partial diagram
from publication.

## Title Cell Format

Every diagram title cell encodes exactly:

```
<provider> <workload> — <boundary id> / <region> | <date> | vN
```

where:

- `<date>` is an ISO 8601 calendar date in `YYYY-MM-DD` form.
- `vN` is the letter `v` followed by a positive integer (for example `v1`, `v2`).

A title cell missing the version identifier or the date is a lint WARNING
(`title-versioned`). Express every Change Marker description using an ISO 8601 date
(`YYYY-MM-DD`); exclude all relative time expressions (no "yesterday", "last week", etc.).

## Mandatory Legend Block

Every diagram includes a Legend that defines all of the following:

- **solid line** = primary flow
- **dashed line** = asynchronous or event-driven flow
- **red** = blocked or missing or disabled
- **🆕** = new in version N
- **🔄** = changed in version N
- **dashed green boundary** = the stack boundary
- **dashed blue boundary** = the Network Boundary

A diagram with no Legend is a lint ERROR (`legend-present`). Example PlantUML legend:

```plantuml
legend right
  Solid line = primary flow
  Dashed line = asynchronous / event-driven flow
  Red = blocked / missing / disabled
  🆕 = new in version N
  🔄 = changed in version N
  Dashed green boundary = stack boundary
  Dashed blue boundary = Network Boundary
endlegend
```

## Multi-cloud Composition

- Where an architecture spans more than one provider, represent each provider using the
  icon and color conventions of its Provider Profile.
- A cross-cloud diagram is limited to a maximum of 12 nodes.
- Produce a **C4 container diagram** for a cross-cloud composition that names each
  provider and labels every cross-provider edge with the data flow it represents.
- Render every Boundary and Network Boundary of each provider using the container group
  style of the corresponding Provider Profile.
- If a referenced Provider Profile declares no container group style for its Boundary or
  Network Boundary, return a profile-convention error identifying the affected provider
  and boundary, and exclude the incomplete diagram from publication.

## Quick Checklist

- [ ] Source format matches the PlantUML/Mermaid decision matrix
- [ ] Single `@startuml`/`@enduml` pair, no preprocessor directives (PlantUML)
- [ ] Lanes ordered actors → edge → router → async messaging → workers → platform core → data → on-premises
- [ ] ≤ 12 nodes (else split + index document)
- [ ] Special-character node names double-quoted
- [ ] Every edge carries a non-empty label (numeric marker `N` counts)
- [ ] Numbered flow markers used; prose moved to a right-side `Flow` legend
- [ ] Orthogonal edge routing; no edge crosses an icon; entries left/top, exits right/bottom
- [ ] Multiple edges on one node side use distinct contact points (fan out)
- [ ] Parallel runs separated by ≥ 1 grid step via explicit waypoints (no shared corridor)
- [ ] Fan-out from one node uses a shared trunk with branches in opposite directions
- [ ] Arrow stubs start just past the source perimeter (exitPerimeter=0), not into the glyph
- [ ] No edge overlaps an unrelated node, a label, or the right-side Flow/Legend blocks
- [ ] Containers pad ≥ 1 grid step around child nodes and nested containers
- [ ] Raster images carry non-empty alt text
- [ ] Triple present: `.drawio` + `.drawio.png` + `.diagram.md`
- [ ] Title cell: `<provider> <workload> — <boundary id> / <region> | <date> | vN`
- [ ] Legend block present with all line styles, colors, and change markers
- [ ] Cross-cloud: C4 container, per-profile icons/boundaries, ≤ 12 nodes, labeled edges
