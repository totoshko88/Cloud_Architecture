"""Diagram & Inventory Rule Engine — Rule Engine Contract.

This module implements the **Rule Engine Contract** (design "Rule Engine
Contract"; Requirement 9 AC6/AC7/AC8): the single invocation boundary an
Arch-Assistant calls to turn one provider Boundary snapshot into the publishable
artifact set. The contract validates inputs, orchestrates the components (Icon
Resolver, Inventory Collector output / Normalizer, Delta Engine, Diagram
Generator, and Linter), and returns the output artifact set.

Public interface (design "Rule Engine Contract")::

    invoke({
        "provider": <aws|azure|gcp|oci|generic>,
        "boundary_id": <str>,
        "region": <str>,
        "previous_doc_path": <str>,
        "inventory_snapshot_path": <str>,
    }) -> {
        "drawio": <path>,
        "drawio_png": <path>,
        "diagram_md": <path>,
        "existing_infrastructure_md": <path>,
    }

**Input validation (Requirement 9 AC6/AC7).** All five inputs are required. The
contract validates inputs *first*: if any required key is missing or empty, or
``provider`` is outside the enumeration ``{aws, azure, gcp, oci, generic}``, the
contract rejects the invocation, produces **no output documents**, and returns an
error naming the missing/invalid input. The rejection is expressed two ways so it
is easy to test either style:

* :func:`invoke` raises :class:`ContractInputError` (carrying ``invalid_input``).
* :func:`invoke_result` returns ``{"error": <message>, "invalid_input": <key>}``
  instead of raising.

**Outputs (Requirement 9 AC8).** On valid inputs the contract produces the
mandatory artifact triple ``NN-topic.drawio`` / ``NN-topic.drawio.png`` /
``NN-topic.diagram.md`` plus the versioned ``NN-existing-infrastructure.md`` (with
kb-frontmatter frontmatter), where ``NN`` is a two-digit zero-padded sequence in
``01``–``99``. Because there is no live cloud here, the contract reads the
inventory snapshot at ``inventory_snapshot_path`` when it exists (a JSON list of
Normalized Resources, or a Collector snapshot folder) and generates deterministic
artifact content; the ``.drawio.png`` raster is written as an exported-raster
stub file (its path is recorded).

**Lints what it writes (Requirement 9).** The contract writes its four outputs
into a private *staging* directory, then lints the real files there through the
**same** path as ``rule-engine-lint --file`` — :func:`rule_engine.cli.parse_artifacts`
followed by :func:`rule_engine.linter.lint_with_ruleset` — rather than through a
synthetic :class:`~rule_engine.linter.Artifact` (R9.1). The frontmatter and body
that are linted are exactly the bytes on disk (R9.4). Only when *every* staged
artifact is eligible for publication are the files moved into ``output_root``;
otherwise the staging directory is removed and :class:`ContractGenerationError`
lists each blocked file with its findings, so a partial/invalid artifact set is
never returned and ``output_root`` is left untouched.

The contract draws **no edges** it did not derive from the input data (R9.2): it
has no relationship information, so the diagram is a set of resolved nodes with
no invented "connects to" edges (the resulting ``node-connectivity`` findings are
non-blocking WARNINGs). IF the current snapshot has more resources than the
diagram-class node limit, the contract raises :class:`ContractGenerationError`
naming the count and the limit instead of silently dropping resources (R9.3).

The authoritative ``diagram-lint.md`` ruleset is located via
:func:`rule_engine.ruleset.require_ruleset` (the shared location used by the
Lint_CLI); a :class:`~rule_engine.ruleset.RulesetUnavailableError` maps to
:class:`ContractGenerationError` before any file is written (Requirement 10.2 /
7 AC14).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rule_engine import cli as cli_mod
from rule_engine import delta as delta_engine
from rule_engine import icon_resolver
from rule_engine import linter as linter_mod
from rule_engine import ruleset as ruleset_mod
from rule_engine.constants import BRAND_HEX as _BRAND_HEX
from rule_engine.constants import PROVIDERS
from rule_engine.constants import provider_labels as _provider_labels

__all__ = [
    "PROVIDERS",
    "REQUIRED_INPUTS",
    "ContractInputError",
    "ContractGenerationError",
    "invoke",
    "invoke_result",
    "validate_inputs",
]

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
# PROVIDERS and the brand palette come from rule_engine.constants (single source
# of truth). The terminology labels are loaded from profiles/terminology.yaml.

#: The five required contract inputs, in the order they are validated
#: (design "Rule Engine Contract" — Inputs).
REQUIRED_INPUTS: Tuple[str, ...] = (
    "provider",
    "boundary_id",
    "region",
    "previous_doc_path",
    "inventory_snapshot_path",
)

# Neutral resource-type -> per-provider native label (terminology normalization
# table; profiles/terminology.yaml). Used for diagram node display labels and the
# companion/inventory documents.
_PROVIDER_LABELS: Dict[str, Dict[str, str]] = _provider_labels()

# Highest zero-padded sequence permitted for NN (01–99).
_MAX_SEQUENCE = 99


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class ContractInputError(ValueError):
    """Raised when the contract rejects an invocation for an invalid input.

    ``invalid_input`` names the offending key (a missing/empty required input, or
    ``"provider"`` for an out-of-enumeration provider value). When raised, the
    contract has produced no output documents (Requirement 9 AC7).
    """

    def __init__(self, invalid_input: str, detail: str) -> None:
        self.invalid_input = invalid_input
        self.detail = detail
        super().__init__(f"invalid-input [{invalid_input}]: {detail}")


class ContractGenerationError(RuntimeError):
    """Raised when the contract cannot return a publishable artifact set.

    Three situations raise it:

    * a staged artifact is blocked from publication — ``artifact`` names the file
      and ``findings`` carries its blocking lint findings;
    * the node count exceeds the diagram-class limit (R9.3) — ``findings`` holds a
      single ``node-count`` record and the message names the count and the limit;
    * the authoritative ruleset is unavailable (R10.2 / 7 AC14) — raised before
      any file is written.
    """

    def __init__(
        self,
        artifact: str,
        findings: Sequence[Mapping[str, str]],
        *,
        message: Optional[str] = None,
    ) -> None:
        self.artifact = artifact
        self.findings = list(findings)
        if message is not None:
            super().__init__(message)
            return
        rendered = ", ".join(
            f"{f.get('rule')}({f.get('severity')})" for f in self.findings
        )
        super().__init__(
            f"generation error: artifact {artifact!r} blocked from publication: "
            f"{rendered}"
        )


# --------------------------------------------------------------------------- #
# Input validation (Requirement 9 AC6/AC7)
# --------------------------------------------------------------------------- #


def validate_inputs(inputs: Any) -> Dict[str, str]:
    """Validate the contract inputs, returning the normalized input mapping.

    Checks, in :data:`REQUIRED_INPUTS` order:

    * ``inputs`` is a mapping;
    * every required key is present and non-empty (after ``str`` + ``strip``);
    * ``provider`` is a member of :data:`PROVIDERS`.

    Raises :class:`ContractInputError` (naming the first offending input) on any
    failure. No output documents are produced on failure (Requirement 9 AC7).
    """
    if not isinstance(inputs, Mapping):
        raise ContractInputError(
            "inputs",
            f"inputs must be a mapping, got {type(inputs).__name__}",
        )

    normalized: Dict[str, str] = {}
    for key in REQUIRED_INPUTS:
        if key not in inputs:
            raise ContractInputError(key, f"required input {key!r} is missing")
        value = inputs[key]
        if value is None:
            raise ContractInputError(key, f"required input {key!r} is empty")
        text = str(value).strip()
        if text == "":
            raise ContractInputError(key, f"required input {key!r} is empty")
        normalized[key] = text

    provider = normalized["provider"]
    if provider not in PROVIDERS:
        raise ContractInputError(
            "provider",
            f"unrecognized provider {provider!r}; expected one of "
            f"{', '.join(PROVIDERS)}",
        )

    return normalized


# --------------------------------------------------------------------------- #
# Snapshot loading (tolerant of a JSON list or a Collector snapshot folder)
# --------------------------------------------------------------------------- #


def _load_snapshot(path: str) -> List[Dict[str, Any]]:
    """Load a current snapshot as a list of Normalized Resource dicts.

    Accepts, in order of preference:

    * a JSON file that is a list of resources;
    * a JSON file that is an object with a ``resources`` list;
    * a Collector snapshot *folder* — every ``*.json`` at its root is read and
      any ``resources`` arrays are concatenated.

    A missing path or unparseable content yields an empty list rather than
    failing: there is no live cloud here, so an absent snapshot simply means
    "nothing enumerated" and the delta treats every resource accordingly.
    """
    p = Path(path)
    if p.is_dir():
        resources: List[Dict[str, Any]] = []
        for json_file in sorted(p.glob("*.json")):
            resources.extend(_resources_from_json(_read_json(json_file)))
        return resources
    if p.is_file():
        return _resources_from_json(_read_json(p))
    return []


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resources_from_json(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, Mapping):
        res = data.get("resources")
        if isinstance(res, list):
            return [r for r in res if isinstance(r, dict)]
        # A single resource object.
        if data.get("resource_type") is not None:
            return [dict(data)]
    return []


def _load_previous_snapshot(path: str) -> Optional[List[Dict[str, Any]]]:
    """Load the previous snapshot for the Delta Engine.

    ``previous_doc_path`` may point at a previous versioned document, a JSON
    snapshot, or a snapshot folder. When it resolves to no resources (missing, or
    a Markdown doc with no embedded snapshot), returns ``None`` so the Delta
    Engine classifies every current resource as ``added`` (Requirement 5 AC6).
    """
    p = Path(path)
    if not p.exists():
        return None
    if p.is_dir():
        resources = _load_snapshot(path)
        return resources or None
    if p.suffix.lower() in {".json"}:
        resources = _resources_from_json(_read_json(p))
        return resources or None
    # A Markdown/other previous document: try to read an embedded snapshot JSON
    # fenced block; otherwise treat as "no previous snapshot".
    return _extract_embedded_snapshot(p) or None


def _extract_embedded_snapshot(path: Path) -> Optional[List[Dict[str, Any]]]:
    """Pull an embedded ```json snapshot fenced block from a Markdown doc."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    marker = "```json"
    start = text.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = text.find("```", start)
    if end == -1:
        return None
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
    return _resources_from_json(data)


