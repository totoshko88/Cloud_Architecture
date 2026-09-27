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
--json
    Emit the full lint result list as JSON on stdout instead of the
    human-readable ``[BLOCKED]``/``[OK]`` lines. Findings carry their
    ``offenders`` and ``reason``; a ``secret-safety`` offender is a JSON pointer
    or ``line:<n>`` location, never a secret value.

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

from datetime import date

from . import kb_validator as _kb_validator
from . import linter as _linter
from .constants import ROOT_LAYER_ID as _ROOT_LAYER_ID
from .constants import is_boundary_container_style as _is_boundary_container_style
from .constants import is_text_cell_style as _is_text_cell_style
from . import icon_refs as _icon_refs
from .drawio_model import DrawioParseError, Page, parse_drawio
from .linter import (
    Artifact,
    Edge,
    RULESET_UNAVAILABLE_ERROR,
    Severity,
    find_ruleset,
    lint,
)
from .ruleset import RulesetUnavailableError, require_ruleset

# Exit codes.
EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_RULESET_UNAVAILABLE = 2
EXIT_USAGE = 3

_DEFAULT_FAIL_ON = (Severity.ERROR, Severity.CRITICAL)

# ---------------------------------------------------------------------------
# Best-effort file parsing
# ---------------------------------------------------------------------------

# The full diagram title format (diagram-standards "Title Cell Format",
# honest-gates R1.11):
#   <provider> <workload> — <boundary id> / <region> | <date> | vN
# The title cell is the text cell whose label matches this in full; a stray
# ``vN`` token in an unrelated cell no longer satisfies ``title-versioned``.
TITLE_RE = re.compile(
    r"^(?P<provider>\S+) (?P<workload>.+?) — (?P<boundary>.+?) / "
    r"(?P<region>\S+) \| (?P<date>\d{4}-\d{2}-\d{2}) \| v(?P<n>[1-9]\d*)$"
)

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


_FLOW_HEADING = "flow"
_LEGEND_HEADING = "legend"


def _first_nonempty_line(cell: "Any") -> str:
    """Return the first non-empty rendered line of a parsed cell, casefolded."""
    for line in cell.lines:
        stripped = line.strip()
        if stripped:
            return stripped.casefold()
    return ""


def _companion_path(path: str) -> str:
    """Return the ``NN-topic.diagram.md`` companion path for a ``.drawio`` file."""
    if path.endswith(".drawio"):
        return path[: -len(".drawio")] + ".diagram.md"
    return os.path.splitext(path)[0] + ".diagram.md"


