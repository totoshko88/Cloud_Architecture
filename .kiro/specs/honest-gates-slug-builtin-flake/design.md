# honest-gates-slug-builtin-flake Bugfix Design

## Overview

The property-based test
`tests/test_fetch_properties.py::test_ambiguous_exact_slug_is_unresolved_with_candidates`
(honest-gates Property 26, Requirement R6.7) intermittently fails on the
Hypothesis counterexample `core='eks', prefixes=('Amazon', 'AWS')`: it asserts
`r.source == 'unresolved'` but the resolver returns `'builtin'`.

The production resolver is correct. `resolve_asset` in
`src/rule_engine/asset_index.py` follows the documented resolution order from
`asset-packs.md` ("Icon Resolution Order"): (1) a curated built-in stencil, then
(2) an official asset file, then (3) unresolved. The ambiguous-slug fail-honest
path lives inside step 2. When the vendor-stripped slug is `eks` — a curated
built-in — step 1 fires first and returns `source='builtin'`, so the ambiguity
recorded in step 2 is never reached.

The defect is in the **test generator**. The `_core_token` Hypothesis strategy
filters out `_MEANINGFUL_WORDS` and `_STRIP_TOKENS`, but not the curated
built-in stencil slugs in `asset_index._BUILTIN_STENCILS['aws']`. The
single-token members of that table (`eks`, `s3`, `rds`, `sqs`, `lambda`,
`bedrock`) can therefore be drawn as a `core`, colliding with step 1 of the
resolver. (`secrets-manager` is two tokens, so it can never be produced as one
core token and is not part of the collision set.)

The fix is minimal and confined to the test file: constrain `_core_token` to
also exclude any slug in `asset_index._BUILTIN_STENCILS['aws']` (referencing the
real table so a future built-in addition cannot silently re-open the flake), and
add a new test that pins the built-in-over-ambiguous priority as a deliberate
contract. **No production code changes.**

This is a pre-existing latent flake surfaced by — but not caused by — the
placement-and-gates 1.9.0 full-suite run; it reproduces on committed `HEAD`
independent of that work.

## Glossary

- **Bug_Condition (C)**: The test's `_core_token` strategy draws a core token
  that is also a single-token curated AWS built-in stencil slug, making the
  R6.7 ambiguity test collide with step 1 of the resolver.
- **Property (P)**: For any generated case of the R6.7 ambiguity test, the
  generated collision slug is never a built-in stencil slug, so the resolver
  reaches its ambiguous path and returns `source='unresolved'`.
- **Preservation**: The production resolver, the R6.6 slug-retention behaviour,
  and the fail-honest R6.7 behaviour for non-built-in ambiguous slugs all stay
  exactly as they are — the fix touches only the test generator and adds a test.
- **`_core_token`**: The Hypothesis strategy at `tests/test_fetch_properties.py`
  (~line 432) generating a lowercase string of length 3–8, filtered against
  `_MEANINGFUL_WORDS` and `_STRIP_TOKENS`.
- **`test_ambiguous_exact_slug_is_unresolved_with_candidates`**: The Property 26
  leg-2 test (R6.7) that builds a two-file AWS pack colliding on one
  vendor-stripped slug and asserts the resolver returns `unresolved`.
- **`_BUILTIN_STENCILS`**: The curated table in
  `src/rule_engine/asset_index.py` (~line 467) mapping a provider's known
  vendor-stripped slugs to built-in draw.io stencil ids; `['aws']` =
  `{eks, lambda, s3, rds, sqs, secrets-manager, bedrock}`.
- **`resolve_asset`**: The resolver in `src/rule_engine/asset_index.py`
  (~lines 559–581) that returns a `ResolvedAsset` by the documented order:
  built-in → official-asset → unresolved.

## Bug Details

### Bug Condition

The bug manifests when the `_core_token` strategy draws a core token equal to a
single-token curated AWS built-in stencil slug. The test then constructs an
index in which that slug is genuinely ambiguous and asserts that
`resolve_asset` returns `source='unresolved'`; but `resolve_asset` consults
`_BUILTIN_STENCILS` before the ambiguous map, so it correctly returns
`source='builtin'` and the assertion fails.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type CoreToken (a value the _core_token strategy can yield)
  OUTPUT: boolean

  RETURN input IN _BUILTIN_STENCILS['aws'].keys()
         AND countTokens(input) = 1        // single-token, so drawable as one core