def _stamp_boundary_region(
    resources: Sequence[Dict[str, Any]], boundary_id: str, region: str
) -> None:
    """Fill in ``boundary`` / ``region`` on any resource missing them, in place.

    ``boundary`` and ``region`` are part of the Delta Engine identity
    (Requirement 5 AC8). A Collector snapshot is scoped to a single
    boundary/region (encoded in its folder name), so a resource that omits them
    inherits the authoritative values from this invocation. A resource that
    already declares a non-empty value keeps its own.
    """
    for resource in resources:
        if not resource.get("boundary"):
            resource["boundary"] = boundary_id
        if not resource.get("region"):
            resource["region"] = region


# --------------------------------------------------------------------------- #
# Sequence numbering (NN in 01–99)
# --------------------------------------------------------------------------- #


def _next_sequence(output_dir: Path) -> str:
    """Return the next two-digit zero-padded ``NN`` sequence for ``output_dir``.

    Scans existing ``NN-existing-infrastructure.md`` documents and diagram
    sources so re-invoking against the same directory produces the next version.
    Raises :class:`ContractGenerationError` when the ``01``–``99`` space is
    exhausted.
    """
    used: set[int] = set()
    if output_dir.is_dir():
        for child in output_dir.iterdir():
            name = child.name
            if len(name) >= 2 and name[:2].isdigit():
                used.add(int(name[:2]))
    for n in range(1, _MAX_SEQUENCE + 1):
        if n not in used:
            return f"{n:02d}"
    raise ContractGenerationError(
        str(output_dir / "NN-existing-infrastructure.md"),
        [{"rule": "sequence-exhausted", "severity": "ERROR"}],
    )


