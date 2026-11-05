---
id: 01b-sep-context-c4-v4
title: SEP system context — C4 rendering
kb_namespace: cloud-architecture
section: generated-diagrams
category: diagram
status: draft
updated: 2026-10-23
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-22
diagram_class: flow
diagram_type: context
change_log:
  - date: 2026-10-23
    note: >-
      v4 — FEAT-003 (Syndicate Server two-component model). The in-account
      Syndicate Server C4 box caption now names both logical components over two
      lines, "Syndicate Server / (Education Extension + Syndi)", above its
      "[Container: EC2 host]" line, so the reader knows one EC2 carries two
      components (EE sandbox lifecycle = diagram 05, Syndi support = diagram 07).
      The box is NOT split into two and stays inside the SEP account boundary.
      The component line is kept narrow (two lines) so its caption band clears
      marker 5. Hand-authored source edited directly (no relayout); only the
      caption text and the title version changed. Title v3→v4.
  - date: 2026-10-22
    note: v1 — new C4-style rendering of the SEP system context added in the 1.11.0 regeneration (WS4 C4 boxes, native skin). Same actors and systems as 01-sep-context, drawn as neutral C4 Container boxes with no provider icons.
  - date: 2026-10-23
    note: v2 — Task-4/Task-5 node + edge changes mirroring 01. The Syndicate Server C4 box ("EC2 host") moved INSIDE the SEP account boundary as the in-account control plane; the boundary grew to enclose it with padding. The deprecated external EPM-CMTR / "Syndicate task manager" (legacy Jenkins) box and its edge are removed, the flow markers renumbered to nine, and the License Manager (marker 8) and AI (marker 9) edges re-pinned on SEP's right face so they nest and no longer cross.
  - date: 2026-10-23
    note: >-
      v3 — sixth-wave licence-path correction (owner step 21), mirroring 01.
      Flow line 8 now reads "License Manager -> SEP
      (sep-lm-synchronization-queue -> se-management-api-handler)"; edge e8 is
      flipped sep->lm → lm->sep and re-pinned contract-legal (exit License
      Manager bottom, floor lane, up the left corridor, enter SEP left),
      crossing-free with e6 and e9. The ESM 5fe731e5 is confirmed inventory, so
      only the onward relay stays a draft note. Flow line 2 appends "(se-ui-api
      REST)". Title v2→v3.
  - date: 2026-10-23
    note: >-
      Seventh-wave sweep (1.11.0): rebuilt BYTE-IDENTICAL, regression-checked
      clean. No routing change appeared under SYS-B/SYS-A; all gates 0
      ERROR/CRITICAL. Version held.
tags:
  - c4
  - context
  - sep
  - aws
  - architecture
related_docs:
  - 01-sep-context.diagram.md
  - 02-sep-summary.diagram.md
---

# SEP system context (C4 rendering)

## Overview

This is the C4-style rendering of the Syndicate Education Platform system context — the same actors and external systems as `01-sep-context`, but drawn as neutral C4 Container boxes rather than cloud service glyphs. Each box carries a `<name>\n[Container: <tech>]` label with no provider icon, following the C4 Container grammar, so the diagram reads as a technology-agnostic context view a stakeholder can follow without knowing the AWS icon set. It is a separate triple from `01-sep-context`; that AWS-glyph context is unchanged, and the two are complementary views of one system. The system under design is the SEP platform (AWS Lambda / Batch) inside the account boundary `870325637521 / eu-central-1`, which now also contains the Syndicate Server ("EC2 host") — the in-account control plane that drives the sandbox and organisation lifecycle. The human actors Student and Operator, the LMS and Keycloak identity systems, and the external systems MongoDB Atlas, License Manager, and the AI providers all sit outside the boundary, each a neutral box. The deprecated external EPM-CMTR / "Syndicate task manager" is removed. The 1.11.0 native skin (grey edges, light furniture, circle markers) is applied.

