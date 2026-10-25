# Requirements Document — Diagram UX & Native-Skin (1.11.0)

## Introduction

Release 1.11.0 is a diagram **presentation and authoring-experience** release. The
engine is geometrically mature (routing, compaction, crossing-aware placement);
this release improves how diagrams *read* and how a user *drives* generation,
without changing the coordinate-free geometry engine.

It groups seven workstreams synthesised from a per-theme code analysis
(2026-10-22). Each workstream is independently shippable and every default is
OFF, so the shipped golden corpus stays byte-identical until a builder opts in.

Primary capabilities delivered:

- A default-off **presentation skin** (furniture border colour, edge colour,
  numeric-marker badge) that changes only style channels and furniture, never
  coordinates (WS1).
- **Logical groups in flow diagrams** plus a choice of where the step
  description and legend live — in-canvas box, companion document, or a
  furniture panel (WS2).
- **Hybrid diagrams**: a foreign-profile sub-block (for example a Kubernetes
  deployment) nested inside a native cloud boundary (WS3).
- **C4 as a style mode** (Context + Container) layered on the existing
  `flow` geometry, not a new geometry class (WS4).
- A **clarify gate**: before generation the engine surfaces assumptions and
  either asks or records them under an explicit policy (WS5).
- A first-class **`network` diagram type** with its own rule profile (WS6);
  an **`access` diagram type** is specified for the following release (WS7).

## Glossary

- **Skin**: A presentation-only value object carrying style-channel choices
  (furniture border, edge colour, marker badge). It never carries geometry.
- **Furniture**: Non-diagram cells — the Flow box, the Legend box, the title,
  and (WS2) an optional description panel.
- **Marker badge**: The visual form of a numbered flow marker — a member of
  `none | circle | square`. `none` is the current inline bold text.
- **Flow group**: A named light-grey box drawn around a declared subset of flow
  nodes. Declared as `{label, members[]}`; never auto-applied.
- **flow_steps**: Where a flow diagram's numbered step descriptions render — a
  member of `box | document | panel`.
- **Hybrid diagram**: A single diagram whose primary provider is one profile and
  which nests a sub-block styled by a different provider profile.
- **C4 style mode**: A renderer that draws nodes as `box + "[Container: X]"`
  labels with dashed relationship labels and no provider icons, selected by
  `style=c4`; the geometry class remains `flow`.
- **Clarify gate**: A pre-generation pass that scans a spec for uncertainties
  and, by policy, asks the user or records each assumption.
- **Assumption**: A typed record `{kind, target_id, question, default, rationale}`
  describing one uncertainty the engine resolved by a default.
- **Diagram type profile**: A data-defined bundle `{base_class, node_cap, axis,
  allowed_roles, special_containers, lint_profile}` selected by `diagram_type`.
- **Byte-inert**: A change under which `scripts/regen_examples.py --check`
  reports every shipped golden `.drawio` byte-identical.
- **Core role invariant**: `constants.RESOURCE_TYPES` is exactly 16 values
  (9 neutral + 7 presentation), asserted by `tests/test_resource_types.py`.
  New roles added by this release are **extended** roles only.

## Requirements

### Requirement 1: Presentation skin (WS1)

**User Story:** As a diagram author, I want to restyle furniture borders, edge
colour, and numeric markers, so that a diagram can read closer to a vendor
reference style without re-placing any node or edge.

#### Acceptance Criteria

1. THE Skin value object SHALL carry the fields `furniture_stroke`
   (`black | light | brand | none`, default `black`), `edge_stroke`
   (optional colour, default unset), and `marker_badge`
   (`none | circle | square`, default `none`).
2. WHERE a diagram declares no Skin, THE engine SHALL emit the exact byte
   sequence the engine emits at release 1.10.12 for furniture, edges, and
   markers.
3. WHERE `furniture_stroke` is `black` and `edge_stroke` is unset and
   `marker_badge` is `none`, THE engine SHALL leave every shipped golden
   `.drawio` byte-identical under `scripts/regen_examples.py --check`.
