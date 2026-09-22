"""Asset-pack ingestion for the Rule Engine.

This subpackage stages the official icon / style asset packs for each provider
profile into a local ``assets/<provider>/`` directory so that later tasks
(icon-mapping enumeration in task 2.2 and the Icon Resolver in task 7.1) can
read authoritative icon identifiers and brand colors from a single, declared
source per provider.

Modules
-------
fetch
    Per-provider source registry plus download-and-unpack functions that
    populate ``assets/<provider>/``. Designed to degrade gracefully when the
    network is unavailable (offline mode) rather than crash the build.
enumerate
    Scans each staged ``assets/<provider>/`` directory and writes an
    ``inventory.json`` (icon id/file, name, brand hex per icon) recording the
    authoritative asset-pack identifier and icon reference source per provider.
    Ships a curated built-in seed inventory so a valid, non-empty inventory is
    produced even when no assets were downloaded (offline mode).

The downloaded asset packs are intentionally excluded from version control
(see the repository ``.gitignore`` which ignores ``assets/``); only the source
registry and the code that fetches them are committed.
"""

from rule_engine.assets.fetch import (
    ASSET_SOURCES,
    AssetSource,
    FetchResult,
    fetch_all,
    fetch_provider,
    provider_asset_pack,
)

# ``enumerate`` shadows the builtin; import it by its module path explicitly.
from rule_engine.assets.enumerate import (
    NEUTRAL_RESOURCE_TYPES,
    SEED_INVENTORY,
    IconEntry,
    ProviderInventory,
    build_inventory,
    provider_icon_source,
    write_all_inventories,
    write_inventory,
)

__all__ = [
    "ASSET_SOURCES",
    "AssetSource",
    "FetchResult",
    "fetch_all",
    "fetch_provider",
    "provider_asset_pack",
    "NEUTRAL_RESOURCE_TYPES",
    "SEED_INVENTORY",
    "IconEntry",
    "ProviderInventory",
    "build_inventory",
    "provider_icon_source",
    "write_all_inventories",
    "write_inventory",
]
