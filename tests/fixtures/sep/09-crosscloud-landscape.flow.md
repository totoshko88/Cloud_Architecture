---
id: 09-crosscloud-landscape-flow
title: SEP cross-cloud landscape — numbered Flow narrative
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram-flow
status: draft
updated: 2026-10-28
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-23
change_log:
  - date: 2026-10-28
    note: >-
      Re-synced to the v19 landscape (Wave 13 consistency fix 03 ⇄ 09). Added
      step 27 — ECS strapi (migrating EC2->ECS) persists Strapi content to RDS
      sep-strapi-pg (new edge e29), under a "SEP internal data-flow cont." group
      header. Markers stay contiguous 1..27. modular-cli and GuardDuty were also
      added to the landscape as supporting nodes (no edge, no numbered step).
  - date: 2026-10-28
    note: >-
      Re-synced to the v18 landscape (Wave 12). Added step 4 — the global AWS
      WAF web ACL syndicate_education_cloudfront_waf protects the CloudFront
      distribution (new edge e28, marker 4). Markers renumbered to a contiguous
      1..26: the WAF step takes 4 and old steps 4..25 shift to 5..26. Group
      ranges are now 1-5 / 6-16 / 17-21 / 22-26. Step 23 (the nuke fleet)
      refined to "Nuke fleet = AWS Batch cleanup of sandbox accounts, driven by
      the Syndicate Server Education Extension (EE); SEP + Batch verify".
  - date: 2026-10-23
    note: >-
      Re-synced to the v16 landscape (FEAT-003). The EC2 Syndicate Server node
      caption now reads "Syndicate Server (Education Extension + Syndi)" — one
      in-account host, two logical components (EE sandbox lifecycle = diagram 05,
      Syndi support = diagram 07), never split into two nodes. The numbered Flow
      list is unchanged (it stays in lockstep with the drawio FLOW tuple); only
      the prose acknowledges both components. No queue direction changed — the
      SQS → Syndicate Server consume edge (step 25) is inventory-consistent.
  - date: 2026-10-23
    note: >-
      Re-synced to the v14 landscape (FEAT-002). MongoDB Atlas moved into its own
      "External datastore — MongoDB Atlas" band and the EC2 syndicate-server now
      reads/writes it as a new step 17 (edge e27). The markers were renumbered to
      a CONTIGUOUS 1..25 (VARIANT A): the retired 18/19 gap is gone, e27 takes 17,
      and old 17/20/21/22/23/24/25/26 shift down to 18/19/20/21/22/23/24/25.
      Flow-accuracy caption fixes applied: step 2 (CloudFront fronts only
      se-ui-api), step 7 (Lambda submits Batch directly), step 9 (EventBridge
      ACE-only), step 14 (DynamoDB CiTerraformStateLocks CI/Terraform lock),
      step 20 (LM -> SQS -> management-api-handler, no Syndicate relay), step 25
      (SQS -> Syndicate Server is local, no peering). Group ranges are now
      1-4 / 5-15 / 16-20 / 21-25.
  - date: 2026-10-23
    note: >-
      Re-synced to the v12 landscape (wave-2). VARIANT 1: ED-KRSB (183631338639)
      is now drawn as an account BOX containing a nested EKS cluster service
      node; the step terminates on that EKS service node (the flat "KTM EKS dev"
      node and the word "dev" are gone).
  - date: 2026-10-23
    note: >-
      Re-synced to the v11 landscape (ITEM 3 + Task-4). The KTM AWS Batch to EKS
      student-cluster public-endpoint path replaced the EPM-CMTR and CICD peer
      accounts. The DIAL / License / sandbox steps now read from the Syndicate
      Server drawn INSIDE the SEP account.
tags:
  - aws
  - sep
  - cross-cloud
  - flow
  - landscape
related_docs:
  - 09-crosscloud-landscape.diagram.md
  - 02-sep-summary.diagram.md
---

# SEP cross-cloud landscape — numbered Flow

## Overview

The `09-crosscloud-landscape` canvas intentionally carries only the Legend: on a
dense "everything" as-built the on-canvas Flow box is dropped
(`flow_steps="document"`) and the Legend takes the top slot, so the diagram stays
legible. This file holds the full numbered data flow that would otherwise crowd
the canvas. Every marker drawn on an edge of the landscape (1-27, contiguous)
is covered in the Numbered Flow section below, grouped by subsystem — ingress
and identity, the SEP internal data-flow, the external integrations, and the
sandbox-management cleanup context. The CloudFront distribution is protected by
the global AWS WAF web ACL syndicate_education_cloudfront_waf (step 4), drawn in
the edge band outside the account. MongoDB Atlas sits in its own
datastore band, read and written by both the Lambda application (step
17) and the EC2 Syndicate Server (step 18), which is the SEP control plane and
drives the full sandbox account lifecycle. Read
this list alongside the landscape
raster `09-crosscloud-landscape.drawio.png`: each numbered badge on the canvas
maps to the matching step here, so a reviewer can follow the request and
lifecycle paths across every account and cloud without the canvas carrying the
prose.

## Main Content

