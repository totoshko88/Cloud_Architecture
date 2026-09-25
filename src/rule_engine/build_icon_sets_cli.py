"""Init-time icon-set builder CLI (``rule-engine-build-icon-sets``).

Standardises service icons on the official provider bundles at initialisation:
fetch every pack declared in ``mappings/asset-sources.yaml``, index each pack's
filename / library structure, and write the committed ``mappings/icon-index.json``
(``pack_summary`` + per-role resolved icons). See
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

Exit codes: 0 success / index current; 1 build failed or index stale (--check);
2 usage/config error.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

from rule_engine.asset_index import build_icon_index, icon_index_to_json

# The repo root: this file is src/rule_engine/build_icon_sets_cli.py -> ... -> root.
REPO_ROOT = Path(__file__).resolve().parents[2]
ICON_INDEX_OUT = REPO_ROOT / "mappings" / "icon-index.json"

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

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def _pack_roots(asset_root: Path) -> Dict[str, str]:
    return {key: str(asset_root / rel) for key, rel in _PACK_ROOTS.items()}


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
    parser.add_argument("--asset-root", default=str(REPO_ROOT / "assets" / "vendor"),
                        help="unpacked asset root (default: assets/vendor)")
    parser.add_argument("--out", default=str(ICON_INDEX_OUT),
                        help="committed icon index path (default: mappings/icon-index.json)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the pack download/unpack; index already-fetched packs")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the committed index differs from a fresh build")
    parser.add_argument("--full", action="store_true",
                        help="embed the full per-slug pack tables (large); default writes a summary")
    args = parser.parse_args(list(argv) if argv is not None else None)

    asset_root = Path(args.asset_root)
    if not asset_root.is_absolute():
        asset_root = REPO_ROOT / asset_root
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path

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
    missing = [k for k, r in pack_roots.items() if not Path(r).exists()]
    if missing:
        print(
            "rule-engine-build-icon-sets: missing unpacked pack(s): "
            f"{', '.join(missing)}. Run without --no-fetch, or fetch first with "
            "`python scripts/fetch_assets.py`.",
            file=sys.stderr,
        )
        return EXIT_FAIL

    try:
        payload = build_icon_index(pack_roots, full_packs=args.full)
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

    if args.check:
        current = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
        if current != text:
            print(
                "rule-engine-build-icon-sets: committed icon-index.json is STALE — "
                "re-run `rule-engine-build-icon-sets` and commit the result.",
                file=sys.stderr,
            )
            return EXIT_FAIL
        print(f"OK: icon-index.json is current ({len(payload['roles'])} roles; packs {packs}).")
        return EXIT_OK

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    # out_path may live outside REPO_ROOT (e.g. rule-engine-init --with-assets
    # writing into a target workspace), so relative_to would raise — print a
    # repo-relative path when possible, else the absolute path.
    try:
        shown = out_path.relative_to(REPO_ROOT)
    except ValueError:
        shown = out_path
    print(f"Wrote {shown} — {len(payload['roles'])} roles; packs {packs}.")

    # Refresh the Azure azure2 shape manifest when a local draw.io app.asar is
    # available (the azure2 shapes ship inside draw.io, not in a fetched pack).
    # This keeps mappings/azure2-shapes.json — the allow-list the icon verifier
    # checks img/lib/azure2 paths against — current with the installed draw.io.
    try:
        from rule_engine import azure2_shapes as _az2
        asar = _az2.find_asar()
        if asar is not None:
            paths = _az2.extract_azure2_paths(asar)
            _az2.write_manifest(paths)
            print(f"Refreshed {_az2.DEFAULT_MANIFEST.relative_to(REPO_ROOT)} — {len(paths)} azure2 shapes.")
            aws4 = _az2.build_aws4_manifest(asar, REPO_ROOT)
            _az2.write_aws4_manifest(aws4)
            print(f"Refreshed {_az2.AWS4_MANIFEST.relative_to(REPO_ROOT)} — {len(aws4)} aws4 ids.")
        else:
            print("  note: draw.io app.asar not found; kept existing azure2/aws4 manifests.")
    except Exception as exc:  # noqa: BLE001 - non-fatal; manifest is optional
        print(f"  note: azure2 manifest refresh skipped ({exc}).")

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