def _load_companion_frontmatter(
    companion: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Read a companion ``.diagram.md`` frontmatter mapping.

    Returns ``(mapping_or_None, parse_failed)``. ``parse_failed`` is True when the
    companion exists but its frontmatter does not parse as YAML — the diagram
    artifact then carries a ``parse-error`` (design §2 / R2.5), rather than
    silently defaulting to ``flow``. A companion with no frontmatter block, or no
    companion at all, is ``(None, False)``.
    """
    if not os.path.isfile(companion):
        return None, False
    try:
        with open(companion, "r", encoding="utf-8") as fh:
            block, _body = _kb_validator.split_frontmatter(fh.read())
    except OSError:
        return None, True
    if block is None:
        return None, False
    fm, violations = _kb_validator.load_frontmatter(block)
    if fm is None:
        return None, True
    return fm, False


def _parse_drawio_page(path: str, page: Page, text: str) -> Artifact:
    """Best-effort parse of a ``.drawio`` XML source into a diagram Artifact.

    Only **top-level** diagram nodes are counted. A vertex is a node when it is
    parented to the root layer or to a Boundary/Network-Boundary container; a
    vertex parented to another node — for example the sub-cells of an embedded
    icon/stencil group that carry a provider glyph — is that node's internal
    geometry, not a separate node, so it is excluded from ``node_names``,
    ``icons`` and the node count.
    """
    cells = page.cells

    # Boundary/Network-Boundary containers hold nodes but are themselves the
    # stack/network frame. A vertex whose parent is the root layer or one of
    # these containers is a top-level node. Container detection (REVIEW.md C4)
    # is the shared rule in constants.is_boundary_container_style, so node
    # counting here and the geometry-aware layout checks cannot drift.
    boundary_ids = {
        cid
        for cid, cell in cells.items()
        if cell.vertex and _is_boundary_container_style(cid, cell.style)
    }
    node_container_parents = {_ROOT_LAYER_ID} | boundary_ids

    # Structural Legend and title detection (honest-gates R1.11, R1.12). The
    # Legend is the text cell whose first non-empty line, casefolded, is
    # ``legend``; the Flow cell the one whose first line is ``flow``. The title
    # cell is the text cell whose whole label matches TITLE_RE with a real
    # calendar date. Identifying them by structure means a stray ``legend`` id or
    # a ``vN`` token in an unrelated cell no longer satisfies the rules.
    legend_lines: Optional[List[str]] = None
    flow_legend_lines: List[str] = []
    title_cell: Optional[str] = None
    title_cell_id: Optional[str] = None
    for cid, cell in cells.items():
        if not _is_text_cell_style(cell.style):
            continue
        heading = _first_nonempty_line(cell)
        if heading == _LEGEND_HEADING and legend_lines is None:
            legend_lines = [line.strip() for line in cell.lines]
        elif heading == _FLOW_HEADING and not flow_legend_lines:
            flow_legend_lines = [line.strip() for line in cell.lines]
        if title_cell is None:
            match = TITLE_RE.match(cell.label)
            if match:
                try:
                    date.fromisoformat(match.group("date"))
                except ValueError:
                    pass
                else:
                    title_cell = cell.label
                    title_cell_id = cid

    has_legend = legend_lines is not None

    # Nodes, edges and icons over the parsed cells. A text cell (title, legend,
    # flow, free label) is never a node; a boundary container is not itself a
    # counted node; a vertex nested inside another node (an embedded glyph /
    # stencil group) is that node's internal geometry, not a separate node.
    node_names: List[str] = []
    icons: List[Any] = []
    edges: List[Edge] = []
    edge_endpoints: List[str] = []
    for cid, cell in cells.items():
        if cell.edge:
            edges.append(Edge(
                source=cell.source or "",
                target=cell.target or "",
                label=cell.label or None,
            ))
            # Record broken endpoints (R1.10): a missing source/target, or one
            # that names a cell id absent from the page.
            if cell.source is None:
                edge_endpoints.append("missing-source")
            elif cell.source not in cells:
                edge_endpoints.append(f"dangling-source:{cell.source}")
            if cell.target is None:
                edge_endpoints.append("missing-target")
            elif cell.target not in cells:
                edge_endpoints.append(f"dangling-target:{cell.target}")
            continue
        if not cell.vertex:
            continue
        if cid in boundary_ids:
            continue
        if _is_text_cell_style(cell.style) or cid == title_cell_id:
            continue
        if cell.parent not in node_container_parents:
            continue
        if cell.label or cell.style:
            node_names.append(cell.label)
        # Classify the icon so an unresolved placeholder trips icon-resolved
        # (REVIEW.md C2). A node with no style at all is itself unresolved.
        icons.append(_icon_descriptor_for_style(cell.style))

    # Harvest every fontSize token so the ``min-font-size`` rule can flag text
    # below the accessibility floor. The parsed model preserves each cell's raw
    # ``style``, so read the tokens from there rather than from a text regex.
    font_sizes: List[int] = []
    for cell in cells.values():
        fs = cell.style_map.get("fontSize")
        if fs is not None:
            try:
                font_sizes.append(int(float(fs)))
            except (TypeError, ValueError):
                pass

    # Geometry from the same parsed Page (task 9.1). A geometry exception is not
    # swallowed here — it is raised so ``parse_artifacts`` records a
    # ``geometry:<Type>:<msg>`` parse-error (R1.8) instead of the old blanket
    # ``except Exception: geo = None`` that silently dropped the layout rules.
    from rule_engine import geometry as _geometry

    geo = _geometry.build_geometry(page)
    text_padding_offenders = _geometry.check_text_padding(text)

    # Diagram class + cross-link contract. The class and the summary_of /
    # detailed_view links are declared in the companion .diagram.md frontmatter
    # (reliable YAML), read through the shared kb_validator loader. A companion
    # that exists but fails to parse makes this artifact carry a ``parse-error``
    # rather than silently defaulting to ``flow`` (design §2 / R2.5).
    companion = _companion_path(path)
    fm, companion_parse_failed = _load_companion_frontmatter(companion)
    diagram_class = "flow"
    summary_of = None
    detailed_view = None
    if fm:
        _cls = str(fm.get("diagram_class", "") or "").strip().lower()
        if _cls in ("flow", "landscape"):
            diagram_class = _cls
        _so = fm.get("summary_of")
        summary_of = str(_so).strip() if _so else None
        _dv = fm.get("detailed_view")
        detailed_view = str(_dv).strip() if _dv else None

    # Overlay vocabulary coverage (R1.12). Overlay markers come from the
    # ``overlay`` style key of each cell; a term is documented only when it
    # appears as a whole token in the structurally-detected Legend lines.
    overlay_markers: List[str] = []
    for cell in cells.values():
        term = cell.style_map.get("overlay")
        if term:
            overlay_markers.append(term)
    legend_overlay_terms: List[str] = []
    if legend_lines is not None:
        legend_tokens = {
            tok.casefold()
            for line in legend_lines
            for tok in re.split(r"[^A-Za-z0-9_\-]+", line)
            if tok
        }
        for term in set(overlay_markers):
            if term.casefold() in legend_tokens:
                legend_overlay_terms.append(term)

    parse_errors: List[str] = []
    if companion_parse_failed:
        parse_errors.append("companion-frontmatter")

    # honest-gates 1.7.0 (task 10.4 / R4.5): extract the manifest-resolvable icon
    # references (resIcon / grIcon / azure2 / oci-*) from the same parsed page and
    # hand them to the ``icon-resolved`` rule, which resolves them against the
    # committed manifests. Flatten the per-cell mapping into one list; file-path
    # (``image``) and ``generic-shape`` refs are carried too but the rule only
    # resolves the manifest-backed kinds (the rest are the verifier's business).
    icon_ref_list: List[Any] = []
    for cell_refs in _icon_refs.extract_refs(page).values():
        icon_ref_list.extend(cell_refs)

    return Artifact(
        kind="diagram",
        path=path,
        page=page.name,
        node_names=node_names,
        edges=edges,
        icons=icons,
        icon_refs=icon_ref_list,
        font_sizes=font_sizes,
        geometry=geo,
        grid_size=page.grid_size,
        text_padding_offenders=text_padding_offenders,
        has_legend=has_legend,
        legend_lines=legend_lines,
        title_cell=title_cell,
        edge_endpoints=edge_endpoints,
        parse_errors=parse_errors,
        source_format="drawio",
        is_drawio=True,
        has_companion_doc=os.path.isfile(companion),
        diagram_class=diagram_class,
        summary_of=summary_of,
        detailed_view=detailed_view,
        overlay_markers=overlay_markers,
        legend_overlay_terms=legend_overlay_terms,
        flow_legend_lines=flow_legend_lines,
    )


def _parse_markdown(path: str, text: str) -> Artifact:
    """Best-effort parse of a Markdown document into a document Artifact.

    A Markdown file that lives inside an ``inventory-*`` Snapshot folder is also
    a snapshot artifact: ``in_snapshot`` is set so ``secret-safety`` scans its
    text regardless of kind (R3.5).
    """
    block, _body = _kb_validator.split_frontmatter(text)
    frontmatter: Optional[Dict[str, Any]] = None
    if block is not None:
        fm, _violations = _kb_validator.load_frontmatter(block)
        frontmatter = fm
    return Artifact(
        kind="document",
        path=path,
        is_markdown=True,
        frontmatter=frontmatter,
        text=text,
        in_snapshot=_in_inventory_folder(path),
        # Structural KB checks run only for a generated KB document (design §4 /
        # R2.8): a companion / versioned KB doc is ``is_kb=True``, while a
        # snapshot ``00-MANIFEST.md`` is ``is_kb=False`` (D5) — validated for
        # secrets as in-snapshot text, but exempt from the frontmatter/structure
        # contract.
        is_kb=_is_kb_document(path),
    )


def _parse_snapshot(path: str, text: str) -> Artifact:
    """Parse an inventory Snapshot JSON file into a snapshot Artifact.

    The whole file content is handed to the Linter's ``secret-safety`` scan
    (REVIEW.md C3 / R3.1): a Snapshot must record metadata only, so any secret
    value, key material, or SecureString content in the file is a CRITICAL
    finding. ``text`` carries the same content on the honest-gates field and
    ``in_snapshot`` marks a file that lives inside an ``inventory-*`` folder.

    honest-gates 1.7.0 (task 10.3 / R3.5): a ``.json`` snapshot that does **not**
    parse as JSON carries a ``json-parse`` ``parse-error`` cause. The Linter then
    reports that parse-error *and* still scans the raw text for secrets (an
    unparsable file that leaks a key must not slip through), so both findings
    coexist rather than the parse-error short-circuiting the secret scan.
    """
    parse_errors: List[str] = []
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        parse_errors.append(f"json-parse:{exc.msg} (line {exc.lineno}, col {exc.colno})")
    return Artifact(
        kind="snapshot",
        path=path,
        is_snapshot_file=True,
        content=text,
        text=text,
        in_snapshot=_in_inventory_folder(path),
        parse_errors=parse_errors,
    )


def _parse_inventory_text(path: str, text: str) -> Artifact:
    """Parse a non-JSON UTF-8 text file under ``inventory-*`` into a snapshot.

    Every UTF-8 text file inside a Snapshot folder is a snapshot artifact
    (``in_snapshot=True`` with its raw ``text``) so ``secret-safety`` scans it
    regardless of extension (R3.5). A Markdown snapshot file is routed through
    :func:`_parse_markdown` instead (so it is *also* a KB document when it is not
    an exempt ``00-MANIFEST.md``); this handles ``.yaml``, ``.txt``, ``.csv`` and
    the like.
    """
    return Artifact(
        kind="snapshot",
        path=path,
        is_snapshot_file=True,
        content=text,
        text=text,
        in_snapshot=True,
    )


# draw.io is the only publishable diagram source in 1.7.0 (D1). A ``.puml`` /
# ``.mmd`` file is still discovered so the ``source-format`` ERROR (task 10.2)
# fires on it; here we only route the file and set ``source_format``.
_SOURCE_FORMAT_BY_SUFFIX = {
    ".puml": "plantuml",
    ".mmd": "mermaid",
}


def _parse_source_diagram(path: str, text: str, source_format: str) -> Artifact:
    """Parse a ``.puml`` / ``.mmd`` file into a diagram Artifact (D1).

    The Artifact carries only ``source_format`` and the raw ``text`` — it is not
    a ``.drawio`` model — so the ``source-format`` rule can report it as a
    non-publishable diagram source without any geometry parsing.
    """
    return Artifact(
        kind="diagram",
        path=path,
        source_format=source_format,
        is_drawio=False,
        text=text,
        in_snapshot=_in_inventory_folder(path),
    )


def _diagram_artifact_from_error(path: str, cause: str) -> Artifact:
    """A diagram Artifact that carries a single ``parse-error`` cause (R1.8).

    Emitted when a ``.drawio`` file cannot be parsed at all (a
    ``DrawioParseError``) or when geometry construction raises for one of its
    pages. It carries no model, so the ``parse-error`` rule (task 10.2) fires and
    every other rule is skipped for it.
    """
    return Artifact(
        kind="diagram",
        path=path,
        source_format="drawio",
        is_drawio=True,
        parse_errors=[cause],
    )


def _parse_drawio_artifacts(path: str, text: str) -> List[Artifact]:
    """Turn a ``.drawio`` file into one Artifact per page (honest-gates R1.3).

    A :class:`DrawioParseError` from the parser yields a single diagram Artifact
    carrying that cause. Each parsed page becomes one Artifact; a geometry
    exception raised while building that page's model is caught here and turned
    into a ``geometry:<Type>:<msg>`` parse-error on that page's Artifact — never
    the pre-1.7 blanket ``except Exception: geo = None`` that silently dropped
    the layout rules.
    """
    try:
        pages = parse_drawio(text, path=path)
    except DrawioParseError as exc:
        artifact = _diagram_artifact_from_error(path, exc.cause)
        artifact.label = path
        return [artifact]

    multi = len(pages) > 1
    artifacts: List[Artifact] = []
    for page in pages:
        try:
            artifact = _parse_drawio_page(path, page, text)
        except DrawioParseError as exc:
            artifact = _diagram_artifact_from_error(path, exc.cause)
            artifact.page = page.name
        except Exception as exc:  # geometry construction (R1.8)
            artifact = _diagram_artifact_from_error(
                path, f"geometry:{type(exc).__name__}:{exc}"
            )
            artifact.page = page.name
        # Label findings ``<file>#<page>`` for a multi-page file, plain ``<file>``
        # for a single page (so existing output and tests keep their shape).
        artifact.label = f"{path}#{page.name}" if multi else path
        artifacts.append(artifact)
    return artifacts


def parse_artifacts(path: str) -> List[Artifact]:
    """Parse a file at ``path`` into a list of :class:`Artifact` (R1.3).

    A ``.drawio`` file yields one Artifact per page (labelled ``<file>#<page>``
    for a multi-page file, plain ``<file>`` for a single page). A ``.md`` /
    ``.markdown`` file yields a document Artifact and a ``.json`` a snapshot
    Artifact — each a single-element list.

    Raises
    ------
    FileNotFoundError
        When ``path`` does not exist.
    ValueError
        When the file extension is not a supported artifact type.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    lower = path.lower()
    if lower.endswith(".drawio"):
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            return [_diagram_artifact_from_error(path, f"unicode:{exc}")]
        return _parse_drawio_artifacts(path, text)

    # ``.puml`` / ``.mmd`` diagram sources (D1): read strictly as UTF-8 text so a
    # non-text file is reported rather than silently mangled.
    source_format = None
    for suffix, fmt in _SOURCE_FORMAT_BY_SUFFIX.items():
        if lower.endswith(suffix):
            source_format = fmt
            break

    # Every UTF-8 text file under an ``inventory-*`` folder is a Snapshot
    # artifact (R3.5); a binary file there is a ``parse-error: not-text``. Read
    # such files strictly (no ``errors="replace"``) so a binary file is caught.
    in_inventory = _in_inventory_folder(path)
    strict_text = (
        source_format is not None
        or in_inventory
        or lower.endswith(".json")
    )
    if strict_text:
        with open(path, "rb") as fh:
            raw = fh.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            if in_inventory:
                return [
                    Artifact(
                        kind="snapshot",
                        path=path,
                        is_snapshot_file=True,
                        in_snapshot=True,
                        parse_errors=["not-text"],
                    )
                ]
            # A non-inventory ``.puml``/``.mmd``/``.json`` that is not UTF-8:
            # fall back to lenient decoding so the routing below still applies.
            text = raw.decode("utf-8", errors="replace")
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()

    if source_format is not None:
        return [_parse_source_diagram(path, text, source_format)]
    if lower.endswith((".md", ".markdown")):
        # A Markdown file (KB document, and additionally a snapshot text file
        # when it lives under ``inventory-*``).
        return [_parse_markdown(path, text)]
    if lower.endswith(".json"):
        return [_parse_snapshot(path, text)]
    if in_inventory:
        # Any other UTF-8 text file inside a Snapshot folder (``.yaml``, ``.txt``,
        # ``.csv``, …) is a snapshot artifact scanned for secrets.
        return [_parse_inventory_text(path, text)]
    raise ValueError(f"unsupported artifact type for linting: {path}")


def parse_artifact(path: str) -> Artifact:
    """Parse a single-page file at ``path`` into one :class:`Artifact`.

    Compatibility wrapper for callers that expect exactly one artifact. It
    returns the sole artifact of a single-page file and raises
    ``ValueError("multi-page: use parse_artifacts")`` for a multi-page
    ``.drawio`` file, so no caller silently lints only page one.

    Raises
    ------
    FileNotFoundError
        When ``path`` does not exist.
    ValueError
        When the file extension is not supported, or the file has several pages.
    """
    artifacts = parse_artifacts(path)
    if len(artifacts) != 1:
        raise ValueError("multi-page: use parse_artifacts")
    return artifacts[0]


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
    "build",  # setuptools build/ output (build/lib/... copies), not source artifacts
    "dist",  # built wheels/sdists
    "_bootstrap",  # bundled workspace-bootstrap payload (build-time copy of the rules)
    ".kiro",  # steering/specs are rule sources, not linted artifacts
    "tests",  # test inputs (deliberately-invalid parser fixtures) are not workspace artifacts
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
    "architecture.md",  # hand-authored project architecture/algorithm doc
    "kiro-university-compliance.md",  # hand-authored Kiro feature-compliance doc
    "skill.md",  # Kiro agent-skill manifest (.kiro/skills/*/SKILL.md), not a KB doc
    "diagram-design-notes.md",  # hand-authored routing/icon rationale doc
    "pull_request_template.md",  # GitHub PR template (.github/), not a KB doc
}


