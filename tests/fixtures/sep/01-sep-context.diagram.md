---
id: 01-sep-context-v14
title: SEP System Context (C4) — AWS 870325637521 / eu-central-1
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-28
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-21
diagram_class: flow
diagram_type: context
tags:
  - sep
  - aws
  - context
  - c4
  - saas
  - wafr
related_docs: []
change_log:
  - date: 2026-10-23
    note: >-
      v12 — FEAT-003 (Syndicate Server two-component model). The in-account EC2
      Syndicate Server node caption now reads "Syndicate Server / (Education
      Extension + Syndi)" over two lines, so the reader knows one host carries
      two logical components (EE sandbox lifecycle = diagram 05, Syndi support =
      diagram 07). The EC2 is NOT split into two nodes and stays inside the SEP
      account. The caption was kept to two lines so the component line stays
      narrow enough to clear marker 5's badge (a single long line widened the
      caption band under the marker). Hand-authored source edited directly (no
      relayout); only the caption text and the title version changed. Title
      v11→v12.
  - date: 2026-10-17
    note: v5 — icon fidelity pass. Student/Operator now use the AWS User resource icon; EPM-CMTR the AWS Organizations Account icon; Syndicate Server the EC2 icon; AI the Amazon Bedrock icon; License Manager the new license_manager icon. Student edge (e1) straightened to a clean right-centre exit. LMS kept neutral (no faithful mortarboard asset).
  - date: 2026-10-17
    note: v6 — LMS now carries a graduation-cap (mortarboard) glyph via the new education image role (hand-authored public-domain SVG under assets/vendor/education/), resolving the regen8 LMS gap. All regen8 icons preserved.
  - date: 2026-10-21
    note: v7 — regenerated on rule-engine 1.10.12. FIX 1 — License Manager no longer carries the AWS License Manager service icon (SEP's License Manager is an EPAM licensing service in account 652063929809, not AWS); it now uses a vendor-neutral certificate/seal glyph (license_neutral role). All other icons preserved; geometry re-laid-out by the upgraded engine.
  - date: 2026-10-22
    note: v8 — regenerated on rule-engine 1.11.0 pre-release with the native skin applied (NATIVE_SKIN = Skin(furniture_stroke='light', edge_stroke='#5A6B7B', marker_badge='circle')). Edges now draw in grey #5A6B7B, the Flow/Legend furniture in light grey #B3B3B3, and each numeric flow marker as a dark #1A1A1A badge disc with a white numeral. Hand-pinned geometry and all icons byte-stable; presentation-only change.
  - date: 2026-10-23
    note: v9 — Task-4/Task-5 node + edge changes. The Syndicate Server is now drawn INSIDE the SEP account boundary as an EC2 host (compute_instance), representing the real in-account control plane (instance tagged syndicate-server, account 870325637521); the account boundary grew to enclose it with padding. The deprecated external EPM-CMTR / "Syndicate task manager" (legacy Jenkins) node and its edge are removed, and the flow markers renumbered (now nine steps). The License Manager (marker 8) and AI (marker 9) edges were re-pinned on SEP's right face so they nest and no longer cross (higher target via the outer corridor, lower via the inner), fixing the crossing of the former markers 9 and 10.
  - date: 2026-10-23
    note: v10 — FEAT-002. Marker 9 (SEP->AI) was riding the account box bottom border (the new marker-on-container-border rule, the owner's "9 наїхала на box account" finding); the SEP->AI and SEP->License-Manager corridors moved outside the account right edge so neither numeral sits on a container border. A new edge 10 was added — SEP returns task results to the LMS over LTI grade passback (Assignment-and-Grade Services) — routed from SEP's bottom face, along the canvas floor and up the left margin into the LMS left face, crossing neither the account box interior nor edge 4.
  - date: 2026-10-23
    note: >-
      v11 — sixth-wave licence-path correction (owner step 21). Flow line 8 now
      reads "License Manager -> SEP (sep-lm-synchronization-queue ->
      se-management-api-handler)"; edge e8 is flipped sep->lm → lm->sep and
      re-pinned contract-legal (exit License Manager bottom, floor lane, up the
      left corridor, enter SEP left) so it stays crossing-free with e6 and e10.
      The ESM 5fe731e5 is confirmed inventory, so only the onward relay stays a
      draft note. Flow line 2 appends "(se-ui-api REST)" naming the one REST API
      CloudFront fronts. Title v10→v11.

  - date: 2026-10-23
    note: >-
      Seventh-wave sweep (rule-engine 1.11.0, SYS-B/SYS-A/ENG-1 installed):
      rebuilt BYTE-IDENTICAL — no geometry change. Owner 01 'markers 9/10 swap
      to avoid overlap' verified RESOLVED: e9 (sep→ai) and e10 (sep→lms) exit
      on distinct bands (0.77 vs 0.51) heading opposite ways, no
      crossing/marker lint finding, so no hand-pinned SPEC tweak was needed.
      Version held (no content change).
  - date: 2026-10-28
    note: >-
      v14 — Wave 12 context additions. Two context nodes were added OUTSIDE the
      SEP account boundary: a WAF node (role waf, the global
      syndicate_education_cloudfront_waf that fronts CloudFront) in the edge
      lane left of CloudFront, and a Sandbox fleets node (role
      sandbox_multicloud, the multi-cloud AWS/Azure/GCP sandbox accounts) that
      the in-account Syndicate Server provisions and cleans up. The external
      request path now enters via the WAF (marker 1 student->WAF) which relays
      to CloudFront (marker 11 WAF->CloudFront); a dashed control edge (marker
      12) runs Syndicate Server->Sandbox fleets for the provision/cleanup
      lifecycle. WAF is a global/edge service, so it is never drawn inside the
      account/VPC. Both nodes resolve their real icons (waf, sandbox_multicloud)
      through the bundled icon tree. Flow grew to 12 steps and two Legend terms
      (WAF, Sandbox fleets) were added. Title v13->v14, date 2026-10-28. Gates 0
      ERROR/CRITICAL.
  - date: 2026-10-23
    note: >-
      v13 — tenth-wave B3 (owner re-flagged 9/10 crossing on the rendered PNG).
      The orthogonaliser had re-snapped e10's pinned bottom exit onto SEP's
      RIGHT face at nearly the same y as e9, so the two shared the right face and
      crossed. e10 (SEP->LMS, a lower-LEFT return) is re-pinned to exit the
      BOTTOM face left-of-centre (0.3, left of e7's bottom-centre) and run LEFT
      immediately down a dedicated far-left corridor (x=300, left of every
      incoming corridor and the account border) into the LMS left face; e9
      (SEP->AI, lower-RIGHT) keeps its right-face exit and right corridor. The
      exit band is now assigned by target direction, so the two diverge from SEP
      with no crossing. Gates 0 ERROR/CRITICAL. Title v12->v13.
---

# SEP System Context (C4)

## Overview

This is the C4 System Context view for the Syndicate Education Platform (SEP),
a SaaS running in AWS account 870325637521 in the eu-central-1 (Frankfurt)
region. It answers one question: who uses SEP and what external systems it
talks to. SEP itself is drawn as a single AWS Account boundary holding one
representative platform node drawn with the custom SEP brand mark; the context
level deliberately keeps the inside of the account to a single box so the
diagram stays under twelve nodes and reads on one screen. Everything else on
the canvas is an actor or an external system, drawn outside the account
boundary. The diagram is a first draft produced from the live production
inventory; where a relationship is not yet confirmed from evidence it is marked
with the draft-assumption callout term documented in the Legend rather than
omitted, so reviewers can see and challenge the open questions directly here. The
1.11.0 native skin is applied: edges are grey, the Flow and Legend furniture
light grey, and each flow marker a dark badge disc with a white numeral.

## Main Content

Four actors sit outside the boundary on the left: the Student and the Operator,
both with the AWS General User icon; the LMS at learn.epam.com with a mortarboard
glyph over LTI 1.0/1.1; and Keycloak as the corporate SSO provider. The Student
request enters via the WAF, the global syndicate_education_cloudfront_waf that
fronts CloudFront (marker 1 student to WAF, marker 11 WAF to CloudFront); the WAF
is a global/edge service drawn in the edge lane outside the account, never inside
the VPC. The edge, CloudFront plus DNS, serves the student UI. Inside the account
sit the SEP platform and the Syndicate Server, drawn with the EC2 icon as the
control plane. A dashed control edge (marker 12) runs from the Syndicate Server
to the Sandbox fleets node — the multi-cloud AWS/Azure/GCP sandbox accounts it
provisions and cleans up — drawn outside the account because those are separate
accounts, not SEP resources. On the right are the external systems: MongoDB
Atlas (over VPC peering), the License Manager with a vendor-neutral certificate
glyph that sends to SEP via the sep-lm-synchronization-queue (marker 8), and the
AI node (Bedrock / DIAL). A return edge (marker 10) carries task results to the
LMS over LTI grade passback.

## Troubleshooting

The AWS-named nodes now carry their real service icons: Student and Operator the
User icon, the Syndicate Server the EC2 icon (now drawn inside the SEP account
boundary as the control plane), and the AI node the Bedrock icon. The License
Manager is deliberately NOT an AWS service here — it is an EPAM licensing
service (account 652063929809) —
so it carries a vendor-neutral certificate-and-seal glyph (the license_neutral
role in the local overlay), never the AWS License Manager icon. MongoDB Atlas
keeps its brand-green leaf, the SEP node its custom logo, Keycloak its brand
mark, and the LMS a neutral mortarboard glyph. The License Manager edge
(marker 8) now runs License Manager to SEP: the inventory confirms the
sep-lm-synchronization-queue event-source mapping (5fe731e5) to the
se-management-api-handler Lambda, so the edge direction is faithful; only the
onward relay beyond that handler stays a draft note. The deprecated external EPM-CMTR (legacy Jenkins "Syndicate task
manager") is no longer drawn — its lifecycle role is the in-account Syndicate
Server. If an external box should become a cloud resource later, move it inside
the account boundary and give it the correct AWS role, then regenerate.

## Anti-patterns

Do not place the external systems inside the AWS Account boundary to tidy up the
edge crossings: only SEP's own cloud resources belong inside it, and an edge that
crosses the boundary from an external actor is correct, not a defect. A real
resource type is still named by its service icon: the Syndicate Server is an EC2
host in the SEP account, so it sits inside the boundary and wears the EC2 glyph.
But a node is NEVER given a look-alike icon: SEP's
License Manager is an EPAM service, not AWS, so it wears a vendor-neutral
certificate glyph, never the AWS License Manager icon. The LMS is a learning
system, so it wears a generic mortarboard glyph (the education role) — a neutral
learning symbol, never a specific vendor product icon. Do not expand the single
SEP platform node into its full internal
component list here; that belongs in a container or landscape view. The title
cell encodes provider, workload, boundary, region, date, and version, for
example:

```text
aws SEP context — 870325637521 / eu-central-1 | 2026-10-28 | v14
```

Do not drop the draft-assumption callout term from the Legend while any dashed
assumption edge remains on the canvas.

## See Also

This diagram is one of the mandatory triple: the drawing source
01-sep-context.drawio, its exported raster 01-sep-context.drawio.png, and this
companion. It is the context (widest) level of a progressive-disclosure set; the
container-level and landscape-level views of SEP drill down from here through the
summary and detailed_view cross-links once they are authored. The authoritative
facts behind every node and edge come from the live production inventory
snapshots in this workspace, in particular the SEP AWS account 870325637521
snapshot and the MongoDB Atlas EPM-EDAI-PROD snapshot that records the VPC
peering link. The diagram standards, the lint ruleset, the provider profiles,
and the knowledge-base frontmatter rules in the workspace steering directory
define the conventions this artifact follows, including the fixed lane order,
the numbered flow legend, and the neutral representation of non-AWS external
systems used throughout this context view.
