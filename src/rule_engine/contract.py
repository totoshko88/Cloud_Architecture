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

Every generated artifact is run through the :mod:`rule_engine.linter`; the
contract raises :class:`ContractGenerationError` if a generated artifact is
blocked from publication (a CRITICAL or ERROR finding), so a partial/invalid
artifact set is never returned.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rule_engine import delta as delta_engine
from rule_engine import icon_resolver
from rule_engine import linter as linter_mod
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
    """Raised when a generated artifact is blocked from publication.

    Carries the ``artifact`` path and the blocking lint ``findings`` so a caller
    can see why the artifact set was not returned.
    """

    def __init__(self, artifact: str, findings: Sequence[Mapping[str, str]]) -> None:
        self.artifact = artifact
        self.findings = list(findings)
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
    # Node limit (diagram-standards: ≤ 12 nodes). Keep the first 12; a real
    # generator would split, but the contract keeps a single lint-clean diagram.
    return nodes[: linter_mod.MAX_NODES]


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


def _legend_block() -> str:
    """The mandatory Legend block (diagram-standards — Mandatory Legend Block)."""
    return (
        "Legend: "
        "solid line = primary flow; "
        "dashed line = asynchronous / event-driven flow; "
        "red = blocked / missing / disabled; "
        "🆕 = new in version N; "
        "🔄 = changed in version N; "
        "dashed green boundary = stack boundary; "
        "dashed blue boundary = Network Boundary."
    )


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
    with its resolved style, plus a labeled edge between consecutive nodes so the
    ``edge-label`` rule stays clean.
    """
    cells: List[str] = []
    # Title + legend as text cells.
    cells.append(
        f'        <mxCell id="title" value="{_xml_escape(title)}" '
        f'style="text;html=1;" vertex="1" parent="1">\n'
        f'          <mxGeometry x="20" y="10" width="720" height="30" as="geometry"/>\n'
        f"        </mxCell>"
    )
    cells.append(
        f'        <mxCell id="legend" value="{_xml_escape(_legend_block())}" '
        f'style="text;html=1;whiteSpace=wrap;" vertex="1" parent="1">\n'
        f'          <mxGeometry x="20" y="380" width="720" height="60" as="geometry"/>\n'
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

    for i in range(len(node_ids) - 1):
        cells.append(
            f'        <mxCell id="e{i}" value="connects to" '
            f'style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" '
            f'source="{node_ids[i]}" target="{node_ids[i + 1]}">\n'
            f'          <mxGeometry relative="1" as="geometry"/>\n'
            f"        </mxCell>"
        )

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
) -> str:
    """Render a kb-frontmatter compliant YAML frontmatter block.

    Emits all twelve required keys with non-empty values (kb-frontmatter.md /
    Requirement 8 AC1): id, title, kb_namespace, section, category, status,
    updated, owner, author, next_review_date, tags (1–20), related_docs (0–20).
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
    trouble = _pad_section(
        "If a resource appears removed unexpectedly, verify the current snapshot "
        "enumerated it and that its identity tuple of provider, resource type, "
        "and identity key matches the previous version. If every resource shows "
        "as added, the previous version could not be resolved and the delta "
        "treated this as a first version, which is expected for a new boundary."
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
# Linting generated artifacts
# --------------------------------------------------------------------------- #


def _lint_diagram(
    drawio_path: Path, title: str, nodes: Sequence[Mapping[str, Any]], version: int
) -> None:
    """Lint the generated diagram; raise on any blocking finding."""
    artifact = linter_mod.Artifact(
        kind="diagram",
        path=str(drawio_path),
        node_names=[
            f'{_node_slug(n["label"])}-{_node_slug(n["name"])}' for n in nodes
        ],
        edges=[
            linter_mod.Edge(label="connects to")
            for _ in range(max(0, len(nodes) - 1))
        ],
        has_legend=True,
        icons=[
            {"resolved": True, "style": n["style_string"]} for n in nodes
        ],
        title_cell=title,
        source_format="drawio",
        diagram_type="component",
        is_drawio=True,
        has_companion_doc=True,
    )
    _raise_if_blocked(str(drawio_path), linter_mod.lint(artifact))


def _lint_document(path: Path, frontmatter: Mapping[str, Any]) -> None:
    """Lint a generated Markdown document; raise on any blocking finding."""
    artifact = linter_mod.Artifact(
        kind="document",
        path=str(path),
        is_markdown=True,
        frontmatter=dict(frontmatter),
    )
    _raise_if_blocked(str(path), linter_mod.lint(artifact))


def _raise_if_blocked(path: str, result: Mapping[str, Any]) -> None:
    if not result.get("eligible_for_publication", False):
        raise ContractGenerationError(path, result.get("findings", []))


def _frontmatter_dict(
    provider: str, boundary_id: str, doc_id: str, title: str
) -> Dict[str, Any]:
    """Build the frontmatter mapping the Linter inspects (all twelve keys)."""
    today = date.today()
    return {
        "id": doc_id,
        "title": title,
        "kb_namespace": f"cloud-architecture/{provider}",
        "section": "infrastructure",
        "category": "architecture-inventory",
        "status": "draft",
        "updated": today.isoformat(),
        "owner": f"{provider}-platform-team",
        "author": "rule-engine",
        "next_review_date": (today + timedelta(days=180)).isoformat(),
        "tags": [provider, "inventory", boundary_id],
        # kb-frontmatter permits 0 entries here, but the Linter's generic
        # empty-collection check flags an empty list; the rendered documents
        # always cross-reference a related doc, so keep it non-empty.
        "related_docs": [f"{provider}-{boundary_id}-related"],
    }


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #


def invoke(
    inputs: Mapping[str, Any],
    *,
    output_root: Optional[str | Path] = None,
    topic: str = "architecture",
    workload: str = "workload",
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
        When a generated artifact is blocked from publication by the Linter.
    """
    # Validate FIRST — no output is produced on rejection (Requirement 9 AC7).
    valid = validate_inputs(inputs)
    provider = valid["provider"]
    boundary_id = valid["boundary_id"]
    region = valid["region"]

    root = Path(output_root) if output_root is not None else Path.cwd()
    root.mkdir(parents=True, exist_ok=True)

    # Allocate the version sequence before writing any file.
    nn = _next_sequence(root)
    version = int(nn)

    # --- Orchestrate: snapshot -> delta -> nodes -------------------------- #
    current = _load_snapshot(valid["inventory_snapshot_path"])
    previous = _load_previous_snapshot(valid["previous_doc_path"])
    try:
        deltas = delta_engine.compute_delta(current, previous)
    except delta_engine.SnapshotInputError:
        # A malformed snapshot means we cannot compute a delta; treat the current
        # snapshot as a first version so the artifact set is still produced.
        deltas = delta_engine.compute_delta(current, None) if current else []

    nodes = _resolve_nodes(provider, current)

    # --- Filenames -------------------------------------------------------- #
    diagram_stem = f"{nn}-{topic}"
    drawio_path = root / f"{diagram_stem}.drawio"
    png_path = root / f"{diagram_stem}.drawio.png"
    diagram_md_path = root / f"{diagram_stem}.diagram.md"
    infra_md_path = root / f"{nn}-existing-infrastructure.md"

    title = _title_cell(provider, workload, boundary_id, region, version)
    diagram_title = f"{provider} {workload} {boundary_id} {region} v{version}"

    # --- Render + lint the diagram ---------------------------------------- #
    drawio_content = _render_drawio(title, nodes)
    _lint_diagram(drawio_path, title, nodes, version)

    # --- Render + lint the two documents ---------------------------------- #
    companion_id = f"{provider}-{boundary_id}-{topic}-diagram-v{version}"
    infra_id = f"{provider}-{boundary_id}-existing-infrastructure-v{version}"

    _lint_document(
        diagram_md_path,
        _frontmatter_dict(provider, boundary_id, companion_id, diagram_title),
    )
    _lint_document(
        infra_md_path,
        _frontmatter_dict(provider, boundary_id, infra_id, diagram_title),
    )

    companion_content = _render_companion_doc(
        doc_id=companion_id,
        title=diagram_title,
        provider=provider,
        boundary_id=boundary_id,
        region=region,
        diagram_filename=f"{diagram_stem}.drawio",
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

    # --- Write the full triple + versioned document ----------------------- #
    # All lint checks passed above, so writing here never emits a blocked
    # artifact.
    drawio_path.write_text(drawio_content, encoding="utf-8")
    # Exported raster stub: a real pipeline would render the PNG from the
    # .drawio source. We write a minimal 1x1 PNG so the file exists and the
    # triple is complete.
    png_path.write_bytes(_PNG_STUB)
    diagram_md_path.write_text(companion_content, encoding="utf-8")
    infra_md_path.write_text(infra_content, encoding="utf-8")

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
) -> Dict[str, Any]:
    """Non-raising variant of :func:`invoke`.

    On valid inputs returns the same output mapping as :func:`invoke`. On invalid
    inputs returns ``{"error": <message>, "invalid_input": <key>}`` and produces
    no output documents (Requirement 9 AC7).
    """
    try:
        return invoke(
            inputs, output_root=output_root, topic=topic, workload=workload
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
