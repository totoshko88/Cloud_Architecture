---
id: 12-sep-access-v3
title: SEP production AWS account — IAM access (security review)
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-23
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-23
diagram_class: flow
diagram_type: access
change_log:
  - date: 2026-10-23
    note: v1 — new access diagram (WS7 access type) on rule-engine 1.11.0. Aggregates the 27 SEP IAM roles (iam.json) into a principal → policy → resource chain by trust principal, within the access node_cap of 12. Native skin (grey edges #5A6B7B, light furniture, circle badges).
  - date: 2026-10-23
    note: >-
      v2 — wave-2 owner review ("незрозуміло чого така широка"). Narrowed the
      diagram: the principal → policy → resource tiers now sit in CONSECUTIVE
      lanes (actors / edge / router) so there are no empty lanes padding the
      columns apart, and the single-member trust-box caption was shortened (its
      detail kept in the Legend) so caption-fit no longer sizes the box to
      ~1100px and pushes the chain far right. The policy and resource columns
      moved from x≈1130 / 1350 to x≈580 / 800 — the chain reads tightly with no
      inter-column dead space. Coordinate-free spec change only. Title v1→v2.
  - date: 2026-10-23
    note: >-
      v3 — wave-4 ITEM 3 (owner: "7, 9, 10 наклались"). Markers 9 and 10 (the
      two policy → resource grant edges) overlapped in the narrow policy →
      resource gap because r-data sat on the top resource row and r-compute on
      the bottom, so e9 (pol-exec[top] → r-compute[bottom]) and e10
      (pol-data[bottom] → r-data[top]) CROSSED and dropped both markers into the
      crossover. Pinning r-compute to the top resource slot and r-data to the
      bottom makes e9 and e10 two parallel non-crossing horizontals, so marker 9
      sits on the top row and marker 10 on the bottom (~160px apart). Marker 7
      (on the Scheduler → execution-policy edge) is a separate corridor and is
      now clearly legible apart from 9/10. Coordinate-free resource-slot pin;
      semantics unchanged. Title v2→v3.
  - date: 2026-10-23
    note: >-
      Seventh-wave sweep (1.11.0): rebuilt BYTE-IDENTICAL, regression-checked
      clean. Prior-wave marker overlaps (7/9/10) remain resolved; no new
      routing change under SYS-B/SYS-A. All gates 0 ERROR/CRITICAL. Version
      held.
tags:
  - aws
  - sep
  - access
  - iam
  - security
  - 870325637521
  - eu-central-1
related_docs:
  - 03-sep-account-landscape.diagram.md
  - 08-network-crossaccount.diagram.md
  - INVENTORY-STATE.md
---

# SEP production AWS account — IAM access (security review)

## Overview

This access diagram is the security-review view of identity and access in the Syndicate Education Platform (SEP) production AWS account `870325637521` in `eu-central-1`. It answers one question an auditor asks: who can assume what, and what does that grant reach. Rather than drawing all 27 IAM roles as an exploded mesh, it aggregates them into a small principal to policy to resource chain read left to right, which is what the access diagram type is for. The 27 roles collapse to five service-principal families grouped by their trust principal (the AWS service allowed to assume the role) plus one human-assumable principal, two policy families, and two resource families — ten drawn nodes, within the access node cap of twelve. Every node is derived from the read-only inventory `iam.json` (keys `role_count`, `external_trust_analysis`, `execution_role_map`) collected 2026-10-07, never invented. The one human principal, `se-sandbox-admin`, sits in a neutral trust-boundary box because its trust is scoped to named users, not an AWS service.

## Main Content

The five service-principal families are Lambda (13 roles trusting `lambda.amazonaws.com`), Batch (8 job and execution roles trusting `ecs-tasks.amazonaws.com`), EC2 instance roles (3, including `syndicate-server` and `strapi-ec2-role`, trusting `ec2.amazonaws.com`), the API Gateway role `se-AWSGatewayRoleForSQS`, and the EventBridge Scheduler role `se-one-time-scheduler-role`. Each family assumes one of two policy families: service-execution grants (CloudWatch Logs, ECR pull, Batch submit) and data or resource-access grants (S3, DynamoDB, SQS, Secrets Manager, RDS). The policies in turn grant onto two resource families: the platform data stores and the compute or container resources (ECR images, an `eks:DescribeCluster` scoped to the local cluster arn only). The one critical trust finding, preserved verbatim from `external_trust_analysis`, is that no SEP role trust policy references an external account principal — every cross-account relationship is realised via VPC peering, not IAM role trust.

## Troubleshooting

The geometry is generated from the coordinate-free spec in `scripts/build_12_sep_access.py`; never hand-edit the `.drawio`. If the layout engine prints a `container-padding` or `container-dead-space` warning on the trust-boundary box, it is because that box holds a single human principal and sits beside the service-principal lane — both are advisory warnings on a flow diagram and do not block publication. If `access-aggregation` fires, the drawn node count has exceeded the cap of twelve: collapse another principal or policy family rather than splitting the diagram. If a principal, policy, or resource icon renders as an empty box, the `principal` / `policy` / `resource` roles have not landed from the FEAT-001 bootstrap; re-run the workspace bootstrap so the IAM Role, IAM Permissions, and Generic Application glyphs resolve. If the policy-to-resource markers crowd each other, keep the two resource families on separate rows (compute top, data stores bottom) so the two grant edges stay parallel and their markers stay apart. Re-run the lint, icon-verify, and raster gates after any change, and read the exported PNG to confirm every icon renders.

## Anti-patterns

Do not draw all 27 roles as individual nodes: an un-aggregated access view is an exploded mesh the `access-aggregation` rule rejects, and it hides the real grant structure. Do not label the trust-boundary box as cross-account IAM trust — SEP has none; the box holds human principals restricted by an `aws:userid` allow-list, and the cross-account links live in `08-network-crossaccount` as VPC peerings. Do not substitute a look-alike icon for a principal or policy; the IAM Role and IAM Permissions resource icons are correct and must resolve through the mappings.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_12_sep_access.py
#   rule-engine-export-raster 12-sep-access.drawio
```

## See Also

The companion as-built `03-sep-account-landscape` shows the same account's deployed services, and `08-network-crossaccount` carries the VPC peerings that realise every cross-account relationship this access view deliberately does not draw as IAM trust. The authoritative inventory is `INVENTORY-STATE.md` and the `iam.json` snapshot under `inventory-aws-870325637521-eu-central-1-2026-10-07_2118`, whose `execution_role_map` is the source of the five service-principal families and `external_trust_analysis` the source of the no-external-trust finding. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the identity role mappings, `diagram-standards.md` for lane order and edge routing, `diagram-lint.md` for the access lint profile and the `access-aggregation` node cap, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
