---
id: 08-network-crossaccount-v11
title: SEP production network — VPC and cross-account connectivity
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-28
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

This landscape is the AWS-side network truth of the Syndicate Education Platform (SEP) production account `870325637521` in `eu-central-1`: the `se` VPC, how traffic enters and leaves it, and every cross-account path it depends on. It is the connectivity picture, not the service catalogue — the paired service-shape summary is `02-sep-summary` and the full as-built is `03-sep-account-landscape`. Every fact is drawn from the read-only inventory recorded in `INVENTORY-STATE.md`, never invented: the VPC `vpc-05cd5663a70d3a65c` (192.168.128.0/20), one NAT gateway, one Internet Gateway, four VPC endpoints (S3 and DynamoDB gateway, ECR dkr and api interface), the four active VPC peerings, and the two EKS clusters reached over public endpoints. It is a first draft pending the open owner questions in `INVENTORY-STATE.md`; every external target is a structural member of one dashed-grey external boundary OUTSIDE the SEP account (so none is ever geometrically inside a boundary it does not belong to), with the peer accounts drawn with the AWS Organizations Account icon and labelled by account id and role, the EKS clusters wearing the real AWS EKS icon, and MongoDB Atlas its own brand-green leaf — never a faked AWS service glyph.

## Main Content

Reading top to bottom, Route 53 (`syndicate.education`, account 323549576358) resolves to CloudFront at the edge, and traffic enters the `se` VPC through the Internet Gateway; private subnets egress through the NAT gateway `nat-11699e9f181a77012`. The `se` VPC box holds the whole in-network tier — the Internet Gateway, the NAT, the two VPC-endpoint nodes, the VPC-attached Lambda, the ECS Strapi content host, and the Strapi RDS `sep-strapi-pg`. The ECS Strapi host persists content to that RDS (Flow step 7), so the database is a real write target, not a producer-less node. S3 and DynamoDB are reached via gateway endpoints and ECR via interface endpoints, so those never traverse the NAT. Each of the four VPC peerings is now a RESOURCE NODE — an AWS VPC Peering Connection icon drawn between the in-VPC workload and the peer account, with two legs attaching — rather than a word on a line: `pcx-0e257b23d337fda0b` to MongoDB Atlas (781849312837, peer 192.168.246.0/24), `pcx-0ba890357ddac7479` to EPM-CMTR SRE (088595288622, 192.168.190.0/24), `pcx-0bd56ed835959cbbc` to EPM-CMTR CloudMentor (088595288622, 172.31.0.0/16), and `pcx-0754f6dee2f5bf2fd` to the CICD account (884218299410, 192.168.254.0/24). The pcx id and peer CIDR for each are carried as P1–P4 in the Flow legend.

## Troubleshooting

All six external targets are members of ONE dashed-grey external boundary below the SEP account, so each is structurally outside the account and none trips the `geometric-containment` rule (an ERROR on a network diagram). Each peering RESOURCE node (VPC Peering Connection icon) is a member of that external box, sitting between the SEP VPC side and its peer account, so it is never wrapped by the SEP account or the VPC. If an icon renders as an empty box, the role is missing from `mappings/aws-icons.yaml`; the networking roles `nat_gateway`, `internet_gateway`, `vpc_endpoint`, and the VPC-attached `lambda_vpc` were added for this run. The two EKS clusters are reached over public endpoints, not peering — a route-less peering `pcx-0fc81284930ddf8e4` exists between the student cluster VPC and the control-plane VPC but carries no route, so the public path is the provable one. The peer-account boxes stay neutral; never substitute an AWS glyph for an account SEP does not own. The 1.11.0 native skin only restyles edges grey, furniture light grey, and markers as dark badge discs — no node moved.

## Anti-patterns

Do not draw the external peer accounts, the EKS clusters, or CloudFront and DNS inside the SEP account boundary to avoid cross-boundary edges — an external account drawn inside SEP's account misrepresents ownership and trust. Do not fake an AWS service icon for a peer account; draw a peer with the AWS Organizations Account icon and label it by account id and role, draw MongoDB Atlas with its own brand-green leaf, and keep the two EKS clusters on the real AWS EKS icon. Do not collapse a VPC endpoint into the service it fronts: the endpoint is in the VPC and the service is regional. Do not redraw the two EKS clusters as peering targets; they are reached over public endpoints, and the one peering that does exist to the student cluster is route-less. Do not hand-edit the `.drawio` coordinates — regenerate from the coordinate-free spec instead.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_08_network_crossaccount.py
#   rule-engine-export-raster 08-network-crossaccount.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system and this landscape names it via the `summary_of` cross-link, so neither ships orphaned. The full account as-built is `03-sep-account-landscape`, which enumerates every service family; this diagram instead isolates the network and cross-account connectivity so a reviewer can reason about blast radius and trust boundaries. The authoritative network inventory behind every node, peering, and CIDR is `INVENTORY-STATE.md` — its gap-fill section records the four active peerings on the `se` VPC with their peer accounts and CIDRs, the four VPC endpoints, and the route-less student-cluster peering. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the AWS service-scope classification, `diagram-standards.md` for the North-South network orientation, nesting, padding, and edge-routing conventions, `diagram-lint.md` for the landscape-class severities, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
