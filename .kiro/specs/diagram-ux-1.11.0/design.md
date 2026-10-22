# Design Document — Diagram UX & Native-Skin (1.11.0)

## Overview

This release adds a presentation/authoring layer on top of the coordinate-free
layout engine. No geometry algorithm changes. Every feature is gated by a
default-off field so the shipped corpus is byte-inert until a builder opts in,
proven by `scripts/regen_examples.py --check` plus `scripts/canvas_metrics.py`.

The design rests on three load-bearing findings from the 2026-10-22 code
analysis, each of which overturned an earlier assumption:

- **A numeric-marker badge is geometry, not style.** The marker is the edge
  cell's `value` (`diagram_layout.py:1016`), anchored at the edge midpoint
  (`geometry.py` `marker_anchor`). A circle beside the arrow is a new cell with
  its own box, so it is NOT byte-inert and must carry its own goldens and
  re-point `marker-label-collision` / `marker-collision` / the hygiene pass.
- **A4 belongs to export, not layout.** Layout is coordinate-free; the raster
  budget caps a `flow` at 1600 px (`raster_gate.py:82`) and
  `export_raster.compute_scale` (`export_raster.py:320`) fits over-budget
  canvases down to a 0.5 floor. A right-side A4 panel would widen a flow and can
  push it under the 0.5 floor into `CanvasTooWideError`. A4 is a soft export
  target; a `panel` on a `left-right` flow grows height (bottom strip), not
  width.
- **C4 is a style mode, not a new class.** `diagram_class` drives node-count and
  raster budgets and is whitelisted to `flow | landscape` at `cli.py:326`.
  C4-context/container are small `flow`-budget diagrams that differ only in
  visual grammar (box+label vs icon+caption) — exactly a style channel.

## Architecture

The engine keeps its three layers. This release touches only the declaration
layer (new optional fields) and the render/lint layer (new style channels and
type profiles). The placement/routing core (`layout/place.py`,
`layout/routers.py`, `layout/solver.py`) is untouched.

```
DiagramSpec (layout/model.py)        <- new optional fields: skin, flow_groups,
   |                                     flow_steps, NodeSpec.provider,
   |                                     ContainerSpec.provider
   v
clarify_gate (NEW layout/clarify.py) <- WS5: scan + ask/auto/error
   |
   v
layout()  (layout/pipeline.py)       <- UNCHANGED geometry
   |
   v
build_diagram (diagram_layout.py)    <- new style channels threaded to
   |                                     text_cell / edge_cell / title_cell /
   |                                     _boundary_style; WS2 _box_flow_groups
   v
.drawio  +  companion .diagram.md    <- WS2 document mode, WS5 recorded assumptions
   |
   v
export_raster (export_raster.py)     <- WS2 A4 soft target lives HERE, not layout
```

Diagram-type profiles (WS6/WS7) are data in a new `mappings/diagram-types.yaml`,
read where `cli.py:326` already reads `diagram_type`, and resolved into a
`TypeProfile` attached to the draw + lint context.

## Components and Interfaces

### Skin (WS1) — `layout/model.py`

- **Responsibility:** carry presentation-only style choices; never geometry.
- **Inputs:** `furniture_stroke`, `edge_stroke`, `marker_badge`.
- **Interface:** `Skin(furniture_stroke="black", edge_stroke=None, marker_badge="none")`,
  frozen dataclass; `DiagramSpec.skin: Skin = Skin()`.
- **Render wiring:** `text_cell`/`title_cell` gain an optional furniture-style
  override; `edge_cell` gains an optional `strokeColor`; defaults emit the
  original literal `_TEXT_STYLE` (`diagram_layout.py:128`) and the current
  no-stroke edge style verbatim. Do not round-trip through `_set_style_token`
  (`diagram_layout.py:737`) on the default path — token reordering breaks
  byte-identity.

### Flow groups + placement (WS2) — `layout/model.py`, `diagram_layout.py`, `contract.py`, `export_raster.py`

- **`flow_groups`:** `DiagramSpec.flow_groups: Tuple[FlowGroup, ...] = ()`. A
  new scoped pass `_box_flow_groups(placed, spec)` computes a bbox around named
  members plus a caption band and emits a grey group box; runs only when
  non-empty. Do NOT overload `_wrap_external_bands` (`layout/place.py:163`),
  which is for the external lane only.
