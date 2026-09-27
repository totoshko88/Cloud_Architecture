"""Shared Hypothesis strategies for the honest-gates property tests.

Feature: honest-gates (release 1.7.0), task 1.1 — shared test infrastructure.

This module is **test-only code**. It provides the generators and the small,
self-contained serializers/encoders that the R1–R8 property tests build on:

* a ``.drawio`` diagram-model strategy plus a serializer
  (:func:`serialize_drawio`) that emits plain, compressed, multi-page,
  ``UserObject``/``object``-wrapped, HTML-labelled diagrams — everything
  ``rule_engine.drawio_model.parse_drawio`` must read (Property 1–7);
* a KB-document structure model plus a renderer (:func:`render_kb_document`)
  driven by section word counts, the four required sections, H1 count, list
  depth, table shape, fenced blocks and an Anti-patterns section (Property
  8–10);
* JSON-value strategies: :func:`benign_json` and :func:`plant_secret`, the
  latter returning ``(value, json_pointer)`` so a test knows exactly where the
  secret was planted (Property 11–14);
* a native-resource strategy with key-case and separator transforms
  (Property 18);
* init source / target / lock tree strategies (Requirement 7);
* a minimal PNG encoder (:func:`encode_png`) writing IHDR / IDAT / tEXt / tRNS /
  IEND with a selectable colour type and row-0 filter (Property/example tests
  for R8).

The serializers here are deliberately independent of the production parser: a
round-trip property that used the parser to build its own input would only prove
the parser is self-consistent. By authoring the ``.drawio`` bytes directly, the
strategy pins the *wire format* draw.io itself produces, so the round-trip
property tests exercise the real contract.
"""

from __future__ import annotations

import base64
import struct
import urllib.parse
import zlib
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Mapping, Optional, Tuple

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st


def _ensure_profiles() -> None:
    """Register the honest-gates Hypothesis profiles if they are not already.

    ``conftest.py`` registers and loads them for the pytest run, but importing
    this module on its own (a REPL, an ad-hoc script) must not fail. Registration
    is idempotent, so calling this from both places is safe.
    """
    suppress = [HealthCheck.function_scoped_fixture]
    try:
        settings.get_profile("honest-gates")
    except Exception:
        settings.register_profile(
            "honest-gates", max_examples=100, suppress_health_check=suppress
        )
    try:
        settings.get_profile("honest-gates-fs")
    except Exception:
        settings.register_profile(
            "honest-gates-fs",
            max_examples=100,
            deadline=None,
            suppress_health_check=suppress,
        )


_ensure_profiles()

# Re-export the filesystem profile so a test can write
# ``@fs_settings`` instead of re-deriving it from the registry.
fs_settings = settings.get_profile("honest-gates-fs")

__all__ = [
    "fs_settings",
    # diagram model
    "Geom",
    "CellModel",
    "PageModel",
    "DiagramModel",
    "geoms",
    "cell_models",
    "page_models",
    "diagram_models",
    "serialize_page",
    "serialize_drawio",
    "compress_payload",
    "xml_escape",
    # KB documents
    "SectionModel",
    "KbStructureModel",
    "kb_structure_models",
    "render_kb_document",
    "render_kb_document_body",
    "frontmatter_mappings",
    "render_frontmatter",
    "REQUIRED_SECTIONS",
    "FRONTMATTER_KEYS",
    # JSON / secrets
    "benign_json",
    "benign_scalar",
    "plant_secret",
    "SECRET_SHAPES",
    "BENIGN_KEYS",
    "CREDENTIAL_KEYS",
    "recase_key",
    # native resources
    "native_resources",
    "key_case_transforms",
    "apply_key_transform",
    # init trees
    "file_trees",
    "InitScenario",
    "init_scenarios",
    # PNG
    "encode_png",
    "png_models",
    "PngModel",
]


# =========================================================================== #
# 1. `.drawio` diagram model + serializer
# =========================================================================== #
#
# The model mirrors the shape of ``rule_engine.drawio_model`` (Geom / Cell /
# Page) closely enough that a round-trip test can compare field for field, but
# it is an independent test type so the serializer is the authority on the wire
# format.


@dataclass(frozen=True)
class Geom:
    """A cell geometry. ``None`` for a coordinate means it is omitted from the
    serialized ``mxGeometry`` (the parser reads a missing coordinate as 0)."""

    x: Optional[float] = 0.0
    y: Optional[float] = 0.0
    w: Optional[float] = 0.0
    h: Optional[float] = 0.0
    relative: bool = False
    points: Tuple[Tuple[float, float], ...] = ()
    source_point: Optional[Tuple[float, float]] = None
    target_point: Optional[Tuple[float, float]] = None
    # A label `offset` point that the parser must ignore (R1.6).
    offset_point: Optional[Tuple[float, float]] = None

    def expected(self) -> Tuple[float, float, float, float]:
        """The (x, y, w, h) the parser should report (omitted -> 0)."""
        return (
            self.x or 0.0,
            self.y or 0.0,
            self.w or 0.0,
            self.h or 0.0,
        )


