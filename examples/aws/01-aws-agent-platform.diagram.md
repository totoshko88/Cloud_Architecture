---
id: aws-agent-platform-diagram-v1
title: AWS Agent Platform Architecture
kb_namespace: cloud-architecture
section: reference-architectures
category: diagram
status: published
updated: 2026-09-28
owner: platform-engineering
author: rule-engine
next_review_date: 2027-03-28
diagram_class: flow
tags:
  - aws
  - bedrock
  - agent-platform
  - golden-example
  - service-scope
  - resource-icons
related_docs:
  - 00-MANIFEST.md
---

# AWS Agent Platform Architecture

## Overview

The AWS agent platform is the reference workload for the `aws` Provider Profile.
It demonstrates correct **service scope placement**: VPC-scoped services (EKS,
RDS, ALB) are placed inside the VPC boundary, while regional managed services
(Lambda, SQS, S3, Bedrock, Secrets Manager) are placed outside the VPC but
inside the Account boundary. This accurately represents how these services are
deployed and accessed — regional services use AWS backbone endpoints, not VPC
network paths. The diagram also demonstrates the use of **Resource Icons**
(`Res_*`) for specific instances (Lambda function, S3 bucket, SQS queue, RDS
instance) alongside Architecture Icons (`Arch_*`) for service categories. This
is the aws golden example: it exercises service scope rules, icon conventions,
and passes all CRITICAL and ERROR lint rules.

## Main Content

The diagram places nodes according to their deployment scope. Inside the VPC
boundary: the EKS cluster (`agent-eks-cluster`) receives traffic via the ALB
(`agent-alb`), and the RDS database (`agent-conversation-db`) stores persistent
data. Outside the VPC but inside the Account: Lambda (`agent-tool-invoker`)
processes requests, SQS (`agent-task-queue`) handles async messaging, Bedrock
(`agent-bedrock-llm`) provides LLM inference, Secrets Manager (`agent-api-secrets`)
stores credentials, and S3 (`agent-artifact-store`) stores artifacts. Edges that
cross the VPC boundary (ALB→Lambda, Lambda→RDS) visually demonstrate how
regional services communicate with VPC resources via AWS PrivateLink or VPC
endpoints. The icon note at the bottom documents when to use Resource Icons
versus Architecture Icons.

## Troubleshooting

If services appear misplaced, consult the Service Scope Classification in
`provider-profiles.md`. VPC-scoped services (EC2, EKS workers, RDS, ElastiCache,
ALB/NLB) require subnets and belong inside the VPC boundary. Regional services
(Lambda, S3, SQS, Bedrock, Secrets Manager) are accessed via AWS PrivateLink or
VPC endpoints and belong outside the VPC but inside the Account boundary. If the
Linter reports an `icon-resolved` error, verify each `image=` path points to an
existing file under `assets/vendor/aws-icons/`. Resource Icons use the path
format `Resource-Icons_*/Res_<Category>/Res_<Service>_<Resource>_48.svg`, while
Architecture Icons use `Architecture-Service-Icons_*/Arch_<Category>/48/
Arch_<Service>_48.svg`. A `container-padding` finding means nodes are too close
to boundary edges — ensure at least 30 pixels of padding on all sides. If edges
cross boundaries unexpectedly, check that VPC endpoint connections are drawn
correctly: regional services connect to VPC resources via endpoint interfaces,
not direct network paths. For `node-count` errors, ensure the diagram stays
within the 12-node limit for flow-class diagrams.

## See Also

This companion document pairs with `01-aws-agent-platform.drawio` and its
exported raster `01-aws-agent-platform.drawio.png` to complete the mandatory
artifact triple required by diagram-lint rules. The Service Scope Classification
table in `provider-profiles.md` provides the authoritative reference for which
services belong inside versus outside the VPC boundary for each of the five
provider profiles (AWS, Azure, GCP, OCI, generic). The diagram-standards section
titled "Service Scope Placement" defines the visual layout rules for VPC-scoped,
regional, and global/edge services, including the lane ordering convention. For
AWS icon conventions and resolution order, consult `asset-packs.md` which
documents when to use Resource Icons (for specific resource instances like a
particular Lambda function or S3 bucket) versus Architecture Icons (for service
categories in general). The multi-region landscape example
`02-aws-ha-multiregion-landscape.drawio` demonstrates these same scope rules
applied to a larger, more complex architecture with multiple availability zones
and cross-region replication patterns.
