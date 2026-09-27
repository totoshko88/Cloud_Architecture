# Requirements Document

**Feature:** Provider Diagram Conventions & Best-Practice Alignment (release 1.10.0)

> **Status: draft for review.** Derived from a review of the official provider
> diagramming guidance — AWS `diagram-as-code` best-practices, the AWS Networking
> Best Practices conventions, the Azure Well-Architected *Create architecture
> design diagrams* guide, and the C4 model — cross-checked against the current
> `diagram-standards.md`, `diagram-lint.md`, and `provider-profiles.md`. Each
> requirement carries the source item it grew out of (**A**–**I**) and states
> whether it is **enforced** (a lint rule / gate) or **guidance** (a steering
> note the linter does not check).

## Introduction

The engine already matches the providers on the load-bearing conventions:
transparent group containers (`fillColor=none`), the AWS resource-icon stroke
pattern (`strokeColor=#ffffff`), the 12px font floor, ≥ 4.5:1 contrast,
open arrowheads, ≥ 1pt strokes, the fixed lane order, the ≤ 12-node flow cap,
double-encoding, a versioned title cell, and a mandatory legend. This release
closes the **remaining** gaps found against the official guidance, as nine
independently reviewable items:

- **A** — forbid bidirectional edges (enforced: `edge-bidirectional`).
- **B** — callouts for explanation, and a node-label length cap (enforced:
  `node-label-length`; overlay term `callout`).
- **C** — documentation IP ranges only in network diagrams (enforced:
  `ip-range` + guidance).
- **D** — dark/light-safe raster mode (companion key `raster_background`;
  raster-gate honours it).
- **E** — C4 layering / progressive disclosure (guidance).
- **F** — an explicit diagram-type taxonomy with per-type axis (guidance).
- **G** — companion metadata: `change_log` and `external_refs` (frontmatter).
- **H** — retire inaccurate diagrams; accuracy over simplicity (guidance).
- **I** — grouping strategies: function / environment / AZ / security boundary
  (guidance).
- **J** — a snapshot→diagram autogenerator (enforced: `rule-engine-draw`,
  closing the deferred `docs/REVIEW.md` gap **G8**).

Cross-cutting invariants — determinism, no weakened existing rule, draw.io as the
only publishable source (D1), the rule-table/steering sync test, and the
ratchet — must hold throughout (Requirement 11). The version bump to 1.10.0 and
the CHANGELOG are sequenced last (Requirement 12).

### Out of scope (1.10.0)

- No new provider profile; no change to the nine neutral resource types or the
  presentation roles.
- No change to the layout geometry constants or the scored placement/route
  solver.
- New enforced rules (A, B, C) are **WARNING** severity: they surface a defect
  without blocking publication, matching how the other advisory geometry rules
  behave. No new rule is CRITICAL or ERROR.

## Glossary

- **Bidirectional_Edge**: an edge whose style sets both a start arrowhead and an
  end arrowhead (`startArrow` ≠ `none` and `endArrow` ≠ `none`).
- **Callout**: a text annotation cell carrying explanatory prose, documented in
  the Legend via the overlay term `callout`; distinct from a node label.
- **Node_Label**: the `value` display text of a service node (an icon cell).
- **Label_Word_Cap / Label_Char_Cap**: the maximum node-label length before
  `node-label-length` warns (4 words / 40 characters, whichever is exceeded).
- **Documentation_Range**: an IP range reserved for documentation — IPv4
  `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`; IPv6 `2001:db8::/32`;
  plus the private ranges RFC1918 / RFC6598 / RFC6815.
- **Public_IP_Literal**: a routable public IP in on-diagram text that is not in a
  Documentation_Range and not private.
- **Network_Diagram**: a diagram whose `diagram_class` is `landscape` or whose
  companion `diagram_type` is `network` / `infrastructure` / `deployment`.
- **Raster_Background**: companion frontmatter key `raster_background`, one of
  `white` (default) or `transparent`.
- **Dark_Light_Safe**: a transparent-background raster using `#7E7E7E` for text
  and lines on the transparent background (AWS Networking convention).
- **Diagram_Type**: an optional companion frontmatter key naming the artifact's
  intent (context / container / component / deployment / data-flow / sequence /
  state / network / user-flow), independent of the lint `diagram_class`.
- **Change_Log / External_Refs**: optional companion frontmatter keys recording,
  respectively, dated change entries and external reference links.
- **Steering_Sync_Test**: the existing test that keeps the `diagram-lint.md` rule
  table in step with the implemented rules.
