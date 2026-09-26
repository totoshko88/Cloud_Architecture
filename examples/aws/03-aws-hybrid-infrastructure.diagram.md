---
id: aws-hybrid-infrastructure-diagram-v1
title: AWS Hybrid Infrastructure (North–South)
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-09-25
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-25
diagram_class: flow
tags:
  - aws
  - infrastructure
  - north-south
  - hybrid
  - golden-example
related_docs:
  - 00-MANIFEST.md
---

# AWS Hybrid Infrastructure (North–South)

## Overview

This is the reference **infrastructure** diagram: the one shipped example laid
out on the North–South axis rather than left to right. `diagram-standards.md`
splits orientation by diagram type — infrastructure, network, and deployment
diagrams read top to bottom, with the most external actor at the top and traffic
descending into progressively more internal tiers, while redundant peers sit side
by side on the same row. Until this example, that axis was specified but no
golden exercised it, so the render path had never been through the publication
gate. It is also the only golden that places an **external actor** and an
**on-premises estate** outside the cloud boundaries, and the only one that draws
Availability Zones as peer containers. Eleven nodes and eleven edges, class
`flow`, so the 12-node cap still applies and every edge carries a numbered
marker described in the right-margin Flow legend.

## Main Content

Traffic descends five tiers. A corporate user — drawn to the left of the Account
boundary, because an actor is not an account resource — resolves the public
hosted zone in Route 53, which answers with the CloudFront distribution. The CDN
origin fetch drops into the public Application Load Balancer inside the VPC, and
the balancer fans out across both Availability Zones: `az-eu-central-1a` and
`az-eu-central-1b` are peer containers sharing one top edge and height, each
holding an EC2 application node above its RDS database node. The writer in AZ-a
replicates synchronously to the standby in AZ-b, which is the availability
dimension read horizontally. Two regional services sit inside the Account but
outside the VPC in their own column: the shared EFS file system the application
tier mounts, and the S3 bucket the balancer ships access logs to. The
on-premises Oracle database has its **own** boundary container, a disjoint
sibling of the Account, so the replication edge visibly crosses out of the VPC,
out of the Account, and into the datacenter.

## Troubleshooting

If the diagram fails `container-padding`, check the vertical stack: each
container reserves its caption strip plus one grid step before its first content
row, so the ALB's label band must clear the AZ boxes' top edge by 30px, and each
AZ box must clear its lowest database footprint by the same. If an edge trips
`edge-direction`, confirm it exits the source's right or bottom **face** and
enters the target's left or top — a top-centre exit such as `(0.5, 0)` is a
defect even though its x leans right. If `container-overlap` fires between the
Account and the on-premises boundary, the two have stopped being disjoint
siblings: the datacenter must never nest inside the Account. Regenerate with
`python scripts/build_aws_infra_example.py`, then re-export the raster with
`python scripts/export_raster.py` and re-run `rule-engine-lint`.

## See Also

The generator is `scripts/build_aws_infra_example.py`; it builds on the shared
numeric layout in `rule_engine.diagram_layout`, so icon size, label placement,
grid step, container padding, and the right-margin Flow/Legend column match
every other golden. Icon style strings are built-in `mxgraph.aws4.*` stencils
verified against `mappings/aws4-icons.json`, so this diagram renders without the
fetched vendor packs. The rules it exercises live in
`.kiro/steering/diagram-standards.md` (Diagram Orientation, the North–South
reference geometry, external actors and on-premises outside the cloud
boundaries, Container Nesting for the peer AZ bands) and
`.kiro/steering/diagram-lint.md` (the rule list and severities). For the
left→right flow layout of the same provider see `01-aws-agent-platform`, and for
the as-built inventory view see the `02-aws-ha-multiregion` summary/landscape
pair.
