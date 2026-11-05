---
id: 11-hybrid-eks-v4
title: SEP cross-account EKS deployment (native AWS, brand service icons)
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-11-04
owner: platform-engineering
author: diagram-author
next_review_date: 2027-05-04
diagram_class: landscape
diagram_type: deployment
summary_of: 02-sep-summary
change_log:
  - date: 2026-10-22
    note: v1 — new hybrid AWS + Kubernetes deployment diagram added in the 1.11.0 regeneration (WS3 per-node provider override, native skin). SEP AWS side in built-in aws4 glyphs; the student EKS clusters in real kubernetes-profile glyphs as a sibling boundary.
  - date: 2026-10-22
    note: v2 — native/brand-icon rework (owner variant b). Every AWS node now draws with its native-colour AWS service icon (image=assets/vendor/aws-icons/...); the two EKS clusters render as the native AWS EKS service box (managed_k8s), not a blue k8s glyph. In-cluster ArgoCD carries its own octopus brand mark and Keycloak its brand mark; Gitbud is named in the label. The student EKS block is a neutral AWS account-style sibling boundary, no longer the k8s-blue cluster box. The provider=kubernetes override is dropped.
  - date: 2026-10-23
    note: >-
      v3 — sixth-wave flow-accuracy correction (owner step 7). Edge e2 is
      re-pointed sep-sqs->sep-batch → sep-lambda->sep-batch: the SEP Lambda
      submits the AWS Batch job directly (se-ktm-job-definition) and Batch uses
      its own built-in job queue; e1 (sep-lambda->sep-sqs) stays the async
      enqueue of the ktm verification queue. Flow marker 1 and marker 2 text are
      corrected to match. SQS stays connected via e1, so no node-connectivity
      regression. Icons, containers and geometry otherwise unchanged. Title
      v2->v3.
  - date: 2026-10-23
    note: >-
      Seventh-wave sweep (1.11.0): rebuilt BYTE-IDENTICAL, regression-checked
      clean under SYS-B/SYS-A. All gates 0 ERROR/CRITICAL. Version held.
  - date: 2026-11-04
    note: >-
      v4 — renamed hybrid to cross-account EKS (there is no on-prem). Account
      183631338639 is drawn as a peer_account group, not an on-premises lane.
      sep-batch now uses the batch role (AWS Batch icon, not EKS). Lambda, SQS
      and S3 sit in a declared eu-central-1 region container outside the VPC
      (regional services); Batch stays in the VPC. ArgoCD edge corrected to
      ArgoCD to cluster (e7). SQS gains a consumer edge (e9, KTM shared cluster;
      assumption, confirm with the owner). Fixes the scope-placement and
      caption-outside-container ERRORs.
tags:
  - aws
  - kubernetes
  - eks
  - cross-account
  - sep
  - deployment
  - brand-icons
related_docs:
  - 02-sep-summary.diagram.md
  - 08-network-crossaccount.diagram.md
  - 06-flow-task-verification.diagram.md
---

# SEP cross-account EKS deployment

## Overview

This landscape is the cross-account deployment view (there is no on-prem) of how the Syndicate Education Platform reaches the student EKS clusters that run its task-verification stack. In v2 (owner variant b) it is a NATIVE AWS diagram with brand service icons, not a kubernetes-profile hybrid: every AWS-side node draws with its native-colour AWS service icon (`image=assets/vendor/aws-icons/...`) via `resolve_icon(role, "aws")`, so the S3 is green, the Lambda orange, and the ALB purple. The two EKS clusters in the peer account `183631338639` (the ED-KRSB / KTM clusters) render as the native AWS EKS service box (`managed_k8s` → Amazon-Elastic-Kubernetes-Service), not a blue Kubernetes glyph. The facts come from the read-only inventory snapshot of account `183631338639` (`containers.json`, `loadbalancing.json`): one active EKS cluster `development-dev` fronted by the internet-facing `development-dev-ingress-alb`, reached over its public endpoint (`publicAccessCidrs 0.0.0.0/0`). The paired summary is `02-sep-summary`, named via `summary_of`.

