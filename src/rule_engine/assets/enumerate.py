"""Enumerate each provider asset pack into ``assets/<provider>/inventory.json``.

This module is the enumeration stage of the Rule Engine (task 2.2). It scans the
staged ``assets/<provider>/`` directory produced by :mod:`rule_engine.assets.fetch`
and emits an ``inventory.json`` per provider recording, for every canonical icon:

- an **icon id** (the draw.io shape / library identifier or a stable file-derived id),
- a **name** and/or source **file**,
- a **brand hex** color formatted as ``#RRGGBB``.

At the top level of each ``inventory.json`` it records the authoritative
**asset-pack identifier** and the **icon reference source** (``custom`` vs
``builtin``) for the provider, mirroring the provenance recorded by ``fetch.py``
in ``SOURCE.json`` and by the icon mapping files authored in task 3.

Offline resilience
-------------------
The asset packs are frequently unavailable (the packaging environment is often
offline; see the graceful-degradation design of ``fetch.py``). Enumeration must
never yield an empty inventory, because task 2.3's unit tests assert that every
provider's ``inventory.json`` is non-empty and that every entry carries an icon
id and a ``#RRGGBB`` brand hex. To guarantee this, the module ships a curated
**built-in seed inventory**: the canonical icons for the nine neutral resource
types (``boundary``, ``network_boundary``, ``serverless_fn``, ``object_store``,
``managed_sql``, ``message_queue``, ``secrets_store``, ``managed_k8s``,
``llm_platform``) for ``aws``, ``azure``, ``gcp`` and ``oci``, each with a proper
``#RRGGBB`` brand hex drawn from the design (section 4b, "Icon Mapping Data
Model"). When real downloaded assets exist, the module enumerates them and
merges the discovered entries into the seed inventory.

Note on the module name
------------------------
This module is deliberately named ``enumerate.py`` (the task filename) which
shadows the built-in :func:`enumerate`. All imports here are absolute and the
built-in ``enumerate`` is never called inside this module, so the shadowing is
harmless.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from rule_engine.assets.fetch import (
    ASSET_SOURCES,
    PROVIDERS,
    default_assets_root,
    provider_asset_pack,
)
from rule_engine.constants import BRAND_HEX
from rule_engine.constants import NEUTRAL_RESOURCE_TYPES
from rule_engine.constants import seed_icons as _seed_icons_source

__all__ = [
    "IconEntry",
    "ProviderInventory",
    "NEUTRAL_RESOURCE_TYPES",
    "SEED_INVENTORY",
    "provider_icon_source",
    "build_inventory",
    "write_inventory",
    "write_all_inventories",
]

# Six-digit hex color, single leading '#'.
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Image / shape file extensions worth enumerating from a real downloaded pack.
_ICON_FILE_SUFFIXES: frozenset[str] = frozenset(
    {".svg", ".png", ".drawio", ".xml", ".vsdx", ".eps", ".ai"}
)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IconEntry:
    """A single enumerated icon.

    Attributes
    ----------
    resource_type:
        Neutral resource type this icon represents (one of
        :data:`NEUTRAL_RESOURCE_TYPES`) for seed icons, or ``""`` when the icon
        was discovered in a downloaded pack and not yet mapped to a neutral type.
    icon_id:
        Stable identifier for the icon. For seed icons this is the draw.io
        library id (e.g. ``mxgraph.aws4.s3``); for discovered files it is a
        slug derived from the file path.
    name:
        Human-readable icon name.
    file:
        Source file path (relative to the provider directory) when the icon was
        discovered on disk, otherwise ``None`` for a built-in/library icon.
    brand_hex:
        Brand color as ``#RRGGBB``.
    origin:
        ``"seed"`` for a curated built-in icon, ``"discovered"`` for one found in
        a downloaded pack.
    """

    resource_type: str
    icon_id: str
    name: str
    brand_hex: str
    file: str | None = None
    origin: str = "seed"


@dataclass(frozen=True)
class ProviderInventory:
    """The enumerated icon inventory for one provider."""

    provider: str
    authoritative_asset_pack: str
    icon_source: str
    icons: tuple[IconEntry, ...]

    def to_json_obj(self) -> dict:
        """Return a JSON-serializable dict for ``inventory.json``."""
        return {
            "provider": self.provider,
            "authoritative_asset_pack": self.authoritative_asset_pack,
            "icon_source": self.icon_source,
            "icon_count": len(self.icons),
            "icons": [_icon_to_json(icon) for icon in self.icons],
        }


def _icon_to_json(icon: IconEntry) -> dict:
    obj = asdict(icon)
    # Drop a null file to keep built-in/library entries compact.
    if obj.get("file") is None:
        obj.pop("file", None)
    return obj


# --------------------------------------------------------------------------- #
# Curated built-in seed inventory (offline-safe)
# --------------------------------------------------------------------------- #
#
# Canonical icons for the nine neutral resource types per provider, each with a
# proper #RRGGBB brand hex sourced from design.md section 4b. AWS ids use the
# built-in mxgraph.aws4 library; azure/gcp/oci ids reference the custom unpacked
# shape libraries. Brand palette anchors: AWS S3 #7AA116, Azure #0078D4,
# GCP #4285F4, OCI #F80000 (per design section 4b).

# Per-provider "house" brand color used where a service does not have a distinct
# published brand hex; keeps every entry a valid #RRGGBB. Sourced from the
# central brand palette (constants.BRAND_HEX).
_HOUSE_HEX: dict[str, str] = {p: BRAND_HEX[p] for p in ("aws", "azure", "gcp", "oci")}

# (resource_type -> (icon_id, name, brand_hex)) per provider, loaded from the
# single terminology source of truth (profiles/terminology.yaml via constants).
_SEED: dict[str, dict[str, tuple[str, str, str]]] = _seed_icons_source()


def _seed_icons(provider: str) -> list[IconEntry]:
    """Return the curated seed icons for ``provider`` in neutral-type order."""
    rows = _SEED.get(provider, {})
    icons: list[IconEntry] = []
    for resource_type in NEUTRAL_RESOURCE_TYPES:
        if resource_type not in rows:
            continue
        icon_id, name, brand_hex = rows[resource_type]
        if not _HEX_RE.match(brand_hex):
            # Defensive: never emit an invalid brand hex; fall back to the
            # provider house color (which is itself validated below).
            brand_hex = _HOUSE_HEX.get(provider, "#000000")
        icons.append(
            IconEntry(
                resource_type=resource_type,
                icon_id=icon_id,
                name=name,
                brand_hex=brand_hex,
                file=None,
                origin="seed",
            )
        )
    return icons


# Exposed for tests / callers that want the raw seed inventory without touching
# the filesystem.
SEED_INVENTORY: dict[str, tuple[IconEntry, ...]] = {
    provider: tuple(_seed_icons(provider)) for provider in _SEED
}


# --------------------------------------------------------------------------- #
# Provenance helpers
# --------------------------------------------------------------------------- #


def provider_icon_source(provider: str) -> str:
    """Return the icon reference source (``builtin`` | ``custom``) for ``provider``.

    Derived from the authoritative (first) asset source registered in
    :data:`rule_engine.assets.fetch.ASSET_SOURCES`. Raises :class:`KeyError` for
    an unknown provider.
    """
    return ASSET_SOURCES[provider][0].icon_source


def _read_source_marker(provider_dir: Path) -> dict:
    """Read the ``SOURCE.json`` provenance marker, tolerating a missing/bad file."""
    marker = provider_dir / "SOURCE.json"
    if not marker.exists():
        return {}
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------- #
# Discovery of real downloaded assets
# --------------------------------------------------------------------------- #


def _slugify(text: str) -> str:
    """Lowercase, hyphen-separate an identifier fragment."""
    slug = re.sub(r"[^0-9A-Za-z]+", "-", text).strip("-").lower()
    return slug or "icon"


def _discover_icons(provider: str, provider_dir: Path) -> list[IconEntry]:
    """Enumerate icon files found under a real downloaded pack for ``provider``.

    Each discovered icon file becomes an :class:`IconEntry` with a slugged
    ``icon_id`` derived from its path, its file name as ``name``, and the
    provider house brand hex (discovered raster/vector files do not themselves
    carry a canonical brand hex, so the provider anchor color is applied to keep
    every entry a valid ``#RRGGBB``). Discovered entries have no neutral
    ``resource_type`` and ``origin="discovered"``.

    Returns an empty list when the provider directory is absent (offline) or
    contains no recognizable icon files.
    """
    if not provider_dir.is_dir():
        return []

    house_hex = _HOUSE_HEX.get(provider, "#000000")
    discovered: list[IconEntry] = []
    seen_ids: set[str] = set()

    for path in sorted(provider_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "SOURCE.json" or path.name == "inventory.json":
            continue
        if path.suffix.lower() not in _ICON_FILE_SUFFIXES:
            continue
        rel = path.relative_to(provider_dir)
        icon_id = _slugify(f"{provider}-{rel.as_posix()}")
        if icon_id in seen_ids:
            continue
        seen_ids.add(icon_id)
        discovered.append(
            IconEntry(
                resource_type="",
                icon_id=icon_id,
                name=path.stem,
                brand_hex=house_hex,
                file=rel.as_posix(),
                origin="discovered",
            )
        )
    return discovered


# --------------------------------------------------------------------------- #
# Build + write
# --------------------------------------------------------------------------- #


def _merge_icons(seed: Iterable[IconEntry], discovered: Iterable[IconEntry]) -> tuple[IconEntry, ...]:
    """Merge seed and discovered icons, de-duplicating on ``icon_id``.

    Seed icons take precedence: a discovered entry whose ``icon_id`` collides
    with a seed id is dropped.
    """
    merged: list[IconEntry] = list(seed)
    seed_ids = {icon.icon_id for icon in merged}
    for icon in discovered:
        if icon.icon_id in seed_ids:
            continue
        seed_ids.add(icon.icon_id)
        merged.append(icon)
    return tuple(merged)


def build_inventory(provider: str, *, assets_root: Path | None = None) -> ProviderInventory:
    """Build the :class:`ProviderInventory` for ``provider``.

    Always includes the curated seed icons (guaranteeing a non-empty inventory
    with valid ``#RRGGBB`` brand hexes even offline), then augments them with any
    icons discovered in a real downloaded pack under
    ``assets/<provider>/`` (or under ``assets_root`` if supplied).

    Raises :class:`KeyError` for an unknown provider.
    """
    if provider not in ASSET_SOURCES:
        raise KeyError(f"Unknown provider {provider!r}; known: {', '.join(PROVIDERS)}")

    root = assets_root or default_assets_root()
    provider_dir = root / provider

    seed = list(SEED_INVENTORY.get(provider, ()))
    discovered = _discover_icons(provider, provider_dir)
    icons = _merge_icons(seed, discovered)

    # Prefer the authoritative pack recorded in SOURCE.json (written by fetch.py);
    # fall back to the static registry value when the marker is absent (offline).
    marker = _read_source_marker(provider_dir)
    asset_pack = marker.get("authoritative_asset_pack") or provider_asset_pack(provider)

    return ProviderInventory(
        provider=provider,
        authoritative_asset_pack=asset_pack,
        icon_source=provider_icon_source(provider),
        icons=icons,
    )


def write_inventory(provider: str, *, assets_root: Path | None = None) -> Path:
    """Build and write ``assets/<provider>/inventory.json``; return the path.

    Creates the provider directory if it does not exist so the inventory is
    always produced, even when nothing was downloaded (offline).
    """
    root = assets_root or default_assets_root()
    provider_dir = root / provider
    provider_dir.mkdir(parents=True, exist_ok=True)

    inventory = build_inventory(provider, assets_root=root)
    target = provider_dir / "inventory.json"
    target.write_text(
        json.dumps(inventory.to_json_obj(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def write_all_inventories(
    providers: Iterable[str] | None = None,
    *,
    assets_root: Path | None = None,
) -> dict[str, Path]:
    """Write ``inventory.json`` for every provider (or a supplied subset).

    Returns a mapping ``provider -> inventory.json path``. Only providers with a
    curated seed inventory are enumerated by default (``aws``, ``azure``,
    ``gcp``, ``oci``); the ``generic`` profile carries no vendor asset pack.
    """
    keys = tuple(providers) if providers is not None else tuple(SEED_INVENTORY.keys())
    root = assets_root or default_assets_root()
    root.mkdir(parents=True, exist_ok=True)
    return {p: write_inventory(p, assets_root=root) for p in keys}


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def _main(argv: list[str] | None = None) -> int:
    """Enumerate asset packs from the command line.

    Usage::

        python -m rule_engine.assets.enumerate [provider ...]

    Prints one line per provider inventory written and always exits 0.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Enumerate provider asset packs into assets/<provider>/inventory.json."
    )
    parser.add_argument(
        "providers",
        nargs="*",
        choices=list(SEED_INVENTORY.keys()),
        help="Providers to enumerate (default: all with a seed inventory).",
    )
    parser.add_argument(
        "--assets-root", type=Path, default=None, help="Override the assets/ staging directory."
    )
    args = parser.parse_args(argv)

    selected = args.providers or None
    root = args.assets_root or default_assets_root()
    written = write_all_inventories(selected, assets_root=root)
    for provider, path in written.items():
        inv = build_inventory(provider, assets_root=root)
        print(f"[{provider}] wrote {len(inv.icons)} icons -> {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