@dataclass(frozen=True)
class CellModel:
    """A model of one ``mxCell`` (optionally wrapped in a UserObject/object)."""

    id: str
    parent: str = "1"
    label: str = ""
    style: str = ""
    vertex: bool = False
    edge: bool = False
    source: Optional[str] = None
    target: Optional[str] = None
    geom: Optional[Geom] = None
    wrapper: Optional[str] = None  # "UserObject" | "object" | None
    wrapper_attrs: Mapping[str, str] = field(default_factory=dict)
    # When True the label is emitted as HTML (with html=1 folded into the style)
    # and `label` is treated as the *decoded plain text* we expect back.
    html_label: bool = False

    @property
    def effective_style(self) -> str:
        """Style actually written, folding in ``html=1`` for an HTML label."""
        if self.html_label and "html=1" not in self.style:
            base = self.style.rstrip(";")
            return f"{base};html=1" if base else "html=1"
        return self.style

    @property
    def expected_label(self) -> str:
        """The decoded, line-stripped label the parser should return."""
        lines = [ln.strip() for ln in self.label.split("\n")]
        return "\n".join(lines)


@dataclass(frozen=True)
class PageModel:
    """A model of one ``<diagram>`` page."""

    name: str
    cells: Tuple[CellModel, ...] = ()
    grid_size: Optional[int] = None  # None -> attribute omitted (parser -> 10)
    compressed: bool = False
    page_id: str = ""

    @property
    def expected_grid(self) -> int:
        return 10 if self.grid_size is None else self.grid_size


@dataclass(frozen=True)
class DiagramModel:
    """A model of a whole ``.drawio`` file (one or more pages)."""

    pages: Tuple[PageModel, ...]
    # When True and there is exactly one page, serialize as a bare
    # <mxGraphModel> (no <mxfile>/<diagram> wrapper).
    bare: bool = False


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def xml_escape(text: str) -> str:
    """Escape a string for use in an XML attribute value (double-quoted).

    Newlines and tabs are written as numeric character references. XML
    attribute-value normalisation turns a literal newline/tab into a space, so a
    label carrying real line breaks (which draw.io stores as ``&#10;``) only
    survives when encoded this way.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "&#10;")
        .replace("\t", "&#9;")
    )


def compress_payload(model_xml: str) -> str:
    """Encode an inner ``<mxGraphModel>`` as a draw.io compressed page body.

    ``base64(deflateRaw(encodeURIComponent(<mxGraphModel>)))`` — the exact
    pipeline ``drawio_model.decode_compressed`` reverses.
    """
    quoted = urllib.parse.quote(model_xml, safe="")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = compressor.compress(quoted.encode("utf-8")) + compressor.flush()
    return base64.b64encode(raw).decode("ascii")


def _attr_escape(text: str) -> str:
    """Escape a string for an XML attribute value without newline handling."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _serialize_label_html(plain: str) -> str:
    """Render plain text as an HTML label stored in an XML ``value`` attribute.

    draw.io stores an HTML label XML-escaped inside the ``value`` attribute
    (``&lt;br&gt;`` for a break); expat decodes the entities, then the parser's
    HTML stripper turns ``<br>`` back into a line break. So the whole assembled
    HTML markup is XML-escaped here. Only reversible constructs are used
    (literal text and ``<br>`` breaks) so the round trip is exact while still
    exercising the HTML path (tag stripping + ``html.unescape``).
    """
    import html as _html

    # HTML-escape the literal text first (so a literal '<' becomes '&lt;' at the
    # HTML level and is NOT mistaken for a tag by the stripper), join lines with
    # a real <br> tag, then XML-escape the whole markup for the attribute.
    escaped_lines = [_html.escape(line, quote=True) for line in plain.split("\n")]
    html_markup = "<br>".join(escaped_lines)
    return _attr_escape(html_markup)


def _serialize_geom(geom: Geom) -> str:
    attrs: List[str] = []
    if geom.x is not None:
        attrs.append(f'x="{_num(geom.x)}"')
    if geom.y is not None:
        attrs.append(f'y="{_num(geom.y)}"')
    if geom.w is not None:
        attrs.append(f'width="{_num(geom.w)}"')
    if geom.h is not None:
        attrs.append(f'height="{_num(geom.h)}"')
    if geom.relative:
        attrs.append('relative="1"')
    attrs.append('as="geometry"')
    head = f"<mxGeometry {' '.join(attrs)}>"
    body: List[str] = []
    if geom.points:
        body.append('<Array as="points">')
        for px, py in geom.points:
            body.append(f'<mxPoint x="{_num(px)}" y="{_num(py)}" />')
        body.append("</Array>")
    if geom.source_point is not None:
        sx, sy = geom.source_point
        body.append(f'<mxPoint x="{_num(sx)}" y="{_num(sy)}" as="sourcePoint" />')
    if geom.target_point is not None:
        tx, ty = geom.target_point
        body.append(f'<mxPoint x="{_num(tx)}" y="{_num(ty)}" as="targetPoint" />')
    if geom.offset_point is not None:
        ox, oy = geom.offset_point
        body.append(f'<mxPoint x="{_num(ox)}" y="{_num(oy)}" as="offset" />')
    if not body:
        return f"<mxGeometry {' '.join(attrs)} />"
    return head + "".join(body) + "</mxGeometry>"


def _num(value: float) -> str:
    """Render a number without a trailing ``.0`` for integral values."""
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def _serialize_cell(cell: CellModel) -> str:
    style = cell.effective_style
    if cell.wrapper:
        # UserObject/object carries id + label; the inner mxCell has neither.
        wattrs = [f'id="{xml_escape(cell.id)}"']
        if cell.html_label:
            wattrs.append(f'label="{_serialize_label_html(cell.label)}"')
        else:
            wattrs.append(f'label="{xml_escape(cell.label)}"')
        for k, v in cell.wrapper_attrs.items():
            wattrs.append(f'{k}="{xml_escape(v)}"')
        inner = _serialize_inner_cell(cell, style, with_id=False, with_value=False)
        return (
            f"<{cell.wrapper} {' '.join(wattrs)}>{inner}</{cell.wrapper}>"
        )
    return _serialize_inner_cell(cell, style, with_id=True, with_value=True)


