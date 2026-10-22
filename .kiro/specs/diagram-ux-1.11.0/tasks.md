# Implementation Plan: Diagram UX & Native-Skin (1.11.0)

## Overview

Python, in `src/rule_engine/`. Build sequence is ordered by cost and
blast radius: the cheap byte-inert style channels first, then the
authoring-experience features, then the two new diagram types one per release.
Every workstream proves byte-inertness with `scripts/regen_examples.py --check`
plus `scripts/canvas_metrics.py` before it is considered done, and re-exports
any changed golden's `.png` (the raster-provenance gate blocks a stale PNG even
when `regen --check` is green). Test sub-tasks marked `*` are required for a
workstream to ship; property tests name the design property they validate.

## Tasks

- [x] 1. WS1 — Skin value object and style channels (cheap, byte-inert)
  - [x] 1.1 Add the frozen `Skin` dataclass and `DiagramSpec.skin` with
    byte-inert defaults in `layout/model.py`.
    - _Requirements: 1.1, 1.2_
    - _Done: `31e6f89`._
  - [x] 1.2 Thread `skin` through `layout()` into `build_diagram`; give
    `text_cell`/`title_cell` a furniture-style override and `edge_cell` an
    optional `strokeColor`; default path emits the original literals verbatim.
    - _Requirements: 1.2, 1.5, 1.7_
    - _Done: `31e6f89`._
  - [x] 1.3 *Property test — skin defaults byte-inert
    - **Property 1: skin defaults are byte-inert**
    - **Validates: Requirements 1.2, 1.3**
  - [x] 1.4 *Property test — style channels never move geometry
    - **Property 2: style channels never move geometry**
    - **Validates: Requirement 1.5**

- [x] 2. WS1 — marker badge (geometry feature, own goldens)
  - [x] 2.1 Add a `circle`/`square` badge renderer (cell beside the arrow,
    black fill + white numeral) in `diagram_layout.py`.
    - _Requirements: 1.1, 1.4_
    - _Done: `5ed03f2` (badge `#1A1A1A` fill + white numeral, owner decision)._
  - [x] 2.2 Re-point `marker-label-collision`, `marker-collision`, and the
    marker-hygiene pass at the badge box instead of the edge midpoint.
    - _Requirements: 1.6_
    - _Done: `5ed03f2`._
  - [x] 2.3 Add one opt-in golden exercising `marker_badge="circle"`; confirm
    all other goldens byte-inert with `marker_badge="none"`.
    - _Requirements: 1.4, 1.6_
    - _Partial: byte-inert with `marker_badge="none"` proven on all goldens; the
      opt-in circle golden is deferred (raster export unavailable in the
      sandbox)._

- [x] 3. WS5 — clarify gate (improves trust across every workstream)
  - [x] 3.1 Add `layout/clarify.py`: `UncertaintyKind`, `Assumption`,
    `scan_uncertainties`, `ClarifyRequired`.
    - _Requirements: 5.1_
    - _Done: `807ce44`._
  - [x] 3.2 Hook `clarify_gate(spec, mode, sink)` at the top of `layout()`
    before `_annotate_edge_regions`; implement `ask | auto | error`.
    - _Requirements: 5.2, 5.3, 5.4, 5.5_
    - _Done with a deliberate deviation (`807ce44`): the gate is hooked in
      `draw_cli` AFTER `spec_from_snapshot` and OUTSIDE `layout()`, so it never
      mutates the deterministic hot-path and `.drawio` stays byte-identical
      under every policy. `ask`/`auto`/`error` all implemented._
  - [x] 3.3 Record applied assumptions as a `recorded_assumptions:` frontmatter
    key plus a `## Assumptions` body section in the companion writer.
    - _Requirements: 5.4, 5.7_
    - _Done: the `## Assumptions` body section and the `recorded_assumptions:`
      frontmatter key (one `kind:target` entry per applied assumption) are both
      emitted by `build_companion`, non-empty-only so a fully-specified spec is
      byte-identical, and the extra key passes the kb-frontmatter contract._
  - [x] 3.4 Add `--assume {ask,auto,error}` (default `auto`) to `draw_cli.py`,
    threaded like `--legacy`.
    - _Requirements: 5.2_
    - _Done: `807ce44`._
  - [x] 3.5 *Property test — fully specified spec yields no assumptions
    - **Property 7: a fully specified spec yields no assumptions**
    - **Validates: Requirement 5.6**

