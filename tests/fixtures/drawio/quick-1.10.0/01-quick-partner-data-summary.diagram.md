---
id: 01-quick-partner-data-summary-v6
title: Quick Partner Data — data-flow summary
kb_namespace: cloud-architecture
section: quick-partner-data
category: diagram
status: review
updated: 2026-10-06
owner: Platform Team
author: Kiro
next_review_date: 2027-01-05
diagram_class: flow
diagram_type: data-flow
detailed_view: 02-quick-partner-data-landscape
tags:
  - aws
  - summary
  - flow
  - amazon-quick
  - partner-central
  - skill-builder
related_docs:
  - 02-quick-partner-data-landscape.diagram.md
  - RUNBOOK.md
  - INTEGRATION_CONFIG.md
change_log:
  - date: 2026-10-06
    note: v6 amended — column-level security removed on request; all 4 groups (incl. MARKETPLACE) have access to all datasets and topics
  - date: 2026-10-06
    note: v6 typed views, Quick workgroup with 1 GB cutoff, topics with relationships, agent Partner Data Analyst, 7 alarms, stack drift IN_SYNC
  - date: 2026-10-05
    note: v5 regenerated from inventory snapshot 2026-10-05_2305 after the audit fixes (latest views, concurrent Skill Builder, EMF alarms)
---

# Quick Partner Data — data-flow summary (v6, 2026-10-06)

## Overview

This summary shows the shape of the Quick Partner Data pipeline in AWS account
123456789012, region us-east-1, as it runs after the 2026-10-05 audit. Three
EventBridge schedules invoke one Lambda function, QuickPartnerETL. It pulls
Partner Central Selling and Benefits data, Marketplace Catalog entities, and
eleven Skill Builder Integrated Reporting datasets. The function writes each
dataset as NDJSON into a daily `dt=` partition of the S3 data lake. Two feeds
have no API and arrive as manual uploads: Partner Central certifications and
Amazon Payee Central invoices. Glue catalogues 22 tables. For each one there is
an Athena view `<table>_latest` pinned to the newest partition. Amazon Quick
reads only those views, through 22 DIRECT_QUERY datasets, the topic Acme data,
and the Quick chat agents. Per-extractor metrics drive five CloudWatch alarms
that notify the operator through SNS. The paired landscape diagram carries every
enumerated resource. This view keeps the flow to eleven nodes so a newcomer can
follow a record from source API to an answer in Quick.

## Main Content

Read the numbered markers left to right. The schedules (1) invoke the function
hourly for opportunities, at 10:00 UTC for eight small Partner, Marketplace and
Benefits datasets, and at 11:00 UTC for Skill Builder. The function pulls the
Partner and Marketplace APIs (2). It also pulls Skill Builder (3), running four
asynchronous report queries at once and dropping exact duplicate rows. It writes
NDJSON partitions (4). An operator uploads the two manual feeds straight into
the lake (5). After writing, the Lambda registers the Glue partition and re-pins
the `_latest` view (6). Because the view filter is a literal date, Athena scans
one partition (7). The 22 datasets read those views (8), so answers in topic
Acme data reflect the current snapshot rather than 90 days of history (9).
Failures, skips and missing runs raise CloudWatch alarms. Alarms send email
through SNS (10, dashed: asynchronous). No VPC exists: the Lambda runs outside
any VPC and all services are regional.

## Troubleshooting

If an answer in Quick looks many times too large, check the dataset first. It
must reference a `<table>_latest` view, not the base table. Base tables hold up
to 90 daily partitions, which inflated counts 18 to 50 times before the fix. If a
view is stale, read the `_views` key of the Lambda response. Then check the
alarm QuickPartnerETL-ExtractorFailures, which fires when a refresh fails with
the dimension `view:<table>`. For a single table, run
`tools/refresh_latest_views.py` with that table name. If Skill Builder data is
missing for a day, look for ExtractorSkipped and re-invoke only those datasets.
If no alarm fires but data stops, QuickPartnerETL-NoRuns watches the hourly
heartbeat. A manual feed shows its upload date in `dt`. Certifications and
invoices are refreshed only when someone uploads a new export, so an old `dt`
there is expected and is not a pipeline failure.

## See Also

The paired landscape diagram, `02-quick-partner-data-landscape`, draws every
resource from the inventory snapshot. It covers the three schedule rules, the
dead-letter queue, IAM roles, the CloudFormation stack, both buckets, the Quick
datasource, topics and space, and the identity provider. RUNBOOK.md holds the
operating procedures. Section 1 covers Skill Builder, sections 2 and 2a the
manual feeds, and section 2b the `_latest` views with rollback. Section 5a lists
the alarms. INTEGRATION_CONFIG.md records configuration, known issues 1 to 21,
and the audit findings of 2026-10-05. The inventory snapshot used to draw both
diagrams is under `inventory/inventory-aws-123456789012-us-east-1-2026-10-05_2305`.
Its manifest states the scope and the resources counted but not drawn. The
generator is `tools/build_architecture_diagrams.py` and the collector is
`tools/collect_inventory.py`. Regenerate both after any change to schedules,
datasets or alarms.