def _serialize_inner_cell(
    cell: CellModel, style: str, *, with_id: bool, with_value: bool
) -> str:
    attrs: List[str] = []
    if with_id:
        attrs.append(f'id="{xml_escape(cell.id)}"')
    if with_value and cell.label:
        if cell.html_label:
            attrs.append(f'value="{_serialize_label_html(cell.label)}"')
        else:
            attrs.append(f'value="{xml_escape(cell.label)}"')
    if style:
        attrs.append(f'style="{xml_escape(style)}"')
    attrs.append(f'parent="{xml_escape(cell.parent)}"')
    if cell.vertex:
        attrs.append('vertex="1"')
    if cell.edge:
        attrs.append('edge="1"')
    if cell.source is not None:
        attrs.append(f'source="{xml_escape(cell.source)}"')
    if cell.target is not None:
        attrs.append(f'target="{xml_escape(cell.target)}"')
    head = f"<mxCell {' '.join(attrs)}"
    if cell.geom is not None:
        return head + ">" + _serialize_geom(cell.geom) + "</mxCell>"
    return head + " />"


def _serialize_model(page: PageModel) -> str:
    """Serialize a page's inner ``<mxGraphModel>`` (with the two root layers)."""
    grid = "" if page.grid_size is None else f' gridSize="{page.grid_size}"'
    cells = "".join(_serialize_cell(c) for c in page.cells)
    return (
        f"<mxGraphModel{grid}>"
        f"<root>"
        f'<mxCell id="0" />'
        f'<mxCell id="1" parent="0" />'
        f"{cells}"
        f"</root>"
        f"</mxGraphModel>"
    )


def serialize_page(page: PageModel) -> str:
    """Serialize one page as a ``<diagram>`` element (plain or compressed)."""
    name = xml_escape(page.name)
    pid = f' id="{xml_escape(page.page_id)}"' if page.page_id else ""
    if page.compressed:
        payload = compress_payload(_serialize_model(page))
        return f'<diagram name="{name}"{pid}>{payload}</diagram>'
    return f'<diagram name="{name}"{pid}>{_serialize_model(page)}</diagram>'


def serialize_drawio(model: DiagramModel) -> str:
    """Serialize a whole diagram model to ``.drawio`` XML text."""
    if model.bare and len(model.pages) == 1 and not model.pages[0].compressed:
        return _serialize_model(model.pages[0])
    body = "".join(serialize_page(p) for p in model.pages)
    return f"<mxfile>{body}</mxfile>"


# --------------------------------------------------------------------------- #
# Diagram-model strategies
# --------------------------------------------------------------------------- #

#: Identifier alphabet for cell/page ids: kept to the unquoted-safe set so ids
#: never need escaping and stay valid draw.io ids.
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"

_ids = st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=12)

#: Coordinate values on a coarse grid so a round trip through ``_num`` is exact
#: (float repr round trips, but integral coordinates keep the payload readable).
_coords = st.integers(min_value=-2000, max_value=4000).map(float)

#: Label text that deliberately includes XML-special characters and internal
#: whitespace. Leading/trailing whitespace on a line is stripped by the parser,
#: so the model's ``expected_label`` accounts for it; we still generate it to
#: exercise the stripping.
_label_chars = st.characters(
    blacklist_categories=("Cs", "Cc"),
    blacklist_characters="\r\x0b\x0c\x00",
)
_label_lines = st.text(alphabet=_label_chars, min_size=0, max_size=24)
_labels = st.lists(_label_lines, min_size=0, max_size=3).map("\n".join)


@st.composite
def geoms(draw: st.DrawFn, *, edge: bool = False) -> Geom:
    """Generate a :class:`Geom`.

    Any of x/y/w/h may be omitted (``None``) to exercise the "missing
    coordinate reads as 0" rule. Edges additionally get waypoints plus decoy
    source/target/offset points the parser must keep separate or ignore.
    """
    def opt_coord() -> Optional[float]:
        return draw(st.one_of(st.none(), _coords))

    points: Tuple[Tuple[float, float], ...] = ()
    source_point = None
    target_point = None
    offset_point = None
    if edge:
        pts = draw(
            st.lists(st.tuples(_coords, _coords), min_size=0, max_size=4)
        )
        points = tuple(pts)
        source_point = draw(st.one_of(st.none(), st.tuples(_coords, _coords)))
        target_point = draw(st.one_of(st.none(), st.tuples(_coords, _coords)))
        offset_point = draw(st.one_of(st.none(), st.tuples(_coords, _coords)))
    return Geom(
        x=opt_coord(),
        y=opt_coord(),
        w=opt_coord(),
        h=opt_coord(),
        relative=draw(st.booleans()),
        points=points,
        source_point=source_point,
        target_point=target_point,
        offset_point=offset_point,
    )


#: A small set of realistic, parseable styles. ``shape=stencil(a;b)`` exercises
#: the "split only outside parentheses" rule; a bare leading token exercises the
#: ``{token: ""}`` structural-key rule.
_styles = st.sampled_from(
    [
        "",
        "rounded=1;whiteSpace=wrap;",
        "text;html=1;strokeColor=none;fillColor=none;",
        "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;",
        "group;",
        "shape=stencil(H4sIAAA;foo=bar);verticalLabelPosition=bottom;",
        "edgeStyle=orthogonalEdgeStyle;html=1;",
    ]
)


