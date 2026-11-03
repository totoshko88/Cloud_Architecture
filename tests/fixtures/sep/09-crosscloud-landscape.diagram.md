---
id: 09-crosscloud-landscape-v21
title: SEP cross-cloud — the whole SEP world as-built landscape
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-28
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-21
diagram_class: landscape
diagram_type: deployment
summary_of: 02-sep-summary
change_log:
  - date: 2026-10-28
    note: >-
      v21 — switched 09 to a hand-pinned build script reproducing the owner's
      manual VPC layout (compact se VPC box, Syndicate Server at its edge);
      coordinate-free solver could not reproduce it (see
      DIAGRAM-ENGINE-FEEDBACK-1.13.0.md).
  - date: 2026-10-28
    note: >-
      v20 — VPC-layout reproduction of the owner hand-placement
      (09-crosscloud-landscape копія), kept consistent with 03 v10.
      Coordinate-free (lane/slot/sub/container only, no x/y pin, no engine/
      mappings edit): the VPC-scoped nodes are grouped into ONE compact box with
      the same INTERNAL shape as 03 — strapi (col0) + rds (col1) on the top row,
      modular-cli (lower-left) on the bottom row, declared in the `data` lane at
      high slots with `sub` giving the two rows; strapi adjacent-left of rds so
      strapi→RDS (e29) is a short forward write entering RDS's left face
      (distinct from lambda→RDS e12 which enters the top). The owner's reference
      additionally draws the Syndicate Server INSIDE the VPC box at its top-right
      so its outbound edges exit right/up. That move was attempted through spec
      (syndicate into boundary-vpc-a, data lane, both vpc_side="left" and
      "right"); on this DENSE cross-cloud canvas the engine places the VPC box
      left/low (or splits the regional columns on "right"), so the server's four
      external edges (e27/e20/e24/e25) rake UP across the account and the build
      BLOCKS with edge-routing (knee-through-apigw/eventbridge),
      container-padding and edge-crossing-excess ERRORs. Per the acceptable-
      partial-result clause the Syndicate Server therefore STAYS a regional node
      here (the only one of the four with real external edges), keeping 09
      publishable; the three edgeless/low-degree VPC nodes are the ones grouped.
      Crossings unchanged at 24/27. The residual (missing spec lever) is recorded
      in DIAGRAM-ENGINE-FEEDBACK-1.13.0.md. Markers, node set, captions,
      WAF/edge/global placement unchanged; the ecs/guardduty resolve_icon
      fallback kept. Title v19→v20; gates 0 ERROR/CRITICAL.
  - date: 2026-10-28
    note: >-
      v19 — Wave 13 consistency fix (03 ⇄ 09). ADDED the three SEP-account nodes
      09 was missing so its node set is identical to 03 (owner's model: 09 = an
      augmented 03): ECS strapi (role ecs, caption "ECS strapi (EC2->ECS
      migration)") inside the se VPC with the content-write edge e29 strapi→RDS;
      modular-cli (role compute_instance, "modular-cli (admin)") inside the VPC
      as overlay="supporting" (admin host, no edge); and GuardDuty (role
      guardduty, "GuardDuty") in the region as overlay="supporting" (1 detector,
      no edge). strapi sits LEFT of RDS (data a2/a3) so strapi→RDS is a clean
      forward hop entering RDS's left face (distinct from lambda→RDS which enters
      the top); modular-cli is on a VPC sub-row clear of corridors. A resolve_icon
      fallback (_style_for / _bundled_style, the 03/08/13 pattern) was added so
      `ecs` / `guardduty` resolve their real official icons from the bundled tree
      (the stale top-level mapping lacks them) — no mappings edit, no new role.
      The new ECS write path is Flow step 27 ("SEP internal data-flow cont.");
      markers stay contiguous 1..27. The Legend supporting line now also names
      modular-cli and GuardDuty. WAF stays global/edge, OUTSIDE the account box.
      ~29 drawn nodes (node-count landscape WARNING only). Title v18→v19; updated
      2026-10-28. Coordinate-free — spec-only change, engine placed. Gates 0
      ERROR/CRITICAL, 29 icons 0 unresolved.
  - date: 2026-10-28
    note: >-
      v18 — Wave 12 (owner message index 3). Added the global AWS WAF web ACL
      syndicate_education_cloudfront_waf as a node in the ingress/edge band
      (ext-ingress sibling box, actors lane, OUTSIDE the SEP account / region /
      VPC — WAF is a GLOBAL/edge service and is never drawn inside the
      eu-central-1 VPC/region). It resolves to the real AWS WAF service icon
      (role waf, bundled tree). New edge e28 (WAF -> CloudFront, marker 4,
      "protected-by") is a short forward hop within the edge band, so it adds no
      cross-band crossing. Markers renumbered to a CONTIGUOUS 1..26 (the WAF step
      takes 4; old markers 4..25 shift to 5..26); edge ids stay stable. The
      sandbox-cleanup framing was refined in the Flow (step 23) and the Legend to
      read "Nuke fleet = AWS Batch cleanup of sandbox accounts, driven by the
      Syndicate Server Education Extension (EE); SEP + Batch verify". Text/node
      change only; geometry re-laid-out by the engine. The .flow.md numbered list
      is re-synced 1:1. Title v17->v18; updated 2026-10-28.
  - date: 2026-10-23
    note: >-
      v16 — FEAT-003 (Syndicate Server two-component model). The in-account EC2
      Syndicate Server node caption now reads "Syndicate Server (Education
      Extension + Syndi)" so the reader knows one host carries two logical
      components (EE sandbox lifecycle = diagram 05, Syndi support = diagram 07).
      The EC2 is NOT split into two nodes and stays inside the SEP account. No
      queue direction changed — the SQS → Syndicate Server consume edge is
      inventory-consistent. Caption/wording only; geometry re-laid-out by the
      engine. The .flow.md numbered list is unchanged; its prose was re-synced.
      Title v15→v16.
  - date: 2026-10-15
    note: v4 — external world re-expressed as grouped peer_account sibling boundary containers; engine Theme 37 band-grid stacks them into a compact grid above the account (canvas-utilization 16pct wide-row to ~30pct), long cross-band edges 17/18 folded into the Flow legend.
  - date: 2026-10-17
    note: v5 — icon fidelity pass. The external Syndicate Server (an EC2 host) now uses the real EC2 icon and License Manager the new license_manager icon; both stay external. Students/Operators already use the User icon and the peer accounts the Organizations Account icon. DIAL AI, LMS, and the fleet abstractions stay neutral (no faithful asset).
  - date: 2026-10-17
    note: v6 — three more faithful icons. LMS now carries a mortarboard (education role), DIAL AI the owner-supplied EPAM DIAL brand mark (dial role), and the Sandbox-mgmt + Logging org the AWS Organizations SERVICE icon (organizations role, distinct from the single-account peer_account glyph). Only the genuine non-AWS clouds / fleet abstractions stay neutral. All regen8 icons preserved.
  - date: 2026-10-21
    note: v7 — regenerated on rule-engine 1.10.12 with three owner fixes. FIX 1 — License Manager (EPAM service, account 652063929809) now carries a vendor-neutral certificate glyph (license_neutral), not the AWS License Manager icon. FIX 2 — two missing Syndicate Server control edges added (e24 Syndicate Server provisions the sandbox fleet by reading SEP SQS; e25 Syndicate Server drives sandbox cleanup via the Nuke fleet), linking the previously disconnected sandbox cluster. FIX 3 — Sandbox fleets node now renders as a cloud enclosing the AWS/Azure/GCP marks (sandbox_multicloud composite). All other icons preserved.
  - date: 2026-10-21
    note: v8 — three cosmetic placement fixes, enabled by the engine G21 hang fix (rule-engine bounds auto-ordering caption finishing on dense landscapes; the v7 build had hung). MongoDB Atlas origin snapped to the grid; the Flow and Legend boxes widened and top-right aligned so the empty band below them is gone (canvas height 2437->2204px); added a Legend line stating the sandbox management plane is a SEPARATE AWS Organization o-j09uu9d646 (mgmt account 533267139808, 223 accounts), distinct from the SEP org o-zizyhj5jga.
  - date: 2026-10-22
    note: v9 — regenerated on rule-engine 1.11.0 pre-release. Native skin applied (grey edges #5A6B7B, light-grey Flow/Legend furniture #B3B3B3, dark #1A1A1A circle badge markers). WS2 flow_steps="document" is LIVE: the on-canvas Flow box is dropped and the Legend takes the top slot, so the numbered steps are carried in this companion rather than on the canvas. No flow_groups on 09. Added a ## Assumptions section from the WS5 clarify scan. Geometry otherwise unchanged (build 113s, within the 180s guard — no G21 regression).
  - date: 2026-10-22
    note: v10 — added the MISSING SQS -> Syndicate Server edge (e26, marker 26, dashed cross-region "Syndi consumes the SEP SQS lifecycle queues over peering") so the SEP SQS and the external Syndicate Server are no longer a logical break. The numbered Flow narrative is externalized to the dedicated plain-markdown file 09-crosscloud-landscape.flow.md (all steps 1..26, including the new step 26); the canvas keeps only the Legend (no Flow box). Build 172s, within the 180s guard (no G21 regression); no crossing-hard-cap regression.
  - date: 2026-10-23
    note: >-
      v11 — ITEM 3 + Task-4 (owner). The Syndicate Server is now drawn INSIDE the SEP
      account (870325637521) as an EC2 (compute_instance) control-plane node, confirmed
      by iam.json RoleName syndicate-server, so its edges to DIAL (20), License Manager
      (21), the SEP SQS (26), the sandbox fleets (24) and the Sandbox-mgmt org (25) now
      correctly cross OUT of the account boundary. Edge 25 was RE-POINTED from the Nuke
      fleet to the grey Sandbox-mgmt + Logging org box because the server drives the FULL
      sandbox account lifecycle (provision + cleanup), which also clears the marker-25
      overprint of the KTM EKS dev node. The deprecated EPM-CMTR (088595288622) and CICD
      (884218299410) dev / CI-CD peer accounts are REMOVED with their edges; the KTM EKS
      dev cluster (ED-KRSB 183631338639) is kept and stays connected via a real SEP path
      (KTM AWS Batch reaches the EKS student cluster development-dev over the public
      endpoint, marker 17). The externalized Flow steps 17/20/21/24/25 are re-synced.
      Engine (1.11.0 pre-release) correctness fix needed by the new topology — size_containers
      now sizes an external sibling band to the WIDER of its slot-pitch grid and its actual
      member extent, so a scored-spread band (the ingress row) always encloses its rightmost
      member (atlas); previously the member fell OUTSIDE its box, tripped container-padding
      against the account, and the repair loop grew the account into the external bands
      (container-overlap). Build 131s, within the 300s guard.
  - date: 2026-10-23
    note: >-
      v12 — wave-2 owner decision VARIANT 1. The single flat "KTM EKS dev
      (183631338639)" peer_account node is replaced by an ACCOUNT BOX captioned
      "ED-KRSB (183631338639)" containing a NESTED EKS cluster service node
      (managed_k8s, the real Amazon EKS icon) as a structural member; the word
      "dev" is dropped from the framing. Edge 17 (batch → the EKS cluster over
      the public endpoint) is re-wired to terminate on the nested EKS service
      node inside the ED-KRSB box. The box stays a disjoint external sibling
      OUTSIDE the SEP account. The externalized flow narrative
      09-crosscloud-landscape.flow.md step 17 is re-synced. Coordinate-free spec
      change only; build within the 300s guard. Title v11→v12.
  - date: 2026-10-23
    note: >-
      v13 — FEAT-002 ITEM F (owner: "25 повинен бути над, а не під боксом").
      Marker 25 (Syndicate Server → Sandbox-mgmt org) was rendering on the
      ext-sandbox container top border (the new marker-on-container-border
      rule). Spec levers (sub-row reorder) could not move it — the engine lays
      an external-lane band as one row and ignores sub there — so the fix is an
      ENGINE marker-placement pass (rule-engine 1.11.0, backlog G30): a Phase 3
      added to resolve_marker_collisions slides a marker along its OWN edge off
      any Boundary container border, accepting the first spot that also clears
      every other marker, foreign edge, node icon and caption. Marker 25's
      anchor moved from the container top (y=520) to y=554, clear of the border
      and above the Sandbox-mgmt box. Numbering unchanged, so the externalized
      flow narrative needs no renumber. Build 131s, within the 300s guard.
      Title v12→v13.
  - date: 2026-10-23
    note: >-
      v14 — FEAT-002 (owner messages 8 + 10). STRUCTURAL: MongoDB Atlas moved out
      of the Ingress & identity edge row into its OWN external sibling band
      "External datastore — MongoDB Atlas" (peer_account kind, outside the SEP
      account), keeping the mongodb_atlas green-leaf. A new single-headed edge e27
      (marker 17) draws the EC2 syndicate-server reading/writing the PRIMARY
      learner data in MongoDB Atlas (PROD_SEP_Server) over peering
      pcx-0e257b23d337fda0b (INVENTORY-STATE.md section 3); e16 (lambda→atlas) is
      kept, so both the Lambda app and the EC2 server show as Atlas readers/writers
      with no double-headed edge. FLOW-ACCURACY (owner step truths): e7 re-pointed
      sqs→batch to lambda→batch (Lambda submits Batch directly; Batch uses its own
      built-in job queue); e21 re-pointed lm→syndicate-server to lm→sqs
      (se-lm-synchronization-queue → se-management-api-handler, ESM 5fe731e5, no
      Syndicate relay); the DynamoDB node is marked overlay=supporting
      (CiTerraformStateLocks is a CI/Terraform state-lock, not a governance data
      path). Captions corrected for CloudFront (only se-ui-api 7cipwpsrx5),
      EventBridge (ACE-only) and SQS→Syndicate (local, no peering). Markers
      renumbered to a CONTIGUOUS 1..25 (VARIANT A): the retired 18/19 gap is gone,
      e27=17, old 17/20/21/22/23/24/25/26 shift to 18/19/20/21/22/23/24/25; edge
      ids stay stable. The externalized flow narrative
      09-crosscloud-landscape.flow.md is re-synced 1:1. Title v13→v14.
  - date: 2026-10-23
    note: >-
      v15 — seventh-wave sweep on rule-engine 1.11.0 (SYS-B / SYS-A). Rebuilt
      + re-exported. ENG-2 verify-after: marker 24 (Syndicate Server →
      Sandbox-mgmt org) routes ~280px clear of the DIAL box and trips no
      marker-* lint rule — no engine change needed. Owner 09 comments
      reconciled (Atlas in its own datastore band, server→Atlas edge present,
      12 down-left, 24 clear of DIAL). flow.md re-synced + gated. All gates 0
      ERROR/CRITICAL, 25 icons 0 unresolved. Title v14→v15.
  - date: 2026-10-23
    note: >-
      v17 — tenth-wave B6 (owner: "дві лінії вхід в монгу наклались; 16 пустити
      над SQS"). The two edges entering the external MongoDB Atlas box — e16
      (Lambda -> Atlas, marker 16) and e27 (syndicate-server -> Atlas, marker 17)
      — overlapped on the approach. e16's `cross-region` routing hint is dropped
      so the router classifies it as an ordinary long edge and gives it a
      DISTINCT corridor (above the SQS/async row) from e27's cross-region lane;
      the two now enter Atlas on separate approaches instead of merging. e27
      keeps its hint; both still render as labelled peering edges to Atlas, so
      the architecture is unchanged. Markers 16/17 unchanged (no renumber), so
      the externalized 09-crosscloud-landscape.flow.md stays 1:1. Gates 0
      ERROR/CRITICAL, 25 icons 0 unresolved. Title v16->v17.
tags:
  - aws
  - sep
  - cross-cloud
  - landscape
  - deployment
  - as-built
  - multi-account
  - multi-cloud
related_docs:
  - 02-sep-summary.diagram.md
  - 03-sep-account-landscape.diagram.md
  - 08-network-crossaccount.diagram.md
  - INVENTORY-STATE.md
---

# SEP cross-cloud — the whole SEP world as-built landscape

## Overview

This is the capstone as-built: the entire Syndicate Education Platform (SEP) world assembled on one wall so a reviewer sees every account, cloud, and fleet and how they relate at once. It is the detailed landscape companion to the `02-sep-summary` flow summary, which carries the request-path shape; this diagram carries the full system inventory. The external world is grouped into labelled sibling boundary containers — the ingress and identity edge (CloudFront with the global AWS WAF that protects it, and Route 53), the MongoDB Atlas datastore, the kept AWS peer account, identity, external integrations, and the sandbox-management cleanup fleet as out-of-WAFR-scope context. The Syndicate Server is the SEP control plane, drawn inside the account. The layout engine stacks those groups into a compact grid above the SEP production AWS account `870325637521`, which hangs below as the one fully nested core. Every node and edge is derived from the live read-only inventory in `INVENTORY-STATE.md`, never invented. Dense families collapse to one captioned node each — one Lambda for 13 functions, one SQS for 14 queues. The on-canvas Flow box is dropped; the full numbered data flow lives in `09-crosscloud-landscape.flow.md`.

## Main Content

The SEP core is the only fully nested boundary: Account `870325637521` contains Region `eu-central-1`, which contains the `se` VPC `vpc-05cd5663a70d3a65c` (192.168.128.0/20). Inside the VPC sit RDS `sep-strapi-pg`, the ECS strapi application (migrating off EC2) that writes to it (27), the Syndicate Server EC2 control plane, and the `modular-cli` admin host (a supporting node); the regional services — API Gateway, Lambda, SQS, EventBridge, AWS Batch, ECR, S3, DynamoDB, SSM+KMS, Bedrock, CloudWatch, and GuardDuty (supporting) — sit in the Region outside the VPC. MongoDB Atlas sits in its own external datastore band, read/written by both the Lambda app (17) and the EC2 Syndicate Server (18). Lambda submits AWS Batch jobs directly (8); DynamoDB `CiTerraformStateLocks` is a CI/Terraform state-lock, not a governance path (15). License Manager carries a vendor-neutral glyph and feeds the SEP SQS sync queue (21); the one kept AWS peer account is ED-KRSB `183631338639`. CloudFront is protected by the global AWS WAF `syndicate_education_cloudfront_waf` (4), in the edge band outside the account — never inside the VPC/region. The outer band holds the sandbox-management org, its nuke fleet (AWS Batch cleanup driven by the Syndicate Server Education Extension, with SEP plus Batch verifying, 23), central Logging, and the fleets it purges.

## Troubleshooting

If a route or caption reads wrong, fix the SCRIPT and never hand-edit the `.drawio`; the geometry is now HAND-PINNED (explicit x/y + edge contacts) in `.build-tools/build_09_crosscloud_landscape.py`, so adjust the pinned coordinates there and regenerate. The external groups stack into a grid above the account; a crowded external world grows sideways rather than into the account body. If two heavy cross-band edges push the diagram over the landscape crossing hard-cap, fold them into the Flow legend as one representative edge per external system. An over-connected node finding means one node carries more than three edges on a face — re-source the edge from the neighbour that owns the relationship. If an icon renders as an empty box, the role is missing from the mapping or its local overlay. A real AWS resource type keeps its service icon even when external (EC2 Syndicate Server, the org-level Organizations glyph), a known brand its own mark (DIAL, the LMS mortarboard). SEP's License Manager is an EPAM service, not AWS, so it wears a vendor-neutral certificate glyph; a non-AWS cloud never carries a fake AWS icon. The Flow box is dropped (`flow_steps="document"`); the empty on-canvas flow-legend is expected.

## Anti-patterns

Do not wire every system to every other system to prove the platform is connected: the engine caps a node at three edges per face, and a hairball hides the real data paths. Show only the genuine relationships the inventory proves, and keep the license-manager edge marked `draft-assumption` until owner question 9B Q1 resolves the LM-to-CMTR-to-SEP relay. Do not draw the external accounts, clouds, or fleets inside the SEP account boundary to avoid cross-boundary edges — an external datastore or a peer account drawn inside the VPC misrepresents the architecture. Do not substitute a look-alike AWS icon for Azure or GCP. A real AWS resource type keeps its true icon even when external — the Syndicate Server (EC2) and the org-level Organizations glyph wear their real service icons — and a known brand keeps its own mark: MongoDB Atlas its leaf, the DIAL proxy the owner-supplied DIAL logo, the LMS a mortarboard. But a non-AWS service is never given an AWS glyph: SEP's License Manager is an EPAM service, so it wears a vendor-neutral certificate mark, and the three-cloud sandbox fleet wears a composite cloud. Do not split this as-built into several twelve-node pages — a landscape exists to show the whole world at once; the paired `02-sep-summary` carries the simplified shape instead.

```python
# Regenerate the triple (hand-pinned geometry; never hand-edit the .drawio):
#   python3 .build-tools/build_09_crosscloud_landscape.py
#   rule-engine-export-raster 09-crosscloud-landscape.drawio
```

## Assumptions

- **unresolved_role** on `atlas`: applied default *boundary icon fallback* — the contract falls back to the enclosing boundary icon when a role does not resolve.
- **ambiguous_edge_kind** on `e1`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e20`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e22`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e23`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e3`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.
- **ambiguous_edge_kind** on `e4`: applied default *geometric classifier* — classify_edge derives the class from lane/region; with no region it defaults to the in-band class.

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system; this landscape names it via the `summary_of` cross-link so neither ships orphaned. The focused component views feed this assembly: `01-sep-context` for the external actors and systems, `03-sep-account-landscape` for the SEP account groupings and node naming, `04` through `07` for the request and lifecycle flows, and `08-network-crossaccount` for the VPC peerings and external accounts. The full numbered data flow for this landscape lives in the dedicated `09-crosscloud-landscape.flow.md` (steps 1..27, contiguous), since the on-canvas Flow box is dropped. The authoritative inventory behind every node and edge is `INVENTORY-STATE.md`, whose section 2 covers the SEP account, section 8 the cross-cloud relationships, and section 9B the open owner questions that may still reshape a few edges. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the service-scope classification, `diagram-standards.md` for nesting, padding, lane order, and edge routing, `diagram-lint.md` for the class-aware severities a landscape escalates, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