The numbered steps are grouped into four subsystems that match the landscape's
left-to-right bands. Ingress and identity (steps 1-5) cover how students and
operators reach the platform through CloudFront — protected by the global AWS
WAF web ACL — the API Gateways, Route 53, and the Keycloak and LMS identity
path. The SEP internal data-flow (steps 6-16) is
the production AWS account's request and governance skeleton — API Gateway into
Lambda, Lambda submitting Batch jobs directly, Bedrock, the S3, RDS, and the
DynamoDB CI/Terraform state-lock, and the CloudWatch, EventBridge, SSM and KMS
plane. The external integrations (steps 17-21) are the cross-account and
cross-cloud paths over VPC peerings and public endpoints — the Lambda and the
EC2 Syndicate Server both reading and writing MongoDB Atlas, the ED-KRSB EKS
cluster, the DIAL AI proxy, and the License Manager path into the SQS sync
queue. The sandbox-management context (steps 22-26) is out-of-WAFR-scope
cleanup: the nuke fleet — AWS Batch cleanup of sandbox accounts, driven by the
Syndicate Server Education Extension (EE), with SEP plus Batch verifying — and
the Syndicate Server that both provisions and tears them down.

## Numbered Flow

Ingress & identity (1-5):

1. Students / Operators reach syndicate.education via CloudFront (4 distributions)
2. CloudFront fronts ONLY the REST API se-ui-api (7cipwpsrx5); the other 4 API Gateways are not behind CloudFront
3. Route 53 (acct 323549576358) resolves syndicate.education to CloudFront
4. AWS WAF web ACL syndicate_education_cloudfront_waf (global / us-east-1) protects the CloudFront distribution
5. Keycloak SSO federates identity; LMS (learn.epam.com) launches tasks via LTI to the REST API

SEP internal data-flow (6-16):

6. API Gateway invokes the SEP Lambda handlers (13 functions)
7. Lambda enqueues work on SQS (14 queues) — async
8. Lambda submits AWS Batch jobs directly (STM / SRE / KTM / ACE / Voiceover, 5 CE); Batch uses its own built-in job queue
9. Batch pulls container images from ECR (5 repos)
10. EventBridge rules + schedules trigger Batch runs — ONLY for ACE jobs that can be scheduled (not all Batch)
11. Lambda calls Bedrock foundation models (Angry EdA)
12. Lambda / Batch write task artifacts / outputs to S3 (25 buckets)
13. Lambda / Strapi persist content to RDS sep-strapi-pg (VPC-scoped)
14. Batch / SQS run metrics flow to CloudWatch alarms (async)
15. DynamoDB table CiTerraformStateLocks is the CI/Terraform state-lock (not a CloudWatch/EventBridge governance store)
16. SSM Parameter Store + KMS hold the JWT salt / SSO secret for the authorizer

External integrations (17-21):

17. Lambda reads/writes MongoDB Atlas over peering pcx-0e257b23d337fda0b (781849312837, .246.0/24)
18. EC2 syndicate-server reads/writes the PRIMARY learner data in MongoDB Atlas (PROD_SEP_Server) over peering pcx-0e257b23d337fda0b
19. KTM AWS Batch reaches the EKS student cluster development-dev over the PUBLIC endpoint (ED-KRSB 183631338639)
20. Syndicate Server (Syndi), inside the SEP account, calls the EPAM DIAL AI proxy ai-proxy.lab.epam.com
21. License Manager (652063929809) -> SQS se-lm-synchronization-queue -> se-management-api-handler Lambda (ESM 5fe731e5)

Sandbox-management context (22-26):

22. Sandbox-mgmt org (533267139808) runs the nuke fleet on AWS Batch (eu-west-1); org members forward events to central Logging (650251687330) EventBridge to SQS FIFO
23. Nuke fleet = AWS Batch cleanup of sandbox accounts, driven by the Syndicate Server Education Extension (EE); SEP + Batch verify — purges AWS (222 accts) / Azure (202 subs) / GCP (org 1090110766254)
24. Syndicate Server provisions resources in the sandbox fleet — reads the SEP SQS lifecycle queues to create sandbox resources (AWS / Azure / GCP)
25. Syndicate Server drives the FULL sandbox account lifecycle (provision + cleanup) via the Sandbox-mgmt org
26. Syndicate Server (Syndi) consumes the SEP SQS lifecycle queues (local — inside the SEP account, no peering)

SEP internal data-flow cont. (27):

27. ECS strapi (migrating EC2->ECS) persists Strapi content to RDS sep-strapi-pg (VPC-scoped, intra-VPC)

## Troubleshooting

If a numbered badge on the canvas has no matching step in the Numbered Flow
section, the edge marker set and this list have drifted — regenerate the triple
from `scripts/build_09_crosscloud_landscape.py` (the `FLOW` tuple and the `EDGES`
markers are the single source) and re-sync this file. If a step references a
peering id or account number that the inventory no longer shows, reconcile
against `INVENTORY-STATE.md` rather than editing this list in isolation. The
canvas carries no Flow box by design, so an empty on-canvas `flow-legend` WARNING
from the linter is expected for `09-crosscloud-landscape.drawio` and is not a
defect. Do not move this narrative back onto the canvas: the landscape is dense
and the Flow box crowded it, which is exactly why it was externalized to this
file in v10. Keep the numbered list and the drawn edge markers in lockstep so a
reviewer can always trace a badge to its step.

## See Also

The landscape this flow describes is `09-crosscloud-landscape.diagram.md` and its
raster `09-crosscloud-landscape.drawio.png`, which carries the full as-built
inventory and names its summary via `summary_of: 02-sep-summary`. The paired flow
summary `02-sep-summary` carries the request-path shape of the same system, so a
reader can start from the shape and drill into this full narrative. The
authoritative inventory behind every numbered step is `INVENTORY-STATE.md`, whose
section 8 covers the cross-cloud relationships and section 9B the open owner
questions that may still reshape a few edges. The always-on steering rules that
govern the numbered-flow convention are in `diagram-standards.md` under
*Numbered Flow Legend* and in `diagram-lint.md` under the `flow-legend` rule,
which this externalized list satisfies for the dense landscape case.