@st.composite
def cell_models(
    draw: st.DrawFn,
    *,
    cell_id: str,
    parent: str = "1",
    allow_wrapper: bool = True,
) -> CellModel:
    """Generate a vertex :class:`CellModel` with the given id/parent."""
    style = draw(_styles)
    html_label = draw(st.booleans())
    label = draw(_labels)
    wrapper = None
    wrapper_attrs: Dict[str, str] = {}
    if allow_wrapper and draw(st.booleans()):
        wrapper = draw(st.sampled_from(["UserObject", "object"]))
        if draw(st.booleans()):
            wrapper_attrs = {
                "tooltip": draw(st.text(alphabet=_label_chars, max_size=10)),
            }
    return CellModel(
        id=cell_id,
        parent=parent,
        label=label,
        style=style,
        vertex=True,
        edge=False,
        geom=draw(st.one_of(st.none(), geoms())),
        wrapper=wrapper,
        wrapper_attrs=wrapper_attrs,
        html_label=html_label,
    )


@st.composite
def page_models(
    draw: st.DrawFn,
    *,
    name: Optional[str] = None,
    force_compressed: Optional[bool] = None,
) -> PageModel:
    """Generate a :class:`PageModel` with unique cell ids and valid parents.

    Vertices are chained into a random parent forest rooted at the ``"1"`` layer
    so ``absolute_origin`` has real chains to walk (and never a cycle). One or
    two edges may reference existing vertices.
    """
    page_name = name if name is not None else draw(_ids)
    n_vertices = draw(st.integers(min_value=0, max_value=5))
    raw_ids = draw(
        st.lists(_ids, min_size=n_vertices, max_size=n_vertices, unique=True)
    )
    cells: List[CellModel] = []
    placed: List[str] = ["1"]
    for cid in raw_ids:
        parent = draw(st.sampled_from(placed))
        cell = draw(cell_models(cell_id=cid, parent=parent))
        cells.append(cell)
        placed.append(cid)

    # Optional edges between existing vertices.
    vertex_ids = [c.id for c in cells]
    n_edges = draw(st.integers(min_value=0, max_value=2)) if vertex_ids else 0
    for _ in range(n_edges):
        eid = draw(_ids.filter(lambda x, taken=set(placed): x not in taken))
        placed.append(eid)
        src = draw(st.sampled_from(vertex_ids))
        tgt = draw(st.sampled_from(vertex_ids))
        cells.append(
            CellModel(
                id=eid,
                parent="1",
                label=draw(_labels),
                style="edgeStyle=orthogonalEdgeStyle;",
                edge=True,
                source=src,
                target=tgt,
                geom=draw(geoms(edge=True)),
            )
        )

    compressed = (
        draw(st.booleans()) if force_compressed is None else force_compressed
    )
    grid = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=50)))
    page_id = draw(st.one_of(st.just(""), _ids))
    return PageModel(
        name=page_name,
        cells=tuple(cells),
        grid_size=grid,
        compressed=compressed,
        page_id=page_id,
    )


@st.composite
def diagram_models(
    draw: st.DrawFn,
    *,
    min_pages: int = 1,
    max_pages: int = 3,
    allow_bare: bool = True,
    allow_duplicate_names: bool = True,
) -> DiagramModel:
    """Generate a whole :class:`DiagramModel` (one or more pages)."""
    n = draw(st.integers(min_value=min_pages, max_value=max_pages))
    if allow_duplicate_names:
        names = draw(
            st.lists(_ids, min_size=n, max_size=n)
        )
    else:
        names = draw(st.lists(_ids, min_size=n, max_size=n, unique=True))
    pages = tuple(draw(page_models(name=nm)) for nm in names)
    bare = allow_bare and n == 1 and draw(st.booleans())
    return DiagramModel(pages=pages, bare=bare)


# =========================================================================== #
# 2. KB documents: frontmatter + structure model
# =========================================================================== #
#
# Property 8 (frontmatter) and Property 9 (structure) generate a model and
# assert the validator's verdict matches the model. The renderer must therefore
# produce a document whose *computable* properties (word counts, H1 count, list
# depth, table shape, fenced blocks, sections) are exactly what the model says.

#: The four required section headings (kb-frontmatter.md), casefold-compared.
REQUIRED_SECTIONS: Tuple[str, ...] = (
    "Overview",
    "Main Content",
    "Troubleshooting",
    "See Also",
)

#: A pool of single "words" (no whitespace) used to hit an exact word count.
_WORD = "lorem"


def _words(n: int) -> str:
    """A run of ``n`` whitespace-separated words (n >= 0)."""
    if n <= 0:
        return ""
    return " ".join([_WORD] * n)


@dataclass(frozen=True)
class SectionModel:
    """One required section with a target word count (words in its body)."""

    title: str
    word_count: int
    present: bool = True


@dataclass(frozen=True)
class KbStructureModel:
    """A structural model of a KB document body (everything after frontmatter).

    Every field maps to one validator constraint so a test can compute the
    expected violation set directly from the model.
    """

    sections: Tuple[SectionModel, ...]
    # extra prose words placed before the first section, to tune doc-length
    lead_words: int = 0
    h1_count: int = 1
    list_depth: int = 0          # 0 = no list; N = deepest nesting level
    table_columns: int = 0       # 0 = no table; else delimiter-row cell count
    table_ragged: bool = False   # a body row with a different cell count
    fenced_block: bool = False
    anti_patterns: bool = False


def _kb_section_models(draw: st.DrawFn) -> Tuple[SectionModel, ...]:
    out: List[SectionModel] = []
    for title in REQUIRED_SECTIONS:
        present = draw(st.booleans()) if draw(st.integers(0, 4)) == 0 else True
        # Word counts straddle the 100-200 band so section-length fires both ways.
        wc = draw(st.integers(min_value=80, max_value=220))
        out.append(SectionModel(title=title, word_count=wc, present=present))
    return tuple(out)