## Main Content

The SEP AWS account holds the verification workflow: a Lambda orchestrator enqueues async work on SQS (the ktm verification queue) and separately submits the AWS Batch job (`se-ktm-job-definition`, AWS Batch icon) directly — Batch uses its own built-in job queue, not SQS — and Batch stores task artifacts in S3. Lambda, SQS and S3 are regional and sit in the region box outside the VPC; Batch runs inside the VPC. The KTM shared cluster consumes the SQS queue (flow 9, an assumption to confirm). Batch then reaches the student cluster over the public EKS endpoint, fronted by the ingress ALB. The EKS block holds the ALB, the two cluster nodes (`development-dev` and the KTM shared cluster) drawn as native AWS EKS boxes, and the in-cluster workloads behind them: ArgoCD reconciling (deploying to) the development-dev cluster and Keycloak / Gitbud running as StatefulSets. ArgoCD and Keycloak carry their own brand marks; Gitbud has no faithful asset, so it is named in the label. The EKS block is NOT nested inside the AWS VPC: foreign-leaf nesting is deferred, so it is a disjoint sibling `peer_account` boundary drawn as a neutral grey AWS account group, connected by cross-account public-endpoint edges.

## Troubleshooting

If an AWS node renders as an empty box, its `image=assets/vendor/aws-icons/...` asset was not fetched; `resolve_icon(role, "aws")` resolves the path from the YAML mapping, but the SVG must be present for the PNG to render. The `verify-icon --strict` gate reports 0 unresolved for all nine vertices (native EKS, native-colour AWS, the ArgoCD octopus under `assets/vendor/custom/argocd.svg`, and Keycloak under `assets/vendor/opensource-colorized/keycloak.svg`). If ArgoCD or Keycloak render blank, confirm the `argocd` and `keycloak` roles are present in `mappings/local/` and bundled mappings respectively. The EKS block is a sibling boundary, not nested in the VPC; drawing it inside the VPC would misstate the public-endpoint reach and hit the deferred foreign-leaf-nesting path. The block is a neutral AWS account-group box, so it must not carry the k8s-blue `#326CE5` stroke any more.

## Anti-patterns

Do not nest the EKS block inside the AWS VPC — foreign-leaf nesting is deferred, and the clusters are reached over a public endpoint, so a nested box would misrepresent both the feature state and the real network path. Do not draw the EKS clusters with a blue kubernetes-profile glyph here; v2 is native AWS, so the clusters wear the native AWS EKS service box. Do not substitute a look-alike icon for ArgoCD, Keycloak, or Gitbud; ArgoCD and Keycloak carry their real brand marks and Gitbud is named in the label (no faithful asset exists). Do not redraw those in-cluster workloads as separate EC2 or load-balancer resources; they are reachable only through the ingress ALB. Do not treat the public-endpoint reach as a VPC peering; it is an internet-facing path (`publicAccessCidrs 0.0.0.0/0`). Do not hand-edit the `.drawio` coordinates; regenerate from the coordinate-free spec instead.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_11_hybrid_eks.py
#   rule-engine-export-raster 11-hybrid-eks.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the platform and this landscape names it via `summary_of`, so neither ships orphaned. The task-verification flow `06-flow-task-verification` carries the step-by-step verification path this deployment serves, and the network view `08-network-crossaccount` shows the same EKS clusters reached over public endpoints alongside the four VPC peerings. The authoritative inventory behind the cluster, its ingress ALB, and the public-endpoint reach is the account `183631338639` snapshot (`containers.json`, `loadbalancing.json`). The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the AWS service-scope classification and container conventions, `diagram-standards.md` for the North-South deployment orientation, sibling-boundary nesting, padding, and edge-routing conventions, `diagram-lint.md` for the landscape-class severities, `asset-packs.md` for the AWS and owner-supplied brand icon resolution (the `argocd` and `keycloak` roles), and `kb-frontmatter.md` for this companion's required frontmatter.
