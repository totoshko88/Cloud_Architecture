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
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import linter as _linter
from .constants import ROOT_LAYER_ID as _ROOT_LAYER_ID
from .constants import is_boundary_container_style as _is_boundary_container_style
from .constants import is_text_cell_style as _is_text_cell_style
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
_ID_ATTR_RE = re.compile(r'\bid="([^"]*)"', re.IGNORECASE)
_PARENT_ATTR_RE = re.compile(r'\bparent="([^"]*)"', re.IGNORECASE)
_FONT_SIZE_RE = re.compile(r"fontSize=([0-9]+)", re.IGNORECASE)

# The draw.io root-layer id and the boundary/text cell classifiers come from
# rule_engine.constants (shared with geometry.build_geometry), so the C4
# container-detection rule cannot drift. _ROOT_LAYER_ID is imported above.

# Style tokens that mark an UNRESOLVED / placeholder icon (REVIEW.md C2). A node
# is resolved when it carries a concrete, non-empty style — whether that is a
# provider stencil (``shape=mxgraph.aws4.*`` / ``mxgraph.gcp2.*`` / embedded OCI
# ``shape=stencil(...)``), a shaped node (``shape=cylinder3`` etc.), or the
# generic profile's intentionally shapeless fill/stroke box. It is UNRESOLVED
# only when the style is empty, explicitly names no shape (``shape=none``), or
# contains a literal placeholder/unresolved marker. This lets ``icon-resolved``
# fire on a parsed ``.drawio`` file, not only on programmatic Artifacts.
_UNRESOLVED_STYLE_MARKERS = (
    "shape=none",
    "placeholder",
    "unresolved",
    "image=data:image/svg",  # a data-URI SVG image node draw.io fails to render
)


