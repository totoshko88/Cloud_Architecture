"""Console entry point for Normalized Resource schema validation.

This module provides the ``rule-engine-validate-schema`` console script
(registered in ``pyproject.toml``) used by the ``validate-on-task`` Kiro hook
and by the CI pipeline. It loads a JSON Schema and validates every matched JSON
file against it, surfacing a blocking failure reason when any target fails.

Usage::

    rule-engine-validate-schema --schema schemas/inventory.schema.json \\
        --targets 'examples/**/*.json'

Options
-------
--schema PATH
    Path to the JSON Schema used to validate targets. Defaults to
    ``schemas/inventory.schema.json`` relative to the current directory.
--targets GLOB
    A glob (``**`` supported) selecting the JSON files to validate. May be
    passed more than once to validate several globs. Defaults to
    ``examples/**/*.json``.
--workspace-root PATH
    Root that relative ``--schema`` / ``--targets`` are resolved against
    (defaults to the current working directory).

Target selection semantics
---------------------------
The ``--targets`` glob typically matches a mix of files. The engine's golden
``examples/<provider>/sample-resource.json`` files are single Normalized
Resources and MUST validate. Other JSON that may live under ``examples/`` —
inventory snapshots, manifest arrays, or fixtures that are not a single
normalized resource — are not resources and must not fail this gate.

To stay robust while still enforcing the contract on real resources, each
matched JSON file is classified:

* A JSON **object** that carries the marker key ``resource_type`` (or the
  ``provider`` key) is treated as a single Normalized Resource and validated.
* A JSON **array** whose entries are all such resource-shaped objects is
  treated as a list of Normalized Resources; every entry is validated.
* Any other JSON shape (an object without the resource markers, an empty
  array, a scalar, a manifest, etc.) is treated as a non-resource document and
  skipped.

A file that fails to parse as JSON is a validation failure (it cannot be a
conforming resource). Files that are skipped never fail the gate.

Exit codes
----------
0   Every resource-shaped target validated, or no targets matched.
1   At least one target failed validation (schema violation or unparseable
    JSON). The blocking reason names each offending file and constraint.
3   A usage or I/O error (schema file missing/unreadable, bad arguments).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from jsonschema import Draft202012Validator

# Exit codes.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 3

_DEFAULT_SCHEMA = "schemas/inventory.schema.json"
_DEFAULT_TARGETS = "examples/**/*.json"

# A JSON object carrying either of these keys is treated as a single
# Normalized Resource and validated; anything else is a non-resource document
# and is skipped (see module docstring).
_RESOURCE_MARKER_KEYS = ("resource_type", "provider")


def _looks_like_resource(obj: Any) -> bool:
    """Return True when ``obj`` is a single resource-shaped JSON object."""
    return isinstance(obj, dict) and any(
        key in obj for key in _RESOURCE_MARKER_KEYS
    )


def _classify(document: Any) -> Tuple[str, List[Any]]:
    """Classify a parsed JSON document into (kind, resources).

    ``kind`` is one of ``"resource"``, ``"resource-list"``, or ``"skip"``.
    ``resources`` is the list of resource-shaped objects to validate (empty for
    ``"skip"``).
    """
    if _looks_like_resource(document):
        return "resource", [document]
    if isinstance(document, list) and document and all(
        _looks_like_resource(item) for item in document
    ):
        return "resource-list", list(document)
    return "skip", []


def _load_schema(schema_path: Path) -> dict[str, Any]:
    with schema_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _errors_for(validator: Draft202012Validator, resource: Any) -> List[str]:
    """Return sorted human-readable validation messages for ``resource``."""
    errors = sorted(validator.iter_errors(resource), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in errors
    ]


def _expand_targets(
    target_globs: Sequence[str], workspace_root: str
) -> List[str]:
    """Expand one or more globs (relative to root) into a sorted file list."""
    found: set[str] = set()
    for pattern in target_globs:
        pat = pattern
        if not os.path.isabs(pat):
            pat = os.path.join(workspace_root, pat)
        for match in glob.glob(pat, recursive=True):
            if os.path.isfile(match):
                found.add(match)
    return sorted(found)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rule-engine-validate-schema",
        description=(
            "Validate JSON targets against the Normalized Resource schema. "
            "Resource-shaped JSON files must conform; non-resource JSON is "
            "skipped."
        ),
    )
    parser.add_argument(
        "--schema",
        default=_DEFAULT_SCHEMA,
        metavar="PATH",
        help=f"path to the JSON Schema (default: {_DEFAULT_SCHEMA})",
    )
    parser.add_argument(
        "--targets",
        action="append",
        default=None,
        metavar="GLOB",
        help=(
            "glob selecting JSON files to validate (may be repeated; "
            f"default: {_DEFAULT_TARGETS})"
        ),
    )
    parser.add_argument(
        "--workspace-root",
        default=None,
        metavar="PATH",
        help="root that relative --schema/--targets resolve against "
        "(default: current directory)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Console entry point for ``rule-engine-validate-schema``.

    Returns a process exit code (see module docstring).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    workspace_root = args.workspace_root or os.getcwd()

    schema_path = Path(args.schema)
    if not schema_path.is_absolute():
        schema_path = Path(workspace_root) / schema_path

    if not schema_path.is_file():
        print(
            f"rule-engine-validate-schema: error: schema file not found: "
            f"{schema_path}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        schema = _load_schema(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"rule-engine-validate-schema: error: could not read schema "
            f"{schema_path}: {exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    validator = Draft202012Validator(schema)

    target_globs = args.targets if args.targets else [_DEFAULT_TARGETS]
    targets = _expand_targets(target_globs, workspace_root)

    if not targets:
        print(
            "rule-engine-validate-schema: no JSON targets matched "
            f"{', '.join(target_globs)}; nothing to validate."
        )
        return EXIT_OK

    failures: List[str] = []
    validated = 0
    skipped = 0

    for target in targets:
        try:
            with open(target, encoding="utf-8") as fh:
                document = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{target}: not valid JSON: {exc}")
            continue

        kind, resources = _classify(document)
        if kind == "skip":
            skipped += 1
            print(f"[SKIP] {target}: not a Normalized Resource document")
            continue

        file_failed = False
        for index, resource in enumerate(resources):
            errors = _errors_for(validator, resource)
            if errors:
                file_failed = True
                where = (
                    f"{target}[{index}]" if kind == "resource-list" else target
                )
                for err in errors:
                    failures.append(f"{where}: {err}")
        if file_failed:
            print(f"[FAIL] {target}: schema validation failed")
        else:
            validated += 1
            print(f"[OK]   {target}: valid Normalized Resource(s)")

    if failures:
        print(
            "\nrule-engine-validate-schema: BLOCKING FAILURE — "
            f"{len(failures)} schema violation(s) across the targets:",
            file=sys.stderr,
        )
        for reason in failures:
            print(f"    - {reason}", file=sys.stderr)
        return EXIT_FAILED

    print(
        f"\nrule-engine-validate-schema: OK — {validated} resource file(s) "
        f"validated, {skipped} non-resource file(s) skipped."
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