- [ ] 4. WS2 — flow groups and description placement
  - [x] 4.1 Add `DiagramSpec.flow_groups` and `flow_steps` with byte-inert
    defaults; validate at the `layout()` entry (mirror `resolve_spacing`).
    - _Requirements: 2.1, 2.6_
    - _Done: `8742c0d`._
  - [x] 4.2 Add the scoped `_box_flow_groups` pass (grey box around declared
    members); do not touch `_wrap_external_bands`.
    - _Requirements: 2.3, 2.4_
    - _Done: `flow_group_cells`, drawn behind nodes, no node shift (`8742c0d`)._
  - [x] 4.3 `flow_steps="document"`: suppress the in-canvas Flow box and emit a
    `## Flow` section in the companion.
    - _Requirements: 2.7_
    - _Done: `85c04de` (Flow box suppressed, Legend takes the top slot)._
  - [x] 4.4 `flow_steps="panel"`: furniture strip, bottom-preferred for
    `left-right`; A4 soft target in `export_raster.compute_scale` only.
    - _Requirements: 2.8, 2.9_
    - _Done: `panel` draws the Flow box as a full-height furniture strip down the
      right margin (presentation only, no node shift; `box`/`document`
      byte-identical; unknown value rejected fail-honest). `--paper a4` adds an
      A4 soft target to `compute_scale` that never inflates, never drops below
      the floor, and never overrides the raster budget._
  - [x] 4.5 Add `rule-engine-advise flow-groups` proposer (prints a draft,
    writes nothing).
    - _Requirements: 2.5_
    - _Done: `rule-engine-advise --flow-groups` clusters same-lane consecutive
      slots (cap 4), prints a draft, writes nothing (`85c04de`)._
  - [x] 4.6 *Property test — empty flow_groups byte-inert
    - **Property 3: empty flow_groups is byte-inert**
    - **Validates: Requirement 2.2**
  - [x] 4.7 *Property test — panel keeps the flow raster budget
    - **Property 4: panel keeps the flow raster budget**
    - **Validates: Requirements 2.8, 2.9**
    - _Done: A4 soft target is budget-subordinate (budget + floor always win);
      tests cover small (no inflate) / medium (pulled to A4) / over-budget
      (floor clamp) / default-unchanged._

- [ ] 5. WS3 — hybrid diagrams
  - [x] 5.1 Add `NodeSpec.provider` / `ContainerSpec.provider` (optional,
    default unset) and accept a foreign leaf boundary parented to a
    `vpc`/`network_boundary` in `_validate_spec`.
    - _Requirements: 3.1, 3.4_
    - _Done: `provider` field on both specs, default `None`, byte-inert
      (`c371425`); `_validate_spec` now explicitly accepts a foreign leaf
      (`namespace`/`security_group`) parented to a cluster envelope or a
      region-network container (`vpc`/`network_boundary`/`subnet`/`az`) in its
      own region, fail-honest on unknown/mis-kinded/wrong-region parent; native
      k8s `cluster ⊃ namespace` preserved (account host exempt from region
      match); `parent=None` sibling leaf unchanged._
  - [x] 5.2 Make `_skin_renderers` / `_boundaries_from` / `_container_style`
    resolve each cell under `cell.provider or primary`.
    - _Requirements: 3.2, 3.3_
    - _Done: `_skin_renderers` per-node provider-aware (`c371425`);
      `_boundaries_from` resolves each container under `container.provider or
      primary` (owner rule: provider brand vs Kubernetes-blue `#326CE5`,
      data-driven via `resolve_container`)._
  - [ ] 5.3 flow-collapse vs landscape-expand rule for the foreign sub-block.
    - _Requirements: 3.5, 3.6_
    - _Deferred. Owner rule closed: managed k8s in its own cloud ⇒ provider
      glyph; foreign/self-hosted ⇒ Kubernetes blue `#326CE5`._
  - [x] 5.4 Per-container provider in `_container_style_providers` with
    title-token fallback.
    - _Requirements: 3.7_
    - _Done: container-style lint recognises a foreign box by its shape
      signature and skips it, so a k8s-blue namespace in an aws-titled diagram is
      never falsely flagged (proven empirically — AWS boxes are `grIcon` groups,
      the k8s namespace is a plain dashed box, no signature collision)._
  - [ ] 5.5 Add an `examples/hybrid/` golden (AWS VPC with a nested k8s
    deployment block), flow + landscape; export raster.
    - _Requirements: 3.5, 3.6_
    - _Deferred (raster export unavailable in the sandbox)._
  - [x] 5.6 *Property test — unset provider byte-inert
    - **Property 5: unset provider is byte-inert**
    - **Validates: Requirement 3.8**

