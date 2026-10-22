---
id: 04-flow-lms-launch-v5
title: SEP LMS launch — LTI 1.0/1.1 launch and run management (data-flow)
kb_namespace: cloud-architecture
section: sep-architecture
category: diagram
status: draft
updated: 2026-10-17
owner: platform-engineering
author: diagram-author
next_review_date: 2027-04-17
diagram_class: flow
diagram_type: data-flow
tags:
  - sep
  - aws
  - lti
  - lms
  - data-flow
  - eu-central-1
related_docs:
  - 01-sep-context.diagram.md
  - 02-sep-summary.diagram.md
change_log:
  - date: 2026-10-17
    note: v5 — icon fidelity pass. The Student in the LMS now uses the AWS General User resource icon (a human user) instead of a neutral box. Keycloak and MongoDB Atlas brand marks unchanged.
---

# SEP LMS launch — LTI 1.0/1.1 launch and run management

## Overview

This is the runtime data-flow view of how a learner enters the Syndicate Education Platform (SEP) from a Learning Management System and how a run is managed, in the production AWS account 870325637521 in eu-central-1 (Frankfurt). It is a first-draft flow diagram, read left to right along the fixed lane order, and deliberately scoped to the launch and run-management path rather than the whole platform. The facts come from a strictly read-only inventory of the live production account and the architecture guide section on LTI launch, not from the application source: ui-api is a REST API Gateway with no gateway authorizer, lti-adapter and management-api-handler are Lambda functions, and MongoDB Atlas is the external application datastore reached over VPC peering. Nothing on the canvas is invented. The three external parties — the student in the LMS, Keycloak SSO, and MongoDB Atlas — are not AWS resources and are drawn outside the account boundary; Atlas carries MongoDB's own brand-green leaf, Keycloak its colorized Keycloak brand mark, and the student is now drawn with the AWS General User resource icon because it is a human user.

## Main Content

The flow has seven numbered steps. A student in the LMS (learn.epam.com or elearn.epam.com) initiates an LTI 1.0/1.1 launch, which reaches ui-api, the REST API Gateway. Critically, ui-api carries no gateway authorizer: it routes the launch straight to lti-adapter, and all authorization happens inside that Lambda. lti-adapter validates the launch (OAuth fields, nonce, HMAC-SHA1 signature) and creates a task-scope session. It validates the corporate identity token with Keycloak SSO, then reads and writes run, enrolment, and session state in the PROD_SEP database in MongoDB Atlas over the VPC peering link. For run and enrolment coordination it calls management-api-handler, which also writes run and enrolment state to Atlas. On task completion elsewhere, lti-adapter returns the grade or score back to the LMS as an asynchronous callback — the dashed back-edge to the student.

## Troubleshooting

If a node looks wrong, remember the scope: this is the launch-and-run path, not the full platform, so socket-api, SQS, Batch, Bedrock, and S3 are intentionally absent — see the summary and landscape views for those. MongoDB Atlas is drawn with its real brand-green leaf, Keycloak with its colorized Keycloak brand mark, and the student in the LMS with the AWS General User resource icon (a human user). None of the three is a faked look-alike; where no faithful icon exists the engine keeps the honest representation rather than substituting a wrong glyph. The authorizer placement is deliberate and matters: ui-api has no gateway authorizer, so if you are tracing an auth failure, look inside lti-adapter, not at the gateway. The grade callback (step 7) is a back-edge to an external actor and leaves lti-adapter on its left face to clear the management-api-handler icon directly below it; that is the honest route, not a routing mistake. If the raster looks oversized, confirm the flow export budget (width at or under 1600px).

## Anti-patterns

Do not place the student, Keycloak, or MongoDB Atlas inside the AWS Account boundary to tidy the edge crossings: only SEP's own cloud resources belong inside it, and an edge that crosses the boundary from an external party is correct. The student is a human user and so wears the AWS User resource icon even though it is external; Atlas wears MongoDB's own brand leaf and Keycloak its own Keycloak brand mark. Do not substitute a look-alike AWS service glyph for a non-AWS system — that misstates the architecture. Do not move the authorization to the gateway in the drawing to make it look conventional; ui-api has no authorizer and lti-adapter owns validation. The title cell encodes provider, workload, boundary, region, date, and version:

```text
aws SEP LMS launch — 870325637521 / eu-central-1 | 2026-10-17 | v5
```

Do not hand-edit the emitted `.drawio` coordinates; change the declaration in the build script and regenerate, then re-run the lint gate.

## See Also

This diagram is one of the mandatory triple: the drawing source 04-flow-lms-launch.drawio, its exported raster 04-flow-lms-launch.drawio.png, and this companion. It sits alongside the context view 01-sep-context, which shows SEP and all of its external systems at the widest C4 level, and the container-level summary 02-sep-summary, which collapses the whole request shape into nine representative nodes with its landscape counterpart. Use this flow when the question is specifically how an LMS launch moves end to end and how a run is coordinated; use the summary or landscape when the question is what is deployed. The authoritative facts behind every node and edge come from the live production inventory of account 870325637521 in eu-central-1 and the MongoDB Atlas EPM-EDAI-PROD snapshot that records the VPC peering link. The lane order, service-scope placement, neutral external representation, numbered flow legend, and class-aware lint severities this artifact follows are defined in the workspace steering directory.
