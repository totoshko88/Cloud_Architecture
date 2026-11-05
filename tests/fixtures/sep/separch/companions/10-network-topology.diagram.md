---
id: 10-network-topology-v9
title: SEP network topology — se VPC, AZs, subnet tiers, endpoints
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-11-04
owner: platform-engineering
author: diagram-author
next_review_date: 2027-05-04
diagram_class: landscape
diagram_type: network
summary_of: 02-sep-summary
change_log:
  - date: 2026-10-22
    note: v1 — new network-topology diagram added in the 1.11.0 regeneration (WS6 network type, native skin). Draws the se VPC's edge devices, four VPC endpoints, a security-group leaf-boundary, and the four cross-account VPC peerings.
  - date: 2026-10-23
    note: v2 — G23 peering-as-resource. The four cross-account VPC peerings are now drawn as RESOURCE NODES (AWS VPC Peering Connection icon) between the SEP VPC side and each peer account, instead of a symmetric dashed 'peering' line.
  - date: 2026-10-23
    note: v3 — seventh-wave ENG-1 VPC-peering node naming (owner 10, 'аналогічно до 08'). The four pcx nodes render their short peer-resource names via peering_label_for; pcx-id + CIDR stay in the Flow legend.
  - date: 2026-10-23
    note: >-
      v4 — ninth-wave G40 depth-5 rebuild (FEAT-002) on the AZ/subnet CORE.
      The flat security-group model is replaced by the real AWS nesting
      Account > VPC se > {AZ eu-central-1a | AZ eu-central-1b side-by-side} >
      four subnet tiers per AZ (public, private-app, private-batch,
      isolated-db) with real CIDRs. Workloads sit in their real subnets
      (Lambda+EC2 in private-app 1a; Batch + ECR interface endpoints in
      private-batch; RDS Multi-AZ primary isolated-db 1b / standby 1a). The
      single regional NAT is drawn once; the egress-only IGW and the S3/DDB
      gateway endpoints are drawn in the public edge tiers. The four peerings
      stay a Flow/caption note (drawn as nodes on 08). scope-placement clean;
      all per-diagram gates 0 ERROR/CRITICAL. Title v3->v4.
  - date: 2026-10-23
    note: >-
      v5 — tenth-wave owner fixes. (1) IGW re-parented from the public-1a subnet
      to the VPC level: the Internet Gateway is a VPC-attached service and now
      sits OUTSIDE every subnet, at the VPC edge between the two AZ boxes. (2)
      ADD-1: MongoDB Atlas drawn as a real external AWS account 781849312837
      (grey dashed box OUTSIDE SEP, peer VPC 192.168.246.0/24) with the Atlas
      VPC peering pcx-0e257b23d337fda0b as a resource node; BOTH the VPC-attached
      Lambda and the EC2 syndicate-server reach the SAME Atlas learner datastore
      over that peering (markers 8/9), correcting the old marker 7 which read
      only syndicate-server->RDS. RDS stays the Strapi content datastore. (3)
      AZ stroke corrected to the official teal #00A4A6 (G46 palette). Flow
      re-synced; scope-placement clean; gates 0 ERROR/CRITICAL. Title v4->v5.
  - date: 2026-10-23
    note: >-
      v6 — eleventh-wave owner fixes + the E-EDGE / E-PCX engine capabilities.
      (1) The single REGIONAL NAT nat-11699e9f is moved OUT of the public 1b
      subnet to the VPC EDGE, drawn side by side with the Internet Gateway
      outside every subnet (owner: a NAT is an МЗС/regional-level service; the
      new E-EDGE lint edge-service-in-subnet enforces it). Both AZs' private
      route tables send 0.0.0.0/0 to this one NAT. (2) The former marker 7
      (syndicate-server->RDS) is REMOVED — the Syndicate Server does not use the
      Strapi RDS (sep-strapi-pg is Strapi-only; the Syndicate Server uses MongoDB
      Atlas, DB PROD_SEP_Server, over the peering); RDS keeps only the Lambda
      path. The Flow is renumbered contiguously 1..8. (3) The two ECR INTERFACE
      endpoints are confirmed in the private-batch tier (subnet-0def0185 1a /
      subnet-0fb5aa20 1b, sg-0b18cd10). (4) The Atlas peering node carries the
      two-line caption 'Atlas peering' + 'pcx-0e257b23d337fda0b' (E-PCX). The
      egress-only IGW (route-level IPv6 egress, also a VPC-edge device) is now a
      Legend/Flow note rather than a drawn node, so the VPC edge reads as the
      IGW + NAT pair the owner asked for, cleanly. scope-placement +
      edge-service-in-subnet clean; gates 0 ERROR/CRITICAL. Title v5->v6.
  - date: 2026-10-28
    note: >-
      v7 — Wave-12 Strapi-as-ECS. The real EC2 strapi-server
      (subnet-0198dec223463fa5e, eu-central-1b) is migrating to ECS, so a new
      private-app 1b subnet (sub-app-b) is drawn holding an ECS strapi node
      (role ecs, caption 'ECS strapi (EC2->ECS migration)') — the same factual
      change as on 03/08/13. Its write edge strapi->RDS primary (isolated-db 1b,
      intra-AZ) gives the RDS primary its real producer. WAF is NOT added (it is
      global/edge, out of scope for this L3/L4 network view). Flow adds step 9;
      scope-placement clean; gates 0 ERROR/CRITICAL. Title v6->v7.
  - date: 2026-10-28
    note: >-
      v8 — converted 10 to a hand-pinned build script reproducing the owner's
      compact AZ layout (narrower AZ boxes, AZ-b pulled left); coordinate-free
      solver over-stretches the AZ boxes (G40-follow-up / L6 in
      ENGINE-TODO-for-release.md).
  - date: 2026-11-04
    note: >-
      v9 - 1.13.0 phase-2 fix. IGW/NAT semantics corrected: private tiers of
      BOTH AZs egress 0/0 -> NAT (edges 1, 2) and NAT -> IGW (edge 3); the
      IGW no longer fronts a private Lambda and NAT no longer feeds Batch 1b.
      S3/DynamoDB gateway endpoints moved to the VPC edge; public subnets are
      drawn empty. Atlas peering is drawn VPC box -> pcx -> Atlas (container
      endpoint, edges 9, 10). On-canvas Flow restored (steps 1-10, P2-P3); the
      deprecated legacy CI peering is dropped. NAT two-line caption restored,
      captions shortened (no caption-outside-container), same-AZ subnet
      widths equalised. Reconcile scoped to flow coverage (see Main Content).