4. WHERE `marker_badge` is `circle`, THE engine SHALL render each numbered
   marker as a filled black circle with a white numeral placed beside the edge,
   not as inline text on the edge line.
5. THE engine SHALL NOT change any node or edge coordinate as a result of any
   `furniture_stroke` or `edge_stroke` value.
6. IF `marker_badge` is `circle` or `square`, THEN THE engine SHALL re-evaluate
   `marker-label-collision`, `marker-collision`, and the marker-hygiene pass
   against the badge box rather than the edge midpoint.
7. THE engine SHALL NOT change provider boundary styles (AWS Account, Azure
   Subscription, GCP Project, OCI Compartment) as part of any Skin value.

### Requirement 2: Flow groups and description placement (WS2)

**User Story:** As a diagram author, I want to box logical groups in a flow
diagram and choose where the step descriptions live, so that a dense flow reads
like a sectioned reference diagram and the canvas stays within the raster
budget.

#### Acceptance Criteria

1. THE DiagramSpec SHALL accept an optional `flow_groups` field, a tuple of
   `{label, members[]}`, default empty.
2. WHERE `flow_groups` is empty, THE engine SHALL leave every shipped golden
   `.drawio` byte-identical.
3. WHERE `flow_groups` is non-empty, THE engine SHALL draw one light-grey group
   box enclosing the named members plus a caption band, without moving any
   member node.
4. THE engine SHALL NOT infer or auto-apply flow groups; a group SHALL exist
   only when a spec declares it.
5. THE engine SHALL provide an advisory command that proposes a draft
   `flow_groups` list from adjacency, printing it for the author to confirm,
   and SHALL NOT write it into a spec automatically.
6. THE DiagramSpec SHALL accept a `flow_steps` field (`box | document | panel`,
   default `box`).
7. WHERE `flow_steps` is `document`, THE engine SHALL omit the in-canvas Flow
   box and SHALL write the numbered steps into the companion `.diagram.md`.
8. WHERE `flow_steps` is `panel`, THE engine SHALL render the steps in a
   full-height grey furniture strip and SHALL place that strip below the body
   for a `left-right` flow so the flow raster budget of 1600 px width holds.
9. THE engine SHALL NOT target an A4 page aspect within the layout stage; any
   paper-aspect target SHALL be applied only in the raster export stage.

### Requirement 3: Hybrid diagrams (WS3)

**User Story:** As a diagram author, I want to nest a Kubernetes deployment
block inside an AWS VPC in one diagram, so that a deployment view does not need
a separate diagram.

#### Acceptance Criteria

1. THE NodeSpec and ContainerSpec SHALL accept an optional `provider` field,
   default unset, naming a profile; the field SHALL NOT carry geometry.
2. WHERE a container or node sets no `provider`, THE engine SHALL resolve its
   style and icon against the diagram's primary provider exactly as at release
   1.10.12.
3. WHERE a container sets a `provider`, THE engine SHALL resolve that container
   and its member nodes against the named profile's icon and style mappings.
4. THE engine SHALL allow a leaf boundary of a foreign profile to nest inside a
   `network_boundary` or `vpc` of the primary profile.
5. WHILE a hybrid diagram's class is `flow`, THE engine SHALL render the foreign
   sub-block as one collapsed boundary with a count caption and no member nodes.
6. WHILE a hybrid diagram's class is `landscape`, THE engine SHALL render the
   foreign sub-block's full nested tree.
7. THE linter SHALL judge each container's style against the provider its spec
   declared, falling back to the title token when no container provider is set.
8. WHERE no container declares a foreign `provider`, THE engine SHALL leave
   every shipped golden `.drawio` byte-identical.
9. WHERE a managed orchestration service is rendered in its own provider's
   diagram (EKS in AWS, AKS in Azure, GKE in GCP, OKE in OCI), THE engine SHALL
   render it with that provider's brand icon and colours.
