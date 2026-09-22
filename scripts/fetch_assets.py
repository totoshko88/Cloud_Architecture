#!/usr/bin/env python3
"""Fetch & unpack official provider icon asset packs, and extract OCI stencils.

This is the local, on-demand asset fetcher described in the ``asset-packs.md``
steering document. It reads ``mappings/asset-sources.yaml`` (the single source of
truth for pack URLs and layouts), downloads each provider's official pack, unpacks
it into a git-ignored asset root, and — for OCI, whose shapes are shipped as a
draw.io ``<mxlibrary>`` rather than per-service files — decodes that library into
a per-title JSON of ready-to-embed stencil XML.

Rules act per the mapping: URLs and layouts live in data (the YAML), never in core
code. Nothing downloaded here is committed; the asset root is ignored by git.

Usage::

    # Fetch everything declared in mappings/asset-sources.yaml
    python scripts/fetch_assets.py

    # Fetch only some providers, into a custom root
    python scripts/fetch_assets.py --only oci aws --root assets/vendor

    # Skip download if the pack ZIP is already cached
    python scripts/fetch_assets.py --cache .build-tools/asset-cache

Exit codes: 0 success; 2 usage/config error; 1 one or more providers failed.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
import zipfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES = REPO_ROOT / "mappings" / "asset-sources.yaml"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Download / unpack
# ---------------------------------------------------------------------------


def _download(url: str, dest: Path, *, timeout: int = 120) -> None:
    """Download ``url`` to ``dest`` (streamed)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "rule-engine-asset-fetcher"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)


def _unpack(zip_path: Path, out_dir: Path) -> int:
    """Unpack ``zip_path`` into ``out_dir``, skipping mac cruft. Returns file count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if "__MACOSX" in name or name.endswith(".DS_Store") or name.endswith("/"):
                continue
            zf.extract(name, out_dir)
            count += 1
    return count


# ---------------------------------------------------------------------------
# OCI stencil extraction (draw.io <mxlibrary>)
# ---------------------------------------------------------------------------


def _decode_drawio_payload(payload: str) -> str:
    """Decode a draw.io library ``xml`` payload (base64 -> raw-deflate -> URL-decode)."""
    raw = base64.b64decode(payload)
    try:
        text = zlib.decompress(raw, -15).decode("utf-8")
    except zlib.error:
        text = zlib.decompress(raw).decode("utf-8")
    return urllib.parse.unquote(text)


def _slugify(title: str) -> str:
    """OCI library title -> slug, e.g. 'Compute - Functions' -> 'functions'."""
    # Drop the leading category prefix ("Compute - ").
    core = title.split(" - ", 1)[-1] if " - " in title else title
    core = core.lower()
    core = re.sub(r"[^a-z0-9]+", "-", core).strip("-")
    return core


def extract_oci_stencils(library_xml: Path) -> Dict[str, Dict[str, Any]]:
    """Decode an OCI ``OCI Library.xml`` into ``slug -> {title, w, h, xml}``.

    ``xml`` is the decoded ``<mxGraphModel>`` group for the shape, ready to embed
    as child cells (so it renders without the library installed).
    """
    text = library_xml.read_text(encoding="utf-8")
    m = re.search(r"<mxlibrary>(.*)</mxlibrary>", text, re.S)
    if not m:
        raise ValueError(f"{library_xml} is not a draw.io <mxlibrary>")
    entries = json.loads(m.group(1))
    out: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        title = entry.get("title") or ""
        payload = entry.get("xml")
        if not title or not payload:
            continue
        slug = _slugify(title)
        if not slug:
            continue
        try:
            decoded = _decode_drawio_payload(payload)
        except (ValueError, zlib.error, base64.binascii.Error):
            continue
        # Keep the first occurrence of each slug (library is category-ordered).
        out.setdefault(slug, {
            "title": title,
            "w": entry.get("w"),
            "h": entry.get("h"),
            "xml": decoded,
        })
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def load_sources(path: Path = SOURCES) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"asset sources config not found: {path}")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "providers" not in data:
        raise ValueError(f"{path} is not a valid asset-sources config")
    return data


def fetch_provider(
    key: str,
    spec: Dict[str, Any],
    asset_root: Path,
    cache_dir: Path,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Fetch and unpack one provider pack; extract OCI stencils when applicable."""
    url = spec["url"]
    unpack_to = spec.get("unpack_to", key)
    zip_path = cache_dir / f"{key}.zip"
    out_dir = asset_root / unpack_to

    if force or not zip_path.is_file():
        print(f"  [{key}] downloading {url}")
        _download(url, zip_path)
    else:
        print(f"  [{key}] using cached {zip_path}")

    n = _unpack(zip_path, out_dir)
    result: Dict[str, Any] = {"provider": key, "files": n, "unpacked": str(out_dir)}

    if spec.get("kind") == "drawio-library":
        lib_rel = spec.get("library_xml")
        lib_path = out_dir / lib_rel if lib_rel else None
        if lib_path and lib_path.is_file():
            stencils = extract_oci_stencils(lib_path)
            stencils_out = asset_root / spec.get("stencils_out", f"{key}-stencils")
            stencils_out.mkdir(parents=True, exist_ok=True)
            manifest = stencils_out / "stencils.json"
            manifest.write_text(
                json.dumps(stencils, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            result["stencils"] = len(stencils)
            result["stencils_manifest"] = str(manifest)
            print(f"  [{key}] extracted {len(stencils)} stencils -> {manifest}")
        else:
            print(f"  [{key}] WARNING: library_xml not found at {lib_path}", file=sys.stderr)

    print(f"  [{key}] unpacked {n} files -> {out_dir}")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch_assets",
        description="Download & unpack official provider icon packs (per mappings/asset-sources.yaml).",
    )
    parser.add_argument("--root", default=None, help="asset root (overrides config asset_root)")
    parser.add_argument("--cache", default=".build-tools/asset-cache", help="ZIP cache directory")
    parser.add_argument("--only", nargs="+", default=None, metavar="PROVIDER",
                        help="fetch only these provider keys")
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    args = parser.parse_args(argv)

    try:
        cfg = load_sources()
    except (FileNotFoundError, ValueError) as exc:
        print(f"fetch_assets: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    asset_root = Path(args.root or (REPO_ROOT / cfg.get("asset_root", "assets/vendor")))
    if not asset_root.is_absolute():
        asset_root = REPO_ROOT / asset_root
    cache_dir = REPO_ROOT / args.cache
    providers = cfg["providers"]

    keys = args.only or list(providers)
    unknown = [k for k in keys if k not in providers]
    if unknown:
        print(f"fetch_assets: error: unknown provider(s): {', '.join(unknown)}",
              file=sys.stderr)
        return EXIT_USAGE

    print(f"Asset root: {asset_root}")
    failures: List[str] = []
    for key in keys:
        try:
            fetch_provider(key, providers[key], asset_root, cache_dir, force=args.force)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  [{key}] FAILED: {exc}", file=sys.stderr)
            failures.append(key)

    if failures:
        print(f"fetch_assets: {len(failures)} provider(s) failed: {', '.join(failures)}",
              file=sys.stderr)
        return EXIT_FAIL
    print("fetch_assets: done.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