END FUNCTION
```

Equivalently, the offending core set is
`{eks, s3, rds, sqs, lambda, bedrock}` — every single-token key of
`_BUILTIN_STENCILS['aws']`. `secrets-manager` is excluded because it is two
tokens and `_core_token` yields a single token.

### Examples

- `core='eks'`, `prefixes=('Amazon', 'AWS')` — the reported counterexample. The
  index records `eks` as ambiguous (first two asserts pass), but
  `resolve_asset('aws', 'eks', idx)` returns `source='builtin'`
  (`mxgraph.aws4.eks`), so `assert r.source == 'unresolved'` fails.
- `core='s3'`, `prefixes=('AWS', 'Amazon')` — same failure via
  `mxgraph.aws4.s3`.
- `core='rds'` / `core='sqs'` / `core='lambda'` / `core='bedrock'` — same
  failure, each colliding with its built-in stencil id.
- `core='vpc'` (a non-built-in single-token core) — expected behaviour: the slug
  is ambiguous, no built-in matches, and `resolve_asset` correctly returns
  `source='unresolved'` (the test passes; this input is NOT in the bug
  condition).

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- The production resolver `resolve_asset` and its resolution order (built-in →
  official-asset → unresolved) are unchanged — no `src/` file is edited.
- The R6.6 slug-retention behaviour (`test_slug_retains_meaningful_words`,
  Property 26 leg 1) is unchanged.
- The R6.7 fail-honest behaviour for a non-built-in ambiguous slug is unchanged:
  it still returns `unresolved` with the full candidate list.

**Scope:**
All inputs that do NOT satisfy the bug condition are completely unaffected by
this fix. This includes:
- Any ambiguous slug that is not a curated built-in stencil slug.
- Any built-in stencil slug reached through normal (non-ambiguous) resolution.
- All slug-normalization and meaningful-word retention behaviour (R6.6).

The actual expected correct behaviour is defined in Correctness Properties
below.

## Hypothesized Root Cause

Based on the confirmed reading of both files, the cause is singular and
verified:

1. **Under-constrained test strategy (confirmed root cause)**: `_core_token`
   (`tests/test_fetch_properties.py` ~line 432) filters only against
   `_MEANINGFUL_WORDS` and `_STRIP_TOKENS`. It does not exclude
   `asset_index._BUILTIN_STENCILS['aws']`, so a single-token built-in slug can
   be drawn as the collision `core`.

2. **Resolution-order interaction (correct, by design)**: `resolve_asset`
   (`asset_index.py` ~lines 559–581) checks `_BUILTIN_STENCILS` before the
   `ambiguous` map. For a built-in slug it returns `source='builtin'` — step 1
   of the documented order in `asset-packs.md`. This is correct production
   behaviour, not a defect.

3. **Non-determinism (why it is a flake)**: Hypothesis reaches the counterexample
   only on some seeds/shrink paths, so the failure is intermittent rather than
   constant, which is why the 1.9.0 full-suite run surfaced a defect that was
   already latent on `HEAD`.

## Correctness Properties

Property 1: Bug Condition - Ambiguity Test Never Collides With A Built-in Slug

_For any_ input where the bug condition holds (isBugCondition returns true — the
drawn `core` is a single-token curated AWS built-in stencil slug), the fixed
`_core_token` strategy SHALL NOT produce that core, so
`test_ambiguous_exact_slug_is_unresolved_with_candidates` SHALL reach the
resolver's ambiguous path and observe `r.source == 'unresolved'` with both
distinct display names in `r.candidates`, for every generated case.

**Validates: Requirements 2.1**

Property 2: Preservation - Non-Built-in Ambiguity And Slug Retention Unchanged

_For any_ input where the bug condition does NOT hold (isBugCondition returns
false — an ambiguous slug that is not a built-in stencil slug, or any R6.6
slug-retention case), the fixed test suite SHALL produce the same result as the
original: an ambiguous non-built-in slug still resolves to `unresolved` with its
candidate list, and meaningful words are still retained in vendor-stripped
slugs. The production `resolve_asset` result is identical because production
code is unchanged.

**Validates: Requirements 3.1, 3.2, 3.3**

Property 3: Built-in Priority - A Built-in Slug That Is Also Ambiguous Resolves To Built-in

_For any_ index in which a curated AWS built-in stencil slug (e.g. `eks`) is
ALSO recorded as ambiguous, `resolve_asset` SHALL return `source='builtin'` with
the built-in stencil id set and `asset_path`/`candidates` unused — the built-in
stencil (step 1 of the documented resolution order) takes priority over the
ambiguous-slug path. This documents the priority as a deliberate contract rather
than an accident.

**Validates: Requirements 2.2**

## Fix Implementation

### Changes Required

The root-cause analysis is confirmed, so the fix is minimal and test-only.

**File**: `tests/test_fetch_properties.py`

**Symbol**: `_core_token` strategy (~line 432)

**Specific Changes**:

1. **Import the built-in table**: Extend the existing
   `from rule_engine.asset_index import (...)` block to also import
   `_BUILTIN_STENCILS` (reference the real table — do NOT hardcode a divergent
   copy, so a future built-in addition cannot silently re-open the flake).

2. **Constrain `_core_token`**: Add a filter clause so the strategy also
   excludes any slug present in `_BUILTIN_STENCILS['aws']`. A single combined
   filter, for example rejecting `t` when
   `t in _MEANINGFUL_WORDS or t in _STRIP_TOKENS or t in _BUILTIN_STENCILS['aws']`.
   This keeps the R6.7 intent intact (a collision slug that genuinely reaches
   the ambiguous path) while removing the built-in collision.

3. **Add a built-in-priority contract test**: Add a new, explicit test (a plain
   deterministic unit test, not property-based) that builds an index where a
   built-in slug such as `eks` is also ambiguous, calls `resolve_asset`, and
   asserts `r.source == 'builtin'` with the stencil id set and `asset_path`/
   `candidates` unused — documenting Property 3.

4. **No production changes**: `src/rule_engine/asset_index.py` is not edited.
   The resolver, `_BUILTIN_STENCILS`, and the resolution order remain exactly
   as they are.

## Testing Strategy

### Validation Approach

Two phases: first surface the counterexample on the current (unfixed) test
generator to confirm the flake reproduces, then apply the generator constraint
and the new contract test and verify the whole Property 26 family passes
deterministically with production behaviour unchanged.

Note on terminology for this bugfix: "UNFIXED code" here means the current
**test generator** (`_core_token` as it stands), since the defect is in the
test, not in `src/`. Production `resolve_asset` is already correct.

### Exploratory Bug Condition Checking

**Goal**: Surface the counterexample that demonstrates the flake BEFORE applying
the generator constraint, and confirm the root cause (a built-in slug drawn as
`core` short-circuits to `source='builtin'`).

**Test Plan**: Write a scoped property-based (or parametrized) test that drives
`test_ambiguous_exact_slug_is_unresolved_with_candidates`'s logic with `core`
pinned to each single-token AWS built-in slug and asserts the current
`unresolved` expectation. Run it against the UNFIXED generator to observe the
failure and record the counterexample.

**Test Cases**:
1. **eks collision**: `core='eks'`, `prefixes=('Amazon', 'AWS')` — reproduces
   the reported counterexample (will fail: resolver returns `builtin`).
2. **s3 / rds / sqs / lambda / bedrock collisions**: each single-token built-in
   slug as `core` (will fail identically).
3. **Non-built-in control**: `core='vpc'` — will pass, confirming the failure is
   specific to built-in slugs and not to ambiguity in general.

**Expected Counterexamples**:
- `resolve_asset('aws', 'eks', idx).source == 'builtin'` while the test expects
  `'unresolved'`.
- Cause: `resolve_asset` checks `_BUILTIN_STENCILS` before the `ambiguous` map,
  and `_core_token` failed to exclude built-in slugs.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed
generator no longer produces them, so the ambiguity test reaches the resolver's
ambiguous path.

**Pseudocode:**
```
FOR ALL core WHERE isBugCondition(core) DO      // core is a single-token built-in slug
  ASSERT core NOT IN outputs(_core_token_fixed) // generator never yields it
