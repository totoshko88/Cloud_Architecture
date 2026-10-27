#!/usr/bin/env python3
"""E-06 spec template — a C4 **Component** diagram (``diagram_type: component``).

A Component diagram is the level below Container: it decomposes ONE container
into its internal components and how they collaborate. It is a ``flow``-class
diagram and reads left -> right (``diagram-standards.md`` -> *C4 layering &
progressive disclosure*). ``component`` is a descriptive ``diagram_type``; the
linter treats it as a flow class (it is deliberately NOT a ``c4-context`` /
``c4-container`` type, and not a network type).

Runnable, commented template: a coordinate-free
:class:`~rule_engine.layout.model.DiagramSpec` is handed to the public
``layout()`` + ``build_diagram()`` pipeline. The template writes a
publication-eligible triple (``.drawio`` + companion ``.diagram.md``). Run it::

    python examples/spec_templates/build_component.py            # writes a temp triple
    python examples/spec_templates/build_component.py --out cmp.drawio

Each node is a neutral C4 box carrying a ``[Component: <tech>]`` stereotype
line, so the diagram reads as C4 components (no provider icons, no asset pack).
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

# Neutral C4 component box (dashed white, grey stroke). The `[Component: <tech>]`
# stereotype is baked into each node's label below, the C4 Component grammar.
_BOX = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#333333;"
    "fontColor=#333333;fontSize=12;verticalAlign=middle;align=center"
)

# ---------------------------------------------------------------------------
# One container (the API application) decomposed. A controller delegates to a
# service, which uses a repository that talks to a database gateway. Lanes read
# left -> right along the call chain.
# ---------------------------------------------------------------------------
_NODES = (
    NodeSpec(id="controller", role="box", lane="actors", region="", slot=0),
    NodeSpec(id="service", role="box", lane="platform", region="", slot=0),
    NodeSpec(id="repo", role="box", lane="workers", region="", slot=0),
    NodeSpec(id="gateway", role="box", lane="data", region="", slot=0),
)
_EDGES = (
    EdgeSpec(id="e1", source="controller", target="service", marker="1"),
    EdgeSpec(id="e2", source="service", target="repo", marker="2"),
    EdgeSpec(id="e3", source="repo", target="gateway", marker="3"),
)

_TECH = {
    "controller": "Spring MVC",
    "service": "Spring Bean",
    "repo": "Spring Data",
    "gateway": "JDBC",
}
_NAMES = {
    "controller": "Order Controller",
    "service": "Order Service",
    "repo": "Order Repository",
    "gateway": "Database Gateway",
}
_LABELS = {nid: f"{_NAMES[nid]}&#10;[Component: {_TECH[nid]}]" for nid in _NAMES}
_FLOW = (
    "Flow",
    "1. Controller delegates to the order service",
    "2. Service reads and writes through the repository",
    "3. Repository calls the database gateway",
)

SPEC = DiagramSpec(
    diagram_id="component-template",
    diagram_name="component-template",
    axis="left-right",
    nodes=_NODES,
    edges=_EDGES,
    containers=(),  # a single container decomposed; no cloud boundary
    flow_lines=_FLOW,
    title="generic component-template — system / global | 2026-01-01 | v1",
    node_labels=tuple((nid, _NAMES[nid]) for nid in _NAMES),
)

_OVERVIEW = (
    "This template produces a C4 Component diagram: the level below Container, "
    "decomposing a single container into its internal components and how they "
    "collaborate. It is a flow-class diagram, so the twelve-node cap applies and "
    "the lanes read from left to right along the call chain. The container here "
    "is the API application from the Container template, and its components are a "
    "controller, a service, a repository, and a database gateway, each carrying "
    "a C4 stereotype line naming its technology. No component is a cloud "
    "resource, so the diagram draws no account or network boundary and uses "
    "neutral rounded boxes rather than provider icons. A Component diagram is "
    "the most concrete C4 structural level: it answers how one deployable "
    "container is built internally, the detail a reader reaches after following "
    "the Context and Container views down through progressive disclosure here."
)
_MAIN = (
    "Every node declares a lane, a region, and a slot, and the engine derives "
    "each coordinate from those keys, so the template writes no x or y. The "
    "controller sits in the actors lane, the service in the platform-core lane, "
    "the repository in the workers lane, and the database gateway in the data "
    "lane, which places them in call order from left to right. Three numbered "
    "edges carry the flow: the controller delegates to the service, the service "
    "reads and writes through the repository, and the repository calls the "
    "database gateway. The numbered markers keep each edge label short while the "
    "Flow legend on the right describes the step, as the diagram standards "
    "require. Each box label keeps the short component name visible and moves "
    "the technology into the stereotype line, so the node-label-length rule, "
    "which counts only the name, is satisfied for every component drawn above."
)
_TROUBLE = (
    "If the Linter reports a companion-doc error, confirm this template wrote "
    "the matching .diagram.md beside the .drawio; the helper writes both. A "
    "node-label-length warning means a visible name is too long; keep it short "
    "and move detail into the stereotype line or a callout, since the rule "
    "counts only the component name, not the C4 Component stereotype. A "
    "node-count error means the diagram exceeds twelve components, which is the "
    "signal to decompose a different container in its own diagram rather than "
    "crowd this one. A canvas-quality warning on a small diagram is expected and "
    "does not block publication. If an edge-label warning appears, every edge "
    "needs a non-empty label, and a numbered marker counts as one, so keep the "
    "numeric markers assigned to each of the three relationships drawn above."
)
_SEE_ALSO = (
    "This template pairs with the Container template, which sits one C4 level up "
    "and shows the deployable containers of the whole system, and with the "
    "Context template two levels up, which names the users and external systems. "
    "The README in this directory maps every diagram_type to its template and to "
    "the relevant steering sections. The C4 layering and progressive-disclosure "
    "guidance, the lane order, and the numbered flow legend convention are "
    "defined in the diagram standards steering document. The class-aware "
    "severities that judge this diagram are defined in the diagram lint ruleset, "
    "and the frontmatter contract this companion satisfies is in the "
    "knowledge-base frontmatter steering rules. For a cloud-resource diagram "
    "with real provider icons and nested boundaries, read the network template, "
    "which resolves official glyphs from the committed icon mappings instead."
)

COMPANION = companion_md(
    basename="component-template",
    diagram_type="component",
    diagram_class="flow",
    title="generic component-template",
    overview=_OVERVIEW,
    main=_MAIN,
    trouble=_TROUBLE,
    see_also=_SEE_ALSO,
    tags=("generic", "component", "c4", "spec-template"),
)


def main(argv=None) -> int:
    render = builtin_icon(_BOX)
    return run_template(
        prog="build_component",
        spec=SPEC,
        renderers={n.id: render for n in SPEC.nodes},
        labels=_LABELS,
        companion=COMPANION,
        argv=argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
