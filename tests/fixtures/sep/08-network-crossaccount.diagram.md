---
id: 08-network-crossaccount-v3
title: SEP production network — VPC and cross-account connectivity
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-15
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-14
diagram_class: landscape
diagram_type: network
summary_of: 02-sep-summary
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

Reading top to bottom, Route 53 (`syndicate.education`, account 323549576358) resolves to CloudFront at the edge, and traffic enters the `se` VPC through the Internet Gateway; private subnets egress through the NAT gateway `nat-11699e9f181a77012`. The `se` VPC box holds the whole in-network tier — the Internet Gateway, the NAT, the two VPC-endpoint nodes, the VPC-attached Lambda, and the Strapi RDS `sep-strapi-pg`. S3 and DynamoDB are reached via gateway endpoints and ECR via interface endpoints, so those never traverse the NAT. The four VPC peerings fan out from the in-VPC workload: `pcx-0e257b23d337fda0b` to MongoDB Atlas (781849312837, peer 192.168.246.0/24), `pcx-0ba890357ddac7479` to EPM-CMTR SRE (088595288622, 192.168.190.0/24), `pcx-0bd56ed835959cbbc` to EPM-CMTR CloudMentor (088595288622, 172.31.0.0/16), and `pcx-0754f6dee2f5bf2fd` to the CICD account (884218299410, 192.168.254.0/24).

## Troubleshooting

All six external targets are members of ONE dashed-grey external boundary below the SEP account, so each is structurally outside the account and none trips the `geometric-containment` rule (an ERROR on a network diagram). One shared box, not four stacked ones, keeps every peering edge a short near-vertical drop and holds the crossing count inside the landscape cap. If an icon renders as an empty box, the role is missing from `mappings/aws-icons.yaml`; the networking roles `nat_gateway`, `internet_gateway`, `vpc_endpoint`, and the VPC-attached `lambda_vpc` were added for this run. The two EKS clusters are reached over public endpoints, not peering — a route-less peering `pcx-0fc81284930ddf8e4` exists between the student cluster VPC and the control-plane VPC but carries no route, so the public path is the provable one. The peer-account boxes stay neutral; never substitute an AWS glyph for an account SEP does not own.

## Anti-patterns

Do not draw the external peer accounts, the EKS clusters, or CloudFront and DNS inside the SEP account boundary to avoid cross-boundary edges — an external account drawn inside SEP's account misrepresents ownership and trust. Do not fake an AWS service icon for a peer account; draw a peer with the AWS Organizations Account icon and label it by account id and role, draw MongoDB Atlas with its own brand-green leaf, and keep the two EKS clusters on the real AWS EKS icon. Do not collapse a VPC endpoint into the service it fronts: the endpoint is in the VPC and the service is regional. Do not redraw the two EKS clusters as peering targets; they are reached over public endpoints, and the one peering that does exist to the student cluster is route-less. Do not hand-edit the `.drawio` coordinates — regenerate from the coordinate-free spec instead.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_08_network_crossaccount.py
#   rule-engine-export-raster 08-network-crossaccount.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system and this landscape names it via the `summary_of` cross-link, so neither ships orphaned. The full account as-built is `03-sep-account-landscape`, which enumerates every service family; this diagram instead isolates the network and cross-account connectivity so a reviewer can reason about blast radius and trust boundaries. The authoritative network inventory behind every node, peering, and CIDR is `INVENTORY-STATE.md` — its gap-fill section records the four active peerings on the `se` VPC with their peer accounts and CIDRs, the four VPC endpoints, and the route-less student-cluster peering. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the AWS service-scope classification, `diagram-standards.md` for the North-South network orientation, nesting, padding, and edge-routing conventions, `diagram-lint.md` for the landscape-class severities, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
