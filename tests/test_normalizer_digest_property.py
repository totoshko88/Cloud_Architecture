"""Property-based tests for the Normalizer config_digest (task 7.14).

Feature: multicloud-diagram-inventory, Property 10: config_digest is deterministic and order-independent

Property 10 — config_digest is deterministic and order-independent
(Validates: Requirements 4.4):

*For any* resource configuration, computing ``config_digest`` twice yields the
same value (and the digest matches ``^[a-f0-9]{64}$``), and any permutation of
object keys or reordering of array elements yields an identical
``config_digest``.

The design defines canonicalization as: drop secret fields, recursively sort
object keys lexicographically, and sort array elements by their canonical
serialization. Consequently:

- **Determinism** — repeated calls on the same input agree, and the output is a
  lowercase 64-char SHA-256 hex digest.
- **Order-independence** — recursively reordering dict keys and shuffling list
  element order does not change the digest (array element ORDER is normalized
  away by the canonical-serialization sort).
- **Secret-safety** — two configs differing only in the values of secret-bearing
  fields produce the same digest, because those fields are dropped before
  hashing.
"""

from __future__ import annotations

import random
import re
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.normalizer import compute_config_digest

# A config_digest must be a lowercase SHA-256 hex digest: 64 hex chars.
_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")

# Secret-bearing key names that the Normalizer drops during canonicalization
# (a subset of rule_engine.normalizer._SECRET_KEY_SUBSTRINGS).
_SECRET_KEYS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
    "access_key",
    "secret_key",
    "session_token",
    "securestring",
)


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

# JSON-like scalars. Floats exclude NaN/infinity so equality and serialization
# are stable; text keys/values keep dict keys unambiguous once stringified.
_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=12),
)

# Arbitrary nested JSON-like configs: dicts (string keys), lists, and scalars.
_configs = st.recursive(
    _scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=8), children, max_size=5),
    ),
    max_leaves=25,
)


def _shuffle_structure(value: Any, rng: random.Random) -> Any:
    """Return a structurally-shuffled variant of ``value``.

    Recursively rebuilds dicts with their key insertion order permuted and lists
    with their element order permuted. The result is *equal as maps/sets* to the
    input — only ordering differs — so its config_digest must match.
    """
    if isinstance(value, dict):
        items = [(k, _shuffle_structure(v, rng)) for k, v in value.items()]
        rng.shuffle(items)
        return dict(items)
    if isinstance(value, list):
        elems = [_shuffle_structure(v, rng) for v in value]
        rng.shuffle(elems)
        return elems
    return value


def _inject_secret_values(value: Any, marker: str) -> Any:
    """Return a copy of ``value`` with secret fields injected at each dict level.

    At every dict node, add one entry per secret key name carrying a distinctive
    ``marker`` value. Two configs built from the same base with different markers
    differ *only* in secret values, so they must hash identically.
    """
    if isinstance(value, dict):
        out = {k: _inject_secret_values(v, marker) for k, v in value.items()}
        for i, sk in enumerate(_SECRET_KEYS):
            out[sk] = f"{marker}-secret-value-{i}"
        return out
    if isinstance(value, list):
        return [_inject_secret_values(v, marker) for v in value]
    return value


# --------------------------------------------------------------------------- #
# Properties
# --------------------------------------------------------------------------- #


@settings(max_examples=200)
@given(config=_configs)
def test_config_digest_is_deterministic_and_well_formed(config: Any) -> None:
    """Repeated calls agree and the digest matches ^[a-f0-9]{64}$.

    Feature: multicloud-diagram-inventory, Property 10: config_digest is deterministic and order-independent
    Validates: Requirements 4.4
    """
    d1 = compute_config_digest(config)
    d2 = compute_config_digest(config)

    assert d1 == d2, "config_digest must be deterministic across repeated calls"
    assert _DIGEST_RE.match(d1), f"expected ^[a-f0-9]{{64}}$, got {d1!r}"


@settings(max_examples=200)
@given(config=_configs, seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_config_digest_is_order_independent(config: Any, seed: int) -> None:
    """Reordering dict keys and shuffling list elements preserves the digest.

    Feature: multicloud-diagram-inventory, Property 10: config_digest is deterministic and order-independent
    Validates: Requirements 4.4
    """
    rng = random.Random(seed)
    shuffled = _shuffle_structure(config, rng)

    assert compute_config_digest(config) == compute_config_digest(shuffled), (
        "config_digest must be independent of dict key order and list element order"
    )


@settings(max_examples=100)
@given(config=_configs)
def test_config_digest_ignores_secret_field_values(config: Any) -> None:
    """Two configs differing only in secret-field values hash identically.

    Feature: multicloud-diagram-inventory, Property 10: config_digest is deterministic and order-independent
    Validates: Requirements 4.4
    """
    with_secrets_a = _inject_secret_values(config, marker="alpha")
    with_secrets_b = _inject_secret_values(config, marker="omega")

    assert compute_config_digest(with_secrets_a) == compute_config_digest(
        with_secrets_b
    ), "digest must not depend on dropped secret-field values"
