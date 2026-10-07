"""``rule-engine-draw`` — the Snapshot → diagram autogenerator command (Part J, J6).

This is the **command front-end** of the ``rule-engine-draw`` autogenerator
(release 1.10.0, ``.kiro/specs/provider-diagram-conventions``, Requirement 10,
closing ``docs/REVIEW.md`` gap **G8**). The translator half lives in
:mod:`rule_engine.draw` (task 7): it turns a committed inventory Snapshot into
the coordinate-free :class:`~rule_engine.layout.model.DiagramSpec`. This module
is task 8 (design J1/J6): it

1. builds that spec via :func:`rule_engine.draw.spec_from_snapshot`,
2. hands it to the *existing* ``layout()`` + ``build_diagram()`` pipeline for the
   ``.drawio`` — no new geometry, no new solver,
3. skins each node/container through the authoritative
   ``mappings/<provider>-icons.yaml`` (via :mod:`rule_engine.icon_resolver`), so
   a role → icon is resolved from committed data, never hand-written,
4. writes a companion ``.diagram.md`` with the required twelve frontmatter keys
   (``kb-frontmatter.md``) plus the ``diagram_class`` — and the
   ``summary_of`` / ``detailed_view`` cross-link for a ``summary`` / ``landscape``
   pair — so the triple is complete and a ``landscape`` is never
   ``orphan-landscape`` (Requirement 10.8), and
5. **best-effort** exports the raster via the existing exporter; a missing
   draw.io CLI is not fatal — the ``.drawio`` and the companion are always
   written, and the raster (task 9's full gate run) can be produced later.

Everything the command does is **deterministic and offline** (Decision D5,
Requirement 10.6): the spec is a stable-sort function of the Snapshot, the skin
is read from committed mappings, and the companion carries a fixed date/owner
rather than the wall clock, so two runs produce byte-identical ``.drawio`` and
``.diagram.md``.

The three user-facing diagram types map onto the two lint classes
(``diagram-standards.md`` → "Choosing the diagram type after inventory"):
``simple`` / ``summary`` are ``diagram_class: flow``; ``landscape`` is
``diagram_class: landscape``. A ``summary`` names its ``detailed_view`` (the
paired landscape basename) and a ``landscape`` names its ``summary_of`` (the
paired summary basename) so the sanctioned pair cross-links both ways.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rule_engine.constants import PROVIDERS
from rule_engine.diagram_layout import (
    Boundary,
    Edge,
    ICON_SIZE,
    Node,
    CONTAINER_PAD,
    _LABEL_STYLE,
    build_diagram,
    overlay_suffix,
)
from rule_engine.draw import DrawError, SnapshotSplitRequired, spec_from_snapshot
from rule_engine.icon_resolver import (
    IconResolverError,
    UnresolvedTypeError,
    resolve_container,
    resolve_icon,
)

try:  # package-relative when used as ``rule_engine.layout``
    from rule_engine.layout import PlacedDiagram, layout
except ImportError:  # pragma: no cover - flat-module fallback
    from layout import PlacedDiagram, layout  # type: ignore[no-redef]


__all__ = ["main", "generate"]


# Page margin past the rightmost/bottommost placed geometry (and past the
# right-margin Flow/Legend column), so the canvas fits with a small border —
# the same value the shipped HA generator uses.
_PAGE_MARGIN = 2 * CONTAINER_PAD  # 60, a whole grid multiple

#: The three user-facing diagram types → the lint ``diagram_class`` they carry.
_CLASS_OF = {"simple": "flow", "summary": "flow", "landscape": "landscape"}

#: A fixed date used for the companion frontmatter dates and the title, so the
#: generated triple is byte-identical across runs (Requirement 10.6 — no
#: wall-clock). Callers who want a real date edit the companion afterwards.
_STABLE_DATE = "2026-01-01"
_STABLE_NEXT_REVIEW = "2026-07-01"


# --------------------------------------------------------------------------- #
# Skin — role → icon and kind → container style, from the committed mappings.
# --------------------------------------------------------------------------- #


def _node_renderer(style_string: str):
    """Return an icon renderer that emits ``style_string`` verbatim.

    ``style_string`` is the authoritative draw.io style for the role, read from
    ``mappings/<provider>-icons.yaml`` via :func:`icon_resolver.resolve_icon`; it
    already carries the label / font tokens, so — unlike
    :func:`diagram_layout.builtin_icon` — this renderer does **not** re-append
    ``_LABEL_STYLE`` (that would duplicate the label tokens). The overlay suffix
    is appended so an overlay-marked node keeps its dashed outline + token.
    """

    def render(node: Node, parent_id: str) -> str:
        style = f"{style_string}{overlay_suffix(node)}"
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


def _label_of(node_spec) -> str:
    """A short, quote-free display label for a node (its slugged node id).

    ``NodeSpec.id`` is already the slug of the resource identity
    (``[a-z0-9_-]`` only), so it is a safe draw.io label. The node-label-length
    rule caps a service label at 4 words / 40 chars; a slug has no spaces and is
    truncated defensively so a very long arn-derived id does not trip it.
    """
    label = node_spec.id
    if len(label) > 40:
        label = label[:40].rstrip("-")
    return label


def _skin_renderers(provider: str, roles: Sequence[str]) -> Dict[str, Any]:
    """Resolve one icon renderer per distinct ``role`` used, via the mappings.

    Raises :class:`DrawError` (naming the role) when the provider's mapping has
    no resolved icon for a role — fail-honest rather than draw a look-alike
    (Icon Fidelity). Each style comes from the committed
    ``mappings/<provider>-icons.yaml``, so the resolution is offline.
    """
    renderers: Dict[str, Any] = {}
    for role in sorted(set(roles)):
        if role in renderers:
            continue
        try:
            resolved = resolve_icon(role, provider)
        except IconResolverError as exc:
            raise DrawError(
                f"no icon for role {role!r} under provider {provider!r}: {exc}"
            ) from exc
        renderers[role] = _node_renderer(resolved["style_string"])
    return renderers


def _container_style(kind: str, provider: str) -> str:
    """Resolve the draw.io style for a container ``kind`` (account/vpc/az).

    The structural kinds map onto the profile's container conventions:
    an ``account`` boundary is the profile's ``boundary`` container style; a
    ``vpc`` is the ``network_boundary`` style; an ``az`` uses a level-specific
    style (``availability_domain``) WHEN the profile declares one — this is how
    the OCI profile expresses the official v24.2 nested palette (Compartment ⊃
    Region/VCN ⊃ Availability Domain), each level with its own fill/stroke.

    Providers that declare only the two canonical kinds (aws/azure/gcp/generic)
    have no ``availability_domain`` entry, so ``az`` FALLS BACK to
    ``network_boundary`` — their behaviour is unchanged. Read from
    ``mappings/<provider>-icons.yaml`` via :func:`icon_resolver.resolve_container`,
    so it is offline and authoritative.
    """
    if kind == "account":
        preferred = ("boundary",)
    elif kind == "az":
        # Level-specific first, then the generic network boundary fallback.
        preferred = ("availability_domain", "network_boundary")
    elif kind == "region":
        preferred = ("region", "network_boundary")
    else:  # vpc / anything else structural
        preferred = ("network_boundary",)

    last_exc: Optional[Exception] = None
    for map_kind in preferred:
        try:
            return resolve_container(map_kind, provider)["style_string"]
        except UnresolvedTypeError as exc:
            # Only an ABSENT kind falls back; a declared-but-malformed entry
            # (AssetSourceError) is a profile defect and must surface.
            last_exc = exc
            continue
        except IconResolverError as exc:
            raise DrawError(
                f"no container style for kind {kind!r} under provider "
                f"{provider!r}: {exc}"
            ) from exc
    raise DrawError(
        f"no container style for kind {kind!r} under provider {provider!r}: "
        f"{last_exc}"
    ) from last_exc


# --------------------------------------------------------------------------- #
# Placed geometry → build_diagram building blocks (mirrors the HA generator).
# --------------------------------------------------------------------------- #


def _nodes_from(placed: PlacedDiagram, renderers: Dict[str, Any]) -> List[Node]:
    role_of = {n.id: n.role for n in placed.spec.nodes}
    overlay_of = {n.id: getattr(n, "overlay", None) for n in placed.spec.nodes}
    label_of = {n.id: _label_of(n) for n in placed.spec.nodes}
    return [
        Node(
            id=n.id,
            label=label_of[n.id],
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=renderers[role_of[n.id]],
            overlay=overlay_of[n.id],
        )
        for n in placed.spec.nodes
        if n.id in placed.nodes
    ]


def _boundaries_from(
    placed: PlacedDiagram, provider: str, labels: Mapping[str, str]
) -> List[Boundary]:
    kind_of = {c.id: c.kind for c in placed.spec.containers}
    out: List[Boundary] = []
    for c in placed.spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        out.append(
            Boundary(
                id=c.id,
                label=labels.get(c.id, c.id),
                x=int(box.x),
                y=int(box.y),
                w=int(box.w),
                h=int(box.h),
                style=_container_style(kind_of[c.id], provider),
                kind=kind_of[c.id],
            )
        )
    return out


def _edges_from(placed: PlacedDiagram) -> List[Edge]:
    return [
        Edge(
            id=pe.spec.id,
            source=pe.spec.source,
            target=pe.spec.target,
            marker=pe.spec.marker,
            dashed=pe.spec.dashed,
            exit=pe.exit,
            entry=pe.entry,
            points=tuple((int(x), int(y)) for x, y in pe.points),
        )
        for pe in placed.edges
    ]


def _page_size(placed: PlacedDiagram) -> "tuple[int, int]":
    rights = [b.x + b.w for b in placed.containers.values()]
    rights += [b.x + b.w for b in placed.nodes.values()]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [b.y + b.h for b in placed.containers.values()]
    bottoms += [b.y + b.h for b in placed.nodes.values()]
    page_w = int(max(rights, default=800)) + _PAGE_MARGIN
    page_h = int(max(bottoms, default=600)) + _PAGE_MARGIN
    return page_w, page_h


# --------------------------------------------------------------------------- #
# .drawio + companion assembly
# --------------------------------------------------------------------------- #


def _account_label(provider: str, boundary_id: str) -> str:
    """A human-readable account/boundary label for the single account container."""
    return f"{provider} {boundary_id}"


def build_drawio(
    snapshot_dir: Any,
    provider: str,
    diagram_type: str,
    basename: str,
    relationships: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    """Build the ``.drawio`` text for a Snapshot (spec → layout → build_diagram).

    Deterministic and offline: the spec is a stable-sort function of the
    Snapshot, the skin is read from committed mappings, and the title carries a
    fixed date. Raises :class:`DrawError` / :class:`SnapshotSplitRequired` from
    the translator (an over-budget landscape emits no diagram).
    """
    spec = spec_from_snapshot(snapshot_dir, provider, diagram_type, relationships)
    # 1.10.7: hand the engine the labels this skin will draw, so the Flow/Legend
    # clears a long slug caption that overhangs the rightmost icon.
    spec = dataclasses.replace(
        spec, node_labels=tuple((n.id, _label_of(n)) for n in spec.nodes)
    )
    placed = layout(spec)
    # 1.10.7: a layout the repair loop could not make oracle-clean is returned
    # degraded rather than raised; say so (the exit code is unchanged — the
    # linter is the publication gate and reports the same defects).
    for warning in placed.layout_warnings:
        print(f"rule-engine-draw: layout WARNING: {warning}", file=sys.stderr)

    renderers = _skin_renderers(provider, [n.role for n in spec.nodes])
    nodes = _nodes_from(placed, renderers)
    edges = _edges_from(placed)

    # Container labels: the single account boundary the translator emits.
    boundary_id, region = _read_boundary_region(spec)
    labels = {"boundary-account": _account_label(provider, boundary_id)}
    boundaries = _boundaries_from(placed, provider, labels)

    page_w, page_h = _page_size(placed)
    title = f"{provider} {diagram_type} — {boundary_id} / {region} | {_STABLE_DATE} | v1"

    return build_diagram(
        diagram_id=f"{provider}-{diagram_type}",
        diagram_name=basename,
        title=title,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=spec.flow_lines,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        # No explicit legend_lines: build_diagram names only the boundary kinds
        # actually drawn (legend_lines_for, 1.10.7) — an account-only diagram
        # carries no inner-boundary line.
        page_w=page_w,
        page_h=page_h,
    )


def _read_boundary_region(spec) -> "tuple[str, str]":
    """Recover the (boundary_id, region) the translator baked into the title.

    ``spec.title`` is ``"<provider> <type> — <boundary> / <region>"`` (draw.py),
    so parse it back rather than re-reading the manifest — keeps this front-end
    a pure function of the spec the translator produced.
    """
    title = spec.title
    boundary_id, region = "boundary", "region"
    if "—" in title and "/" in title:
        after = title.split("—", 1)[1]
        left, _, right = after.partition("/")
        boundary_id = left.strip() or boundary_id
        region = right.strip() or region
    return boundary_id, region


def _companion_frontmatter(
    basename: str,
    provider: str,
    diagram_type: str,
    paired_basename: Optional[str],
) -> Dict[str, Any]:
    """Assemble the twelve required frontmatter keys plus the class cross-links.

    ``kb-frontmatter.md`` requires all twelve keys with non-empty values,
    ``status`` an enum, the two dates ISO-8601, ``tags`` 1–20 entries, and
    ``related_docs`` 0–20. ``diagram_class`` and the pairing key
    (``summary_of`` for a landscape, ``detailed_view`` for a summary) are added
    so the triple is complete and a landscape is not ``orphan-landscape``.
    """
    diagram_class = _CLASS_OF[diagram_type]
    # Deduplicate the tag list deterministically (diagram_type and diagram_class
    # coincide for a landscape) — tags must be 1–20 non-empty entries.
    tags: List[str] = []
    for tag in (provider, diagram_type, diagram_class, "autogenerated"):
        if tag not in tags:
            tags.append(tag)
    fm: Dict[str, Any] = {
        "id": f"{basename}-v1",
        "title": f"{provider} {diagram_type} — autogenerated",
        "kb_namespace": "cloud-architecture",
        "section": "generated-diagrams",
        "category": "diagram",
        "status": "draft",
        "updated": _STABLE_DATE,
        "owner": "platform-engineering",
        "author": "rule-engine-draw",
        "next_review_date": _STABLE_NEXT_REVIEW,
        "diagram_class": diagram_class,
        "tags": tags,
        "related_docs": [],
    }
    # A landscape MUST cross-link a flow summary or it is orphan-landscape (an
    # ERROR). When no explicit pair was given, derive a summary basename so the
    # standalone landscape is still publication-eligible; the reader is pointed
    # at the summary the operator is expected to generate alongside it.
    pair = paired_basename
    if diagram_type == "landscape" and not pair:
        pair = _paired_summary_basename(basename)
    if pair:
        if diagram_type == "landscape":
            fm["summary_of"] = pair
        elif diagram_type == "summary":
            fm["detailed_view"] = pair
        fm["related_docs"] = [f"{pair}.diagram.md"]
    return fm


def _paired_summary_basename(basename: str) -> str:
    """Derive the paired flow-summary basename for a landscape ``basename``.

    Prefers a ``landscape`` → ``summary`` substitution when the token is present;
    otherwise appends ``-summary`` so the cross-link is always a non-empty stem
    distinct from the landscape's own basename.
    """
    if "landscape" in basename:
        return basename.replace("landscape", "summary")
    return f"{basename}-summary"


def _yaml_frontmatter(fm: Mapping[str, Any]) -> str:
    """Render the frontmatter mapping as a deterministic YAML block.

    Hand-rendered (rather than ``yaml.safe_dump``) so key order and list styling
    are fixed across runs and PyYAML versions — the companion must be
    byte-identical for the same inputs (Requirement 10.6).
    """
    lines: List[str] = ["---"]
    # Emit scalar keys first in a fixed order, then the two list keys last, so a
    # cross-link (summary_of / detailed_view) sits with the scalars.
    scalar_order = [
        "id", "title", "kb_namespace", "section", "category", "status",
        "updated", "owner", "author", "next_review_date", "diagram_class",
        "summary_of", "detailed_view",
    ]
    for key in scalar_order:
        if key in fm:
            lines.append(f"{key}: {fm[key]}")
    for key in ("tags", "related_docs"):
        value = fm.get(key, [])
        if value:
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: []")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _companion_body(provider: str, diagram_type: str, basename: str) -> str:
    """The four required sections, each 100–200 words (kb-frontmatter.md)."""
    diagram_class = _CLASS_OF[diagram_type]
    overview = (
        f"This diagram was produced by the rule-engine-draw autogenerator from a "
        f"committed {provider} inventory snapshot. It is a {diagram_type} view, "
        f"which the linter treats as the {diagram_class} class. The autogenerator "
        f"resolves every enumerated resource to one of the sixteen diagram roles "
        f"through the shared role mapper, assigns each node a lane in the fixed "
        f"lane order, and derives the account boundary from the snapshot manifest. "
        f"No coordinate is placed by hand: the coordinate-free specification is "
        f"handed to the existing layout and build pipeline, which places every "
        f"node on the grid, sizes the account boundary with padding, chooses "
        f"contact points, and routes each supplied relationship in its own "
        f"corridor. Because the generator reads only committed snapshot files and "
        f"uses a stable sort, two runs on the same snapshot produce a "
        f"byte-identical drawing. This companion is a first-pass draft: review "
        f"the roles, edit relationships, and promote the status before it is "
        f"published to the knowledge base as a reviewed reference artifact today."
    )
    main = (
        f"Each node carries an official {provider} icon resolved from the "
        f"committed icon mappings, so no look-alike glyph is ever substituted for "
        f"a distinct service. A resource whose type resolves to no diagram role is "
        f"skipped rather than drawn with the wrong icon, and no relationship is "
        f"invented: edges appear only when a relationships file is supplied, so an "
        f"unconnected node surfaces as a node-connectivity warning rather than a "
        f"fabricated dependency. A {diagram_class}-class drawing covers the "
        f"in-scope resources for its type; a landscape draws every role-bearing "
        f"resource on one canvas so the reconcile gate confirms nothing was "
        f"silently dropped. The title cell encodes the provider, workload, "
        f"boundary, region, date, and version. The legend documents the solid and "
        f"dashed line meanings and the boundary conventions, and the numbered flow "
        f"list, when present, describes each ordered step so the edges stay "
        f"readable without long labels crowding the icons on the canvas here."
    )
    trouble = (
        f"If the export step reports that the draw.io command-line tool is "
        f"missing, the drawing and this companion are still written; only the "
        f"raster is skipped, and it can be produced later with the packaged "
        f"exporter. A node-connectivity warning is expected whenever no "
        f"relationships file was supplied, because the autogenerator never "
        f"fabricates an edge; add a relationships file to connect the nodes. An "
        f"orphan-landscape error means the summary cross-link is missing; the "
        f"generator writes it automatically for a paired run, so regenerate the "
        f"pair together. A container-padding finding indicates a node drifted "
        f"against the boundary; regenerate rather than hand-nudge, since the "
        f"layout is deterministic. If a role has no resolved icon for this "
        f"provider, the run fails honestly naming the role instead of drawing a "
        f"placeholder, so add the icon mapping and rebuild the icon index first."
    )
    see_also = (
        f"This artifact is one of the mandatory triple: the drawing source named "
        f"{basename}.drawio, its exported raster, and this companion document. "
        f"For the role-to-lane assignment and the snapshot-to-specification "
        f"translation, see the autogenerator core module and the provider "
        f"diagram conventions specification that introduced it. The class-aware "
        f"severities that judge this drawing are defined in the diagram lint "
        f"ruleset, and the frontmatter contract this document satisfies is in the "
        f"knowledge-base frontmatter steering rules. The fixed lane order, the "
        f"container nesting and padding rules, and the numbered flow legend "
        f"convention are all defined in the diagram standards steering document. "
        f"For the read-only inventory collection that produced the source "
        f"snapshot, and the reconcile gate that confirms this drawing covers it, "
        f"see the inventory standards and the reconciliation gate documentation "
        f"maintained alongside the other packaged rule-engine gates in this repo."
    )
    return (
        f"# {provider} {diagram_type} — autogenerated\n\n"
        f"## Overview\n\n{overview}\n\n"
        f"## Main Content\n\n{main}\n\n"
        f"## Troubleshooting\n\n{trouble}\n\n"
        f"## See Also\n\n{see_also}\n"
    )


def build_companion(
    provider: str,
    diagram_type: str,
    basename: str,
    paired_basename: Optional[str] = None,
) -> str:
    """Build the full companion ``.diagram.md`` text (frontmatter + four sections)."""
    fm = _companion_frontmatter(basename, provider, diagram_type, paired_basename)
    return _yaml_frontmatter(fm) + "\n" + _companion_body(provider, diagram_type, basename)


# --------------------------------------------------------------------------- #
# Relationships input
# --------------------------------------------------------------------------- #


def _load_relationships(path: Path) -> List[Mapping[str, Any]]:
    """Load a JSON or YAML list of ``{source, target, label}`` mappings.

    Raises :class:`DrawError` when the file cannot be read/parsed or is not a
    list of mappings. ``label`` is optional (the translator falls back to a
    numeric marker).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DrawError(f"cannot read relationships file {path}: {exc}") from exc
    data: Any
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001 - surface any parse failure
            raise DrawError(
                f"relationships file {path} is not valid JSON or YAML: {exc}"
            ) from exc
    if not isinstance(data, list) or not all(isinstance(r, Mapping) for r in data):
        raise DrawError(
            f"relationships file {path} must be a list of "
            "{source, target, label} mappings"
        )
    return list(data)