10. WHERE a Kubernetes cluster is rendered outside its managing cloud,
    self-hosted, or on a foreign cloud, THE engine SHALL render it in
    Kubernetes blue `#326CE5`.

### Requirement 4: C4 style mode (WS4)

**User Story:** As an architect, I want Context and Container C4 diagrams, so
that I can present a system at the top C4 levels using C4 grammar rather than
cloud icons.

#### Acceptance Criteria

1. THE engine SHALL accept `c4-context` and `c4-container` as `diagram_type`
   values, each mapping to the `flow` geometry class.
2. THE engine SHALL accept a `style` selector (`icon | c4`, default `icon`).
3. WHERE `style` is `c4`, THE engine SHALL render each node as a box carrying a
   `"<name> [Container: <tech>]"` label and no provider icon, and SHALL render
   each relationship with a dashed labelled edge.
4. WHERE `style` is `icon`, THE engine SHALL render exactly as at release
   1.10.12.
5. THE engine SHALL NOT introduce a third enforced `diagram_class`; C4 SHALL
   remain a style mode over the `flow` class.
6. WHERE `diagram_type` is `c4-context` or `c4-container`, THE linter SHALL
   suppress provider-icon rules (`icon-resolved`, `verify-icon`, reconcile) for
   that diagram.
7. WHERE no diagram selects `style=c4`, THE engine SHALL leave every shipped
   golden `.drawio` byte-identical.

### Requirement 5: Clarify gate (WS5)

**User Story:** As a diagram author, I want the engine to surface its
assumptions before it draws, so that I can correct an imprecise spec or
knowingly accept the defaults with a recorded trail.

#### Acceptance Criteria

1. THE clarify gate SHALL scan a DiagramSpec and return a list of typed
   Assumptions for unresolved roles, missing boundary membership, ambiguous edge
   kinds, and guessed flow direction.
2. THE engine SHALL accept an `assume` policy (`ask | auto | error`, default
   `auto`).
3. WHEN the policy is `ask` and at least one Assumption exists, THE engine SHALL
   halt before drawing and return the Assumption list and no artifact.
4. WHEN the policy is `auto`, THE engine SHALL apply each Assumption's default,
   draw the diagram, and record every applied Assumption in the companion
   `.diagram.md`.
5. WHEN the policy is `error` and at least one Assumption exists, THE engine
   SHALL fail the build.
6. WHERE a spec is fully specified, THE clarify gate SHALL return an empty list
   and SHALL leave the drawn `.drawio` byte-identical to the no-gate result.
7. THE engine SHALL record applied Assumptions as a structured companion block,
   not as free-text inside the Legend.

### Requirement 6: `network` diagram type (WS6)

**User Story:** As a cloud architect, I want a dedicated network diagram type
with its own rules, so that TGW, peering, IGW, NAT, and security groups read as
a network, not as a data-flow.

#### Acceptance Criteria

1. THE engine SHALL read a data-defined diagram-type profile for `network`
   carrying `base_class`, `node_cap`, `axis`, `allowed_roles`,
   `special_containers`, and `lint_profile`.
2. THE engine SHALL provide the extended roles `transit_gateway`,
   `vpn_gateway`, `direct_connect`, `route_table`, and `network_firewall`
   resolving to a per-provider icon, each an extended role only.
3. THE engine SHALL add `security_group` as a container kind rendered as a leaf
   boundary whose member nodes nest directly inside it.
4. THE engine SHALL NOT add any new value to `constants.RESOURCE_TYPES`; the
   core role invariant of 16 values SHALL hold.
5. WHERE no diagram declares `diagram_type: network`, THE engine SHALL leave
   every shipped golden `.drawio` byte-identical.
6. THE engine SHALL ship one `network` golden pair (a `landscape` as-built and
   its `flow` summary) under `examples/`.

### Requirement 7: `access` diagram type (WS7, following release)

**User Story:** As a security reviewer, I want an access diagram that aggregates
principals, policies, and resources, so that a 40-plus-role account reads as a
small principal-to-resource graph, not an exploded mesh.

#### Acceptance Criteria