- [ ] 6. WS4 — C4 style mode
  - [x] 6.1 Add `c4-context`/`c4-container` diagram types (both map to `flow`)
    and a `--style icon|c4` selector.
    - _Requirements: 4.1, 4.2, 4.5_
    - _Done: `1149128` (types normalise onto flow geometry, `context` kept as a
      `c4-context` alias, `--style icon|c4` threaded through the CLI)._
  - [x] 6.2 Add the box renderer + dashed labelled edges under `style=c4`,
    reusing the `external_system` style string.
    - _Requirements: 4.3_
    - _Done: `_c4_box_renderer` (box + `[Container: role]`, no provider glyph)
      and dashed relationship arrows under `style=c4` (`_edges_from` forces
      `dashed` for C4). The engine is topological, so relationship prose stays in
      the Flow legend (numbered-marker convention), not a free-text edge label._
  - [x] 6.3 Write `_c4_container_spec` modelled on `_context_spec`.
    - _Requirements: 4.1_
    - _Done: `_c4_container_spec` — neutral boxes (no provider icon) nested in a
      single `vpc`-kind system boundary, external actors around them, capped at
      the flow budget; `c4-container` routes to it instead of `summary`._
  - [x] 6.4 Suppress provider-icon rules for C4 diagram types in the linter.
    - _Requirements: 4.6_
    - _Done: `_is_c4_diagram` gates `icon-resolved` and `container-style` off for
      `c4-context` / `c4-container`; non-C4 types byte-inert._
  - [ ] 6.5 Add a `c4-context` + `c4-container` golden (aws + cross-cloud);
    confirm `style=icon` byte-inert.
    - _Requirements: 4.4, 4.7_
    - _Partial: `style=icon` byte-inert proven; goldens deferred (raster)._
  - [x] 6.6 *Property test — C4 style off byte-inert
    - **Property 6: C4 style off is byte-inert**
    - **Validates: Requirement 4.7**

- [x] 7. WS6 — `network` diagram type (ships as its own release)
  - [x] 7.1 Add `mappings/diagram-types.yaml` and resolve a `TypeProfile` where
    `cli.py` reads `diagram_type`.
    - _Requirements: 6.1_
    - _Done: `diagram-types.yaml` (`network` profile) + `diagram_profiles.py`
      `TypeProfile` reader; `network` lint_profile wired into the linter's
      Network_Diagram recognition (`6d73206`)._
  - [x] 7.2 Add extended network roles (`transit_gateway`, `vpn_gateway`,
    `direct_connect`, `route_table`, `network_firewall`) to `roles.yaml`, the
    four icon mappings, and `ROLE_SCOPE`.
    - _Requirements: 6.2, 6.4_
    - _Done: 5 roles × 4 profiles (all 20 resolve), `roles.yaml` native types,
      icon-index rebuilt 68→73, `ROLE_SCOPE` network-scoped (`cd28dc8`,
      `a394477`)._
  - [x] 7.3 Add `security_group` to `CONTAINER_KINDS` as a leaf boundary + a
    per-provider container style.
    - _Requirements: 6.3_
    - _Done: `security_group` leaf-boundary kind + per-provider dashed-rect
      styles ×4 (`cd28dc8`, `a394477`)._
  - [ ] 7.4 Promote `08-network-crossaccount` into `examples/` and author its
    `flow` summary partner.
    - _Requirements: 6.6_
    - _Deferred: raster export is unavailable in the dev sandbox, so the golden
      pair cannot be authored/verified here. Code side (profile, roles,
      container, linter) is complete._
  - [x] 7.5 *Property test — core role invariant holds
    - **Property 8: the core role invariant holds**
    - **Validates: Requirement 6.4**
    - _Satisfied: `tests/test_resource_types.py` asserts `RESOURCE_TYPES` stays
      the 16-value set; the 5 network roles are extended-only._
  - [x] 7.6 *Property test — no diagram-type declaration byte-inert
    - **Property 9: no diagram-type declaration is byte-inert**
    - **Validates: Requirements 6.5, 7.5**
    - _Satisfied: `tests/test_diagram_profiles_1_11_0.py` — a non-network / empty
      `diagram_type` resolves to no profile and is byte-inert; `regen --check`
      clean, all 13 goldens byte-identical._

