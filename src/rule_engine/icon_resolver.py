"""Icon Resolver.

Maps a Normalized Resource Type + Provider to a draw.io style string and brand
color, sourced from the profile's authoritative asset pack. Also resolves the
Boundary and Network Boundary container group styles. The resolver never emits a
placeholder: an unmapped type produces an unresolved-type error and a missing or
unreadable asset pack produces an asset-source error (Requirement 2, AC1-AC10).

Public interface (design.md "Icon Resolver")::

    resolve_icon(resource_type, provider) -> {style_string, brand_hex, icon_source}
    resolve_container(kind, provider)     -> {style_string}

Each provider's mapping lives at ``mappings/<provider>-icons.yaml`` at the
repository root. Every file declares a top-level ``provider``, ``asset_pack``,
and ``icon_source``; a ``resources`` table keyed by Normalized Resource Type; and
a ``containers`` table keyed by container kind (``boundary`` /
``network_boundary``). The AWS file keeps the two structural types only under
``containers``; the other profiles list them under both ``resources`` and
``containers``. ``resolve_icon`` handles both layouts by falling back from
``resources`` to ``containers`` for the two structural types.
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

from rule_engine.constants import CONTAINER_KINDS, ICON_SOURCES, PROVIDERS
from rule_engine.constants import NEUTRAL_RESOURCE_TYPES as RESOURCE_TYPES
from rule_engine.constants import resolve_bundled_dir

# ---------------------------------------------------------------------------
# Domain constants (re-exported from rule_engine.constants, the single source)
# ---------------------------------------------------------------------------

#: A brand color must be a single ``#`` followed by exactly six hex digits.
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# mappings/<provider>-icons.yaml. Resolved from the repo root (dev), the bundled
# package payload (pip / Kiro-Power install), or the CWD (bootstrapped
# workspace) — so icons resolve to the real mapping in every install shape,
# not just a repo checkout.
_MAPPINGS_DIR = resolve_bundled_dir("mappings")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IconResolverError(Exception):
    """Base class for Icon Resolver errors."""


class UnresolvedTypeError(IconResolverError):
    """Raised when a Normalized Resource Type is absent from a provider's map.

    Carries the offending ``resource_type`` and ``provider``. The resolver emits
    no style string and no placeholder icon and leaves the input unchanged
    (Requirement 2 AC8).
    """

    def __init__(self, resource_type: str, provider: str) -> None:
        self.resource_type = resource_type
        self.provider = provider
        super().__init__(
            f"unresolved-type: resource_type {resource_type!r} is not mapped "
            f"for provider {provider!r}"
        )


class AssetSourceError(IconResolverError):
    """Raised when a provider's authoritative asset pack cannot be used.

    This covers an unknown provider, a missing or unreadable mapping file, and a
    malformed or incomplete mapping. Carries the affected ``provider``. The
    resolver emits no icon identifier, brand color, or placeholder and leaves the
    input unchanged (Requirement 2 AC10).
    """

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(
            f"asset-source: provider {provider!r} asset pack unavailable: {reason}"
        )


# ---------------------------------------------------------------------------
# Mapping loading
# ---------------------------------------------------------------------------


def _mapping_path(provider: str) -> Path:
    return _MAPPINGS_DIR / f"{provider}-icons.yaml"


def load_mapping(provider: str) -> Dict[str, Any]:
    """Load and return the parsed icon mapping for ``provider``.

    Returns a fresh deep copy each call (so a caller cannot corrupt the cache),
    backed by a cached file read + parse — the mapping file is static at runtime
    and was otherwise re-read and re-parsed once per resolved node/resource.

    Raises :class:`AssetSourceError` (naming the provider) when the provider is
    not a member of :data:`PROVIDERS`, when the mapping file is missing or
    unreadable, or when the parsed mapping is malformed (not a mapping, or
    missing the top-level ``icon_source`` / ``asset_pack`` provenance keys).
    """
    return copy.deepcopy(_load_mapping_cached(provider))


@lru_cache(maxsize=len(PROVIDERS) or None)
def _load_mapping_cached(provider: str) -> Dict[str, Any]:
    if provider not in PROVIDERS:
        raise AssetSourceError(
            provider,
            f"not a recognized provider (expected one of {', '.join(PROVIDERS)})",
        )

    path = _mapping_path(provider)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AssetSourceError(provider, f"cannot read {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AssetSourceError(provider, f"cannot parse {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise AssetSourceError(provider, f"{path} does not contain a mapping")

    # Provenance keys must be present so every resolved icon/color can be
    # attributed to the declared asset pack (Requirement 2 AC9).
    if not data.get("asset_pack"):
        raise AssetSourceError(provider, f"{path} declares no asset_pack")
    icon_source = data.get("icon_source")
    if icon_source not in ICON_SOURCES:
        raise AssetSourceError(
            provider,
            f"{path} declares icon_source {icon_source!r}; "
            f"expected one of {', '.join(ICON_SOURCES)}",
        )

    return data


def _require_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_icon(resource_type: str, provider: str) -> Dict[str, str]:
    """Resolve ``resource_type`` for ``provider`` to a draw.io icon.

    Returns a dict with keys ``style_string`` (non-empty draw.io style),
    ``brand_hex`` (``#RRGGBB``), and ``icon_source`` (``builtin`` or ``custom``,
    taken from the mapping's top-level provenance).

    Lookup order: the provider's ``resources`` table first, then — for the two
    structural types ``boundary`` and ``network_boundary`` only — a fallback to
    the ``containers`` table (the AWS layout keeps those two only under
    ``containers``).

    Raises :class:`AssetSourceError` when the provider or its asset pack is
    unavailable, and :class:`UnresolvedTypeError` when the type is not mapped for
    the provider. On either error no style string and no placeholder are emitted
    and the inputs are left unchanged (Requirement 2 AC8, AC10).
    """
    data = load_mapping(provider)
    icon_source = data["icon_source"]

    resources = data.get("resources") or {}
    containers = data.get("containers") or {}
    if not isinstance(resources, dict) or not isinstance(containers, dict):
        raise AssetSourceError(provider, "resources/containers are not mappings")

    entry = resources.get(resource_type)
    if entry is None and resource_type in CONTAINER_KINDS:
        # AWS keeps the structural types only under `containers`.
        entry = containers.get(resource_type)

    if entry is None:
        raise UnresolvedTypeError(resource_type, provider)

    if not isinstance(entry, dict):
        raise AssetSourceError(
            provider, f"mapping entry for {resource_type!r} is malformed"
        )

    style = entry.get("style")
    brand_hex = entry.get("brand_hex")

    if not _require_str(style):
        raise AssetSourceError(
            provider, f"mapping entry for {resource_type!r} has no style string"
        )
    if not _require_str(brand_hex) or not _HEX_COLOR_RE.match(brand_hex):
        raise AssetSourceError(
            provider,
            f"mapping entry for {resource_type!r} has no valid #RRGGBB brand_hex",
        )

    return {
        "style_string": style,
        "brand_hex": brand_hex,
        "icon_source": icon_source,
    }


def resolve_container(kind: str, provider: str) -> Dict[str, str]:
    """Resolve the container group style for ``kind`` under ``provider``.

    ``kind`` must be one of ``boundary`` or ``network_boundary``. Returns exactly
    one style per kind as ``{"style_string": <style>}`` (Requirement 2 AC6),
    read from the mapping's ``containers`` table.

    Raises :class:`UnresolvedTypeError` when ``kind`` is not a container kind or
    is absent from the provider's ``containers`` table, and
    :class:`AssetSourceError` when the provider or its asset pack is unavailable
    or declares no style for the kind.
    """
    data = load_mapping(provider)

    if kind not in CONTAINER_KINDS:
        raise UnresolvedTypeError(kind, provider)

    containers = data.get("containers") or {}
    if not isinstance(containers, dict):
        raise AssetSourceError(provider, "containers is not a mapping")

    entry = containers.get(kind)
    if entry is None:
        raise UnresolvedTypeError(kind, provider)
    if not isinstance(entry, dict):
        raise AssetSourceError(provider, f"container entry for {kind!r} is malformed")

    style = entry.get("style")
    if not _require_str(style):
        # A profile that declares no container group style for its Boundary or
        # Network Boundary is a profile-convention / asset-source error.
        raise AssetSourceError(
            provider, f"container {kind!r} declares no group style"
        )

    return {"style_string": style}