def _icon_descriptor_for_style(style: str) -> Dict[str, Any]:
    """Classify a node's draw.io ``style`` into a linter icon descriptor.

    Returns ``{"style": style, "resolved": bool}`` (with ``placeholder`` set when
    unresolved). A style is unresolved when it is empty or matches one of
    :data:`_UNRESOLVED_STYLE_MARKERS`; any other concrete style — a provider
    stencil, a shaped node, an embedded stencil group, or the generic profile's
    grayscale fill/stroke box — is a resolved icon.
    """
    low = (style or "").strip().lower()
    if low == "":
        return {"style": style, "resolved": False, "placeholder": True}
    if any(marker in low for marker in _UNRESOLVED_STYLE_MARKERS):
        return {"style": style, "resolved": False, "placeholder": True}
    return {"style": style, "resolved": True}


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
    """Best-effort parse of a ``.drawio`` XML source into a diagram Artifact.

    Only **top-level** diagram nodes are counted. A vertex is a node when it is
    parented to the root layer or to a Boundary/Network-Boundary container; a
    vertex parented to another node — for example the sub-cells of an embedded
    icon/stencil group that carry a provider glyph — is that node's internal
    geometry, not a separate node, so it is excluded from ``node_names``,
    ``icons`` and the node count.
    """
    edges: List[Edge] = []

    cells = _MXCELL_RE.findall(text)

    # Locate a title cell heuristically: a value containing a ` vN ` token
    # (the title-cell version identifier). Recorded so it is excluded from the
    # node set below.
    title_cell: Optional[str] = None
    for cell in cells:
        value_match = _VALUE_ATTR_RE.search(cell)
        if value_match and re.search(r"\bv[1-9][0-9]*\b", value_match.group(1)):
            title_cell = value_match.group(1)
            break

    # First pass: gather every cell's id/parent and classify text vs. structural
    # cells, so we can distinguish top-level nodes from nested glyph geometry.
    def _cell_id(cell: str) -> str:
        m = _ID_ATTR_RE.search(cell)
        return m.group(1) if m else ""

    def _cell_parent(cell: str) -> str:
        m = _PARENT_ATTR_RE.search(cell)
        return m.group(1) if m else ""

    def _is_text_cell(value: str, style: str) -> bool:
        # Style-based text detection is shared with geometry via constants; the
        # value-based checks (title cell, a "Legend" block) are cli-specific.
        return (
            _is_text_cell_style(style)
            or value == title_cell
            or value.lower().startswith("legend")
        )

    # Boundary/Network-Boundary containers hold nodes but are themselves the
    # stack/network frame. A vertex whose parent is the root layer or one of
    # these containers is a top-level node. Container detection (REVIEW.md C4)
    # is the shared rule in constants.is_boundary_container_style, so node
    # counting here and the geometry-aware layout checks cannot drift.
    boundary_ids: set[str] = set()
    for cell in cells:
        if not _VERTEX_RE.search(cell):
            continue
        cid = _cell_id(cell)
        m = _STYLE_ATTR_RE.search(cell)
        style = m.group(1) if m else ""
        if _is_boundary_container_style(cid, style):
            boundary_ids.add(cid)
    node_container_parents = {_ROOT_LAYER_ID} | boundary_ids

    node_names: List[str] = []
    icons: List[Any] = []
    for cell in cells:
        value_match = _VALUE_ATTR_RE.search(cell)
        value = value_match.group(1) if value_match else ""
        style_match = _STYLE_ATTR_RE.search(cell)
        style = style_match.group(1) if style_match else ""
        style_low = style.lower()
        if _EDGE_RE.search(cell):
            edges.append(Edge(label=value or None))
        elif _VERTEX_RE.search(cell):
            cid = _cell_id(cell)
            parent = _cell_parent(cell)
            # Skip text-only cells (titles, legends, free labels).
            if _is_text_cell(value, style_low):
                continue
            # A boundary container is not itself a counted node.
            if cid in boundary_ids:
                continue
            # Only top-level nodes count: a vertex nested inside another node
            # (an embedded glyph/stencil group) is that node's internal
            # geometry, not a separate node.
            if parent not in node_container_parents:
                continue
            if value or style:
                node_names.append(value)
            # Classify the icon so an unresolved placeholder trips icon-resolved
            # (REVIEW.md C2). A node with no style at all is itself unresolved.
            icons.append(_icon_descriptor_for_style(style))

    has_legend = "legend" in text.lower()

    companion = os.path.splitext(path)[0] + ".diagram.md"
    # `NN-topic.drawio` -> `NN-topic.diagram.md`
    if path.endswith(".drawio"):
        companion = path[: -len(".drawio")] + ".diagram.md"

    # Harvest every fontSize token so the ``min-font-size`` rule can flag text
    # below the accessibility floor (REVIEW.md D1). Includes labels, titles,
    # boundary captions, and legend cells.
    font_sizes = [int(m) for m in _FONT_SIZE_RE.findall(text)]

    # Parse a light geometry model so the geometry-aware rules
    # (grid-alignment, container-padding, edge-routing, node-overlap)
    # can evaluate layout quality on the real file (REVIEW.md D2/D3/D6).
    try:
        from rule_engine import geometry as _geometry
        geo = _geometry.build_geometry(text)
    except Exception:
        geo = None

    return Artifact(
        kind="diagram",
        path=path,
        node_names=node_names,
        edges=edges,
        icons=icons,
        font_sizes=font_sizes,
        geometry=geo,
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


def _parse_snapshot(path: str, text: str) -> Artifact:
    """Parse an inventory Snapshot JSON file into a snapshot Artifact.

    The whole file content is handed to the Linter's ``secret-safety`` scan
    (REVIEW.md C3): a Snapshot must record metadata only, so any secret value,
    key material, or SecureString content in the file is a CRITICAL finding.
    """
    return Artifact(
        kind="snapshot",
        path=path,
        is_snapshot_file=True,
        content=text,
    )


def parse_artifact(path: str) -> Artifact:
    """Parse a file at ``path`` into an :class:`Artifact` (best-effort).

    ``.drawio`` files parse as diagrams, ``.md``/``.markdown`` as documents, and
    Snapshot ``.json`` files as snapshots (routed through ``secret-safety``).

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
    if lower.endswith(".json"):
        return _parse_snapshot(path, text)
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
    "review.md",  # hand-authored architecture review, not a generated KB doc
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


def _is_snapshot_json(path: str) -> bool:
    """Return True when a ``.json`` file is an inventory Snapshot to secret-scan.

    A JSON file is treated as a Snapshot (REVIEW.md C3) when either:

    * it lives inside an ``inventory-*`` Snapshot folder (inventory-standards
      snapshot naming), or
    * its content is a Normalized Resource (an object with ``resource_type`` or
      ``provider``) or a list of such objects.

    JSON Schema files and other config JSON are not snapshots and are skipped.
    """
    parts = os.path.normpath(path).split(os.sep)
    if any(seg.startswith("inventory-") for seg in parts):
        return True
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = json.loads(fh.read())
    except (OSError, json.JSONDecodeError):
        return False
    candidates = data if isinstance(data, list) else [data]
    for item in candidates:
        if isinstance(item, dict) and ("resource_type" in item or "provider" in item):
            return True
    return False


def discover_artifacts(workspace_root: str) -> List[str]:
    """Return the sorted list of lintable ``.drawio``/Markdown/Snapshot files.

    Diagrams (``.drawio``), engine-generated Markdown, and inventory Snapshot
    JSON files are all routed through the Linter so the ``secret-safety``
    CRITICAL gate actually runs in the CLI/CI ``--all`` path (REVIEW.md C3).
    """
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
            elif low.endswith(".json") and _is_snapshot_json(full):
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