END FOR
// and for every case the generator CAN now yield:
FOR ALL generated_case OF test_ambiguous_exact_slug_is_unresolved_with_candidates DO
  ASSERT resolve_asset(...).source == 'unresolved'
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the
fixed test suite behaves identically to the original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT resolve_asset_fixedSuite(input) = resolve_asset_originalSuite(input)
  // R6.6 slug retention and R6.7 non-built-in ambiguity unchanged
END FOR
```

**Testing Approach**: Property-based testing is well suited to preservation
here because R6.6 and the R6.7 non-built-in case are already universal
properties over generated inputs. Since production code is untouched, any
observed change would come only from the generator constraint, which by
construction only removes built-in-slug cores.

**Test Cases**:
1. **R6.6 retention preserved**: `test_slug_retains_meaningful_words` continues
   to pass unchanged.
2. **Non-built-in ambiguity preserved**: a non-built-in ambiguous slug still
   resolves to `unresolved` with its candidate list.
3. **Production unchanged**: no diff in `src/rule_engine/asset_index.py`.

### Unit Tests

- New built-in-priority contract test: `eks` (built-in) also ambiguous →
  `resolve_asset` returns `source='builtin'` with stencil id set (Property 3).
- Existing resolver unit tests for built-in, official-asset, and unresolved
  paths continue to pass.

### Property-Based Tests

- Fixed `test_ambiguous_exact_slug_is_unresolved_with_candidates` passes for all
  generated cases (Property 1).
- `test_slug_retains_meaningful_words` (R6.6) passes unchanged (Property 2).

### Integration Tests

- Run the full `tests/test_fetch_properties.py` module and confirm the
  Property 26 family is green.
- Run the repository test suite (`pytest`) to confirm no regressions elsewhere
  from the test-only change.
