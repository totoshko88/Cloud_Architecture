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

    Row shape: ``| N | concept | `resource_type` | <provider cols...> |``. The
    provider columns are read from the table HEADER rather than assumed to be
    exactly five, so adding a profile (e.g. ``kubernetes`` in 1.10.11) is a data
    edit — the parser follows the header's provider order instead of a hard-wired
    positional slice. Returns ``{resource_type -> {provider -> label}}``.
    """
    text = _STEERING.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    providers: list[str] | None = None
    for line in text.splitlines():
        # Header row: ``| # | Neutral concept | `resource_type` | aws | ... |``.
        if providers is None:
            hm = re.match(
                r"^\|\s*#\s*\|\s*Neutral concept\s*\|\s*`?resource_type`?\s*\|(.+)\|\s*$",
                line,
            )
            if hm:
                providers = [c.strip() for c in hm.group(1).split("|")]
            continue
        m = re.match(
            r"^\|\s*\d+\s*\|[^|]*\|\s*`([a-z0-9_]+)`\s*\|(.+)\|\s*$", line
        )
        if not m:
            continue
        rtype = m.group(1)
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < len(providers):
            continue
        out[rtype] = {prov: cells[i] for i, prov in enumerate(providers)}
    return out


def test_steering_table_matches_terminology_source():
    steering = _parse_steering_table()
    labels = C.provider_labels()
    # The nine-row terminology normalization table in provider-profiles.md covers
    # the nine neutral resource types. terminology.yaml additionally carries the
    # seven diagram role rows added in 1.7.0 (design D4); those are documented in a
    # separate steering table and are not part of this nine-row guardrail.
    assert set(steering) == set(C.NEUTRAL_RESOURCE_TYPES)
    assert set(C.NEUTRAL_RESOURCE_TYPES).issubset(set(labels))
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
