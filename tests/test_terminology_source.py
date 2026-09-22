"""Anti-drift guardrail for the terminology source of truth.

``profiles/terminology.yaml`` is the single source of the neutral-concept →
per-provider label mapping (REVIEW.md C1). This test asserts that source agrees
with BOTH:

- the core modules that read it (contract labels, normalizer aliases, asset
  seed), and
- the authoritative terminology normalization table in the steering document
  ``.kiro/steering/provider-profiles.md``.

If a future edit changes one without the other, this test fails — which is the
guarantee the terminology.yaml header advertises.
"""

from __future__ import annotations

import re
from pathlib import Path

from rule_engine import constants as C

_STEERING = (
    Path(__file__).resolve().parents[1]
    / ".kiro" / "steering" / "provider-profiles.md"
)


def _parse_steering_table() -> dict[str, dict[str, str]]:
    """Parse the terminology table rows from provider-profiles.md.

    Row shape: ``| N | concept | `resource_type` | aws | azure | gcp | oci | generic |``
    Returns ``{resource_type -> {provider -> label}}``.
    """
    text = _STEERING.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = re.match(
            r"^\|\s*\d+\s*\|[^|]*\|\s*`([a-z0-9_]+)`\s*\|(.+)\|\s*$", line
        )
        if not m:
            continue
        rtype = m.group(1)
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 5:
            continue
        aws, azure, gcp, oci, generic = cells[:5]
        out[rtype] = {
            "aws": aws, "azure": azure, "gcp": gcp, "oci": oci, "generic": generic,
        }
    return out


def test_steering_table_matches_terminology_source():
    steering = _parse_steering_table()
    labels = C.provider_labels()
    assert set(steering) == set(labels) == set(C.NEUTRAL_RESOURCE_TYPES)
    for rtype in C.NEUTRAL_RESOURCE_TYPES:
        for provider in C.PROVIDERS:
            assert steering[rtype][provider] == labels[rtype][provider], (
                f"steering table and terminology.yaml disagree for "
                f"{rtype}/{provider}: {steering[rtype][provider]!r} != "
                f"{labels[rtype][provider]!r}"
            )


def test_contract_labels_match_source():
    from rule_engine import contract
    assert contract._PROVIDER_LABELS == C.provider_labels()


def test_normalizer_aliases_derive_from_source():
    from rule_engine import normalizer
    src = C.native_aliases()
    for rtype, per_provider in src.items():
        for provider, aliases in per_provider.items():
            for alias in aliases:
                assert normalizer.resolve_resource_type(alias, provider) == rtype


def test_seed_icons_match_source():
    from rule_engine.assets import enumerate as en
    assert en._SEED == C.seed_icons()