def _is_generated_markdown(path: str) -> bool:
    """Return True when a Markdown file is an engine-generated KB document.

    Companion documents (``*.diagram.md``) and versioned inventory / KB
    documents are linted; top-level hand-authored repo docs (README, INSTALL,
    CHANGELOG, ...) are not. Steering files are rule *sources*, not generated KB
    documents: those under the repo's own ``.kiro/steering`` are already skipped
    by the ``.kiro`` directory prune in ``_EXCLUDED_DIRS``, but a power ships its
    steering under ``dev.kiro/steering`` (walked normally), and steering uses
    Kiro's ``inclusion:`` frontmatter, not the 12 KB keys — so the frontmatter
    contract must not apply to it. Exempt any ``*.kiro/steering/`` file here, the
    single predicate both the ``--all`` scan and the ``--file`` hook path use.
    """
    if _is_steering_markdown(path):
        return False
    base = os.path.basename(path).lower()
    if base.endswith(".diagram.md"):
        return True
    return base not in _EXCLUDED_MD_BASENAMES


def _is_steering_markdown(path: str) -> bool:
    """True when ``path`` is a Kiro steering doc (a rule source, not a KB doc).

    Matches a file directly inside a ``steering`` directory whose parent is a
    Kiro config dir — literal ``.kiro`` or a client-namespaced ``*.kiro`` such as
    ``dev.kiro`` (the power's ``dev.kiro/steering``). Steering carries an
    ``inclusion:`` frontmatter contract, not the 12 generated-KB keys, so it is
    exempt from the ``frontmatter`` rule.
    """
    parts = [p.lower() for p in os.path.normpath(path).split(os.sep)]
    for i in range(1, len(parts) - 1):
        parent = parts[i - 1]
        # ".kiro" / "dev.kiro" (workspace/power) and the dot-free "kiro" used by
        # the bundled package payload all denote a steering source directory.
        if parts[i] == "steering" and (
            parent == ".kiro" or parent == "kiro" or parent.endswith(".kiro")
        ):
            return True
    return False


