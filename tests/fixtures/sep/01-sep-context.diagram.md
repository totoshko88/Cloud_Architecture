---
id: 01-sep-context-v6
title: SEP System Context (C4) — AWS 870325637521 / eu-central-1
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-17
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-17
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
  - date: 2026-10-17
    note: v5 — icon fidelity pass. Student/Operator now use the AWS User resource icon; EPM-CMTR the AWS Organizations Account icon; Syndicate Server the EC2 icon; AI the Amazon Bedrock icon; License Manager the new license_manager icon. Student edge (e1) straightened to a clean right-centre exit. LMS kept neutral (no faithful mortarboard asset).
  - date: 2026-10-17
    note: v6 — LMS now carries a graduation-cap (mortarboard) glyph via the new education image role (hand-authored public-domain SVG under assets/vendor/education/), resolving the regen8 LMS gap. All regen8 icons preserved.
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
omitted, so reviewers can see and challenge the open questions directly here.

## Main Content

Four actors sit outside the boundary on the left: the Student and the Operator,
both drawn with the AWS General User resource icon because they are human users;
the LMS at learn.epam.com, now drawn with a graduation-cap (mortarboard) glyph,
launching over LTI 1.0/1.1; and Keycloak as the corporate SSO identity provider. The Student edge leaves the Student's right-centre as one
straight horizontal line into the edge, with no bend. The edge, CloudFront plus
DNS for syndicate.education, is drawn at the top and serves the student UI. On
the right are the external systems SEP integrates with: MongoDB Atlas (the
application datastore, over VPC peering), the Syndicate Server drawn with the EC2
icon (sandbox lifecycle and Syndi support, over SQS), EPM-CMTR in account
088595288622 drawn with the AWS Organizations Account icon, the License Manager
drawn with the AWS License Manager icon, and the AI node (Bedrock / DIAL) drawn
with the Amazon Bedrock icon. Each edge carries a numeric marker; the right-side
Flow legend describes every step in order.

## Troubleshooting

The AWS-named nodes now carry their real service icons: Student and Operator the
User icon, EPM-CMTR the Organizations Account icon, the Syndicate Server the EC2
icon, the AI node the Bedrock icon, and the License Manager the License Manager
icon (resolved through the workspace mapping and the local overlay for the new
license_manager role). MongoDB Atlas keeps its brand-green leaf, the SEP node its
custom logo, Keycloak its brand mark. The LMS now carries a graduation-cap
(mortarboard) glyph via the new education image role: a hand-authored
public-domain SVG under assets/vendor/education/, not a vendor look-alike, so it
resolves and renders without tripping icon fidelity. The License Manager edge is
dashed and marked draft-assumption because
the proven path today is License Manager to the CMTR queue, not directly to SEP;
treat marker 9 as unconfirmed. If an external box should become a cloud resource
later, move it inside the account boundary and give it the correct AWS role,
then regenerate rather than hand-editing.

## Anti-patterns

Do not place the external systems inside the AWS Account boundary to tidy up the
edge crossings: only SEP's own cloud resources belong inside it, and an edge that
crosses the boundary from an external actor is correct, not a defect. A real
resource type is still named by its service icon even when the node is external:
EPM-CMTR literally is an AWS account, the Syndicate Server is an EC2 host, and
License Manager is an AWS service, so each wears its true glyph. The LMS is a
learning system, so it wears a generic mortarboard glyph (the education role) —
a neutral learning symbol, never a specific vendor product icon, which would be
the look-alike to avoid. Do not expand the single SEP platform node into its full internal
component list here; that belongs in a container or landscape view. The title
cell encodes provider, workload, boundary, region, date, and version, for
example:

```text
aws SEP context — 870325637521 / eu-central-1 | 2026-10-17 | v6
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
