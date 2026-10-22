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

import base64
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from rule_engine.engine_assets import locate_asset, sniff_mime

# ---------------------------------------------------------------------------
# Canonical layout geometry (AWS reference). Do not fork these per provider.
# ---------------------------------------------------------------------------


def _xml_escape(text: str) -> str:
    """Escape text for safe interpolation into an XML attribute value.

    Theme 4 (REVIEW.md): every ``value="…"`` the builder emits is free-form
    display text (a node/boundary label, the title, an edge marker, a Flow/Legend
    line). An unescaped ``&``, ``<`` or ``>`` produces malformed XML that draw.io
    refuses to open — a latent crash the moment a label contains, say,
    ``Users & admins`` or ``t < 5ms``. The same five replacements as
    ``contract._xml_escape`` (``&`` first, so it never double-escapes the entities
    the others introduce). Callers that build a multi-line value join the escaped
    lines with the literal ``&#10;`` entity, which stays intact because its own
    ``&`` is never re-escaped (each line is escaped BEFORE the join).
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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

#: Standard stair step distance (3 grid steps = 30px). The first waypoint off
#: an exit point steps out by this amount before the vertical turn, keeping
#: all stair corners consistent and visually balanced (neither too cramped
#: at 10px nor too loose at 60-70px). Per diagram-standards Edge Routing.
STAIR_STEP = 3 * GRID

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
#: Every service/resource node caption renders on an opaque white background so
#: an edge that passes over the label band never strikes through the text
#: (diagram-standards → Accessibility & Contrast; the caption must stay legible
#: even where a line crosses it). This is the default; a node inside a filled
#: container may override it with the local fill via ``node.label_bg`` (draw.io
#: takes the LAST occurrence of a style key, and ``overlay_suffix`` appends the
#: override after this default).
_LABEL_BG = "#FFFFFF"
_LABEL_STYLE = (
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;"
    f"fontSize={MIN_FONT_SIZE};fontStyle=0;labelBackgroundColor={_LABEL_BG}"
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
# Presentation skin (1.11.0 WS1) — style channels ONLY, never geometry.
# ---------------------------------------------------------------------------
# A Skin restyles furniture borders, edge colour, and (later) numeric markers
# without moving a single node or edge coordinate. Every field defaults to the
# value that reproduces the 1.10.12 byte output, so a diagram with no Skin — or
# the default Skin — renders byte-identically (proven by regen_examples.py
# --check). The furniture/edge channels are pure style: no geometry consumer
# (legend-placement, marker-*, container-*) reads a furniture or edge COLOUR, so
# changing them cannot shift a verdict. The marker badge is a separate,
# geometry-bearing feature (WS1 task 2) and is not carried here yet.

#: Furniture border presets for the Flow/Legend text boxes.
_FURNITURE_STROKE = {
    "black": "#000000",   # 1.10.12 default — byte-identical
    "light": "#B3B3B3",   # neutral light grey
    "none": "none",       # borderless
    # "brand" is resolved per diagram from the provider boundary stroke by the
    # caller (draw_cli), which knows the provider; the renderer receives the
    # already-resolved hex via edge_stroke/furniture overrides.
}


@dataclass(frozen=True)
class Skin:
    """Presentation-only style choices. Defaults reproduce 1.10.12 exactly.

    - ``furniture_stroke``: border of the Flow/Legend boxes
      (``black`` default | ``light`` | ``none`` | an explicit ``#RRGGBB``).
    - ``edge_stroke``: edge line colour. ``None`` (default) emits NO
      ``strokeColor`` token, byte-identical to today (draw.io default black);
      a hex adds ``strokeColor=<hex>`` to every edge.
    - ``marker_badge``: numeric-marker form (``none`` default = inline bold
      text, the only byte-inert value). ``circle``/``square`` are the
      geometry-bearing badge forms delivered by WS1 task 2; carried here so the
      field exists, but the renderer treats any non-``none`` value as a no-op
      until the badge renderer lands.
    """

    furniture_stroke: str = "black"
    edge_stroke: Optional[str] = None
    marker_badge: str = "none"

    def furniture_stroke_hex(self) -> str:
        """The resolved stroke colour token for a furniture box style."""
        return _FURNITURE_STROKE.get(self.furniture_stroke, self.furniture_stroke)


#: The default Skin — every field at its 1.10.12 byte-identical value.
DEFAULT_SKIN = Skin()


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
    #: Optional overlay marker term (Overlay Vocabulary), e.g. ``"standby"``.
    #: Rendered by :func:`overlay_suffix` as a dashed outline plus the
    #: machine-readable ``overlay=<term>`` token the linter reads.
    overlay: Optional[str] = None
    #: Caption background colour; set by ``build_diagram`` only for a node whose
    #: caption an edge painted beneath it crosses (see ``_edge_slots``).
    label_bg: Optional[str] = None


# Visual encoding of an overlay marker. diagram-standards → *Icon Fidelity*
# forbids customising a pack icon (no forced fill, no recoloured stroke), so an
# overlay must be ADDITIVE: the shape channel is a **dashed outline** on the
# node's own cell, never a repaint of the glyph. The other two channels are the
# node's label token (e.g. ``…-standby``) and the Legend entry, so the marker
# survives grayscale printing and colour-vision deficiency.
_OVERLAY_SHAPE = {
    "standby": "dashed=1;dashPattern=6 4",
    # 1.10.12 WS5 (C13): an ops / observability service (monitoring, CI state,
    # a config store) that supports the workload but is not a step of its
    # data flow. A dotted outline, distinct from the dashed ``standby`` ring.
    "supporting": "dashed=1;dashPattern=1 3",
}

#: The standard Legend line for each overlay term a builder can emit
#: (:func:`overlay_legend_lines`). Each names the term as a whole token, which
#: is what ``overlay-legend-coverage`` checks.
OVERLAY_LEGEND_LINES = {
    "standby": "standby = passive peer (dashed outline); edges mirror the active side",
    "supporting": "supporting = ops / observability service (dotted outline); not a data-flow step",
}


def overlay_legend_lines(nodes: Sequence["Node"]) -> Tuple[str, ...]:
    """The standard Legend lines for the overlay terms ``nodes`` carry, in
    first-use order (1.10.12 WS5). A term with no standard line is left to the
    builder's own Legend text."""
    out: List[str] = []
    for n in nodes:
        line = OVERLAY_LEGEND_LINES.get(n.overlay or "")
        if line and line not in out:
            out.append(line)
    return tuple(out)


def overlay_suffix(node: "Node") -> str:
    """Return the style suffix that encodes ``node.overlay``, or ``""``.

    Emits the dashed-outline shape channel plus ``overlay=<term>``, the token
    ``cli._parse_drawio`` / ``geometry.build_geometry`` read to know a node
    carries a marker (so ``overlay-legend-coverage`` can check it is documented
    and ``node-connectivity`` can exempt it).
    """
    out = ""
    if node.overlay:
        shape = _OVERLAY_SHAPE.get(node.overlay, "dashed=1")
        out = f";{shape};overlay={node.overlay}"
    if node.label_bg:
        # Set by ``build_diagram`` for a node whose caption an edge drawn beneath
        # it crosses: the caption is painted on the local background so the line
        # passes BEHIND the text instead of striking it through.
        out += f";labelBackgroundColor={node.label_bg}"
    return out


@dataclass
class Edge:
    """One orthogonal edge with a numeric marker and explicit contact points."""

    id: str
    source: str
    target: str
    marker: str
    dashed: bool = False
    #: Theme 16 (1.10.10): a network-level PEERING relationship (VPC/VCN peering,
    #: a cross-cloud peering link), not a directional data-flow step. Rendered as
    #: a symmetric dashed line with NO arrowhead on either end (``startArrow=none;
    #: endArrow=none``) — a peering is bidirectional and undirected, so a single
    #: head would misstate it and a double head trips ``edge-bidirectional``.
    #: ``startArrow=none`` + ``endArrow=none`` passes both ``arrow-style`` (none
    #: is an accepted head) and ``edge-bidirectional`` (either end none → not
    #: double-headed). The marker is a text label (e.g. ``peering``), not a
    #: numeric flow step, so it never enters the flow-marker hygiene passes.
    peering: bool = False
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
    #: The structural kind this box presents (``account`` / ``region`` / ``vpc``
    #: / ``az``), 1.10.7. Drives the conditional Legend (:func:`legend_lines_for`);
    #: ``""`` (the default, every hand-authored builder) keeps the full legend.
    kind: str = ""


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

    Since 1.10.2, AWS resolves its official SVGs to a **file-path image style**
    (``image;...;image=assets/vendor/aws-icons/...svg``) and feeds that whole
    style here (see ``scripts/build_aws_ha_example.py`` / ``resolve_icon``). Such
    a style is run through :func:`_embed_asset_style`, which inlines the
    ``assets/vendor`` SVG as ``image=data:image/svg+xml,<b64>`` so it renders in
    the draw.io editor and adds the ``iconRef=<path>`` companion — identical
    treatment to :func:`image_icon`. A genuine ``mxgraph.*`` stencil style carries
    no ``image=assets/vendor`` token and is emitted unchanged.
    """

    def render(node: Node, parent_id: str) -> str:
        style = _embed_asset_style(f"{shape_style};{_LABEL_STYLE}{overlay_suffix(node)}")
        return (
            f'        <mxCell id="{node.id}" value="{_xml_escape(node.label)}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


def image_icon(image_path: str) -> IconRenderer:
    """Renderer for a file-path image-shape node (AWS/GCP official icons, Azure azure2).

    ``image_path`` is the icon path a role resolves to. Two shapes are handled so
    the glyph renders in the draw.io **editor**, not only in PNG export:

    * A **repo-relative asset path** under ``assets/vendor/`` (AWS official SVGs,
      GCP official 2025 icons). The draw.io editor cannot resolve a relative
      ``image=<path>`` — its base path is the app, not the ``.drawio`` file — so
      such nodes show blank in the editor. We therefore read the SVG bytes from
      the cwd-relative asset root, base64-encode them, and emit
      ``image=data:image/svg+xml,<b64>`` (the **comma** form draw.io renders,
      matching ``export_raster.inline_local_images`` — *not* ``;base64,``). The
      original path is preserved verbatim in a companion ``iconRef=<path>`` style
      token so every honest-gate that reverse-identifies a role FROM the asset
      path keeps working (draw.io ignores the unknown ``iconRef`` style key).
      If the asset is missing at generation time, the old ``image=<path>`` form
      is kept (never crash) — the asset-paths guard / verifier still flag it.

    * A **draw.io-internal path** (``img/lib/azure2/<category>/<Name>.svg``).
      draw.io ships these inside the app, so they already render in the editor;
      the path is emitted verbatim as ``image=<path>`` and NOT embedded.

    Produces one flat ``image`` cell with the same 78x78 footprint and bottom
    label placement as :func:`builtin_icon`, so file-path providers match the AWS
    reference exactly.
    """

    embedded_image, icon_ref = _embed_asset_image(image_path)

    def render(node: Node, parent_id: str) -> str:
        ref_token = f"iconRef={icon_ref};" if icon_ref else ""
        style = (
            "image;html=1;aspect=fixed;points=[];align=center;"
            f"verticalLabelPosition=bottom;verticalAlign=top;fontSize={MIN_FONT_SIZE};"
            f"labelBackgroundColor={_LABEL_BG};"
            f"{ref_token}image={embedded_image}{overlay_suffix(node)}"
        )
        return (
            f'        <mxCell id="{node.id}" value="{_xml_escape(node.label)}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


#: Icon-asset roots whose SVGs are embedded as data-URIs so they render in the
#: draw.io editor. A path under one of these is read cwd-relative at generation
#: time; ``img/lib/...`` (azure2, shipped inside draw.io) and any already-inline
#: ``data:`` URI are deliberately excluded.
_EMBEDDABLE_ASSET_PREFIX = "assets/vendor/"


def _embed_asset_image(image_path: str) -> Tuple[str, Optional[str]]:
    """Return ``(image_token_value, icon_ref)`` for an ``image=`` style value.

    For a repo-relative ``assets/vendor/*`` path that exists cwd-relative (or
    is an engine-bundled asset), returns the ``data:<mime>,<b64>`` (comma form,
    MIME sniffed from the bytes) inline value plus the
    original path as ``icon_ref`` (the honest-gates reverse-identification key).
    For an ``img/lib/...`` draw.io-internal path, an already-inline ``data:``
    URI, or an asset that cannot be read, returns the path unchanged and
    ``icon_ref=None`` so the caller emits the legacy ``image=<path>`` form.
    """
    path = image_path.strip()
    if path.startswith("data:") or not path.startswith(_EMBEDDABLE_ASSET_PREFIX):
        return image_path, None
    # The workspace file, else an engine-bundled asset (1.10.12: education).
    asset = locate_asset(path)
    try:
        raw = asset.read_bytes() if asset is not None else None
    except OSError:
        raw = None
    if raw is None:
        # Asset not present at generation time — keep the path form (do not
        # crash); the asset-paths guard / Icon_Verifier still flag it.
        return image_path, None
    b64 = base64.b64encode(raw).decode("ascii")
    # MIME from the bytes (1.10.12): a PNG brand mark inlined as svg+xml
    # renders as a broken image.
    return f"data:{sniff_mime(raw, path)},{b64}", path


# ``image=<path>`` token in a style string (value runs to the next ``;`` or end).
_STYLE_IMAGE_RE = re.compile(r"(?:^|;)image=([^;]+)")


def _embed_asset_style(style: str) -> str:
    """Inline an ``image=assets/vendor/*.svg`` token in a whole style string.

    AWS resolves its official icons to a *file-path image style* and renders it
    through :func:`builtin_icon`, so the embedding must work on a style string,
    not only on a bare path. When ``style`` carries an ``image=assets/vendor/*``
    token whose asset exists cwd-relative, the token value is replaced with the
    ``data:image/svg+xml,<b64>`` comma form and an ``iconRef=<path>;`` companion
    is prepended (unless already present). A style with no embeddable
    ``image=assets/vendor`` token — a genuine ``mxgraph.*`` stencil, an
    ``img/lib/...`` azure2 path, or an already-inline ``data:`` URI — is returned
    unchanged. Idempotent: an already-embedded style carries a ``data:`` value
    that :func:`_embed_asset_image` leaves alone.
    """
    m = _STYLE_IMAGE_RE.search(style or "")
    if not m:
        return style
    value = m.group(1)
    embedded, icon_ref = _embed_asset_image(value)
    if icon_ref is None:
        return style
    new_style = style[: m.start(1)] + embedded + style[m.end(1):]
    if "iconRef=" not in new_style:
        new_style = f"iconRef={icon_ref};{new_style}"
    return new_style


# --- OCI embedded-stencil renderer ----------------------------------------

#: OCI v24.2 caption typeface. Oracle Sans is not a web font and is rarely
#: installed, so a bare ``fontFamily=Oracle Sans`` falls back to the browser's
#: default SERIF face (every CI raster export). The list keeps it sans-serif.
#: Must stay in sync with the ``fontFamily`` in ``mappings/oci-icons.yaml``.
OCI_FONT_FAMILY = "Oracle Sans,Helvetica,Arial,sans-serif"
#: OCI v24.2 caption colour — Oracle near-black, never red.
OCI_CAPTION_HEX = "#312D2A"

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
    #
    # A shape cell's ``x``/``y`` are RELATIVE to its parent group. Most OCI
    # stencils draw straight under the root (id="2"), so the local coordinate is
    # already the root-frame one; but a few (``object-storage``, ``cdn``) wrap the
    # glyph in an intermediate group offset by ~14px. Measuring those shapes in
    # their LOCAL frame understates the glyph's true left edge, the centering pad
    # then cannot cancel the wrapper's offset, and the glyph renders off-centre
    # from the bottom label — the visible "model-storage" shift (docs/REVIEW.md
    # D16). Accumulating every ancestor group's offset into a root-frame origin
    # first makes the bbox — and thus the pad — correct for a flat OR a nested
    # stencil (the accumulation is a no-op when the root is the only ancestor).
    geom_x_of: Dict[str, float] = {}
    geom_y_of: Dict[str, float] = {}
    for cell in cells:
        m = _ID_RE.search(cell)
        if not m:
            continue
        gm = _GEOM_RE.search(cell)
        geom_x_of[m.group(1)] = (_num(gm.group(0), "x") if gm else None) or 0.0
        geom_y_of[m.group(1)] = (_num(gm.group(0), "y") if gm else None) or 0.0

    def _ancestor_offset(cid: str) -> Tuple[float, float]:
        # Sum the offsets of every group STRICTLY ABOVE ``cid`` up to the root
        # (id="2"), which itself is repositioned by the pad below — so the root's
        # own offset is deliberately excluded here.
        ax = ay = 0.0
        seen: set[str] = set()
        cur = parent_of.get(cid, "")
        while cur and cur not in ("0", "1", _OCI_GROUP_CELL_ID) and cur not in seen:
            seen.add(cur)
            ax += geom_x_of.get(cur, 0.0)
            ay += geom_y_of.get(cur, 0.0)
            cur = parent_of.get(cur, "")
        return ax, ay

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
        w = _num(g, "width")
        h = _num(g, "height")
        if w is None or h is None:
            continue
        aox, aoy = _ancestor_offset(m.group(1))
        x = (_num(g, "x") or 0.0) + aox
        y = (_num(g, "y") or 0.0) + aoy
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
    ``scripts/fetch_assets.py``). ``brand_hex`` is the profile's brand anchor
    (kept for the Icon Resolver contract); the node CAPTION uses the OCI v24.2
    text style — ``OCI_FONT_FAMILY`` in ``caption_hex`` (Oracle near-black
    ``#312D2A``), never red: red on a diagram means blocked/missing/disabled
    (Legend), and the v24.2 guide never sets captions in red (docs/REVIEW.md D17).
    """

    def __init__(
        self,
        stencils: Dict[str, Any],
        slug: str,
        brand_hex: str = "#F80000",
        caption_hex: str = OCI_CAPTION_HEX,
    ):
        if slug not in stencils:
            raise KeyError(f"OCI stencil slug {slug!r} not found in extracted pack")
        self.entry = stencils[slug]
        self.slug = slug
        self.brand_hex = brand_hex
        self.caption_hex = caption_hex

    def __call__(self, node: Node, parent_id: str) -> str:
        gw = float(self.entry.get("w") or ICON_SIZE)
        gh = float(self.entry.get("h") or ICON_SIZE)
        style = (
            "group;html=1;fillColor=none;strokeColor=none;"
            f"{_LABEL_STYLE};fontFamily={OCI_FONT_FAMILY};"
            f"fontColor={self.caption_hex};"
            f"ociSlug={self.slug}{overlay_suffix(node)}"
        )
        container = (
            f'        <mxCell id="{node.id}" value="{_xml_escape(node.label)}" style="{style}" '
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
        f'        <mxCell id="title" value="{_xml_escape(text)}" '
        'style="text;html=1;strokeColor=none;fillColor=none;align=left;'
        'verticalAlign=middle;fontSize=16;fontStyle=1" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="30" as="geometry" />\n'
        "        </mxCell>\n"
    )


def _boundary_style(b: Boundary) -> str:
    return b.style or (
        "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;"
        f"strokeColor={b.stroke};fillColor=none;verticalAlign=top;"
        f"fontColor={b.stroke};fontSize=12"
    )


def _set_style_token(style: str, key: str, value: str) -> str:
    parts = [p for p in style.split(";") if p and not p.startswith(f"{key}=")]
    parts.append(f"{key}={value}")
    return ";".join(parts)


def _clear_container_captions(
    boundaries: Sequence[Boundary], nodes: Sequence[Node], edges: Sequence[Edge]
) -> List[Boundary]:
    """Move a container caption off any vertical edge leg that would cut it.

    A draw.io group draws its caption inside its own top edge. A top entry into a
    node near a container's left (or centre) drops straight through that strip,
    and when the caption text sits on the drop column the line slices the words
    — the ``vpc-primary …`` caption on every HA landscape whose VPC caption is
    left-aligned (AWS, OCI). Geometry is fixed by the layout engine, so the
    CAPTION moves instead: to the nearest grid slot no leg passes through,
    expressed as ``align=left;spacingLeft=N``. A caption that is already clear
    is left byte-identical. ``edge-crosses-container-label`` is the check.
    """
    from rule_engine.geometry import Box, free_caption_x0, vertical_caption_cuts

    boxes = {n.id: Box(n.id, n.x, n.y, ICON_SIZE, ICON_SIZE) for n in nodes}
    polylines = []
    for e in edges:
        s, t = boxes.get(e.source), boxes.get(e.target)
        if s is None or t is None:
            continue
        pl = [(s.x + e.exit[0] * s.w, s.y + e.exit[1] * s.h)]
        pl += [tuple(p) for p in e.points]
        pl.append((t.x + e.entry[0] * t.w, t.y + e.entry[1] * t.h))
        polylines.append(pl)
    out: List[Boundary] = []
    for b in boundaries:
        style = _boundary_style(b)
        box = Box(b.id, b.x, b.y, b.w, b.h)
        x0 = free_caption_x0(b.label, style, box, vertical_caption_cuts(polylines, box))
        if x0 is None:
            out.append(b)
            continue
        spacing = 2  # draw.io default label spacing, added to spacingLeft
        new = _set_style_token(style, "align", "left")
        new = _set_style_token(new, "spacingLeft", str(int(round(x0 - b.x - spacing))))
        out.append(Boundary(b.id, b.label, b.x, b.y, b.w, b.h, b.stroke, b.parent, new, b.kind))
    return out


def _wrap_caption_two_lines(label: str) -> Optional[str]:
    """Split a one-line caption at the space nearest its middle (``<br>``)."""
    if "<br" in label or " " not in label.strip():
        return None
    words = label.split(" ")
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        cost = max(len(a), len(b))
        if best is None or cost < best[0]:
            best = (cost, f"{a}<br>{b}")
    return best[1] if best else None


def fit_boundary_captions(
    boundaries: Sequence[Boundary],
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    legend_x: Optional[int] = None,
) -> List[Boundary]:
    """Make every boundary hold its caption (1.10.12 WS6, C4) — builder side.

    The layout engine sizes containers to their captions itself
    (``layout.place.fit_container_captions``); this pass covers geometry that
    did not come from ``layout()`` (a hand-placed context diagram, SEP 01) and
    is a no-op on engine output. For each boundary whose caption
    (:func:`rule_engine.geometry.container_caption_need`) is wider than the box,
    innermost first:

    1. **grow right** by the missing width when the added strip is free: no
       node icon or caption, no boundary other than an ancestor, no edge whose
       two ends are both outside the box, and clear of a right-margin
       Flow/Legend at ``legend_x``; ancestors grow with it when needed and they
       pass the same test;
    2. else **wrap** the caption onto two lines (``<br>`` at the space nearest
       the middle) when the two lines fit the box;
    3. else leave it (``container-caption-overflow`` reports it).
    """
    from rule_engine.geometry import (
        Box, caption_lines, container_caption_need, node_caption_box,
    )

    out = list(boundaries)
    blocks = []
    for n in nodes:
        icon = Box(n.id, n.x, n.y, ICON_SIZE, ICON_SIZE)
        blocks.append(icon)
        if caption_lines(n.label):
            blocks.append(node_caption_box(icon, n.label))
    pos = {n.id: (n.x, n.y) for n in nodes}

    def _box(b: Boundary) -> "Box":
        return Box(b.id, b.x, b.y, b.w, b.h)

    def _inside(p, b: Boundary) -> bool:
        return b.x <= p[0] <= b.x + b.w and b.y <= p[1] <= b.y + b.h

    def _hits(a: "Box", c: "Box") -> bool:
        return a.x < c.right and c.x < a.right and a.y < c.bottom and c.y < a.bottom

    def _encloses(a: Boundary, b: Boundary) -> bool:
        return (a.id != b.id and a.x <= b.x and a.y <= b.y
                and b.x + b.w <= a.x + a.w and b.y + b.h <= a.y + a.h)

    def _strip_free(k: int, new_right: int) -> bool:
        b = out[k]
        if new_right <= b.x + b.w:
            return True
        strip = Box("s", b.x + b.w, b.y, new_right - (b.x + b.w), b.h)
        if legend_x is not None and new_right + GRID > legend_x:
            return False
        if any(_hits(strip, o) for o in blocks):
            return False
        for j, o in enumerate(out):
            if j != k and not _encloses(o, b) and _hits(strip, _box(o)):
                return False
        for e in edges:
            s, t = pos.get(e.source), pos.get(e.target)
            if s is None or t is None:
                continue
            sc = (s[0] + ICON_SIZE / 2, s[1] + ICON_SIZE / 2)
            tc = (t[0] + ICON_SIZE / 2, t[1] + ICON_SIZE / 2)
            if _inside(sc, b) or _inside(tc, b):
                continue
            pts = [sc] + [tuple(p) for p in e.points] + [tc]
            for p, q in zip(pts, pts[1:]):
                seg = Box("e", min(p[0], q[0]), min(p[1], q[1]),
                          max(abs(q[0] - p[0]), 1), max(abs(q[1] - p[1]), 1))
                if _hits(strip, seg):
                    return False
        return True

    order = sorted(range(len(out)), key=lambda i: out[i].w * out[i].h)
    for k in order:
        b = out[k]
        need = container_caption_need(b.label, _boundary_style(b))
        if need <= b.w:
            continue
        new_right = b.x + int(-(-need // GRID) * GRID)
        chain = [k] + [j for j in order if _encloses(out[j], b)]
        plan = {}
        ok = True
        right = new_right
        for j in chain:
            box = out[j]
            target = max(box.x + box.w, right + (0 if j == k else CONTAINER_PAD))
            if not _strip_free(j, target):
                ok = False
                break
            plan[j] = target
            right = target
        if ok:
            for j, target in plan.items():
                o = out[j]
                out[j] = replace(o, w=int(target - o.x))
            continue
        wrapped = _wrap_caption_two_lines(b.label)
        if (wrapped and "html=1" in _boundary_style(b)
                and container_caption_need(wrapped, _boundary_style(b)) <= b.w):
            out[k] = replace(b, label=wrapped)
    return out


def _local_background(n: Node, boundaries: Sequence[Boundary]) -> str:
    """The fill of the innermost FILLED container holding ``n`` (else white)."""
    best: Optional[Boundary] = None
    for b in boundaries:
        if not (b.x <= n.x and n.x + ICON_SIZE <= b.x + b.w
                and b.y <= n.y and n.y + ICON_SIZE <= b.y + b.h):
            continue
        m = re.search(r"(?:^|;)fillColor=(#[0-9A-Fa-f]{6})", _boundary_style(b))
        if m and (best is None or b.w * b.h < best.w * best.h):
            best = b
    if best is None:
        return "#FFFFFF"
    return re.search(r"(?:^|;)fillColor=(#[0-9A-Fa-f]{6})", _boundary_style(best)).group(1)


def boundary_cell(b: Boundary) -> str:
    style = _boundary_style(b)
    return (
        f'        <mxCell id="{b.id}" value="{_xml_escape(b.label)}" style="{style}" '
        f'vertex="1" parent="{b.parent}">\n'
        f'          <mxGeometry x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" as="geometry" />\n'
        "        </mxCell>\n"
    )


def _orthogonalised(
    edges: Sequence[Edge], nodes: Sequence[Node]
) -> List[Edge]:
    """Return ``edges`` with every route rewritten to axis-aligned legs (v1.6.0).

    An ``orthogonalEdgeStyle`` edge never draws a diagonal: when two consecutive
    points are not axis-aligned, draw.io inserts its own corner and **picks the
    direction**. So an unaligned waypoint is not a diagonal on screen — it is a
    corner the author did not specify, which is how an edge ends up grazing a glyph
    or sliding along a border even though every waypoint looked deliberate.

    Applying :func:`rule_engine.geometry.orthogonalise_route` here, in the shared
    builder, covers **both** authoring paths from one place: the lane-grid layout
    engine already aligns the routes it computes, and this catches the diagrams
    whose waypoints are hand-written coordinate literals (the five per-provider
    reference examples). It also makes the alignment a property of the *builder*,
    so a new generator inherits it without knowing the rule exists.

    A route that is already orthogonal with perpendicular contact legs is returned
    unchanged, so this is a no-op for a correct hand-authored edge.

    **Contacts are grid-resolved first.** A hand-written fraction such as ``0.25``
    on a 78px icon resolves to ``y0 + 19.5`` — half a pixel off the 10-grid that
    every waypoint snaps to. Aligning a snapped waypoint to that contact would
    leave a permanent 0.5px kink, which is the skew that made arrowheads look bent.
    Nudging the *fraction* so the absolute contact lands on the grid removes it, and
    converges the hand-authored values onto the same ones the layout engine's
    ``_grid_contact`` produces (``0.25 → 0.2564``, ``0.5 → 0.5128``), so the two
    authoring paths agree. The nudge is under half a grid step, so the contact stays
    on the same face and the directional contract is unaffected.
    """
    from rule_engine.geometry import (
        Box, contact_faces, grid_resolve_contact, orthogonalise_route,
    )

    boxes = {n.id: Box(n.id, n.x, n.y, ICON_SIZE, ICON_SIZE) for n in nodes}
    out: List[Edge] = []
    for e in edges:
        src, tgt = boxes.get(e.source), boxes.get(e.target)
        if src is None or tgt is None:
            out.append(e)
            continue
        exit_abs, exit_frac = grid_resolve_contact(src, e.exit)
        entry_abs, entry_frac = grid_resolve_contact(tgt, e.entry)
        pts = orthogonalise_route(
            exit_abs, e.points, entry_abs,
            contact_faces(*exit_frac), contact_faces(*entry_frac),
        )
        out.append(
            Edge(
                id=e.id, source=e.source, target=e.target, marker=e.marker,
                dashed=e.dashed, peering=e.peering, exit=exit_frac, entry=entry_frac,
                points=tuple(pts),
            )
        )
    return out


def edge_cell(e: Edge, parent: str = "1", origin: Tuple[float, float] = (0, 0),
              skin: "Skin | None" = None) -> str:
    """Emit one edge cell. ``parent`` / ``origin``: the cell the edge is a child
    of and that cell's absolute origin — draw.io stores an edge's waypoints
    relative to its parent, so they are written as ``point - origin``.

    ``skin``: when it carries ``edge_stroke`` a ``strokeColor=<hex>`` token is
    appended; ``None`` / an unset ``edge_stroke`` emits NO colour token — the
    exact 1.10.12 byte output (draw.io default black)."""
    dash = "dashed=1;" if (e.dashed or e.peering) else ""
    ex, ey = e.exit
    nx, ny = e.entry
    if e.peering:
        # Theme 16: a peering link is symmetric and undirected — a dashed line
        # with NO head on either end. startArrow=none + endArrow=none passes
        # arrow-style (none is accepted) and edge-bidirectional (either-none →
        # not double-headed). Keeps the orthogonal routing + contact contract.
        heads = "startArrow=none;startFill=0;endArrow=none;endFill=0;"
    else:
        # Open arrowhead (endArrow=open;endFill=0) and a >= 1pt stroke, per AWS
        # diagram conventions (diagram-standards "Accessibility & Contrast" /
        # arrow-style lint rule): open pointers read cleaner than heavy filled
        # heads and the stroke stays visible when scaled down.
        heads = "endArrow=open;endFill=0;"
    # Style channel: an explicit edge colour from the skin. Appended LAST so it
    # never reorders the existing tokens; absent → no token (byte-identical).
    stroke = ""
    if skin is not None and skin.edge_stroke:
        stroke = f"strokeColor={skin.edge_stroke};"
    style = (
        f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;{heads}"
        f"strokeWidth={EDGE_STROKE_WIDTH};{dash}{stroke}"
        f"exitX={ex};exitY={ey};exitDx=0;exitDy=0;exitPerimeter=0;"
        f"entryX={nx};entryY={ny};entryDx=0;entryDy=0;"
        "fontSize=12;fontStyle=1"
    )
    head = (
        f'        <mxCell id="{e.id}" value="{_xml_escape(e.marker)}" style="{style}" '
        f'edge="1" parent="{parent}" source="{e.source}" target="{e.target}">\n'
    )
    if e.points:
        ox, oy = origin
        pts = "".join(
            f'              <mxPoint x="{px - ox:.2f}" y="{py - oy:.2f}" />\n'
            for px, py in e.points
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


def text_cell(cid: str, lines: Sequence[str], x: int, y: int, w: int = 320, h: int = 200,
              skin: "Skin | None" = None) -> str:
    value = "&#10;".join(_xml_escape(line) for line in lines)
    style = _TEXT_STYLE
    # Style channel: swap the furniture border colour. Default skin (or None)
    # keeps strokeColor=#000000, so the emitted style is byte-identical. Only a
    # non-black furniture_stroke rewrites the single strokeColor token in place,
    # preserving token order (fillColor and spacing are untouched).
    if skin is not None and skin.furniture_stroke != "black":
        style = _TEXT_STYLE.replace("strokeColor=#000000", f"strokeColor={skin.furniture_stroke_hex()}")
    return (
        f'        <mxCell id="{cid}" value="{value}" style="{style}" '
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
    # 1.10.3: boundaries are named by NESTING and caption, not by line style —
    # AWS Account / VPC are solid vendor groups, Azure's VNet is dotted, OCI's
    # Region is filled. "Dashed" was wrong on every provider but generic.
    "Outer boundary = stack Boundary (captioned; provider style)",
    "Inner boundary = Network Boundary (captioned; provider style)",
    "Numbered markers (1..N) = ordered data flow steps; see Flow list",
)

#: The Legend lines that name a boundary, and the boundary kind each requires.
_OUTER_BOUNDARY_LINE = "Outer boundary = stack Boundary (captioned; provider style)"
_INNER_BOUNDARY_LINE = "Inner boundary = Network Boundary (captioned; provider style)"


def legend_lines_for(boundaries: Sequence[Boundary]) -> Tuple[str, ...]:
    """Return the standard Legend lines for the boundaries actually drawn (1.10.7).

    The outer/inner boundary lines are required only when that boundary is on the
    canvas (diagram-standards → Mandatory Legend Block): ``Outer boundary = …``
    needs an ``account`` box and ``Inner boundary = …`` a ``vpc`` box. When no
    boundary declares a ``kind`` (a hand-authored builder that never set one) the
    legend is :data:`STANDARD_LEGEND_LINES` unchanged; with no boundaries at all,
    or with kinds declared, a line whose boundary is absent is dropped.
    """
    kinds = {b.kind for b in boundaries}
    if boundaries and kinds == {""}:
        return STANDARD_LEGEND_LINES
    drop = set()
    if "account" not in kinds:
        drop.add(_OUTER_BOUNDARY_LINE)
    if "vpc" not in kinds:
        drop.add(_INNER_BOUNDARY_LINE)
    return tuple(line for line in STANDARD_LEGEND_LINES if line not in drop)


def _node_membership(
    nodes: Sequence["Node"], boundaries: Sequence["Boundary"]
) -> Dict[str, Tuple[str, int, int]]:
    """Map node id -> (host boundary id, host x, host y) for structural nesting.

    Wave C (container-cell model): a node is a *structural member* of the
    tightest Boundary that geometrically contains its icon box. Emitting it as a
    child of that boundary (``parent=<id>`` + geometry relative to the host
    origin) makes membership checkable (Theme 27) while — per the proven spike —
    keeping every absolute position, hence every lint verdict and the raster,
    identical. A node contained by NO boundary (an external actor to the left /
    above) keeps ``parent="1"`` and is absent from the map.

    Containment is the icon box (not the caption): a boundary wraps its members'
    icons, and the label band hangs below. Ties (equal area) are impossible for
    well-formed nested boundaries; the smallest-area winner is deterministic.
    """
    host: Dict[str, Tuple[str, int, int]] = {}
    for n in nodes:
        best_id, best_x, best_y, best_area = None, 0, 0, None
        for b in boundaries:
            if (
                b.x <= n.x
                and b.y <= n.y
                and n.x + ICON_SIZE <= b.x + b.w
                and n.y + ICON_SIZE <= b.y + b.h
            ):
                area = b.w * b.h
                if best_area is None or area < best_area:
                    best_id, best_x, best_y, best_area = b.id, b.x, b.y, area
        if best_id is not None:
            host[n.id] = (best_id, best_x, best_y)
    return host


#: Theme 43 — body aspect at/above which the Flow/Legend move BELOW the body as
#: a right-aligned horizontal row (Mode B) instead of a right-margin top stack
#: (Mode A). Calibrated on the SEP + shipped corpus: every shipped golden body is
#: <= 2.02, SEP 02/06/07 are >= 2.50, so 2.2 is a clean separating threshold and
#: no golden crosses it (an engine-level rule stays byte-inert on the corpus).
ASPECT_LEGEND_BELOW = 2.2


def theme43_legend_placement(
    nodes: Sequence["Node"],
    boundaries: Sequence["Boundary"],
    flow_lines: Sequence[str],
    legend_lines: Sequence[str],
    legend_w: int,
    *,
    pad: int = CONTAINER_PAD,
    engine_legend_x: int | None = None,
    edges: Sequence["Edge"] = (),
):
    """Aspect-driven Flow/Legend placement (Theme 43).

    Returns ``(legend_x, legend_y_flow, legend_mode, page_w, page_h)``.

    The subject body is every node icon + boundary box (NOT the legend). When the
    body is squarish or tall (``aspect < ASPECT_LEGEND_BELOW``) use **Mode A**: the
    two boxes stack in the right margin, their shared left edge one pad past the
    body's right edge, TOP-aligned to the body top. When the body is physically
    wide-and-short (``aspect >= ASPECT_LEGEND_BELOW``) use **Mode B**: the two
    boxes sit side-by-side BELOW the body — kept below (not right of) the body so
    the legend never drives the canvas width (the flow 1600px raster budget holds).

    Mode B, 1.10.12 WS6 (C9): the row is LEFT-aligned with the body and starts
    one pad below the body's lowest node caption, container or edge waypoint
    (``edges``, optional). Before, it was right-aligned and a full row step
    below the bare icons, which left the lower-left quadrant of SEP 02/06/07
    empty (the largest empty rectangle of the canvas). ``legend-placement``
    accepts a box that sits below the whole body."""
    from rule_engine.geometry import caption_band

    rights = [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes]
    lefts = [b.x for b in boundaries] + [n.x for n in nodes]
    tops = [b.y for b in boundaries] + [n.y for n in nodes]
    bottoms = [b.y + b.h for b in boundaries] + [n.y + ICON_SIZE for n in nodes]
    # Mode B clears the real body bottom: node captions and edge waypoints too.
    low = list(bottoms)
    low += [n.y + ICON_SIZE + caption_band(n.label) for n in nodes]
    low += [p[1] for e in edges for p in (e.points or ())]
    body_left = min(lefts, default=0)
    body_right = max(rights, default=0)
    body_top = min(tops, default=0)
    body_bottom = max(bottoms, default=0)
    body_w = body_right - body_left
    body_h = body_bottom - body_top
    aspect = (body_w / body_h) if body_h else 1.0

    # Box heights: a line-count estimate (the renderer uses ~16px/line plus the
    # box's own top/bottom padding). This only sizes the page and the stack gap;
    # the exact wrapped height is build_diagram's own `_text_h`, which lays the
    # cells. A small over-estimate is harmless (slightly taller page).
    _LINE = 16
    flow_h = len(tuple(flow_lines)) * _LINE + 2 * pad
    legend_h = len(tuple(legend_lines)) * _LINE + 2 * pad

    if aspect >= ASPECT_LEGEND_BELOW:
        # Mode B — side-by-side row below the body, left edge = body left.
        row_w = 2 * legend_w + GRID
        legend_x = int(body_left)
        legend_y_flow = int(-(-(max(low, default=body_bottom) + pad) // GRID) * GRID)
        legend_mode = "row-below"
        row_bottom = legend_y_flow + max(flow_h, legend_h)
        page_w = int(max(body_right, legend_x + row_w)) + 2 * pad
        page_h = int(row_bottom) + 2 * pad
    else:
        # Mode A — right-margin vertical stack, top-aligned to the body top.
        # Use the engine's caption-safe right-margin x (``place_legend_for`` already
        # clears node captions that overhang the icon right edge) as the floor, so
        # the stack never lands on a caption or an edge that reaches a right-side
        # node — falling back to body_right+pad only when no engine value is given.
        legend_x = int(max(body_right + pad, engine_legend_x or 0))
        legend_y_flow = int(body_top)
        legend_mode = "stack"
        stack_bottom = legend_y_flow + flow_h + GRID + legend_h
        page_w = int(legend_x + legend_w) + 2 * pad
        page_h = int(max(body_bottom, stack_bottom)) + 2 * pad
    return legend_x, legend_y_flow, legend_mode, page_w, page_h


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
    legend_lines: Sequence[str] | None = None,
    legend_mode: str = "stack",
    page_w: int = 1850,
    page_h: int = 950,
    caption_safe: bool = True,
    caption_plan=None,
    skin: "Skin | None" = None,
) -> str:
    """Assemble a full ``.drawio`` document from the standard building blocks.

    Every route is orthogonalised (:func:`_orthogonalised`). Then, with
    ``caption_safe`` (the default), every edge whose route strikes its OWN
    source or target caption is re-routed via the side corridor (Variant A,
    :func:`rule_engine.caption_routing.plan_caption_safe_routes`, 1.10.12 WS2),
    judged on the finished document so the caption widths and obstacles are the
    linter's; a re-route is kept only when it adds no crossing and no routing
    finding. A container whose right-edge node needs a side corridor grows
    right/down to hold it (with its ancestors and the right-margin Flow/Legend). The layout engine's oracle serializes candidates with
    ``caption_safe=False`` so it keeps judging the geometry it routed.

    ``caption_plan`` (from :func:`caption_safe_plan`) applies a precomputed
    plan instead of planning on this document.

    Edges are drawn beneath the vertices (:func:`_edge_slots`), so a node's
    caption background masks any line that still passes under its name.

    Numbered flow markers are de-collided from each other and slid along their
    own edge off any foreign edge's line (``orthogonalise.marker_hygiene_text``,
    1.10.7). The pass is idempotent and leaves the document byte-identical when
    no marker collides.
    """
    # 1.10.12 WS6: a boundary narrower than its caption grows right into free
    # space or wraps the caption (a no-op on layout() output, which is fitted).
    boundaries = fit_boundary_captions(
        boundaries, nodes, edges, legend_x if legend_mode != "row-below" else None)
    kwargs = dict(
        diagram_id=diagram_id, diagram_name=diagram_name, title=title,
        boundaries=boundaries, nodes=nodes, flow_lines=flow_lines,
        legend_x=legend_x, legend_y_flow=legend_y_flow,
        legend_y_legend=legend_y_legend, legend_w=legend_w,
        legend_lines=legend_lines, legend_mode=legend_mode,
        page_w=page_w, page_h=page_h,
        skin=skin,
    )
    routed = _orthogonalised(edges, nodes)
    text = _assemble_document(routed=routed, **kwargs)
    if caption_safe:
        plan = caption_plan if caption_plan is not None else _plan_from_text(text)
        safe = _apply_plan(plan, routed, boundaries, legend_x)
        if safe is not None:
            routed, kwargs["boundaries"], kwargs["legend_x"] = safe
            kwargs["nodes"] = _apply_wraps(plan, nodes)
            text = _assemble_document(routed=routed, **kwargs)
    # Flow-marker hygiene (1.10.7 D37): markers are de-collided from each other
    # and slid along their own edge off any foreign edge's line, so every
    # builder (rule-engine-draw, the HA builders, hand-written layout() +
    # build_diagram scripts) gets it. Idempotent; a no-op when nothing collides.
    # Function-local import: geometry imports this module at load time.
    from rule_engine.orthogonalise import marker_hygiene_text

    return _cover_page(marker_hygiene_text(text)[0], page_w, page_h)


def _plan_from_text(text: str):
    """The Variant A plan for an assembled document (None when unparsable).
    Function-local imports: geometry imports this module."""
    from rule_engine.caption_routing import CaptionPlan, plan_caption_safe_geo
    from rule_engine.collinear_repair import plan_collinear_shift_geo
    from rule_engine.crossing_repair import plan_crossing_repair_geo
    from rule_engine.drawio_model import DrawioParseError, parse_drawio
    from rule_engine.geometry import build_geometry

    try:
        pages = parse_drawio(text.encode("utf-8"), path="<build_diagram>")
    except DrawioParseError:
        return None
    if not pages:
        return None
    caption, work = plan_caption_safe_geo(build_geometry(pages[0]))
    # 1.10.12 WS3: the final crossing-repair pass plans on the caption-safe
    # result, so a re-route it keeps never brings a caption strike back.
    crossing, work = plan_crossing_repair_geo(work)
    # 1.10.12 WS8: the collinear-shift pass plans on the crossing-repaired
    # result, so separating two lines never re-introduces a crossing or a
    # caption strike an earlier pass removed.
    collinear, _ = plan_collinear_shift_geo(work)
    if not crossing.routes and not collinear.routes:
        return caption
    return CaptionPlan(
        routes={**caption.routes, **crossing.routes, **collinear.routes},
        containers={**caption.containers, **crossing.containers, **collinear.containers},
        text_dx=caption.text_dx + crossing.text_dx + collinear.text_dx,
        wraps=dict(caption.wraps),
    )


def _apply_plan(
    plan, routed: Sequence[Edge], boundaries: Sequence[Boundary], legend_x: int,
) -> Optional[Tuple[List[Edge], List[Boundary], int]]:
    """``(edges, boundaries, legend_x)`` with ``plan``'s re-routes, grown
    containers and right-margin legend shift applied; None when it changes
    nothing."""
    if plan is None or not plan.routes:
        return None
    out: List[Edge] = []
    for e in routed:
        if e.id in plan.routes:
            exit_frac, entry_frac, pts = plan.routes[e.id]
            e = replace(e, exit=tuple(exit_frac), entry=tuple(entry_frac), points=tuple(pts))
        out.append(e)
    bounds: List[Boundary] = []
    for b in boundaries:
        g = plan.containers.get(b.id)
        if g is not None and b.parent == "1":
            b = replace(b, w=int(math.ceil(g.right - b.x)), h=int(math.ceil(g.bottom - b.y)))
        bounds.append(b)
    return out, bounds, int(math.ceil(legend_x + plan.text_dx))


def _apply_wraps(plan, nodes: Sequence[Node]) -> List[Node]:
    """``nodes`` with the plan's wrapped captions (1.10.12 WS2). Each node's
    OWN label is wrapped (:func:`geometry.wrap_caption`, deterministic), so a
    plan computed on a representative presentation (the HA skins) wraps every
    skin at its own best break; a label with no break point stays as is."""
    wraps = getattr(plan, "wraps", None) or {}
    if not wraps:
        return list(nodes)
    from rule_engine.geometry import wrap_caption

    out: List[Node] = []
    for n in nodes:
        if n.id in wraps:
            w = wrap_caption(n.label)
            if w is not None:
                n = replace(n, label=w)
        out.append(n)
    return out


def _render_node(n: Node, parent_id: str) -> str:
    """``n``'s cell XML. A multi-line caption (a wrapped label) is written with
    ``&#10;`` line breaks: a raw newline inside an XML attribute value is
    normalised to a space by every XML parser (draw.io included), so the wrap
    would silently vanish. Renderers that escape the label (or not) are all
    covered; a one-line label is emitted byte-identically."""
    out = n.render(n, parent_id)
    if "\n" not in n.label:
        return out
    pat = re.compile(r'(<mxCell\b[^>]*?\bid="' + re.escape(n.id) + r'"[^>]*?\bvalue=")([^"]*)(")', re.S)
    return pat.sub(lambda m: m.group(1) + m.group(2).replace("\n", "&#10;") + m.group(3), out, count=1)


def caption_safe_plan(
    *,
    boundaries: Sequence[Boundary],
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    flow_lines: Sequence[str],
    legend_x: int,
    legend_y_flow: int = 120,
    legend_y_legend: int = 360,
    legend_w: int | None = None,
    legend_lines: Sequence[str] | None = None,
    legend_mode: str = "stack",
):
    """Compute the Variant A plan (:class:`rule_engine.caption_routing.CaptionPlan`)
    for a diagram without emitting it.

    A builder that renders ONE geometry under several skins (the HA examples,
    whose four providers must stay geometry-identical) computes the plan once
    on a representative presentation — the widest node labels and container
    captions any skin draws — and passes it to every :func:`build_diagram` call
    as ``caption_plan``. A route that clears the widest caption clears every
    skin's caption."""
    routed = _orthogonalised(edges, nodes)
    text = _assemble_document(
        diagram_id="plan", diagram_name="plan", title="plan",
        boundaries=boundaries, nodes=nodes, routed=routed, flow_lines=flow_lines,
        legend_x=legend_x, legend_y_flow=legend_y_flow, legend_y_legend=legend_y_legend,
        legend_w=legend_w, legend_lines=legend_lines, legend_mode=legend_mode,
        page_w=0, page_h=0,
    )
    return _plan_from_text(text)


def _is_filled(style: str) -> bool:
    """True when a boundary style paints an opaque fill (absent ``fillColor`` is
    draw.io's default white)."""
    m = re.search(r"(?:^|;)fillColor=([^;]*)", style)
    return m is None or m.group(1).strip().lower() not in ("none", "")


def _edge_polyline(e: Edge, boxes: Dict[str, Tuple[float, float]]) -> List[Tuple[float, float]]:
    s, t = boxes.get(e.source), boxes.get(e.target)
    if s is None or t is None:
        return []
    return (
        [(s[0] + e.exit[0] * ICON_SIZE, s[1] + e.exit[1] * ICON_SIZE)]
        + [tuple(p) for p in e.points]
        + [(t[0] + e.entry[0] * ICON_SIZE, t[1] + e.entry[1] * ICON_SIZE)]
    )


def _segment_meets_rect(p, q, x0: float, y0: float, x1: float, y1: float) -> bool:
    """True when the axis-aligned segment ``p``-``q`` touches the closed rectangle."""
    lo_x, hi_x = sorted((p[0], q[0]))
    lo_y, hi_y = sorted((p[1], q[1]))
    return lo_x <= x1 and hi_x >= x0 and lo_y <= y1 and hi_y >= y0


def _edge_slots(
    boundaries: Sequence[Boundary], nodes: Sequence[Node], edges: Sequence[Edge]
) -> Tuple[Dict[str, int], set]:
    """Choose where each edge sits in draw order so it renders BENEATH vertices.

    draw.io paints the model depth-first in document order. Boundaries are flat
    on the root layer and each node is a child of its tightest boundary (Wave C),
    so a node paints right after its boundary's fill, and an edge listed after
    the boundaries paints above every node — which is why the caption background
    (``labelBackgroundColor``) never masked a line (1.10.12 WS2, defect C1).

    Each edge gets the EARLIEST slot that is still above every filled boundary
    its polyline touches: slot ``-1`` (root layer, before every boundary) when it
    touches no filled one, else slot ``k`` — the first child of the last such
    boundary ``k`` in emission order, so it paints over that fill but beneath
    that boundary's nodes and every node painted after it. Unfilled boundaries
    (``fillColor=none``) may paint over an edge: only their border and caption.

    Returns ``({edge_id: slot}, masked_node_ids)``: the masked nodes are those
    painted after an edge that crosses their caption, whose caption background
    is set to the local fill so the line passes behind the name."""
    from rule_engine.geometry import Box, caption_lines, node_caption_box, segment_crosses_box

    boxes = {n.id: (n.x, n.y) for n in nodes}
    filled = [
        (i, b) for i, b in enumerate(boundaries) if _is_filled(_boundary_style(b))
    ]
    index = {b.id: i for i, b in enumerate(boundaries)}
    host = {nid: index[h[0]] for nid, h in _node_membership(nodes, boundaries).items()}
    captions = {
        n.id: node_caption_box(Box(n.id, n.x, n.y, ICON_SIZE, ICON_SIZE), n.label)
        for n in nodes if caption_lines(n.label)
    }
    slots: Dict[str, int] = {}
    masked: set = set()
    for e in edges:
        poly = _edge_polyline(e, boxes)
        slot = -1
        for i, b in filled:
            if any(_segment_meets_rect(p, q, b.x, b.y, b.x + b.w, b.y + b.h)
                   for p, q in zip(poly, poly[1:])):
                slot = max(slot, i)
        slots[e.id] = slot
        for nid, cap in captions.items():
            if host.get(nid, len(boundaries)) < slot:
                continue  # painted before the edge: it cannot mask it
            if any(segment_crosses_box(p, q, cap) for p, q in zip(poly, poly[1:])):
                masked.add(nid)
    return slots, masked


def _assemble_document(
    *,
    diagram_id: str,
    diagram_name: str,
    title: str,
    boundaries: Sequence[Boundary],
    nodes: Sequence[Node],
    routed: Sequence[Edge],
    flow_lines: Sequence[str],
    legend_x: int,
    legend_y_flow: int,
    legend_y_legend: int,
    legend_w: int | None,
    legend_lines: Sequence[str] | None,
    legend_mode: str,
    page_w: int,
    page_h: int,
    skin: "Skin | None" = None,
) -> str:
    """Emit the ``.drawio`` document for already-routed edges (no hygiene)."""
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
    # Edges beneath vertices (1.10.12 WS2): each edge is emitted either on the
    # root layer BEFORE every boundary (slot -1) or as the FIRST child of the
    # last filled boundary it touches (listed after the boundary cells, before
    # the node cells, with boundary-relative waypoints). A node painted after an
    # edge that crosses its caption gets the local fill as caption background,
    # so the line passes behind the service name instead of striking it.
    slots, masked = _edge_slots(boundaries, nodes, routed)
    if masked:
        nodes = [
            replace(n, label_bg=_local_background(n, boundaries)) if n.id in masked else n
            for n in nodes
        ]
    for e in routed:
        if slots.get(e.id, -1) < 0:
            parts.append(edge_cell(e, skin=skin))
    parts.append("\n")
    for b in _clear_container_captions(boundaries, nodes, routed):
        parts.append(boundary_cell(b))
    parts.append("\n")
    for e in routed:
        k = slots.get(e.id, -1)
        if k >= 0:
            b = boundaries[k]
            parts.append(edge_cell(e, parent=b.id, origin=(b.x, b.y), skin=skin))
    parts.append("\n")
    # Wave C: emit each node as a structural child of its tightest enclosing
    # boundary (``parent=<id>`` + geometry relative to the host origin), so
    # membership is checkable (Theme 27). A node contained by no boundary keeps
    # parent="1". Absolute positions are unchanged — draw.io resolves a child's
    # relative geometry back to the same pixels — so render and lint are identical
    # (proven by the Wave C spike).
    _host = _node_membership(nodes, boundaries)
    for n in nodes:
        hb = _host.get(n.id)
        if hb is None:
            parts.append(_render_node(n, "1"))
        else:
            host_id, hx, hy = hb
            rel = replace(n, x=n.x - hx, y=n.y - hy)
            parts.append(_render_node(rel, host_id))
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

    # A caller may extend the standard Legend (e.g. a diagram that uses an
    # overlay marker must document it — ``overlay-legend-coverage``).
    # Without an explicit list the Legend names only the boundaries drawn
    # (:func:`legend_lines_for`, 1.10.7).
    legend_body = legend_lines_for(boundaries) if legend_lines is None else tuple(legend_lines)
    # A caller may pin a narrower ``legend_w`` (the Flow/Legend blocks then wrap
    # and grow taller instead of running wide into the diagram body); otherwise
    # size to the longest line with no wrap.
    box_w = legend_w if legend_w is not None else _text_w(flow_lines, legend_body)
    flow_h = _text_h(flow_lines, legend_w)
    legend_h = _text_h(legend_body, legend_w)
    if legend_mode == "row-below":
        # Theme 43 Mode B: a physically wide-and-short diagram puts the two boxes
        # SIDE-BY-SIDE below the body, as a horizontal row whose RIGHT edge aligns
        # to the body's right edge (``legend_x`` is passed as that right edge minus
        # the row width). Flow sits left, Legend right, both at ``legend_y_flow``.
        # Keeping the row below (not right of) the body means the legend never
        # drives the canvas width, so a flow raster stays under its 1600px budget.
        flow_x = legend_x
        legend2_x = int(legend_x + box_w + GRID)
        parts.append(text_cell("flow-legend", flow_lines, flow_x, legend_y_flow, box_w, flow_h, skin=skin))
        parts.append(text_cell("legend", legend_body, legend2_x, legend_y_flow, box_w, legend_h, skin=skin))
    else:
        # Mode A (default, stack): the Legend stacks BELOW the Flow box. A caller's
        # ``legend_y_legend`` is a hint, not a guarantee: a long Flow list (or a
        # pinned narrow width, which makes it wrap taller) can grow past it and the
        # two boxes would overlap — silently, because neither is a node, so no
        # geometry rule would catch it. Push the Legend down to clear the Flow box
        # by one grid step.
        legend_y = max(legend_y_legend, legend_y_flow + flow_h + GRID)
        parts.append(text_cell("flow-legend", flow_lines, legend_x, legend_y_flow, box_w, flow_h, skin=skin))
        parts.append(text_cell("legend", legend_body, legend_x, legend_y, box_w, legend_h, skin=skin))
    parts.append(
        "      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n"
    )
    return "".join(parts)


_PAGE_SIZE_RE = re.compile(r'pageWidth="(\d+)" pageHeight="(\d+)"')


def _cover_page(text: str, page_w: int, page_h: int) -> str:
    """Grow ``pageWidth`` / ``pageHeight`` so the page covers everything drawn.

    1.10.12 WS1 (defect C14): a caller's page size is an estimate made before
    the text boxes were sized and the edges routed, so a long Flow list or a
    wide caption could end below / right of the page (SEP 05: pageHeight 602
    vs a content bottom of 750). The finished document is measured with the
    linter's own parser (:func:`rule_engine.geometry.content_bbox`) and each
    axis is raised, never lowered, to the content edge plus one container pad,
    rounded up to the grid. A page that already covers its content is left
    byte-identical."""
    from rule_engine.drawio_model import DrawioParseError, parse_drawio
    from rule_engine.geometry import build_geometry, content_bbox

    try:
        pages = parse_drawio(text.encode("utf-8"), path="<build_diagram>")
    except DrawioParseError:
        return text
    if not pages:
        return text
    bb = content_bbox(build_geometry(pages[0]))
    if bb is None:
        return text

    def _cover(current: int, edge: float) -> int:
        if current >= edge:
            return current
        need = math.ceil(edge) + CONTAINER_PAD
        return int(-(-need // GRID) * GRID)

    new_w, new_h = _cover(page_w, bb.right), _cover(page_h, bb.bottom)
    if (new_w, new_h) == (page_w, page_h):
        return text
    return _PAGE_SIZE_RE.sub(
        f'pageWidth="{new_w}" pageHeight="{new_h}"', text, count=1
    )


__all__ = [
    "ICON_SIZE", "GRID", "COL_STEP", "ROW_STEP", "CONTAINER_PAD",
    "STACK_BOUNDARY_STROKE", "NETWORK_BOUNDARY_STROKE",
    "Node", "Edge", "Boundary", "IconRenderer",
    "builtin_icon", "embed_oci_stencil", "OciStencilIcon", "OciStencilError",
    "title_cell", "boundary_cell", "edge_cell", "text_cell",
    "STANDARD_LEGEND_LINES", "legend_lines_for", "build_diagram", "caption_safe_plan",
    "fit_boundary_captions",
    "OVERLAY_LEGEND_LINES", "overlay_legend_lines",
]
