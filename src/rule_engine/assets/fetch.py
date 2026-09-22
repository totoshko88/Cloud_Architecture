"""Download and unpack the official provider asset packs into ``assets/<provider>/``.

This module is the ingestion stage of the Rule Engine (task 2.1). It declares a
per-provider **source registry** recording the authoritative asset-pack
identifier for each provider profile, and provides download + unpack functions
that stage each pack into a local ``assets/<provider>/`` staging area.

Authoritative asset packs (per the design, section 4b "Icon Mapping Data Model")
------------------------------------------------------------------------------
- **oci**   — OCI draw.io style guide (custom draw.io shape library).
- **aws**   — ``mxgraph.aws4`` draw.io built-in library (AWS 2019+) *plus* the
              AWS Architecture Icons set. The primary reference is ``builtin``:
              ``mxgraph.aws4`` ships inside draw.io / the ``@mxgraph/drawio``
              distribution and needs no download, so the AWS entry records the
              built-in library as authoritative and treats the downloadable
              Architecture Icons archive as a supplementary pack.
- **azure** — Microsoft Azure architecture icon set, version V24 (custom).
- **gcp**   — Google Cloud architecture icons: the category icon set and the
              core-products icon set (custom).

Design goals
------------
1. **Declared provenance.** Every provider has exactly one authoritative
   ``asset_pack`` identifier and an ``icon_source`` of ``builtin`` or ``custom``,
   mirroring the mapping files authored in task 3. :func:`provider_asset_pack`
   exposes the identifier so downstream code records provenance consistently.
2. **Graceful degradation.** Network access is frequently unavailable in the
   packaging environment. Download failures (offline, DNS, HTTP errors) never
   raise out of :func:`fetch_provider` / :func:`fetch_all`; they are captured in
   a :class:`FetchResult` with ``status="offline"`` or ``status="error"`` so the
   build continues. Built-in packs report ``status="builtin"`` with no download.
3. **Idempotent staging.** Each pack is unpacked into ``assets/<provider>/``.
   A ``SOURCE.json`` provenance marker is always written (even offline) so a
   later enumeration step can record the authoritative identifier per provider.
4. **No large binaries in git.** ``assets/`` is git-ignored (see ``.gitignore``);
   this module only downloads into that ignored staging area.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

__all__ = [
    "AssetSource",
    "FetchResult",
    "ASSET_SOURCES",
    "PROVIDERS",
    "default_assets_root",
    "provider_asset_pack",
    "fetch_provider",
    "fetch_all",
]

# --------------------------------------------------------------------------- #
# Source registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AssetSource:
    """Declares where a single asset pack comes from and how to unpack it.

    Attributes
    ----------
    provider:
        Provider profile key (``aws`` | ``azure`` | ``gcp`` | ``oci``).
    asset_pack:
        Human-readable authoritative asset-pack identifier recorded as
        provenance for the provider (matches the ``asset_pack`` field used in
        ``mappings/<provider>-icons.yaml``).
    icon_source:
        ``"builtin"`` when the icons ship inside draw.io (no download needed) or
        ``"custom"`` when the icons are unpacked from a downloaded archive.
    urls:
        Candidate download URLs, tried in order until one succeeds. Empty for a
        ``builtin`` source. Multiple URLs allow resilient fallback mirrors.
    archive_kind:
        Archive type to unpack: ``"zip"`` or ``"none"`` (built-in / no archive).
    description:
        Short note describing the pack's contents.
    """

    provider: str
    asset_pack: str
    icon_source: str
    urls: tuple[str, ...] = field(default_factory=tuple)
    archive_kind: str = "zip"
    description: str = ""

    @property
    def requires_download(self) -> bool:
        """True when this source must be fetched over the network."""
        return self.icon_source == "custom" and self.archive_kind != "none"


# Authoritative per-provider asset-pack registry.
#
# URLs are the publicly documented distribution points for each icon set. They
# are intentionally treated as *candidates*: if none resolve (offline build),
# fetching degrades gracefully and records provenance only. The AWS entry is
# built-in (mxgraph.aws4 ships with draw.io); AWS Architecture Icons are added
# as a supplementary custom pack for completeness.
ASSET_SOURCES: dict[str, tuple[AssetSource, ...]] = {
    "oci": (
        AssetSource(
            provider="oci",
            asset_pack="OCI draw.io style guide",
            icon_source="custom",
            urls=(
                "https://docs.oracle.com/en-us/iaas/Content/Resources/Assets/technicalstackicons/OCI_Icons.zip",
            ),
            archive_kind="zip",
            description="Oracle Cloud Infrastructure draw.io style guide / icon library.",
        ),
    ),
    "aws": (
        AssetSource(
            provider="aws",
            asset_pack="mxgraph.aws4 (draw.io built-in, AWS 2019+)",
            icon_source="builtin",
            urls=(),
            archive_kind="none",
            description=(
                "Built-in draw.io AWS 2019+ shape library (mxgraph.aws4); "
                "no download required, ships with draw.io."
            ),
        ),
        AssetSource(
            provider="aws",
            asset_pack="AWS Architecture Icons",
            icon_source="custom",
            urls=(
                "https://d1.awsstatic.com/webteam/architecture-icons/Asset-Package.zip",
            ),
            archive_kind="zip",
            description="Official AWS Architecture Icons asset package (supplementary to mxgraph.aws4).",
        ),
    ),
    "azure": (
        AssetSource(
            provider="azure",
            asset_pack="Azure architecture icons V24",
            icon_source="custom",
            urls=(
                "https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V24.zip",
            ),
            archive_kind="zip",
            description="Microsoft Azure public service / architecture icon set, version V24.",
        ),
    ),
    "gcp": (
        AssetSource(
            provider="gcp",
            asset_pack="GCP architecture icons (category + core-products)",
            icon_source="custom",
            urls=(
                "https://cloud.google.com/static/architecture/images/icons.zip",
            ),
            archive_kind="zip",
            description="Google Cloud architecture icons: category icon set plus core-products icon set.",
        ),
    ),
}

PROVIDERS: tuple[str, ...] = tuple(ASSET_SOURCES.keys())


def provider_asset_pack(provider: str) -> str:
    """Return the authoritative asset-pack identifier declared for ``provider``.

    The authoritative pack is the first source registered for the provider (the
    built-in library for AWS, the sole custom pack for the others). Raises
    :class:`KeyError` for an unknown provider.
    """
    sources = ASSET_SOURCES[provider]
    return sources[0].asset_pack


# --------------------------------------------------------------------------- #
# Fetch result model
# --------------------------------------------------------------------------- #


@dataclass
class FetchResult:
    """Outcome of staging one asset source into ``assets/<provider>/``.

    ``status`` is one of:
    - ``"downloaded"`` — archive fetched and unpacked successfully.
    - ``"builtin"``    — no download needed (ships with draw.io).
    - ``"offline"``    — network unreachable / all URLs failed to connect.
    - ``"error"``      — a non-network failure occurred while unpacking.
    - ``"skipped"``    — nothing to do (no URLs and not built-in).
    """

    provider: str
    asset_pack: str
    icon_source: str
    status: str
    target_dir: str
    source_url: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        """True when the source is usable (downloaded or built-in)."""
        return self.status in ("downloaded", "builtin")


# --------------------------------------------------------------------------- #
# Filesystem helpers
# --------------------------------------------------------------------------- #


def default_assets_root() -> Path:
    """Return the default ``assets/`` staging directory at the repository root.

    Resolved relative to this file: ``src/rule_engine/assets/fetch.py`` →
    repository root is three parents up. The staging root is git-ignored.
    """
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "assets"


def _provider_dir(assets_root: Path, provider: str) -> Path:
    return assets_root / provider


def _write_source_marker(target_dir: Path, source: AssetSource, result: FetchResult) -> None:
    """Persist a ``SOURCE.json`` provenance marker for the provider directory.

    Written on every run (including offline) so the enumeration step can record
    the authoritative asset-pack identifier and icon reference source per
    provider even before any binary is available locally.
    """
    marker = target_dir / "SOURCE.json"
    payload: dict = {}
    if marker.exists():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    payload.setdefault("provider", source.provider)
    packs = payload.setdefault("asset_packs", [])
    entry = {
        "asset_pack": source.asset_pack,
        "icon_source": source.icon_source,
        "status": result.status,
        "source_url": result.source_url,
        "description": source.description,
    }
    # Replace any prior entry for the same asset pack to stay idempotent.
    packs[:] = [p for p in packs if p.get("asset_pack") != source.asset_pack]
    packs.append(entry)
    # The authoritative pack is the first registered source for the provider.
    payload["authoritative_asset_pack"] = provider_asset_pack(source.provider)
    marker.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Download + unpack
# --------------------------------------------------------------------------- #


def _download(url: str, dest: Path, timeout: float) -> None:
    """Download ``url`` to ``dest``. Raises ``urllib.error.URLError`` on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "rule-engine-asset-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 (declared source URLs)
        with dest.open("wb") as fh:
            shutil.copyfileobj(response, fh)


