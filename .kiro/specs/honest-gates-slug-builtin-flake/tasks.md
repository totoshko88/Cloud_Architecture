# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Ambiguity Test Never Collides With A Built-in Slug
  - **CRITICAL**: This test MUST FAIL on the unfixed test generator - failure confirms the flake exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after the generator is constrained
  - **GOAL**: Surface the counterexample that demonstrates the flake exists
  - **Scoped PBT Approach**: For this deterministic collision, scope the property to the concrete failing cores — each single-token AWS built-in slug (`eks`, `s3`, `rds`, `sqs`, `lambda`, `bedrock`) with `prefixes=('Amazon', 'AWS')` — so it reproduces the reported counterexample `core='eks'`
  - Build the same two-file AWS pack as `test_ambiguous_exact_slug_is_unresolved_with_candidates` in `tests/test_fetch_properties.py`, then assert `resolve_asset('aws', <builtin-slug>, idx).source == 'unresolved'` (the current, pre-fix expectation) — see Bug Condition and Fix Checking in design.md
  - Run test against the UNFIXED generator/resolver
  - **EXPECTED OUTCOME**: Test FAILS — `resolve_asset` returns `source='builtin'` (e.g. `mxgraph.aws4.eks`) instead of `'unresolved'` (this is correct — it proves the flake exists and confirms the root cause)
  - Document the counterexample found (e.g. "resolve_asset('aws','eks',idx).source == 'builtin', expected 'unresolved'") to confirm the resolution-order interaction in `src/rule_engine/asset_index.py::resolve_asset` (~lines 559–581) vs `_BUILTIN_STENCILS['aws']` (~line 469)
  - Mark task complete when the test is written, run, and the failure is documented
  - _Requirements: 1.1, 1.2_

- [x] 2. Write preservation property tests (BEFORE constraining the generator)
  - **Property 2: Preservation** - Non-Built-in Ambiguity And Slug Retention Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe on the UNFIXED suite: a non-built-in ambiguous core (e.g. `core='vpc'`, `prefixes=('Amazon','AWS')`) already resolves to `source='unresolved'` with both display names in `candidates`
  - Observe on the UNFIXED suite: `test_slug_retains_meaningful_words` (R6.6, Property 26 leg 1) passes and meaningful words survive vendor-stripping
  - Write/confirm property-based tests capturing these observed behaviors from the Preservation Requirements in design.md (a non-built-in ambiguous slug → `unresolved` + candidates; meaningful words retained in slugs)
  - Property-based testing generates many cases for stronger preservation guarantees
  - Run tests on the UNFIXED suite
  - **EXPECTED OUTCOME**: Tests PASS (this confirms the baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on the unfixed suite
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. Fix for the under-constrained `_core_token` test strategy (test-only, no production changes)

  - [x] 3.1 Constrain the `_core_token` strategy and add the built-in-priority contract test
    - In `tests/test_fetch_properties.py`, extend the `from rule_engine.asset_index import (...)` block to also import `_BUILTIN_STENCILS` (reference the real table; do NOT hardcode a divergent copy so a future built-in addition cannot silently re-open the flake)
    - Constrain `_core_token` (~line 432) so its `.filter(...)` also rejects any `t in _BUILTIN_STENCILS['aws']`, in addition to the existing `_MEANINGFUL_WORDS` and `_STRIP_TOKENS` exclusions
    - Add a new deterministic unit test (Property 3) that builds an index where a built-in slug (`eks`) is ALSO ambiguous and asserts `resolve_asset('aws', 'eks', idx).source == 'builtin'` with the stencil id set and `asset_path`/`candidates` unused — documenting built-in priority (step 1 of the `asset-packs.md` resolution order) as a deliberate contract
    - Do NOT modify `src/rule_engine/asset_index.py` — the resolver and `_BUILTIN_STENCILS` are unchanged
    - _Bug_Condition: isBugCondition(core) — core is a single-token slug in `_BUILTIN_STENCILS['aws']` (design.md Bug Condition)_
    - _Expected_Behavior: expectedBehavior — the fixed generator never yields a built-in slug, so the ambiguity test reaches the resolver's ambiguous path (design.md Correctness Properties, Property 1 & Property 3)_
    - _Preservation: Preservation Requirements from design.md (R6.6 retention, non-built-in ambiguity, production code unchanged)_
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Ambiguity Test Never Collides With A Built-in Slug
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior; when the generator no longer yields built-in slugs, `test_ambiguous_exact_slug_is_unresolved_with_candidates` reaches the ambiguous path
    - Also run the new built-in-priority contract test (Property 3) added in task 3.1
    - Run the exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms the flake is resolved) and the Property 3 contract test PASSES (`source='builtin'`)
    - _Requirements: 2.1, 2.2_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Built-in Ambiguity And Slug Retention Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run the preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions) — non-built-in ambiguity still `unresolved`, R6.6 retention unchanged, `src/rule_engine/asset_index.py` unchanged
    - Confirm all tests still pass after the fix
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run the full `tests/test_fetch_properties.py` module and confirm the Property 26 family is green
  - Run the repository test suite (`pytest`) to confirm no regressions from the test-only change
  - Confirm no diff exists under `src/rule_engine/asset_index.py`
  - Ensure all tests pass, ask the user if questions arise