- [ ] 8. WS7 — `access` diagram type (following release)
  - [ ] 8.1 Add the `access` TypeProfile with a mandatory aggregation key and a
    node cap.
    - _Requirements: 7.1_
  - [ ] 8.2 Add extended roles `principal`, `policy`, `resource`,
    `trust_boundary`.
    - _Requirements: 7.2_
  - [ ] 8.3 Add the `access-aggregation` lint rule (class-aware severity).
    - _Requirements: 7.3_
  - [ ] 8.4 Render `principal -> policy -> resource` left-to-right; ship an
    access golden pair.
    - _Requirements: 7.4_

- [x] 9. WS9 — icon coverage, data-only role fill-in (ships in 1.11.0)
  - [x] 9.1 Add the 9 missing AWS roles (CloudTrail, ECS/Fargate, KMS, Kinesis,
    Athena, Glue, GuardDuty, Config, SageMaker) to `roles.yaml` +
    `aws-icons.yaml` pointing at the indexed pack files.
    - _Requirements: 9.1, 9.2_
    - _Done: `6fdce84`._
  - [x] 9.2 Add the 17 missing Azure roles referencing built-in `azure2` image
    shapes (VM, LB, App Gateway, Cosmos DB, Monitor, Firewall, API Management,
    ACR, Front Door, Entra, Log Analytics, Container Apps, Cognitive Services,
    Bastion, App Service, Event Hub, DNS/WAF/Cache/File).
    - _Requirements: 9.1, 9.2, 9.4_
    - _Done: `6fdce84`._
  - [x] 9.3 Add the 16 missing GCP roles, product-first then category-fallback,
    no look-alike where no product glyph exists (Apigee product; Compute/LB/CDN/
    DNS/IAM/Armor category; Spanner/BigQuery product).
    - _Requirements: 9.1, 9.2, 9.4_
    - _Done: `6fdce84`._
  - [x] 9.4 Add the 13 missing OCI roles via embedded stencil slugs verified in
    `oci-stencil-digests.json` (compute, mysql, load_balancer, api_gateway, iam,
    bastion, waf, monitoring, logging, data_science, block_volume, file_storage,
    container_registry).
    - _Requirements: 9.1, 9.2, 9.4_
    - _Done: `6fdce84`._
  - [x] 9.5 Run `rule-engine-build-icon-sets` to re-resolve the index; run
    `regen_examples.py --check` to prove every golden byte-inert.
    - _Requirements: 9.3_
    - _Done: `6fdce84` (index rebuilt; `--check` clean)._
  - [x] 9.6 *Property test — added roles byte-inert until used
    - **Property 10: added icon roles are byte-inert until used**
    - **Validates: Requirement 9.3**

