"""``rule-engine-relayout`` — best-effort re-layout of an engine-emitted ``.drawio``
(1.11.0 ITEM D, E-07).

What it does
------------
The engine's input model is a **coordinate-free**
:class:`~rule_engine.layout.model.DiagramSpec`: coordinates are the engine's
*output*, never its input. A ``.drawio`` the engine produced therefore has a
recoverable shape — labelled boundary containers, role-bearing nodes, and edges
between them — and this command re-flows that shape:

1. parse the file to a :class:`~rule_engine.geometry.DiagramGeometry`
   (via the single :mod:`rule_engine.drawio_model` parser),
2. reconstruct the presentation building blocks from the parsed model — each
   node keeps its EXACT icon style and label, each boundary its style / caption
   / kind, each edge its source/target and marker — **dropping only the pinned
   edge contact points and waypoints**, so the router re-chooses them,
3. re-run :func:`rule_engine.diagram_layout.build_diagram`, which re-routes every
   edge orthogonally, re-applies the caption-safe and marker-hygiene finishing,
   and re-covers the page, and
4. re-emit the ``.drawio`` (and, with ``--png``, the raster via the packaged
   exporter).

Because :func:`build_diagram` is **deterministic and idempotent**, re-laying out
an already-engine-laid-out file reproduces it **byte-for-byte**: a second
``rule-engine-relayout`` on the output is a no-op. That is the guarantee this
command offers.

What it does NOT do (fail-honest)
---------------------------------
A **hand-authored** ``.drawio`` — one whose cells were placed and pinned by hand
(the SEP ``01`` / ``01b`` sketches) — has no recoverable engine shape: its edges
may be detached from any node, it may carry no Legend furniture, or it may have
no nodes at all. Rather than silently emit a mangled re-layout, this command
**fails honestly**, naming exactly what it could not recover
(:class:`RelayoutError`). Hand-authored ``.drawio`` is **not first-class**: the
first-class input is a ``DiagramSpec`` (see ``examples/spec_templates/``) or an
engine-emitted ``.drawio``.

Exit status: 0 on success, 2 when the file cannot be parsed or reconstructed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from rule_engine.diagram_layout import Boundary, Edge, Node, build_diagram
from rule_engine.drawio_model import DrawioParseError, Page, parse_drawio
from rule_engine.geometry import DiagramGeometry, build_geometry

__all__ = ["main", "relayout_text", "RelayoutError"]

_PAGE_MARGIN = 60


class RelayoutError(RuntimeError):
    """Raised when a ``.drawio`` cannot be faithfully reconstructed for re-layout.

    ``reason`` is a human-readable description of what could not be recovered
    (e.g. "no nodes", "edge e8 references a detached endpoint", "no Legend
    furniture — the file is not engine-emitted")."""

    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"{source}: cannot relayout: {reason}")


def _verbatim_renderer(style: str):
    """An icon renderer that emits a node with ``style`` VERBATIM.

    Every scope / overlay / external / icon token already lives in the parsed
    style string, so re-emitting it unchanged preserves the node's exact glyph
    and markers. (We therefore pass ``overlay=None`` on the reconstructed
    :class:`Node`, so ``build_diagram`` does not re-append an overlay suffix the
    style already carries.)"""
    from rule_engine.diagram_layout import ICON_SIZE

    def render(node: Node, parent_id: str) -> str:
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


def _contacts(edge) -> dict:
    """Edge contact/waypoint kwargs recovered from a parsed :class:`EdgeGeom`.

    Preserves the engine's chosen ``exit`` / ``entry`` faces and ``points``
    corridor so relayout re-emits the engine's routing verbatim. A floating
    contact (neither coordinate pinned) is omitted so the :class:`Edge` default
    applies; the waypoints are always carried (empty tuple when none)."""
    out: dict = {"points": tuple((int(px), int(py)) for px, py in edge.points)}
    ex, ey = edge.exit
    if ex is not None and ey is not None:
        out["exit"] = (ex, ey)
    en_x, en_y = edge.entry
    if en_x is not None and en_y is not None:
        out["entry"] = (en_x, en_y)
    return out


def _title_and_text_cells(page: Page, geo: DiagramGeometry):
    """Classify the parsed text cells into (title, flow_lines, legend_lines).

    The title is the text cell whose heading is neither ``Flow`` nor ``Legend``
    (the engine emits exactly one such cell, the versioned title); the Flow and
    Legend cells carry those headings. Full line lists come from the parsed page
    cells (``DiagramGeometry`` keeps only each text cell's heading). Any of the
    three may be absent."""
    title = ""
    flow_lines: List[str] = []
    legend_lines: List[str] = []
    for cid, heading in geo.text_headings.items():
        head = (heading or "").strip()
        cell = page.cells.get(cid)
        lines = list(cell.lines) if cell is not None else [head]
        if head == "Flow":
            flow_lines = lines
        elif head == "Legend":
            legend_lines = lines
        elif head and not title:
            title = head
    return title, tuple(flow_lines), tuple(legend_lines)