tags:
  - aws
  - sep
  - network
  - vpc
  - availability-zone
  - subnet
  - vpc-endpoint
related_docs:
  - 02-sep-summary.diagram.md
  - 08-network-crossaccount.diagram.md
  - INVENTORY-STATE.md
---

# SEP network topology

## Overview

This landscape is the real depth-5 intra-VPC network topology of the Syndicate Education Platform production account `870325637521` in `eu-central-1`. It nests `Account > VPC se > {AZ eu-central-1a | AZ eu-central-1b} > subnet tiers`, the canonical AWS network shape, so a reviewer sees which services are network-isolated and in which availability zone. Every fact is drawn from the read-only inventory snapshot `network.json`, never invented: the VPC `vpc-05cd5663a70d3a65c` (192.168.128.0/20, dual-stack IPv6), its two availability zones, the four subnet tiers each AZ carries (public, private-app, private-batch, isolated-db) with their real CIDRs, the Internet Gateway and the single regional NAT `nat-11699e9f181a77012` (both VPC-attached, drawn side by side at the VPC edge outside every subnet), the egress-only IGW, and the four VPC endpoints. It also draws the external MongoDB Atlas AWS account `781849312837` and the Atlas VPC peering `pcx-0e257b23d337fda0b` (captioned with its pcx-id) both the Lambda and the syndicate-server use. The paired service-shape summary is `02-sep-summary`, named via the `summary_of` cross-link so this landscape never ships orphaned. There is no transit gateway, VPN gateway, Direct Connect, or network firewall in this account, so none is drawn, and the default VPC 172.31.0.0/16 is excluded.