- [ ] 10. WS10 — render→index bridge (separate release after WS9)
  - [ ] 10.1 Build the committed index with `full_packs=True` so the per-slug
    table ships for offline resolution.
    - _Requirements: 9.5_
  - [ ] 10.2 In `resolve_icon`, on `UnresolvedTypeError`, consult
    `asset_index.resolve_asset` (exact-name only) and synthesise an
    `image=<official file>` style; keep fail-honest when no exact match.
    - _Requirements: 9.5, 9.6_
  - [ ] 10.3 *Property test — bridge never substitutes a look-alike
    - **Property 11: the render→index bridge never substitutes a look-alike**
    - **Validates: Requirement 9.6**

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7"] },
    { "id": 4, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5", "6.6"] },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3", "7.4", "7.5", "7.6"] },
    { "id": 8, "tasks": ["9.1", "9.2", "9.3", "9.4", "9.5", "9.6"] },
    { "id": 9, "tasks": ["8.1", "8.2", "8.3", "8.4"] },
    { "id": 10, "tasks": ["10.1", "10.2", "10.3"] }
  ]
}
```

## Resolved owner decisions (2026-10-22)

- **WS1.** Marker badge accepted as a geometry feature with its own goldens
  (not under the byte-inert umbrella). Colours: `furniture_stroke=light` is
  `#B3B3B3`; `brand` is the per-provider boundary stroke; neutral `edge_stroke`
  is `#5A6B7B`; `marker_badge=circle` is `#1A1A1A` fill with a white numeral.
- **WS2.** A4 lives in the export stage, never layout. `flow_steps` corpus
  default stays `box`. Group proposer "adjacent" = same lane + consecutive
  slots; max group size 4 (larger ⇒ advise splitting the diagram).
- **WS3.** Per-container/node `provider` field (not a `foreign_block` kind).
  Flow-collapse caption `"<service> (×N <unit>)"`. **Hybrid sub-block
  icon/colour rule (closed):** a managed orchestration service in its OWN cloud
  renders with the provider brand icon and colours (EKS→AWS, AKS→Azure,
  GKE→GCP, OKE→OCI); a cluster OUTSIDE that cloud, self-hosted, or on a foreign
  cloud renders in Kubernetes blue `#326CE5`. This follows directly from the
  `provider` field: `provider=<cloud>` + `managed_k8s` role ⇒ provider glyph;
  `provider=kubernetes` ⇒ blue k8s. Hybrid title keeps the primary provider
  token; the lint style check judges per-container.
- **WS4.** C4 is a style mode over the `flow` class (not a new
  `diagram_class`). `context` stays as an accepted alias of `c4-context`. C4
  goldens this release cover `aws` + `cross-cloud` only.
- **WS5.** Default policy `auto` (keeps goldens byte-inert); CI runs
  `--assume error` on authored specs. Per-kind defaults: unresolved role →
  boundary-fallback; missing membership → geometric tier-band; guessed
  direction → keep declared order. The `contract.py` silent boundary-fallback
  is routed through the same gate (one owner of role-fallback).
- **WS6.** One class per release: `network` first, `access` second. TGW is a
  node (hub), not a boundary. `security_group` is a boundary-only kind (dashed
  rectangle, member nodes inside), no SG node glyph. Add `infrastructure` to
  the `diagram-standards.md` taxonomy table to match `linter.py:379`.
  `sequence` is out of scope (wrong paradigm for a topological engine).
- **WS8+ (new, `dataflow` type for audits — GDPR/WAFR).** A `dataflow` diagram
  type SHIPS AS A THIRD SEPARATE RELEASE after `network`: a lint profile over
  the existing `ip-range` rule plus a new `data-classification` rule (flag PII
  stores, data boundaries, encryption state). Confirmed in scope; sequenced
  after network, before/with access per audit urgency.
- **WS9/WS10 (icon coverage, audited 2026-10-22 across all 4 profiles).** The
  render path reads only `<provider>-icons.yaml` with no neutral fallback, so a
  common un-roled service hits a hard `DrawError`; ~55 common services across
  AWS/Azure/GCP/OCI are affected though every official icon is already indexed.
  WS9 (data-only extended roles, all 4 profiles, byte-inert) ships in 1.11.0.
  WS10 (render→index bridge, exact-name only, Icon Fidelity) ships as a
  separate release after WS9. The 16-value core role invariant is untouched.
