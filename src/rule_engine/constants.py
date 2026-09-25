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
    "ROOT_LAYER_ID",
    "is_boundary_container_style",
    "is_text_cell_style",
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

def _resolve_terminology_path() -> Path:
    """Locate ``profiles/terminology.yaml`` for both the repo and installed cases.

    Resolution order (first that exists):
      1. the repo root — ``src/rule_engine/constants.py`` -> parents[2] -> root,
         the dev/checkout case;
      2. the payload bundled inside the installed package
         (``rule_engine/_bootstrap/profiles/terminology.yaml``, staged by
         ``build_backend.py``) — present in every pip / Kiro-Power install, so
         the CLIs work with no repo checkout;
      3. the current working directory's ``profiles/`` — a bootstrapped
         workspace.

    Falls back to the repo-root path (even if absent) so the eventual
    ``FileNotFoundError`` names the expected location.
    """
    here = Path(__file__).resolve()
    repo_root = here.parents[2] / "profiles" / "terminology.yaml"
    bundled = here.parent / "_bootstrap" / "profiles" / "terminology.yaml"
    cwd = Path.cwd() / "profiles" / "terminology.yaml"
    for candidate in (repo_root, bundled, cwd):
        if candidate.is_file():
            return candidate
    return repo_root


#: profiles/terminology.yaml — the terminology source of truth. Resolved from the
#: repo root (dev), the bundled package payload (pip/Power install), or the CWD
#: (bootstrapped workspace), so the engine loads it in every install shape.
TERMINOLOGY_PATH: Path = _resolve_terminology_path()


def resolve_bundled_dir(name: str) -> Path:
    """Locate a bundled data directory (``mappings`` / ``schemas``) in any install.

    Same resolution order as :func:`_resolve_terminology_path`, for the data
    dirs the icon resolver and schema loader read: the repo root (dev), the
    package payload bundled by ``build_backend`` (pip / Kiro-Power install), then
    the CWD (a bootstrapped workspace). Falls back to the repo-root path so a
    later "not found" names the expected location. This is the single home for
    the repo→bundle→cwd lookup so ``icon_resolver`` and ``schema`` do not each
    re-hard-code ``parents[2]`` (which broke icon/schema resolution in a
    repo-less install).
    """
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[2] / name,          # repo checkout
        here.parent / "_bootstrap" / name,  # bundled package payload
        Path.cwd() / name,               # bootstrapped workspace
    ):
        if candidate.is_dir():
            return candidate
    return here.parents[2] / name


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


# --------------------------------------------------------------------------- #
# Shared .drawio cell classification (single home so cli + geometry agree)
# --------------------------------------------------------------------------- #

#: The draw.io root layer cell id. A vertex parented here (or to a boundary
#: container) is a top-level diagram node; a vertex parented to another node is
#: that node's internal glyph geometry.
ROOT_LAYER_ID = "1"


def is_boundary_container_style(cell_id: str, style: str) -> bool:
    """Return True when a vertex is a Boundary / Network-Boundary container.

    Shared by ``cli._parse_drawio`` (node counting) and
    ``geometry.build_geometry`` (layout checks) so the container-detection rule
    (REVIEW.md C4) cannot drift between the two. A vertex is a container when:

    * its id starts with the conventional ``boundary`` prefix; or
    * it is a dashed borderless rectangle (generic/oci/gcp boundary style,
      ``dashed=1`` + ``fillColor=none``); or
    * it is an AWS-style group container — a group/``container=1`` style that
      names a ``group_*`` container icon or ``grIcon=`` (e.g.
      ``shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;dashed=0``).

    A group-styled cell that merely hosts embedded glyph geometry (an OCI node
    container) is NOT a boundary — it names no ``group_``/``grIcon=`` — and is
    handled as an ordinary top-level node.
    """
    low = (style or "").lower()
    is_group = "group" in low or "container=1" in low
    is_dashed = "dashed=1" in low and "fillcolor=none" in low
    is_boundary_group = is_group and ("group_" in low or "gricon=" in low)
    return (cell_id or "").startswith("boundary") or is_dashed or is_boundary_group


def is_text_cell_style(style: str) -> bool:
    """Return True when a cell is a text/label cell (title, legend, free text)."""
    low = (style or "").lower()
    return low.startswith("text;") or "text;" in low or "text" == low.strip()


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