def _in_inventory_folder(path: str) -> bool:
    """True when ``path`` has an ancestor directory matching ``inventory-*``.

    This is the ``inventory-standards`` Snapshot-folder naming
    (``inventory-<provider>-<boundary>-<region>-<timestamp>``). Any UTF-8 text
    file under such a folder is a Snapshot artifact and is secret-scanned
    regardless of its extension (R3.5), so its directory segments — not its own
    basename — are what matter.
    """
    parts = os.path.normpath(path).split(os.sep)
    # The final segment is the file itself; only ancestor directories count.
    return any(seg.startswith("inventory-") for seg in parts[:-1])


def _is_snapshot_manifest(path: str) -> bool:
    """True for a ``00-MANIFEST.md`` inside an ``inventory-*`` Snapshot folder.

    Such a manifest is the Collector's table manifest, owned by
    ``snapshot_gate``; it is exempt from the generated-KB frontmatter rule (D5).
    A ``00-MANIFEST.md`` that lives *outside* a Snapshot folder (for example
    ``examples/azure/00-MANIFEST.md``) is a normal KB document and is not
    matched here.
    """
    return os.path.basename(path).lower() == "00-manifest.md" and _in_inventory_folder(
        path
    )


def _is_kb_document(path: str) -> bool:
    """True when a Markdown file is a generated KB document the KB rule applies to.

    ``_is_kb_document = _is_generated_markdown and not _is_snapshot_manifest``
    (design §2, D5): a companion / versioned KB document is validated for its
    frontmatter and structure, but a snapshot ``00-MANIFEST.md`` is exempt (it
    is scanned only for secrets, as an in-snapshot text file).
    """
    return _is_generated_markdown(path) and not _is_snapshot_manifest(path)


