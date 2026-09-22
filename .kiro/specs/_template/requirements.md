# Requirements Document

<!--
  SPEC TEMPLATE — requirements.md
  Copy the `.kiro/specs/_template/` directory to `.kiro/specs/<feature-name>/`
  when creating a new spec, then replace every <angle-bracket placeholder> and
  resolve every TODO. Delete these HTML guidance comments before publishing.

  Conventions (mirror the parent spec for consistency):
  - Follow EARS notation. Every acceptance criterion is a single testable
    SHALL statement that a linter or reviewer can mark pass/fail.
  - Follow the Absolute Context principle: no pronouns, no relative time
    expressions ("yesterday", "recently"), and every entity named explicitly.
  - Use ISO 8601 dates (YYYY-MM-DD) only. No relative dates.

  EARS patterns to use for each acceptance criterion:
  - Ubiquitous:   THE <system> SHALL <response>.
  - Event-driven: WHEN <trigger>, THE <system> SHALL <response>.
  - State-driven: WHILE <state>, THE <system> SHALL <response>.
  - Optional:     WHERE <feature/condition is present>, THE <system> SHALL <response>.
  - Unwanted:     IF <condition>, THEN THE <system> SHALL <response>.
-->

## Introduction

<!--
  1–3 short paragraphs. State what this feature is, who consumes it, and the
  problem it solves. Name the major components/outputs at a high level.
-->

TODO: <One-paragraph summary of the feature and the problem it solves.>

TODO: <List the primary outputs or capabilities this feature delivers.>

## Glossary

<!--
  Define every domain term, component name, and enumeration used below so the
  requirements can name entities explicitly with no pronouns. One bullet per term.
-->

- **<Term>**: <Precise definition.>
- **<Component Name>**: <Responsibility of the component.>
- **<Enumeration>**: <A member of the enumeration `<value-a> | <value-b> | <value-c>`.>

## Requirements

### Requirement 1: <Requirement Name>

**User Story:** As a <role>, I want <capability>, so that <benefit>.

#### Acceptance Criteria

<!--
  Number criteria 1..N. Each is one EARS SHALL statement. Keep each atomic and
  independently testable. Add as many as the requirement needs.
-->

1. WHEN <trigger>, THE <system/component> SHALL <observable response>.
2. WHERE <condition/feature present>, THE <system/component> SHALL <observable response>.
3. IF <unwanted condition>, THEN THE <system/component> SHALL <corrective response>.
4. THE <system/component> SHALL <ubiquitous invariant>.

### Requirement 2: <Requirement Name>

**User Story:** As a <role>, I want <capability>, so that <benefit>.

#### Acceptance Criteria

1. WHEN <trigger>, THE <system/component> SHALL <observable response>.
2. IF <unwanted condition>, THEN THE <system/component> SHALL <corrective response>.

<!--
  TODO: Repeat the "### Requirement N" block for every requirement.
  TODO: Ensure each acceptance criterion is later traceable to a design section
        and to a tasks.md `_Requirements: N.M_` reference.
-->
