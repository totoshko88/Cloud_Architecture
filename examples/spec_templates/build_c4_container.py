#!/usr/bin/env python3
"""E-06 spec template — a C4 **Container** diagram (``diagram_type: c4_container``).

A Container diagram is the next C4 level down from Context: the deployable units
of one system and how a request moves between them. It is a ``flow``-class
diagram and reads left -> right along the request flow
(``diagram-standards.md`` -> *C4 layering & progressive disclosure*).

Runnable, commented template: a coordinate-free
:class:`~rule_engine.layout.model.DiagramSpec` is handed to the public
``layout()`` + ``build_diagram()`` pipeline, which places every node and routes
every edge. The template writes a publication-eligible triple (``.drawio`` +
companion ``.diagram.md``). Run it::

    python examples/spec_templates/build_c4_container.py            # writes a temp triple
    python examples/spec_templates/build_c4_container.py --out c4.drawio

Each node is a neutral C4 box carrying a ``[Container: <tech>]`` stereotype
line, so the diagram reads as C4 containers (no provider icons, no asset pack).
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

# Neutral C4 container box (dashed white, grey stroke). The `[Container: <tech>]`
# stereotype is baked into each node's label below, the C4 Container grammar.
_BOX = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#333333;"
    "fontColor=#333333;fontSize=12;verticalAlign=middle;align=center"
)

# ---------------------------------------------------------------------------
# One system's deployable containers. A browser SPA calls an API application,
# which reads/writes a database and publishes to a message broker consumed by a
# worker. Lanes read left -> right along the request flow.
# ---------------------------------------------------------------------------
_NODES = (
    NodeSpec(id="spa", role="box", lane="actors", region="", slot=0),
    NodeSpec(id="api", role="box", lane="platform", region="", slot=0),
    NodeSpec(id="worker", role="box", lane="workers", region="", slot=0),
    NodeSpec(id="broker", role="box", lane="async", region="", slot=0),
    NodeSpec(id="db", role="box", lane="data", region="", slot=0),
)
_EDGES = (
    EdgeSpec(id="e1", source="spa", target="api", marker="1"),
    EdgeSpec(id="e2", source="api", target="db", marker="2"),
    EdgeSpec(id="e3", source="api", target="broker", marker="3", dashed=True),
    EdgeSpec(id="e4", source="broker", target="worker", marker="4", dashed=True),
)

# The C4 label: name + [Container: tech]. &#10; is a draw.io line break.
_TECH = {
    "spa": "JavaScript, React",
    "api": "Java, Spring Boot",
    "worker": "Python",
    "broker": "RabbitMQ",
    "db": "PostgreSQL",
}
_NAMES = {
    "spa": "Single-Page App",
    "api": "API Application",
    "worker": "Async Worker",
    "broker": "Message Broker",
    "db": "Database",
}
_LABELS = {nid: f"{_NAMES[nid]}&#10;[Container: {_TECH[nid]}]" for nid in _NAMES}
_FLOW = (
    "Flow",
    "1. Single-page app calls the API application",
    "2. API reads and writes the database",
    "3. API publishes an event to the message broker (async)",
    "4. Broker delivers the event to the async worker (async)",
)

SPEC = DiagramSpec(
    diagram_id="c4-container-template",
    diagram_name="c4-container-template",
    axis="left-right",
    nodes=_NODES,
    edges=_EDGES,
    containers=(),  # the single system boundary is implied; no cloud boundary
    flow_lines=_FLOW,
    title="generic c4-container-template — system / global | 2026-01-01 | v1",
    # Hand the engine the FULL rendered labels (name + stereotype) so the
    # right-margin Flow/Legend clears the widest caption line and never lands
    # over a node (legend-placement overlaps-node-*).
    node_labels=tuple((nid, _LABELS[nid].replace("&#10;", "\n")) for nid in _LABELS),
)

_OVERVIEW = (
    "This template produces a C4 Container diagram: the level below Context, "
    "showing the deployable units of a single system and how a request moves "
    "between them. It is a flow-class diagram, so the twelve-node cap applies "
    "and the lanes read from left to right along the request flow. The system "
    "here is a typical web application: a single-page app in the browser, an API "
    "application, an async worker, a message broker, and a relational database. "
    "Each box carries a C4 stereotype line naming its technology, so a reader "
    "sees not only the containers but what each is built with. No box is a cloud "
    "resource, so the diagram draws no account or network boundary and uses "
    "neutral rounded boxes rather than provider icons. A Container diagram "
    "answers how a request flows through the deployable pieces, one level more "
    "concrete than Context and one level more abstract than a component view."
)
_MAIN = (
    "Every node is declared coordinate-free with a lane, a region, and a slot, "
    "and the engine derives each coordinate from those keys, so the template "
    "writes no x or y. The single-page app sits in the actors lane, the API in "
    "the platform-core lane, the worker in the workers lane, the broker in the "
    "asynchronous-messaging lane, and the database in the data lane, which "
    "places them in request order from left to right. Four numbered edges carry "
    "the flow: the app calls the API, the API reads and writes the database, the "
    "API publishes an event to the broker as a dashed asynchronous step, and the "
    "broker delivers that event to the worker, also dashed. The numbered markers "
    "keep edge labels short while the Flow legend on the right describes each "
    "step. To add a container, declare one node and the edges that connect it; "
    "the engine re-flows the layout with no manual coordinate editing required."
)
_TROUBLE = (
    "If the Linter reports a companion-doc error, confirm this template wrote "
    "the matching .diagram.md beside the .drawio; the helper writes both. A "
    "node-label-length warning means a box label is too long; keep the visible "
    "name short and move detail into the stereotype line or a callout, since the "
    "rule counts only the service name, not the C4 Container stereotype. A "
    "node-count error means the diagram exceeds twelve nodes, which is the "
    "signal to drill into a component view for one container rather than crowd "
    "the Container diagram. A canvas-quality warning on a small diagram is "
    "expected and does not block publication. If an edge-label warning appears, "
    "every edge needs a non-empty label, and a numbered marker counts as one, so "
    "keep the numeric markers assigned to each of the four relationships above."
)
_SEE_ALSO = (
    "This template pairs with the Context template, which sits one C4 level up "
    "and names the users and external systems, and with the component template, "
    "which sits one level down and decomposes a single container into its "
    "internal components. The README in this directory maps every diagram_type "
    "to its template and to the relevant steering sections. The C4 layering and "
    "progressive-disclosure guidance, the lane order, and the numbered flow "
    "legend convention are defined in the diagram standards steering document. "
    "The class-aware severities that judge this diagram are defined in the "
    "diagram lint ruleset, and the frontmatter contract this companion satisfies "
    "is in the knowledge-base frontmatter steering rules. For a cloud-resource "
    "diagram with real provider icons and nested boundaries, read the network "
    "template in this directory, which resolves glyphs from the icon mappings."
)

COMPANION = companion_md(
    basename="c4-container-template",
    diagram_type="c4_container",
    diagram_class="flow",
    title="generic c4-container-template",
    overview=_OVERVIEW,
    main=_MAIN,
    trouble=_TROUBLE,
    see_also=_SEE_ALSO,
    tags=("generic", "c4-container", "c4", "spec-template"),
)


def main(argv=None) -> int:
    render = builtin_icon(_BOX)
    return run_template(
        prog="build_c4_container",
        spec=SPEC,
        renderers={n.id: render for n in SPEC.nodes},
        labels=_LABELS,
        companion=COMPANION,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
