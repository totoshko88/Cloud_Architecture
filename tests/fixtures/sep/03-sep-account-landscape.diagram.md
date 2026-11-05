---
id: 03-sep-account-landscape-v12
title: SEP production AWS account — as-built landscape
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
      v12 — separated overlapping edge corridors (e12/e15/e4 and the
      right-approach pairs) for readability. LAYOUT/ROUTING-ONLY edge-corridor
      cleanup in the hand-pinned build script: e12 keeps the x=300 corridor,
      e15 moves to its own x=330 lane (jog lowered to y=630 off e16's y=610),
      e4 moves to its own far-left x=270 lane and y=810 run, so the owner's
      "15 12 4" overlap band is split onto three distinct corridors; e13's
      horizontal raised to y=549 (off e11's y=569) and the right-side verticals
      spread to e8 x=740 / e7 x=760 / e10 x=790. No node, edge, caption,
      overlay, icon/role or container moved; Flow/Legend verbatim. Title
      v11->v12 (date 2026-10-28). Gates 0 ERROR/CRITICAL.
  - date: 2026-10-28
    note: >-
      v11 — converted 03 to a hand-pinned build script matching 09's compact
      se-VPC layout (compute spine left, VPC box right, Syndicate Server
      top-right) for 03/09 consistency. Rewrote the coordinate-free
      layout()/DiagramSpec script as a HAND-PINNED build script
      (.build-tools/build_sep_account_landscape.py), in the same style as
      01/09, calling build_diagram() directly with explicit
      Node(x,y)/Boundary(x,y,w,h)/Edge(exit,entry,points). This reproduces 09's
      compact se-VPC layout so 03 and 09 read consistently (owner model: 09 =
      augmented 03): a two-column compute spine on the left inside the region
      (col1 governance/messaging x=350, col2 compute x=620), the compact se VPC
      box to the RIGHT of the spine holding Syndicate Server top-right, ECS
      strapi + RDS adjacent on the middle row (strapi left, rds right) with the
      short strapi->RDS write, and modular-cli lower-left; WAF/CloudFront/DNS in
      the edge lane at top with WAF global/edge OUTSIDE the account.
      LAYOUT-ONLY: every node, edge, caption, overlay, icon/role and the
      Flow/Legend are preserved verbatim from v10; only coordinates and the
      title/id change. The old coordinate-free
      scripts/build_sep_account_landscape.py is retired after gates pass.
      Title v10->v11. Gates 0 ERROR/CRITICAL.
  - date: 2026-10-28
    note: >-
      v10 — VPC-layout reproduction of the owner hand-placement
      (09-crosscloud-landscape копія). Coordinate-free (lane/slot/sub/container
      only, no x/y pin, no engine/mappings edit): the se VPC box
      (boundary-vpc-a) now holds all four VPC-scoped nodes in ONE compact box
      with the owner's intended INTERNAL arrangement — the four are declared in
      the `data` lane at high slots with `sub` giving two rows, so the per-
      sub-row (lane, slot) ranking draws the top row strapi (col0) + rds (col1)
      + syndicate-server (col2, top-right) and the bottom row modular-cli
      (lower-left). strapi sits adjacent-left of rds so strapi→RDS is a short
      forward write. Crossings fell 9→6 (edge-crossing-avoidable 4→1). The
      owner's reference also places the box to the RIGHT of the compute spine;
      `vpc_side="right"` is the coordinate-free lever for that, but on this
      account the regional services span inner+outer regional columns and
      `vpc_side="right"` splits the compute spine around the VPC box, which the
      engine then cannot route (batch→EPM-CMTR knee-through-modular-cli,
      edge-routing ERROR → BLOCKED). The box therefore stays LEFT of the spine
      with the correct internal shape; the residual (missing lever: keep the
      regional columns together under vpc_side="right") is recorded in
      DIAGRAM-ENGINE-FEEDBACK-1.13.0.md. Node set, edges, captions, WAF/edge/
      global placement unchanged. Title v9→v10; gates 0 ERROR/CRITICAL.
  - date: 2026-10-28
    note: >-
      v9 — Wave 13 consistency fix (03 ⇄ 09). ADDED the Syndicate Server EC2
      (role compute_instance, caption "Syndicate Server (Education Extension +
      Syndi)") inside the se VPC (boundary-vpc-a) alongside RDS / ECS strapi /
      modular-cli, so 03's SEP-account node set is identical to 09's (owner's
      model: 09 = an augmented 03). ONE host carrying TWO logical components —
      the caption names both; it is NOT split into two nodes. The representative
      data-flow edge (Syndicate Server → SQS) was tried first per the plan, but
      on this dense account landscape the engine could not route the long
      VPC→regional hop without a new edge-routing ERROR and it pushed the
      crossing count over the landscape hard-cap; per plan A.1 the node is
      instead marked overlay="supporting" (dotted ring, no edge — the documented
      node-connectivity exemption, like modular-cli) placed at slot 5 sub 1 so
      it stacks below the VPC row rather than widening the async lane. The
      SQS-consume relationship stays described in Flow step 19 (marked "not
      drawn") and is drawn in 09 (e26). The Legend supporting line now names the
      Syndicate Server control plane. Title v8→v9; updated 2026-10-28.
      Coordinate-free — spec-only change, engine placed. Gates 0 ERROR/CRITICAL.
  - date: 2026-10-21
    note: v4 — regenerated on rule-engine 1.10.12 (title v3→v4). No content change; the upgraded engine's WS6 container compaction shrank the canvas markedly (~3336x3116 to ~2399x1932). Icons and edges unchanged.
  - date: 2026-10-22
    note: v5 — regenerated on rule-engine 1.11.0 pre-release with the native skin applied (grey edges #5A6B7B, light-grey Flow/Legend furniture #B3B3B3, dark #1A1A1A circle badge markers). No flow_groups or flow_steps on this landscape; geometry and icons unchanged, presentation-only.
  - date: 2026-10-23
    note: >-
      v6 — sixth-wave flow-accuracy correction (owner steps 2/7/9/14). Edge e5
      is re-pointed sqs→batch → lambda→batch: the SEP Lambda submits the AWS
      Batch job directly and Batch uses its own built-in job queue (owner step
      7, confirmed FALSE via the event-source-mapping table — zero Batch
      targets); e4 (lambda→sqs) stays the async enqueue. Flow text corrected:
      marker 2 names CloudFront fronting ONLY the REST API se-ui-api
      (7cipwpsrx5), marker 5 the direct Lambda→Batch submit, marker 14 the
      EventBridge→Batch trigger as ONLY for schedulable ACE jobs, marker 16 the
      DynamoDB table CiTerraformStateLocks as the CI/Terraform state-lock (not
      governance). Icons and geometry otherwise unchanged. Title v5→v6.
  - date: 2026-10-23
    note: >-
      Seventh-wave sweep (1.11.0): rebuilt BYTE-IDENTICAL. Owner 03 '13 can
      exit downward' already satisfied (the below target was a strict
      same-column drop drawn straight pre-SYS-A; SYS-A argmin-selects the
      identical route). All gates 0 ERROR/CRITICAL. Version held.
  - date: 2026-10-23
    note: >-
      v7 — tenth-wave B5 (owner: "13 вийти вниз ліворуч аби уникнути перетину із
      3; 3 можна вийти прямо вниз"). e3 (API Gateway -> Lambda, Lambda directly
      below) and e13 (API Gateway -> RDS, RDS down-left in the VPC) both left
      apigw's right face and crossed. e13 is re-declared adjacent to e3 so the
      direction-spread assigns the bottom face by target direction: marker 3
      drops straight DOWN into Lambda, marker 13 exits DOWN-LEFT to RDS, so the
      two no longer cross. Gates 0 ERROR/CRITICAL. Title v6->v7.
  - date: 2026-10-28
    note: >-
      v8 — Wave 12 inventory corrections. ADDED Strapi as ECS (role ecs,
      "ECS strapi (EC2->ECS migration)") inside the se VPC with edge e17
      strapi->RDS (RDS's real content writer); the same factual Strapi-as-ECS
      change applied on 08/10/13. ADDED modular-cli-instance (role
      compute_instance, "modular-cli (admin)", 4th running EC2) inside the VPC
      with admin edge e19 modular-cli->SSM. ADDED WAF (role waf,
      syndicate_education_cloudfront_waf, wafv2 global) in the actors edge lane
      OUTSIDE the region/VPC with edge e18 cloudfront->waf. ADDED GuardDuty
      (role guardduty, 1 detector) in the region as overlay='supporting'
      (dotted outline, no data-flow edge), documented in the Legend. Refined
      the DynamoDB caption to "DynamoDB CiTerraformStateLocks (Terraform
      state-lock)" (no Batch->DynamoDB edge added). Added Legend lines for the
      supporting marker, the global WAF edge placement, and the enabled-but-
      undrawn AWS X-Ray + AWS Config. Title v7->v8; updated 2026-10-28.
      Coordinate-free — spec-only change, engine placed. Gates 0 ERROR/CRITICAL.
tags:
  - aws
  - sep
  - landscape
  - deployment
  - as-built
  - 870325637521
  - eu-central-1
related_docs:
  - 02-sep-summary.diagram.md
  - INVENTORY-STATE.md
---

# SEP production AWS account — as-built landscape

## Overview

This landscape is the as-built view of the Syndicate Education Platform (SEP) production AWS account `870325637521` in `eu-central-1`, drawn on one canvas so a reviewer can see every deployed service family and how it relates at once. It is the detailed companion to the `02-sep-summary` flow summary, which carries the request-path shape; this diagram carries the full inventory. Every node and edge is derived from the live read-only inventory recorded in `INVENTORY-STATE.md` (collected 2026-10-07 and 2026-10-12, owner-reviewed 2026-10-08), never invented. Dense service families are grouped into one captioned node each — a single Lambda node stands for 13 functions, one SQS node for 14 queues plus dead-letter queues — so the picture stays legible without dropping a real resource. The nesting is Account contains Region contains the `se` VPC; the Strapi content database (RDS) is the only VPC-scoped service, while the regional managed services sit in the Region but outside the VPC, reached over endpoints or the NAT gateway. This is a first draft pending the open owner questions in `INVENTORY-STATE.md` section 9B.

## Main Content

Inside the VPC `se vpc-05cd5663a70d3a65c` (192.168.128.0/20) sit the VPC-scoped hosts: RDS `sep-strapi-pg` (PostgreSQL, Multi-AZ, encrypted) — Strapi's content store; the Strapi application itself, drawn as ECS, writing to that RDS; `modular-cli` (the admin CLI EC2 host); and the Syndicate Server EC2 (`Education Extension + Syndi`), the SEP control plane — one host carrying two logical components, drawn as a supporting node because its SQS-consume relationship is a long VPC→regional hop better shown on the cross-cloud landscape 09. The regional tier holds the compute and integration services: API Gateway, the Lambda handler group (VPC-attached), SQS, EventBridge, AWS Batch (STM, SRE, KTM, ACE, Voiceover) backed by ECR, S3, DynamoDB (`CiTerraformStateLocks`, the Terraform state-lock), SSM Parameter Store with KMS, Bedrock, CloudWatch, and GuardDuty (one detector, drawn as a supporting dotted node). Outside the account boundary sit the global edge — CloudFront, Route 53, and the global WAF `syndicate_education_cloudfront_waf` attached to CloudFront — the external MongoDB Atlas datastore, and the peered accounts EPM-CMTR and CICD, each reached over a dedicated VPC peering.

## Troubleshooting

If a gate reports a finding, fix the pinned coordinates in the hand-pinned build script `.build-tools/build_sep_account_landscape.py` rather than hand-editing the `.drawio`; the geometry is explicit `Node(x,y)` / `Boundary(x,y,w,h)` / `Edge(exit,entry,points)` passed straight to `build_diagram()`, so adjust a coordinate (never a child's size) and regenerate. An over-connected node error means a single node carries more than three edges on one face — re-source an edge from the real neighbour that owns the relationship instead of wiring everything through the Lambda hub. A `container-padding` finding (an ERROR on a landscape) means a node drifted against a boundary; it is almost always an external node that should declare no container so the account envelope never wraps it. If an icon renders as an empty box, the role is missing from `mappings/aws-icons.yaml`; AWS Batch and ECR were added for this run. The MongoDB Atlas node renders MongoDB's own brand-green leaf mark — it is external and must never carry a fake AWS icon, but its real vendor glyph is correct. The 1.11.0 native skin only restyles edges grey, the Flow/Legend furniture light grey, and markers as dark badge discs — no node moved. Re-run the lint, icon-verify, and raster gates after any change.

## Anti-patterns

Do not wire every service to the Lambda node to show that it is central: the engine caps a node at three edges per face, and more importantly a hairball hides the real data paths. Show only the genuine relationships the inventory proves. Do not place the external nodes (Atlas, the peered accounts, CloudFront, DNS) inside the account boundary to avoid cross-boundary edges — an external datastore drawn inside the VPC misrepresents the architecture. Do not substitute a look-alike AWS icon for MongoDB Atlas; its MongoDB brand-green leaf is correct. Do not split this as-built into several twelve-node pages — a landscape exists to show the whole account at once; the paired `02-sep-summary` carries the simplified shape instead.

```python
# Regenerate the triple (hand-pinned; never hand-edit the .drawio, change the script):
#   python3 .build-tools/build_sep_account_landscape.py
#   rule-engine-export-raster 03-sep-account-landscape.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system; this landscape names it via the `summary_of` cross-link so neither ships orphaned. The authoritative inventory behind every node and edge is `INVENTORY-STATE.md`, whose section 2 covers this account, section 8 the cross-cloud relationships (the Atlas and EPM-CMTR peerings), and section 9B the open owner questions that may still reshape a few edges. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the AWS service-scope classification that decides VPC-scoped versus regional placement, `diagram-standards.md` for the nesting, padding, lane order, and edge-routing conventions, `diagram-lint.md` for the class-aware severities (a landscape escalates container-padding, edge-direction, edge-float, and the crossing cap to errors), `asset-packs.md` for the icon resolution order, and `kb-frontmatter.md` for this companion's required frontmatter.
