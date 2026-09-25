"""Fetch & unpack official provider icon asset packs, and extract OCI stencils.

This is the installed-package form of the on-demand asset fetcher described in
the ``asset-packs.md`` steering document. It reads ``mappings/asset-sources.yaml``
(the single source of truth for pack URLs and layouts) **from a working root you
pass in**, downloads each provider's official pack, unpacks it into that root's
git-ignored asset directory, and — for OCI, whose shapes ship as a draw.io
``<mxlibrary>`` rather than per-service files — decodes that library into a
per-title JSON of ready-to-embed stencil XML.

Why it lives in the package (not only ``scripts/``)
---------------------------------------------------
Icons are materialized on demand and never committed (``/assets/`` is
git-ignored). A user who installs the engine (via pip or the Kiro Power) has the
``rule_engine`` package but may not have the repo's ``scripts/`` directory. So the
fetch logic must be importable from the package and operate on an **arbitrary
target workspace root**, so ``rule-engine-init --with-assets`` can materialize the
GCP/OCI icon files in a fresh workspace. ``scripts/fetch_assets.py`` remains as a
thin wrapper for the repo's own build.

Rules act per the mapping: URLs and layouts live in data (the YAML), never in core
code. Nothing downloaded here is committed; the asset root is ignored by git.

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

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def default_root() -> Path:
    """The engine repo root (this file is src/rule_engine/fetch_assets.py)."""
    return Path(__file__).resolve().parents[2]


def _sources_path(root: Path) -> Path:
    return root / "mappings" / "asset-sources.yaml"


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
    """Unpack ``zip_path`` into ``out_dir``, skipping mac cruft. Returns file count.

    Rejects any entry whose resolved path escapes ``out_dir`` (zip-slip), so a
    tampered or malicious pack cannot write outside the asset root.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    root = out_dir.resolve()
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if "__MACOSX" in name or name.endswith(".DS_Store") or name.endswith("/"):
                continue
            target = (out_dir / name).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"{zip_path}: entry {name!r} escapes {out_dir}")
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


def load_sources(path: Path) -> Dict[str, Any]:
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


def fetch_all(
    root: Path,
    *,
    only: Optional[Sequence[str]] = None,
    asset_root: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    force: bool = False,
) -> List[str]:
    """Fetch every (or ``only``) provider pack into ``root``. Returns failed keys.

    ``root`` is the working workspace root that holds ``mappings/asset-sources.yaml``
    and under which ``assets/vendor`` is materialized. This is what makes the
    fetcher usable in an arbitrary target workspace, not just the engine repo.
    """
    cfg = load_sources(_sources_path(root))
    a_root = asset_root or (root / cfg.get("asset_root", "assets/vendor"))
    if not a_root.is_absolute():
        a_root = root / a_root
    c_dir = cache_dir or (root / ".build-tools" / "asset-cache")
    providers = cfg["providers"]

    keys = list(only) if only else list(providers)
    unknown = [k for k in keys if k not in providers]
    if unknown:
        raise ValueError(f"unknown provider(s): {', '.join(unknown)}")

    print(f"Asset root: {a_root}")
    failures: List[str] = []
    for key in keys:
        try:
            fetch_provider(key, providers[key], a_root, c_dir, force=force)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  [{key}] FAILED: {exc}", file=sys.stderr)
            failures.append(key)
    return failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rule-engine-fetch-assets",
        description="Download & unpack official provider icon packs "
        "(per mappings/asset-sources.yaml).",
    )
    parser.add_argument("--workspace", default=".",
                        help="workspace root holding mappings/asset-sources.yaml "
                        "(default: current directory)")
    parser.add_argument("--root", default=None,
                        help="asset root (overrides config asset_root)")
    parser.add_argument("--cache", default=None, help="ZIP cache directory")
    parser.add_argument("--only", nargs="+", default=None, metavar="PROVIDER",
                        help="fetch only these provider keys")
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    args = parser.parse_args(argv)

    root = Path(args.workspace).expanduser().resolve()
    try:
        failures = fetch_all(
            root,
            only=args.only,
            asset_root=Path(args.root).expanduser().resolve() if args.root else None,
            cache_dir=Path(args.cache).expanduser().resolve() if args.cache else None,
            force=args.force,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"rule-engine-fetch-assets: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if failures:
        print(f"rule-engine-fetch-assets: {len(failures)} provider(s) failed: "
              f"{', '.join(failures)}", file=sys.stderr)
        return EXIT_FAIL
    print("rule-engine-fetch-assets: done.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