## Main Content
Each availability zone is a dashed teal (`#00A4A6`) box holding its subnet tiers, stacked North-South: public (drawn empty), private-app, private-batch, isolated-db. The Internet Gateway, the single regional NAT (`nat-11699e9f`) and the S3 and DynamoDB gateway endpoints are VPC-level services, so they sit at the VPC edge between the AZs. Private tiers of both AZs send `0.0.0.0/0` to the NAT (steps 1 and 2) and the NAT egresses through the IGW (step 3); the IGW never fronts a private tier. Private-app 1a holds the VPC-attached Lambda and the syndicate-server EC2. Private-app 1b holds the ECS strapi host. Private-batch holds Batch Fargate and the two ECR interface endpoints. Isolated-db holds the RDS `sep-strapi-pg` pair (primary 1b, standby 1a). Lambda and the syndicate-server reach the external MongoDB Atlas datastore over the Atlas peering, drawn VPC box to pcx to Atlas (steps 9 and 10); the syndicate-server does not use the Strapi RDS.

## Flow
1. AZ 1a private tier (EC2 syndicate-server) sends 0.0.0.0/0 to the regional NAT nat-11699e9f
2. AZ 1b private tier (ECS strapi) sends 0.0.0.0/0 to the same regional NAT
3. NAT egresses to the Internet via the Internet Gateway igw-06f4f5e6797fb83bc
4. Lambda reaches S3 via the gateway VPC endpoint
5. Batch 1a reaches ECR api via the interface VPC endpoint
6. Batch 1b reaches ECR dkr via the interface VPC endpoint
7. Lambda persists Strapi content to RDS sep-strapi-pg primary
8. ECS strapi persists Strapi content to the RDS primary (intra-AZ)
9. VPC se peers to MongoDB Atlas over pcx-0e257b23d337fda0b
10. Lambda and syndicate-server use the Atlas learner datastore over the peering
## Troubleshooting
Every workload sits geometrically inside its real subnet, and the VPC-attached Lambda carries an explicit `scope=network` override, so `scope-placement` and `geometric-containment` report nothing. If an icon renders as an empty box, check `mappings/aws-icons.yaml`; `verify-icon --strict` reports 15 resolved. Captions are short so each fits its box; the routing story lives in the Legend. Reconcile note: this is a scoped network slice, so use `rule-engine-reconcile --coverage-class flow` (all expected roles covered on both snapshots). It stays `landscape` because 15 nodes exceed the flow cap of 12; under landscape coverage the CDN, LB, queue, object-store, WAF and LLM roles are omitted by design. Residual `edge-crosses-container` and `graph-islands` WARNINGs (batch tiers and the Atlas pair) do not block publication.

## Anti-patterns

Do not draw a route-table object per subnet — it overloads the canvas; the routing (0/0 to NAT, ::/0 to the egress-only IGW, S3/DDB to the gateway endpoints, plus the four peering CIDRs) is attributed in the Legend instead. Do not draw the default VPC 172.31.0.0/16; it is not SEP. Do not collapse a VPC endpoint into the service it fronts: the endpoint lives in the VPC and the service is regional, so draw them distinctly. Do not duplicate the single regional NAT into a per-AZ pair to match the textbook AWS reference; draw the one real NAT and note the deviation. Do not draw a transit gateway, VPN, Direct Connect, or network firewall — none exists here. This diagram is now a HAND-PINNED build script holding the owner's compact AZ geometry (narrower AZ boxes, AZ-b pulled left) because the coordinate-free solver over-stretches the AZ boxes; still, never hand-edit the `.drawio` coordinates — change the pinned build script and regenerate instead.

```python
# Regenerate the triple (hand-pinned geometry; never hand-edit the .drawio):
#   python3 .build-tools/build_10_network_topology.py
#   rule-engine-export-raster 10-network-topology.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system and this landscape names it via the `summary_of` cross-link, so neither ships orphaned. The sibling network view `08-network-crossaccount` carries the account-to-account connectivity — the four named VPC peerings and the public EKS endpoints — while this diagram isolates the VPC's own availability-zone and subnet structure so a reviewer can reason about intra-VPC paths, zone resilience, and blast radius. The authoritative network inventory behind every subnet, CIDR, endpoint, and gateway is the snapshot `network.json` and the roll-up in `INVENTORY-STATE.md`. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the AWS service-scope classification and container conventions, `diagram-standards.md` for the North-South network orientation, AZ side-by-side placement, nesting, and padding, `diagram-lint.md` for the landscape-class severities, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