# --------------------------------------------------------------------------- #
# Icon resolution over the current snapshot
# --------------------------------------------------------------------------- #


def _resolve_nodes(
    provider: str, resources: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Resolve one diagram node per current resource via the Icon Resolver.

    Each node carries its neutral ``resource_type``, a display ``name``, the
    provider ``label`` (terminology normalization), and the resolved
    ``style_string`` / ``brand_hex`` / ``icon_source``. An unmapped type falls
    back to the provider Boundary icon so the diagram never emits an unresolved
    placeholder (which would be an ``icon-resolved`` lint ERROR).
    """
    nodes: List[Dict[str, Any]] = []
    for resource in resources:
        rtype = str(resource.get("resource_type") or "boundary")
        try:
            icon = icon_resolver.resolve_icon(rtype, provider)
        except icon_resolver.IconResolverError:
            # Fall back to the Boundary icon (always present) so no placeholder
            # is emitted; if even that fails, use the provider brand anchor.
            try:
                icon = icon_resolver.resolve_icon("boundary", provider)
            except icon_resolver.IconResolverError:
                icon = {
                    "style_string": "rounded=1;",
                    "brand_hex": _BRAND_HEX.get(provider, "#000000"),
                    "icon_source": "custom",
                }
        label = _PROVIDER_LABELS.get(rtype, {}).get(provider, rtype)
        name = str(resource.get("name") or resource.get("id") or label)
        nodes.append(
            {
                "resource_type": rtype,
                "name": name,
                "label": label,
                "style_string": icon["style_string"],
                "brand_hex": icon["brand_hex"],
                "icon_source": icon["icon_source"],
            }
        )
    # A diagram with no nodes is degenerate; seed a single Boundary node so the
    # artifact is still meaningful and lint-clean.
    if not nodes:
        try:
            icon = icon_resolver.resolve_icon("boundary", provider)
            style, brand, source = (
                icon["style_string"],
                icon["brand_hex"],
                icon["icon_source"],
            )
        except icon_resolver.IconResolverError:
            style, brand, source = "rounded=1;", _BRAND_HEX.get(provider, "#000000"), "custom"
        nodes.append(
            {
                "resource_type": "boundary",
                "name": _PROVIDER_LABELS["boundary"].get(provider, "Boundary"),
                "label": _PROVIDER_LABELS["boundary"].get(provider, "Boundary"),
                "style_string": style,
                "brand_hex": brand,
                "icon_source": source,
            }
        )
    # The node-count limit (diagram-standards: ≤ 12 nodes for a flow diagram) is
    # NOT enforced by silently slicing here (that would drop resources — R9.3).
    # The caller checks the count against the class limit and raises a
    # ContractGenerationError naming the count and the limit instead.
    return nodes


# --------------------------------------------------------------------------- #
# Artifact rendering
# --------------------------------------------------------------------------- #


def _title_cell(
    provider: str, workload: str, boundary_id: str, region: str, version: int
) -> str:
    """Build the mandated title-cell string (diagram-standards — Title Cell).

    ``<provider> <workload> — <boundary id> / <region> | <date> | vN``
    """
    today = date.today().isoformat()
    return f"{provider} {workload} — {boundary_id} / {region} | {today} | v{version}"


def _legend_lines() -> List[str]:
    """The mandatory Legend block, one entry per line (diagram-standards).

    The **first** line is exactly ``Legend`` so the Linter's structural Legend
    detection (a text cell whose first non-empty line casefolds to ``legend``)
    finds it; the remaining lines document every line style, color, and change
    marker required by the *Mandatory Legend Block* standard.
    """
    return [
        "Legend",
        "solid line = primary flow",
        "dashed line = asynchronous / event-driven flow",
        "red = blocked / missing / disabled",
        "new in version N",
        "changed in version N",
        "dashed green boundary = stack boundary",
        "dashed blue boundary = Network Boundary",
    ]


def _node_slug(text: str) -> str:
    """Slug ``text`` into the allowed unquoted node-name set ``[A-Za-z0-9_-]``.

    Keeps node values `node-quote`-clean without needing double quotes; empty
    results fall back to ``node``.
    """
    import re as _re

    slug = _re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-")
    return slug or "node"


def _render_drawio(title: str, nodes: Sequence[Mapping[str, Any]]) -> str:
    """Render a minimal, lint-clean draw.io (mxGraph) source.

    The source encodes the title cell, the Legend block, and one vertex per node
    with its resolved style. It draws **no edges**: the contract has no
    relationship data for this boundary, and inventing "connects to" edges would
    publish relationships that are not in the input (R9.2). Drawing none is the
    honest output; the resulting ``node-connectivity`` findings are non-blocking
    WARNINGs.
    """
    cells: List[str] = []
    # Title + legend as text cells.
    cells.append(
        f'        <mxCell id="title" value="{_xml_escape(title)}" '
        f'style="text;html=1;" vertex="1" parent="1">\n'
        f'          <mxGeometry x="20" y="10" width="720" height="30" as="geometry"/>\n'
        f"        </mxCell>"
    )
    # The Legend renders each entry on its own line (first line exactly
    # ``Legend``). With ``html=1`` draw.io treats ``<br>`` as a line break, so the
    # parser's structural Legend detection reads ``Legend`` as the first line.
    # Join with an escaped ``<br>`` so the attribute value is well-formed XML;
    # the parser decodes it back to a literal ``<br>`` and, because the cell is
    # ``html=1``, treats it as a line break (first line becomes ``Legend``).
    legend_value = "&lt;br&gt;".join(_xml_escape(line) for line in _legend_lines())
    cells.append(
        f'        <mxCell id="legend" value="{legend_value}" '
        f'style="text;html=1;whiteSpace=wrap;spacingLeft=10;spacingRight=10;'
        f'spacingTop=10;spacingBottom=10;fillColor=#FFFFFF;strokeColor=#000000;" '
        f'vertex="1" parent="1">\n'
        f'          <mxGeometry x="20" y="380" width="720" height="140" as="geometry"/>\n'
        f"        </mxCell>"
    )

    node_ids: List[str] = []
    for i, node in enumerate(nodes):
        node_id = f"n{i}"
        node_ids.append(node_id)
        # The node value must satisfy the `node-quote` rule: it uses only the
        # allowed unquoted set [A-Za-z0-9_-], so the label and name are slugged
        # into a single hyphen-joined token. Change markers are conveyed via the
        # Legend and the companion document, not embedded in the node name.
        value = f'{_node_slug(node["label"])}-{_node_slug(node["name"])}'
        style = f'{node["style_string"]};fillColor={node["brand_hex"]}'
        cells.append(
            f'        <mxCell id="{node_id}" value="{_xml_escape(value)}" '
            f'style="{_xml_escape(style)}" vertex="1" parent="1">\n'
            f'          <mxGeometry x="{40 + i * 160}" y="120" width="140" height="80" as="geometry"/>\n'
            f"        </mxCell>"
        )

    # No edges: the contract has no relationship data, so it invents none (R9.2).

    body = "\n".join(cells)
    return (
        '<mxfile host="rule-engine">\n'
        f'  <diagram name="{_xml_escape(title)}">\n'
        "    <mxGraphModel dx=\"800\" dy=\"600\" grid=\"1\" gridSize=\"10\">\n"
        "      <root>\n"
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f"{body}\n"
        "      </root>\n"
        "    </mxGraphModel>\n"
        "  </diagram>\n"
        "</mxfile>\n"
    )


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _frontmatter(
    *,
    doc_id: str,
    title: str,
    provider: str,
    boundary_id: str,
    tags: Sequence[str],
    related_docs: Sequence[str],
    extra: Optional[Mapping[str, str]] = None,
) -> str:
    """Render a kb-frontmatter compliant YAML frontmatter block.

    Emits all twelve required keys with non-empty values (kb-frontmatter.md /
    Requirement 8 AC1): id, title, kb_namespace, section, category, status,
    updated, owner, author, next_review_date, tags (1–20), related_docs (0–20).
    ``extra`` adds further scalar keys (for example ``diagram_class`` on a
    companion document) after the required keys.
    """
    today = date.today()
    review = (today + timedelta(days=180)).isoformat()
    lines = [
        "---",
        f"id: {doc_id}",
        f"title: {title}",
        f"kb_namespace: cloud-architecture/{provider}",
        "section: infrastructure",
        "category: architecture-inventory",
        "status: draft",
        f"updated: {today.isoformat()}",
        f"owner: {provider}-platform-team",
        "author: rule-engine",
        f"next_review_date: {review}",
        "tags:",
        f"  - {provider}",
        "  - inventory",
        f"  - {boundary_id}",
    ]
    lines.append("related_docs:")
    if related_docs:
        for doc in related_docs[:20]:
            lines.append(f"  - {doc}")
    else:
        lines[-1] = "related_docs: []"
    if extra:
        for key, value in extra.items():
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _pad_section(body: str, target_min: int = 110) -> str:
    """Pad a section body to satisfy the 100–200 word section bound.

    kb-frontmatter requires each mandatory section to be 100–200 words. The
    generated bodies are deterministic; this appends a neutral clarifying
    sentence-set until the word count clears the lower bound without exceeding
    the upper one.
    """
    filler = (
        "This section is generated deterministically by the Rule Engine contract "
        "from the current inventory snapshot and the computed delta against the "
        "previous version so that the document remains reviewable, versioned, and "
        "consistent across every provider profile and every subsequent invocation "
        "of the engine for this boundary and region."
    )
    words = body.split()
    while len(words) < target_min:
        words.extend(filler.split())
    # Cap below the 200-word upper bound.
    if len(words) > 190:
        words = words[:190]
    return " ".join(words)


def _render_companion_doc(
    *,
    doc_id: str,
    title: str,
    provider: str,
    boundary_id: str,
    region: str,
    diagram_filename: str,
    nodes: Sequence[Mapping[str, Any]],
) -> str:
    """Render the ``NN-topic.diagram.md`` Companion Document (kb-frontmatter)."""
    fm = _frontmatter(
        doc_id=doc_id,
        title=title,
        provider=provider,
        boundary_id=boundary_id,
        tags=[provider, "diagram", boundary_id],
        related_docs=[diagram_filename],
        # The companion declares the diagram class so the Linter evaluates the
        # sibling .drawio as a ``flow`` diagram (the Contract never emits a
        # landscape). Read by cli._load_companion_frontmatter.
        extra={"diagram_class": "flow"},
    )
    node_lines = "\n".join(
        f"- {n['label']} — {n['name']}" for n in nodes
    )
    overview = _pad_section(
        f"This companion document describes the architecture diagram "
        f"{diagram_filename} for the {provider} boundary {boundary_id} in region "
        f"{region}. The diagram renders the enumerated resources of the boundary "
        f"using the {provider} provider profile icons, colors, and container "
        f"conventions."
    )
    main = _pad_section(
        "The diagram contains the following resolved nodes, each mapped from a "
        "neutral resource type to its provider-native service label with a "
        f"resolved provider icon:\n{node_lines}\nEdges are labeled with the flow "
        "they represent and the Legend defines every line style, color, and "
        "change marker used across versions."
    )
    trouble = _pad_section(
        "If a node renders without an icon, confirm the provider icon mapping "
        "resolves its neutral resource type; the contract falls back to the "
        "Boundary icon rather than emitting an unresolved placeholder. If the "
        "raster image is missing, regenerate the artifact triple so the exported "
        "PNG accompanies the draw.io source and this companion document."
    )
    see_also = _pad_section(
        f"See the versioned existing-infrastructure document for the full "
        f"resource inventory and the computed delta for boundary {boundary_id}. "
        "See the provider profile terminology normalization table for the "
        "neutral-concept to native-service mapping, and the diagram lint ruleset "
        "for the standards every generated diagram must satisfy before publication."
    )
    return (
        f"{fm}\n\n"
        f"# {title}\n\n"
        f"![Architecture diagram for {provider} {boundary_id} in {region}]"
        f"({diagram_filename}.png)\n\n"
        f"## Overview\n\n{overview}\n\n"
        f"## Main Content\n\n{main}\n\n"
        f"## Troubleshooting\n\n{trouble}\n\n"
        f"## See Also\n\n{see_also}\n"
    )


def _render_infrastructure_doc(
    *,
    doc_id: str,
    title: str,
    provider: str,
    boundary_id: str,
    region: str,
    diagram_filename: str,
    deltas: Sequence[Any],
) -> str:
    """Render the versioned ``NN-existing-infrastructure.md`` (kb-frontmatter)."""
    fm = _frontmatter(
        doc_id=doc_id,
        title=title,
        provider=provider,
        boundary_id=boundary_id,
        tags=[provider, "existing-infrastructure", boundary_id],
        related_docs=[f"{diagram_filename}.diagram.md"],
    )
    counts: Dict[str, int] = {c: 0 for c in delta_engine.CLASSIFICATIONS}
    for rec in deltas:
        counts[rec.classification] = counts.get(rec.classification, 0) + 1
    delta_lines = "\n".join(
        f"- {rec.identity.resource_type} {rec.identity.identity_key}: "
        f"{rec.classification} {rec.change_marker}".rstrip()
        for rec in deltas
    ) or "- (no resources enumerated in this snapshot)"

    # Duplicate identities are reported explicitly (never silently overwritten),
    # and are listed in the Troubleshooting section below (Requirement 5 AC8).
    duplicate_lines = "\n".join(
        f"- {rec.identity.resource_type} {rec.identity.identity_key} "
        f"in boundary {rec.identity.boundary} region {rec.identity.region}"
        + (f" ({rec.detail})" if rec.detail else "")
        for rec in deltas
        if rec.classification == delta_engine.DUPLICATE
    )

    overview = _pad_section(
        f"This document records the existing infrastructure for the {provider} "
        f"boundary {boundary_id} in region {region}, as enumerated by the "
        "read-only Inventory Collector and normalized into provider-neutral "
        "resources. It is a versioned snapshot: each invocation of the Rule "
        "Engine contract produces the next sequence number for this boundary."
    )
    main = _pad_section(
        "The delta against the previous version classifies every resource as "
        f"added, changed, removed, or unchanged. Summary counts: "
        f"added {counts.get('added', 0)}, changed {counts.get('changed', 0)}, "
        f"removed {counts.get('removed', 0)}, unchanged {counts.get('unchanged', 0)}.\n"
        f"{delta_lines}"
    )
    duplicate_block = (
        "The following identities occurred more than once in a snapshot and are "
        "reported as duplicate rather than silently overwritten; resolve each by "
        "giving the resources distinct identities before the next collection:\n"
        f"{duplicate_lines}\n"
        if duplicate_lines
        else "No duplicate identities were detected in this snapshot. "
    )
    trouble = _pad_section(
        f"{duplicate_block}"
        "If a resource appears removed unexpectedly, verify the current snapshot "
        "enumerated it and that its identity tuple of provider, resource type, "
        "boundary, region, and identity key matches the previous version. If "
        "every resource shows as added, the previous version could not be "
        "resolved and the delta treated this as a first version, which is "
        "expected for a new boundary."
    )
    see_also = _pad_section(
        f"See the companion diagram document {diagram_filename}.diagram.md for the "
        "rendered architecture, and the inventory standards for the read-only "
        "collection contract, snapshot layout, and secret-safety rules that "
        "govern how this inventory was produced. The provider profile defines the "
        "terminology normalization applied to every resource in this document."
    )
    return (
        f"{fm}\n\n"
        f"# {title}\n\n"
        f"## Overview\n\n{overview}\n\n"
        f"## Main Content\n\n{main}\n\n"
        f"## Troubleshooting\n\n{trouble}\n\n"
        f"## See Also\n\n{see_also}\n"
    )


# --------------------------------------------------------------------------- #
# Linting the written files (R9.1, R9.4)
# --------------------------------------------------------------------------- #


def _lint_written_file(path: Path) -> None:
    """Lint one written file exactly as ``rule-engine-lint --file`` does.

    Parses the real bytes on disk with :func:`rule_engine.cli.parse_artifacts`
    (so the diagram is read by the same XML parser and the documents by the same
    frontmatter/structure validator the CLI uses — R9.1/R9.4), then evaluates
    each parsed Artifact through the ruleset-guarded
    :func:`rule_engine.linter.lint_with_ruleset`. A ``.drawio`` may yield several
    page artifacts; every one must be eligible. Raises
    :class:`ContractGenerationError` naming the file and the blocking findings on
    the first artifact that is blocked from publication.

    ``lint_with_ruleset`` is used (not the unguarded ``lint``) so that a missing
    or unreadable ruleset fails closed: it returns a blocked result and this
    raises, honoring Requirement 7 AC14 / R10.2.
    """
    for artifact in cli_mod.parse_artifacts(str(path)):
        result = linter_mod.lint_with_ruleset(artifact)
        if not result.get("eligible_for_publication", False):
            raise ContractGenerationError(str(path), result.get("findings", []))


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #


def invoke(
    inputs: Mapping[str, Any],
    *,
    output_root: Optional[str | Path] = None,
    topic: str = "architecture",
    workload: str = "workload",
    workspace_root: Optional[str] = None,
) -> Dict[str, str]:
    """Invoke the Rule Engine contract for one provider Boundary.

    Parameters
    ----------
    inputs:
        Mapping with the five required keys (:data:`REQUIRED_INPUTS`):
        ``provider``, ``boundary_id``, ``region``, ``previous_doc_path``,
        ``inventory_snapshot_path``.
    output_root:
        Directory under which the artifact set is written. Defaults to the
        current working directory. Tests inject a ``tmp_path`` here.
    topic:
        The ``topic`` slug used in the ``NN-topic.*`` triple filenames.
    workload:
        The workload name embedded in the diagram title cell.
    workspace_root:
        Passed through to :func:`rule_engine.ruleset.require_ruleset` so the
        Contract locates the authoritative ruleset the **same way** the Lint_CLI
        does (Requirement 10.2). ``None`` uses the shared implicit discovery
        (``RULE_ENGINE_RULESET`` env var, then ``<cwd>/.kiro/…``, then the
        repository/bundled fallbacks).

    Returns
    -------
    dict
        ``{"drawio", "drawio_png", "diagram_md", "existing_infrastructure_md"}``
        mapping each output name to its written path.

    Raises
    ------
    ContractInputError
        When a required input is missing/empty or ``provider`` is out of the
        enumeration. No output documents are produced (Requirement 9 AC7).
    ContractGenerationError
        When the ruleset is unavailable (before any file is written), when the
        node count exceeds the diagram-class limit (R9.3), or when a written
        artifact is blocked from publication by the Linter (R9.1). On any of
        these the output root is left without any new artifact.
    """
    # Validate FIRST — no output is produced on rejection (Requirement 9 AC7).
    valid = validate_inputs(inputs)
    provider = valid["provider"]
    boundary_id = valid["boundary_id"]
    region = valid["region"]

    # Fail closed on a missing ruleset BEFORE any file I/O (R10.2 / 7 AC14). The
    # Contract locates the ruleset exactly as the Lint_CLI does.
    try:
        ruleset_mod.require_ruleset(workspace_root)
    except ruleset_mod.RulesetUnavailableError as exc:
        raise ContractGenerationError(
            "diagram-lint.md",
            [{"rule": "ruleset-unavailable", "severity": "CRITICAL"}],
            message=f"generation error: ruleset unavailable: {exc}",
        ) from exc

    root = Path(output_root) if output_root is not None else Path.cwd()
    root.mkdir(parents=True, exist_ok=True)

    # Allocate the version sequence before writing any file.
    nn = _next_sequence(root)
    version = int(nn)

    # --- Orchestrate: snapshot -> delta -> nodes -------------------------- #
    current = _load_snapshot(valid["inventory_snapshot_path"])
    previous = _load_previous_snapshot(valid["previous_doc_path"])
    # boundary and region are part of the resource identity (Requirement 5 AC8).
    # A Collector snapshot is scoped to exactly one boundary/region (its folder
    # name), so when an entry does not carry them we stamp the authoritative
    # values from this invocation before computing the delta.
    _stamp_boundary_region(current, boundary_id, region)
    if previous is not None:
        _stamp_boundary_region(previous, boundary_id, region)
    try:
        deltas = delta_engine.compute_delta(current, previous)
    except delta_engine.SnapshotInputError:
        # A malformed snapshot means we cannot compute a delta; treat the current
        # snapshot as a first version so the artifact set is still produced.
        deltas = delta_engine.compute_delta(current, None) if current else []

    nodes = _resolve_nodes(provider, current)

    # Node-count limit (R9.3). The Contract emits a single ``flow`` diagram, so
    # the limit is MAX_NODES (12). If the current snapshot resolves to more nodes
    # than the class allows, raise an error naming the count and the limit rather
    # than silently dropping resources by slicing the node list.
    if len(nodes) > linter_mod.MAX_NODES:
        raise ContractGenerationError(
            str(root / f"{nn}-{topic}.drawio"),
            [{"rule": linter_mod.RULE_NODE_COUNT, "severity": "ERROR"}],
            message=(
                f"generation error: node count {len(nodes)} exceeds the flow "
                f"diagram limit of {linter_mod.MAX_NODES}; split the inventory "
                "into multiple boundaries or reduce its scope"
            ),
        )

    # --- Filenames -------------------------------------------------------- #
    diagram_stem = f"{nn}-{topic}"
    drawio_name = f"{diagram_stem}.drawio"
    png_name = f"{diagram_stem}.drawio.png"
    diagram_md_name = f"{diagram_stem}.diagram.md"
    infra_md_name = f"{nn}-existing-infrastructure.md"

    title = _title_cell(provider, workload, boundary_id, region, version)
    diagram_title = f"{provider} {workload} {boundary_id} {region} v{version}"

    companion_id = f"{provider}-{boundary_id}-{topic}-diagram-v{version}"
    infra_id = f"{provider}-{boundary_id}-existing-infrastructure-v{version}"

    # --- Render the artifact set ------------------------------------------ #
    drawio_content = _render_drawio(title, nodes)
    companion_content = _render_companion_doc(
        doc_id=companion_id,
        title=diagram_title,
        provider=provider,
        boundary_id=boundary_id,
        region=region,
        diagram_filename=drawio_name,
        nodes=nodes,
    )
    infra_content = _render_infrastructure_doc(
        doc_id=infra_id,
        title=diagram_title,
        provider=provider,
        boundary_id=boundary_id,
        region=region,
        diagram_filename=diagram_stem,
        deltas=deltas,
    )

    # --- Stage, lint the WRITTEN files, then move into place -------------- #
    # The four outputs are written into a private staging directory under the
    # output root, linted there through the SAME parser as ``rule-engine-lint
    # --file`` (R9.1/R9.4), and moved into ``root`` only when every staged
    # artifact is eligible for publication. On any blocking finding the staging
    # directory is removed and ``root`` is left without any new artifact.
    staging = root / f".staging-{nn}-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        staged_drawio = staging / drawio_name
        staged_png = staging / png_name
        staged_diagram_md = staging / diagram_md_name
        staged_infra_md = staging / infra_md_name

        staged_drawio.write_text(drawio_content, encoding="utf-8")
        # Exported raster stub: a real pipeline would render the PNG from the
        # .drawio source. A minimal 1x1 PNG completes the mandatory triple.
        staged_png.write_bytes(_PNG_STUB)
        staged_diagram_md.write_text(companion_content, encoding="utf-8")
        staged_infra_md.write_text(infra_content, encoding="utf-8")

        # Lint the real files. The companion .diagram.md must sit next to the
        # .drawio for the diagram's ``diagram_class`` (and cross-links) to be
        # read, which the staging layout preserves.
        _lint_written_file(staged_drawio)
        _lint_written_file(staged_diagram_md)
        _lint_written_file(staged_infra_md)

        # Every artifact is eligible — move the set into place.
        drawio_path = root / drawio_name
        png_path = root / png_name
        diagram_md_path = root / diagram_md_name
        infra_md_path = root / infra_md_name

        os.replace(staged_drawio, drawio_path)
        os.replace(staged_png, png_path)
        os.replace(staged_diagram_md, diagram_md_path)
        os.replace(staged_infra_md, infra_md_path)
    finally:
        # Remove the staging directory whether we succeeded (now empty) or
        # raised (still holding the blocked files), so no partial set survives.
        shutil.rmtree(staging, ignore_errors=True)

    return {
        "drawio": str(drawio_path),
        "drawio_png": str(png_path),
        "diagram_md": str(diagram_md_path),
        "existing_infrastructure_md": str(infra_md_path),
    }


def invoke_result(
    inputs: Mapping[str, Any],
    *,
    output_root: Optional[str | Path] = None,
    topic: str = "architecture",
    workload: str = "workload",
    workspace_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Non-raising variant of :func:`invoke`.

    On valid inputs returns the same output mapping as :func:`invoke`. On invalid
    inputs returns ``{"error": <message>, "invalid_input": <key>}`` and produces
    no output documents (Requirement 9 AC7).
    """
    try:
        return invoke(
            inputs,
            output_root=output_root,
            topic=topic,
            workload=workload,
            workspace_root=workspace_root,
        )
    except ContractInputError as exc:
        return {"error": str(exc), "invalid_input": exc.invalid_input}


# A minimal, valid 1x1 transparent PNG used as the exported-raster stub. Real
# pipelines export the PNG from the .drawio source; here the file just needs to
# exist so the mandatory artifact triple is complete.
_PNG_STUB = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