def _json_is_normalized_resource(path: str) -> bool:
    """True when a ``.json`` file's content is a Normalized Resource.

    A Normalized Resource is an object with ``resource_type`` or ``provider``
    (or a list of such objects). JSON Schema files and other config JSON are not
    snapshots and are skipped.
    """
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


def _is_snapshot_json(path: str) -> bool:
    """Return True when a ``.json`` file is an inventory Snapshot to secret-scan.

    A JSON file is treated as a Snapshot (REVIEW.md C3) when either:

    * it lives inside an ``inventory-*`` Snapshot folder (inventory-standards
      snapshot naming), or
    * its content is a Normalized Resource (an object with ``resource_type`` or
      ``provider``) or a list of such objects.

    JSON Schema files and other config JSON are not snapshots and are skipped.
    """
    if _in_inventory_folder(path):
        return True
    return _json_is_normalized_resource(path)


# Scratch / duplicate file markers. A copy made by an editor or file manager
# (e.g. draw.io desktop, Finder, Explorer) is an editing scratch, not a golden
# artifact, so it is excluded from the --all scan (and thus from lint, the
# golden-example tests, and CI). Markers cover the common localized "copy"
# suffixes and numeric duplicates.
_SCRATCH_NAME_MARKERS = (
    "копія",       # uk: "copy" (draw.io/Finder on a Ukrainian system)
    "copy",        # en: "... copy" / "... - Copy"
    "копия",       # ru
    "kopie",       # de/nl
    "copie",       # fr
    "copia",       # es/it/pt
)