def _unpack_zip(archive: Path, target_dir: Path) -> None:
    """Extract a zip ``archive`` into ``target_dir``, guarding against path escape."""
    with zipfile.ZipFile(archive) as zf:
        target_root = target_dir.resolve()
        for member in zf.namelist():
            resolved = (target_dir / member).resolve()
            if not str(resolved).startswith(str(target_root)):
                raise ValueError(f"Unsafe archive member path: {member!r}")
        zf.extractall(target_dir)


def _fetch_one(
    source: AssetSource,
    assets_root: Path,
    *,
    timeout: float,
) -> FetchResult:
    """Stage a single :class:`AssetSource` into ``assets/<provider>/``."""
    target_dir = _provider_dir(assets_root, source.provider)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Built-in libraries need no download; just record provenance.
    if not source.requires_download:
        if source.icon_source == "builtin":
            result = FetchResult(
                provider=source.provider,
                asset_pack=source.asset_pack,
                icon_source=source.icon_source,
                status="builtin",
                target_dir=str(target_dir),
                detail="Ships with draw.io; no download required.",
            )
        else:
            result = FetchResult(
                provider=source.provider,
                asset_pack=source.asset_pack,
                icon_source=source.icon_source,
                status="skipped",
                target_dir=str(target_dir),
                detail="No download URLs declared.",
            )
        _write_source_marker(target_dir, source, result)
        return result

    last_error: str | None = None
    for url in source.urls:
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp_path = Path(tmp.name)
            _download(url, tmp_path, timeout)
            if source.archive_kind == "zip":
                _unpack_zip(tmp_path, target_dir)
            else:
                shutil.copy2(tmp_path, target_dir / Path(url).name)
            result = FetchResult(
                provider=source.provider,
                asset_pack=source.asset_pack,
                icon_source=source.icon_source,
                status="downloaded",
                target_dir=str(target_dir),
                source_url=url,
            )
            _write_source_marker(target_dir, source, result)
            return result
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Connectivity / IO failure — try the next candidate URL.
            last_error = f"{type(exc).__name__}: {exc}"
        except (zipfile.BadZipFile, ValueError) as exc:
            # Downloaded but could not unpack — non-network error.
            result = FetchResult(
                provider=source.provider,
                asset_pack=source.asset_pack,
                icon_source=source.icon_source,
                status="error",
                target_dir=str(target_dir),
                source_url=url,
                detail=f"{type(exc).__name__}: {exc}",
            )
            _write_source_marker(target_dir, source, result)
            return result
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    # All candidate URLs failed to connect: treat as offline, degrade gracefully.
    result = FetchResult(
        provider=source.provider,
        asset_pack=source.asset_pack,
        icon_source=source.icon_source,
        status="offline",
        target_dir=str(target_dir),
        detail=last_error or "No reachable download URL.",
    )
    _write_source_marker(target_dir, source, result)
    return result