@st.composite
def kb_structure_models(draw: st.DrawFn) -> KbStructureModel:
    """Generate a :class:`KbStructureModel` spanning valid and invalid docs."""
    sections = _kb_section_models(draw)
    fenced = draw(st.booleans())
    return KbStructureModel(
        sections=sections,
        lead_words=draw(st.integers(min_value=0, max_value=60)),
        h1_count=draw(st.integers(min_value=0, max_value=3)),
        list_depth=draw(st.integers(min_value=0, max_value=3)),
        table_columns=draw(st.integers(min_value=0, max_value=7)),
        table_ragged=draw(st.booleans()),
        fenced_block=fenced,
        anti_patterns=draw(st.booleans()),
    )


def _render_list(depth: int) -> str:
    """A nested bullet list reaching ``depth`` levels (1-based)."""
    lines: List[str] = []
    for level in range(depth):
        indent = "  " * level
        lines.append(f"{indent}- item level {level + 1}")
    return "\n".join(lines)


def _render_table(columns: int, ragged: bool) -> str:
    """A GFM table whose delimiter row has ``columns`` cells.

    ``ragged`` adds a body row with one fewer cell (the source shape of a
    "merged"/malformed cell the validator flags as ``table-merged-cell``).
    """
    header = "| " + " | ".join(f"h{i}" for i in range(columns)) + " |"
    delim = "| " + " | ".join(["---"] * columns) + " |"
    row = "| " + " | ".join(f"c{i}" for i in range(columns)) + " |"
    lines = [header, delim, row]
    if ragged and columns > 1:
        short = "| " + " | ".join(f"c{i}" for i in range(columns - 1)) + " |"
        lines.append(short)
    return "\n".join(lines)


def render_kb_document_body(model: KbStructureModel) -> str:
    """Render just the Markdown body (no frontmatter) from a structure model."""
    blocks: List[str] = []

    # H1 headings (ATX). h1_count may be 0, 1 or more.
    for i in range(model.h1_count):
        blocks.append(f"# Title {i + 1}")

    if model.lead_words:
        blocks.append(_words(model.lead_words))

    for section in model.sections:
        if not section.present:
            continue
        blocks.append(f"## {section.title}")
        blocks.append(_words(section.word_count))

    if model.list_depth > 0:
        blocks.append("## List")
        blocks.append(_render_list(model.list_depth))

    if model.table_columns > 0:
        blocks.append("## Table")
        blocks.append(_render_table(model.table_columns, model.table_ragged))

    if model.fenced_block:
        blocks.append("## Example")
        blocks.append("```python\nprint('hello')\n```")

    if model.anti_patterns:
        blocks.append("## Anti-patterns")
        blocks.append(_words(20))

    return "\n\n".join(blocks) + "\n"


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #

#: The twelve required frontmatter keys (kb-frontmatter.md).
FRONTMATTER_KEYS: Tuple[str, ...] = (
    "id",
    "title",
    "kb_namespace",
    "section",
    "category",
    "status",
    "updated",
    "owner",
    "author",
    "next_review_date",
    "tags",
    "related_docs",
)

_STATUS_VALUES = ("draft", "review", "published")

#: Text for a required non-empty string key: guaranteed to contain at least one
#: non-whitespace character, so it never strips to "" (which the validator, per
#: kb-frontmatter, correctly rejects as ``empty-key``). Any surrounding or
#: interior whitespace is fine — only an all-whitespace value is excluded.
_nonblank_text = st.text(min_size=1, max_size=20).filter(
    lambda s: s.strip() != ""
)


def _valid_iso_date(draw: st.DrawFn) -> str:
    d = draw(
        st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31))
    )
    return d.isoformat()


#: Near-miss date strings the validator must reject (impossible day, non-padded,
#: timestamp form).
_BAD_DATES = st.sampled_from(
    [
        "2026-02-30",
        "2026-13-01",
        "2026-00-10",
        "2026-2-3",
        "2026/02/03",
        "2026-02-03T10:00:00",
        "not-a-date",
    ]
)


