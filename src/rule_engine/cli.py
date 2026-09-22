"""Command-line entry point for the Diagram & Inventory Rule Engine Linter.

This module provides the ``rule-engine-lint`` console script (registered in
``pyproject.toml``) used by the ``lint-on-save`` and ``validate-on-task`` Kiro
hooks and by the CI pipeline. It wraps :mod:`rule_engine.linter`, adding
ruleset-availability enforcement (Requirement 7 AC14) and best-effort parsing of
``.drawio`` and ``.md`` files into :class:`~rule_engine.linter.Artifact`
instances.

Usage::

    rule-engine-lint --file path/to/01-topic.drawio
    rule-engine-lint --all
    rule-engine-lint --all --fail-on error,critical

Options
-------
--file PATH
    Lint a single artifact file. ``.drawio`` files are parsed as diagrams;
    ``.md`` / ``.markdown`` files are parsed as documents (frontmatter checked).
--all
    Lint every ``.drawio`` and Markdown document found under the workspace root.
--fail-on LEVELS
    Comma-separated severities that cause a non-zero exit when present in the
    findings (default ``error,critical``). WARNING-only findings never fail the
    run unless explicitly requested.
--workspace-root PATH
    Override the workspace root used to locate the ruleset and to scan for
    artifacts (defaults to the current working directory).

Exit codes
----------
0   All linted artifacts pass the configured ``--fail-on`` gate.
1   At least one artifact produced a finding at/above a ``--fail-on`` severity,
    or the artifact is otherwise blocked from publication.
2   The authoritative ruleset ``diagram-lint.md`` is missing or unreadable, so
    every artifact is blocked (fail-closed, Requirement 7 AC14).
3   A usage or I/O error (no target given, file not found, etc.).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import linter as _linter
from .linter import (
    Artifact,
    Edge,
    RULESET_UNAVAILABLE_ERROR,
    Severity,
    find_ruleset,
    lint,
)

# Exit codes.
EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_RULESET_UNAVAILABLE = 2
EXIT_USAGE = 3

_DEFAULT_FAIL_ON = (Severity.ERROR, Severity.CRITICAL)

# ---------------------------------------------------------------------------
# Best-effort file parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)

# draw.io mxCell node cells carry vertex="1"; edges carry edge="1".
_MXCELL_RE = re.compile(r"<mxCell\b[^>]*>", re.IGNORECASE | re.DOTALL)
_VALUE_ATTR_RE = re.compile(r'value="([^"]*)"', re.IGNORECASE)
_VERTEX_RE = re.compile(r'vertex="1"', re.IGNORECASE)
_EDGE_RE = re.compile(r'edge="1"', re.IGNORECASE)
_STYLE_ATTR_RE = re.compile(r'style="([^"]*)"', re.IGNORECASE)


def _parse_frontmatter(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse of a Markdown YAML frontmatter block.

    Uses PyYAML when available; otherwise falls back to a minimal key/value and
    list scan. Returns ``None`` when the document has no frontmatter block.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    block = match.group(1)
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(block)
        if isinstance(loaded, dict):
            return loaded
        return {}
    except Exception:
        return _parse_frontmatter_fallback(block)


def _parse_frontmatter_fallback(block: str) -> Dict[str, Any]:
    """Minimal YAML-subset parser for ``key: value`` and simple lists."""
    result: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_list_key is not None:
            item = stripped[2:].strip().strip("'\"")
            result.setdefault(current_list_key, [])
            if isinstance(result[current_list_key], list):
                result[current_list_key].append(item)
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Strip inline comments.
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            if value == "" :
                # Could be the header of a block list; mark as pending list.
                current_list_key = key
                result[key] = []
            elif value in ("[]", "{}"):
                result[key] = []
                current_list_key = None
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                result[key] = (
                    [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
                    if inner
                    else []
                )
                current_list_key = None
            else:
                result[key] = value.strip("'\"")
                current_list_key = None
    return result


def _parse_drawio(path: str, text: str) -> Artifact:
    """Best-effort parse of a ``.drawio`` XML source into a diagram Artifact."""
    node_names: List[str] = []
    edges: List[Edge] = []
    icons: List[Any] = []

    # Locate a title cell heuristically: a value containing a ` vN ` token
    # (the title-cell version identifier). Recorded so it is excluded from the
    # node set below.
    title_cell: Optional[str] = None
    for cell in _MXCELL_RE.findall(text):
        value_match = _VALUE_ATTR_RE.search(cell)
        if value_match and re.search(r"\bv[1-9][0-9]*\b", value_match.group(1)):
            title_cell = value_match.group(1)
            break

    for cell in _MXCELL_RE.findall(text):
        value_match = _VALUE_ATTR_RE.search(cell)
        value = value_match.group(1) if value_match else ""
        style_match = _STYLE_ATTR_RE.search(cell)
        style = style_match.group(1) if style_match else ""
        style_low = style.lower()
        if _EDGE_RE.search(cell):
            edges.append(Edge(label=value or None))
        elif _VERTEX_RE.search(cell):
            # Text-only cells (titles, legends, free labels) are not diagram
            # nodes: skip cells that carry a text/label style or match the
            # title cell / a legend block.
            is_text_cell = (
                "text" in style_low
                or style_low.startswith("text;")
                or value == title_cell
                or value.lower().startswith("legend")
            )
            if is_text_cell:
                continue
            # A real node: record its (possibly special-char) name and icon.
            if value or style:
                node_names.append(value)
            if style:
                icons.append({"style": style, "resolved": True})

    has_legend = "legend" in text.lower()

    companion = os.path.splitext(path)[0] + ".diagram.md"
    # `NN-topic.drawio` -> `NN-topic.diagram.md`
    if path.endswith(".drawio"):
        companion = path[: -len(".drawio")] + ".diagram.md"

    return Artifact(
        kind="diagram",
        path=path,
        node_names=node_names,
        edges=edges,
        icons=icons,
        has_legend=has_legend,
        title_cell=title_cell,
        source_format="drawio",
        is_drawio=True,
        has_companion_doc=os.path.isfile(companion),
    )


def _parse_markdown(path: str, text: str) -> Artifact:
    """Best-effort parse of a Markdown document into a document Artifact."""
    frontmatter = _parse_frontmatter(text)
    return Artifact(
        kind="document",
        path=path,
        is_markdown=True,
        frontmatter=frontmatter,
    )


def parse_artifact(path: str) -> Artifact:
    """Parse a file at ``path`` into an :class:`Artifact` (best-effort).

    Raises
    ------
    FileNotFoundError
        When ``path`` does not exist.
    ValueError
        When the file extension is not a supported artifact type.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    lower = path.lower()
    if lower.endswith(".drawio"):
        return _parse_drawio(path, text)
    if lower.endswith((".md", ".markdown")):
        return _parse_markdown(path, text)
    raise ValueError(f"unsupported artifact type for linting: {path}")


