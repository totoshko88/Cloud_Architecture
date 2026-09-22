---
inclusion: always
---

# Knowledge Base Frontmatter & Formatting Rules

This steering document defines the mandatory YAML frontmatter and the Markdown
formatting rules that **every generated knowledge-base document** must satisfy
before it is emitted to the knowledge base. These rules are enforced by the
Diagram Generator and validated by the Linter (`diagram-lint.md`,
rule `frontmatter`, severity CRITICAL). They implement Requirement 8
(AC 8.1–8.11) and are always-on per Requirement 11 AC1.

The rules below govern documents the engine **generates** (companion documents,
versioned inventory documents, and other KB Markdown). This steering file itself
is a rule specification, not a generated KB document.

## Required Frontmatter

Every generated Markdown document MUST begin with a YAML frontmatter block
(delimited by `---` fences) containing **all twelve** of the following keys.
Every key MUST be present and MUST have a non-empty value. (AC 8.1)

| Key | Required | Value format / constraint |
|---|---|---|
| `id` | yes | Non-empty stable identifier string |
| `title` | yes | Non-empty document title string |
| `kb_namespace` | yes | Non-empty namespace string |
| `section` | yes | Non-empty section string |
| `category` | yes | Non-empty category string |
| `status` | yes | Enumeration: exactly one of `draft`, `review`, `published` |
| `updated` | yes | ISO 8601 calendar date `YYYY-MM-DD` |
| `owner` | yes | Non-empty owner string |
| `author` | yes | Non-empty author string |
| `next_review_date` | yes | ISO 8601 calendar date `YYYY-MM-DD` |
| `tags` | yes | List with between 1 and 20 entries inclusive |
| `related_docs` | yes | List with between 0 and 20 entries inclusive |

Value rules, restated for precision:

- `status` MUST be one of exactly `draft`, `review`, or `published`. Any other
  value is invalid.
- `updated` and `next_review_date` MUST match the ISO 8601 date format
  `YYYY-MM-DD`. Timestamps, relative dates, and other formats are invalid.
- `tags` MUST contain **1 to 20** entries inclusive (empty list invalid).
- `related_docs` MUST contain **0 to 20** entries inclusive (empty list allowed).

### Frontmatter Template

```yaml
---
id: <stable-id>
title: <document title>
kb_namespace: <namespace>
section: <section>
category: <category>
status: draft            # draft | review | published
updated: 2025-01-15      # YYYY-MM-DD
owner: <owning team or person>
author: <authoring agent or person>
next_review_date: 2025-07-15   # YYYY-MM-DD
tags:                    # 1–20 entries
  - <tag>
related_docs: []         # 0–20 entries
---
```

## Document Length

Each generated Markdown document MUST have a total length between **300 and
2000 words inclusive**. (AC 8.2)

## Required Sections

Every generated Markdown document MUST include these four sections, and each of
them MUST have a length between **100 and 200 words inclusive**. (AC 8.3, 8.7)

- `Overview` — 100–200 words
- `Main Content` — 100–200 words
- `Troubleshooting` — 100–200 words
- `See Also` — 100–200 words

## Heading Rule

Each document MUST contain **exactly one H1 heading**. Zero H1 headings and two
or more H1 headings are both invalid. (AC 8.4)

## List Nesting

List nesting MUST NOT exceed **two levels**. A third nesting level is invalid.
(AC 8.5)

## Tables

Each table MUST have **at most five columns** and MUST NOT contain merged cells.
(AC 8.6)

## Anti-patterns Section

WHERE a document contains **at least one fenced code block**, the document MUST
include an `Anti-patterns` section. A document with no fenced code block does
not require this section. (AC 8.8)

## Accept / Reject Behavior

A document is emitted to the knowledge base **only when every constraint above
is satisfied** (AC 8.11). Otherwise the document is rejected:

- IF any required frontmatter key from the required-frontmatter table is
  **absent, empty, or holds a value outside its specified format, enumeration,
  or bound**, THEN the document MUST be rejected, MUST NOT be emitted to the
  knowledge base, and an error indication MUST **name the offending key**.
  (AC 8.9)
- IF a document violates any of the constraints in **Document Length, Required
  Sections, Heading Rule, List Nesting, Tables, or the Anti-patterns Section**
  (AC 8.2–8.8), THEN the document MUST be rejected, MUST NOT be emitted to the
  knowledge base, and an error indication MUST **name the violated constraint**.
  (AC 8.10)
- WHEN all constraints in AC 8.1 through AC 8.8 are satisfied, the document MUST
  be emitted to the knowledge base. (AC 8.11)

Rejection is fail-closed: a partially conforming document is never emitted. The
Linter reports a missing or empty required frontmatter key as a CRITICAL finding
(`diagram-lint.md`, rule `frontmatter`).
