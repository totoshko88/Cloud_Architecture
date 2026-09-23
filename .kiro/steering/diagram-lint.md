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
| `node-count` | Too many nodes for the diagram class: `flow` &gt; 12 (ERROR); `landscape` &gt; 30 (WARNING), &gt; 50 (ERROR). | ERROR/WARNING | R7 AC4 / R1 AC4 / diagram-standards Diagram Class |
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
| `container-padding` | A container border sits flush against or straddles a child node (no grid-step padding). Raised to ERROR for `landscape`. | WARNING/ERROR | diagram-standards Container Padding |
| `min-font-size` | A diagram carries on-diagram text below the 12px minimum font size. | WARNING | diagram-standards Accessibility & Contrast |
| `grid-alignment` | A diagram node's absolute x or y is not a whole multiple of the grid step (default 10). | WARNING | diagram-standards Layout Geometry |
| `node-overlap` | Two diagram node icon boxes overlap (intersecting rectangles). | WARNING | diagram-standards Layout Geometry |
| `arrow-style` | A diagram edge uses a filled/heavy arrowhead (or an unspecified head that defaults to filled), or a stroke width below 1pt. | WARNING | diagram-standards Accessibility & Contrast |
| `orphan-landscape` | A `landscape`-class diagram declares no valid `summary_of` cross-link to a `flow` summary. | ERROR | diagram-standards Diagram Class |
| `overlay-legend-coverage` | A diagram carries an overlay marker (findings/state vocabulary) that the Legend does not document. | WARNING | diagram-standards Overlay Vocabulary |
| `container-overlap` | Two sibling (non-nested) Boundary/Network-Boundary containers overlap. Raised to ERROR for `landscape`. | WARNING/ERROR | diagram-standards Container Nesting |
| `edge-direction` | An edge with explicit contact points does not exit its source right/bottom and enter its target left/top. Raised to ERROR for `landscape`. | WARNING/ERROR | diagram-standards Edge Routing (directional contract) |
| `text-padding` | A filled+stroked text/legend/note box does not set uniform inner padding (`spacing{Left,Right,Top,Bottom}`). | WARNING | diagram-standards Text-box Padding |
| `corridor-sharing` | Two unrelated long edges run in the same straight horizontal/vertical corridor (same grid line, overlapping extent). | WARNING | diagram-standards Edge Routing (one edge per corridor) |
| `edge-float` | An edge declares no explicit exit/entry contact point (floats its connection to the perimeter router). Raised to ERROR for `landscape`. | WARNING/ERROR | diagram-standards Edge Routing (no-float on landscape) |

### Rule Detail

- **`node-count` (ERROR/WARNING)** — Count the nodes in the diagram; the
  threshold and severity depend on the diagram **class** (see *Diagram Class*
  below). For a **`flow`** diagram (the default): more than 12 nodes is an ERROR
  — split it so each holds at most 12 nodes, with an index document referencing
  each split. The 12-node cap also applies to cross-cloud composition diagrams.
  For a **`landscape`** diagram (as-built / inventory): the cap is relaxed —
  more than 30 nodes is a WARNING and more than 50 nodes is an ERROR — because a
  landscape's job is completeness on one canvas, and readability is instead held
  by the raised container-padding rule, the geometry rules, and the mandatory
  summary cross-link.
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
  container border is a WARNING. **Class-aware:** for a `landscape` diagram this is
  raised to an **ERROR**, because nested labelled containers are the primary
  device that keeps a large as-built legible, so a padding defect must block
  publication rather than merely warn.

- **`orphan-landscape` (ERROR)** — A `landscape`-class diagram must declare a
  `summary_of` cross-link (in its companion `.diagram.md` frontmatter) naming
  the sibling `flow` summary that overviews the same system. A landscape with an
  absent or empty `summary_of` is an ERROR. This encodes the "summary + detailed"
  pair as a checked contract: the ≤12-node `flow` summary carries the shape of
  the system, the `landscape` carries the full as-built, and neither ships
  orphaned. `flow` diagrams are unaffected.

- **`overlay-legend-coverage` (WARNING)** — A diagram may carry an optional,
  double-encoded **overlay vocabulary** (shape + color + label) for findings and
  state — for example "spec-required-not-deployed" (red dashed box),
  "observability-overlay" (blue stroke), or change markers. When an overlay
  marker is used, the Legend must document it; an overlay marker not covered by
  the Legend is a WARNING. Diagrams that carry no overlay markers are
  unaffected.
- **`container-overlap` (WARNING/ERROR)** — *Geometry-enforced from the parsed
  `.drawio` model.* Two boundary containers may **nest** (Account ⊃ Region ⊃
  Availability Zone) but two **sibling** boundaries — neither containing the
  other — must not overlap. Overlapping peer boundaries put shared canvas area
  under two labelled groups at once, so a node in that area is ambiguous about
  which boundary owns it (the primary-VPC box bleeding into the passive-VPC box
  is the canonical defect). WARNING for `flow`; **ERROR for `landscape`**, where
  the nested boundary hierarchy is the primary device that keeps a large
  as-built legible.
