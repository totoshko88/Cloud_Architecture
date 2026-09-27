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
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

# The draw.io payload decoder lives in drawio_model (the single XML parser owns
# decompression); it is imported back here under the historical private name so
# the OCI <mxlibrary> extraction below keeps working unchanged.
from rule_engine.drawio_model import decode_compressed as _decode_drawio_payload

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def default_root() -> Path:
    """The engine repo root (this file is src/rule_engine/fetch_assets.py)."""
    return Path(__file__).resolve().parents[2]


def _sources_path(root: Path) -> Path:
    return root / "mappings" / "asset-sources.yaml"


# ---------------------------------------------------------------------------
# Pinning & secure download errors
# ---------------------------------------------------------------------------


class PackPinError(RuntimeError):
    """A pack's downloaded bytes do not match its pinned ``sha256``/``size``.

    Also raised when a provider has no pin at all: verification cannot proceed
    without a Pack_Pin, so the fetch is refused (R6.1).
    """

    def __init__(self, provider: str, expected: Any, actual: Any) -> None:
        self.provider = provider
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{provider}: pack pin mismatch: expected {expected}, got {actual}"
        )


class InsecureURLError(RuntimeError):
    """A pack URL — the initial request or any redirect — is not HTTPS (R6.2)."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"refusing non-HTTPS URL: {url}")


# ---------------------------------------------------------------------------
# HTTPS-only opener (injectable for tests)
# ---------------------------------------------------------------------------


class _HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that refuses to follow a non-HTTPS ``Location``.

    ``redirect_request`` is called for every 301/302/303/307 hop, so this
    enforces HTTPS at *every* redirect step, not just the initial URL (R6.2).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise InsecureURLError(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _https_opener() -> urllib.request.OpenerDirector:
    """An opener that follows redirects but rejects any non-HTTPS hop (R6.2)."""
    return urllib.request.build_opener(_HTTPSOnlyRedirectHandler())


# The opener used by ``_download_verified``; injectable so tests can supply a
# fake that serves bytes from a fixture without any network access.
def default_opener() -> urllib.request.OpenerDirector:
    return _https_opener()


# ---------------------------------------------------------------------------
# Download / unpack
# ---------------------------------------------------------------------------


def _pin_for(provider: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Return the ``{sha256, size}`` Pack_Pin for a provider, or refuse.

    A provider whose ``sha256``/``size`` keys are absent or empty has no pin;
    verification is impossible, so the fetch is refused with a message pointing
    at the ``--update-pins`` command (task 14.6) that creates the first pins.
    """
    sha256 = spec.get("sha256")
    size = spec.get("size")
    if not sha256 or size in (None, ""):
        raise PackPinError(
            provider,
            "a sha256+size pin (run `rule-engine-build-icon-sets --update-pins`)",
            "no pin",
        )
    return {"sha256": str(sha256).lower(), "size": int(size)}