## Main Content

Reading the relationships numbered 1 through 9: a Student opens the Syndicate UI or launches via the LMS through the edge; the edge (CloudFront) serves the UI and forwards API calls to SEP; an Operator drives SEP through the management API or CLI; the LMS launches SEP over LTI 1.0/1.1; and Keycloak validates the corporate SSO token for SEP. On the outbound side, SEP reads and writes application data in MongoDB Atlas over VPC peering; SEP exchanges messages with the in-account Syndicate Server over SQS for the sandbox and organisation lifecycle; the License Manager sends to SEP (the sep-lm-synchronization-queue relayed to the se-management-api-handler Lambda, so marker 8 runs License Manager to SEP, shown dashed); and SEP calls the AI providers (Bedrock / DIAL) for the Syndi and Angry EdA assistants. Because the boxes carry no provider icon, the technology of each container is stated in its `[Container: ...]` stereotype line instead — Person, LMS / LTI, OIDC IdP, CDN / DNS, MongoDB, EC2 host, EPAM licensing, and LLM platform.

## Troubleshooting

The C4 box labels are intentionally long: the `[Container: <tech>]` stereotype line is part of the C4 grammar, so the `node-label-length` WARNING on these boxes is expected and does not block publication — it is the shape of a C4 Container label, not a defect. This diagram is `diagram_class: flow`, so it keeps the twelve-node cap and the numbered-flow-marker convention; with eleven nodes it is within budget. If a box renders with a cloud glyph instead of the neutral C4 look, the renderer was resolved through `resolve_icon` instead of the replicated `_c4_box_renderer` — the whole point of the C4 style is that no `resIcon` or `image=assets` token appears in the source. The License Manager relationship runs License Manager to SEP (marker 8): the sep-lm-synchronization-queue event-source mapping (5fe731e5) to the se-management-api-handler Lambda is confirmed inventory, so the edge direction is faithful; only the onward relay beyond that handler stays a draft note, carried as a callout term in the Legend.

## Anti-patterns

Do not add a provider icon to any box — a C4 Container diagram states the technology in the stereotype line, not with a cloud glyph, and mixing the two defeats the technology-agnostic reading this view exists to give. Do not draw the external systems (MongoDB Atlas, License Manager, the AI providers) inside the SEP account boundary; only SEP's own containers — the platform and the in-account Syndicate Server — belong inside it, exactly as in `01-sep-context`. Keep the License Manager edge running License Manager to SEP (the confirmed ESM direction) and dashed only for the onward-relay draft note; do not reverse it back to SEP to License Manager. Do not merge this triple into `01-sep-context`; the two are deliberately separate renderings of one context so a reader can pick the glyph view or the C4 view. Do not hand-edit the `.drawio` coordinates; regenerate from the build script instead.

```python
# Regenerate the triple (never hand-edit the .drawio):
#   python3 scripts/build_01b_sep_context_c4.py
#   rule-engine-export-raster 01b-sep-context-c4.drawio
```

## See Also

The companion glyph view is `01-sep-context`, which renders the identical set of actors and systems with AWS service icons, MongoDB Atlas's brand leaf, Keycloak's brand mark, and a vendor-neutral license glyph; this C4 rendering trades those glyphs for neutral boxes and explicit `[Container: <tech>]` stereotypes. The flow summary `02-sep-summary` carries the request-path shape of the platform one level down from this context. The provider-neutral rules this diagram obeys are in the always-on steering: `diagram-standards.md` for the C4 layering and progressive-disclosure guidance, the lane order, and the edge-routing conventions, `diagram-lint.md` for the flow-class severities (including why the C4 label length is a WARNING, not an ERROR), and `kb-frontmatter.md` for this companion's required frontmatter. The C4 box renderer replicates `draw_cli._c4_box_renderer`, so this hand-built script stays faithful to the engine's own `--style c4` output.
