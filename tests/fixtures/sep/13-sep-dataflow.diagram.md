---
id: 13-sep-dataflow-v9
title: SEP production — data flow, PII classification and encryption boundaries
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-29
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-23
diagram_class: landscape
diagram_type: dataflow
summary_of: 02-sep-summary
change_log:
  - date: 2026-10-29
    note: >-
      v9 FROZEN (hand-pinned) — the owner hand-routed the Lambda / Batch / ECS →
      data-store connections in the draw.io GUI to remove the dense-fan-out line
      overlaps the coordinate-free engine could not separate (collinear:2,
      confirmed by rule-engine-advise). To make the hand edits lint-clean and
      regenerate-proof, the se VPC boundary was removed (all data stores now sit
      in one regional column, so the regional stores no longer fall inside a VPC
      box — geometric-containment; owner decision "просто приберемо VPC"), every
      node was re-homed to its boundary with child-relative geometry, the dead
      "Inner boundary" legend line was dropped, and the edge contacts the GUI
      stripped were re-pinned (edge-float) keeping every hand-drawn waypoint. The
      coordinate-free builder is archived (build_13_sep_dataflow.py.ARCHIVED-
      coordinate-free); 13 is now a hand-pinned artifact and must not be
      regenerated from the builder. Lint [OK], 0 ERROR/CRITICAL. ECS caption kept
      as "ECS strapi-server" (no migration wording, per owner).
  - date: 2026-10-23
    note: v1 — new dataflow diagram (WS8 dataflow type) on rule-engine 1.11.0. Shows where SEP data lives and moves, PII classification, and encryption boundaries for a GDPR / WAFR review. Draft-assumptions (S3/DynamoDB encryption) clearly labelled in the Legend. Native skin (grey edges #5A6B7B, light furniture, circle badges).
  - date: 2026-10-23
    note: >-
      v2 — wave-2 owner review. DEFECT 6b: the external MongoDB Atlas
      encryption-boundary box is width-aligned to the SEP account box (shared
      left edge and right edge) so it no longer overlaps the right-side Legend;
      the Flow/Legend column is recomputed past the widened box. DEFECT 6a: the
      single external Atlas node is nudged to sit just left of the workers
      column, so the two edges that drop to it (e7 lambda→atlas, e9
      strapi→atlas, marker 9) route in the clear corridor just inside the
      account's left edge instead of riding ON the account box border. GDPR
      classification markers and draft-assumption legend lines are intact.
      Builder-side Boundary/furniture alignment (09 precedent); title v1→v2.
  - date: 2026-10-23
    note: >-
      v3 — FEAT-002 ITEM G (owner: "студент lms sep cf api gw і також напряму без
      lms"). The single flat ingress node is replaced by the real ingress
      topology: Learner → LMS → CloudFront → API Gateway → Lambda, PLUS a direct
      Learner → CloudFront path that bypasses the LMS (a learner opening the
      Syndicate UI directly rather than from a course). This fills the empty left
      of the canvas with the honest ingress chain. Markers renumbered in lockstep
      (now 12 steps). The builder-side Atlas node-position nudge and edge
      waypoint-clearing from v2 are dropped — the expanded ingress changed the
      layout and the 1.11.0 engine now places and routes the external Atlas node
      cleanly on its own (coordinate-free). The GDPR Atlas enc-at-rest-NONE
      finding, the PII/TLS classification markers, and the draft-assumption
      legend lines are all preserved. Title v2→v3.
  - date: 2026-10-23
    note: >-
      v4 — wave-4 ITEM 4 (owner: "3 може прямо пройти вниз", "не зрозуміло чому 7
      не просто пряма лінія"). Edge 7 (Lambda → RDS strapi-pg) is now a straight
      horizontal line: its exit and entry contacts already resolved to the same
      y (260), but the VPC data column sits 20px above the workers column so the
      engine classed it an upward fan-out-row and jogged up-across-down for
      nothing. A scoped rule-engine 1.11.0 router fix adds a level-run shortcut
      (route_spine + route_fan_out_row): when a right→left edge's contacts
      coincide in y and the direct run is obstacle-free, it draws one straight
      segment. Byte-inert on every shipped golden. Edge 3 (CloudFront → API
      Gateway) is DELIBERATELY NOT forced into a straight vertical drop: although
      API Gateway sits directly below CloudFront, a bottom-centre drop would cut
      through CloudFront's own caption band (diagram-standards Variant A), so the
      caption-safe side route is kept — forcing a vertical would strike the
      label. The GDPR Atlas finding, classification markers and draft-assumption
      legend are unchanged. Title v3→v4.
  - date: 2026-10-23
    note: >-
      v5 — sixth-wave flow-accuracy correction (owner steps 2/7). No edge change
      (e6 Lambda->Batch is already correct); flow marker 6 is tightened to
      "Lambda submits AWS Batch jobs directly; Batch uses its own built-in job
      queue" for consistency with 03/11/09. The Overview body names the one REST
      API CloudFront fronts, se-ui-api (7cipwpsrx5), where the ingress TLS path
      is described. The GDPR Atlas enc-at-rest-NONE finding, the PII/TLS
      classification markers and the draft-assumption legend lines are unchanged.
      Title v4->v5.
  - date: 2026-10-23
    note: >-
      v6 — seventh-wave SPEC-13 (owner 13 'API GW це регіональний сервіс тож
      він повинен бути в регіоні'). API Gateway moved INTO the region box via
      the per-node scope='regional' override (shared api_gateway role
      unchanged); CloudFront kept at the edge; the empty CloudFront→region gap
      closed; marker 3 reads as a straight-down drop (SYS-A). Side-effect of
      the apigw move: both Atlas-writing edges would merge on one top-entry of
      the canvas-left external Atlas box (entry-thirds ERROR); resolved by
      dropping one of the two edges' cross-region ROUTING hint so the
      convergence spreads onto distinct faces (same architecture asserted —
      both still render as labelled peering edges to Atlas). All gates 0
      ERROR/CRITICAL, 12 icons 0 unresolved. Title v5→v6.
  - date: 2026-10-23
    note: >-
      v7 — tenth-wave owner fixes. B2: Strapi and the Syndicate Server are two
      different EC2s; the Syndicate Server is the account-orchestration control
      plane and is NOT a dataflow participant here, so it is removed — the one
      EC2 node is relabelled "EC2 strapi-server" and its edge is retargeted from
      MongoDB Atlas to RDS sep-strapi-pg (marker 12, "Strapi content only" per
      INVENTORY-STATE). Atlas keeps exactly one writer in this view, the Lambda
      handlers (marker 10). ADD-2: marker 10 (Lambda -> Atlas) no longer takes
      the huge right-side hook past RDS; AWS Batch moved to its own column
      (platform lane) so the Lambda drop column is clear and e10 exits bottom
      and runs DOWN-then-LEFT to the bottom-left Atlas box (coordinate-free).
      Flow step 12 re-synced. All gates 0 ERROR/CRITICAL, 12 icons 0 unresolved.
      Title v6->v7.
  - date: 2026-10-28
    note: >-
      v9 — Wave 13 routing cleanup + WAF (owner 13: "багато зайвих перетинів",
      "10 може вийти ліворуч внизу і тоді не буде перетинів із 7", "варто
      додати WAF до Cloudfront"). Added a WAF node (role waf, "WAF (CloudFront)")
      at the GLOBAL edge fronting CloudFront with a WAF -> CloudFront edge, never
      inside the region/VPC — consistent with 01/02/03/09 and the real
      syndicate_education_cloudfront_waf web ACL. Flow markers renumbered
      contiguously 1..13. The Lambda -> MongoDB Atlas edge (e10) is declared
      ahead of the rightward store fan to bias a down-left route. Residual
      WARNINGs (edge-crossing-excess 5/13 driven by the heavy 5-way Lambda
      fan-out where Lambda->RDS climbs across the store edges, and the
      collinear:2 store-column approach, plus the e10/e7 crossing the owner
      flagged) are a 1.13.0 engine routing limitation reached via spec levers
      only — recorded in DIAGRAM-ENGINE-FEEDBACK-1.13.0.md; the WARNINGs do not
      block publication. Title v8->v9.
  - date: 2026-10-28
    note: >-
      v8 — Wave 12 Strapi-as-ECS change. The one Strapi content-server node has
      its role changed compute_instance -> ecs and its caption refined "EC2
      strapi-server" -> "ECS strapi-server (EC2->ECS migration)", reflecting the
      imminent EC2->ECS migration (the same factual change applied on 03/08/10).
      It stays in the se VPC private tier and its datastore edge e12 strapi ->
      RDS sep-strapi-pg is unchanged. The DynamoDB caption is refined to
      "DynamoDB CiTerraformStateLocks (Terraform state-lock; operational)" to
      name the real state-lock table. Flow step 12 re-synced to the ECS wording.
      No topology change otherwise. Title v7->v8.
tags:
  - aws
  - sep
  - dataflow
  - gdpr
  - pii
  - encryption
  - wafr
  - 870325637521
  - eu-central-1
related_docs:
  - 02-sep-summary.diagram.md
  - 03-sep-account-landscape.diagram.md
  - INVENTORY-STATE.md
---

# SEP production — data flow, PII classification and encryption boundaries

## Overview

This dataflow landscape is the data-protection view of the Syndicate Education Platform (SEP), drawn for a GDPR and AWS Well-Architected Security-pillar review. It answers where SEP data lives, how it moves, what is personal data (PII), and where encryption boundaries sit. Data flows left to right: a learner launches a task from the LMS (LTI) or opens the Syndicate UI directly, PII travels over TLS through CloudFront and the one REST API it fronts, se-ui-api (7cipwpsrx5), the Lambda handlers and AWS Batch jobs process it, and it comes to rest in the data stores — RDS, S3, DynamoDB, Secrets/SSM with KMS, and the external MongoDB Atlas clusters. Every data-store node carries a classification marker in its caption so an auditor can read the posture at a glance. Facts are taken from the read-only inventory (`storage.json`, `database.json`, `secrets.json`, and `INVENTORY-STATE.md` section 3 for Atlas); where the snapshot is silent on encryption, the node is clearly labelled as a draft-assumption rather than presented as a confirmed fact, and the Legend records each assumption with the verification it still needs.

## Main Content

The data stores and their posture: RDS `sep-strapi-pg` is `StorageEncrypted=True` (confirmed), holding Strapi content inside the `se` VPC; the Strapi content-server (drawn as ECS in the private tier) persists that content to RDS (the Syndicate Server is a separate account-orchestration EC2 and is not a dataflow participant here, so it is not drawn). MongoDB Atlas is the primary learner datastore and its one writer in this view is the Lambda handlers. Secrets Manager and SSM Parameter Store are KMS-encrypted (6 keys); the snapshot read metadata only, never secret values. The critical finding, confirmed from the Atlas inventory, is that MongoDB Atlas — which holds the primary SEP learner and CDM data across `PROD_SEP`, `PROD_SEP_Modular`, and `PROD_SEP_Server` — has encryption-at-rest NONE, so it is marked PII, confidential, and the NONE state is called out as the key data-protection gap. Two stores are draft-assumptions: the snapshot captured no per-bucket S3 encryption config and no DynamoDB `SSEDescription`, so S3 (25 buckets, PII in attachment/report buckets) and the DynamoDB `CiTerraformStateLocks` Terraform state-lock table are drawn `encrypted (draft — unverified)`, reflecting the AWS default while flagging that it is not yet confirmed. Data residency is EU: AWS `eu-central-1` and Atlas `EU_CENTRAL_1` (Frankfurt).

## Troubleshooting

The geometry is generated from the coordinate-free spec in `scripts/build_13_sep_dataflow.py`; never hand-edit the `.drawio`. If `data-classification` fires (an ERROR on this landscape), a node whose caption names PII carries no classification marker — add `encrypted`, `confidential`, `restricted`, or an equivalent token to that node's caption, matching the real posture. If `container-overlap` or `node-overlap` warns, the external Atlas box has drifted into the account band; keep the Atlas node in the `on-premises` lane so its encryption-boundary box stays a disjoint sibling outside the account. If `ip-range` warns, an on-diagram string carries a routable public address — this diagram deliberately names no host addresses. If the MongoDB Atlas icon renders as an empty box, the `mongodb_atlas` role is missing from the mappings. If the CloudFront to API Gateway edge takes a short side jog rather than a straight vertical drop, that is intentional: a bottom drop would cut CloudFront's own caption, so the caption-safe side route is kept. Re-run the lint, icon-verify, and raster gates after any change, and read the exported PNG to confirm every classification marker is visible.

## Anti-patterns

Do not present a draft-assumption as a confirmed fact: S3 and DynamoDB encryption are unverified in this snapshot, so they are labelled `draft — unverified`, not simply `encrypted`. Do not draw MongoDB Atlas inside the AWS account to tidy the picture — it is an external, separately-managed store whose encryption boundary is its own, and conflating it hides the encryption-at-rest gap this diagram exists to surface. Do not drop a data store because its classification is awkward; a dataflow audit must show every store of regulated data and state how it is classified. Do not put a real public IP in any label — use the EU-region residency note instead.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_13_sep_dataflow.py
#   rule-engine-export-raster 13-sep-dataflow.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system; this landscape names it via the `summary_of` cross-link so neither ships orphaned, and `03-sep-account-landscape` is the full as-built of the same account. The authoritative inventory is `INVENTORY-STATE.md` (section 3 for the MongoDB Atlas clusters and their encryption-at-rest NONE finding) and the `storage.json` / `database.json` / `secrets.json` snapshots under `inventory-aws-870325637521-eu-central-1-2026-10-07_2118`. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the service-scope placement of data stores, `diagram-standards.md` for nesting, padding, and lane order, `diagram-lint.md` for the dataflow lint profile and the `data-classification` and `ip-range` rules, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
