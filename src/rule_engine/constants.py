"""Central constants and the single terminology source of truth.

This module removes the duplication called out in the architecture review
(REVIEW.md U1/U2/C1). It is the one place that declares:

- :data:`PROVIDERS` — the five Provider Profile ids.
- :data:`NEUTRAL_RESOURCE_TYPES` — the nine neutral resource types (kept in
  lockstep with ``schemas/inventory.schema.json``).
- :data:`CONTAINER_KINDS`, :data:`ICON_SOURCES` — small structural enums.
- :data:`BRAND_HEX` — the per-provider brand anchor color.
- :data:`SECRET_MARKERS` — the shared secret-material vocabulary consumed by
  both the Linter's content scan and the Normalizer's config-key drop list.

It also loads ``profiles/terminology.yaml`` — the authoritative machine-readable
neutral-concept → per-provider mapping (native label, native-type aliases, seed
icon metadata) — and exposes helpers so the contract, normalizer, and asset-seed
modules all READ from the same data instead of hard-coding their own tables.
Adding a provider is then a data edit in the YAML, not a core-code change.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

__all__ = [
    "PROVIDERS",
    "NEUTRAL_RESOURCE_TYPES",
    "CONTAINER_KINDS",
    "ICON_SOURCES",
    "BRAND_HEX",
    "SECRET_MARKERS",
    "SECRET_CONTENT_MARKERS",
    "TERMINOLOGY_PATH",
    "load_terminology",
    "provider_labels",
    "native_aliases",
    "seed_icons",
]

# --------------------------------------------------------------------------- #
# Core enums
# --------------------------------------------------------------------------- #

#: The five supported Provider Profiles.
PROVIDERS: Tuple[str, ...] = ("aws", "azure", "gcp", "oci", "generic")

#: The nine neutral Normalized Resource Types (schemas/inventory.schema.json).
NEUTRAL_RESOURCE_TYPES: Tuple[str, ...] = (
    "boundary",
    "network_boundary",
    "serverless_fn",
    "object_store",
    "managed_sql",
    "message_queue",
    "secrets_store",
    "managed_k8s",
    "llm_platform",
)

#: The two structural container kinds.
CONTAINER_KINDS: Tuple[str, ...] = ("boundary", "network_boundary")

#: Accepted values for a mapping's top-level ``icon_source`` field.
ICON_SOURCES: Tuple[str, ...] = ("builtin", "custom")

# --------------------------------------------------------------------------- #
# Shared secret-material vocabulary (U2)
# --------------------------------------------------------------------------- #
#
# There are two matching semantics, so there are two vocabularies drawn from one
# place:
#
#   SECRET_MARKERS          — broad, matched against object KEY NAMES by the
#                             Normalizer (normalizer._is_secret_key). A field
#                             literally named ``secret``/``token``/``access_key``
#                             is credential-bearing and dropped before hashing.
#
#   SECRET_CONTENT_MARKERS  — narrow, matched as substrings against RAW SNAPSHOT
#                             CONTENT by the Linter (linter._content_has_secret).
#                             It must contain only tokens that reliably indicate a
#                             secret VALUE or a compound credential key, because a
#                             broad token like ``secret`` would false-positive on
#                             legitimate metadata (e.g. the neutral type value
#                             ``secrets_store`` or a field name ``access_key_id``)
#                             and wrongly block a secret-free snapshot.
SECRET_MARKERS: Tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "privatekey",
    "securestring",
    "apikey",
    "api_key",
    "access_key",
    "accesskey",
    "secret_key",
    "secretkey",
    "session_token",
    "client_secret",
    "secret_access_key",
    "secretaccesskey",
    "aws_secret_access_key",
)

#: Narrow markers for scanning raw snapshot CONTENT for a leaked secret value or
#: compound credential key. Deliberately excludes broad single words
#: (``secret``, ``token``, ``credential``, ``access_key``, ``apikey``) that occur
#: in ordinary resource metadata.
SECRET_CONTENT_MARKERS: Tuple[str, ...] = (
    "-----begin ",         # PEM key material block
    "securestring",        # SSM SecureString value
    "private_key",
    "privatekey",
    "secret_access_key",
    "secretaccesskey",
    "aws_secret_access_key",
    "client_secret",
    "session_token",
)

# --------------------------------------------------------------------------- #
# Terminology source of truth (C1)
# --------------------------------------------------------------------------- #

#: profiles/terminology.yaml lives at the repo root: this file is
#: src/rule_engine/constants.py -> src/rule_engine -> src -> <root>.
TERMINOLOGY_PATH: Path = Path(__file__).resolve().parents[2] / "profiles" / "terminology.yaml"


@functools.lru_cache(maxsize=1)
def load_terminology() -> Dict[str, Any]:
    """Load and cache ``profiles/terminology.yaml``.

    Raises :class:`FileNotFoundError` if the file is missing (it is required —
    the core cannot function without the terminology source of truth).
    """
    with open(TERMINOLOGY_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "resources" not in data:
        raise ValueError(f"{TERMINOLOGY_PATH} is not a valid terminology file")
    return data


@functools.lru_cache(maxsize=1)
def _brand_hex_from_terminology() -> Dict[str, str]:
    data = load_terminology()
    return dict(data.get("brand_hex") or {})


#: Per-provider brand anchor hex. Sourced from the terminology file; falls back
#: to the built-in defaults if the file omits an entry.
BRAND_HEX: Dict[str, str] = {
    "aws": "#232F3E",
    "azure": "#0078D4",
    "gcp": "#4285F4",
    "oci": "#F80000",
    "generic": "#FFFFFF",
    **_brand_hex_from_terminology(),
}


def provider_labels() -> Dict[str, Dict[str, str]]:
    """Return ``{neutral_type -> {provider -> native label}}`` from the source."""
    data = load_terminology()
    out: Dict[str, Dict[str, str]] = {}
    for rtype, per_provider in data["resources"].items():
        out[rtype] = {
            prov: str(spec.get("label", rtype))
            for prov, spec in per_provider.items()
        }
    return out


def native_aliases() -> Dict[str, Dict[str, Tuple[str, ...]]]:
    """Return ``{neutral_type -> {provider -> (native alias, ...)}}``."""
    data = load_terminology()
    out: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    for rtype, per_provider in data["resources"].items():
        out[rtype] = {
            prov: tuple(str(a) for a in (spec.get("aliases") or ()))
            for prov, spec in per_provider.items()
        }
    return out


def seed_icons() -> Dict[str, Dict[str, Tuple[str, str, str]]]:
    """Return ``{provider -> {neutral_type -> (icon_id, name, brand_hex)}}``.

    Only providers/types that declare an ``icon`` block contribute (the
    ``generic`` profile has no vendor icon).
    """
    data = load_terminology()
    out: Dict[str, Dict[str, Tuple[str, str, str]]] = {p: {} for p in PROVIDERS}
    for rtype, per_provider in data["resources"].items():
        for prov, spec in per_provider.items():
            icon = spec.get("icon")
            if not icon:
                continue
            out.setdefault(prov, {})[rtype] = (
                str(icon["id"]),
                str(icon["name"]),
                str(icon["hex"]),
            )
    # Drop providers with no icons (e.g. generic) to mirror the previous _SEED.
    return {p: rows for p, rows in out.items() if rows}