@st.composite
def frontmatter_mappings(
    draw: st.DrawFn, *, valid: Optional[bool] = None
) -> Dict[str, object]:
    """Generate a frontmatter mapping (valid, or with near-miss violations).

    When ``valid`` is True the mapping satisfies every kb-frontmatter constraint;
    when False at least one near-miss is injected; when None the choice is
    random (so a property can decide acceptance from the model, not the flag).
    """
    make_valid = draw(st.booleans()) if valid is None else valid

    fm: Dict[str, object] = {
        "id": draw(st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=10)),
        "title": draw(_nonblank_text),
        "kb_namespace": "kb",
        "section": "s",
        "category": "c",
        "status": draw(st.sampled_from(_STATUS_VALUES)),
        "updated": _valid_iso_date(draw),
        "owner": "team",
        "author": "agent",
        "next_review_date": _valid_iso_date(draw),
        "tags": ["a"],
        "related_docs": [],
    }
    fm["tags"] = ["t"] * draw(st.integers(min_value=1, max_value=20))
    fm["related_docs"] = ["r"] * draw(st.integers(min_value=0, max_value=20))

    if make_valid:
        return fm

    # Inject one or more near-miss violations.
    mutators = draw(
        st.lists(
            st.sampled_from(
                [
                    "drop-key",
                    "empty-key",
                    "bad-status",
                    "bad-date",
                    "tags-empty",
                    "tags-over",
                    "related-over",
                    "tags-scalar",
                ]
            ),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    for m in mutators:
        if m == "drop-key":
            k = draw(st.sampled_from(FRONTMATTER_KEYS))
            fm.pop(k, None)
        elif m == "empty-key":
            fm["owner"] = ""
        elif m == "bad-status":
            fm["status"] = draw(
                st.text(min_size=1, max_size=8).filter(
                    lambda s: s not in _STATUS_VALUES
                )
            )
        elif m == "bad-date":
            fm["updated"] = draw(_BAD_DATES)
        elif m == "tags-empty":
            fm["tags"] = []
        elif m == "tags-over":
            fm["tags"] = ["t"] * 21
        elif m == "related-over":
            fm["related_docs"] = ["r"] * 21
        elif m == "tags-scalar":
            fm["tags"] = "not-a-list"
    return fm


def _yaml_scalar(value: object) -> str:
    if isinstance(value, str):
        # Quote to preserve dates-as-strings and empty strings faithfully.
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def render_frontmatter(fm: Mapping[str, object]) -> str:
    """Render a frontmatter mapping as a YAML block (between ``---`` fences)."""
    lines = ["---"]
    for key, value in fm.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def render_kb_document(
    fm: Mapping[str, object], model: KbStructureModel
) -> str:
    """Render a full KB document: frontmatter block + structured body."""
    return render_frontmatter(fm) + "\n" + render_kb_document_body(model)


# =========================================================================== #
# 3. JSON values: benign metadata + plant-a-secret
# =========================================================================== #
#
# Property 11 plants a secret and checks find_secrets locates it at the planted
# JSON pointer; Property 12 asserts benign values are never reported. The
# generators here keep the two spaces cleanly separate so the tests stay honest.

#: Benign key names that must never be treated as secrets, including the D3
#: metadata allow-list identifiers (``publicKey``, ``partitionKey``, …) and
#: names that merely *contain* a marker substring (``AccessKeyId``, ``SecretArn``,
#: ``PasswordLastUsed``, ``privateKeyType``).
BENIGN_KEYS: Tuple[str, ...] = (
    "id",
    "name",
    "region",
    "arn",
    "instanceId",
    "AccessKeyId",
    "SecretArn",
    "PasswordLastUsed",
    "privateKeyType",
    "CustomerMasterKeySpec",
    "publicKey",
    "sshPublicKey",
    "partitionKey",
    "sortKey",
    "objectKey",
    "s3Key",
    "keyPairName",
    "tags",
    "status",
    "count",
)

#: Key names that DO denote credentials (used by plant_secret's key path).
CREDENTIAL_KEYS: Tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "sessionToken",
    "clientSecret",
    "accountKey",
    "sharedAccessKey",
    "connectionString",
    "privateKey",
    "apiKey",
    "secretAccessKey",
)

#: Benign scalar values: identifiers, ARNs, regions, the literal REDACTED, plus
#: numbers and booleans (which are metadata even under a credential-looking key).
_benign_strings = st.sampled_from(
    [
        "prod",
        "us-east-1",
        "arn:aws:s3:::my-bucket",
        "i-0123456789abcdef0",
        "[REDACTED]",
        "SecureString",
        "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
        "privateKeyType",
    ]
)


def benign_scalar() -> st.SearchStrategy[object]:
    """A JSON scalar that is never a secret."""
    return st.one_of(
        _benign_strings,
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
        st.none(),
    )


def _benign_key() -> st.SearchStrategy[str]:
    return st.sampled_from(BENIGN_KEYS)


@st.composite
def benign_json(draw: st.DrawFn, *, max_depth: int = 3) -> object:
    """Generate a benign JSON value (dicts/lists/scalars, no secrets)."""

    def recurse(depth: int) -> st.SearchStrategy[object]:
        if depth <= 0:
            return benign_scalar()
        return st.one_of(
            benign_scalar(),
            st.lists(recurse(depth - 1), max_size=3),
            st.dictionaries(
                _benign_key(), recurse(depth - 1), max_size=3
            ),
        )

    return draw(recurse(max_depth))


# --------------------------------------------------------------------------- #
# Secret value shapes (Property 11 / R3.3)
# --------------------------------------------------------------------------- #


def _pem_private_key() -> str:
    return (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEA\n"
        "-----END PRIVATE KEY-----"
    )


def _jwt() -> str:
    return (
        "eyJhbGciOiJIUzI1NiJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )


#: Value-shaped secrets: ``(label, value)``. Each ``value`` is one the
#: ``value_secret_kind`` detector must flag under *any* (even benign) key.
SECRET_SHAPES: Tuple[Tuple[str, str], ...] = (
    ("pem-private-key", _pem_private_key()),
    ("jwt", _jwt()),
    ("account-key", "AccountKey=abcdefghijklmnopqrstuvwxyz0123456789=="),
    ("shared-access-key", "SharedAccessKey=Zm9vYmFyYmF6cXV4"),
    ("sas-sig", "https://x.blob.core.windows.net/c?sv=2021&sig=abcDEF123%2F%2B"),
    ("url-userinfo", "postgres://admin:S3cr3tP4ss@db.example.com:5432/app"),
    ("inline-assignment", "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY"),
)


def _secret_value_strategy() -> st.SearchStrategy[Tuple[str, str]]:
    """A ``(kind-label, value)`` pair of a value-shaped secret."""
    return st.sampled_from(SECRET_SHAPES)


def recase_key(name: str, style: str) -> str:
    """Re-render a lowerCamel base key in a given case/separator ``style``.

    ``style`` in ``{"camel", "snake", "kebab", "upper", "pascal"}``. The base
    ``name`` is a lowerCamelCase identifier (e.g. ``clientSecret``); the result
    keeps the same word boundaries so the normalized key is unchanged.
    """
    # Split lowerCamel into words.
    words: List[str] = []
    current = ""
    for ch in name:
        if ch.isupper() and current:
            words.append(current)
            current = ch.lower()
        else:
            current += ch.lower()
    if current:
        words.append(current)

    if style == "camel":
        return words[0] + "".join(w.capitalize() for w in words[1:])
    if style == "pascal":
        return "".join(w.capitalize() for w in words)
    if style == "snake":
        return "_".join(words)
    if style == "kebab":
        return "-".join(words)
    if style == "upper":
        return "_".join(w.upper() for w in words)
    return name


_CASE_STYLES = ("camel", "snake", "kebab", "upper", "pascal")


def _rfc6901_escape(token: str) -> str:
    """Escape one RFC 6901 reference token (``~`` -> ``~0``, ``/`` -> ``~1``)."""
    return token.replace("~", "~0").replace("/", "~1")


@st.composite
def plant_secret(draw: st.DrawFn) -> Tuple[object, str]:
    """Return ``(json_value, json_pointer)`` with a secret at the pointer.

    The secret is planted one of two ways, chosen at random:

    * as a string value under a credential-named key rendered in a random
      case/separator style (exercises the key rule, R3.2); or
    * as a value of a recognized secret *shape* under a benign key (exercises
      the value rule, R3.3).

    The returned pointer is the RFC 6901 location where ``find_secrets`` must
    report a hit. The surrounding object is benign, so the pointer is the only
    place a hit is expected.
    """
    container = draw(benign_json(max_depth=2))
    if not isinstance(container, dict):
        container = {"wrap": container}

    by_key = draw(st.booleans())
    if by_key:
        base = draw(st.sampled_from(CREDENTIAL_KEYS))
        key = recase_key(base, draw(st.sampled_from(_CASE_STYLES)))
        value: object = draw(
            st.text(min_size=1, max_size=24).filter(lambda s: s != "[REDACTED]")
        )
    else:
        key = draw(_benign_key())
        _, value = draw(_secret_value_strategy())

    # Ensure the planted key does not collide with an existing benign key that
    # would shadow the pointer semantics.
    container = dict(container)
    container[key] = value
    pointer = "/" + _rfc6901_escape(key)
    return container, pointer


# =========================================================================== #
# 4. Native resources with key-case / separator transforms
# =========================================================================== #
#
# Property 18: normalize() is invariant to key case and separator style. A
# transform re-renders every key of a resource without changing its meaning.

#: A base native resource shape uses lowerCamel keys (as an SDK response would).
_NATIVE_BASE_KEYS = (
    "instanceId",
    "functionArn",
    "fileSystemId",
    "resourceType",
    "region",
    "name",
)


@st.composite
def native_resources(draw: st.DrawFn) -> Dict[str, object]:
    """Generate a native (pre-normalization) resource with lowerCamel keys."""
    resource: Dict[str, object] = {
        "resourceType": draw(
            st.sampled_from(
                ["compute_instance", "object_store", "serverless_fn", "file_system"]
            )
        ),
        "name": draw(st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=12)),
        "region": draw(st.sampled_from(["us-east-1", "eu-central-1", "global"])),
    }
    if draw(st.booleans()):
        resource["instanceId"] = "i-" + draw(
            st.text(alphabet="0123456789abcdef", min_size=8, max_size=17)
        )
    if draw(st.booleans()):
        resource["tags"] = draw(
            st.dictionaries(
                st.sampled_from(["env", "team", "app"]),
                st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=8),
                max_size=3,
            )
        )
    return resource


