"""Property-based tests for Normalizer schema conformance (task 7.13).

Feature: multicloud-diagram-inventory, Property 9: Every emitted resource validates against the schema

Property 9 — Every emitted resource validates against the schema
(Validates: Requirements 4.1, 4.2, 4.3, 4.7):
Every Normalized Resource the Normalizer emits conforms to
``schemas/inventory.schema.json``. For any native provider resource whose
``native_type`` maps to a Normalized Resource Type, the emitted resource has a
valid ``provider`` enum value, a ``resource_type`` drawn from the neutral enum,
every mandatory field populated, and a ``config_digest`` matching the schema
pattern — so ``resource_errors(normalized) == []``.

The generators build *valid* native resources: a provider drawn from
``PROVIDERS``; a ``native_type`` drawn from that provider's known aliases (so
type mapping always succeeds); and non-empty ``name`` / ``boundary`` / ``region``
strings, an ``id``, and a ``tags`` map. Both the single-resource entry point
(:func:`normalize`) and the batch entry point (:func:`normalize_all`) are
exercised, and every emitted resource is asserted to validate against the schema.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.normalizer import (
    PROVIDERS,
    NEUTRAL_RESOURCE_TYPES,
    _NATIVE_ALIASES,
    normalize,
    normalize_all,
)
from rule_engine.schema import resource_errors


def _provider_native_aliases() -> dict[str, list[str]]:
    """Build ``{provider -> [native aliases...]}`` from the mapping table.

    For each provider, collect every native alias declared across all nine
    neutral resource types, plus each neutral type string itself (which is
    always a valid alias for itself in ``TYPE_MAPPING``). Every entry is
    guaranteed to resolve to a neutral ``resource_type`` for that provider.
    """
    per_provider: dict[str, set[str]] = {p: set() for p in PROVIDERS}
    for neutral, provider_map in _NATIVE_ALIASES.items():
        for provider, aliases in provider_map.items():
            per_provider[provider].add(neutral)
            per_provider[provider].update(aliases)
    return {p: sorted(v) for p, v in per_provider.items()}


_PROVIDER_ALIASES = _provider_native_aliases()

# Non-empty strings for name / boundary / region (schema requires minLength 1).
# Constrain to printable text and strip to avoid whitespace-only values that
# would stringify to empty.
_nonempty_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=40,
)

# id is optional-empty per schema (type string, no minLength); allow "".
_id_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=0,
    max_size=60,
)

# tags: a small {str: str} map. Values are stringified by the Normalizer, so any
# JSON scalar is acceptable input; keep it to short strings for clarity.
_tags = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=1,
        max_size=20,
    ),
    values=st.text(max_size=30),
    max_size=5,
)


@st.composite
def valid_native_resource(draw: st.DrawFn) -> tuple[dict, str]:
    """Generate a ``(native_resource, provider)`` pair that normalizes cleanly.

    The ``native_type`` is drawn from the chosen provider's known aliases, so the
    neutral ``resource_type`` mapping always succeeds. All mandatory sourced
    fields are populated with non-empty values.
    """
    provider = draw(st.sampled_from(PROVIDERS))
    native_type = draw(st.sampled_from(_PROVIDER_ALIASES[provider]))
    native = {
        "native_type": native_type,
        "id": draw(_id_text),
        "name": draw(_nonempty_text),
        "boundary": draw(_nonempty_text),
        "region": draw(_nonempty_text),
        "tags": draw(_tags),
    }
    return native, provider


@settings(max_examples=200)
@given(sample=valid_native_resource())
def test_normalize_emits_schema_conforming_resource(sample: tuple[dict, str]) -> None:
    """Every resource ``normalize`` emits validates against the schema.

    Feature: multicloud-diagram-inventory, Property 9: Every emitted resource validates against the schema
    Validates: Requirements 4.1, 4.2, 4.3, 4.7
    """
    native, provider = sample

    normalized = normalize(native, provider)

    errors = resource_errors(normalized)
    assert errors == [], (
        f"emitted resource failed schema validation for provider {provider!r}: {errors}"
    )
    # AC2/AC3: provider and resource_type are drawn from the neutral enums.
    assert normalized["provider"] in PROVIDERS
    assert normalized["resource_type"] in NEUTRAL_RESOURCE_TYPES


@settings(max_examples=100)
@given(samples=st.lists(valid_native_resource(), min_size=1, max_size=12))
def test_normalize_all_emits_only_schema_conforming_resources(
    samples: list[tuple[dict, str]],
) -> None:
    """Every resource ``normalize_all`` emits validates against the schema.

    A batch is grouped by provider (``normalize_all`` normalizes a list under a
    single provider). Every emitted Normalized Resource conforms to the schema
    and none of the valid inputs are excluded as errors.

    Feature: multicloud-diagram-inventory, Property 9: Every emitted resource validates against the schema
    Validates: Requirements 4.1, 4.2, 4.3, 4.7
    """
    by_provider: dict[str, list[dict]] = {}
    for native, provider in samples:
        by_provider.setdefault(provider, []).append(native)

    for provider, natives in by_provider.items():
        normalized_list, errors_list = normalize_all(natives, provider)

        # All valid inputs are emitted; none excluded.
        assert errors_list == [], (
            f"unexpected exclusions for provider {provider!r}: "
            f"{[str(e) for e in errors_list]}"
        )
        assert len(normalized_list) == len(natives)

        for normalized in normalized_list:
            assert resource_errors(normalized) == [], (
                f"batch-emitted resource failed schema validation for "
                f"provider {provider!r}: {resource_errors(normalized)}"
            )
            assert normalized["provider"] in PROVIDERS
            assert normalized["resource_type"] in NEUTRAL_RESOURCE_TYPES


def test_alias_domain_covers_all_providers() -> None:
    """Sanity guard: every provider contributes a non-empty alias domain."""
    assert set(_PROVIDER_ALIASES) == set(PROVIDERS)
    for provider, aliases in _PROVIDER_ALIASES.items():
        assert aliases, f"expected non-empty alias domain for provider {provider!r}"