def _is_scratch_copy(name: str) -> bool:
    """True when a filename looks like an editor/file-manager duplicate.

    Matches a copy marker as a whole word / suffix (``… копія.drawio``,
    ``… - Copy.drawio``, ``… copy 2.drawio``) or a trailing ``(1)`` numeric
    duplicate, so a legitimate name that merely contains the substring (e.g.
    ``copybook``) is not excluded."""
    stem = re.sub(r"\.[A-Za-z0-9.]+$", "", name).lower()
    if re.search(r"\(\d+\)\s*$", stem):
        return True
    for marker in _SCRATCH_NAME_MARKERS:
        # marker as a standalone trailing token, optionally followed by a number:
        # "... copy", "... - copy", "... копія 2".
        if re.search(rf"(?:^|[ \-_]){re.escape(marker)}(?:[ \-_]?\d+)?\s*$", stem):
            return True
    return False


def _is_reference_artifact(name: str) -> bool:
    """True when a filename is a preserved ``-reference`` snapshot.

    The hand-authored HA golden pair is frozen as ``NN-...-reference.drawio``
    (plus its ``.drawio.png`` / ``.diagram.md`` companions) before the layout
    engine takes over generation. A reference snapshot is deliberately kept
    out of both the lint scan and any regeneration discovery: it is a
    read-only comparison baseline, not a golden artifact to validate or
    re-emit. The marker is the ``-reference`` stem suffix, matched before the
    extension so ``02-aws-ha-multiregion-landscape-reference.drawio`` and its
    ``-reference.drawio.png`` / ``-reference.diagram.md`` companions are all
    excluded, while a legitimate name that merely contains the substring is
    not (the suffix must terminate the stem)."""
    stem = re.sub(r"\.[A-Za-z0-9.]+$", "", name)
    return stem.endswith("-reference")


