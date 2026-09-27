"""Init-time icon-set builder CLI (``rule-engine-build-icon-sets``).

Standardises service icons on the official provider bundles at initialisation:
fetch every pack declared in ``mappings/asset-sources.yaml``, index each pack's
filename / library structure, and write the committed ``mappings/icon-index.json``
(``pack_summary`` + per-role resolved icons) and the committed
``mappings/oci-stencil-digests.json`` (``{slug: sha256}``, hashes only). See
``audit-2026-09-23/11-landscape-regeneration-lessons.md`` §5a/§5b for the design.

The heavy vendor binaries stay uncommitted in ``assets/vendor/``; only the index
(the lookup table) is committed, so generators and CI resolve role→icon and verify
wiring without the packs present. A new/renamed vendor icon is a re-index, not a
code edit.

Usage::

    rule-engine-build-icon-sets                 # fetch (if needed) + build index
    rule-engine-build-icon-sets --no-fetch      # index already-fetched packs only
    rule-engine-build-icon-sets --check         # verify the committed index is current
    rule-engine-build-icon-sets --full          # embed full per-slug pack tables
    rule-engine-build-icon-sets --check --no-fetch --allow-missing
                                                # CI: stale index fails; a pack that
                                                # failed to download is skipped
    rule-engine-build-icon-sets --update-pins   # download each pack, rewrite the
                                                # sha256:/size: pins in asset-sources.yaml
                                                # (comments survive), then rebuild
    rule-engine-build-icon-sets --update-pins --only aws azure
                                                # update pins for two providers only
    rule-engine-build-icon-sets --manifests-dir path/mappings
                                                # write the committed manifests there

Exit codes: 0 success / index current (or, with --allow-missing, packs absent);
1 build failed or index stale (--check); 2 usage/config error.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from rule_engine.asset_index import build_icon_index, icon_index_to_json
from rule_engine.constants import resolve_bundled_dir
from rule_engine.icon_refs import oci_glyph_digest

# The repo root: this file is src/rule_engine/build_icon_sets_cli.py -> ... -> root.
REPO_ROOT = Path(__file__).resolve().parents[2]
# The committed icon index lives in the mappings/ tree. Resolve it through the
# shared repo → bundled-payload → CWD helper (v1.5.1): on a pip/Power install
# ``REPO_ROOT`` (parents[2]) is NOT the repo root, so a bare
# ``REPO_ROOT / "mappings"`` wrote/read the index in the wrong place. The
# asset-root default stays under the resolved mappings' parent so a rebuild
# writes next to the tree it belongs to, not into an unrelated CWD.
_MAPPINGS_DIR = resolve_bundled_dir("mappings")
ICON_INDEX_OUT = _MAPPINGS_DIR / "icon-index.json"
# Workspace root that owns the resolved mappings/ tree (its parent), used as the
# base for the default asset root and relative --out/--asset-root values.
_WORKSPACE_ROOT = _MAPPINGS_DIR.parent

# Pack key -> unpacked root under the asset root (mirrors asset-sources.yaml
# `unpack_to`). GCP resolves against two packs (core products first, then
# categories); OCI resolves against the decoded stencils.json.
_PACK_ROOTS = {
    "aws": "aws-icons",
    "azure": "azure-icons",
    "gcp-core": "gcp-core",
    "gcp-category": "gcp-category",
    "oci": "oci-stencils/stencils.json",
}

def _shown(path: Path) -> str:
    """Return a workspace-relative display path, or the absolute path.

    A written file may live under the resolved workspace root (repo, bundled
    payload, or a target workspace passed via --out), so ``relative_to`` may
    raise; fall back to the absolute path then (v1.5.1)."""
    try:
        return str(Path(path).relative_to(_WORKSPACE_ROOT))
    except ValueError:
        return str(path)


EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def _pack_roots(asset_root: Path) -> Dict[str, str]:
    return {key: str(asset_root / rel) for key, rel in _PACK_ROOTS.items()}


# asset-sources.yaml keys the providers as aws/azure/gcp_category/gcp_core/oci;
# the icon index keys the packs as aws/azure/gcp-category/gcp-core/oci. Map one
# to the other so the pin sha256 lands on the right pack summary (R6.4).
_SOURCE_KEY_TO_PACK = {
    "aws": "aws",
    "azure": "azure",
    "gcp_category": "gcp-category",
    "gcp_core": "gcp-core",
    "oci": "oci",
}


def _load_pack_pins() -> Dict[str, str]:
    """Return ``{pack_key: sha256}`` from ``mappings/asset-sources.yaml``.

    The pin sha256 is what ``build_icon_index`` records in ``pack_summary``
    (R6.4) — the digest of the verified pack, never recomputed from the tree.
    A provider whose pin is not yet populated (the placeholder ``sha256: ""``)
    contributes an empty digest, and any read error yields no pins at all."""
    sources = _MAPPINGS_DIR / "asset-sources.yaml"
    try:
        import yaml  # PyYAML is a runtime dep
        data = yaml.safe_load(sources.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - pins are optional; fail-honest to empty
        return {}
    pins: Dict[str, str] = {}
    for src_key, spec in (data.get("providers") or {}).items():
        pack_key = _SOURCE_KEY_TO_PACK.get(src_key)
        if pack_key is None or not isinstance(spec, dict):
            continue
        pins[pack_key] = str(spec.get("sha256") or "")
    return pins


# --------------------------------------------------------------------------- #
# --update-pins: download each pack, compute sha256+size, rewrite the pins in
# mappings/asset-sources.yaml (line-level so comments and layout survive), then
# rebuild the index. (honest-gates R6.5 / D7)
# --------------------------------------------------------------------------- #

_ASSET_SOURCES = _MAPPINGS_DIR / "asset-sources.yaml"

# A ``  <key>:`` provider header at two-space indent (the top-level providers'
# children sit two spaces further in). Only these open a provider block.
_PROVIDER_HEADER_RE = re.compile(r"^(?P<indent> {2,})(?P<key>[A-Za-z0-9_]+):\s*(?:#.*)?$")
# A ``sha256:``/``size:`` line, capturing the value region and any trailing
# comment so a rewrite can preserve the comment verbatim.
_PIN_LINE_RE = re.compile(
    r"^(?P<lead>\s*)(?P<key>sha256|size):(?P<gap>[ \t]*)(?P<value>.*?)(?P<comment>\s+#.*)?$"
)


def _sources_document_keys(text: str) -> Dict[str, int]:
    """Map each provider source-key to the indent width of its header line.

    Used to know which lines belong to a provider block: a block runs from its
    header until the next line indented at or below the header's indent.
    """
    depths: Dict[str, int] = {}
    for line in text.splitlines():
        m = _PROVIDER_HEADER_RE.match(line)
        if m:
            depths[m.group("key")] = len(m.group("indent"))
    return depths


def _rewrite_pin_lines(text: str, provider: str, sha256: str, size: int) -> str:
    """Return ``text`` with ``provider``'s ``sha256:``/``size:`` lines rewritten.

    A **line-oriented** rewrite: only the value on the ``sha256:`` and ``size:``
    lines inside ``provider``'s block changes; the trailing comment, indentation
    and every other line survive verbatim. PyYAML cannot round-trip comments, so
    a full dump would drop them — hence this targeted edit (R6.5).
    """
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    in_block = False
    block_indent = -1
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        eol = raw[len(line):]
        header = _PROVIDER_HEADER_RE.match(line)
        if header:
            key = header.group("key")
            indent = len(header.group("indent"))
            if key == provider:
                in_block = True
                block_indent = indent
            elif in_block and indent <= block_indent:
                in_block = False
            out.append(raw)
            continue
        if in_block:
            # A less-indented non-blank line closes the block (a sibling/parent).
            stripped = line.strip()
            if stripped and (len(line) - len(line.lstrip())) <= block_indent:
                in_block = False
            else:
                pin = _PIN_LINE_RE.match(line)
                if pin and pin.group("key") in ("sha256", "size"):
                    new_value = f'"{sha256}"' if pin.group("key") == "sha256" else str(size)
                    comment = pin.group("comment") or ""
                    rebuilt = f'{pin.group("lead")}{pin.group("key")}:{pin.group("gap") or " "}{new_value}{comment}'
                    out.append(rebuilt + eol)
                    continue
        out.append(raw)
    return "".join(out)


def _update_pins(
    *,
    only: Optional[Sequence[str]] = None,
    opener_factory: Optional[Callable[[], object]] = None,
) -> Tuple[int, Dict[str, Tuple[str, str, int]]]:
    """Download each pack, compute sha256+size, and rewrite the pins in place.

    Returns ``(exit_code, changes)`` where ``changes`` maps each updated source
    key to ``(old_sha256, new_sha256, new_size)``. The network opener is
    injectable (``opener_factory``) so a test can drive this without any network
    or real vendor pack (mirrors the fetcher's injectable opener). The pack bytes
    themselves are hashed, then discarded — this step writes only the pins.
    """
    fetch_assets = _load_fetch_assets()
    if fetch_assets is None:
        print(
            "rule-engine-build-icon-sets: scripts/fetch_assets.py not found; "
            "cannot download packs to compute pins.",
            file=sys.stderr,
        )
        return EXIT_USAGE, {}
    try:
        import yaml
        text = _ASSET_SOURCES.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"rule-engine-build-icon-sets: cannot read asset-sources.yaml: {exc}", file=sys.stderr)
        return EXIT_USAGE, {}

    providers = data.get("providers") or {}
    keys = list(only) if only else list(providers)
    unknown = [k for k in keys if k not in providers]
    if unknown:
        print(
            f"rule-engine-build-icon-sets: unknown provider(s): {', '.join(unknown)}",
            file=sys.stderr,
        )
        return EXIT_USAGE, {}

    import tempfile

    opener = (opener_factory or fetch_assets.default_opener)()
    changes: Dict[str, Tuple[str, str, int]] = {}
    failures: List[str] = []
    with tempfile.TemporaryDirectory(prefix="rule-engine-pins-") as tmp:
        cache_dir = Path(tmp)
        for key in keys:
            spec = providers[key]
            if not isinstance(spec, dict) or "url" not in spec:
                failures.append(key)
                print(f"  [{key}] no url in asset-sources.yaml", file=sys.stderr)
                continue
            url = spec["url"]
            old_sha = str(spec.get("sha256") or "")
            try:
                zip_path = fetch_assets._download_no_pin(url, cache_dir, opener=opener)
                new_sha, new_size = fetch_assets._hash_file(zip_path)
            except Exception as exc:  # noqa: BLE001 - report and continue
                failures.append(key)
                print(f"  [{key}] FAILED to download/hash {url}: {exc}", file=sys.stderr)
                continue
            text = _rewrite_pin_lines(text, key, new_sha, new_size)
            changes[key] = (old_sha, new_sha, new_size)
            print(f"  [{key}] {old_sha or '(none)'} -> {new_sha} ({new_size} bytes)")

    if changes:
        _ASSET_SOURCES.write_text(text, encoding="utf-8")
        print(f"Updated {_shown(_ASSET_SOURCES)} — {len(changes)} pin(s) rewritten.")
    if failures:
        print(
            f"rule-engine-build-icon-sets: {len(failures)} provider(s) failed: "
            f"{', '.join(failures)}",
            file=sys.stderr,
        )
        return EXIT_FAIL, changes
    return EXIT_OK, changes


# --------------------------------------------------------------------------- #
# OCI stencil digest manifest (honest-gates R4.1)
# --------------------------------------------------------------------------- #
#
# ``mappings/oci-stencil-digests.json`` binds each OCI stencil slug to the
# sha256 an OCI node built from that stencil renders (its ``shape=stencil(...)``
# payloads, hashed by ``icon_refs.oci_glyph_digest``). It holds **hashes only**
# — no vendor content — so committing it never redistributes vendor icon
# binaries. ``icon_refs`` resolves an ``oci-glyph`` ref against this manifest
# when the pack is absent, and requires ``oci_digests[slug] == glyph_digest`` so
# an ``ociSlug=`` marker cannot vouch for the wrong glyph. Written next to
# ``aws4-icons.json``; covered by ``--check``.

_STENCIL_PAYLOAD_RE = re.compile(r"shape=stencil\(([^)]*)\)")

# The committed digest manifest lives beside aws4-icons.json in the mappings dir.
OCI_DIGESTS_OUT = _MAPPINGS_DIR / "oci-stencil-digests.json"


def _stencil_payloads_for_xml(stencil_xml: str) -> list:
    """Every ``shape=stencil(...)`` payload embedded in one stencil's xml.

    ``embed_oci_stencil`` copies the ``shape=stencil(...)`` style verbatim (it
    rescales geometry only), so the payloads a node renders are exactly the
    payloads present in ``stencils.json[slug]["xml"]`` — hashing them here yields
    the same digest an ``icon_refs`` glyph ref computes from the diagram.
    """
    return _STENCIL_PAYLOAD_RE.findall(stencil_xml or "")


def build_oci_digests(stencils_path: Path) -> Optional[Dict[str, str]]:
    """Return ``{slug: sha256}`` derived from a decoded ``stencils.json``.

    Returns ``None`` when the stencils pack is absent (fail-honest: the packs are
    fetched on demand and may not be present). Each digest is
    ``oci_glyph_digest`` of the slug's embedded ``shape=stencil(...)`` payloads,
    so it matches the page-level glyph digest an OCI diagram produces.
    """
    stencils_path = Path(stencils_path)
    if not stencils_path.is_file():
        return None
    try:
        data = json.loads(stencils_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    digests: Dict[str, str] = {}
    for slug, entry in data.items():
        xml = entry.get("xml", "") if isinstance(entry, dict) else ""
        digests[str(slug)] = oci_glyph_digest(_stencil_payloads_for_xml(xml))
    return digests


def oci_digests_to_json(digests: Dict[str, str]) -> str:
    """Serialise the digest manifest deterministically (sorted keys)."""
    payload = {
        "manifest": "oci-stencil-digests",
        "count": len(digests),
        "digests": {slug: digests[slug] for slug in sorted(digests)},
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _load_fetch_assets():
    """Return the asset fetcher module.

    Prefer the installed-package fetcher (``rule_engine.fetch_assets``) so a
    pip/Power install works without the repo's ``scripts/`` directory; fall back
    to importing ``scripts/fetch_assets.py`` by path for older layouts."""
    try:
        from rule_engine import fetch_assets as _fa  # installed-package form
        return _fa
    except Exception:  # noqa: BLE001 - fall back to the scripts/ wrapper
        pass
    fa_path = REPO_ROOT / "scripts" / "fetch_assets.py"
    if not fa_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("fetch_assets", fa_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rule-engine-build-icon-sets",
        description="Fetch official icon packs and build the committed mappings/icon-index.json.",
    )
    parser.add_argument("--asset-root", default=str(_WORKSPACE_ROOT / "assets" / "vendor"),
                        help="unpacked asset root (default: <workspace>/assets/vendor)")
    parser.add_argument("--out", default=str(ICON_INDEX_OUT),
                        help="committed icon index path (default: mappings/icon-index.json)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the pack download/unpack; index already-fetched packs")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the committed index differs from a fresh build")
    parser.add_argument("--full", action="store_true",
                        help="embed the full per-slug pack tables (large); default writes a summary")
    parser.add_argument("--allow-missing", action="store_true",
                        help="with --check: when an unpacked pack is missing (e.g. the "
                        "download failed), skip the check with a warning and exit 0 "
                        "instead of failing. A STALE index still exits 1.")
    parser.add_argument("--update-pins", action="store_true",
                        help="download each pack over HTTPS, compute its sha256+size, "
                        "and rewrite ONLY the sha256:/size: lines in each provider "
                        "block of mappings/asset-sources.yaml (comments survive), "
                        "then rebuild the index in one step.")
    parser.add_argument("--only", nargs="+", default=None, metavar="PROVIDER",
                        help="with --update-pins: update pins for these provider "
                        "source keys only (e.g. aws azure gcp_core).")
    parser.add_argument("--manifests-dir", default=None,
                        help="directory the committed manifests (icon-index.json, "
                        "oci-stencil-digests.json, aws4-icons.json, azure2-shapes.json) "
                        "are written to (default: the directory of --out).")
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Relative --asset-root / --out are resolved against the workspace root that
    # OWNS the resolved mappings/ tree (repo checkout, bundled payload, or CWD),
    # not a bare ``parents[2]`` that is wrong on a pip/Power install (v1.5.1).
    asset_root = Path(args.asset_root)
    if not asset_root.is_absolute():
        asset_root = _WORKSPACE_ROOT / asset_root
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = _WORKSPACE_ROOT / out_path

    # --manifests-dir redirects where the committed manifests are written; it
    # defaults to the directory of --out so the icon index, the OCI digests and
    # the azure2/aws4 manifests always land together (R6.5 / init R7.6).
    if args.manifests_dir is not None:
        manifests_dir = Path(args.manifests_dir)
        if not manifests_dir.is_absolute():
            manifests_dir = _WORKSPACE_ROOT / manifests_dir
    else:
        manifests_dir = out_path.parent
    # The OCI digest manifest lives beside the icon index (and thus beside
    # aws4-icons.json), so a target-workspace --out keeps them together.
    oci_digests_path = manifests_dir / "oci-stencil-digests.json"

    # 0) --update-pins: download each pack, compute sha256+size, rewrite the pins
    #    in asset-sources.yaml (comments preserved), then continue to fetch+index
    #    in the same run (R6.5 / D7).
    if args.update_pins:
        if args.check:
            print(
                "rule-engine-build-icon-sets: --update-pins rewrites pins and cannot "
                "be combined with --check.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        rc, _changes = _update_pins(only=args.only)
        if rc != EXIT_OK:
            return rc
        # Pins are now populated; fall through to a normal fetch + index build so
        # the whole update happens "in one step" (R6.5). --no-fetch is honoured.

    # 1) Fetch the official packs (unless indexing pre-fetched ones or --check).
    if not args.no_fetch and not args.check:
        fetch_assets = _load_fetch_assets()
        if fetch_assets is None:
            print("rule-engine-build-icon-sets: scripts/fetch_assets.py not found; "
                  "use --no-fetch to index already-fetched packs.", file=sys.stderr)
            return EXIT_USAGE
        print("Fetching official icon packs (per mappings/asset-sources.yaml)...")
        rc = fetch_assets.main(["--root", str(asset_root)])
        if rc != 0:
            print("rule-engine-build-icon-sets: asset fetch failed; aborting.", file=sys.stderr)
            return EXIT_FAIL

    # 2) Index the packs into the icon-index payload.
    pack_roots = _pack_roots(asset_root)

    def _absent(root: str) -> bool:
        # An EMPTY pack directory counts as missing too (v1.6.1): a failed unpack
        # of an earlier release left one behind, and indexing it would report a
        # stale index instead of a missing pack.
        path = Path(root)
        if not path.exists():
            return True
        return path.is_dir() and not any(path.iterdir())

    missing = [k for k, r in pack_roots.items() if _absent(r)]
    if missing:
        if args.check and args.allow_missing:
            # v1.6.1: CI runs --check as a BLOCKING gate. A pack that failed to
            # download is a network problem, not a stale index, so it is reported
            # and skipped here — while a genuinely stale index still exits 1.
            print(
                "rule-engine-build-icon-sets: WARNING: icon-index check SKIPPED — "
                f"missing unpacked pack(s): {', '.join(missing)} (--allow-missing).",
                file=sys.stderr,
            )
            return EXIT_OK
        print(
            "rule-engine-build-icon-sets: missing unpacked pack(s): "
            f"{', '.join(missing)}. Run without --no-fetch, or fetch first with "
            "`python scripts/fetch_assets.py`.",
            file=sys.stderr,
        )
        return EXIT_FAIL

    try:
        payload = build_icon_index(
            pack_roots, full_packs=args.full, pack_pins=_load_pack_pins()
        )
    except Exception as exc:  # noqa: BLE001 - surface any build error
        print(f"rule-engine-build-icon-sets: index build failed: {exc}", file=sys.stderr)
        return EXIT_FAIL

    text = icon_index_to_json(payload) + "\n"

    unresolved = [
        f"{role}/{prov}"
        for role, per in payload["roles"].items()
        for prov, r in per.items()
        if r.get("source") == "unresolved"
    ]
    if unresolved:
        print(f"  note: {len(unresolved)} unresolved role(s): {', '.join(unresolved)}")

    packs = {p: s["count"] for p, s in payload["pack_summary"].items()}

    # OCI stencil digest manifest ({slug: sha256}, hashes only). Derived from the
    # decoded stencils.json in the OCI pack; ``None`` when the pack is absent
    # (fail-honest — the manifest is then left untouched / not checked).
    oci_stencils_json = asset_root / _PACK_ROOTS["oci"]
    oci_digests = build_oci_digests(oci_stencils_json)
    oci_digests_text = (
        oci_digests_to_json(oci_digests) if oci_digests is not None else None
    )

    if args.check:
        current = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
        if current != text:
            print(
                "rule-engine-build-icon-sets: committed icon-index.json is STALE — "
                "re-run `rule-engine-build-icon-sets` and commit the result.",
                file=sys.stderr,
            )
            return EXIT_FAIL
        if oci_digests_text is not None:
            current_oci = (
                oci_digests_path.read_text(encoding="utf-8")
                if oci_digests_path.is_file()
                else ""
            )
            if current_oci != oci_digests_text:
                print(
                    "rule-engine-build-icon-sets: committed oci-stencil-digests.json "
                    "is STALE — re-run `rule-engine-build-icon-sets` and commit the "
                    "result.",
                    file=sys.stderr,
                )
                return EXIT_FAIL
        print(f"OK: icon-index.json is current ({len(payload['roles'])} roles; packs {packs}).")
        return EXIT_OK

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"Wrote {_shown(out_path)} — {len(payload['roles'])} roles; packs {packs}.")

    if oci_digests_text is not None:
        oci_digests_path.parent.mkdir(parents=True, exist_ok=True)
        oci_digests_path.write_text(oci_digests_text, encoding="utf-8")
        print(f"Wrote {_shown(oci_digests_path)} — {len(oci_digests)} OCI stencil digests.")

    # Refresh the Azure azure2 shape manifest when a local draw.io app.asar is
    # available (the azure2 shapes ship inside draw.io, not in a fetched pack).
    # This keeps mappings/azure2-shapes.json — the allow-list the icon verifier
    # checks img/lib/azure2 paths against — current with the installed draw.io.
    try:
        from rule_engine import azure2_shapes as _az2
        asar = _az2.find_asar()
        if asar is not None:
            # Honour --manifests-dir so the azure2/aws4 manifests land next to
            # the icon index rather than in the engine's own mappings/ tree
            # (R6.5 / init R7.6: writes stay in the target).
            azure2_out = manifests_dir / _az2.DEFAULT_MANIFEST.name
            aws4_out = manifests_dir / _az2.AWS4_MANIFEST.name
            paths = _az2.extract_azure2_paths(asar)
            _az2.write_manifest(paths, out=azure2_out)
            print(f"Refreshed {_shown(azure2_out)} — {len(paths)} azure2 shapes.")
            # build_aws4_manifest resolves the curated mappings/ tree itself via
            # the shared bundled-payload helper (v1.5.1); no repo root passed.
            aws4 = _az2.build_aws4_manifest(asar)
            _az2.write_aws4_manifest(aws4, out=aws4_out)
            print(f"Refreshed {_shown(aws4_out)} — {len(aws4)} aws4 ids.")
        else:
            print("  note: draw.io app.asar not found; kept existing azure2/aws4 manifests.")
    except Exception as exc:  # noqa: BLE001 - non-fatal; manifest is optional
        print(f"  note: azure2 manifest refresh skipped ({exc}).")

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