def fetch_provider(
    provider: str,
    *,
    assets_root: Path | None = None,
    timeout: float = 30.0,
) -> list[FetchResult]:
    """Download and unpack every asset pack declared for ``provider``.

    Writes into ``assets/<provider>/`` (or under ``assets_root`` if supplied).
    Never raises on network failure — offline / unreachable sources yield a
    :class:`FetchResult` with ``status="offline"``. Raises :class:`KeyError`
    only for an unknown provider.
    """
    if provider not in ASSET_SOURCES:
        raise KeyError(f"Unknown provider {provider!r}; known: {', '.join(PROVIDERS)}")
    root = assets_root or default_assets_root()
    root.mkdir(parents=True, exist_ok=True)
    return [_fetch_one(src, root, timeout=timeout) for src in ASSET_SOURCES[provider]]


def fetch_all(
    providers: Iterable[str] | None = None,
    *,
    assets_root: Path | None = None,
    timeout: float = 30.0,
) -> dict[str, list[FetchResult]]:
    """Download and unpack asset packs for every provider (or a given subset).

    Returns a mapping ``provider -> [FetchResult, ...]``. Degrades gracefully:
    a fully offline environment still produces provenance markers and a result
    per source, so the caller can report status without the build failing.
    """
    keys = tuple(providers) if providers is not None else PROVIDERS
    root = assets_root or default_assets_root()
    root.mkdir(parents=True, exist_ok=True)
    return {p: fetch_provider(p, assets_root=root, timeout=timeout) for p in keys}


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def _main(argv: list[str] | None = None) -> int:
    """Fetch asset packs from the command line.

    Usage::

        python -m rule_engine.assets.fetch [provider ...]

    Prints a per-source status line and always exits 0 (offline is not a build
    failure — provenance is still recorded).
    """
    import argparse

    parser = argparse.ArgumentParser(description="Stage provider asset packs into assets/<provider>/.")
    parser.add_argument("providers", nargs="*", choices=list(PROVIDERS),
                        help="Providers to fetch (default: all).")
    parser.add_argument("--assets-root", type=Path, default=None,
                        help="Override the assets/ staging directory.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-download timeout in seconds.")
    args = parser.parse_args(argv)

    selected = args.providers or None
    results = fetch_all(selected, assets_root=args.assets_root, timeout=args.timeout)
    for provider, provider_results in results.items():
        for res in provider_results:
            detail = f" ({res.detail})" if res.detail else ""
            print(f"[{provider}] {res.status:<10} {res.asset_pack} -> {res.target_dir}{detail}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