def key_case_transforms() -> st.SearchStrategy[str]:
    """A case/separator style name for :func:`apply_key_transform`."""
    return st.sampled_from(_CASE_STYLES + ("upper",))


def apply_key_transform(resource: Mapping[str, object], style: str) -> Dict[str, object]:
    """Re-render every top-level key of ``resource`` in ``style``.

    Meaning is preserved (same normalized key), so ``normalize`` must return the
    same Normalized Resource for the original and the transformed input.
    """
    return {recase_key(k, style): v for k, v in resource.items()}


# =========================================================================== #
# 5. Init source / target / lock trees
# =========================================================================== #
#
# Requirement 7: rule-engine-init detects missing / current / stale / edited /
# extra files. A scenario carries the three trees plus the expected state of
# every path so an init test can assert the classification directly.

#: A small pool of workspace-relative bootstrap paths.
_INIT_PATHS = (
    ".kiro/steering/diagram-lint.md",
    ".kiro/steering/diagram-standards.md",
    ".kiro/hooks/lint-on-save.json",
    "mappings/aws-icons.yaml",
    "schemas/inventory.schema.json",
)

_INIT_STATES = ("missing", "current", "stale", "edited", "extra")


@dataclass(frozen=True)
class InitScenario:
    """Three trees plus the expected per-path state for an init ``--check``.

    ``source`` is the engine's bootstrap payload (path -> content), ``target`` is
    the workspace on disk, ``lock`` is the recorded lock hashes (path -> content
    whose hash was locked; a test hashes it to build the lock file). ``states``
    maps each path to its expected classification.
    """

    source: Mapping[str, str]
    target: Mapping[str, str]
    lock: Mapping[str, str]
    states: Mapping[str, str]


