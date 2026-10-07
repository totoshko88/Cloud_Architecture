---
id: 02-quick-partner-data-landscape-v6
title: Quick Partner Data — as-built landscape
kb_namespace: cloud-architecture
section: quick-partner-data
category: diagram
status: review
updated: 2026-10-06
owner: Platform Team
author: Kiro
next_review_date: 2027-01-05
diagram_class: landscape
diagram_type: deployment
summary_of: 01-quick-partner-data-summary
tags:
  - aws
  - landscape
  - as-built
  - inventory
  - amazon-quick
  - partner-central
  - skill-builder
related_docs:
  - 01-quick-partner-data-summary.diagram.md
  - RUNBOOK.md
  - INTEGRATION_CONFIG.md
change_log:
  - date: 2026-10-06
    note: v6 amended — column-level security removed on request; all 4 groups (incl. MARKETPLACE) have access to all datasets and topics
  - date: 2026-10-06
    note: v6 typed views, Quick workgroup with 1 GB cutoff, topics with relationships, agent Partner Data Analyst, 7 alarms, stack drift IN_SYNC
  - date: 2026-10-05
    note: v5 drawn from inventory snapshot 2026-10-05_2305 (29 resources, 0 collection failures); replaces architecture.drawio v4.4
---

# Quick Partner Data — as-built landscape (v6, 2026-10-06)

## Overview

This landscape is the full as-built view of the Quick Partner Data system. It
covers AWS account 123456789012 in us-east-1. It was drawn from a read-only
inventory snapshot collected on 2026-10-05 at 23:05 UTC. That run used only
list, describe and get verbs and recorded no failures. The snapshot holds twenty-nine
records: the account, three IAM roles, one Lambda function, three EventBridge
rules, an SQS dead-letter queue, an SNS topic, two S3 buckets, the Glue
database, the Athena workgroup, CloudWatch logs and alarms, the CloudFormation
stack, and seven Amazon Quick resources. It also records five external sources
and consumers. The diagram reads top to bottom. People, manual feeds and the
identity provider sit above the account. Schedules, messaging, compute, the data
lake with its query layer, and the Quick consumption layer are inside it. The
AWS-operated source APIs and the alert recipient sit below. The two QuickSight
service roles are drawn as one node. The paired summary shows the same system as
an eleven-node flow.

## Main Content

The rules (1 to 3) invoke the Lambda, and every rule sends undeliverable events
to the dead-letter queue (4, dashed). The arrow is drawn once, from the Skill
Builder rule. The Lambda pulls Partner Central, Marketplace Catalog and Skill
Builder (5 to 7) as its execution role (9). That role has two inline policies,
one for extraction and one for the view DDL. The function writes NDJSON
partitions (10). Glue catalogues them (11), and manual uploads land in the same
lake (8). The function logs to CloudWatch for 365 days and emits metrics (12)
that feed five alarms (13), which notify SNS (14) and the operator (28). The
stack (15) owns the Lambda, its role, 18 tables and two rules. The daily rule,
the alarms, four tables and the views are out of band. Athena reads the latest
views (16, 17) and writes results with a 7-day lifecycle (18). QuickSight roles
(19) and the datasource (20 to 21) serve 22 datasets. Ten of them feed topic
Acme data (22), shared through space Acme Data (23). Topic Skill Builder has no
datasets (24). Users sign in through Identity Center (25 to 27).

## Troubleshooting

To check that this landscape still matches the account, collect a new snapshot
with `tools/collect_inventory.py`. Compare `config_digest` per resource ID with
this snapshot, then run `rule-engine-reconcile` against the regenerated diagram.
A resource that exists in the account but not in the snapshot sits outside the
stated scope. The manifest lists account-wide counts for every floor domain:
zero VPCs, EC2, load balancers, CloudFront, Route 53, WAF, EKS, ECS, EFS, FSx,
RDS, ElastiCache and Secrets Manager. It also counts eight unrelated S3 buckets,
one DynamoDB table, twenty-one personal Quick spaces, fifteen agents, twelve
flows and thirty-eight action connectors. Those are out of scope. If the
CloudFormation node disagrees with live state, run drift detection. On
2026-10-05 the only stack drift was the hourly rule input. Everything else
outside the stack is listed in the template header. If a Quick dataset node
seems wrong, `tools/repoint_datasets.py --rollback` restores the pre-audit
definitions.

## See Also

The summary `01-quick-partner-data-summary` is the eleven-node data-flow view of
the same system. Read it first, then return here for detail. The snapshot folder
`inventory/inventory-aws-123456789012-us-east-1-2026-10-05_2305` holds one JSON
file per service domain, a `resources/` subfolder per record, and a manifest
with scope, tool versions and delta instructions. RUNBOOK.md explains how to run
and recover every component drawn here, including the `_latest` view design and
its rollback in section 2b. INTEGRATION_CONFIG.md lists configuration, costs and
known issues, including the audit items 14 to 21. The template
`cloudformation.yaml` declares the stack and the out-of-band resources with
their adoption caveats. The previous diagram, `archive/architecture-v4.4-2026-09-18/architecture.drawio` v4.4
of 2026-09-18, predates the audit fixes and is superseded by this pair. The
icon styles come from `mappings/aws-icons.yaml`, with workspace roles added for
services the rule engine does not ship.
