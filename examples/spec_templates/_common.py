#!/usr/bin/env python3
"""Shared plumbing for the E-06 DiagramSpec templates (1.11.0 ITEM D).

Each ``build_<type>.py`` template declares a coordinate-free
:class:`~rule_engine.layout.model.DiagramSpec` plus a per-node icon renderer,
and calls :func:`write_triple` here to:

1. lay the spec out with the public ``layout()`` + ``build_diagram()`` pipeline,
2. write the ``.drawio`` source, and
3. write a conforming companion ``.diagram.md`` (the twelve required
   ``kb-frontmatter.md`` keys + the four 100-200-word sections), so the emitted
   triple is **publication-eligible** (zero ERROR / CRITICAL lint findings).

No coordinate is authored anywhere: the engine derives every ``x``/``y`` from
the ``(lane, region, slot)`` keys and the canonical grid. This file is a
template helper, not engine code — it imports only the public engine surface.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from rule_engine.diagram_layout import (
    Boundary,
    Edge,
    Node,
    build_diagram,
)
from rule_engine.layout import layout
from rule_engine.layout.model import DiagramSpec

_PAGE_MARGIN = 60

IconRenderer = Callable[[Node, str], str]


def build_drawio(
    spec: DiagramSpec,
    renderers: Mapping[str, IconRenderer],
    labels: Mapping[str, str],
    container_labels: Optional[Mapping[str, str]] = None,
    container_styles: Optional[Mapping[str, str]] = None,
    kind_of: Optional[Mapping[str, str]] = None,
    legend_lines: Optional[Sequence[str]] = None,
) -> str:
    """Lay ``spec`` out and serialize the full ``.drawio`` XML.

    ``renderers`` / ``labels`` are keyed by node id; ``container_labels`` /
    ``container_styles`` / ``kind_of`` by container id. The geometry is the
    engine's output — this only maps the placed boxes onto the template's icons,
    labels and container styles.
    """
    import dataclasses

    container_labels = dict(container_labels or {})
    container_styles = dict(container_styles or {})
    kind_of = dict(kind_of or {c.id: c.kind for c in spec.containers})

    # Present the real captions/styles to the oracle so the layout is scored
    # against the captions the linter will see (1.10.6).
    presented = dataclasses.replace(
        spec,
        container_captions=tuple(sorted(container_labels.items())),
        container_styles=tuple(sorted(container_styles.items())),
    )
    placed = layout(presented, strict=True)

    nodes: List[Node] = [
        Node(
            id=n.id,
            label=labels[n.id],
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=renderers[n.id],
        )
        for n in spec.nodes
        if n.id in placed.nodes
    ]
    edges: List[Edge] = [
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
    boundaries: List[Boundary] = []
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        boundaries.append(
            Boundary(
                id=c.id,
                label=container_labels.get(c.id, c.id),
                x=int(box.x),
                y=int(box.y),
                w=int(box.w),
                h=int(box.h),
                style=container_styles[c.id],
                kind=kind_of[c.id],
            )
        )

    rights = [int(b.x + b.w) for b in placed.nodes.values()]
    rights += [int(b.x + b.w) for b in placed.containers.values()]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [int(b.y + b.h) for b in placed.nodes.values()]
    bottoms += [int(b.y + b.h) for b in placed.containers.values()]
    page_w = max(rights) + _PAGE_MARGIN
    page_h = max(bottoms) + _PAGE_MARGIN

    return build_diagram(
        diagram_id=spec.diagram_id,
        diagram_name=spec.diagram_name,
        title=spec.title,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=spec.flow_lines,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        legend_lines=legend_lines,
        page_w=page_w,
        page_h=page_h,
    )


def companion_md(
    basename: str,
    diagram_type: str,
    diagram_class: str,
    title: str,
    overview: str,
    main: str,
    trouble: str,
    see_also: str,
    tags: Sequence[str],
) -> str:
    """Render a conforming companion ``.diagram.md`` (kb-frontmatter.md).

    The twelve required frontmatter keys with non-empty values, the optional
    ``diagram_type`` / ``diagram_class`` keys the taxonomy reads, and the four
    required sections (each the caller sizes to 100-200 words). Dates are fixed
    so a re-run is byte-identical.
    """
    tag_block = "\n".join(f"  - {t}" for t in tags)
    return (
        "---\n"
        f"id: {basename}-v1\n"
        f"title: {title}\n"
        "kb_namespace: cloud-architecture\n"
        "section: spec-templates\n"
        "category: diagram\n"
        "status: draft\n"
        "updated: 2026-01-01\n"
        "owner: platform-engineering\n"
        "author: rule-engine-spec-templates\n"
        "next_review_date: 2026-07-01\n"
        f"diagram_class: {diagram_class}\n"
        f"diagram_type: {diagram_type}\n"
        f"tags:\n{tag_block}\n"
        "related_docs: []\n"
        "---\n"
        f"# {title}\n"
        "## Overview\n"
        f"{overview}\n"
        "## Main Content\n"
        f"{main}\n"
        "## Troubleshooting\n"
        f"{trouble}\n"
        "## See Also\n"
        f"{see_also}\n"
    )


def run_template(
    *,
    prog: str,
    spec: DiagramSpec,
    renderers: Mapping[str, IconRenderer],
    labels: Mapping[str, str],
    container_labels: Optional[Mapping[str, str]] = None,
    container_styles: Optional[Mapping[str, str]] = None,
    legend_lines: Optional[Sequence[str]] = None,
    companion: str = "",
    argv: Optional[Sequence[str]] = None,
) -> int:
    """Shared CLI for every template: ``--out`` / ``--stdout``.

    Writes both the ``.drawio`` and its companion ``.diagram.md`` next to it, so
    the emitted triple is publication-eligible. The default output directory is
    a temp dir, so running the template never writes into the repo tree.
    """
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--out", default=None, help="output .drawio path (default: a temp file)")
    ap.add_argument("--stdout", action="store_true", help="write the .drawio to stdout only")
    args = ap.parse_args(argv)

    xml = build_drawio(
        spec, renderers, labels,
        container_labels=container_labels,
        container_styles=container_styles,
        legend_lines=legend_lines,
    )
    if args.stdout:
        sys.stdout.write(xml)
        return 0
    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / f"{spec.diagram_name}.drawio"
    out.write_text(xml, encoding="utf-8")
    if companion:
        companion_path = Path(str(out)[: -len(".drawio")] + ".diagram.md") if str(out).endswith(".drawio") else out.with_suffix(".diagram.md")
        companion_path.write_text(companion, encoding="utf-8")
    print(f"{prog}: wrote {out} ({len(spec.nodes)} nodes)")
    return 0