- **Proposer:** a new advisory verb `rule-engine-advise flow-groups` (precedent
  `advise_cli.py:45`) clusters adjacent same-lane consecutive-slot steps and
  prints a draft; never writes a spec.
- **`flow_steps`:** `box` keeps the current path; `document` suppresses the
  in-canvas box and extends `contract._render_companion_doc` (`contract.py:637`)
  with a `## Flow` section; `panel` adds a furniture renderer beside
  `theme43_legend_placement` (`diagram_layout.py:1131`), bottom-preferred for
  `left-right`.
- **A4:** a soft target inside `export_raster.compute_scale`, never a layout
  constant.

### Hybrid provider override (WS3) — `layout/model.py`, `draw_cli.py`, `layout/place.py`, `linter.py`

- **Responsibility:** let one container + its children resolve against a foreign
  profile.
- **Interface:** `NodeSpec.provider: Optional[str] = None`,
  `ContainerSpec.provider: Optional[str] = None`.
- **Render wiring:** `_skin_renderers` / `_boundaries_from` / `_container_style`
  (`draw_cli.py:136,233,158`) resolve each cell under `cell.provider or primary`;
  the scalar-provider call shape stays the default.
- **Placement:** accept a leaf boundary parented to a `vpc`/`network_boundary`,
  reusing the namespace/peer_account sibling-leaf path (`place.py:564`).
- **Lint:** `_container_style_providers` (`linter.py:1308`) judges each container
  against its declared provider, title-token fallback for legacy.

### C4 style mode (WS4) — `draw.py`, `draw_cli.py`, `linter.py`

- **Responsibility:** render box+label C4 grammar over `flow` geometry.
- **Interface:** `diagram_type ∈ {c4-context, c4-container}` (both
  `_CLASS_OF -> flow`, `draw_cli.py:84`); `style ∈ {icon, c4}` default `icon`.
- **Render wiring:** `style=c4` swaps the node renderer for a box renderer reusing
  the sanctioned `external_system` style string (`aws-icons.yaml:325`) and emits
  dashed labelled edges. `_c4_container_spec` modelled on `_context_spec`
  (`draw.py:481`).
- **Lint:** new C4-scoped rules gate on `diagram_type`; provider-icon rules
  suppressed for C4 diagrams.

### Clarify gate (WS5) — new `layout/clarify.py`, `layout/pipeline.py`, `draw_cli.py`, `contract.py`

- **Responsibility:** surface and record spec uncertainties before draw.
- **Interface:** `scan_uncertainties(spec, *, provider, icon_index) ->
  tuple[Assumption,...]`; `clarify_gate(spec, mode, *, sink) -> DiagramSpec`
  called once at the top of `layout()` (`pipeline.py:1025`), before
  `_annotate_edge_regions`.
- **Policy:** `ask` raises `ClarifyRequired` with no artifact; `auto` applies
  defaults and appends to the companion sink; `error` fails the build.
- **Recording:** `recorded_assumptions:` frontmatter key plus a `## Assumptions`
  body section (`extra=` precedent at `contract.py:655`).

### Diagram-type profiles (WS6/WS7) — new `mappings/diagram-types.yaml`, `cli.py`, `roles.yaml`, `constants.py`, `linter.py`

- **Responsibility:** bundle per-type rules as data.
- **Interface:** a `TypeProfile{base_class, node_cap, axis, allowed_roles,
  special_containers, lint_profile}` resolved from `diagram_type` at `cli.py:326`.
- **network:** add extended roles `transit_gateway`, `vpn_gateway`,
  `direct_connect`, `route_table`, `network_firewall` to `roles.yaml` + the four
  icon mappings + `base.py:106 ROLE_SCOPE`; add `security_group` to
  `constants.CONTAINER_KINDS` (`constants.py:106`) as a leaf boundary; promote
  `tests/fixtures/sep/.../08-network-crossaccount` into `examples/` as the
  landscape golden plus a new `flow` summary partner.

### Icon coverage (WS9/WS10) — `roles.yaml`, `mappings/<provider>-icons.yaml`, `icon_resolver.py`, `asset_index.py`

- **Responsibility:** make common services renderable with their official icon.
- **WS9 (data-only, 1.11.0):** add the audited roles (AWS 9, Azure 17, GCP 16,
  OCI 13) as extended-role entries — a `roles.yaml` query plus a
  `<provider>-icons.yaml` `resources:` entry pointing at an already-indexed
  asset. No code, no change to `constants.RESOURCE_TYPES`.
