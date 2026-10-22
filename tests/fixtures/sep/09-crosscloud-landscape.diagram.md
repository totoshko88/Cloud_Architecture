---
id: 09-crosscloud-landscape-v6
title: SEP cross-cloud — the whole SEP world as-built landscape
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-17
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-17
diagram_class: landscape
diagram_type: deployment
summary_of: 02-sep-summary
change_log:
  - date: 2026-10-15
    note: v4 — external world re-expressed as grouped peer_account sibling boundary containers; engine Theme 37 band-grid stacks them into a compact grid above the account (canvas-utilization 16pct wide-row to ~30pct), long cross-band edges 17/18 folded into the Flow legend.
  - date: 2026-10-17
    note: v5 — icon fidelity pass. The external Syndicate Server (an EC2 host) now uses the real EC2 icon and License Manager the new license_manager icon; both stay external. Students/Operators already use the User icon and the peer accounts the Organizations Account icon. DIAL AI, LMS, and the fleet abstractions stay neutral (no faithful asset).
  - date: 2026-10-17
    note: v6 — three more faithful icons. LMS now carries a mortarboard (education role), DIAL AI the owner-supplied EPAM DIAL brand mark (dial role), and the Sandbox-mgmt + Logging org the AWS Organizations SERVICE icon (organizations role, distinct from the single-account peer_account glyph). Only the genuine non-AWS clouds / fleet abstractions stay neutral. All regen8 icons preserved.
tags:
  - aws
  - sep
  - cross-cloud
  - landscape
  - deployment
  - as-built
  - multi-account
  - multi-cloud
related_docs:
  - 02-sep-summary.diagram.md
  - 03-sep-account-landscape.diagram.md
  - 08-network-crossaccount.diagram.md
  - INVENTORY-STATE.md
---

# SEP cross-cloud — the whole SEP world as-built landscape

## Overview

This is the capstone as-built: the entire Syndicate Education Platform (SEP) world assembled on one wall so a reviewer sees every account, cloud, and fleet and how they relate at once. It is the detailed landscape companion to the `02-sep-summary` flow summary, which carries the request-path shape; this diagram carries the full system inventory. The external world is grouped into five labelled sibling boundary containers — ingress and identity edge, AWS peer accounts, identity (LMS and Keycloak), external integrations (Syndicate, DIAL, License), and the sandbox-management cleanup fleet shown as out-of-WAFR-scope context. The layout engine stacks those groups into a compact grid above the SEP production AWS account `870325637521`, which hangs below as the one fully nested core; related systems now sit one under another rather than spread across a single wide row. Every node and edge is derived from the live read-only inventory in `INVENTORY-STATE.md` (collected 2026-10-07 and 2026-10-12, owner-reviewed 2026-10-08), never invented. Dense service families collapse to one captioned node each — one Lambda node for 13 functions, one SQS node for 14 queues — with the counts carried in the Flow legend. This is a first draft pending the open owner questions in section 9B.

## Main Content

The SEP core is the only fully nested boundary: Account `870325637521` contains Region `eu-central-1`, which contains the `se` VPC `vpc-05cd5663a70d3a65c` (192.168.128.0/20). RDS `sep-strapi-pg` is the single VPC-scoped node; the regional managed services — API Gateway (4 REST plus 1 WebSocket), Lambda (13), SQS (14), EventBridge, AWS Batch (5 compute environments), ECR (5 repos), S3 (25 buckets), DynamoDB, SSM plus KMS, Bedrock, CloudWatch — sit in the Region but outside the VPC. Students and Operators carry the AWS General User icon; the AWS peer accounts the AWS Organizations Account icon — EPM-CMTR, ED-KRSB (EKS dev), and the CICD account — and Keycloak SSO its Keycloak brand mark. The Syndicate Server (EC2) and License Manager carry their real service icons. The LMS now wears a mortarboard, DIAL AI the owner-supplied EPAM DIAL brand mark, and the sandbox-management org the AWS Organizations service icon — distinct from the single-account peer glyph. Only the non-AWS clouds and fleet abstractions stay neutral boxes. MongoDB Atlas (3 databases) keeps its brand-green MongoDB leaf. The outer context band holds the sandbox-management org `533267139808`, its nuke fleet, central Logging `650251687330`, and the three fleets it purges — AWS (222 accounts), Azure (202 subscriptions), and GCP (org `1090110766254`).

## Troubleshooting

If the layout engine reports a warning, read `placed.layout_warnings` rather than hand-editing the `.drawio`; the geometry is generated from the coordinate-free spec in `scripts/build_09_crosscloud_landscape.py`, so fix the spec and regenerate. The external groups are stacked into a grid above the account by the engine band-grid: when a column would overrun the gap above the account it wraps to the right, so a crowded external world grows sideways rather than into the account body. If two heavy cross-band edges push the diagram over the landscape crossing hard-cap, fold them into the Flow legend as one representative edge per external system. An over-connected node finding means one node carries more than three edges on a face — re-source the edge from the neighbour that owns the relationship. If an icon renders as an empty box, the role is missing from the mapping or its local overlay. A real resource type keeps its service icon even when external (EC2 Syndicate Server, License Manager, peer-account and org-level Organizations glyphs), a known brand its own mark (DIAL, the LMS mortarboard); only a genuine non-AWS cloud and the fleet abstractions stay neutral and must never carry a fake AWS icon.

## Anti-patterns

Do not wire every system to every other system to prove the platform is connected: the engine caps a node at three edges per face, and a hairball hides the real data paths. Show only the genuine relationships the inventory proves, and keep the license-manager edge marked `draft-assumption` until owner question 9B Q1 resolves the LM-to-CMTR-to-SEP relay. Do not draw the external accounts, clouds, or fleets inside the SEP account boundary to avoid cross-boundary edges — an external datastore or a peer account drawn inside the VPC misrepresents the architecture. Do not substitute a look-alike AWS icon for Azure, GCP, or a whole-fleet abstraction; a neutral box is correct there. But a real resource type keeps its true icon even when external — the Syndicate Server (EC2), License Manager, and the org-level Organizations glyph wear their real service icons — and a known brand keeps its own mark: MongoDB Atlas its leaf, the DIAL proxy the owner-supplied DIAL logo, the LMS a mortarboard. Do not split this as-built into several twelve-node pages — a landscape exists to show the whole world at once; the paired `02-sep-summary` carries the simplified shape instead.

```python
# Regenerate the triple (coordinate-free; never hand-edit the .drawio):
#   python3 scripts/build_09_crosscloud_landscape.py
#   rule-engine-export-raster 09-crosscloud-landscape.drawio
```

## See Also

The paired flow summary `02-sep-summary` carries the request-path shape of the same system; this landscape names it via the `summary_of` cross-link so neither ships orphaned. The focused component views feed this assembly: `01-sep-context` for the external actors and systems, `03-sep-account-landscape` for the SEP account groupings and node naming, `04` through `07` for the request and lifecycle flows, and `08-network-crossaccount` for the VPC peerings and external accounts. The authoritative inventory behind every node and edge is `INVENTORY-STATE.md`, whose section 2 covers the SEP account, section 8 the cross-cloud relationships, and section 9B the open owner questions that may still reshape a few edges. The provider-neutral rules this diagram obeys are in the always-on steering: `provider-profiles.md` for the service-scope classification, `diagram-standards.md` for nesting, padding, lane order, and edge routing, `diagram-lint.md` for the class-aware severities a landscape escalates, `asset-packs.md` for icon resolution, and `kb-frontmatter.md` for this companion's required frontmatter.
