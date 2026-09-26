---

## inclusion: always

# Diagram Standards

These rules govern every architecture diagram the Diagram Generator produces, across all five provider profiles (`aws`, `azure`, `gcp`, `oci`, `generic`). They are always on: every agent turn inherits them. Given the same inputs, any conforming agent must produce a diagram that passes the lint ruleset in `diagram-lint.md`.

## Source Format: PlantUML vs Mermaid Decision Matrix

Choose the diagram source deterministically from the diagram type and render target.

| Diagram type | Render target | Source |
| --- | --- | --- |
| C4 / architecture / component / deployment | any | **PlantUML** |
| sequence / flow / state | GitLab Markdown or Backstage TechDocs | Mermaid permitted |
| sequence / flow / state | any other target | **PlantUML** |

Rules:

- A C4, architecture, component, or deployment diagram is always authored in PlantUML, regardless of render target.
- A sequence, flow, or state diagram may be authored in Mermaid **only** when the render target is GitLab Markdown or Backstage TechDocs.
- A sequence, flow, or state diagram whose render target is neither GitLab Markdown nor Backstage TechDocs must be authored in PlantUML.
- Using Mermaid for any diagram type other than sequence, flow, or state is a lint WARNING (`mermaid-type`).

## Diagram Orientation (axis by diagram type)

Choose the primary layout axis deterministically from the diagram type, so the same system always lays out the same way and matches the convention cloud reviewers expect (`awslabs/diagram-as-code`, AWS reference architectures).

| Diagram type | Primary axis | Convention |
| --- | --- | --- |
| infrastructure / network / deployment | **top → bottom (North–South)** | external/users/internet at the **top** (North), internal resources and administrators at the **bottom** (South); use the horizontal (East–West) direction for redundancy / availability zones |
| flow / application / data-flow / sequence | **left → right (West–East)** | the ordered lanes below read left to right along the primary data flow |
| C4 / component | left → right | container/component boxes read left to right; nest per C4 level |

Rules:

- An **infrastructure, network, or deployment** diagram is laid out **North–South**: the outermost/most-external actor (internet, user, ingress) sits at the top and traffic descends into progressively more internal tiers, with redundant peers (AZ-a / AZ-b) placed side by side on the same row.
- A **flow, application, data-flow, or sequence** diagram is laid out **left → right** following the lane order below.
- The chosen axis is fixed for the whole diagram — do not mix a North–South infra layout with a left→right flow layout in one diagram; split them instead (each still capped at 12 nodes).
- Orientation is **authoring guidance**, not a lint rule: the linter cannot infer a node's external-vs-internal role from geometry alone, so it does not attempt to enforce the axis. Pick the axis from the diagram type above and keep it consistent.

## PlantUML Syntax Constraints

- Every PlantUML diagram uses exactly one `@startuml` and exactly one `@enduml`, and all syntax lives inside that single pair.
- Exclude every preprocessor directive (no `!include`, `!define`, `!ifdef`, `%…`, or any other preprocessor construct).

## Lane Order

Arrange diagram lanes in this fixed order. For a **left → right** (flow/application) diagram the lanes read left to right; for a **North–South** (infrastructure/deployment) diagram the same order reads **top → bottom** (actors/edge at the top, data/on-premises at the bottom). The sequence is identical either way — only the axis changes, per **Diagram Orientation** above:

1. actors
2. edge
3. router
4. asynchronous messaging
5. workers
6. platform core
7. data
8. on-premises

`actors → edge → router → async messaging → workers → platform core → data → on-premises`

(read this sequence left→right for a flow diagram, or top→bottom for a North–South infrastructure diagram).

## Node Limit and Split Rule

- Limit each diagram to a maximum of **12 nodes**. More than 12 nodes is a lint ERROR (`node-count`).
- When a system contains more than 12 nodes, split it into multiple diagrams so that each diagram holds at most 12 nodes, and produce one index document that references every split diagram.
- A cross-cloud composition diagram is also capped at 12 nodes.

## Diagram Class (flow vs landscape)

Every diagram declares a **class** in its companion `.diagram.md` frontmatter
via `diagram_class`, defaulting to `flow`. The class chooses the node-count and
container rules the Linter applies (see `diagram-lint.md` → *Diagram Class*).

- **`flow`** (default) — a narrative / data-flow view answering "how does a
  request move end-to-end?". Keeps the 12-node cap and the numbered-flow-marker
  convention. Use for summaries, request flows, and any diagram a reader follows
  along a single ordered path.
- **`landscape`** — an as-built / inventory view answering "what is actually
  deployed, and how does it all relate at once?". The node cap is relaxed
  (WARNING &gt; 30, ERROR &gt; 50); in exchange, **nested labelled containers are
  mandatory** (Account → Region → VPC → tier), their padding is an **ERROR** not
  a WARNING, and the diagram **must cross-link to a `flow` summary** of the same
  system via `summary_of`.

**The sanctioned pair.** A large system is documented as one `flow` summary
(≤ 12 nodes, the shape) plus one `landscape` as-built (the full inventory),
cross-linked:

- the `landscape` companion frontmatter sets `summary_of: <NN-topic-summary>`;
- the `flow` summary companion frontmatter may set `detailed_view: <NN-topic-landscape>`.

The reviewer reads the summary to get the shape, then drills into the landscape
to reason about specifics. Do **not** split a comprehensive as-built into
several 12-node pages — that destroys the one thing it exists to show (how
everything relates at once). Author it as a single `landscape` instead.

## Choosing the diagram type after inventory (simple / summary / landscape)

After an inventory run, **offer the user a choice of diagram type before
generating** — do not silently pick one. There are three user-facing types; the
first two are the `flow` lint class and the third is the `landscape` class, so
the choice maps onto the two classes above:

| User choice | Lint class | When to offer it | Node budget |
| --- | --- | --- | --- |
| **simple** | `flow` | A single focused view of one workload / request path. The everyday default when the inventory is small or the user wants one clear picture. | ≤ 12 |
| **summary** | `flow` | The ≤12-node *shape* of a large system, paired with a landscape. Sets `detailed_view:` to its landscape; the landscape sets `summary_of:` back. | ≤ 12 |
| **landscape** | `landscape` | The full as-built / inventory view — everything that was enumerated, on one canvas. Required when the inventory is large or the user asks "show everything". Cross-links a `summary` via `summary_of`. | > 12 (WARNING > 30, ERROR > 50) |

Rules:

- **Always present the three options** once inventory is collected, with a short
  recommendation: **simple** for a small account or a single-flow question;
  **summary + landscape** (the sanctioned pair) for a large account, so the
  reader gets both the shape and the full detail.
- **simple** and **summary** are both authored as `diagram_class: flow`; they
  differ only in intent and cross-linking (a `summary` names its `detailed_view`;
  a standalone `simple` names neither). **landscape** is `diagram_class:
  landscape` and MUST cross-link a `flow` summary via `summary_of`
  (`orphan-landscape` ERROR otherwise).
- When the user picks **landscape** for a large system, produce the **pair**: one
  `summary` (≤ 12 nodes, the shape) and one `landscape` (the full as-built),
  cross-linked. Do not split a landscape into several 12-node pages.
- Whichever type is chosen, **every enumerated resource that has a role must
  appear** on the landscape (or on the simple/summary when it is in scope) — see
  *Inventory completeness → diagram* below.

## Inventory completeness → diagram (draw what was enumerated)

When a diagram is generated **from an inventory snapshot**, it MUST represent
every enumerated resource that resolves to a diagram role
(`mappings/roles.yaml` — the nine neutral types plus the presentation roles
`cdn`, `dns`, `waf`, `lb`, `cache`, `compute_instance`, `file_system`).

- On a **landscape** (the as-built), coverage is **total**: every enumerated,
  role-resolvable resource is a node. Omitting one is a completeness defect — the
  EFS filesystem that existed in `eu-central-1` but was left off the diagram is
  the canonical failure this rule prevents.
- On a **simple** / **summary** (`flow`, ≤ 12 nodes), coverage is **scoped**: the
  diagram shows the workload or flow in question, so it need not carry every
  resource — but it MUST NOT silently drop a resource that is part of the flow it
  claims to show. If the in-scope resource set exceeds 12 nodes, that is the
  signal to offer a `landscape` (or split), not to quietly omit resources.