1. THE engine SHALL read a data-defined diagram-type profile for `access`
   carrying a mandatory aggregation key and a node cap.
2. THE engine SHALL provide extended roles `principal`, `policy`, `resource`,
   and `trust_boundary`, each resolving to a per-provider icon.
3. WHEN an access diagram's un-aggregated principal, policy, or resource count
   exceeds the profile cap, THE linter SHALL raise an aggregation finding.
4. THE engine SHALL render an access diagram as a `principal -> policy ->
   resource` left-to-right flow.
5. WHERE no diagram declares `diagram_type: access`, THE engine SHALL leave
   every shipped golden `.drawio` byte-identical.

### Requirement 8: `dataflow` diagram type for audits (WS8, third release)

**User Story:** As an auditor, I want a data-flow diagram that shows where data
lives and moves, what is classified as PII, and where data boundaries and
encryption sit, so that a GDPR/WAFR review reads the data posture at a glance.

#### Acceptance Criteria

1. THE engine SHALL read a data-defined diagram-type profile for `dataflow`.
2. THE linter SHALL apply the existing `ip-range` rule plus a new
   `data-classification` rule to a `dataflow` diagram.
3. WHEN a data store carrying PII is drawn without a classification marker,
   THE `data-classification` rule SHALL raise a finding.
4. WHERE no diagram declares `diagram_type: dataflow`, THE engine SHALL leave
   every shipped golden `.drawio` byte-identical.
5. THE `dataflow` type SHALL ship as a separate release after `network`.

### Requirement 9: Icon coverage (WS9 role fill-in + WS10 render→index bridge)

**User Story:** As a diagram author, I want common cloud services to render with
their official icon instead of failing generation, so that a diagram of a real
account does not hit a hard error for an un-mapped but entirely standard service.

#### Background (audited 2026-10-22, all four cloud profiles)

The generation path reads only `mappings/<provider>-icons.yaml` via
`icon_resolver.resolve_icon`. A role with no entry there raises
`UnresolvedTypeError` which `draw_cli._skin_renderers` converts to a hard
`DrawError` — there is no neutral-box fallback. `roles.yaml`, the committed
`icon-index.json`, and `asset_index.resolve_asset` all carry far more coverage
than the render path consumes, but the render path consults none of them.
Render-reachable service roles vs indexed pack slugs: AWS ~62 of 1133 (9 common
gaps), Azure ~10 of 637 (17 gaps), GCP ~9 of 45 (16 gaps), OCI ~10 of 218
(13 gaps). Every gap's official icon already exists in the indexed pack.

#### Acceptance Criteria

1. THE engine SHALL render each of the audited common services (AWS 9, Azure 17,
   GCP 16, OCI 13) with that provider's official icon, not a `DrawError`.
2. THE WS9 additions SHALL be data-only: a `roles.yaml` query plus a
   `<provider>-icons.yaml` `resources:` entry pointing at an already-indexed
   pack asset, adding no new value to `constants.RESOURCE_TYPES`.
3. WHERE a WS9 role is added but no diagram references it, THE engine SHALL
   leave every shipped golden `.drawio` byte-identical.
4. THE engine SHALL honour each provider's pack idiosyncrasy: Azure roles
   reference the built-in `azure2` image shapes; GCP roles follow product-first
   then category-fallback and SHALL NOT substitute a look-alike product glyph
   where none exists; OCI roles reference an embedded stencil slug present in
   `oci-stencil-digests.json`.
5. WHERE the WS10 render→index bridge is present and a role has no
   `<provider>-icons.yaml` entry, THE engine SHALL resolve the service name
   against the committed full-pack index and synthesise an official
   file-path style before raising `UnresolvedTypeError`.
6. WHERE the WS10 bridge resolves an icon, THE engine SHALL match the service
   name exactly and SHALL NOT substitute a look-alike (Icon Fidelity).
7. THE WS10 bridge SHALL ship as a separate release after WS9; WS9 SHALL be
   shippable in 1.11.0 with no code change.
