---
id: 12-sep-access-v4
title: SEP production AWS account — IAM access (security review)
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-11-04
owner: platform-engineering
author: diagram-author
next_review_date: 2027-05-04
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
  - date: 2026-11-04
    note: >-
      v4 — phase-2 fix on the finalized rule-engine 1.13.0. The EventBridge Scheduler service principal is no longer parented to the human Trust boundary box: the builder passes the spec membership to build_diagram (membership_of(placed)), so only se-sandbox-admin is a member and the box wraps that one human principal. Principals are re-slotted by the policy they attach (Scheduler / EC2 on top, Lambda / Batch in the middle, API Gateway / se-sandbox-admin at the bottom, order manual), so the Scheduler edge (7) is a short top entry that no longer crosses the title band or a caption. The data policy and data-store family sit on the human principal's row, so edge 8 is a straight run. The two resource families now draw with the ECR service icon and the AWS General Database glyph, captioned with the real services, instead of the generic application glyph. Crossings 4 to 0. Title v3 to v4.
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

This access diagram is the security-review view of identity and access in the Syndicate Education Platform (SEP) production AWS account `870325637521` in `eu-central-1`. It answers one question an auditor asks: who can assume what, and what does that grant reach. Rather than drawing all 27 IAM roles as an exploded mesh, it aggregates them into a small principal to policy to resource chain read left to right, which is what the access diagram type is for. The 27 roles collapse to five service-principal families grouped by their trust principal (the AWS service allowed to assume the role) plus one human-assumable principal, two policy families, and two resource families, ten drawn nodes within the access node cap of twelve. Every node comes from the read-only inventory `iam.json` (keys `role_count`, `external_trust_analysis`, `execution_role_map`) collected 2026-10-07. The one human principal, `se-sandbox-admin`, is the only member of a neutral trust-boundary box, because its trust is scoped to named users rather than an AWS service.

## Main Content

The principals are stacked by the policy family they attach. At the top are the EventBridge Scheduler role `se-one-time-scheduler-role` and the EC2 instance roles (3, including `syndicate-server` and `strapi-ec2-role`), which carry only service-execution grants. In the middle are Lambda (13 roles trusting `lambda.amazonaws.com`) and Batch (8 job and execution roles trusting `ecs-tasks.amazonaws.com`), which carry both families. At the bottom are the API Gateway role `se-AWSGatewayRoleForSQS` and `se-sandbox-admin`, which carry data or resource-access grants. Execution grants (CloudWatch Logs, ECR pull, Batch submit) reach the container and compute family, drawn with the ECR icon (ECR images and an `eks:DescribeCluster` scoped to the local cluster arn). Data grants reach the aggregated data stores, drawn with the AWS General Database glyph (S3, DynamoDB, RDS, Secrets Manager, SSM). The critical trust finding from `external_trust_analysis` is preserved: no SEP role trust policy references an external account principal, and every cross-account relationship is realised via VPC peering, not IAM role trust.

## Troubleshooting

The geometry is generated from the coordinate-free spec in `scripts/build_12_sep_access.py`; never hand-edit the `.drawio`. Membership is explicit: the builder passes `membership_of(placed)` to `build_diagram`, so only `se-sandbox-admin` is parented to the trust-boundary box. If a service principal appears inside that box, the membership argument was dropped and the builder fell back to geometric parenting. The spec uses `order="manual"`, so the declared slots are drawn as written; if you add a principal, slot it next to the principals that attach the same policy family, or the fan-in starts to cross. If `access-aggregation` fires, the drawn node count has exceeded the cap of twelve: collapse another family rather than splitting the diagram. If the Database glyph renders as an empty box, the workspace role `data_store_family` in `mappings/local/aws-icons.yaml` is missing. One `collinear-edges` WARNING remains where the Lambda and Batch fan-ins share a short corridor; it is advisory. Re-run lint, icon-verify, and raster gates after any change, and read the exported PNG.

## Anti-patterns

Do not draw all 27 roles as individual nodes: an un-aggregated access view is an exploded mesh the `access-aggregation` rule rejects, and it hides the real grant structure. Do not put a service principal inside the trust-boundary box, and do not label that box as cross-account IAM trust; SEP has none. The box holds the one human principal restricted by an `aws:userid` allow-list, and the cross-account links live in `08-network-crossaccount` as VPC peerings. Do not draw an aggregated resource family with a single service icon such as S3; that claims the family is one service. Use the family glyph and name the services in the caption.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_12_sep_access.py
#   rule-engine-export-raster 12-sep-access.drawio --max-width 1440  # keeps the flow height/size budget
```

## See Also

The companion as-built `03-sep-account-landscape` shows the same account's deployed services, and `08-network-crossaccount` carries the VPC peerings that realise every cross-account relationship this access view deliberately does not draw as IAM trust. The authoritative inventory is `INVENTORY-STATE.md` and the `iam.json` snapshot under `inventory-aws-870325637521-eu-central-1-2026-10-07_2118`, whose `execution_role_map` is the source of the five service-principal families and `external_trust_analysis` the source of the no-external-trust finding. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the identity role mappings, `diagram-standards.md` for lane order and edge routing, `diagram-lint.md` for the access lint profile and the `access-aggregation` node cap, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
