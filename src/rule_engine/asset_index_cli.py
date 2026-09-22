"""Console entry point for the Asset Index & Icon Fallback.

``rule-engine-index-assets`` scans a directory of unpacked official provider
icon packs and either (a) writes a JSON manifest of every indexed asset, or
(b) resolves one service name to the best available icon (built-in stencil,
official SVG/PNG, or unresolved).

The asset root is a local directory the caller has populated by unpacking the
official vendor packs (see steering ``asset-packs.md`` for the download URLs and
expected layout). This tool performs no network access.

Usage::

    # Build a manifest for all providers found under ./assets-src
    rule-engine-index-assets --root ./assets-src \
        --aws aws-icons --azure azure-icons --gcp gcp-core \
        --out asset-index.json

    # Resolve a single service (prints JSON)
    rule-engine-index-assets --root ./assets-src --aws aws-icons \
        --resolve aws "AWS Security Agent"

Exit codes: 0 success; 2 usage error; 1 resolve produced an ``unresolved``
result (so scripts can detect a missing icon).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import Dict, Optional, Sequence

from .asset_index import build_index, index_to_json, resolve_asset

EXIT_OK = 0
EXIT_UNRESOLVED = 1
EXIT_USAGE = 2

_PROVIDER_FLAGS = ("aws", "azure", "gcp", "oci")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rule-engine-index-assets",
        description="Index official provider icon packs and resolve service icons.",
    )
    p.add_argument("--root", default=".", help="base directory containing the unpacked packs")
    for prov in _PROVIDER_FLAGS:
        p.add_argument(
            f"--{prov}",
            metavar="SUBDIR",
            default=None,
            help=f"{prov} pack subdirectory under --root",
        )
    p.add_argument("--out", metavar="PATH", default=None, help="write the JSON manifest here")
    p.add_argument(
        "--resolve",
        nargs=2,
        metavar=("PROVIDER", "SERVICE"),
        default=None,
        help="resolve one service name and print the result as JSON",
    )
    return p


def _pack_roots(args: argparse.Namespace) -> Dict[str, str]:
    roots: Dict[str, str] = {}
    for prov in _PROVIDER_FLAGS:
        sub = getattr(args, prov)
        if sub:
            roots[prov] = os.path.join(args.root, sub)
    return roots


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    roots = _pack_roots(args)
    if not roots:
        print(
            "rule-engine-index-assets: error: provide at least one of "
            "--aws/--azure/--gcp/--oci",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        index = build_index(roots)
    except (FileNotFoundError, ValueError) as exc:
        print(f"rule-engine-index-assets: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.resolve:
        provider, service = args.resolve
        try:
            result = resolve_asset(provider, service, index.get(provider))
        except ValueError as exc:
            print(f"rule-engine-index-assets: error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
        return EXIT_UNRESOLVED if result.source == "unresolved" else EXIT_OK

    manifest = index_to_json(index)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(manifest + "\n")
        total = sum(len(v) for v in index.values())
        print(
            f"rule-engine-index-assets: indexed {total} assets across "
            f"{len(index)} provider(s) -> {args.out}"
        )
    else:
        print(manifest)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