@st.composite
def file_trees(draw: st.DrawFn) -> Dict[str, str]:
    """A flat ``path -> content`` tree over the bootstrap path pool."""
    paths = draw(
        st.lists(st.sampled_from(_INIT_PATHS), min_size=1, max_size=len(_INIT_PATHS), unique=True)
    )
    return {p: draw(st.text(min_size=0, max_size=40)) for p in paths}


@st.composite
def init_scenarios(draw: st.DrawFn) -> InitScenario:
    """Generate an :class:`InitScenario` covering all five file states.

    For each path a state is chosen and the three trees are populated so the
    state is exactly reproduced:

    * ``missing`` — in source, absent from target;
    * ``current`` — target content == source content;
    * ``stale``   — target content == lock content != source content;
    * ``edited``  — target content != lock content (and != source);
    * ``extra``   — in target only (not in source).
    """
    source: Dict[str, str] = {}
    target: Dict[str, str] = {}
    lock: Dict[str, str] = {}
    states: Dict[str, str] = {}

    for path in _INIT_PATHS:
        state = draw(st.sampled_from(_INIT_STATES))
        src_content = f"src::{path}"
        if state == "missing":
            source[path] = src_content
            states[path] = "missing"
        elif state == "current":
            source[path] = src_content
            target[path] = src_content
            lock[path] = src_content
            states[path] = "current"
        elif state == "stale":
            stale_content = f"old::{path}"
            source[path] = src_content
            target[path] = stale_content
            lock[path] = stale_content
            states[path] = "stale"
        elif state == "edited":
            edited_content = f"edited::{path}"
            source[path] = src_content
            target[path] = edited_content
            lock[path] = f"locked::{path}"
            states[path] = "edited"
        elif state == "extra":
            target[path] = f"extra::{path}"
            states[path] = "extra"

    # Guarantee at least one path is present in source so a run has work to do.
    if not source:
        source[_INIT_PATHS[0]] = f"src::{_INIT_PATHS[0]}"
        target.pop(_INIT_PATHS[0], None)
        states[_INIT_PATHS[0]] = "missing"

    return InitScenario(source=source, target=target, lock=lock, states=states)


# =========================================================================== #
# 6. Minimal PNG encoder (test-only)
# =========================================================================== #
#
# R8 raster checks read IHDR (width/height/colour type), the tEXt provenance
# chunk, the tRNS chunk (transparency) and reconstruct row 0 from its filter
# byte. This encoder writes a valid, minimal PNG the raster gate can parse, with
# a selectable colour type and a controllable row-0 filter, so a test can build
# both a conforming raster and every near-miss (alpha channel, tRNS present,
# non-white first row, wrong source sha).

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Bytes-per-pixel by PNG colour type (only the ones the gate accepts + RGBA).
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


@dataclass(frozen=True)
class PngModel:
    """A model of a minimal PNG for the raster-gate tests."""

    width: int
    height: int
    color_type: int = 2         # 0=gray, 2=RGB, 4=gray+alpha, 6=RGBA
    row0_filter: int = 0        # 0=None, 1=Sub, 2=Up, 3=Average, 4=Paeth
    first_pixel_white: bool = True
    trns: bool = False          # emit a tRNS chunk
    source_sha256: Optional[str] = None  # tEXt provenance chunk


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(model: PngModel) -> bytes:
    """Encode ``model`` into PNG bytes (IHDR / [tRNS] / [tEXt] / IDAT / IEND).

    The image data is a solid raster: the first scanline uses ``row0_filter`` and
    all remaining rows use filter 0. Row 0 is reconstructed by the gate from its
    filter byte alone (the Up/Paeth predictors reference an all-zero previous
    row), so choosing the filter lets a test drive that reconstruction while the
    first pixel controls the white-background check.
    """
    channels = _CHANNELS[model.color_type]
    white = 255 if model.first_pixel_white else 0
    # Raw sample value per channel for the first pixel; the "filter" byte only
    # affects how the gate reconstructs it, so we store the post-filter deltas
    # matching filter 0 semantics for a solid image (deltas are 0 for Sub/Up).
    def scanline(filter_byte: int) -> bytes:
        row = bytes([filter_byte])
        for x in range(model.width):
            sample = white if x == 0 else 255
            row += bytes([sample] * channels)
        return row

    raw = bytearray()
    for y in range(model.height):
        raw += scanline(model.row0_filter if y == 0 else 0)

    ihdr = struct.pack(
        ">IIBBBBB",
        model.width,
        model.height,
        8,               # bit depth
        model.color_type,
        0,               # compression
        0,               # filter method
        0,               # interlace
    )

    out = bytearray(_PNG_SIGNATURE)
    out += _png_chunk(b"IHDR", ihdr)
    if model.trns:
        # A minimal tRNS: one entry (meaning varies by colour type; presence is
        # what the gate checks).
        out += _png_chunk(b"tRNS", b"\x00\x00")
    if model.source_sha256 is not None:
        text = b"rule-engine:source-sha256\x00" + model.source_sha256.encode("latin-1")
        out += _png_chunk(b"tEXt", text)
    out += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    out += _png_chunk(b"IEND", b"")
    return bytes(out)


@st.composite
def png_models(draw: st.DrawFn) -> PngModel:
    """Generate a :class:`PngModel` spanning conforming and near-miss rasters."""
    return PngModel(
        width=draw(st.integers(min_value=1, max_value=64)),
        height=draw(st.integers(min_value=1, max_value=64)),
        color_type=draw(st.sampled_from([0, 2, 4, 6])),
        row0_filter=draw(st.integers(min_value=0, max_value=4)),
        first_pixel_white=draw(st.booleans()),
        trns=draw(st.booleans()),
        source_sha256=draw(
            st.one_of(
                st.none(),
                st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
            )
        ),
    )