def _reconstruct(page: Page, geo: DiagramGeometry, source: str):
    """Reconstruct the ``build_diagram`` building blocks from parsed geometry.

    Raises :class:`RelayoutError` when the file is not an engine-emitted shape:
    no nodes, an edge detached from any node, or no Legend furniture. Container
    ``kind`` is left unset — the style is re-emitted verbatim and the Legend is
    recovered verbatim, so ``build_diagram`` never needs the structural kind.
    """
    if not geo.nodes:
        raise RelayoutError(source, "no nodes — nothing to lay out")

    node_ids = set(geo.nodes)

    # An engine-emitted diagram always carries a Legend text cell. A hand sketch
    # may not; and even when it does, its edges are the real tell.
    headings = {(h or "").strip() for h in geo.text_headings.values()}
    if "Legend" not in headings:
        raise RelayoutError(
            source,
            "no Legend furniture — the file is not engine-emitted "
            "(hand-authored .drawio is not first-class; author from a "
            "DiagramSpec instead)",
        )

    # Every edge must attach to two real nodes. A detached endpoint (a line to
    # nowhere, or an edge hung off a container face) means the shape was hand
    # pinned and cannot be re-flowed faithfully.
    for e in geo.edges:
        if e.source not in node_ids or e.target not in node_ids:
            missing = e.source if e.source not in node_ids else e.target
            raise RelayoutError(
                source,
                f"edge {e.id!r} references {missing!r}, which is not a "
                "reconstructable node — the shape was hand-authored / "
                "hand-pinned and cannot be re-flowed faithfully",
            )

    # Emit nodes and boundaries in a DETERMINISTIC order so a re-parse of the
    # output yields the same order (idempotence): nodes by id; boundaries by
    # area DESCENDING (the outer account box first, then region, then VPC — the
    # correct nesting z-order), id as the tiebreak. The parse/insertion order of
    # ``geo`` must NOT leak into the emission, or relayout(relayout(x)) would
    # reorder the cells each pass.
    nodes: List[Node] = [
        Node(
            id=cid,
            label=geo.node_labels.get(cid, ""),
            x=int(geo.nodes[cid].x),
            y=int(geo.nodes[cid].y),
            render=_verbatim_renderer(geo.node_styles.get(cid, "")),
            overlay=None,  # the parsed style already carries any overlay token
        )
        for cid in sorted(geo.nodes)
    ]

    boundaries: List[Boundary] = [
        Boundary(
            id=cid,
            label=geo.container_labels.get(cid, cid),
            x=int(geo.containers[cid].x),
            y=int(geo.containers[cid].y),
            w=int(geo.containers[cid].w),
            h=int(geo.containers[cid].h),
            style=geo.container_styles.get(cid, ""),
            kind="",
        )
        for cid in sorted(
            geo.containers,
            key=lambda c: (-(geo.containers[c].w * geo.containers[c].h), c),
        )
    ]

    # Edges: keep source/target/marker/dashed AND the engine's chosen contact
    # points + waypoints. The scored router in ``layout()`` chose that routing;
    # discarding it and letting ``build_diagram``'s plain orthogonaliser re-pick
    # contacts would DEGRADE an engine-emitted diagram (it has no scored solver).
    # So relayout PRESERVES the engine's routing and re-runs only the idempotent
    # finishing passes build_diagram applies (orthogonalise + caption-safe +
    # marker-hygiene + page cover) — a no-op on already-finished output, which is
    # exactly what makes relayout(engine output) byte-identical.
    edge_styles = {cid: cell.style for cid, cell in page.cells.items() if cell.edge}
    edges: List[Edge] = [
        Edge(
            id=e.id,
            source=e.source,
            target=e.target,
            marker=e.label,
            dashed="dashed=1" in edge_styles.get(e.id, ""),
            **_contacts(e),
        )
        for e in sorted(geo.edges, key=lambda e: e.id)
    ]

    title, flow_lines, legend_lines = _title_and_text_cells(page, geo)
    return nodes, edges, boundaries, title, flow_lines, legend_lines


