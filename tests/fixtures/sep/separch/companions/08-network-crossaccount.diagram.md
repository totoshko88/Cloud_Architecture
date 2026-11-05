---
id: 08-network-crossaccount-v12
title: SEP production network — VPC and cross-account connectivity
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-11-03
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-21
diagram_class: landscape
diagram_type: network
summary_of: 02-sep-summary
change_log:
  - date: 2026-10-21
    note: v4 — regenerated on rule-engine 1.10.12 (title v3→v4). No content change; the upgraded engine's WS6 container compaction shrank the canvas markedly (~3346x2703 to ~2425x1584). Icons and edges unchanged.
  - date: 2026-10-22
    note: v5 — regenerated on rule-engine 1.11.0 pre-release with the native skin applied (grey edges #5A6B7B, light-grey Flow/Legend furniture #B3B3B3, dark #1A1A1A circle badge markers). No flow_groups or flow_steps on this network landscape; geometry and icons unchanged, presentation-only.
  - date: 2026-10-23
    note: v6 — G23 peering-as-resource. The four cross-account VPC peerings are now drawn as RESOURCE NODES (AWS VPC Peering Connection icon) sitting between the SEP VPC side and each peer account, with two legs attaching (DiagramSpec.peering_as_node=True), instead of a 'peering' word on a line. The pcx detail stays in the Flow legend P1–P4; the two public-EKS endpoints are renumbered 7/8 and remain ordinary dashed edges (not peerings). Removed the deprecated 'Task Manager' framing from the CloudMentor peering line.
  - date: 2026-10-23
    note: >-
      v7 — wave-2 owner review of edges 5 and 8. Rebuilt on the current engine;
      edge 5 (RDS → VPCe ECR interface) and edge 8 (NAT → EKS dev public
      endpoint) are the standards-mandated caption-safe side-corridor routes
      (Variant A): a straight drop would cut RDS's own caption / the external
      band caption, which the engine's caption-safe pass deliberately avoids, so
      the minimal side-step is retained rather than forced through a caption.
      EPM-CMTR / CICD peers and the four VPC Peering resource nodes (G23) are
      preserved with clean legs and no empty marker discs. Title v6→v7.
  - date: 2026-10-23
    note: >-
      v8 — seventh-wave: ENG-1 VPC-peering node naming. The four materialized
      pcx nodes now render their short peer-resource names (Atlas peering /
      CMTR-SRE peering / CMTR-CloudMentor peering / CICD peering) via
      EdgeSpec.peering_label + peering_label_for, instead of the generic VPC
      Peering caption; the pcx-id + CIDR stay in the Flow legend (P1..P4).
      Resolves owner 08 'VPC peering варто давати імена, на основі назви
      ресурса'. Rebuilt + re-exported under SYS-B/SYS-A; all gates 0
      ERROR/CRITICAL, icons 0 unresolved (node-label-length clean). Title
      v7→v8.
  - date: 2026-10-23
    note: >-
      v9 — eleventh-wave E-PCX: each of the four materialized pcx nodes now
      carries the raw pcx-id on a SECOND caption line below the short peer name
      (Atlas peering / pcx-0e257b23d337fda0b; CMTR-SRE peering /
      pcx-0ba890357ddac7479; CMTR-CloudMentor / pcx-0bd56ed835959cbbc; CICD
      peering / pcx-0754f6dee2f5bf2fd), surfaced by the new engine accessor
      peering_id_for. Resolves owner 'Peering має ідентифікатор і його варто
      додавати, як підпис, особливо в схемах із багатьма peering'. The two
      short lines stay under node-label-length; the peer CIDRs stay in the Flow
      legend P1..P4. All gates 0 ERROR/CRITICAL; icons 0 unresolved. Title
      v8->v9.
  - date: 2026-10-28
    note: >-
      v11 — Wave 13 line-overlap cleanup (owner 08: "накладання ліній"). Attempted
      spec-only separation of the two overlapping cross-account legs e13
      (strapi -> RDS, in-VPC) and e8-a (the lambda-sourced CMTR-SRE peering leg):
      swept the external peer slot order and the strapi VPC slot/sub. Each sweep
      traded the single residual collinear:1 (e13, e8-a) for a worse pairing or
      an extra crossing on this dense cross-account layout, so the slot order is
      kept and the residual collinear:1 plus the e8-a peer-ext top-caption
      crossing (edge-crosses-container-label) are left as a 1.13.0 engine routing
      limitation, recorded in DIAGRAM-ENGINE-FEEDBACK-1.13.0.md; both are WARNINGs
      and do not block publication. The graph-islands:2 (eks-dev / eks-shared /
      nat public-endpoint subgraph) is pre-existing structure and out of scope.
      No topology change. Title v10->v11.
  - date: 2026-10-28
    note: >-
      v10 — Wave 12 Strapi-as-ECS. Added an ECS strapi node (role ecs, caption
      "ECS strapi (EC2->ECS migration)") in the se VPC private app/batch subnet
      tier, with a new edge strapi -> RDS sep-strapi-pg (Flow step 7), so the
      RDS is no longer a producer-less node. The same factual change as on
      03/10/13. WAF is NOT added here (global/edge; 08 is the eu-central-1
      network view). The two public-EKS endpoints are renumbered 8/9 to keep the
      numbered flow contiguous. Title v9->v10; updated 2026-10-28.
  - date: 2026-11-03
    note: >-
      v12 — rebuilt on the final rule-engine 1.13.0 to fix the misleading v11
      picture (review-1130 items 08-1..08-15). Removed the fake CloudFront ->
      IGW -> Lambda ingress; CloudFront now reaches its real regional origins
      (API Gateway se-ui-api, S3 se-ui) outside the VPC, and API Gateway invokes
      the VPC-attached Lambda. The IGW serves the public-IP EC2 modular-cli and
      the NAT; Lambda, Syndicate Server and Batch (5 Fargate compute envs) egress
      through the NAT, and the IGW carries the public EKS endpoint paths, so the
      old NAT/EKS island is gone. The ECR endpoint consumer is Batch, not RDS.
      Added Region and the four subnet tiers (public / private-app /
      private-batch / isolated-db), the internal ALB strapi-alb (10-31
      snapshot) in front of ECS strapi, one peer_account group per peer account
      plus an external_cloud SaaS box for MongoDB Atlas, and peering legs that
      leave the VPC container face (item 8) with every leg labelled. EPM-CMTR
      (legacy Jenkins Task Manager, owner decision 2026-11-03) is DEPRECATED:
      its two peerings (pcx-0ba890357ddac7479 SRE path, pcx-0bd56ed835959cbbc
      CloudMentor) and the EPM-CMTR nodes are no longer drawn. Legend fixed
      (Region exists; dashed = via endpoint / public path). Title v11 -> v12.
tags:
  - aws
  - sep
  - network
  - vpc-peering
  - cross-account
  - 870325637521
  - eu-central-1
related_docs:
  - 02-sep-summary.diagram.md
  - 03-sep-account-landscape.diagram.md
  - INVENTORY-STATE.md
---
# SEP production network and cross-account connectivity

## Overview

This landscape is the AWS-side network truth of the Syndicate Education Platform (SEP) production account `870325637521` in `eu-central-1`: the `se` VPC `vpc-05cd5663a70d3a65c` (192.168.128.0/20), how traffic enters and leaves it, and every cross-account path it depends on. It is the connectivity picture, not the service catalogue; the paired service-shape summary is `02-sep-summary` and the full as-built is `03-sep-account-landscape`. Every fact comes from the read-only snapshots `inventory-aws-870325637521-eu-central-1-2026-10-31_2044` and `-2026-10-07_2118` and from `INVENTORY-STATE.md`. The nesting is Account, Region, VPC, then the four subnet tiers in AWS reference order: public, private app, private batch and isolated database. Global edge services (Route 53 in EPMC-EOOS `323549576358`, CloudFront owned by SEP) sit in a dashed edge box outside the region. Each peer AWS account has its own grey account group outside SEP, and MongoDB Atlas has a dashed SaaS box. EPM-CMTR, the legacy Jenkins Task Manager, is deprecated and is not drawn.

## Main Content

Ingress: Route 53 resolves `syndicate.education` to CloudFront, whose real origins are regional services outside the VPC: API Gateway `se-ui-api` and the S3 bucket `se-ui` (plus a Lambda function URL and other S3 buckets, collapsed here). API Gateway invokes the VPC-attached Lambda as a service call, not through the Internet Gateway. The IGW fronts the only running EC2 with a public IP, `modular-cli-instance`, in the public subnet. Egress: the VPC-attached Lambdas, the Syndicate Server EC2 and the five Batch Fargate compute environments leave through the NAT Gateway in the public subnet, and the NAT goes out through the IGW. The two EKS clusters are reached over their PUBLIC endpoints along that path, not over peering. S3 and DynamoDB are reached through gateway endpoints, and Batch pulls images through the ECR interface endpoints. The internal ALB `strapi-alb` forwards to the ECS strapi tasks, which persist content to RDS `sep-strapi-pg`. Two active peerings remain, each drawn from the VPC boundary face to a VPC Peering Connection node in the peer box: `pcx-0e257b23d337fda0b` to Atlas and `pcx-0754f6dee2f5bf2fd` to CICD `884218299410`.

## Troubleshooting

If a peering leg seems to start from a host, regenerate: since v12 every leg leaves the VPC container face and carries the label `peering`. The pcx id and peer CIDR are in the Flow list (P1, P2). If an icon renders as an empty box, check `mappings/aws-icons.yaml` and `mappings/local/` for the networking roles. The builder hand-routes the IGW and NAT funnel edges, the RDS feeds, the CloudFront origin legs and the two peering legs from the placed boxes, because the 1.13.0 router cut the IGW glyph, merged unrelated lines and doubled the VPC exit point on this spec. The remaining lint findings are WARNINGs. Collinear and corridor-sharing pairs are the deliberate IGW fan-out, NAT fan-in and RDS fan-in trunks. `graph-islands` lists the two peer boxes because the linter does not count container-endpoint legs as a connection to the VPC's nodes. The crossings stay at 8/20, well under the hard cap. Reconcile omissions are justified in the section below; nothing role-bearing is silently dropped.

## Reconcile justification

`rule-engine-reconcile` (landscape) against the 2026-10-31 snapshot omits three roles, and the 2026-10-07 snapshot omits two. None of them sits on a network path this view draws:

- `message_queue` (14 SQS queues): regional services with no interface endpoint. They are reached through the NAT (Flow 11, 15) and drawn on `03-sep-account-landscape`.
- `llm_platform` (55 Bedrock foundation models, 10-31 snapshot only): a regional managed API with no VPC footprint, reached through the NAT. It is not a network resource of the `se` VPC.
- `waf` (`syndicate_education_cloudfront_waf`): a global WebACL attached to CloudFront, an attribute of the edge node rather than a hop. It is drawn on 03.

The `lb` role (internal `strapi-alb`, new in the 10-31 snapshot) is drawn.

## Anti-patterns

Do not draw a CloudFront edge into the Internet Gateway: CloudFront origins are regional endpoints, and a VPC-attached Lambda never takes ingress through an IGW. Do not hang a peering leg off a Lambda or an RDS node; the peering joins networks, so the leg leaves the VPC boundary. Do not draw EPM-CMTR or its peerings again, because the legacy Jenkins TM is deprecated. Do not put CloudFront or regional services inside the VPC, and do not draw a NAT without its users.

```python
# Regenerate the triple (never hand-edit the .drawio):
#   python3 scripts/build_08_network_crossaccount.py
#   rule-engine-export-raster 08-network-crossaccount.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system. This landscape names it through the `summary_of` cross-link, so neither ships orphaned. The full account as-built is `03-sep-account-landscape`, which enumerates every service family, including the SQS queues, the Bedrock usage and the CloudFront WAF that this network view leaves out. This diagram isolates the network and cross-account connectivity, so a reviewer can reason about blast radius and trust boundaries. The authoritative inventory behind every node, peering and CIDR is `INVENTORY-STATE.md`. Its gap-fill section records the peerings on the `se` VPC with their peer accounts and CIDRs, the four VPC endpoints and the route-less student-cluster peering. The always-on steering covers the rest: `provider-profiles.md` for service scope, `diagram-standards.md` for the North-South orientation, nesting and edge routing, `diagram-lint.md` for landscape severities, `asset-packs.md` for icons and `kb-frontmatter.md` for this frontmatter.

## Assumptions

- **ambiguous_edge_kind** on `e1`: applied default *geometric classifier*, which derives the edge class from lane and region (Route 53 to CloudFront inside the global edge box).
