"""Icon-reference verifier for the Diagram & Inventory Rule Engine (v1.3.0).

A guessed ``resIcon`` / ``grIcon`` id renders as an empty box in draw.io, and the
linter's ``icon-resolved`` rule only catches an *empty* or literal-placeholder
style — not a *well-formed but non-existent* stencil id (e.g.
``resIcon=mxgraph.aws4.lamdba``, a typo). This helper closes that gap: it
resolves every icon reference in a ``.drawio`` source against the provider's
authoritative icon source, so authors never hand-extract the stencil library to
confirm a name.

Resolution sources per provider (see ``.kiro/steering/asset-packs.md`` and the
verified naming conventions):

- **AWS** — built-in ``mxgraph.aws4.*`` stencils. Service nodes use
  ``shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.<service>``; group
  containers use ``shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_<kind>``.
  The set of valid ids is read from ``mappings/aws-icons.yaml`` (the repository's
  curated, verified allow-list) — never guessed.
- **Azure** — ``img/lib/azure2/<category>/<Name>.svg`` file-path image shapes.
- **GCP** — official 2025 category/core icons referenced by file path under the
  fetched asset root (``assets/vendor/gcp-*``).
- **OCI** — embedded stencils keyed by slug in
  ``assets/vendor/oci-stencils/stencils.json``.

The verifier is **fail-honest**: when the authoritative source for a provider is
not present in the workspace (e.g. assets not fetched), it reports the reference
as ``skipped`` rather than ``unresolved``, so it never blocks on a missing
optional asset — mirroring the asset-paths guard's exit policy.

Public interface::

    verify_drawio(path) -> {
        "path": str,
        "references": [ {"cell_id", "kind", "reference", "status", "detail"} ],
        "unresolved": int,   # references that are well-formed but not found
        "resolved": int,
        "skipped": int,      # source unavailable, not checkable
    }

    main(argv) -> int   # CLI: rule-engine-verify-icon
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Reuse the shared classifier so container vs. service detection cannot drift
# from the linter's own node counting.
from rule_engine.constants import is_boundary_container_style as _is_boundary_style
from rule_engine.azure2_shapes import load_manifest as _load_azure2_manifest

# --- reference extraction ---------------------------------------------------

_CELL_RE = re.compile(r"<mxCell\b[^>]*?(?:/>|>.*?</mxCell>)", re.S)


def _attr(cell: str, name: str) -> Optional[str]:
    m = re.search(rf'\b{name}="([^"]*)"', cell)
    return m.group(1) if m else None


def _style_token(style: str, name: str) -> Optional[str]:
    m = re.search(rf"\b{name}=([^;\"]+)", style)
    return m.group(1).strip() if m else None


# Status constants.
RESOLVED = "resolved"
UNRESOLVED = "unresolved"
SKIPPED = "skipped"


def _aws_allowed_ids(workspace_root: Path) -> Optional[set]:
    """Return the set of allowed ``mxgraph.aws4.*`` ids.

    Prefers the committed ``mappings/aws4-icons.json`` manifest — the full aws4
    stencil-id allow-list (asar-extracted ∪ curated), which covers every service
    ``resIcon`` and group ``grIcon``, not just the nine neutral types in
    ``aws-icons.yaml``. Falls back to harvesting ``aws-icons.yaml`` when the
    manifest is absent, and to ``None`` (skip) when neither is present so AWS
    references are never wrongly flagged.
    """
    from rule_engine.azure2_shapes import load_aws4_manifest
    manifest = load_aws4_manifest(workspace_root / "mappings" / "aws4-icons.json")
    if manifest:
        return manifest
    mapping = workspace_root / "mappings" / "aws-icons.yaml"
    if not mapping.is_file():
        return None
    text = mapping.read_text(encoding="utf-8")
    ids = set(re.findall(r"mxgraph\.aws4\.([A-Za-z0-9_]+)", text))
    return ids or None


def _resolve_aws(ref: str, allowed: Optional[set]) -> tuple[str, str]:
    """Resolve an ``mxgraph.aws4.<id>`` reference against the allow-list."""
    if allowed is None:
        return SKIPPED, "mappings/aws-icons.yaml not present"
    m = re.match(r"mxgraph\.aws4\.([A-Za-z0-9_]+)", ref)
    if not m:
        return UNRESOLVED, f"not an mxgraph.aws4.* id: {ref!r}"
    ident = m.group(1)
    if ident in allowed:
        return RESOLVED, f"mxgraph.aws4.{ident}"
    return UNRESOLVED, (
        f"mxgraph.aws4.{ident} not in aws-icons.yaml allow-list "
        f"(guessed/typo id renders as an empty box)"
    )


def _resolve_azure2(ref: str, azure2_paths: Optional[set]) -> tuple[str, str]:
    """Resolve a draw.io-internal ``img/lib/azure2/*.svg`` path against the manifest.

    The azure2 shapes ship inside the draw.io app (not on disk), so a well-formed
    but non-existent path (e.g. ``…/Azure_Cache_Redis.svg`` vs the real
    ``Cache_Redis.svg``) renders as a broken image. ``mappings/azure2-shapes.json``
    is the committed allow-list; when it is absent the reference is skipped."""
    if azure2_paths is None:
        return SKIPPED, "mappings/azure2-shapes.json not present"
    if ref in azure2_paths:
        return RESOLVED, ref
    return UNRESOLVED, (
        f"azure2 path not in azure2-shapes.json allow-list: {ref} "
        f"(renders as a broken-image placeholder)"
    )


def _resolve_filepath(ref: str, workspace_root: Path) -> tuple[str, str]:
    """Resolve a file-path image reference (GCP) under the asset root.

    ``img/lib/azure2/*`` paths are handled by :func:`_resolve_azure2` before this
    is called; other ``img/lib/*`` shapes (non-azure2 draw.io internals) are not
    manifested and are skipped."""
    if ref.startswith("img/lib/"):
        return SKIPPED, "draw.io-internal img/lib shape (not manifested)"
    candidate = (workspace_root / ref).resolve()
    root = (workspace_root / "assets").resolve()
    if not root.exists():
        return SKIPPED, "assets/ root not fetched"
    if candidate.is_file():
        return RESOLVED, ref
    return UNRESOLVED, f"image path not found under asset root: {ref}"


def _oci_slugs(workspace_root: Path) -> Optional[set]:
    stencils = workspace_root / "assets" / "vendor" / "oci-stencils" / "stencils.json"
    if not stencils.is_file():
        return None
    try:
        data = json.loads(stencils.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        return set(data.keys()) or None
    return None


def verify_drawio(path: str, workspace_root: Optional[str] = None) -> Dict[str, object]:
    """Verify every icon reference in a ``.drawio`` file resolves.

    Returns a report dict (see module docstring). A reference is ``resolved``
    when its id/path exists in the authoritative source, ``unresolved`` when the
    source is available and the id/path is absent (a guessed name), and
    ``skipped`` when the source is not present to check against.
    """
    p = Path(path)
    root = Path(workspace_root) if workspace_root else _find_workspace_root(p)
    text = p.read_text(encoding="utf-8")

    aws_allowed = _aws_allowed_ids(root)
    oci_slugs = _oci_slugs(root)
    azure2_paths = _load_azure2_manifest(root / "mappings" / "azure2-shapes.json")

    references: List[Dict[str, str]] = []
    for cell in _CELL_RE.findall(text):
        if 'vertex="1"' not in cell:
            continue
        cid = _attr(cell, "id") or ""
        style = _attr(cell, "style") or ""

        res_icon = _style_token(style, "resIcon")
        gr_icon = _style_token(style, "grIcon")
        image = _style_token(style, "image")

        if res_icon:
            status, detail = _resolve_aws(res_icon, aws_allowed)
            references.append({"cell_id": cid, "kind": "resIcon", "reference": res_icon, "status": status, "detail": detail})
        if gr_icon:
            status, detail = _resolve_aws(gr_icon, aws_allowed)
            references.append({"cell_id": cid, "kind": "grIcon", "reference": gr_icon, "status": status, "detail": detail})
        if image and not image.startswith("data:"):
            if image.startswith("img/lib/azure2/"):
                status, detail = _resolve_azure2(image, azure2_paths)
                references.append({"cell_id": cid, "kind": "azure2", "reference": image, "status": status, "detail": detail})
            elif oci_slugs is not None and image in oci_slugs:
                references.append({"cell_id": cid, "kind": "oci-slug", "reference": image, "status": RESOLVED, "detail": f"OCI stencil slug {image}"})
            else:
                status, detail = _resolve_filepath(image, root)
                references.append({"cell_id": cid, "kind": "image", "reference": image, "status": status, "detail": detail})

    resolved = sum(1 for r in references if r["status"] == RESOLVED)
    unresolved = sum(1 for r in references if r["status"] == UNRESOLVED)
    skipped = sum(1 for r in references if r["status"] == SKIPPED)
    return {
        "path": str(p),
        "references": references,
        "resolved": resolved,
        "unresolved": unresolved,
        "skipped": skipped,
    }


def _find_workspace_root(p: Path) -> Path:
    """Walk upward from a file to the workspace root (dir holding mappings/)."""
    here = p.resolve()
    for parent in [here] + list(here.parents):
        if (parent / "mappings").is_dir() or (parent / ".kiro").is_dir():
            return parent
    return here.parent


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: ``rule-engine-verify-icon``.

    Usage::

        rule-engine-verify-icon --file path/to/NN-topic.drawio
        rule-engine-verify-icon --file NN.drawio --json

    Exit codes:
      0 — every icon reference resolved (or was skipped for a missing source).
      1 — at least one well-formed reference is unresolved (a guessed id/path).
      3 — usage / I/O error.
    """
    ap = argparse.ArgumentParser(prog="rule-engine-verify-icon")
    ap.add_argument("--file", required=True, help="path to a .drawio source")
    ap.add_argument("--workspace-root", default=None)
    ap.add_argument("--json", action="store_true", help="emit the full JSON report")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    path = Path(args.file)
    if not path.is_file():
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 3
    try:
        report = verify_drawio(str(path), args.workspace_root)
    except OSError as exc:
        print(f"error: could not read {args.file}: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report["references"]:
            mark = {"resolved": "OK ", "unresolved": "BAD", "skipped": "-- "}[r["status"]]
            print(f"[{mark}] {r['kind']:>9} {r['reference']}  ({r['detail']})")
        print(
            f"\n{report['resolved']} resolved, {report['unresolved']} unresolved, "
            f"{report['skipped']} skipped  in {report['path']}"
        )
    return 1 if report["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
