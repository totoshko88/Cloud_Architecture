# Bugfix Requirements Document

**Feature:** honest-gates-slug-builtin-flake

## Introduction

The property-based test
`tests/test_fetch_properties.py::test_ambiguous_exact_slug_is_unresolved_with_candidates`
(honest-gates Property 26, Requirement R6.7) is a latent flake. It fails
intermittently on the Hypothesis-generated counterexample
`core='eks', prefixes=('Amazon', 'AWS')`, where the test asserts
`r.source == 'unresolved'` but the resolver returns `r.source == 'builtin'`.

The failure is a **test-strategy defect, not a production defect**. The
resolver `src/rule_engine/asset_index.py::resolve_asset` is behaving exactly as
its documented resolution order requires (`asset-packs.md` → "Icon Resolution
Order"): a curated built-in stencil (step 1) is preferred over an official
asset file (step 2) and over the ambiguous-slug fail-honest path. The test's
`_core_token` Hypothesis strategy is under-constrained: it can draw a core token
(`eks`, `s3`, `rds`, `sqs`, `lambda`, `bedrock`) that collides with a curated
built-in stencil slug in `asset_index._BUILTIN_STENCILS['aws']`, and for such a
core the resolver correctly short-circuits to `source='builtin'` before ever
consulting the ambiguous map the test is trying to exercise.

This flake is a **pre-existing latent defect** surfaced by — but not caused by —
the placement-and-gates 1.9.0 full-suite run. It reproduces identically on
committed `HEAD` independent of the 1.9.0 work. Production behaviour is correct
and MUST remain unchanged; only the test generator is corrected, plus a new test
that pins the built-in-over-ambiguous priority as a deliberate contract.

## Bug Analysis

### Current Behavior (Defect)

When the Hypothesis `_core_token` strategy in
`tests/test_fetch_properties.py` draws a core token that is also a single-token
curated AWS built-in stencil slug, the test builds an index in which that slug
is genuinely ambiguous, but `resolve_asset` returns the built-in stencil
instead of the `unresolved` result the test asserts.

1.1 WHEN the `_core_token` strategy draws a core equal to a single-token AWS
built-in stencil slug (`eks`, `s3`, `rds`, `sqs`, `lambda`, or `bedrock`) THEN
the test `test_ambiguous_exact_slug_is_unresolved_with_candidates` fails at
`assert r.source == 'unresolved'` because `resolve_asset` returns
`source='builtin'`.

1.2 WHEN Hypothesis explores the input domain across CI runs THEN the failure
appears non-deterministically (a flake), because the counterexample is only
reached on some seeds/shrink paths rather than every run.

### Expected Behavior (Correct)

2.1 WHEN the `_core_token` strategy is drawn for the R6.7 ambiguity test THEN it
SHALL exclude every slug present in `asset_index._BUILTIN_STENCILS['aws']`, so
the generated collision slug is never one the resolver would satisfy from a
built-in stencil, and `test_ambiguous_exact_slug_is_unresolved_with_candidates`
SHALL pass deterministically for every generated case.

2.2 WHEN a slug is BOTH a curated built-in stencil slug AND recorded as
ambiguous in the index THEN `resolve_asset` SHALL return `source='builtin'`
(the built-in stencil is step 1 of the documented resolution order and takes
priority over the ambiguous-slug path), and a dedicated test SHALL assert this
contract explicitly.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a slug is ambiguous in the index and is NOT a curated built-in stencil
slug THEN `resolve_asset` SHALL CONTINUE TO return `source='unresolved'` with
every competing display name listed in `candidates` (the existing R6.7
fail-honest contract).

3.2 WHEN the `_STRIP_TOKENS` / `_MEANINGFUL_WORDS` slug behaviour is exercised
(honest-gates Property 26 leg 1, R6.6, `test_slug_retains_meaningful_words`)
THEN the system SHALL CONTINUE TO retain meaning-carrying words in
vendor-stripped slugs, unchanged by this fix.

3.3 WHEN `resolve_asset` is called for any input that does NOT hit the built-in
stencil table THEN the system SHALL CONTINUE TO resolve via official-asset,
token-subsequence, or unresolved exactly as before — no production code in
`src/rule_engine/asset_index.py` is modified by this fix.
