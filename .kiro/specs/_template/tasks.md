# Implementation Plan: <Feature Name>

<!--
  SPEC TEMPLATE — tasks.md
  Copy the `.kiro/specs/_template/` directory to `.kiro/specs/<feature-name>/`
  when creating a new spec, then replace every <angle-bracket placeholder> and
  resolve every TODO. Delete these HTML guidance comments before publishing.

  Task list rules (mirror the parent spec for consistency):
  - Every task is a checkbox item: `- [ ] N. <Task>` with sub-tasks `- [ ] N.M`.
  - Each leaf task ends with a `_Requirements: X.Y, X.Z_` reference line that
    traces to acceptance criteria in requirements.md.
  - Optional test sub-tasks are marked with a trailing `*` (or noted as optional).
  - Property-based test sub-tasks name the design property and add a
    `**Validates: Requirements X.Y**` line.
  - Order tasks in dependency order; each task builds on the previous ones.
-->

## Overview

<!--
  Summarize the build sequence and the implementation language/frameworks.
  State how test sub-tasks and property-based tests are treated.
-->

TODO: <Describe the implementation approach, language, and build sequence.>

## Tasks

- [ ] 1. <Top-level task: scaffold / foundational step>
  - <Concrete action or file to create>
  - <Concrete action or file to create>
  - _Requirements: <X.Y>, <X.Z>_

- [ ] 2. <Top-level task with sub-tasks>
  - [ ] 2.1 <Sub-task>
    - <Concrete action or file>
    - _Requirements: <X.Y>_
  - [ ] 2.2 <Sub-task>
    - <Concrete action or file>
    - _Requirements: <X.Y>_
  - [ ] 2.3 *Write unit tests for <thing>
    - <What the tests assert>
    - _Requirements: <X.Y>_

- [ ] 3. <Top-level task including a property-based test>
  - [ ] 3.1 <Implementation sub-task>
    - <Concrete action or file>
    - _Requirements: <X.Y>_
  - [ ] 3.2 *Write property test — <property short name>
    - **Property <N>: <property statement>**
    - **Validates: Requirements <X.Y>**

<!-- TODO: Repeat top-level tasks and sub-tasks for the full plan. -->

## Task Dependency Graph

<!--
  Group tasks into ordered execution waves. Each wave lists task ids that can run
  once the previous waves complete. Replace the placeholder ids below.
-->

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["3.2"] }
  ]
}
```