- **`edge-direction` (WARNING/ERROR)** — *Geometry-enforced.* The **directional
  contract**: every edge that declares explicit contact points must **exit** its
  source on the **right or bottom** (`exitX >= 0.5`, admitting the right edge and
  the top-right / bottom-right corners, or `exitY == 1`) and **enter** its target
  on the **left or top** (`entryX <= 0.5` or `entryY == 0`). A left-edge exit
  (`0, 0.5`) or a right-edge entry (`1, 0.5`) is the defect. This single rule
  removes most crossings on a dense diagram. Edges that float their connection
  (no explicit contact point) are left to the perimeter router and not judged.
  WARNING for `flow`; **ERROR for `landscape`**.
- **Label-aware geometry (applies to `container-padding` and `node-overlap`).**
  A node's footprint is not its 78×78 icon box alone — the service name renders
  in a caption band **below** the icon (`verticalLabelPosition=bottom`), and that
  band collides with the next row and the container border exactly as the icon
  does. Both `container-padding` and `node-overlap` therefore measure the
  **footprint** (icon box grown downward by one label line, ~30px = three grid
  steps), not the bare icon. A label that reaches a boundary border or the icon
  of the row below is a finding even when the icons themselves clear each other.
- **`text-padding` (WARNING)** — Every text/legend/note box with a **visible box**
  (a concrete `fillColor=#…` and `strokeColor=#…`) must set uniform inner padding
  on all four sides (`spacingLeft/Right/Top/Bottom`, one grid step = 10px) so no
  line of text abuts the border. A borderless cell — the diagram title or a free
  label that sets no concrete fill+stroke — has no box to pad and is exempt. The
  shared builder's `_TEXT_STYLE` carries this padding, so every generated diagram
  passes; a hand-authored box that drops the tokens trips the rule.
- **`corridor-sharing` (WARNING)** — *Geometry-enforced.* Two **unrelated** long
  edges must not run in the same straight corridor: a pair whose dominant
  horizontal (or vertical) segment lies on the **same grid line** with overlapping
  extent is flagged, because the two lines merge into one and cannot be told apart.
  A **shared trunk is exempt** (diagram-standards "shared trunk, opposite
  branches"): two edges that leave the *same source* or reach the *same target*
  may share their stub before branching. Only long runs (> two grid steps) count;
  short adjacent stubs are ignored.
- **`edge-float` (WARNING/ERROR)** — *Geometry-enforced.* Every edge must fix its
  contact points (`exitX/exitY` + `entryX/entryY`) so the directional contract is
  checkable and the perimeter router cannot drift a side. An edge that sets
  **neither** an exit nor an entry point floats its connection. WARNING for `flow`;
  **ERROR for `landscape`**, where a dense diagram must pin every contact side.
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

## Diagram Class (flow vs landscape)

Every diagram has a **class** that selects which node-count and container rules
apply. The class is declared in the companion `.diagram.md` frontmatter key
`diagram_class` and defaults to `flow` when absent, so every pre-1.3.0 artifact
keeps its exact behavior.

| Rule | `flow` (default) | `landscape` (as-built / inventory) |
| --- | --- | --- |
| `node-count` | ERROR at &gt; 12 | WARNING at &gt; 30, ERROR at &gt; 50 |
| `container-padding` | WARNING | **ERROR** (containers are load-bearing) |
| `container-overlap` | WARNING | **ERROR** (sibling boundaries must not overlap) |
| `edge-direction` | WARNING | **ERROR** (directional contract is strict) |
| `edge-float` | WARNING | **ERROR** (every edge must pin its contact points) |
| `orphan-landscape` | n/a | ERROR unless `summary_of` names a `flow` summary |
| numbered flow markers | expected | optional (a landscape has no single path) |
| `overlay-legend-coverage` | WARNING when overlay markers are used | WARNING when overlay markers are used |
| raster budget (export guidance) | ≤ 1200px / < 500KB | ≤ 3600px / < 2MB (a wide as-built stays legible) |

Rules:

- A **`flow`** diagram is a narrative / data-flow view. It keeps the 12-node cap
  and the numbered-flow-marker convention. This is the default and the only
  class a diagram has unless its companion declares otherwise.
- A **`landscape`** diagram is a system-of-record / as-built inventory view. Its
  value is completeness on one canvas, so the node cap is relaxed (WARNING &gt; 30,
  ERROR &gt; 50) while other rules tighten: containers become mandatory and their
  padding is an ERROR, and the diagram must cross-link to a `flow` summary.
- **Sanctioned pair.** A `landscape` declares `summary_of: <flow-diagram>` and
  the paired `flow` summary may declare `detailed_view: <landscape-diagram>`.
  The pair is one publishable unit: the ≤12-node summary carries the shape, the
  landscape carries the full as-built. A `landscape` with no `summary_of` is an
  `orphan-landscape` ERROR.
- **Overlay vocabulary (optional, both classes).** A diagram may double-encode
  findings/state as shape + color + label (e.g. red dashed box =
  "spec-required-not-deployed", blue stroke = "observability-overlay", change
  markers 🆕/🔄). When used, every overlay term must be documented in the Legend
  (`overlay-legend-coverage`).

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