def discover_artifacts(workspace_root: str) -> List[str]:
    """Return the sorted list of lintable ``.drawio``/Markdown/Snapshot files.

    Diagrams (``.drawio``), engine-generated Markdown, and inventory Snapshot
    JSON files are all routed through the Linter so the ``secret-safety``
    CRITICAL gate actually runs in the CLI/CI ``--all`` path (REVIEW.md C3).
    Editor/file-manager duplicates (``… копія.drawio``, ``… - Copy.drawio``,
    ``… (1).drawio``) are scratch, not golden artifacts, and are skipped, as
    are preserved ``-reference`` snapshots (frozen comparison baselines that
    are neither linted nor regenerated).
    """
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        for name in filenames:
            if _is_scratch_copy(name) or _is_reference_artifact(name):
                continue
            low = name.lower()
            full = os.path.join(dirpath, name)
            in_inventory = _in_inventory_folder(full)
            if low.endswith(".drawio"):
                found.append(full)
            elif low.endswith((".puml", ".mmd")):
                # Non-publishable diagram sources, discovered so ``source-format``
                # (task 10.2) reports them (D1, R10.3).
                found.append(full)
            elif low.endswith((".md", ".markdown")):
                # A generated KB document, or any Markdown inside an
                # ``inventory-*`` snapshot folder (secret-scanned there even when
                # it is an exempt ``00-MANIFEST.md``).
                if _is_kb_document(full) or in_inventory:
                    found.append(full)
            elif low.endswith(".json") and _is_snapshot_json(full):
                found.append(full)
            elif in_inventory:
                # Any other UTF-8 text (or binary) file inside a Snapshot folder
                # is a snapshot artifact scanned for secrets (R3.5).
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