def _hash_file(path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, byte_count)`` for ``path`` (streamed)."""
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 16)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def _download_verified(
    url: str,
    pin: Dict[str, Any],
    cache_dir: Path,
    *,
    provider: str = "?",
    opener: Optional[urllib.request.OpenerDirector] = None,
    timeout: int = 120,
) -> Path:
    """Download ``url``, verify against ``pin``, and land it at ``<sha256>.zip``.

    The download streams into a ``NamedTemporaryFile`` inside ``cache_dir`` while
    the sha256 and byte count are computed on the fly. On a size or digest
    mismatch the temp file is removed and ``PackPinError`` is raised; on success
    the temp file is atomically ``os.replace``-d to ``cache_dir/<sha256>.zip``
    (R6.3). A pack already cached under its digest name is re-hashed before reuse
    (a corrupted cache never reaches the index). Legacy ``<key>.zip`` cache names
    are ignored.
    """
    # Enforce HTTPS on the initial URL up front — a non-HTTPS source is refused
    # even if a matching digest happens to sit in the cache (R6.2).
    if urllib.parse.urlsplit(url).scheme != "https":
        raise InsecureURLError(url)

    cache_dir.mkdir(parents=True, exist_ok=True)
    expected_sha = pin["sha256"]
    expected_size = pin["size"]

    cached = cache_dir / f"{expected_sha}.zip"
    if cached.is_file():
        sha, size = _hash_file(cached)
        if sha == expected_sha and size == expected_size:
            return cached
        # Corrupt cache entry — drop it and re-download.
        cached.unlink()

    op = opener or default_opener()
    req = urllib.request.Request(
        url, headers={"User-Agent": "rule-engine-asset-fetcher"}
    )
    h = hashlib.sha256()
    size = 0
    tmp = tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".part", delete=False)
    tmp_path = Path(tmp.name)
    try:
        with op.open(req, timeout=timeout) as resp:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
                tmp.write(chunk)
        tmp.close()
        actual_sha = h.hexdigest()
        if size != expected_size or actual_sha != expected_sha:
            raise PackPinError(
                provider,
                {"sha256": expected_sha, "size": expected_size},
                {"sha256": actual_sha, "size": size},
            )
        dest = cache_dir / f"{expected_sha}.zip"
        os.replace(tmp_path, dest)
        return dest
    finally:
        if not tmp.closed:
            tmp.close()
        if tmp_path.exists():
            tmp_path.unlink()


def _download_no_pin(
    url: str,
    cache_dir: Path,
    *,
    opener: Optional[urllib.request.OpenerDirector] = None,
    timeout: int = 120,
) -> Path:
    """Download ``url`` over HTTPS with **no** pin to verify against.

    This is the primitive behind ``rule-engine-build-icon-sets --update-pins``:
    a pin does not exist yet (it is what the command is about to compute), so the
    bytes are downloaded, streamed to a temp file in ``cache_dir``, and returned
    for the caller to ``_hash_file``. HTTPS is still enforced on the initial URL
    and on every redirect hop (R6.2) — the injectable ``opener`` (default the
    HTTPS-only opener) owns the redirect refusal. The file lands at
    ``cache_dir/download-<rand>.zip`` and the caller is responsible for its
    lifetime (``--update-pins`` uses a ``TemporaryDirectory``).
    """
    if urllib.parse.urlsplit(url).scheme != "https":
        raise InsecureURLError(url)
    cache_dir.mkdir(parents=True, exist_ok=True)
    op = opener or default_opener()
    req = urllib.request.Request(
        url, headers={"User-Agent": "rule-engine-asset-fetcher"}
    )
    tmp = tempfile.NamedTemporaryFile(
        dir=cache_dir, prefix="download-", suffix=".zip", delete=False
    )
    tmp_path = Path(tmp.name)
    try:
        with op.open(req, timeout=timeout) as resp:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                tmp.write(chunk)
        tmp.close()
        return tmp_path
    except BaseException:
        if not tmp.closed:
            tmp.close()
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _unpack_fresh(zip_path: Path, out_dir: Path) -> int:
    """Unpack ``zip_path`` into a fresh ``out_dir``, replacing any prior contents.

    Extraction goes into a hidden sibling staging directory
    (``.<name>.staging-<rand>``) using the same zip-slip guard as ``_unpack``.
    Only on a clean extraction is the staging directory swapped into place: the
    existing ``out_dir`` (if any) is renamed to ``.<name>.old-<rand>``, the
    staging directory is ``os.replace``-d onto ``out_dir``, and the old copy is
    removed. This guarantees that files from an earlier pack version cannot
    survive in ``out_dir`` and reach the index (R6.3).
    """
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(4)
    staging = out_dir.with_name(f".{out_dir.name}.staging-{token}")
    old = out_dir.with_name(f".{out_dir.name}.old-{token}")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        count = _unpack(zip_path, staging)
        if out_dir.exists():
            os.replace(out_dir, old)
        os.replace(staging, out_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
    return count


def _unpack(zip_path: Path, out_dir: Path) -> int:
    """Unpack ``zip_path`` into ``out_dir``, skipping mac cruft. Returns file count.

    Rejects any entry whose resolved path escapes ``out_dir`` (zip-slip), so a
    tampered or malicious pack cannot write outside the asset root.

    The archive is opened BEFORE ``out_dir`` is created (v1.6.1): a download
    that is not a zip (an HTML error page, a truncated file) used to leave an
    empty pack directory behind, which the icon-index check then read as a
    present-but-stale pack instead of a missing one.
    """
    with zipfile.ZipFile(zip_path) as zf:
        out_dir.mkdir(parents=True, exist_ok=True)
        root = out_dir.resolve()
        count = 0
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
    opener: Optional[urllib.request.OpenerDirector] = None,
) -> Dict[str, Any]:
    """Fetch and unpack one provider pack; extract OCI stencils when applicable.

    The pack is verified against its pinned ``sha256``/``size`` before it is
    unpacked (R6.1), downloaded HTTPS-only and atomically into a digest-keyed
    cache (R6.2/R6.3), and unpacked into a fresh directory so stale files from an
    earlier pack version cannot survive (R6.3). A provider without a pin is
    refused with a message pointing at ``--update-pins``.
    """
    url = spec["url"]
    unpack_to = spec.get("unpack_to", key)
    out_dir = asset_root / unpack_to

    pin = _pin_for(key, spec)
    cached = cache_dir / f"{pin['sha256']}.zip"
    if not force and cached.is_file():
        print(f"  [{key}] using cached {cached}")
    else:
        print(f"  [{key}] downloading {url}")
    zip_path = _download_verified(url, pin, cache_dir, provider=key, opener=opener)

    n = _unpack_fresh(zip_path, out_dir)
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
    opener: Optional[urllib.request.OpenerDirector] = None,
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
            fetch_provider(
                key, providers[key], a_root, c_dir, force=force, opener=opener
            )
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
