"""Shared, provider-neutral diagram layout builder.

This module is the single source of truth for the **numeric layout geometry** of
every generated architecture diagram, so AWS, Azure, GCP, OCI, and generic
diagrams all share one look: the same icon size, the same label placement, the
same lane grid, the same container padding, and the same orthogonal edge routing
with distinct waypoint corridors.

The canonical values are taken from the AWS golden example
(``examples/aws/01-aws-agent-platform.drawio``), which is the reference diagram
for the standard (see ``.kiro/steering/diagram-standards.md`` → "Layout
Geometry"). Keeping them here — rather than duplicated in each per-provider
generator — means a future provider is added by supplying an *icon renderer*
(how to draw one node's glyph), not by re-deriving the layout.

Two icon-renderer strategies are provided:

- :func:`builtin_icon` — a node whose glyph is a built-in draw.io stencil id
  (e.g. ``mxgraph.aws4.resourceIcon``). One flat cell.
- :func:`image_icon` — a node whose glyph is a file-path image shape
  (``image;...;image=<path under the asset root>.svg``), used by the file-path
  providers (GCP official 2025 icons, Azure azure2). One flat cell.
- :func:`OciStencilIcon` — a node whose glyph is an embedded OCI stencil group
  (OCI ships no built-in draw.io library), with the stencil's baked-in caption
  stripped and the icon scaled square, so it matches the built-in-icon nodes.

Both strategies emit a node that the Linter counts as exactly one top-level node
(nested glyph sub-cells are the node's geometry, per
``rule_engine.cli._parse_drawio``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Canonical layout geometry (AWS reference). Do not fork these per provider.
# ---------------------------------------------------------------------------

#: Square icon footprint in model units. The node's cell is exactly this size so
#: the bottom label hugs the icon (AWS reference uses 78x78).
ICON_SIZE = 78

#: Grid step (matches draw.io ``gridSize``). Spacings are whole multiples of it.
GRID = 10

#: Horizontal distance between adjacent node columns (lanes read left→right).
COL_STEP = 220

#: Vertical distance between adjacent node rows.
ROW_STEP = 160

#: Minimum padding between a container border and its children / a nested
#: container (>= one grid step, per diagram-standards Container Padding).
CONTAINER_PAD = 30

#: Minimum on-diagram font size, in px. AWS diagram conventions require a
#: >= 12px floor for readability/accessibility (see diagram-standards.md
#: "Accessibility & Contrast" and the ``min-font-size`` lint rule). Every text
#: style below (labels, boundaries, legends) sits at or above this value.
MIN_FONT_SIZE = 12

#: Minimum edge stroke width in pt (AWS convention: lines >= 1pt). The shared
#: builder draws edges at this width; the ``arrow-style`` lint rule flags thinner.
EDGE_STROKE_WIDTH = 1.5

#: Standard node label style suffix (label sits directly under the icon). The
#: label font is held at ``MIN_FONT_SIZE`` so node captions clear the 12px floor.
_LABEL_STYLE = (
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;"
    f"fontSize={MIN_FONT_SIZE};fontStyle=0"
)

#: Boundary stroke colors (diagram-standards Legend): dashed green stack
#: boundary, dashed blue network boundary. Providers with an official group
#: shape (AWS) may override via ``boundary_style``.
STACK_BOUNDARY_STROKE = "#00A000"
NETWORK_BOUNDARY_STROKE = "#0062AD"

# Every text/legend/note box carries uniform inner padding of one grid step on
# all four sides (spacing*=GRID) so no line of text abuts the border — the
# reference audit as-built uses spacing*=10 and the shared builder must match
# (see .kiro/steering/diagram-standards.md → Container Padding / text boxes).
_TEXT_STYLE = (
    f"text;html=1;align=left;verticalAlign=top;fontSize={MIN_FONT_SIZE};"
    "whiteSpace=wrap;strokeColor=#000000;fillColor=#FFFFFF;"
    f"spacingLeft={GRID};spacingRight={GRID};spacingTop={GRID};spacingBottom={GRID}"
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """One diagram node placed at (x, y) with an ``ICON_SIZE`` square footprint."""

    id: str
    label: str
    x: int
    y: int
    # Icon renderer: given (node, parent_id) returns the full <mxCell> XML for
    # this node (a single top-level cell, plus any nested glyph geometry).
    render: "IconRenderer" = field(repr=False, default=None)  # type: ignore[assignment]


@dataclass
class Edge:
    """One orthogonal edge with a numeric marker and explicit contact points."""

    id: str
    source: str
    target: str
    marker: str
    dashed: bool = False
    exit: Tuple[float, float] = (1.0, 0.5)
    entry: Tuple[float, float] = (0.0, 0.5)
    # Explicit routing waypoints (model coords) so parallel runs never share a
    # corridor. Each is (x, y).
    points: Sequence[Tuple[float, float]] = ()


@dataclass
class Boundary:
    """A Boundary / Network-Boundary container rectangle."""

    id: str
    label: str
    x: int
    y: int
    w: int
    h: int
    stroke: str = STACK_BOUNDARY_STROKE
    parent: str = "1"
    style: Optional[str] = None  # full style override (e.g. AWS group shape)


# An icon renderer produces the node's mxCell XML. Signature: (node, parent_id).
IconRenderer = Callable[[Node, str], str]


# ---------------------------------------------------------------------------
# Icon renderers
# ---------------------------------------------------------------------------


def builtin_icon(shape_style: str) -> IconRenderer:
    """Renderer for a built-in draw.io stencil node (AWS ``mxgraph.aws4.*``).

    Azure and GCP resolve to **file-path image shapes** (see :func:`image_icon`)
    and OCI to an **embedded stencil** (see :class:`OciStencilIcon`), so this
    built-in-stencil renderer is used by AWS (and any other provider whose icon
    is a genuine built-in ``mxgraph.*`` stencil), not by Azure/GCP/OCI.

    ``shape_style`` is the provider style prefix, e.g.
    ``"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"``.
    The standard label suffix is appended so every provider's labels match.
    """

    def render(node: Node, parent_id: str) -> str:
        style = f"{shape_style};{_LABEL_STYLE}"
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


def image_icon(image_path: str) -> IconRenderer:
    """Renderer for a file-path image-shape node (GCP official icons, Azure azure2).

    ``image_path`` is the icon path under the fetched asset root, e.g.
    ``"assets/vendor/gcp-core/Unique Icons/Vertex AI/SVG/VertexAI-512-color.svg"``
    or ``"img/lib/azure2/<category>/<Name>.svg"``. The path is emitted verbatim as
    the draw.io ``image=`` style token, so it must be a file path — never an inline
    ``data:`` URI, which the linter flags as ``icon-resolved`` (see
    ``.kiro/steering/asset-packs.md`` -> "Image-style caveat").

    Produces one flat ``image`` cell with the same 78x78 footprint and bottom
    label placement as :func:`builtin_icon`, so file-path providers match the AWS
    reference exactly.
    """

    def render(node: Node, parent_id: str) -> str:
        style = (
            "image;html=1;aspect=fixed;points=[];align=center;"
            f"verticalLabelPosition=bottom;verticalAlign=top;fontSize={MIN_FONT_SIZE};"
            f"image={image_path}"
        )
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


# --- OCI embedded-stencil renderer ----------------------------------------

_CELL_RE = re.compile(r"<mxCell\b[^>]*?(?:/>|>.*?</mxCell>)", re.S)
_ID_RE = re.compile(r'\bid="([^"]*)"')
_PARENT_RE = re.compile(r'\bparent="([^"]*)"')
_GEOM_RE = re.compile(r"<mxGeometry\b[^>]*?/>")
# A stencil's baked-in caption cell (Oracle Sans text below the icon).
_CAPTION_MARKERS = ("Oracle Sans", "font-family", "foreignObject")
# The extracted OCI stencils place the top-level group at cell id="2" (parent
# "1"); the icon geometry hangs off it. This is a shape of the current pack.
_OCI_GROUP_CELL_ID = "2"


class OciStencilError(ValueError):
    """Raised when an extracted OCI stencil does not match the expected shape.

    The embedder makes two pack-shape assumptions (fail-honest per asset-packs):
    the top-level group is cell ``id="2"``, and a baked-in caption (when present)
    is detectable by the Oracle-Sans markers. If a refreshed pack breaks either,
    this turns a silent visual defect (leaked caption / mis-scaled icon) into a
    loud generator failure so the pack shape can be re-checked.
    """


def _num(attrs: str, name: str) -> Optional[float]:
    m = re.search(rf'\b{name}="([-0-9.eE]+)"', attrs)
    return float(m.group(1)) if m else None


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"{self.prefix}-g{self.n}"


def embed_oci_stencil(
    node_id: str,
    stencil_xml: str,
    stencil_w: float,
    stencil_h: float,
    parent_id: str,
    box: int = ICON_SIZE,
) -> str:
    """Embed one extracted OCI stencil group as ``node_id``'s icon geometry.

    Drops the root cells and the baked-in caption subtree, scales the icon-only
    region uniformly into a ``box`` square, and re-parents the group under
    ``node_id``. Returns the inner glyph cells (to place inside a group node).
    """
    cells = _CELL_RE.findall(stencil_xml)

    # Guard the pack-shape assumption: the top-level group must be id="2".
    cell_ids = {(_ID_RE.search(c).group(1)) for c in cells if _ID_RE.search(c)}
    if _OCI_GROUP_CELL_ID not in cell_ids:
        raise OciStencilError(
            f"OCI stencil for node {node_id!r} has no group cell "
            f'id="{_OCI_GROUP_CELL_ID}"; the extracted pack shape changed — '
            "re-check scripts/fetch_assets.py stencil extraction."
        )

    parent_of: Dict[str, str] = {}
    caption_ids: set[str] = set()
    icon_bottom = stencil_h
    for cell in cells:
        m = _ID_RE.search(cell)
        if not m:
            continue
        cid = m.group(1)
        pm = _PARENT_RE.search(cell)
        parent_of[cid] = pm.group(1) if pm else ""
        if "value=" in cell and any(mk in cell for mk in _CAPTION_MARKERS):
            caption_ids.add(cid)
            gm = _GEOM_RE.search(cell)
            if gm:
                cy = _num(gm.group(0), "y")
                if cy is not None:
                    icon_bottom = min(icon_bottom, cy)
    changed = True
    while changed:
        changed = False
        for cid, par in parent_of.items():
            if par in caption_ids and cid not in caption_ids:
                caption_ids.add(cid)
                changed = True

    # Scale by the GLYPH's real bounding box, not the stencil's declared size.
    # The declared width/height include the baked-in caption (a long caption like
    # "OCI Container Engine for Kubernetes" makes the stencil w=138 even though the
    # glyph itself is ~84x84). Measuring the drawn shape cells (non-caption, with a
    # ``shape=``/``stencil`` geometry) yields the actual glyph extent, so every
    # provider glyph normalizes to the same visual size — matching the reference
    # pack where all service icons share one standardized icon footprint.
    gx0 = gy0 = float("inf")
    gx1 = gy1 = float("-inf")
    for cell in cells:
        m = _ID_RE.search(cell)
        if not m or m.group(1) in ("0", "1") or m.group(1) in caption_ids:
            continue
        if "shape=" not in cell and "stencil" not in cell:
            continue
        gm = _GEOM_RE.search(cell)
        if not gm:
            continue
        g = gm.group(0)
        x = _num(g, "x") or 0.0
        y = _num(g, "y") or 0.0
        w = _num(g, "width")
        h = _num(g, "height")
        if w is None or h is None:
            continue
        gx0, gy0 = min(gx0, x), min(gy0, y)
        gx1, gy1 = max(gx1, x + w), max(gy1, y + h)

    if gx1 > gx0 and gy1 > gy0:
        icon_w = gx1 - gx0
        icon_h = gy1 - gy0
    else:
        # Fallback to the caption-based estimate if no shape cells were measured.
        # ``icon_bottom`` is the caption's top y, used as a proxy for the icon
        # height (the icon sits above the caption). Guard against a degenerate
        # proxy: a caption sitting near the TOP of the stencil would make
        # ``icon_bottom`` tiny, and ``scale = box / icon_h`` would then blow the
        # glyph far outside the box. Only trust the proxy when it is a plausible
        # fraction of the declared height (>= half); otherwise fall back to the
        # full declared height.
        icon_w = stencil_w
        if icon_bottom and icon_bottom >= 0.5 * stencil_h:
            icon_h = icon_bottom
        else:
            icon_h = stencil_h
        gx0 = gy0 = 0.0

    scale = min(box / icon_w, box / icon_h) if icon_w and icon_h else 1.0
    # Center the scaled glyph in the box, accounting for a non-zero bbox origin.
    pad_x = (box - icon_w * scale) / 2.0 - gx0 * scale
    pad_y = (box - icon_h * scale) / 2.0 - gy0 * scale

    alloc = _IdAllocator(node_id)
    id_map: Dict[str, str] = {}
    kept: List[str] = []
    for cell in cells:
        m = _ID_RE.search(cell)
        if not m:
            continue
        oid = m.group(1)
        if oid in ("0", "1") or oid in caption_ids:
            continue
        id_map[oid] = alloc.next()
        kept.append(cell)

    def _rescale(cell: str, is_group: bool) -> str:
        def repl(gm: "re.Match[str]") -> str:
            attrs = gm.group(0)
            w = _num(attrs, "width")
            h = _num(attrs, "height")
            x = _num(attrs, "x")
            y = _num(attrs, "y")
            out = attrs
            if w is not None:
                out = re.sub(r'\bwidth="[-0-9.eE]+"', f'width="{w * scale:.3f}"', out)
            if h is not None:
                out = re.sub(r'\bheight="[-0-9.eE]+"', f'height="{h * scale:.3f}"', out)
            if is_group:
                if re.search(r'\bx="', out):
                    out = re.sub(r'\bx="[-0-9.eE]+"', f'x="{pad_x:.3f}"', out)
                else:
                    out = out.replace("<mxGeometry", f'<mxGeometry x="{pad_x:.3f}"', 1)
                if re.search(r'\by="', out):
                    out = re.sub(r'\by="[-0-9.eE]+"', f'y="{pad_y:.3f}"', out)
                else:
                    out = out.replace("<mxGeometry", f'<mxGeometry y="{pad_y:.3f}"', 1)
            else:
                if x is not None:
                    out = re.sub(r'\bx="[-0-9.eE]+"', f'x="{x * scale:.3f}"', out)
                if y is not None:
                    out = re.sub(r'\by="[-0-9.eE]+"', f'y="{y * scale:.3f}"', out)
            return out

        return _GEOM_RE.sub(repl, cell, count=1)

    out: List[str] = []
    for cell in kept:
        oid = _ID_RE.search(cell).group(1)
        new_id = id_map[oid]
        pm = _PARENT_RE.search(cell)
        old_parent = pm.group(1) if pm else "1"
        new_parent = parent_id if old_parent in ("0", "1") else id_map.get(old_parent, parent_id)
        cell2 = _ID_RE.sub(f'id="{new_id}"', cell, count=1)
        if _PARENT_RE.search(cell2):
            cell2 = _PARENT_RE.sub(f'parent="{new_parent}"', cell2, count=1)
        else:
            cell2 = cell2.replace("<mxCell", f'<mxCell parent="{new_parent}"', 1)
        if oid == "2":
            cell2 = re.sub(r'\bvalue="[^"]*"', 'value=""', cell2, count=1)
        cell2 = _rescale(cell2, is_group=(oid == "2"))
        out.append(cell2)
    return "".join(out)


class OciStencilIcon:
    """Renderer for an OCI node whose glyph is an embedded stencil group.

    ``stencils`` maps a slug -> ``{"w", "h", "xml"}`` (as produced by
    ``scripts/fetch_assets.py``). ``brand_hex`` colors the node label.
    """

    def __init__(self, stencils: Dict[str, Any], slug: str, brand_hex: str = "#F80000"):
        if slug not in stencils:
            raise KeyError(f"OCI stencil slug {slug!r} not found in extracted pack")
        self.entry = stencils[slug]
        self.slug = slug
        self.brand_hex = brand_hex

    def __call__(self, node: Node, parent_id: str) -> str:
        gw = float(self.entry.get("w") or ICON_SIZE)
        gh = float(self.entry.get("h") or ICON_SIZE)
        style = (
            "group;html=1;fillColor=none;strokeColor=none;"
            f"{_LABEL_STYLE};fontColor={self.brand_hex}"
        )
        container = (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" connectable="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )
        glyph = embed_oci_stencil(node.id, self.entry["xml"], gw, gh, node.id, ICON_SIZE)
        return container + "          " + glyph + "\n"


# ---------------------------------------------------------------------------
# Cell builders
# ---------------------------------------------------------------------------


def title_cell(text: str, x: int = 40, y: int = 20, w: int = 900) -> str:
    return (
        f'        <mxCell id="title" value="{text}" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=left;'
        'verticalAlign=middle;fontSize=16;fontStyle=1" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="30" as="geometry" />\n'
        "        </mxCell>\n"
    )


def boundary_cell(b: Boundary) -> str:
    style = b.style or (
        "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;"
        f"strokeColor={b.stroke};fillColor=none;verticalAlign=top;"
        f"fontColor={b.stroke};fontSize=12"
    )
    return (
        f'        <mxCell id="{b.id}" value="{b.label}" style="{style}" '
        f'vertex="1" parent="{b.parent}">\n'
        f'          <mxGeometry x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" as="geometry" />\n'
        "        </mxCell>\n"
    )


def edge_cell(e: Edge) -> str:
    dash = "dashed=1;" if e.dashed else ""
    ex, ey = e.exit
    nx, ny = e.entry
    style = (
        # Open arrowhead (endArrow=open;endFill=0) and a >= 1pt stroke, per AWS
        # diagram conventions (diagram-standards "Accessibility & Contrast" /
        # arrow-style lint rule): open pointers read cleaner than heavy filled
        # heads and the stroke stays visible when scaled down.
        f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=open;endFill=0;"
        f"strokeWidth={EDGE_STROKE_WIDTH};{dash}"
        f"exitX={ex};exitY={ey};exitDx=0;exitDy=0;exitPerimeter=0;"
        f"entryX={nx};entryY={ny};entryDx=0;entryDy=0;"
        "fontSize=12;fontStyle=1"
    )
    head = (
        f'        <mxCell id="{e.id}" value="{e.marker}" style="{style}" '
        f'edge="1" parent="1" source="{e.source}" target="{e.target}">\n'
    )
    if e.points:
        pts = "".join(
            f'              <mxPoint x="{px:.2f}" y="{py:.2f}" />\n' for px, py in e.points
        )
        return (
            head
            + '          <mxGeometry relative="1" as="geometry">\n'
            + '            <Array as="points">\n'
            + pts
            + "            </Array>\n"
            + "          </mxGeometry>\n"
            + "        </mxCell>\n"
        )
    return head + '          <mxGeometry relative="1" as="geometry" />\n        </mxCell>\n'


def text_cell(cid: str, lines: Sequence[str], x: int, y: int, w: int = 320, h: int = 200) -> str:
    value = "&#10;".join(lines)
    return (
        f'        <mxCell id="{cid}" value="{value}" style="{_TEXT_STYLE}" '
        f'vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />\n'
        "        </mxCell>\n"
    )


STANDARD_LEGEND_LINES = (
    "Legend",
    "Solid line = primary flow",
    "Dashed line = asynchronous / event-driven flow",
    "Red = blocked / missing / disabled",
    "🆕 = new in version N",
    "🔄 = changed in version N",
    "Dashed outer boundary = stack Boundary (profile brand color)",
    "Dashed inner boundary = Network Boundary (profile brand color)",
    "Numbered markers (1..N) = ordered data flow steps; see Flow list",
)


def build_diagram(
    *,
    diagram_id: str,
    diagram_name: str,
    title: str,
    boundaries: Sequence[Boundary],
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    flow_lines: Sequence[str],
    legend_x: int,
    legend_y_flow: int = 120,
    legend_y_legend: int = 360,
    legend_w: int | None = None,
    page_w: int = 1850,
    page_h: int = 950,
) -> str:
    """Assemble a full ``.drawio`` document from the standard building blocks."""
    parts: List[str] = []
    parts.append(
        f'<mxfile host="app.diagrams.net" agent="rule-engine golden-example" version="24.0.0">\n'
        f'  <diagram id="{diagram_id}" name="{diagram_name}">\n'
        f'    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="{GRID}" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{page_w}" pageHeight="{page_h}" math="0" shadow="0">\n'
        "      <root>\n"
        '        <mxCell id="0" />\n'
        '        <mxCell id="1" parent="0" />\n\n'
    )
    parts.append(title_cell(title))
    parts.append("\n")
    for b in boundaries:
        parts.append(boundary_cell(b))
    parts.append("\n")
    for n in nodes:
        parts.append(n.render(n, "1"))
    parts.append("\n")
    for e in edges:
        parts.append(edge_cell(e))
    parts.append("\n")
    # Size each text box from its content plus uniform padding so no line is
    # clipped or abuts the border. Height: one 12px line ~= 16px of leading, plus
    # one grid step of padding top and bottom. Width: wide enough that the
    # LONGEST line across BOTH the Flow and Legend boxes fits WITHOUT wrapping,
    # then the SAME width is applied to both so the pair reads as one aligned
    # block (diagram-standards → Legend/Flow furniture). ~5.6px per 12px glyph +
    # 2× the grid-step inner padding, rounded up to the grid.
    #: usable characters per line at a given box width (glyph ~5.6px + padding).
    def _chars_per_line(width: int) -> int:
        return max(1, int((width - 2 * GRID) / 5.6))

    def _text_h(lines: Sequence[str], width: int | None = None) -> int:
        # One 12px line ~= 16px of leading, plus one grid step of padding top and
        # bottom. When a narrow ``width`` is set, a line longer than the box wraps,
        # so count the wrapped visual lines (the box grows taller, not wider).
        if width is None:
            visual = len(list(lines))
        else:
            cpl = _chars_per_line(width)
            visual = sum(max(1, -(-len(s) // cpl)) for s in lines)
        return visual * 16 + 2 * GRID

    def _text_w(*line_groups: Sequence[str]) -> int:
        longest = max((len(s) for grp in line_groups for s in grp), default=20)
        # ~5.6px per 12px glyph (measured against the reference) + one grid step
        # of inner padding each side; rounded up to the grid. Tight to content so
        # the box is only as wide as its longest line, not oversized.
        raw = int(longest * 5.6) + 2 * GRID
        return int(-(-raw // GRID) * GRID)  # round up to a grid multiple

    # A caller may pin a narrower ``legend_w`` (the Flow/Legend blocks then wrap
    # and grow taller instead of running wide into the diagram body); otherwise
    # size to the longest line with no wrap.
    box_w = legend_w if legend_w is not None else _text_w(flow_lines, STANDARD_LEGEND_LINES)
    parts.append(text_cell("flow-legend", flow_lines, legend_x, legend_y_flow, box_w, _text_h(flow_lines, legend_w)))
    parts.append(text_cell("legend", STANDARD_LEGEND_LINES, legend_x, legend_y_legend, box_w, _text_h(STANDARD_LEGEND_LINES, legend_w)))
    parts.append(
        "      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n"
    )
    return "".join(parts)


__all__ = [
    "ICON_SIZE", "GRID", "COL_STEP", "ROW_STEP", "CONTAINER_PAD",
    "STACK_BOUNDARY_STROKE", "NETWORK_BOUNDARY_STROKE",
    "Node", "Edge", "Boundary", "IconRenderer",
    "builtin_icon", "embed_oci_stencil", "OciStencilIcon", "OciStencilError",
    "title_cell", "boundary_cell", "edge_cell", "text_cell",
    "STANDARD_LEGEND_LINES", "build_diagram",
]
