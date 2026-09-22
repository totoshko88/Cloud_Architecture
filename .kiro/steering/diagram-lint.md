---
inclusion: always
---

# Diagram Lint Ruleset

This file is the **authoritative lint ruleset** for the Rule Engine. The Linter
reads this file to evaluate every diagram and every Markdown document, assigning
each finding a severity of **CRITICAL**, **ERROR**, or **WARNING** (Requirement 7
AC1). It is always on: every agent turn within this workspace inherits these rules
(Requirement 11 AC1).

The Linter is the single quality gate before publication. Given the same inputs,
any conforming agent must produce artifacts that this ruleset evaluates as eligible
for publication.

## Severity Scale

- **CRITICAL** — a safety or data-integrity failure. Blocks publication. Must never
  ship.
- **ERROR** — a standards violation that blocks publication until corrected.
- **WARNING** — a quality concern that is reported but does **not**, on its own,
  block publication.

## Lint Rules

Each rule below has a stable rule name, the condition that triggers a finding, and
the severity the Linter assigns when the condition holds. The Linter evaluates
every applicable rule against every artifact.

| Rule | Condition | Severity | Source |
| --- | --- | --- | --- |
| `node-count` | A diagram contains more than 12 nodes. | ERROR | R7 AC4 / R1 AC4 |
| `edge-label` | A diagram edge has no non-empty label. | WARNING | R7 AC5 / R1 AC7 |
| `node-quote` | A node name contains a space or any character outside `[A-Za-z0-9_-]` and is not enclosed in double quotes. | ERROR | R7 AC6 / R1 AC6 |
| `legend-present` | A diagram has no Legend. | ERROR | R7 AC7 / R5 AC11 |
| `companion-doc` | A `.drawio` file has no matching `.diagram.md` Companion Document. | ERROR | R7 AC8 / R1 AC10 |
| `frontmatter` | A Markdown document is missing a required Frontmatter key or has a required Frontmatter key with an empty value. | CRITICAL | R7 AC9 / R8 |
| `icon-resolved` | A diagram icon is an unresolved placeholder rather than a resolved provider icon. | ERROR | R7 AC10 / R2 AC8 |
| `secret-safety` | A Snapshot file contains a secret value, key material, or a SecureString value. | CRITICAL | R7 AC11 / R3 AC8 |
| `title-versioned` | A diagram title cell has no version identifier or no date. | WARNING | R7 AC12 / R5 AC9 |
| `mermaid-type` | Mermaid is used for a diagram type other than sequence, flow, or state. | WARNING | R7 AC13 / R1 AC2 |
| `flow-legend` | A diagram uses numeric flow markers on edges but has no `Flow` legend cell covering every marker. | WARNING | diagram-standards Numbered Flow Legend |
| `edge-routing` | A diagram edge is not orthogonally routed, crosses a node icon, shares a corridor with a parallel edge, overlaps a label/legend, or two edges leave/enter one node side on the same contact point. | WARNING | diagram-standards Edge Routing |
| `container-padding` | A container border sits flush against or straddles a child node (no grid-step padding). | WARNING | diagram-standards Container Padding |
| `min-font-size` | A diagram carries on-diagram text below the 12px minimum font size. | WARNING | diagram-standards Accessibility & Contrast |
| `grid-alignment` | A diagram node's absolute x or y is not a whole multiple of the grid step (default 10). | WARNING | diagram-standards Layout Geometry |
| `node-overlap` | Two diagram node icon boxes overlap (intersecting rectangles). | WARNING | diagram-standards Layout Geometry |
| `arrow-style` | A diagram edge uses a filled/heavy arrowhead (or an unspecified head that defaults to filled), or a stroke width below 1pt. | WARNING | diagram-standards Accessibility & Contrast |

### Rule Detail

- **`node-count` (ERROR)** — Count the nodes in the diagram. If the count exceeds
  12, report an ERROR. Diagrams over the limit must be split so that each holds at
  most 12 nodes, with an index document referencing each split. The 12-node cap
  also applies to cross-cloud composition diagrams.
- **`edge-label` (WARNING)** — Every edge must carry a non-empty, descriptive text
  label. An edge with a missing or empty label produces a WARNING.
- **`node-quote` (ERROR)** — The allowed unquoted character set for a node name is
  `[A-Za-z0-9_-]`. A node name containing a space or any character outside that set
  must be enclosed in double quotes; an unquoted special-character node name is an
  ERROR.
- **`legend-present` (ERROR)** — Every diagram must include a Legend defining the
  standard line styles, colors, and change markers. A diagram with no Legend is an
  ERROR.
- **`companion-doc` (ERROR)** — Each `NN-topic.drawio` source must ship with its
  matching `NN-topic.diagram.md` Companion Document. A `.drawio` with no matching
  `.diagram.md` is an ERROR.
- **`frontmatter` (CRITICAL)** — Every Markdown document must begin with complete
  YAML Frontmatter. A missing required key, or a required key present with an empty
  value, is a CRITICAL finding.
- **`icon-resolved` (ERROR)** — Every diagram icon must be a resolved provider icon,
  not an unresolved placeholder. A placeholder icon is an ERROR.