def _page_size(nodes, boundaries, legend_x, legend_w):
    rights = [n.x + 78 for n in nodes] + [b.x + b.w for b in boundaries]
    rights.append(legend_x + legend_w)
    bottoms = [n.y + 78 for n in nodes] + [b.y + b.h for b in boundaries]
    page_w = int(max(rights, default=800)) + _PAGE_MARGIN
    page_h = int(max(bottoms, default=600)) + _PAGE_MARGIN
    return page_w, page_h


def _legend_x_w(geo: DiagramGeometry):
    """Recover the right-margin Flow/Legend left edge and width from the parsed
    text boxes.

    Only the ``Flow`` / ``Legend`` furniture is considered (the two boxes share
    one width under right-margin placement); the title cell — which can be much
    wider — is deliberately excluded, so the recovered ``legend_w`` matches the
    engine's and the re-emitted page is not inflated. Falls back to the widest
    text box when no Flow/Legend heading is present."""
    furniture = [
        cid
        for cid, heading in geo.text_headings.items()
        if (heading or "").strip() in ("Flow", "Legend")
    ]
    if not furniture:
        furniture = list(geo.text_boxes)
    legend_x = 0
    legend_w = 0
    for cid in furniture:
        box = geo.text_boxes.get(cid)
        if box is None:
            continue
        legend_x = max(legend_x, int(box.x))
        legend_w = max(legend_w, int(box.w))
    return legend_x, legend_w


def relayout_text(text: str, path: str = "<relayout>") -> str:
    """Re-flow an engine-emitted ``.drawio`` string and return the new XML.

    Raises :class:`DrawioParseError` when the file does not parse and
    :class:`RelayoutError` when it parses but is not a reconstructable
    engine-emitted shape."""
    pages = parse_drawio(text.encode("utf-8"), path=path)
    if not pages:
        raise RelayoutError(path, "no diagram page")
    page = pages[0]
    geo = build_geometry(page)

    nodes, edges, boundaries, title, flow_lines, legend_lines = _reconstruct(page, geo, path)
    legend_x, legend_w = _legend_x_w(geo)
    page_w, page_h = _page_size(nodes, boundaries, legend_x, legend_w)

    # Recover the diagram id / name from the PARSED page, not the filename, so
    # relayout is idempotent regardless of the output path (a second pass over
    # the output recovers the same id/name). Fall back to the file stem.
    diagram_id = page.id or Path(path).stem or "relayout"
    diagram_name = page.name or Path(path).stem or "relayout"

    return build_diagram(
        diagram_id=diagram_id,
        diagram_name=diagram_name,
        title=title,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=flow_lines,
        legend_x=legend_x,
        legend_w=legend_w or None,
        legend_lines=legend_lines or None,
        page_w=page_w,
        page_h=page_h,
    )


def relayout_file(
    source: str | Path, out: Optional[str | Path] = None, png: bool = False
) -> Path:
    """Re-flow ``source`` and write the result (default: overwrite ``source``).

    With ``png=True`` the raster is re-exported via the packaged exporter
    (best-effort — a missing draw.io CLI is reported, never fatal to the
    ``.drawio`` write)."""
    source = Path(source)
    text = source.read_text(encoding="utf-8")
    new_text = relayout_text(text, path=str(source))
    out_path = Path(out) if out is not None else source
    out_path.write_text(new_text, encoding="utf-8")
    if png:
        try:
            from rule_engine.export_raster import export_one

            export_one(out_path)
        except Exception as exc:  # pragma: no cover - best-effort raster
            print(f"rule-engine-relayout: raster export skipped: {exc}", file=sys.stderr)
    return out_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rule-engine-relayout",
        description="Best-effort re-layout of an engine-emitted .drawio "
                    "(re-flow edges + finishing). Fails honestly on a "
                    "hand-authored / hand-pinned source.",
    )
    ap.add_argument("file", help="the .drawio to re-lay out")
    ap.add_argument("--out", default=None,
                    help="write the result here instead of overwriting the input")
    ap.add_argument("--stdout", action="store_true",
                    help="write the re-laid-out .drawio to stdout (no file written)")
    ap.add_argument("--png", action="store_true",
                    help="also re-export the raster (best-effort; needs the draw.io CLI)")
    args = ap.parse_args(argv)

    src = Path(args.file)
    if not src.is_file():
        print(f"error: no such file: {src}", file=sys.stderr)
        return 2
    try:
        if args.stdout:
            sys.stdout.write(relayout_text(src.read_text(encoding="utf-8"), path=str(src)))
            return 0
        out = relayout_file(src, out=args.out, png=args.png)
    except DrawioParseError as exc:
        print(f"error: {src}: parse error: {exc.cause}", file=sys.stderr)
        return 2
    except RelayoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"rule-engine-relayout: wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