- **Companion**: the `NN-topic.diagram.md` document paired with a `.drawio`.
- **Autogenerator**: `rule-engine-draw`, the snapshot→diagram command that
  builds a `DiagramSpec` from a Snapshot and hands it to the existing
  `layout()` + `build_diagram()` pipeline (closing G8).
- **DiagramSpec**: the existing coordinate-free declaration
  (`rule_engine.layout.model.DiagramSpec`): `NodeSpec(role, lane, region,
  slot)`, `EdgeSpec`, `ContainerSpec` — no geometry.
- **Role_Mapper**: the existing `reconcile.role_of`, mapping one raw Snapshot
  resource to one of the 16 diagram roles, offline and pure (Decision D5).
- **Lane_Assignment**: the deterministic role→lane function the Autogenerator
  uses to place each node in the fixed lane order.
- **Relationship_Input**: an optional edge list the Autogenerator consumes to
  draw relationships; absent one, nodes are drawn per the completeness rule
  and connectivity is left to the author (a `node-connectivity` WARNING).

## Requirements

### Requirement 1: Forbid bidirectional edges (A, enforced)

**User Story:** As a reviewer, I want a bidirectional edge flagged, so that a
double-headed arrow does not hide an ambiguous dependency — the provider guidance
is to draw two separate single-ended flows or annotate request/response instead.

#### Acceptance Criteria

1. THE Linter SHALL add a rule `edge-bidirectional` (WARNING, both classes) that
   fires WHEN an edge's style sets both a non-`none` start arrowhead and a
   non-`none` end arrowhead (a Bidirectional_Edge).
2. THE rule SHALL read the parsed `.drawio` edge style tokens (`startArrow`,
   `endArrow`, `startFill`, `endFill`); an edge with a single arrowhead SHALL NOT
   be flagged.
3. `diagram-standards.md` SHALL state the convention: represent a two-way
   relationship as **two single-ended edges** (preferred) or annotate one edge
   with request/response; never a double-headed arrow.
4. THE rule SHALL be recorded in the `diagram-lint.md` rule table in sync with
   the implementation (Steering_Sync_Test).
5. Every Shipped_Diagram SHALL remain free of `edge-bidirectional` findings after
   this release.

### Requirement 2: Callouts and a node-label length cap (B, enforced)