- **`secret-safety` (CRITICAL)** — Snapshot files record non-secret metadata only.
  A Snapshot file that contains a secret value, key material, or a SecureString
  value is a CRITICAL finding.
- **`title-versioned` (WARNING)** — Every title cell must encode both a version
  identifier (`vN`) and an ISO 8601 date (`YYYY-MM-DD`). A title cell missing the
  version identifier or the date is a WARNING.
- **`mermaid-type` (WARNING)** — Mermaid is permitted only for sequence, flow, or
  state diagrams (and only for the render targets allowed by the diagram standards).
  Using Mermaid for any other diagram type is a WARNING.
- **`flow-legend` (WARNING)** — When a diagram labels its edges with numeric flow
  markers (`1`, `2`, `3`, …), it must include a `Flow` legend cell (first line
  exactly `Flow`) placed to the right of the diagram, with one `N. <description>`
  line per marker in ascending order. A diagram that uses numeric markers but omits
  the `Flow` legend, or whose `Flow` legend does not cover every marker, produces a
  WARNING. Diagrams that use descriptive prose labels instead of numeric markers are
  unaffected.
- **`edge-routing` (WARNING)** — *Geometry-enforced from the parsed `.drawio` model.* The check is conservative to avoid false positives on validly routed diagrams: it flags a **non-orthogonal** edge, and a **waypoint-free** edge whose straight run between its real contact points passes through an unrelated node. An edge carrying explicit `<mxPoint>` waypoints is treated as deliberately routed (draw.io routes orthogonally around nodes). Beyond the enforced core, edges should be orthogonally routed
  (`edgeStyle=orthogonalEdgeStyle` for `.drawio`), must not cross through a node icon,
  and must enter a node on its left/top and exit on its right/bottom. When one node
  side carries more than one edge, each edge uses a distinct contact point
  (`exitX/exitY`, `entryX/entryY`) so edges fan out rather than stack. Two edges must
  not share the same horizontal or vertical corridor: parallel runs are offset by at
  least one grid step (model `gridSize`, default `10`) using explicit waypoints, and an
  edge must not overlap an unrelated node, an edge label, or the right-side Flow/Legend
  blocks. When one node fans out to several targets on the same side, prefer a shared
  trunk just outside the node with branches leaving it in opposite directions over
  several near-parallel detours, and start arrow stubs just past the source perimeter
  (`exitPerimeter=0`) so they do not bite into the glyph. A violation of any of these is a
  WARNING.
- **`container-padding` (WARNING)** — *Geometry-enforced from the parsed `.drawio` model* (a node's absolute box is measured against each container box). A Boundary or Network Boundary container must keep
  at least one grid step of padding between its border and every child node, and between
  a nested container and its parent. A node placed flush against or straddling a
  container border is a WARNING.
- **`min-font-size` (WARNING)** — Every piece of on-diagram text (node labels, edge
  labels, boundary captions, title cell, and the `Flow`/`Legend` cells) must render at
  **12px or larger**, the accessibility floor from published AWS diagram conventions. A
  diagram whose parsed `fontSize=<n>` tokens include any value below 12 produces a
  WARNING. When no font sizes are parsed (e.g. a programmatic artifact), the rule is
  skipped rather than assumed to pass.
- **`grid-alignment` (WARNING)** — *Geometry-enforced.* Every diagram node's absolute
  x and y origin must be a whole multiple of the model grid step (draw.io `gridSize`,
  default 10) so nodes share one rhythm. A node off the grid produces a WARNING. When no
  geometry is parsed (a programmatic artifact), the rule is skipped.
- **`node-overlap` (WARNING)** — *Geometry-enforced.* No two node icon boxes may overlap.
  Overlapping rectangles (icons drawn on top of each other) produce a WARNING. Boundary
  containers are excluded (nodes are expected to sit inside them).
- **`arrow-style` (WARNING)** — *Geometry-enforced.* Prefer an **open** arrowhead
  (`endArrow=open;endFill=0`) over a heavy filled head, and keep stroke width at ≥ 1pt.
  An edge with a filled head (`block`/`classic`/`diamond`/`oval`, fill on), an unspecified
  head (which defaults to filled `classic`), or a sub-1pt `strokeWidth` produces a WARNING.

## Publication Eligibility

The Linter reports publication eligibility for each evaluated artifact using this
rule:

- An artifact is **eligible for publication** if and only if it has **zero CRITICAL
  findings and zero ERROR findings** (Requirement 7 AC2). WARNING findings do not
  block publication.
- An artifact with **at least one CRITICAL finding or at least one ERROR finding**
  is **blocked from publication** (Requirement 7 AC3).

Interface shape:

```
lint(artifact) -> {
  findings: [ { rule, severity } ],
  eligible_for_publication: bool   # true iff zero CRITICAL and zero ERROR findings
}
```

## Ruleset-Unavailable Behavior

This file is the authoritative ruleset. If this file (`diagram-lint.md`) is
**missing or cannot be read**, the Linter SHALL:

1. Return a **`ruleset-unavailable`** error, and
2. Report **every** evaluated diagram and document as **blocked from publication**
   (Requirement 7 AC14).

No artifact is ever eligible for publication while the ruleset is unavailable.
