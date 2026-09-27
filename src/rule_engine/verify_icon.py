"""Icon-reference verifier for the Diagram & Inventory Rule Engine.

A guessed ``resIcon`` / ``grIcon`` id renders as an empty box in draw.io, and the
linter's ``icon-resolved`` rule only catches an *empty* or literal-placeholder
style — not a *well-formed but non-existent* stencil id (e.g.
``resIcon=mxgraph.aws4.lamdba``, a typo). This helper closes that gap: it
resolves every icon reference in a ``.drawio`` source against the provider's
authoritative icon source, so authors never hand-extract the stencil library to
confirm a name.

Since 1.7.0 (honest-gates) this module carries **no** ``.drawio`` regexes of its
own. It parses with :func:`rule_engine.drawio_model.parse_drawio` and extracts /
resolves references with :mod:`rule_engine.icon_refs`, so the verifier and the
linter's ``icon-resolved`` rule share one vocabulary and cannot drift (R4.1,
R4.5). Two behaviours follow directly from that shared module:

- **No blind spot on OCI.** OCI nodes embed their glyph as
  ``shape=stencil(...)`` and carry an ``ociSlug=`` marker; both are verifiable
  refs, so an OCI node is checked rather than reported ``skipped`` for every
  provider that is not AWS/Azure (the pre-1.7 gap).
- **Unverified is honest (R4.2).** A service vertex (a node that is neither a
  Boundary container nor a text cell) that carries *no* verifiable reference is
  reported ``unverified`` with its cell id — the gate never silently reports
  "0 unresolved" as success when in fact nothing was checked.

Public interface::

    verify_drawio(path, workspace_root=None) -> {
        "path": str,
        "references": [ {"cell_id", "kind", "reference", "status", "detail"} ],
        "resolved": int,
        "unresolved": int,   # well-formed but not found -> exit 1 always
        "skipped": int,      # source unavailable, not checkable
        "unverified": int,   # a service vertex with no verifiable ref (R4.2)
        "service_vertices": int,
    }

    main(argv) -> int   # CLI: rule-engine-verify-icon

Exit codes (design §6, R4.3)::

    0 — nothing to flag (or only skips / unverified without --strict).
    1 — any ``unresolved`` ref;
        under --strict: any ``unverified`` ref, or a file that has service
        vertices and zero ``resolved`` refs (a ``skipped`` ref counts as
        not-verified).
    3 — an I/O error or a DrawioParseError.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from rule_engine.drawio_model import DrawioParseError, Page, parse_drawio
from rule_engine.icon_refs import (
    RESOLVED,
    SKIPPED,
    UNRESOLVED,
    UNVERIFIED,
    IconSources,
    extract_refs,
    load_sources,
    resolve,
    service_vertices,
)

__all__ = [
    "RESOLVED",
    "UNRESOLVED",
    "SKIPPED",
    "UNVERIFIED",
    "verify_drawio",
    "main",
]


def _find_workspace_root(p: Path) -> Path:
    """Walk upward from a file to the workspace root (dir holding mappings/)."""
    here = p.resolve()
    for parent in [here] + list(here.parents):
        if (parent / "mappings").is_dir() or (parent / ".kiro").is_dir():
            return parent
    return here.parent


def _verify_page(page: Page, sources: IconSources) -> tuple[List[Dict[str, str]], int]:
    """Verify one parsed :class:`Page`.

    Returns ``(references, service_vertex_count)``. Every service vertex is
    accounted for: a vertex whose refs all resolve/skip contributes those
    reference rows; a vertex with no *verifiable* reference contributes one
    ``unverified`` row carrying its cell id (R4.2).
    """
    references: List[Dict[str, str]] = []
    refs_by_cell = extract_refs(page)
    vertices = service_vertices(page)

    for cell in vertices:
        cell_refs = refs_by_cell.get(cell.id, [])
        verifiable_rows: List[Dict[str, str]] = []
        for ref in cell_refs:
            status, detail = resolve(ref, sources)
            row = {
                "cell_id": cell.id,
                "kind": ref.kind,
                "reference": ref.reference,
                "status": status,
                "detail": detail,
            }
            if status == UNVERIFIED:
                # A ref kind with no verification source at all does not make
                # the vertex "verifiable"; fold it into the vertex-level
                # unverified report below rather than emitting a ref row.
                continue
            verifiable_rows.append(row)

        if verifiable_rows:
            references.extend(verifiable_rows)
        else:
            # No verifiable reference on this service vertex -> unverified (R4.2).
            references.append(
                {
                    "cell_id": cell.id,
                    "kind": "vertex",
                    "reference": cell.label or cell.id,
                    "status": UNVERIFIED,
                    "detail": "service vertex has no verifiable icon reference",
                }
            )
    return references, len(vertices)


def verify_drawio(
    path: str, workspace_root: Optional[str] = None
) -> Dict[str, object]:
    """Verify every icon reference in a ``.drawio`` file resolves.

    Parses the file with :func:`rule_engine.drawio_model.parse_drawio` (every
    page) and resolves each extracted reference with :mod:`rule_engine.icon_refs`.
    A reference is ``resolved`` when its id/path exists in the authoritative
    source, ``unresolved`` when the source is available and the id/path is absent
    (a guessed name), ``skipped`` when the source is not present to check
    against, and a service vertex with no verifiable reference is reported
    ``unverified`` (R4.2).

    Raises :class:`~rule_engine.drawio_model.DrawioParseError` when the file
    cannot be parsed, so the caller maps it to exit 3 (fail-honest — a file the
    verifier cannot read is never "OK").
    """
    p = Path(path)
    root = Path(workspace_root) if workspace_root else _find_workspace_root(p)
    data = p.read_bytes()

    pages = parse_drawio(data, path=str(p))
    sources = load_sources(root)

    references: List[Dict[str, str]] = []
    service_vertex_count = 0
    for page in pages:
        page_refs, page_vertices = _verify_page(page, sources)
        references.extend(page_refs)
        service_vertex_count += page_vertices

    resolved = sum(1 for r in references if r["status"] == RESOLVED)
    unresolved = sum(1 for r in references if r["status"] == UNRESOLVED)
    skipped = sum(1 for r in references if r["status"] == SKIPPED)
    unverified = sum(1 for r in references if r["status"] == UNVERIFIED)
    return {
        "path": str(p),
        "references": references,
        "resolved": resolved,
        "unresolved": unresolved,
        "skipped": skipped,
        "unverified": unverified,
        "service_vertices": service_vertex_count,
    }


def _exit_code_for(report: Dict[str, object], *, strict: bool) -> int:
    """Compute the exit code for one report (R4.3 exit-code contract).

    | Condition                                   | default | --strict |
    | ------------------------------------------- | ------- | -------- |
    | any ``unresolved`` ref                      | 1       | 1        |
    | any ``unverified`` ref                      | 0       | 1        |
    | service vertices present, 0 ``resolved``    | 0       | 1        |

    A ``skipped`` ref counts as not-verified for the third row, so a diagram
    checked without its assets fails under ``--strict`` instead of passing on
    zero checks.
    """
    if report["unresolved"]:
        return 1
    if strict:
        if report["unverified"]:
            return 1
        if report["service_vertices"] and not report["resolved"]:
            return 1
    return 0


def _mark(status: str) -> str:
    return {
        RESOLVED: "OK ",
        UNRESOLVED: "BAD",
        SKIPPED: "-- ",
        UNVERIFIED: "??",
    }.get(status, "?? ")


def _discover_examples(workspace_root: Path) -> List[str]:
    """Return the ``.drawio`` sources under ``examples/`` using the Lint_CLI filters.

    Reuses ``cli.discover_artifacts`` (which prunes scratch copies, ``-reference``
    baselines and excluded directories) and keeps only the ``.drawio`` files that
    live under an ``examples/`` directory, so the verifier's ``--all`` walk sees
    exactly the diagrams CI lints.
    """
    from rule_engine.cli import discover_artifacts

    examples_root = workspace_root / "examples"
    if not examples_root.is_dir():
        return []
    found: List[str] = []
    for full in discover_artifacts(str(examples_root)):
        if full.lower().endswith(".drawio"):
            found.append(full)
    return sorted(found)


def _print_report(report: Dict[str, object]) -> None:
    for r in report["references"]:
        mark = _mark(r["status"])
        cell = r.get("cell_id", "")
        print(f"[{mark}] {r['kind']:>12} {r['reference']}  ({cell}: {r['detail']})")
    print(
        f"\n{report['resolved']} resolved, {report['unresolved']} unresolved, "
        f"{report['skipped']} skipped, {report['unverified']} unverified "
        f"({report['service_vertices']} service vertices) in {report['path']}"
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: ``rule-engine-verify-icon``.

    Usage::

        rule-engine-verify-icon --file path/to/NN-topic.drawio
        rule-engine-verify-icon --file NN.drawio --json
        rule-engine-verify-icon --all --strict     # CI: walk examples/

    Exit codes:
      0 — nothing to flag (see the exit-code contract in the module docstring).
      1 — an unresolved ref, or (under --strict) an unverified vertex / a file
          with service vertices and zero verified refs.
      3 — usage / I/O error / DrawioParseError.
    """
    ap = argparse.ArgumentParser(prog="rule-engine-verify-icon")
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--file", help="path to a .drawio source")
    target.add_argument(
        "--all",
        action="store_true",
        help="verify every .drawio under examples/ (Lint_CLI discovery filters)",
    )
    ap.add_argument("--workspace-root", default=None)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on an unverified vertex or a file with service "
        "vertices and zero verified refs",
    )
    ap.add_argument("--json", action="store_true", help="emit the full JSON report")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    # Resolve the list of files to verify.
    if args.all:
        root = (
            Path(args.workspace_root)
            if args.workspace_root
            else Path(os.getcwd())
        )
        files = _discover_examples(root)
        if not files:
            print(
                f"rule-engine-verify-icon: no .drawio examples found under {root}",
                file=sys.stderr,
            )
            return 3
    else:
        path = Path(args.file)
        if not path.is_file():
            print(f"error: file not found: {args.file}", file=sys.stderr)
            return 3
        files = [str(path)]

    reports: List[Dict[str, object]] = []
    exit_code = 0
    for f in files:
        try:
            report = verify_drawio(f, args.workspace_root)
        except DrawioParseError as exc:
            print(f"error: could not parse {f}: {exc.cause}", file=sys.stderr)
            return 3
        except OSError as exc:
            print(f"error: could not read {f}: {exc}", file=sys.stderr)
            return 3
        reports.append(report)
        exit_code = max(exit_code, _exit_code_for(report, strict=args.strict))

    if args.json:
        print(json.dumps(reports if args.all else reports[0], indent=2))
    else:
        for report in reports:
            _print_report(report)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