**User Story:** As a reader, I want explanatory prose in a callout rather than
crammed into an icon label, so that node labels stay short and the diagram stays
localizable and accessible (AWS: "do not embed explanatory text into images; use
short labels; use callouts").

#### Acceptance Criteria

1. THE Linter SHALL add a rule `node-label-length` (WARNING, both classes) that
   fires WHEN a Node_Label exceeds the Label_Word_Cap (4 words) OR the
   Label_Char_Cap (40 characters).
2. THE rule SHALL apply to service-node labels only; Legend, Flow, title, and
   Callout text cells SHALL NOT be flagged.
3. THE overlay vocabulary SHALL gain a `callout` term (a text annotation),
   documented in the Legend when used (`overlay-legend-coverage`), and a Callout
   cell SHALL NOT count as a node (it is a text cell).
4. `diagram-standards.md` SHALL state: node labels are short (service name);
   explanation goes in a Callout keyed `overlay=callout`, not in the label.
5. THE rule SHALL be recorded in the `diagram-lint.md` rule table (Steering_Sync_Test).

### Requirement 3: Documentation IP ranges in network diagrams (C, enforced)

**User Story:** As a network reviewer, I want a real public IP in a diagram
flagged, so that examples use the reserved documentation ranges and never leak or
conflict with a real network (AWS Networking convention).

#### Acceptance Criteria

1. THE Linter SHALL add a rule `ip-range` (WARNING) that fires WHEN on-diagram
   text in a Network_Diagram contains a Public_IP_Literal (a routable public IPv4
   or IPv6 that is not in a Documentation_Range and not private).
2. A private range (RFC1918 / RFC6598 / RFC6815) or a Documentation_Range SHALL
   NOT be flagged.
3. THE rule SHALL only evaluate a Network_Diagram; a flow/application diagram that
   incidentally mentions an address SHALL NOT be flagged.
4. `diagram-standards.md` SHALL list the Documentation_Ranges and require IPv6 be
   written per RFC5952 (lowercase, compressed).
5. THE rule SHALL be recorded in the `diagram-lint.md` rule table (Steering_Sync_Test).

### Requirement 4: Dark/light-safe raster mode (D, enforced)

**User Story:** As a publisher, I want to choose a transparent, dark/light-safe
raster when the target theme adapts, so that a diagram renders on both light and
dark backgrounds — while white-background remains the default.

#### Acceptance Criteria

1. THE Companion SHALL accept an optional frontmatter key `raster_background`
   with value `white` (default when absent) or `transparent`.
2. WHERE `raster_background` is `transparent`, THE raster gate SHALL require the
   exported PNG to have a transparent (alpha) background rather than the opaque
   white it currently enforces.
3. WHERE `raster_background` is `transparent`, `diagram-standards.md` SHALL
   require on-transparent text and lines to use `#7E7E7E` (Dark_Light_Safe), and
   the exporter SHALL export without forcing a white background.
4. WHERE `raster_background` is `white` or absent, the existing opaque-white
   check SHALL be unchanged (backward compatible for every current Shipped_Diagram).
5. THE default and the exception SHALL both be documented in `diagram-standards.md`
   (the AWS icon-styling guide wants white; the AWS Networking docs guide wants
   transparent — both are valid publication targets).

### Requirement 5: C4 layering / progressive disclosure (E, guidance)

**User Story:** As an author, I want the class model tied to the C4 levels and a
"layer, don't overload" principle, so that I start from a context view and drill
down rather than encoding everything on one canvas.

#### Acceptance Criteria

1. `diagram-standards.md` SHALL map the engine's classes/types to the C4 levels:
   context → container (≈ `flow` summary) → component/deployment (≈ `landscape`
   as-built), and SHALL state the progressive-disclosure principle (start broad,
   narrow deliberately).
2. THE guidance SHALL cross-reference the existing `summary_of` / `detailed_view`
   pair as the mechanism for layering.
3. This item SHALL be guidance only — no new lint rule.

### Requirement 6: Diagram-type taxonomy with per-type axis (F, guidance)

**User Story:** As an author, I want an explicit diagram-type taxonomy with the
layout axis each type expects, so that I pick the right view and orientation
deterministically (Azure Well-Architected type list; AWS north-south infra).

#### Acceptance Criteria

1. `diagram-standards.md` SHALL define an optional companion key `diagram_type`
   and enumerate the recognised types (context / container / component /
   deployment / data-flow / sequence / state / network / user-flow), each with
   its expected primary axis and lane reading.
2. THE guidance SHALL state that a Network_Diagram may be split into an
   east-west and a north-south view, and SHALL keep the existing orientation
   rules as the axis source of truth.
3. This item SHALL be guidance only — `diagram_type` is descriptive metadata,
   not lint-enforced (the existing `diagram_class` remains the enforced class).

### Requirement 7: Companion metadata — change log and external refs (G, frontmatter)

**User Story:** As a returning reader, I want a dated change log and external
references on a diagram, so that I can tell what changed and trace to source
material (Azure: include metadata and a linked change log).

#### Acceptance Criteria

1. THE Companion SHALL accept two optional frontmatter keys: `change_log` (a list
   of `{date, note}` entries, each `date` an ISO 8601 calendar date) and
   `external_refs` (a list of URLs or citations).
2. WHERE present, `change_log` entries SHALL each carry a valid `YYYY-MM-DD`
   date; an invalid date SHALL be a `frontmatter` finding, consistent with the
   existing date-format enforcement.
3. WHERE absent, no finding SHALL be raised (both keys are optional and
   backward-compatible with every current Companion).
4. `kb-frontmatter.md` SHALL document both optional keys and their formats.

### Requirement 8: Retire inaccurate diagrams; accuracy over simplicity (H, guidance)

**User Story:** As a maintainer, I want the standard to say a diagram must be
accurate or retired, so that a stale or knowingly-wrong diagram is not shipped
for the sake of simplicity (Azure: be accurate; retire diagrams that no longer
answer an active question).

#### Acceptance Criteria

1. `diagram-standards.md` SHALL state: do not sacrifice accuracy for simplicity
   (the PaaS-in-a-subnet-via-private-endpoint example), and retire a diagram that
   no longer answers an active stakeholder question.
2. THE guidance SHALL cross-reference the existing inventory→diagram completeness
   rule as the enforced companion to this principle.
3. This item SHALL be guidance only — no new lint rule.

### Requirement 9: Grouping strategies (I, guidance)

**User Story:** As an author, I want the sanctioned grouping strategies named, so
that I group resources consistently (AWS: function / environment / availability
zone / security boundary).

#### Acceptance Criteria

1. `diagram-standards.md` SHALL name the four grouping strategies — by function
   (web/app/data tier), by environment (dev/staging/prod), by availability zone,
   and by security boundary — and SHALL tie them to the existing boundary-nesting
   and lane-order rules.
2. This item SHALL be guidance only — no new lint rule.

### Requirement 10: Snapshot→diagram autogenerator (J, enforced)

**User Story:** As an operator, I want to generate a first-pass diagram directly
from an inventory Snapshot, so that I do not hand-place every node and hand-route
every edge — closing the deferred `docs/REVIEW.md` gap **G8**.

#### Acceptance Criteria

1. THE engine SHALL add a console script `rule-engine-draw` that reads a committed
   Snapshot folder and a chosen diagram type (`simple` / `summary` / `landscape`)
   and emits a coordinate-free DiagramSpec, then hands it to the existing
   `layout()` + `build_diagram()` pipeline to produce the mandatory triple.
2. THE Autogenerator SHALL resolve every enumerated resource to a role via the
   existing Role_Mapper (`reconcile.role_of`), reading only committed Snapshot
   files and never provider state (Decision D5); a resource with no resolvable
   role SHALL be skipped, never drawn with a look-alike icon.
3. THE Autogenerator SHALL assign each node a lane via a deterministic
   Lane_Assignment (role→lane) consistent with the fixed lane order in
   `diagram-standards.md`, and SHALL derive containers (account / region / az)
   from the Snapshot's boundary metadata.
4. WHERE the chosen type is `landscape`, THE Autogenerator SHALL emit a node for
   **every** role-bearing enumerated resource (total coverage), so the produced
   diagram passes `rule-engine-reconcile` for that Snapshot; WHERE the type is
   `simple` / `summary`, coverage SHALL be the in-scope subset per the existing
   completeness rule.
5. WHERE a Relationship_Input is supplied, THE Autogenerator SHALL draw the given
   edges; WHERE absent, it SHALL emit nodes without inventing relationships, and
   the resulting unconnected nodes SHALL surface as `node-connectivity` WARNINGs
   rather than fabricated edges.
6. THE Autogenerator SHALL be deterministic: run twice on the same Snapshot and
   inputs it SHALL produce a byte-identical `.drawio` (no wall-clock, randomness,
   or dict-order dependence).
7. THE produced triple SHALL be publication-eligible (zero CRITICAL, zero ERROR)
   for a Snapshot whose role-bearing resource count fits the chosen type's node
   budget; WHERE a `landscape` exceeds the `node-count` ERROR bound (> 50), THE
   Autogenerator SHALL report that the Snapshot must be split rather than emit a
   blocked diagram.
8. THE Autogenerator SHALL emit a companion `.diagram.md` with the required
   frontmatter (including `diagram_class`, and `summary_of`/`detailed_view` for a
   `summary`/`landscape` pair) so the triple is complete and the landscape is not
   an `orphan-landscape`.
9. THE `rule-engine-draw` command SHALL be a packaged console script (shipped in
   the wheel and the power), consistent with the other `rule-engine-*` gates.

### Requirement 11: Cross-cutting invariants

**User Story:** As a maintainer, I want the release to preserve every existing
guarantee, so that adding these conventions never regresses the corpus.

#### Acceptance Criteria

1. Every new **lint rule** (Requirements 1–3) SHALL be **WARNING** severity and
   SHALL NOT, on its own, block publication. (The Autogenerator of Requirement
   10 adds no lint rule; it produces artifacts the existing gates judge.)
2. No existing lint rule SHALL be weakened or removed.
3. Generation SHALL stay deterministic: the same spec SHALL produce a
   byte-identical `.drawio` (no new nondeterminism from callouts or metadata).
4. Every Shipped_Diagram SHALL remain eligible for publication (zero CRITICAL,
   zero ERROR) after this release; any new WARNING it trips SHALL be either
   resolved in the generator or explicitly accepted and recorded.
5. THE `diagram-lint.md` rule table SHALL stay in sync with the implemented rules
   (Steering_Sync_Test), and the raster ratchet SHALL be tightened-never-regressed.
6. draw.io SHALL remain the only publishable source (D1).

### Requirement 12: Version bump and CHANGELOG

**User Story:** As a maintainer, I want the version triple and CHANGELOG updated
last, so that 1.10.0 releases consistently.

#### Acceptance Criteria

1. THE version triple (`VERSION`, `pyproject.toml`, newest CHANGELOG heading),
   `powers/rule-engine-artifacts/plugin.json`, the bootstrap pin, and the
   SessionStart hook SHALL all read `1.10.0`.
2. THE CHANGELOG SHALL carry a `## [1.10.0]` section describing items A–I.
3. THE version-triple, version-pin, and bootstrap-payload-sync guards SHALL pass.