def _format_offenders(offenders: Sequence[Any]) -> str:
    """Render a finding's offender ids as ``[a, b, c]`` (empty list → ``[]``).

    Offenders are always identifiers — node/edge/container ids, JSON pointers or
    ``line:<n>`` locations — never values, so a ``secret-safety`` finding printed
    here can never leak a secret (design §2, R1.13).
    """
    return "[" + ", ".join(str(o) for o in offenders) + "]"


def _print_result(result: Dict[str, Any], label: str, failed: bool) -> None:
    """Print one lint result in the ``[BLOCKED]``/``[OK]`` human format (R1.13).

    A blocked artifact prints its summary line followed by one line per finding::

        [BLOCKED] <label>: rule(SEV), …
            - SEV rule [offenders]: reason
    """
    status = "BLOCKED" if failed else "OK"
    findings = result.get("findings", [])
    summary = (
        ", ".join(f"{f['rule']}({f['severity']})" for f in findings) or "no findings"
    )
    print(f"[{status}] {label}: {summary}")
    for f in findings:
        offenders = _format_offenders(f.get("offenders", ()))
        reason = f.get("reason", "") or ""
        suffix = f": {reason}" if reason else ""
        print(f"    - {f['severity']} {f['rule']} {offenders}{suffix}")


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
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the full lint result list as JSON on stdout instead of the "
        "human-readable [BLOCKED]/[OK] lines",
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

    # R10.2 / Requirement 7 AC14: the Lint_CLI and the Contract locate the
    # ruleset the same way and fail closed when it is absent. ``require_ruleset``
    # resolves it (env var, workspace root, repo checkout, bundled payload) or
    # raises ``RulesetUnavailableError``, which maps to exit 2 — every artifact
    # is blocked from publication, and no output is emitted.
    try:
        require_ruleset(workspace_root=workspace_root)
    except RulesetUnavailableError as exc:
        print(
            f"rule-engine-lint: {exc}. Every artifact is blocked from "
            "publication.",
            file=sys.stderr,
        )
        return EXIT_RULESET_UNAVAILABLE

    # Gather targets.
    if args.file:
        # A single hand-authored Markdown doc (README, ARCHITECTURE, a SKILL.md,
        # etc.) is not an engine-generated KB document, so the kb-frontmatter
        # contract does not apply. Mirror the --all scan's exclusion here so the
        # lint-on-save hook (which calls --file on any saved .md) does not raise
        # a false `frontmatter` CRITICAL on such files.
        low = args.file.lower()
        if low.endswith((".md", ".markdown")) and not _is_generated_markdown(args.file):
            print(f"[SKIP] {args.file}: hand-authored document (frontmatter contract not applied)")
            return EXIT_OK
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
    json_results: List[Dict[str, Any]] = []
    for target in targets:
        try:
            artifacts = parse_artifacts(target)
        except FileNotFoundError:
            print(f"rule-engine-lint: error: file not found: {target}", file=sys.stderr)
            return EXIT_USAGE
        except ValueError as exc:
            # For --all this cannot happen (extensions are filtered); for --file
            # an unsupported extension is a usage error.
            print(f"rule-engine-lint: error: {exc}", file=sys.stderr)
            return EXIT_USAGE

        for artifact in artifacts:
            result = lint(artifact)
            failed = _result_fails(result, fail_on)
            any_failed = any_failed or failed

            # The label names what was evaluated: ``<file>#<page>`` for a page of
            # a multi-page file, else the file path (R1.13).
            label = result.get("label") or getattr(artifact, "label", None) or target
            if args.json:
                json_results.append(result)
            else:
                _print_result(result, label, failed)

    if args.json:
        print(json.dumps(json_results, indent=2, sort_keys=True))

    return EXIT_BLOCKED if any_failed else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