# --------------------------------------------------------------------------- #
# Public generate() + CLI
# --------------------------------------------------------------------------- #


def generate(
    snapshot_dir: Any,
    provider: str,
    diagram_type: str,
    out_basename: Any,
    relationships: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    export: bool = True,
    drawio: str = "drawio",
) -> Dict[str, Any]:
    """Write the ``.drawio`` + companion (+ best-effort raster) for a Snapshot.

    ``out_basename`` is a path stem (a directory + basename): the diagram is
    written to ``<out_basename>.drawio`` and the companion to
    ``<out_basename>.diagram.md``. Returns a dict recording which files were
    written and whether the raster export happened. Raster export is best-effort
    (Requirement 10.9 note): a missing draw.io CLI leaves ``raster=None`` but the
    ``.drawio`` and companion are always written.
    """
    out_basename = Path(out_basename)
    basename = out_basename.name

    drawio_text = build_drawio(
        snapshot_dir, provider, diagram_type, basename, relationships
    )
    companion_text = build_companion(provider, diagram_type, basename)

    out_basename.parent.mkdir(parents=True, exist_ok=True)
    drawio_path = out_basename.with_name(f"{basename}.drawio")
    companion_path = out_basename.with_name(f"{basename}.diagram.md")
    drawio_path.write_text(drawio_text, encoding="utf-8")
    companion_path.write_text(companion_text, encoding="utf-8")

    result: Dict[str, Any] = {
        "drawio": str(drawio_path),
        "companion": str(companion_path),
        "raster": None,
        "raster_error": None,
    }

    if export:
        try:
            from rule_engine.export_raster import export_one

            png = export_one(drawio_path, repo_root=Path.cwd(), drawio=drawio)
            result["raster"] = str(png)
        except Exception as exc:  # noqa: BLE001 - export is best-effort
            # A missing/failed draw.io CLI (or a missing vendor asset) never
            # blocks the .drawio + companion; the raster is task 9's gate run.
            result["raster_error"] = f"{type(exc).__name__}: {exc}"

    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point: ``rule-engine-draw``.

    Usage::

        rule-engine-draw --snapshot inventory-aws-… --provider aws \\
            --type landscape --out examples/aws/10-generated
        rule-engine-draw --snapshot <dir> --provider aws --type summary \\
            --out <stem> --relationships rels.json

    Exit codes:
      0 — the ``.drawio`` and companion were written (raster best-effort).
      2 — a usage / generation error (unknown provider/type, unreadable
          snapshot, an over-budget landscape that must be split, or a role with
          no resolved icon). Nothing partial is published.
    """
    ap = argparse.ArgumentParser(
        prog="rule-engine-draw",
        description="Autogenerate a diagram triple (.drawio + .diagram.md + "
        "best-effort raster) from a committed inventory Snapshot.",
    )
    ap.add_argument("--snapshot", required=True,
                    help="path to the committed inventory-* Snapshot folder")
    ap.add_argument("--provider", required=True, choices=sorted(PROVIDERS),
                    help="provider profile of the Snapshot")
    ap.add_argument("--type", required=True, dest="diagram_type",
                    choices=("simple", "summary", "landscape"),
                    help="diagram type: simple/summary are flow-class, landscape "
                    "is landscape-class")
    ap.add_argument("--out", required=True, dest="out_basename",
                    help="output path stem; writes <out>.drawio and "
                    "<out>.diagram.md")
    ap.add_argument("--relationships", default=None,
                    help="optional JSON/YAML file: a list of "
                    "{source, target, label} edges to draw")
    ap.add_argument("--no-export", action="store_true",
                    help="skip the best-effort raster export (write only the "
                    ".drawio and companion)")
    ap.add_argument("--drawio", default="drawio",
                    help="path to the draw.io CLI for raster export "
                    "(default: 'drawio' on PATH)")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))

    relationships: Optional[List[Mapping[str, Any]]] = None
    if args.relationships:
        try:
            relationships = _load_relationships(Path(args.relationships))
        except DrawError as exc:
            print(f"rule-engine-draw: {exc}", file=sys.stderr)
            return 2

    try:
        result = generate(
            args.snapshot,
            args.provider,
            args.diagram_type,
            args.out_basename,
            relationships,
            export=not args.no_export,
            drawio=args.drawio,
        )
    except SnapshotSplitRequired as exc:
        print(f"rule-engine-draw: {exc}", file=sys.stderr)
        return 2
    except DrawError as exc:
        print(f"rule-engine-draw: {exc}", file=sys.stderr)
        return 2

    print(f"rule-engine-draw: wrote {result['drawio']}")
    print(f"rule-engine-draw: wrote {result['companion']}")
    if result["raster"]:
        print(f"rule-engine-draw: wrote {result['raster']}")
    elif result["raster_error"]:
        print(
            f"rule-engine-draw: raster export skipped ({result['raster_error']})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
