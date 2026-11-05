---
id: 01-sep-context-v15
title: SEP System Context (C4) — AWS 870325637521 / eu-central-1
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-11-03
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
related_docs:
  - 01b-sep-context-c4
  - 02-sep-summary
  - 03-sep-account-landscape
  - 04-flow-lms-launch
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
  - date: 2026-11-03
    note: >-
      v15 — phase-2 fix on rule-engine 1.13.0, builder-only. Flow markers renumbered in
      flow order (Student to WAF 1, WAF to CloudFront 2, CloudFront to SEP 3). The single
      AI edge is split into two: Bedrock from SEP (Lambda, Angry EdA) and DIAL from the
      Syndicate Server EC2 (Syndi). Legend built with legend_lines_for, so no undrawn
      Inner boundary line. Account caption wrapped to two lines and the SEP column moved
      right so the CloudFront drop no longer crosses it. Syndicate Server label shortened,
      detail moved to a callout. The SEP to LMS grade-passback return now rides a bus
      above the row. Crossings 4 to 0. EPM-CMTR and Jenkins are not drawn (owner decision
      2026-11-03). Earlier change_log entries that describe routes or numbering from v9
      to v14 are historical and no longer match the file.

---

# SEP System Context (C4)

## Overview

This is the C4 System Context view for the Syndicate Education Platform (SEP), a SaaS running in AWS account 870325637521 in eu-central-1. It answers one question: who uses SEP and which external systems it talks to. Inside the SEP account boundary sit two nodes: the SEP platform (the Lambda application, drawn with the custom SEP mark) and the Syndicate Server EC2 control plane. Everything else is an actor or external system outside the boundary. The canonical ingress path is Client, WAF, CloudFront, then the SEP targets (S3 se-ui, se-ui-api, Lambda URL), collapsed here into the one SEP node. The WAF is attached to CloudFront only, never to API Gateway. The diagram stays within twelve nodes, plus one callout text box that is not a node.

## Main Content

Flow markers follow the ingress order: the Student reaches the WAF (1), the WAF relays to CloudFront (2), CloudFront serves SEP (3). The Operator (4), the LMS over LTI 1.0/1.1 (5) and Keycloak SSO (6) call SEP. SEP reads application data in MongoDB Atlas over peering (7) and drives the Syndicate Server over SQS (8). License Manager syncs into SEP through the sep-lm-synchronization-queue (9). Two separate AI paths are drawn: SEP calls Bedrock for Angry EdA (10), and the Syndicate Server calls the EPAM DIAL API for Syndi (11). SEP returns grades to the LMS over a return bus above the row (12). The Syndicate Server provisions and cleans up the multi-cloud sandbox fleets (13, dashed). A callout names the two components that one EC2 host carries.

## Troubleshooting

If the account caption overprints a node or an edge, widen the boundary or wrap the caption and re-run the builder; never move shapes by hand in the drawio. The builder is .build-tools/build_01_sep_context.py and the engine is 1.13.0. If the Legend lists an Inner boundary, check that it is built with legend_lines_for. If a numbered marker sits on a caption, shorten the label or slide the marker. The SEP left face carries four arrivals (Operator, LMS, Keycloak, License Manager) and the engine reports entry-thirds as a warning; this is inherent to the context view. The License Manager return is long because it must clear the AI node and the actor lanes. Neither Jenkins nor EPM-CMTR belongs here.

## Anti-patterns

Do not draw one AI node fed by a single generic SEP edge: Bedrock comes from Lambda and DIAL from the Syndicate Server. Do not attach the WAF to API Gateway, and do not send a client straight to the REST API. Do not put external systems inside the account boundary, and do not give a node a look-alike icon. Keep long explanations in a callout instead of the node label. Do not hand-edit the drawio: change the builder and regenerate, so the result stays reproducible. The title cell encodes provider, workload, boundary, region, date and version, for example:

```text
aws SEP context — 870325637521 / eu-central-1 | 2026-11-03 | v15
```

## See Also

This diagram is one of the mandatory triple: 01-sep-context.drawio, its raster 01-sep-context.drawio.png, and this companion. It is the widest level of a progressive-disclosure set. The summary is 02-sep-summary, the as-built landscape is 03-sep-account-landscape, the LMS launch flow is 04-flow-lms-launch, and the alternative C4 rendering is 01b-sep-context-c4. Facts come from the SEP account snapshot inventory-aws-870325637521-eu-central-1-2026-10-31_2044 and the MongoDB Atlas snapshot that records the VPC peering link. The workspace steering rules define the conventions followed here: the fixed lane order, the numbered Flow legend, the neutral representation of non-AWS external systems, and the callout overlay term documented in the Legend. Read the summary first for the shape of the platform, then the landscape for every deployed resource. The canonical facts that keep diagrams 01 to 04 consistent (one ingress path, two AI paths, Strapi on ECS and RDS, the Syndicate Server as the SQS consumer) live in the shared canonical facts note kept with the phase-2 task files.
