---
id: 03-sep-account-landscape-v3
title: SEP production AWS account — as-built landscape
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-15
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-14
diagram_class: landscape
diagram_type: deployment
summary_of: 02-sep-summary
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

Inside the VPC `se vpc-05cd5663a70d3a65c` (192.168.128.0/20) sits only RDS `sep-strapi-pg` (PostgreSQL 17.9, Multi-AZ, encrypted) — Strapi's content store, not the application datastore. The regional tier holds the compute and integration services: API Gateway (four REST APIs plus one WebSocket), the Lambda handler group (13 functions, VPC-attached), SQS, EventBridge (5 `se-` rules plus 82 schedules), AWS Batch (5 compute environments / 5 job queues / 6 job definitions covering STM, STM-clean, SRE, KTM, ACE, Voiceover) backed by ECR (5 repositories), S3 (25 buckets), DynamoDB (the CI Terraform state-lock table), SSM Parameter Store (245 params) with KMS (6 keys), Bedrock (54 foundation models for Angry EdA), and CloudWatch. Outside the account boundary sit the global edge (CloudFront, Route 53 in account 323549576358), the external MongoDB Atlas primary datastore (its MongoDB brand leaf), and the peered accounts EPM-CMTR and CICD drawn with the AWS Organizations Account icon, each reached over a dedicated VPC peering.

## Troubleshooting

If the layout engine reports a warning, read `placed.layout_warnings` rather than hand-editing the `.drawio`; the geometry is generated from the coordinate-free spec in `scripts/build_sep_account_landscape.py`, so fix the spec and regenerate. An over-connected node error means a single node carries more than three edges on one face — re-source an edge from the real neighbour that owns the relationship instead of wiring everything through the Lambda hub. A `container-padding` finding (an ERROR on a landscape) means a node drifted against a boundary; it is almost always an external node that should declare no container so the account envelope never wraps it. If an icon renders as an empty box, the role is missing from `mappings/aws-icons.yaml`; AWS Batch and ECR were added for this run. The MongoDB Atlas node renders MongoDB's own brand-green leaf mark — it is external and must never carry a fake AWS icon, but its real vendor glyph is correct. Re-run the lint, icon-verify, and raster gates after any change.

## Anti-patterns

Do not wire every service to the Lambda node to show that it is central: the engine caps a node at three edges per face, and more importantly a hairball hides the real data paths. Show only the genuine relationships the inventory proves. Do not place the external nodes (Atlas, the peered accounts, CloudFront, DNS) inside the account boundary to avoid cross-boundary edges — an external datastore drawn inside the VPC misrepresents the architecture. Do not substitute a look-alike AWS icon for MongoDB Atlas; its MongoDB brand-green leaf is correct. Do not split this as-built into several twelve-node pages — a landscape exists to show the whole account at once; the paired `02-sep-summary` carries the simplified shape instead.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_sep_account_landscape.py
#   rule-engine-export-raster 03-sep-account-landscape.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system; this landscape names it via the `summary_of` cross-link so neither ships orphaned. The authoritative inventory behind every node and edge is `INVENTORY-STATE.md`, whose section 2 covers this account, section 8 the cross-cloud relationships (the Atlas and EPM-CMTR peerings), and section 9B the open owner questions that may still reshape a few edges. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the AWS service-scope classification that decides VPC-scoped versus regional placement, `diagram-standards.md` for the nesting, padding, lane order, and edge-routing conventions, `diagram-lint.md` for the class-aware severities (a landscape escalates container-padding, edge-direction, edge-float, and the crossing cap to errors), `asset-packs.md` for the icon resolution order, and `kb-frontmatter.md` for this companion's required frontmatter.