- A resource is **only** legitimately absent when it has no role at all. In that
  case add a role to `roles.yaml` and re-run `rule-engine-build-icon-sets` — do
  **not** drop the resource and do **not** substitute a look-alike icon (see
  *Icon Fidelity — one role per distinct service*). A storage service is a
  concrete example: an `object_store` (bucket) and a `file_system` (EFS / Files /
  Filestore / OCI File Storage) are **distinct** roles with distinct icons; a
  file system is never folded into the bucket node.
- Before publishing an inventory-driven diagram, reconcile the node set against
  the snapshot's per-domain JSON (`storage.json`, `compute.json`, …): every
  role-resolvable resource in the snapshot is either drawn or, for a
  simple/summary, consciously out of scope. An unexplained gap is a defect.

**Drawing a resource is not the same as relating it.** Completeness gets the node
onto the canvas; it does not make the diagram an *architecture*. A node with **no
incident edge** tells the reader nothing about how it participates, and when most
of the nodes float, the picture has become an inventory listing with icons. Every
role-bearing node must therefore be either **connected** — at least one edge, in
or out — or **explicitly marked** with an overlay term that declares why it is
not (in practice `standby`, for a symmetric passive peer whose edges mirror the
active side). This is the `node-connectivity` lint rule (WARNING on both classes).
It is a WARNING rather than an ERROR because "connected enough" is a judgement the
author makes: an edge-less node is always worth a second look, but only the author
knows whether the missing relationship is real or out of scope.

## Overlay Vocabulary (findings / state)

A diagram may carry an **optional** second layer of meaning — findings and
state — encoded **redundantly** as shape *and* color *and* label so it survives
grayscale printing and color-blindness. When any overlay marker is used, every
overlay term must be documented in the Legend (`overlay-legend-coverage`
WARNING). The canonical vocabulary:

| Meaning | Shape | Color | Label token |
| --- | --- | --- | --- |
| Spec requires, not deployed | dashed rectangle overlay | red `#D64550` | `spec-required-not-deployed` |
| Observability overlay | stroked box | blue `#0062AD` | `observability-overlay` |
| Passive peer, edges omitted | dashed node outline | — (never repaint a pack glyph) | `standby` |
| New in version N | badge on node | — | 🆕 |
| Changed in version N | badge on node | — | 🔄 |

Overlay markers are additive: they annotate existing nodes/edges, never replace
the node's own icon or the standard Legend/Flow blocks.