# Directories excluded from the `--all` scan.
_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "assets",
    ".build-tools",  # downloaded tooling + unpacked vendor asset packs (uncommitted)
    "release-dist",  # locally built release bundles (uncommitted)
    ".kiro",  # steering/specs are rule sources, not linted artifacts
}

# Hand-authored repository documents that are not engine-generated KB documents;
# the frontmatter contract (kb-frontmatter) applies to generated documents, so
# these are excluded from the Markdown scan to avoid false positives.
_EXCLUDED_MD_BASENAMES = {
    "readme.md",
    "install.md",
    "changelog.md",
    "contributing.md",
    "license.md",
    "notice.md",
    "code_of_conduct.md",
    "security.md",
}


def _is_generated_markdown(path: str) -> bool:
    """Return True when a Markdown file is an engine-generated KB document.

    Companion documents (``*.diagram.md``) and versioned inventory / KB
    documents are linted; top-level hand-authored repo docs (README, INSTALL,
    CHANGELOG, ...) are not.
    """
    base = os.path.basename(path).lower()
    if base.endswith(".diagram.md"):
        return True
    return base not in _EXCLUDED_MD_BASENAMES


def discover_artifacts(workspace_root: str) -> List[str]:
    """Return the sorted list of lintable ``.drawio``/Markdown files under root."""
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        for name in filenames:
            low = name.lower()
            full = os.path.join(dirpath, name)
            if low.endswith(".drawio"):
                found.append(full)
            elif low.endswith((".md", ".markdown")) and _is_generated_markdown(full):
                found.append(full)
    return sorted(found)


