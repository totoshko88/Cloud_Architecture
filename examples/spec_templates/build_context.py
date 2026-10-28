#!/usr/bin/env python3
"""E-06 spec template — a C4 **Context** diagram (``diagram_type: context``).

A Context diagram is the widest single view: who uses the system and what it
talks to. It is a ``flow``-class diagram (``diagram-standards.md`` -> *Choosing
the diagram type after inventory*), so it keeps the <= 12-node cap and reads
left -> right along the primary flow.

This is a **runnable, commented** template: it constructs a coordinate-free
:class:`~rule_engine.layout.model.DiagramSpec`, hands it to the public
``layout()`` + ``build_diagram()`` pipeline, and writes a publication-eligible
triple (``.drawio`` + companion ``.diagram.md``). Coordinates are never
authored -- the engine derives every ``x``/``y`` from the ``(lane, region,
slot)`` keys and the canonical grid. Run it::

    python examples/spec_templates/build_context.py            # writes a temp triple
    python examples/spec_templates/build_context.py --out ctx.drawio

Nodes carry NO provider icon: a Context/C4 diagram uses neutral boxes (the
sanctioned ``external_system`` look), so it reads as C4 boxes, not cloud glyphs,
and needs no fetched asset pack to render.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rule_engine.diagram_layout import builtin_icon  # noqa: E402
from rule_engine.layout.model import (  # noqa: E402
    DiagramSpec,
    EdgeSpec,
    NodeSpec,
)

from _common import companion_md, run_template  # noqa: E402

# A neutral C4 box: a dashed white rounded rectangle with a dark caption. No
# provider icon, so no asset pack is needed and `verify-icon` sees no unresolved
# reference (the box carries no `image=`/`resIcon=` token).
_BOX = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#333333;"
    "fontColor=#333333;fontSize=12;verticalAlign=middle;align=center"
)

# ---------------------------------------------------------------------------
# Coordinate-free declaration. Two actors talk to the system; the system talks
# to one downstream dependency. Lanes read left -> right along the flow:
# actors -> platform core -> data. `region=""` keeps every node at the account
# level (a Context view has no network boundary).
# ---------------------------------------------------------------------------
_NODES = (
    NodeSpec(id="user", role="box", lane="actors", region="", slot=0),
    NodeSpec(id="admin", role="box", lane="actors", region="", slot=1),
    NodeSpec(id="system", role="box", lane="platform", region="", slot=0),
    NodeSpec(id="payments", role="box", lane="data", region="", slot=0),
)
_EDGES = (
    EdgeSpec(id="e1", source="user", target="system", marker="1"),
    EdgeSpec(id="e2", source="admin", target="system", marker="2"),
    EdgeSpec(id="e3", source="system", target="payments", marker="3", dashed=True),
)

_LABELS = {
    "user": "Customer",
    "admin": "Operator",
    "system": "Order System",
    "payments": "Payments Provider",
}
_FLOW = (
    "Flow",
    "1. Customer places an order through the system",
    "2. Operator administers the system",
    "3. System calls the external payments provider (async)",
)

SPEC = DiagramSpec(
    diagram_id="context-template",
    diagram_name="context-template",
    axis="left-right",
    nodes=_NODES,
    edges=_EDGES,
    containers=(),  # a Context diagram draws no cloud boundary
    flow_lines=_FLOW,
    title="generic context-template — system / global | 2026-01-01 | v1",
    node_labels=tuple(_LABELS.items()),
)

_OVERVIEW = (
    "This template produces a C4 Context diagram: the widest single view of a "
    "system, naming who uses it and the external systems it depends on. It is a "
    "flow-class diagram, so the twelve-node cap applies and the lanes read from "
    "left to right along the primary interaction. The two people who interact "
    "with the Order System are a Customer and an Operator; the single external "
    "dependency is a third-party Payments Provider. Nothing here is a cloud "
    "resource, so the diagram draws no account, region, or network boundary and "
    "every node is a neutral rounded box rather than a provider icon. The point "
    "of a Context diagram is to answer, at a glance, what the system is for and "
    "what sits around it, before any container or deployment detail is added in "
    "a more detailed view that this one can later link to for the reader."
)
_MAIN = (
    "Each node is declared coordinate-free with a lane, a region, and a slot; "
    "the engine derives every coordinate from those keys and the canonical grid, "
    "so the template never writes an x or a y. The Customer and the Operator sit "
    "in the actors lane, the Order System in the platform-core lane, and the "
    "Payments Provider in the data lane, which places them left to right in the "
    "order a request travels. Three numbered edges carry the flow: the Customer "
    "places an order, the Operator administers the system, and the system then "
    "calls the external payments provider as an asynchronous, dashed step. The "
    "numbered markers keep each edge label short while the Flow legend on the "
    "right spells out the step, exactly as the diagram standards require. To "
    "extend the diagram, add a node and an edge; the layout re-flows itself "
    "with no manual coordinate work from the author at all."
)
_TROUBLE = (
    "If the Linter reports a companion-doc error, confirm that this template "
    "wrote the matching .diagram.md beside the .drawio; the helper writes both "
    "as one triple. A node-count error means the diagram exceeds twelve nodes, "
    "which is the signal to split a Context view rather than crowd it. A "
    "canvas-quality warning on a very small Context diagram is expected and does "
    "not block publication, because a two or three node diagram is inherently "
    "sparse; add the real actors and dependencies and the warning clears. If a "
    "legend-present error appears, the Flow legend header must be exactly the "
    "word Flow on its first line, which build_diagram adds automatically here. "
    "Should an edge-label warning surface, every edge needs a non-empty label, "
    "and a numbered marker counts as one, so keep the numeric markers that the "
    "template already assigns to each of the three relationships drawn above."
)
_SEE_ALSO = (
    "This template pairs with the other spec templates under this directory: a "
    "C4 Container view, a network topology view, and a component view, each "
    "mapping one diagram_type onto the coordinate-free DiagramSpec and the "
    "shared layout and build pipeline. The README in this directory maps every "
    "diagram_type to its template and to the relevant steering sections. The "
    "lane order, the numbered flow legend convention, and the twelve-node cap "
    "are defined in the diagram standards steering document, under Choosing the "
    "diagram type after inventory and Lane Order. The class-aware severities "
    "that judge this diagram are defined in the diagram lint ruleset, and the "
    "frontmatter contract this companion satisfies is in the knowledge-base "
    "frontmatter steering rules. For a cloud-resource diagram with real icons "
    "and boundaries, read the network template, which resolves provider glyphs."
)

COMPANION = companion_md(
    basename="context-template",
    diagram_type="context",
    diagram_class="flow",
    title="generic context-template",
    overview=_OVERVIEW,
    main=_MAIN,
    trouble=_TROUBLE,
    see_also=_SEE_ALSO,
    tags=("generic", "context", "c4", "spec-template"),
)


def main(argv=None) -> int:
    render = builtin_icon(_BOX)
    return run_template(
        prog="build_context",
        spec=SPEC,
        renderers={n.id: render for n in SPEC.nodes},
        labels=_LABELS,
        companion=COMPANION,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