**Machine-readable form.** A marked cell carries `overlay=<term>` in its style —
the token the linter reads for `overlay-legend-coverage` (is the term documented?)
and for `node-connectivity` (is this node's edge-lessness *declared*?). The token
is not the marker: the three human channels (shape, color, label) still apply, so
the marker survives grayscale printing and colour-vision deficiency.

**`standby` (v1.6.0).** An active-passive architecture draws every passive peer,
but drawing its full edge set duplicates the active region's topology and doubles
the ink for no new information. A peer marked `standby` states "mirrors the active
one; edges omitted for clarity", which is the sanctioned alternative to real edges
under `node-connectivity`. Its three channels are a **dashed node outline**, a
**`-standby` label suffix** (kept inside the `node-quote` safe set
`[A-Za-z0-9_-]`, so no label needs quoting), and a **Legend entry**. It
deliberately declares **no colour**: *Icon Fidelity* forbids recolouring a pack
glyph, so the marker is additive only. Use it for a genuine symmetric mirror — a
passive region, a standby AZ — never to excuse a node the author simply forgot to
connect.

## Node Quoting Rule

- Enclose a node name in double quotes whenever it contains a space character or any character outside the set of ASCII letters, ASCII digits, hyphen (`-`), and underscore (`_`). Allowed unquoted set: `[A-Za-z0-9_-]`.
- A special-character node name that is not quoted is a lint ERROR (`node-quote`).

## Mandatory Edge Labels

- Attach a non-empty, descriptive text label to **every** edge.
- An edge with no non-empty label is a lint WARNING (`edge-label`).
- **Numbered flow markers**: prefer a short **numeric marker** (`1`, `2`, `3`, …) as the on-edge label instead of a long prose sentence. The prose description of each step is moved to a dedicated **numbered Flow legend** placed to the right of the diagram (see "Numbered Flow Legend" below). This keeps edges readable and avoids labels overlapping nodes. A numeric marker `N` is a valid, non-empty edge label and satisfies `edge-label`.
- Numeric markers on edges within one diagram are unique and ordered along the primary data flow, starting at `1`.

## Numbered Flow Legend

When a diagram uses numbered flow markers, it includes a **Flow** legend cell placed to the **right** of the diagram body (adjacent to, and separate from, the standard Legend block). The Flow legend:

- Has a value whose first line is exactly `Flow`.
- Lists one line per marker in the form `N. <description of the step>`, in ascending numeric order, covering every numeric marker used on an edge.
- Is a text cell (`style` contains `text;`), so the Linter does not count it as a node.

The standard Legend block additionally documents the marker convention with the line `Numbered markers (1..N) = ordered data flow steps; see Flow list`.

**Flow and Legend share one width. No-wrap is the default; a narrow pin is the sanctioned exception.** The two right-margin cells (`Flow` and `Legend`) always use the **same width**, so the pair reads as one aligned block with a consistent left/right silhouette (widths equal; heights may differ per content). The width is chosen one of two ways, and only these two:

- **Default — size to content, no wrapping.** The shared width is the **longest line across both** boxes, so every line fits on one line. `build_diagram` computes this automatically when no width is pinned: one `box_w` from the longest Flow/Legend line, applied to both, with each height sized from its own line count plus the uniform inner padding.
- **Exception — pin narrower and let it wrap taller.** When the no-wrap width would push the block past the page or back into the diagram body (a wide as-built, where the longest legend line is wider than the right margin can hold), pin a narrower `legend_w`. The text then **wraps and the box grows taller**, which is correct: a narrow-and-tall Flow/Legend never collides with a node or a container border, whereas a wide one does. `build_diagram`'s height calculation is wrap-aware, so the pinned box is still sized to its real (wrapped) line count. The four shipped HA landscapes take this path at `legend_w=280`.

So wrapping is **not** a defect in itself — wrapping *at the default width* is, because it means the width was hand-set too small for no reason. Reserve enough right-margin page width for `legend_x + box_w` either way, and never let the Legend box overlap the Flow box above it: `build_diagram` pushes the Legend down to clear the Flow box by one grid step, since a long Flow list (or a pinned narrow width) can grow past a caller's requested `legend_y_legend`.

## Edge Routing

Route edges so that no edge crosses through a node icon and no two edges overlap where it can be avoided. Use orthogonal routing (`edgeStyle=orthogonalEdgeStyle`) for `.drawio` sources. Fix connection points explicitly with `exitX/exitY` and `entryX/entryY` rather than relying on floating connections.

**Every leg is explicitly axis-aligned — never leave a corner to draw.io.** An `orthogonalEdgeStyle` edge never draws a diagonal. When two consecutive points of a route are not axis-aligned, draw.io **inserts its own corner and chooses which way it turns** — so an unaligned waypoint is not a diagonal on screen, it is a corner the author did not specify. Its two possible shapes (horizontal-first or vertical-first) can differ by a whole icon: one clears a glyph and the other cuts straight through it. That is how an edge ends up grazing an icon or sliding along a container border while every waypoint in the source looked deliberate, and it is invisible to every other geometry rule, all of which read the points as given.

So the source must fully determine the drawn path. Three concrete requirements, enforced by the `edge-approach` lint rule:

- **Every leg is H or V.** For each consecutive pair in `[exit contact] + waypoints + [entry contact]`, either the x or the y is equal. Insert the corner yourself instead of implying it.
- **The first leg meets the exit face head-on.** A right/left face is left by a **horizontal** leg, a top/bottom face by a **vertical** one. (A corner contact lies on two faces and accepts either.)
- **The last leg meets the entry face head-on**, arriving from an approach lane one grid step outside the face. A horizontal leg running *along* a node's top border into a top-centre entry is the defect: the arrowhead slides across the glyph's edge rather than dropping into it. Turn one step above the node and drop in.

A fourth, related rule: **collapse an overshoot.** A run that passes the contact and comes back along the same axis (`… → (1290, 410) → entry at (1290, 380)`) is one run to 380, not two. The extra point adds nothing and makes the route read as a stutter.

**Contacts are grid-resolved along the face they sit on.** A fraction such as `exitY=0.25` on a 78px icon resolves to `y0 + 19.5` — half a pixel off the 10-grid every waypoint snaps to — which leaves a permanent kink that reads as a bent arrowhead. Nudge the *fraction* until the absolute contact lands on the grid, but snap **only the along-face coordinate**: for a right face only the y, for a top face only the x. Snapping the face coordinate would pull the contact *inside* the glyph whenever the icon is not grid-commensurate (a 64px icon at `x=540` has its right edge at 604; rounding to 600 moves the contact off its own face and silently breaks the directional contract).

Generated diagrams get all of this for free — the layout engine re-aligns every route after each repair pass, and the shared builder aligns at render time — so these rules bite on hand-authored sources and on edges dragged in the draw.io GUI. `scripts/orthogonalise_drawio.py` applies the same rewrite to a `.drawio` in place. (Distilled from a reviewer's hand-edit of the AWS landscape, 2026-09-26: three edges, all three instances of this one defect.)

**The directional contract (the one hard rule — stated first).** Every edge with explicit contact points **exits** its source on the **right or bottom** and **enters** its target on the **left or top**. In draw.io unit-square fractions: a valid exit leans right (`exitX >= 0.5`, which admits the right edge and the top-right / bottom-right corners) or sits on the bottom edge (`exitY == 1`); a valid entry leans left (`entryX <= 0.5`) or sits on the top edge (`entryY == 0`). A left-edge exit (`exitX=0`) or a right-edge entry (`entryX=1`) is the defect. This single rule removes most crossings on a dense diagram and is enforced by the `edge-direction` lint rule — WARNING for `flow`, **ERROR for `landscape`**. Exceptions are the documented corner-exit and back-edge patterns below (both still exit right/bottom, enter left/top).

**No floating connections (pin every contact point).** Because the contract is checked from the contact points, every edge must actually **set** them (`exitX/exitY` + `entryX/entryY`) rather than float its connection to draw.io's perimeter router, which picks a side by geometry and drifts. An edge that sets neither an exit nor an entry point is an `edge-float` finding — WARNING for `flow`, **ERROR for `landscape`** (a dense as-built must pin every side).

**One edge per corridor (no merged lines).** Two **unrelated** long edges must never run in the same straight corridor — same horizontal (or vertical) grid line with overlapping extent — because the two lines merge into one and cannot be told apart. Offset each parallel run by ≥ one grid step onto its own corridor via explicit `<mxPoint>` waypoints. Cross-region / cross-AZ long-haul edges each get their **own** dedicated corridor (e.g. a lane above the AZ boxes or in the inter-VPC gap), one lane each. A **shared trunk is exempt**: edges leaving the *same source* (or reaching the *same target*) may share their stub before branching in opposite directions. This is enforced by the `corridor-sharing` lint rule (WARNING).

**Route in the nearest FREE corridor and enter the face that corridor meets (adaptive routing).** A tier-skip or cross-region run does not always take "right corridor → enter top." It picks the nearest **free** corridor and enters the target's face that corridor reaches — all faces used stay contract-legal (exit right/bottom, enter left/top):

- **Tier-skip past an intermediate node, same column, LEFT gap free** → drop in the column's **left** corridor and enter the target's **left** face (the load-balancer→lower-AZ-app case). Cleaner than a right corridor that must step back across the column. Taken only when the enclosing container leaves ≥ 1 grid step to the column's left and no icon sits in that gap; otherwise fall back to the right corridor + top entry.
- **Cross-region hop, target has a clear left approach** (row-rightmost, left face free) → route in the **inter-row gap** between the source row and the row below, then enter the target's **left** face — never along an AZ/VPC top caption. A target with a left neighbour is still reached from the **top**.
- **Free-corridor predicate.** Before choosing a side, verify the corridor lane is empty and the target face has a clear approach (≥ 1 grid step to its neighbour / container edge). This makes a hand-tuned route reproducible for any layout rather than hard-coding coordinates. `edge-crosses-container-label` (below) is the regression gate.

**A long run picks its row band by what else is in that band, and its exit band follows.** This is the one rule that subsumes most of the fan-out and long-haul guidance below, and the one that took the landscape to hand-routed quality. Every fan-out, cross-region hop and back-edge runs a long horizontal leg in a **row gap** — above the row or below it — and three decisions have to agree:

- **The band above a container's first row is free by construction.** Nothing is ever placed between a container's caption strip and its topmost icons, whereas the band *below* a row carries the next tier's drops, the nested boundary boxes and their captions. So a fan-out whose source sits in the topmost row of its container runs **above** the row — *unless* an inbound **top-entry approach** column falls inside the run, because that approach has to cross the band to reach its target and the fan-out would cut it. Check the run's own extent (`source_right … target_x − ½ gap`) against the row's approach columns: an approach at the far left of the row does not block a fan-out running off to the right.
- **The exit band must be on the side the lane is on.** An above-going branch leaves from an **upper** band, a **level** run (a straight hop to a same-row neighbour) keeps the **centre**, a below-going branch leaves from a **lower** band. Leave from the wrong side and the stub has to travel back across the face to reach its lane, cutting every sibling on the way — a descending fan-out that left from *above* the level run it then crossed is exactly this defect. A **back-runner** (one that turns and heads left) goes **outermost**, because its turn column is necessarily the nearest lane to the face, so a sibling turning farther out would cross it at the glyph.
- **One band, non-overlapping runs.** Two long runs in one band get distinct lanes, but distinct lanes do not stop them crossing: each turns vertically at its ends, and when their horizontal **extents overlap**, those turn legs cut the sibling's lane whichever lane each got — symmetrically, so no lane ordering fixes it. Overlapping extents therefore go on **opposite sides** of the row. Claim extents per (row, side), fan-out runs first (their side is forced by the container geometry), then give each long-haul run the first side it does not clash with, preferring its natural side. A **top row** has no band above it, so two opposed runs leaving it cannot be separated — that crossing is the layout's, not the router's.

Corollary: the **overflow valve** below now stands down when a face has an above-lane-capable branch. Three right-face exits can be served one per band (above / level / below) instead of spilling the farthest onto the bottom, which is what the valve was approximating while every fan-out was stuck below its row.

**A crowded right face is relieved by the branch that has a straight drop.** When a node fans out sideways along its row **and** has one branch to the tier directly below it, three exits pile onto the right face and the downward one has to turn, run back under the row and cross both siblings. That branch has a clean vertical available, so it takes it: **bottom-centre to top-centre**, no turns, no lane, nothing to cross. Scoped to a genuinely crowded face (three or more right exits) with **exactly one** directly-below branch, so the engine never has to choose between two bottom stubs.

**Overflow valve: spill a crowded fan-out onto the bottom face.** A node's right face holds only so many distinct fan-out lanes before their below-row corridors tangle with each other and with an adjacent target's straight stub (the `app → cache / db / obj` case: three right exits whose corridors crossed). When a source has **more than two** right-going fan-out edges, spill the surplus onto the **bottom** face, farthest target first (largest dx, declared-order tiebreak): the spilled edge drops straight from the source bottom into its **own** below-row corridor and enters the target's left face, so the right face keeps at most two clean exits. Deterministic and scoped to genuinely over-connected right faces (≤ 2 right edges are untouched); both faces stay contract-legal, so `edge-direction` is unaffected. **Superseded in part:** where an above-row lane is available the branches split across the two bands instead (see the band rule above); the valve still applies when every branch is stuck in the below band.

**A left-corridor fan-out branch exits bottom-LEFT, the straight branch bottom-centre.** When a fan-out source sends one branch down the **left** corridor and another straight down the column, the left branch must leave from the **bottom-left** band and the straight branch keep the **bottom-centre** — otherwise the left branch's immediate leftward step crosses the centre branch's drop at the glyph (edge 4 crossing edge 3). Biasing the left-corridor branch to the left band makes the two bottom stubs diverge from the start with no crossing.

**A source that fans out downward may leave from TWO faces (right + bottom).** When a node is the *start* of several downward flows — a load balancer or DNS branching to two app tiers / two AZs — it reads more naturally leaving from **two contract-legal faces** than cramming every branch onto the right and looping the straight-down one. The rule (v1.5.1, generator-applied): for a source with **≥ 2 downward edges**, the branch whose target is **directly below in the same column** exits the **bottom** (a clean vertical drop into the target's top, exactly like the compact summary's `lb → app` chain); the sibling branches keep the **right** face. This needs no change to `edge-direction` — bottom (`exitY==1`) and right (`exitX>=0.5`) are both legal exits — it only widens which allowed face the engine picks for the straight-down branch. It triggers only when exactly one branch is the clean directly-below drop, so a single-edge source or a fan-out with no vertical branch is unchanged.

**Spine edges route via a side corridor, not down the node column.** A vertical "spine" hop between tiers in the same column (edge → router → app, app → data) should **not** drop straight down through the column even when source and target share an x — a straight in-column vertical visually collides with the icons and their labels stacked in that column. Instead **exit the source's right, drop in the gap corridor one grid column beside the column, and enter the target's left/top.** (The exception is the fan-out-source bottom branch above: a *directly-below* target with a clear column is reached by a straight bottom drop, since there is no intervening icon to collide with.) For the canonical HA layout that gap sits between the node column and the next (e.g. a load-balancer at column x routes down the corridor at `x + ½·COL_STEP` — the empty lane between the LB column and the cache column — then into the app node). This keeps the spine legible and leaves the node column clear for labels. (Distilled from a reviewer's hand-edit of the AWS landscape, 2026-09-23.)

**Fan-out along a row: turn up into the target in the gap BEFORE it, not right after the source.** When one node fans out to several targets to its right on the same row (e.g. `app → cache`, `app → db`, `app → object-store`, where cache/db/obj sit two-plus columns away past intervening icons), each edge exits the source's right/bottom, runs along its **own** below-row lane, and makes its **vertical up-turn in the inter-column gap immediately to the LEFT of its target** — then enters the target's left face. Do **not** drop all the fan-out verticals right beside the source: that stacks them a few pixels apart so they read as one merged line, and forces every edge to run the full width under the row. Placing the up-turn in the gap just before each target (`target_x − ~½ gap`) instead spreads the verticals across the row (one per target, well separated) and keeps each horizontal run only as long as it must be. Pair this with **distinct below-row lanes** (each edge its own y, ≥ 1 grid step apart) so the horizontals never merge either. Net shape: a set of stepped "exit-right → own lane → up-turn just before the target → enter-left" edges that fan across the row cleanly, rather than a bundle of near-parallel lines hugging the source. (Distilled from the reviewer's `app→db` / `app→obj` routing on the AWS landscape, 2026-09-23.)

**A back-edge runs on the side its TARGET is on, and drops in a FREE column.** Two parts, both about not deciding a long route from local information:

- **Corridor side.** A back-edge (or cross-region hop) whose target sits a full row or more **below** it loops **below** its own row, not above. Choosing the side on canvas room alone sends a downward hop up over the tier above and back down the length of the diagram to reach a target that was two rows beneath it.
- **Drop column.** The natural column to descend in before a **top** entry is the target's own centre — but only when that column is clear. Where the target sits at the bottom of a **stacked column** (load balancer over application tier over API tier, all at one x) that column is full: the drop cuts every icon above the target, and the clockwise detour then leaves it a couple of pixels off their border, which is the second-rail defect this standard forbids. Take the target's own column when clear, else the **centred lane in the gap beside it** (left preferred, then right, each kept ≥ one grid step inside the enclosing container and the target column), then step across in the lane just above the target and drop into its top. Clearance of one grid step from a column of icons is the floor; more is better.

**A back-edge's turn corridor sits one column beyond its SOURCE, not the canvas edge.** When an edge's target is far to the right (or a back-reference to the left), its first turn happens in the gap **one grid column beyond the source**, and it runs across in a reserved lane from there — it does **not** detour to a far/outer column first (that makes the longest, most border-crossing line on the canvas). Example: a `dns → passive-LB` standby edge turns at `dns_x + ~1 column` and crosses in a mid corridor, rather than travelling to the passive region's own column before turning. (Generalises the earlier "turn near the source" lesson to the spine edges.)

**Never leave an edge endpoint detached.** Every edge's `source` and `target` must reference the **node cell id**, never a floating `<mxPoint>` coordinate. A hand-drag in draw.io can detach an arrowhead onto empty canvas (the edge then has no `source=`/`target=`); such an edge renders as a line to nowhere and trips `edge-float`. Re-attach both ends to their node ids. (This is why the generator sets `source`/`target` explicitly and never emits point-only endpoints.)

**Step sideways before turning (stair, not an immediate right-angle at the glyph).** When an edge leaves a service's side and must then turn, take a short step **into the gap corridor first** and only **then** turn — the turn happens one grid column off the node, not glued to the node's border. Concretely, the first waypoint after a right exit sits at the gap-corridor x (e.g. `source_right + gap`), and the vertical drop happens there — never at the source's exact edge x. A right-angle bend flush against the glyph reads as a kink; a short lead-out step then the turn reads as a clean stair. (Distilled from a reviewer hand-edit, 2026-09-23.)

**One turn at a time; no long vertical run parallel to a node column.** Minimise the number of turns an edge makes, and never run a long vertical **alongside a column of icons** (e.g. hugging the boundary's inner margin next to the app/api column) — it reads as a parallel rail and visually merges with the column. A tier-skipping vertical (e.g. LB → app in the second AZ) routes in an **inter-column gap corridor**, drops once, and enters the target's left/top with a single step-in — not a left-margin detour with a full-height vertical beside the nodes.

**A tier-skip must not cross a fan-out; take the one clear corridor.** When a long tier-skipping edge (e.g. `LB → app-AZ2`) would have to cross the source-tier's fan-out lanes (the `app → cache/db/object-store` below-row corridors all sit to the *right* of the app column), route it instead down the **one reserved corridor that crosses none of them** — the gap on the side the fan-out does *not* occupy (here the left gap, `vpc_left..app_left`, centered), and enter the target's near face. Choosing the crossing-free lane beats a "prettier" central drop that cuts every fan-out horizontal. Verify the chosen corridor's x is outside every fan-out segment's x-range before committing it.

**A bottom fan-out exits DOWN first, then steps (stair from the bottom).** In the rare case a bottom exit is used (target directly below, no label between — see *Label-safe exits*), the edge goes **straight down** into its lane first and only then turns sideways — it does not leave from a bottom corner and immediately veer. (Mirror of the side stair: side → step out then turn; bottom → drop then turn.)

**Step out before turning up, too (not only down).** The stair rule is symmetric for upward turns: a cross-tier/cross-region edge that exits a node's right and must then rise into a corridor **steps sideways into the gap first, then turns up** — the vertical up-leg sits one grid column off the node, never glued to the node's right edge. Example: cross-region `db → db'` exits right, steps to `source_right + gap`, then rises into its corridor.

Directional convention (matches the lane order and provider reference diagrams):

- **Exit side priority (in order).** Choose the exit point by the first rule that fits: (1) **right, centred** (`exitX=1, exitY=0.5`) is the default; (2) **right, biased toward the run's direction** — nearer the top for a target above, nearer the bottom for a target below; (3) **straight down the bottom** (`exitY=1`) **only when that is the shortest path** and no label lies between source and target (see *Label-safe exits*); (4) a **second/third** edge repeats this priority, spread across the side by the even-thirds rule below. The right side is the default because a bottom/top stub crosses the node's own caption.
- **Entry side by the incoming line, then centred.** The entry **side** is chosen by where the line arrives, not by a fixed left-before-top order: a line arriving **horizontally** enters the **left** (`entryX=0`), a line descending **vertically** enters the **top** (`entryY=0`). On that side the point is **centred** (`0.5`) by default. Only when a target takes **more than one** entry do the extra entries **shift off centre toward their own incoming line** (by the even-thirds rule) so each stub meets its line without doubling back. Never enter over the target's own label.
- **Distinct same-side exits (straight line keeps the centre).** A node with **one** edge on a side uses that side's **centre** (`0.5`). When several edges share a side, an edge whose target sits **directly opposite** (same row → a straight horizontal; or directly below → a straight vertical) keeps the **centre** because a straight line is the most readable; the *other* edges spread around it. The only hard requirements are that the exits stay **distinct** (any two ≥ ~⅕ of the side apart, so they never merge into one doubled line at the glyph) and that a side carries **at most three** exits (a fourth means the node is over-connected — split or re-lane). This is deliberately looser than a rigid `0.25/0.5/0.75` grid, so `0.5` + a spread pair, or `0.33/0.66`, are all valid. Lint-checked (`exit-thirds`, WARNING — over-connected side, or two exits that merge).
- **Step out one grid step before turning (exit and entry alike).** An exit runs one grid step straight out of its side before its first turn; an entry runs one grid step straight into its side after its last turn. The corner never sits flush against the glyph — it is one step off, in the gap corridor. This is the *stair* shape stated once for both ends.
- **Clean arrow start (exit slightly past the perimeter).** Start the stub a hair beyond the icon border (`exitX=1.02` with `exitPerimeter=0`, or the matching `exitY`) so the arrow does not bite into the source glyph while the head still lands on the target's entry point.
- **Route around obstacles clockwise.** When an edge must detour around an intervening node, a container border, or another line, go around it **clockwise** (obstacle kept on the edge's left). One fixed turn direction makes the detour deterministic — two agents routing the same edge produce the same path — and stops a detour from doubling back into what it just avoided.
- **Any overlap (edge, or a container border) means step off by one grid step.** If a run would coincide with another edge's corridor **or with a boundary/container border**, offset it by at least one grid step onto its own lane via explicit `<mxPoint>` waypoints. A line riding along a box border reads as part of the border; a line riding another line merges into one. Both are the same fix: step off a step.
- **When space is tight, widen — never narrow — the corridor.** If a corridor cannot hold every parallel run at one grid step apart, grow the gap (push nodes or the container out a step) rather than squeezing runs below one step. More padding is always better than a corridor too narrow to separate its lines. This is the tie-breaker whenever spacing and compactness conflict.
- **Lanes are two grid steps apart by default, one when the band is full, and never shared.** Parallel runs read as separate lines at two grid steps; a band trimmed to ~30px by a container caption strip holds only one such lane, so a second run there drops to **one** grid step — still distinct, still grid-aligned. What must never happen is a run falling back to the band's *midpoint*, because a second run falling back the same way lands on the same line, and a shared lane that was never allocated cannot be repaired: bumping one run moves it onto the other. Allocate, then tighten, and only then give up.
- **A long vertical never coincides with a container border.** A run that sits exactly on a box edge reads as part of that edge. This bites where a lane is derived from the same column as a nested boundary — centring a corridor in a VPC's left gap lands it precisely on the AZ box's left edge. Step to the nearest grid line in the gap that clears every border it would otherwise ride, preferring the smallest move so the lane stays as centred as it can be.
- **No edge–node crossings.** An edge must not pass through any node it does not connect; route around it (clockwise, per above) with waypoints, or move the node out of the corridor. A line overlapping an unrelated icon is a defect.
- **Corridors clear the label band (no line through a caption).** A horizontal corridor placed one grid step under an icon still runs through the **service caption** drawn beneath it (the label band, ~one line ≈ 30px below the icon). Every horizontal run therefore starts **below the source row's label band** (a below-row lane insets past `icon_bottom + LABEL_BAND`), and an over-row corridor insets past the **upper** row's label band. This keeps a fan-out or cross-region run off the names of the row it passes. Enforced by the `edge-crosses-label` lint rule (WARNING): a routed polyline that crosses an unrelated node's label band is flagged, so the icon-box geometry rules (which measure the bare icon) do not let a caption-crossing slip through.
- **Bottom-exit is a last resort, only to remove a crossing.** The default is a right exit (a bottom stub crosses the node's own caption). A tier-skip to a target **strictly below in the same column** MAY exit the bottom **only when** doing so removes a crossing the right-exit route would make and introduces none — verified against the geometry oracle, never applied speculatively.
- **No edge–label / edge–legend crossings.** Keep every edge clear of the right-side `Flow` and `Legend` cells; reserve the right margin for those blocks and route edges within the diagram body.
- **Shared trunk, opposite branches (fan-out from one node).** When a single source fans out to targets stacked on the same side, route the edges into **one shared trunk** just outside the source (one clear grid column/row beyond its edge), then branch off it in **opposite directions** — up to the upper targets, down to the lower ones. The branches never overlap, ink and corner count stay low, and the picture reads as a clean tree. This is the one place edges may share a stub (the `corridor-sharing` exemption for a common source/target); prefer it over giving every fan-out edge its own long detour corridor.

A node should not sit directly between two other nodes on a straight horizontal or vertical line that an edge must traverse; stagger nodes across lanes (vary the row) so edges route around icons rather than through them.

### Named routing patterns (apply to both classes)

These patterns are independent of node count and matter most on dense diagrams.
They were distilled from building a 40-node as-built against this standard.

- **Directional back-edge (exit-right / loop / enter-left).** When an edge's
  target is to the **left** of its source (a back-reference, e.g.
  `Bedrock → Aurora` where Aurora sits in an earlier column), it must **exit the
  source's right, travel in a dedicated over/under corridor, and enter the
  target's left** — never exit the same side it enters. Exiting left and
  re-entering left makes the edge cross its own column. Give the back-edge its
  own grid-step corridor above (or below) the node rows so it clears every icon.
- **Longer clean detour over a short crossing.** When routing an edge either
  short-but-through an unrelated icon, or longer-but-around it, always choose the
  longer path that stays in declared corridors. A fan-out edge from a stacked
  column must leave through a **side corridor** one grid column beyond the stack,
  not straight through the middle icon of the stack. Ink economy never justifies
  a crossing.
- **Corridor before content.** Decide the horizontal/vertical gap corridors
  *before* placing edges; assign each parallel run its own grid-step column/row
  via explicit `<mxPoint>` waypoints. Do not rely on the auto-router to separate
  parallel runs — it merges them.

## Container Padding

A Boundary or Network Boundary container must leave a margin of at least **one grid step on every side** between the container edge and the nodes inside it, and between a nested container (for example a Network Boundary inside a Boundary) and its parent. Do not place a node flush against, or straddling, a container border. Size containers so their children plus this padding fit without the border clipping a node or its label. A node that shares the container's column (or row) but has **slid past its top/bottom border** — drawn just outside the box it lines up with — is the same defect from the other side: size the container to enclose every resource that belongs to it, and place a resource that does *not* belong (a regional service like S3 relative to a VPC) in its own column clear of that container's band, not below it. The `container-padding` rule flags such a spilled node.

**A node's footprint includes its label.** A node cell is a 78×78 icon, but the service name renders in a caption band directly **below** the icon (`verticalLabelPosition=bottom`). That band collides with the next row and the container border exactly as the icon does, so *padding is measured against the footprint (icon + one label line, ~30px), not the bare icon box*. Sizing a container to the icon boxes alone leaves the labels crowding — or overflowing — the border, which reads as "no padding" even though the icons technically fit. The `container-padding` and `node-overlap` lint rules are label-aware for this reason.

**A container's TOP padding reserves its own caption strip (≥ 60px).** A draw.io group draws its caption *inside* its own top edge, so a uniform 30px pad makes the caption band and the top padding the **same** strip: the first content row then begins exactly where the caption ends, and there is **no corridor lane inside the container above its first row**. Any edge descending into the container has to run through the caption — which is what `edge-crosses-container-label` flags, and what four edges on the re-connected HA landscape did (an account-row hop and a CDN origin fetch slicing `vpc-primary us-east-1`). So the top padding is **`CONTAINER_PAD + CONTAINER_LABEL_BAND` (30 + 30)** while the other three sides keep the bare 30: the caption gets its own strip, the 30px below it is real clearance, and every container gains a legal entry corridor. Two consequences follow for a nested stack: the region band is anchored one caption strip *plus* one pad lower than its lane row would put it (so the container cannot grow upward into the tier above — on the HA landscape, into the account edge row's label band), and an inter-band gap that separates two boxed bands grows by the same strip. The shared layout engine applies all of this in `size_containers` and `_band_packing`; a hand-authored container must budget the same 60px at the top.

**Text-box padding (Flow / Legend / notes).** Every text box that draws a **visible box** (a concrete `fillColor` and `strokeColor`) reserves uniform inner padding on all four sides — `spacingLeft=spacingRight=spacingTop=spacingBottom=10` (one grid step) — so no line of text abuts the stroke, and is sized from its content **plus** that padding (one 12px line ≈ 16px of leading). Use the one project-wide value everywhere so every box breathes identically. The shared builder's `_TEXT_STYLE` carries these tokens and `build_diagram` auto-sizes the box height, so every generated Flow/Legend cell passes; a borderless title or free label (no concrete fill+stroke) has no box to pad and is exempt. Enforced by the `text-padding` lint rule (WARNING).

## Container Nesting (proper nesting, no sibling overlap)

Boundary containers form a **strict tree**: a child is *fully inside* its parent with padding (Account ⊃ Region/VPC ⊃ Availability Zone ⊃ tier). Two containers either nest (one fully contains the other) or are **disjoint siblings** — they must never *partially* overlap. Two overlapping peer boundaries (for example a primary-region VPC box bleeding into the passive-region VPC box) put shared canvas area under two labelled groups at once, so a node in that area is ambiguous about which boundary owns it. A sibling overlap is a `container-overlap` finding (WARNING for `flow`, **ERROR for `landscape`**).

Practically: give each region/VPC its own horizontal band with a clear gap between peers, size each Availability-Zone box to sit fully inside its VPC with ≥ 1 grid step of padding, and never let two AZ boxes (or two VPC boxes) share an x- or y-corridor. **Sibling containers in the same row share a common top edge and height; in the same column, a common left edge and width** — absorb any padding correction by adjusting the non-shared dimension (width for a row, height for a column), so peer boundaries read as one banded row rather than a ragged step.

**Balance the horizontal space: centre nodes in their boundary; keep sibling bands one consistent gap apart.** Do not leave a large dead gap between two region/VPC bands while the nodes hug one side of each. Nudge each band's nodes so they sit **centred within their boundary** (even left/right padding), pull sibling bands together so the inter-band gap is **one consistent step** (not a wide void), and size the enclosing parent (Account) to **wrap the bands snugly** with one grid step of padding — no trailing empty margin. All nudges are whole grid multiples so every origin stays on the grid; the right-margin Flow/Legend column then sits just past the tightened parent, not far out in dead space. (Distilled from a reviewer's space-optimisation of the AWS landscape, 2026-09-23.)

**Sibling region bands are equal size, and their nodes sit centred on the grid.** Peer region containers (the primary and passive VPC, and their matching AZ boxes) must be the **same width** — a passive region is not drawn narrower than the active one. Widen both bands toward the shared centre so their outer edges stay put and their widths match. Within each band, the block of service nodes is **centred** in its VPC with equal left/right padding, and every node origin stays on the grid (a whole grid multiple). Centre the block as a whole (all nodes plus their edge waypoints move together) so routing is preserved; do not centre by eye. This keeps the two regions mirror-symmetric and readable. (Reviewer goal 2026-09-23.)

**Reserve the right margin for Flow/Legend, clear of the cloud.** The `Flow` and `Legend` text blocks live in the right margin, their left edge at least one grid step **past the outermost container's right edge** — never overlapping the account/VPC boxes, and never parked in the left margin under the actor column. Enforced by the `legend-placement` lint rule (WARNING), which reports `left-of-diagram-body` when a block does not clear the outermost container and `overlaps-<container-id>` when it is drawn on top of one. When the diagram is wide, pin the blocks **narrow and let them wrap taller** rather than run wide into (or past) the diagram body — the sanctioned exception described under *Numbered Flow Legend* above; a narrow-and-tall Flow/Legend never collides with a node or a container border.

**Size a parent's envelope from its deepest child's FOOTPRINT, not its top.** A parent container's bottom (and right) must clear its deepest/rightmost child by ≥ 1 grid step measured against that child's **footprint** (icon + label band), and the child container must clear ITS deepest node the same way. Grow the parent's height/width to satisfy this — never shrink a child box until its own node's label touches its border. Concretely: if the lowest node's footprint bottom is `B`, the enclosing AZ box bottom is ≥ `B + 30`, the VPC box bottom is ≥ `AZ_bottom + 30`, and the Account box bottom is ≥ `VPC_bottom + 30`; the page height follows the Account box. A nested box whose bottom coincides with its parent's bottom (flush) is a `container-padding` finding.

## External actors and on-premises sit OUTSIDE the cloud boundaries

An actor (lane `actors`) or an on-premises / external-datacenter node (lane `on-premises`) is **not** an account/region resource and must be placed **outside** the stack Boundary and Network Boundary containers. Only cloud resources live inside them. On-premises resources get their **own** boundary container (an On-premise group) drawn outside and separate from the cloud Account/Region boundary — never inside it, and never as a bare floating icon. The cross-boundary edge (a cloud tool → an on-prem server) then visibly crosses from the cloud boundary into the on-prem boundary, which is the point.

## Layout Geometry (canonical, all providers)

Every generated diagram uses one shared numeric layout so AWS, Azure, GCP, OCI, and generic diagrams read identically. The **AWS golden example** (`examples/aws/01-aws-agent-platform.drawio`) is the reference; the values below are its distilled standard. The shared builder `src/rule_engine/diagram_layout.py` implements them and is the mechanism new diagrams should use — a new provider supplies an *icon renderer*, not new geometry.

| Constant | Value | Meaning |
| --- | --- | --- |
| Icon footprint | **78 × 78** | Every service node's cell is a 78×78 square (`aspect=fixed`). |
| Label placement | `verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=12` | The label sits directly under the icon. The node cell equals the icon size so the label hugs the icon — never a taller footprint that pushes the label away. **12px is the minimum** (see Accessibility & Contrast). |
| Column step | **220** | Horizontal distance between adjacent node columns (lanes read left→right). |
| Row step | **160** | Vertical distance between adjacent node rows. |
| Grid step | **10** | Model `gridSize`; every node origin (x, y) is a whole multiple of it. The `grid-alignment` lint rule enforces this. Column step (220) and row step (160) are the reference rhythm; individual rows may differ but stay grid-multiples. |
| Container padding | **≥ 30** | Padding between a container border and its children / a nested container (≥ 1 grid step; the reference uses 30). |
| Legend column | right margin | The `Flow` and `Legend` text cells stack in the right margin, clear of the diagram body. |

**Icon size is uniform.** All service icons render at the same 78×78 footprint regardless of the source asset's native aspect ratio. The exact stencil id / style string for each provider is authoritative in `mappings/<provider>-icons.yaml` — never hand-write or guess a `shape=mxgraph.<lib>.<id>` (an unknown id renders as an empty box → `icon-resolved` ERROR; see `asset-packs.md`). AWS (`mxgraph.aws4.*`) and GCP (`mxgraph.gcp2.*`) resolve to draw.io built-in stencils; Azure and OCI use **custom imported** shape libraries (`icon_source: custom` in their mapping — Azure V24 and the OCI draw.io style guide), not built-in libraries, so their packs must be imported into draw.io before the ids resolve. Whatever the source, the node is one flat cell at 78×78. For OCI the official stencil is embedded, its baked-in caption is **stripped** (so the node carries exactly one label — the service name), and the icon is scaled uniformly into the 78×78 square. Do not let a stencil's own caption double the label or distort the aspect ratio.

**Reference topology (hub-adjacent-to-data).** Place the platform-core hub in the column **immediately left of the data column**, with asynchronous-messaging and worker nodes stacked in the rows **above and below** the hub — never between the hub and the data stores. This keeps hub→data edges short and straight and leaves the data column reachable without crossing an intervening icon.

**North–South reference geometry (infrastructure/deployment diagrams).** The canonical values above describe the default **left→right** flow layout. For a **North–South** infra diagram (see *Diagram Orientation*), rotate the same grid 90°: the eight lanes become **rows top→bottom** (actors/edge at the top, data/on-premises at the bottom), spaced by the **row step (160)**; nodes within a tier are placed **left→right across columns** spaced by the **column step (220)**, with redundant peers (AZ-a / AZ-b) side by side on the same row. Icon footprint (78×78), grid step (10), container padding (≥ 30), and the right-margin Flow/Legend column are unchanged. The geometry-enforced lint rules (grid-alignment, container-padding, node-overlap, edge-routing) apply identically on either axis, since they measure absolute coordinates and are orientation-agnostic. (The four shipped golden examples are all left→right; an infrastructure golden example is a documented gap — see REVIEW.md.)

**Edge routing on the grid.** Route every edge orthogonally (`edgeStyle=orthogonalEdgeStyle`), start stubs just past the source perimeter (`exitPerimeter=0`), and enter left/top, exit right/bottom. When two or more edges would share a corridor, give each explicit `<mxPoint>` waypoints on its own grid column/row, offset by ≥ 1 grid step, so no two lines overlap and no line crosses an unrelated icon or a legend block. When several nodes stack in one column, route edges among them through a side corridor (one grid column left or right of the stack) rather than straight through the middle icon.

**Layout quality is now lint-enforced.** The linter parses the `.drawio` geometry and checks `grid-alignment` (node origins on the grid), `container-padding` (≥ 1 grid step inside every boundary), `node-overlap` (no icons drawn on top of each other), and `edge-routing` (orthogonal edges; a waypoint-free edge may not run straight through an unrelated node). These are advisory WARNINGs — they surface layout defects without blocking publication.

## Icon Fidelity (one role per distinct service)

A node's icon is only ever as correct as the **role** it is mapped to. A service that is semantically different from an existing role gets its **own role** with a per-provider icon — never a look-alike reused from another role. A CDN is not an object store; a DNS/traffic-manager is not a load balancer; a WAF is not a generic secrets store. The presentation roles beyond the nine neutral resource types (for example `cdn`, `dns`, `waf`, `lb`, `cache`) are declared in `mappings/roles.yaml` and resolved, per provider, into the committed `mappings/icon-index.json` by the init-time icon-set builder (`rule-engine-build-icon-sets`; see `asset-packs.md`). Diagram generators resolve a role→icon through that index rather than hand-writing an SVG path or stencil id.

Provider specifics:

- **AWS / Azure / GCP** resolve to an official pack file (or, for AWS, a built-in `mxgraph.aws4` `resIcon`). **GCP follows Google's own docs taxonomy**: a service with a dedicated 2025 product icon uses it; a service without one uses its **category** icon (product-first, category-fallback). Cloud CDN has no product glyph, so — exactly as `docs.cloud.google.com` does — it uses the **Networking category** icon. This is Google's convention, not a look-alike substitution.
- **OCI** ships no built-in draw.io library: every OCI node renders via an **embedded stencil** (`OciStencilIcon`, slug from the 218 decoded stencils in `assets/vendor/oci-stencils/stencils.json`), the same mechanism as the OCI golden example. The OCI-red labelled-box form is a **last-resort fallback only when the stencil pack is absent**, never the default — a node that renders as an empty box is a defect.
- **Never customise a pack icon** (no forced opaque `fillColor`, no recoloured stroke). Signal state with an overlay (red dashed ring + label, edge color, badge, legend entry), not by repainting the glyph.

**Visual render check.** A name-only linter cannot see that a well-formed reference rendered as an empty box, so the pre-export checklist includes a visual pass: confirm every icon actually **renders** in the exported PNG, not merely that its id/path is spelled right. `rule-engine-verify-icon` resolves each reference against the committed index to catch a typo before export.

## Accessibility & Contrast

Every diagram must be legible for reviewers and meet baseline accessibility, aligned with published AWS diagram conventions.

- **Minimum font size 12px.** No on-diagram text — node labels, edge labels, boundary captions, title, `Flow`/`Legend` cells — renders below **12px**. The shared builder pins label and text styles at `rule_engine.diagram_layout.MIN_FONT_SIZE` (12). Text below 12px trips the advisory `min-font-size` lint rule.
- **Contrast ratio ≥ 4.5:1.** Text and lines must reach at least a 4.5:1 contrast ratio against the background. On a white background use a dark text/line color (`#000000` or `#16191F`); never light-gray-on-white. Text inside a filled icon may use the fill's appropriate on-color (e.g. white on a saturated brand fill).
- **Defined background.** Use an explicit white (`#FFFFFF`) background for the exported raster — do not leave it transparent unless the publication target requires a dark/light-adaptive image, in which case use a mid-gray (`#7E7E7E`) for lines/text that balances against both schemes.
- **Never encode meaning by color alone (double-encode).** Any distinction carried by color (for example the removed/blocked "red" change marker) must also be carried by a second channel — a shape, a text label, or a legend entry — so the diagram survives grayscale printing and color-vision deficiency. The numbered-flow legend and the change-marker glyphs (🆕 / 🔄) already provide this second channel; keep them.
- **Lines and arrows.** Minimum stroke width **1pt** (the shared builder draws edges at 1.5pt via `diagram_layout.EDGE_STROKE_WIDTH`); solid = primary flow, dashed = secondary/asynchronous; use **open** arrowheads (`endArrow=open;endFill=0`) rather than heavy filled heads. The `arrow-style` lint rule enforces this.

## Raster Alt Text

- Whenever a diagram includes a raster image, provide non-empty alt text describing the raster image content.

## The Mandatory Artifact Triple

For each `.drawio` diagram named `NN-topic.drawio`, always produce the full triple:

- `NN-topic.drawio` — the draw.io source
- `NN-topic.drawio.png` — the exported raster image
- `NN-topic.diagram.md` — the Companion Document

A `.drawio` file with no matching `.diagram.md` Companion Document is a lint ERROR (`companion-doc`).

If any required output file for a diagram cannot be produced, return a generation error that identifies the diagram and the missing output file, and exclude the partial diagram from publication.

## Raster Export Dimensions

The exported `NN-topic.drawio.png` must stay readable and lightweight, aligned with AWS diagram conventions. **The budget is class-aware**: a `flow` diagram fits a documentation column, so its raster is narrow; a `landscape` as-built exists to show a whole system on one canvas, so forcing it into a flow-width raster shrinks thirty-plus nodes until the icons are illegible (the exact defect the audit surfaced). A landscape therefore exports wider — the reference detailed as-built lands at ~3400px — and readability at that width is held by the container / padding / overlap / direction rules, not by a narrow cap.

| Property | `flow` target | `landscape` target | Rationale |
| --- | --- | --- | --- |
| Max export width | **≤ 1600px** | **≤ 3600px** | flow fits a doc column (a touch wider for a two-region summary); a landscape needs far more |
| File size | **< 500KB** | **< 2MB** | fast page loads; a wide as-built is inherently heavier |
| Resolution | **72–96 DPI** | **72–96 DPI** | crisp on screen without oversizing |
| Background | explicit **white** (`#FFFFFF`) | explicit **white** (`#FFFFFF`) | consistent rendering across viewers (see Accessibility & Contrast) |
| Outside padding | **8px** all sides | **8px** all sides | clean framing per AWS convention |

Rules:

- A `flow` raster stays at **1600px or less** and **under 500KB**. If a flow diagram cannot meet that while staying readable, that is a signal it holds too much — **split it** (each split still capped at 12 nodes with an index document), rather than exporting an oversized raster.
- A `landscape` raster may run up to **3600px** and **under 2MB** — do **not** split a comprehensive as-built to fit the flow width, since that destroys the one thing it exists to show. `scripts/export_raster.py` picks the export width from the diagram's `diagram_class` automatically (flow → 1600px, landscape → 3400px).
- The **model** canvas may be larger than the export width (draw.io units); it is the **exported image** that carries the width/size budget. Choose an export scale that lands the image within its class budget.
- The class-aware budget **is** enforced — by the raster gate (`rule-engine-check-rasters`), which reads each `.drawio`'s companion `diagram_class` and applies the matching width/size ceiling. (The linter still evaluates only the `.drawio` source and companion, not the PNG; the raster gate is the pixel/byte enforcement point.)

## Title Cell Format

Every diagram title cell encodes exactly:

```
<provider> <workload> — <boundary id> / <region> | <date> | vN

```

where:

- `<date>` is an ISO 8601 calendar date in `YYYY-MM-DD` form.
- `vN` is the letter `v` followed by a positive integer (for example `v1`, `v2`).

A title cell missing the version identifier or the date is a lint WARNING (`title-versioned`). Express every Change Marker description using an ISO 8601 date (`YYYY-MM-DD`); exclude all relative time expressions (no "yesterday", "last week", etc.).

## Mandatory Legend Block

Every diagram includes a Legend that defines all of the following:

- **solid line** = primary flow
- **dashed line** = asynchronous or event-driven flow
- **red** = blocked or missing or disabled
- **🆕** = new in version N
- **🔄** = changed in version N
- **dashed boundary, outer** = the stack Boundary (Account / Subscription / Project / Tenancy / Environment)
- **dashed boundary, inner** = the Network Boundary (VPC / VNet / VCN / Network)Boundary **stroke color follows the Provider Profile brand palette** (e.g. AWS Account `#232F3E` / VPC `#8C4FFF`; GCP Project `#4285F4` / VPC `#34A853`; the `generic` profile uses green for the stack boundary and blue for the Network Boundary). Distinguish the two boundaries by their **dashed outer-vs-inner nesting and their labels**, never by color alone (see Accessibility & Contrast — double-encode). The legend entry names each boundary in words so it is correct for every provider.

A diagram with no Legend is a lint ERROR (`legend-present`). Example PlantUML legend:

```plantuml
legend right
  Solid line = primary flow
  Dashed line = asynchronous / event-driven flow
  Red = blocked / missing / disabled
  🆕 = new in version N
  🔄 = changed in version N
  Dashed outer boundary = stack Boundary (profile brand color)
  Dashed inner boundary = Network Boundary (profile brand color)
endlegend

```

## Multi-cloud Composition

- Where an architecture spans more than one provider, represent each provider using the icon and color conventions of its Provider Profile.
- A cross-cloud diagram is limited to a maximum of 12 nodes.
- Produce a **C4 container diagram** for a cross-cloud composition that names each provider and labels every cross-provider edge with the data flow it represents.
- Render every Boundary and Network Boundary of each provider using the container group style of the corresponding Provider Profile.
- If a referenced Provider Profile declares no container group style for its Boundary or Network Boundary, return a profile-convention error identifying the affected provider and boundary, and exclude the incomplete diagram from publication.

## Quick Checklist

- [ ] Source format matches the PlantUML/Mermaid decision matrix
- [ ] Single `@startuml`/`@enduml` pair, no preprocessor directives (PlantUML)
- [ ] Orientation matches diagram type: North–South (top→bottom) for infra/deployment, left→right for flow/application
- [ ] Lanes ordered actors → edge → router → async messaging → workers → platform core → data → on-premises
- [ ] ≤ 12 nodes (else split + index document)
- [ ] Special-character node names double-quoted
- [ ] Every edge carries a non-empty label (numeric marker `N` counts)
- [ ] Numbered flow markers used; prose moved to a right-side `Flow` legend
- [ ] Orthogonal edge routing; no edge crosses an icon; entries left/top, exits right/bottom
- [ ] Exit priority: right-centre → right-biased → straight-down-if-shortest → repeat per thirds (never over a label)
- [ ] Entry side follows the incoming line (horizontal→left, vertical→top), centred; extra entries shift toward their own line
- [ ] Same-side exits stay distinct (never merge) and number ≤ 3; a straight-line edge keeps the centre
- [ ] Step out one grid step before the first turn (exit AND entry); corner never flush against the glyph
- [ ] Detours go clockwise around any obstacle (node, border, or line)
- [ ] Any overlap with an edge OR a container border → step off by one grid step onto own lane
- [ ] When spacing is tight, widen the corridor — never squeeze runs below one grid step
- [ ] Parallel runs separated by ≥ 1 grid step via explicit waypoints (no shared corridor)
- [ ] Fan-out from one node uses a shared trunk with branches in opposite directions
- [ ] Back-edges exit right / loop / enter left — never exit the side they enter
- [ ] Fan-out from a stacked column leaves via a side corridor, not through the middle icon
- [ ] Row fan-out: each edge turns up in the gap just before its target (not stacked beside the source); own below-row lane per edge
- [ ] Long run's band picked by what else is in it: above a container's first row when free and no top-entry approach crosses the run, else below; overlapping extents on opposite sides
- [ ] Exit band matches the lane side (above→upper, level→centre, below→lower; back-runner outermost)
- [ ] A crowded right face (3+ exits) with one directly-below branch gives that branch the straight bottom drop
- [ ] Back-edge loops on the side its target is on, and drops in a FREE column (never the target's own when stacked above it)
- [ ] Lanes 2 grid steps apart (1 when the band is full), always allocated — never a shared midpoint fallback
- [ ] No long vertical coincides with a container border
- [ ] Every leg explicitly H or V; first leg meets the exit face head-on, last leg the entry face, from a lane one grid step out; no overshoot-and-return (`edge-approach`)
- [ ] Contacts grid-resolved along the face only (never snap the face coordinate)
- [ ] Step sideways into the gap corridor before turning (stair) — no right-angle bend glued to the glyph edge; symmetric for up-turns (step out then rise)
- [ ] Minimise turns; no long vertical run parallel to a node column; a tier-skip takes the one corridor that crosses no fan-out lane
- [ ] Two+ edges leaving one node side use points ≥ a third apart (0.25/0.5/0.75); a third edge moves to another face (bottom)
- [ ] Bottom fan-out exits DOWN first, then steps sideways (stair from the bottom)
- [ ] Parent container bottom/right clears the deepest child footprint by ≥ 1 grid step (grow the parent, don't shrink the child); no flush borders
- [ ] Flow and Legend boxes share one width: sized tight to the longest line (no wrap) by default, or deliberately pinned narrower so they wrap taller on a wide diagram; heights fit each box's real line count
- [ ] Flow and Legend sit in the right margin, past the outermost container and clear of every boundary (`legend-placement`)
- [ ] Diagram class declared in companion frontmatter (`flow` default, or `landscape`)
- [ ] `landscape` cross-links a ≤12-node `flow` summary via `summary_of`
- [ ] Any overlay marker (findings/state) is documented in the Legend (shape+color+label)
- [ ] Arrow stubs start just past the source perimeter (exitPerimeter=0), not into the glyph
- [ ] No edge overlaps an unrelated node, a label, or the right-side Flow/Legend blocks
- [ ] Containers pad ≥ 1 grid step around child nodes and nested containers (padding measured against the icon+label footprint, not the bare icon)
- [ ] Container TOP padding reserves the caption strip (30 + 30), so an edge can enter below the caption
- [ ] Every role-bearing node is connected by at least one edge, or carries an overlay marker saying why not (`node-connectivity`)
- [ ] Sibling containers do not overlap — boundaries nest strictly or sit disjoint (no partial overlap); peers in a row share top+height, in a column share left+width
- [ ] External actors and on-premises nodes sit OUTSIDE the cloud boundaries (on-prem in its own boundary)
- [ ] Directional contract: every edge exits its source right/bottom and enters its target left/top (`edge-direction`)
- [ ] Every edge pins explicit exit/entry contact points — no floating connections (`edge-float`)
- [ ] One edge per corridor: no two unrelated long edges share a straight lane; cross-region runs get their own corridor; shared trunk exempt (`corridor-sharing`)
- [ ] Text/Legend/note boxes set uniform inner padding (spacing*=10) and are sized to content + padding (`text-padding`)
- [ ] One role per distinct service; icon resolved through `mappings/icon-index.json` (CDN≠object-store; GCP CDN→Networking category; OCI via embedded stencil); every icon actually renders in the PNG
- [ ] Icons uniform 78×78 (aspect=fixed); label hugs the icon (footprint = icon size)
- [ ] All on-diagram text ≥ 12px; text/line contrast ≥ 4.5:1; meaning never color-only
- [ ] Edges use open arrowheads (endArrow=open;endFill=0) and ≥ 1pt stroke
- [ ] OCI stencils embedded with baked-in caption stripped and icon scaled square
- [ ] Grid layout: columns step 220, rows step 160; hub adjacent to the data column
- [ ] Raster images carry non-empty alt text
- [ ] Triple present: `.drawio` + `.drawio.png` + `.diagram.md`
- [ ] Exported PNG within its class budget: flow ≤ 1600px / < 500KB, landscape ≤ 3600px / < 2MB; white background, 8px padding
- [ ] Title cell: `<provider> <workload> — <boundary id> / <region> | <date> | vN`
- [ ] Legend block present with all line styles, colors, and change markers
- [ ] Cross-cloud: C4 container, per-profile icons/boundaries, ≤ 12 nodes, labeled edges