- **WS10 (bridge, separate release):** on `UnresolvedTypeError` in
  `resolve_icon`, consult the committed full-pack index via
  `asset_index.resolve_asset` and synthesise an `image=<official file>` style;
  requires building the index with `full_packs=True`; exact-name match only
  (Icon Fidelity), never a look-alike.

## Data Models

### Skin
| `edge_stroke` | `Optional[str]` | hex; `None`(default) emits no `strokeColor` token |
| `marker_badge` | `str` | `none`(default) \| `circle` \| `square` |

### Assumption (WS5)

| Field | Type | Constraint / Notes |
| --- | --- | --- |
| `kind` | `UncertaintyKind` | `unresolved_role` \| `missing_membership` \| `ambiguous_edge_kind` \| `guessed_direction` |
| `target_id` | `str` | node id or edge id |
| `question` | `str` | owner-facing |
| `default` | `str` | what `auto` picks |
| `rationale` | `str` | why that default |

### TypeProfile (WS6/WS7)

| Field | Type | Constraint / Notes |
| --- | --- | --- |
| `base_class` | `str` | `flow` \| `landscape` |
| `node_cap` | `int` | per-type node-count cap |
| `axis` | `str` | `left-right` \| `north-south` |
| `allowed_roles` | `list[str]` | roles permitted for this type |
| `special_containers` | `list[str]` | e.g. `security_group` |
| `lint_profile` | `list[str]` | lint rule ids active for this type |

## Correctness Properties

**Property 1: skin defaults are byte-inert**

For every shipped golden spec `g`, rendering `g` with
`Skin(furniture_stroke="black", edge_stroke=None, marker_badge="none")` SHALL
produce a `.drawio` byte-identical to the 1.10.12 output of `g`.

**Validates: Requirements 1.2, 1.3**

**Property 2: style channels never move geometry**

For every spec `s` and every `furniture_stroke`/`edge_stroke` value `v`, the set
of node and edge coordinates in `render(s, v)` SHALL equal the set in
`render(s, default)`.

**Validates: Requirement 1.5**

**Property 3: empty flow_groups is byte-inert**

For every shipped golden spec `g`, rendering `g` with `flow_groups=()` SHALL
produce a `.drawio` byte-identical to the output with the field absent.

**Validates: Requirement 2.2**

**Property 4: panel keeps the flow raster budget**

For every `left-right` flow spec `s` rendered with `flow_steps="panel"`, the
exported raster width SHALL be ≤ 1600 px or the exporter SHALL fit it down
without falling below the 0.5 export-scale floor.

**Validates: Requirements 2.8, 2.9**

**Property 5: unset provider is byte-inert**

For every shipped golden spec `g` in which no node or container sets `provider`,
rendering `g` SHALL produce a `.drawio` byte-identical to the 1.10.12 output.

**Validates: Requirement 3.8**

**Property 6: C4 style off is byte-inert**

For every shipped golden spec `g` rendered with `style="icon"`, the output SHALL
be byte-identical to the 1.10.12 output of `g`.

**Validates: Requirement 4.7**

**Property 7: a fully specified spec yields no assumptions**

For every shipped golden spec `g`, `scan_uncertainties(g)` SHALL return the empty
tuple and the clarify gate SHALL leave the drawn `.drawio` byte-identical.

**Validates: Requirement 5.6**

**Property 8: the core role invariant holds**

After adding the WS6 network roles, `len(constants.RESOURCE_TYPES)` SHALL equal
16 and `tests/test_resource_types.py` SHALL pass.

**Validates: Requirement 6.4**

**Property 9: no diagram-type declaration is byte-inert**

For every shipped golden spec `g` that declares no `network` or `access`
`diagram_type`, rendering `g` SHALL produce a `.drawio` byte-identical to the
1.10.12 output.

**Validates: Requirements 6.5, 7.5**

**Property 10: added icon roles are byte-inert until used**

For every shipped golden spec `g`, after adding the WS9 extended roles, rendering
`g` SHALL produce a `.drawio` byte-identical to the 1.10.12 output, since no
golden references a new role.

**Validates: Requirement 9.3**

**Property 11: the render→index bridge never substitutes a look-alike**

For every service name `n` the WS10 bridge resolves, the resolved file SHALL be
the exact-name match for `n` in the committed index, or the bridge SHALL raise
`UnresolvedTypeError` rather than return a different icon.

**Validates: Requirement 9.6**