# ---------------------------------------------------------------------------
# fail-on parsing and evaluation
# ---------------------------------------------------------------------------


def _parse_fail_on(raw: str) -> Tuple[Severity, ...]:
    """Parse a comma-separated severity list into a tuple of :class:`Severity`."""
    levels: List[Severity] = []
    for token in raw.split(","):
        token = token.strip().upper()
        if not token:
            continue
        try:
            levels.append(Severity(token))
        except ValueError as exc:
            raise ValueError(
                f"invalid --fail-on severity '{token}'; expected any of "
                "CRITICAL, ERROR, WARNING"
            ) from exc
    return tuple(levels) if levels else _DEFAULT_FAIL_ON


def _result_fails(result: Dict[str, Any], fail_on: Sequence[Severity]) -> bool:
    """Return True when a lint result should fail the gate for ``fail_on``."""
    if result.get("error"):
        return True
    if not result.get("eligible_for_publication", False):
        return True
    fail_values = {s.value for s in fail_on}
    return any(f.get("severity") in fail_values for f in result.get("findings", []))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rule-engine-lint",
        description=(
            "Lint diagrams and Markdown documents against the authoritative "
            "diagram-lint.md ruleset."
        ),
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--file", metavar="PATH", help="lint a single artifact file")
    target.add_argument(
        "--all",
        action="store_true",
        help="lint every diagram and Markdown document under the workspace root",
    )
    parser.add_argument(
        "--fail-on",
        default="error,critical",
        metavar="LEVELS",
        help="comma-separated severities that cause a non-zero exit "
        "(default: error,critical)",
    )
    parser.add_argument(
        "--workspace-root",
        default=None,
        metavar="PATH",
        help="workspace root used to locate the ruleset and scan artifacts "
        "(default: current directory)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Console entry point for ``rule-engine-lint``.

    Returns a process exit code (see module docstring).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        fail_on = _parse_fail_on(args.fail_on)
    except ValueError as exc:
        print(f"rule-engine-lint: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    workspace_root = args.workspace_root or os.getcwd()

    # Requirement 7 AC14: ruleset must be available before any artifact is
    # eligible; otherwise block everything, fail-closed.
    resolved_ruleset = find_ruleset(workspace_root=workspace_root)
    if not _linter.ruleset_available(workspace_root=workspace_root):
        where = resolved_ruleset or os.path.join(
            workspace_root, _linter.RULESET_RELATIVE_PATH
        )
        print(
            f"rule-engine-lint: {RULESET_UNAVAILABLE_ERROR}: authoritative lint "
            f"ruleset diagram-lint.md is missing or unreadable ({where}). "
            "Every artifact is blocked from publication.",
            file=sys.stderr,
        )
        return EXIT_RULESET_UNAVAILABLE

    # Gather targets.
    if args.file:
        targets = [args.file]
    else:
        targets = discover_artifacts(workspace_root)
        if not targets:
            print(
                "rule-engine-lint: no .drawio or Markdown artifacts found under "
                f"{workspace_root}",
            )
            return EXIT_OK

    any_failed = False
    for target in targets:
        try:
            artifact = parse_artifact(target)
        except FileNotFoundError:
            print(f"rule-engine-lint: error: file not found: {target}", file=sys.stderr)
            return EXIT_USAGE
        except ValueError as exc:
            # For --all this cannot happen (extensions are filtered); for --file
            # an unsupported extension is a usage error.
            print(f"rule-engine-lint: error: {exc}", file=sys.stderr)
            return EXIT_USAGE

        result = lint(artifact)
        failed = _result_fails(result, fail_on)
        any_failed = any_failed or failed

        status = "BLOCKED" if failed else "OK"
        findings = result.get("findings", [])
        summary = ", ".join(
            f"{f['rule']}({f['severity']})" for f in findings
        ) or "no findings"
        print(f"[{status}] {target}: {summary}")
        for finding in findings:
            if finding["severity"] in {s.value for s in fail_on}:
                print(
                    f"    - {finding['severity']}: {finding['rule']}",
                    file=sys.stderr,
                )

    return EXIT_BLOCKED if any_failed else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
