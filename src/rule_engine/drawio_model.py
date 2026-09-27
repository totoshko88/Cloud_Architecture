"""One XML parser for ``.drawio`` files (honest-gates R1.1–R1.9).

Before 1.7.0, three modules (``cli``, ``geometry``, ``verify_icon``) each carried
their own ``_CELL_RE`` / ``_attr`` regexes that read ``.drawio`` bytes, and any
file those regexes could not read was silently skipped (``except Exception: geo =
None``). This module is the single place that reads ``.drawio`` bytes and turns
them into a parsed model that every consumer shares, and — critically — anything
it cannot parse becomes a :class:`DrawioParseError` (a Blocking_Finding upstream)
rather than a silent skip.

Design (see ``design.md`` §1):

* :func:`parse_drawio` accepts a ``<mxfile>`` with one or more ``<diagram>``
  children, or a bare ``<mxGraphModel>`` (one page named after the file stem).
  A compressed ``<diagram>`` (``base64(deflateRaw(encodeURIComponent(...)))``) is
  decompressed with :func:`decode_compressed` and its inner model parsed with the
  same guarded parser. Duplicate page names are disambiguated ``name``,
  ``name (2)``, ….
* XML safety: built on ``xml.parsers.expat`` directly with a small tree builder.
  Doctype, entity-declaration and external-entity handlers raise
  ``DrawioParseError("dtd-or-entity-declaration")``, and parameter-entity parsing
  is disabled — so billion-laughs and external-entity documents are rejected
  without adding a third-party dependency.
* Wrappers: a ``UserObject`` / ``object`` element holding exactly one ``mxCell``
  yields one :class:`Cell` whose ``id`` and ``label`` come from the wrapper; the
  wrapper's other attributes land in ``wrapper_attrs``. Zero or several ``mxCell``
  children is a :class:`DrawioParseError`.
* Labels: when ``html=1`` the label is treated as HTML (``<br>``/``</div>``/
  ``</p>``/``</li>`` → line breaks, tags stripped with an ``HTMLParser`` subclass,
  entities resolved with ``html.unescape``); each line is stripped.
* Geometry: waypoints come only from ``<Array as="points">``;
  ``sourcePoint``/``targetPoint`` are kept separately and the label ``offset`` is
  ignored. A missing coordinate is 0. ``grid_size`` is ``mxGraphModel@gridSize``,
  else 10.
* :func:`absolute_origin` walks the parent chain and raises
  ``DrawioParseError("parent-cycle:<id>")`` on a cycle.
"""

from __future__ import annotations

import base64
import binascii
import html
import urllib.parse
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple
from xml.parsers import expat

__all__ = [
    "Geom",
    "Cell",
    "Page",
    "DrawioParseError",
    "parse_drawio",
    "absolute_origin",
    "decode_compressed",
]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class DrawioParseError(ValueError):
    """A ``.drawio`` file (or an embedded model) could not be parsed.

    ``cause`` is a machine-readable string (e.g. ``"expat:..."``,
    ``"dtd-or-entity-declaration"``, ``"decompress:..."``, ``"missing-root"``,
    ``"non-numeric-geometry:..."``, ``"parent-cycle:<id>"``) so upstream gates can
    surface it as the reason of a ``parse-error`` finding.
    """

    def __init__(self, cause: str, *, path: str = "", page: Optional[str] = None) -> None:
        self.cause = cause
        self.path = path
        self.page = page
        loc = path or "<drawio>"
        if page is not None:
            loc = f"{loc}#{page}"
        super().__init__(f"{loc}: {cause}")


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Geom:
    """A cell's geometry. A missing coordinate is 0 (R1.6)."""

    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    relative: bool = False
    points: Tuple[Tuple[float, float], ...] = ()  # only <Array as="points">
    source_point: Optional[Tuple[float, float]] = None
    target_point: Optional[Tuple[float, float]] = None


@dataclass(frozen=True)
class Cell:
    """A parsed ``mxCell`` (possibly unwrapped from a ``UserObject``/``object``)."""

    id: str
    parent: str
    label: str  # decoded plain text, lines joined by "\n"
    style: str
    style_map: Mapping[str, str]
    vertex: bool
    edge: bool
    source: Optional[str]
    target: Optional[str]
    geom: Optional[Geom]
    wrapper: Optional[str]  # "UserObject" | "object" | None
    wrapper_attrs: Mapping[str, str] = field(default_factory=dict)

    @property
    def lines(self) -> Tuple[str, ...]:
        """The label split into lines (empty tuple for an empty label)."""
        if not self.label:
            return ()
        return tuple(self.label.split("\n"))


@dataclass(frozen=True)
class Page:
    """One ``<diagram>`` (or the single bare ``<mxGraphModel>``) as a page."""

    name: str  # <diagram name>, else file stem
    id: str
    grid_size: int  # mxGraphModel@gridSize, else 10 (R1.7)
    cells: Mapping[str, Cell]  # insertion-ordered
    compressed: bool


# --------------------------------------------------------------------------- #
# Compressed page payloads (moved here from fetch_assets._decode_drawio_payload)
# --------------------------------------------------------------------------- #


def decode_compressed(text: str) -> str:
    """Decode a draw.io compressed payload (base64 -> raw-deflate -> URL-decode).

    This is the pipeline draw.io uses for a compressed ``<diagram>`` body and for
    a ``<mxlibrary>`` ``xml`` entry:
    ``base64(deflateRaw(encodeURIComponent(<mxGraphModel>)))``. Raw-deflate
    (``wbits=-15``) is tried first, then zlib-wrapped as a fallback.

    Moved here from ``fetch_assets._decode_drawio_payload`` so the single XML
    parser owns the decompression; ``fetch_assets`` imports it back.
    """
    raw = base64.b64decode(text)
    try:
        decoded = zlib.decompress(raw, -15).decode("utf-8")
    except zlib.error:
        decoded = zlib.decompress(raw).decode("utf-8")
    return urllib.parse.unquote(decoded)


# --------------------------------------------------------------------------- #
# Guarded expat tree builder
# --------------------------------------------------------------------------- #


class _Node:
    """A minimal parsed-XML element: tag, attributes, text, ordered children."""

    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag: str, attrs: Mapping[str, str]) -> None:
        self.tag = tag
        self.attrs: Dict[str, str] = dict(attrs)
        self.children: List["_Node"] = []
        self.text: str = ""

    def find_all(self, tag: str) -> List["_Node"]:
        return [c for c in self.children if c.tag == tag]

    def find(self, tag: str) -> Optional["_Node"]:
        for c in self.children:
            if c.tag == tag:
                return c
        return None


def _parse_xml(data: str, *, path: str, page: Optional[str]) -> _Node:
    """Parse ``data`` into a ``_Node`` tree with DTD/entity handlers that reject.

    Any DTD, internal entity declaration or external entity reference raises
    ``DrawioParseError("dtd-or-entity-declaration")``; parameter-entity parsing
    is disabled. An expat error becomes ``DrawioParseError("expat:<msg>")``.
    """
    parser = expat.ParserCreate()

    def _reject_dtd(*_args: object, **_kwargs: object) -> None:
        raise DrawioParseError("dtd-or-entity-declaration", path=path, page=page)

    parser.StartDoctypeDeclHandler = _reject_dtd  # type: ignore[assignment]
    parser.EntityDeclHandler = _reject_dtd  # type: ignore[assignment]
    parser.ExternalEntityRefHandler = _reject_dtd  # type: ignore[assignment]
    parser.UnparsedEntityDeclHandler = _reject_dtd  # type: ignore[assignment]
    try:
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    except (AttributeError, expat.ExpatError):  # pragma: no cover - platform dependent
        pass

    root_holder: List[_Node] = []
    stack: List[_Node] = []

    def _start(tag: str, attrs: Mapping[str, str]) -> None:
        node = _Node(tag, attrs)
        if stack:
            stack[-1].children.append(node)
        else:
            root_holder.append(node)
        stack.append(node)

    def _end(_tag: str) -> None:
        if stack:
            stack.pop()

    def _chardata(text: str) -> None:
        if stack:
            stack[-1].text += text

    parser.StartElementHandler = _start
    parser.EndElementHandler = _end
    parser.CharacterDataHandler = _chardata

    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise DrawioParseError(f"expat:{exc}", path=path, page=page) from exc

    if not root_holder:
        raise DrawioParseError("empty-document", path=path, page=page)
    return root_holder[0]


# --------------------------------------------------------------------------- #
# HTML label stripping
# --------------------------------------------------------------------------- #


class _LabelStripper(HTMLParser):
    """Strip HTML tags from a label, turning block breaks into newlines.

    ``<br>``, ``</div>``, ``</p>`` and ``</li>`` become line breaks; all other
    tags are dropped. Text is accumulated and entities are resolved afterwards
    with ``html.unescape`` (``convert_charrefs`` keeps character refs intact so a
    single ``html.unescape`` pass handles them uniformly)."""

    _BREAK_START = {"br"}
    _BREAK_END = {"div", "p", "li"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag.lower() in self._BREAK_START:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        if tag.lower() in self._BREAK_START:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BREAK_END:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def text(self) -> str:
        return "".join(self._parts)


def _decode_label(raw: str, is_html: bool) -> str:
    """Decode a raw label to plain text, lines joined by ``\\n``.

    Expat already decoded XML entities in the attribute value; when the cell's
    style says ``html=1`` the value is HTML markup, so tags are stripped and HTML
    entities resolved. Each resulting line is stripped of surrounding whitespace.
    """
    if raw is None:
        return ""
    if is_html:
        stripper = _LabelStripper()
        stripper.feed(raw)
        stripper.close()
        text = html.unescape(stripper.text())
    else:
        text = raw
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Style parsing
# --------------------------------------------------------------------------- #


def _split_style(style: str) -> List[str]:
    """Split a draw.io style on ``;``, but only outside parentheses.

    ``shape=stencil(...)`` values embed ``;`` inside the ``stencil(...)`` payload,
    so a naive ``split(";")`` would shred them. Depth-tracking on ``(`` / ``)``
    keeps such a value whole.
    """
    tokens: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in style:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == ";" and depth == 0:
            tokens.append("".join(current))
            current = []
        else:
            current.append(ch)
    tokens.append("".join(current))
    return [t for t in tokens if t]


def _parse_style(style: str) -> Dict[str, str]:
    """Parse ``key=value;`` pairs; a bare leading token is stored as ``{token: ""}``.

    So ``"text" in style_map`` is a structural test rather than a substring match,
    and ``shape=stencil(...)`` is kept whole (split only outside parentheses).
    """
    out: Dict[str, str] = {}
    for token in _split_style(style or ""):
        if "=" in token:
            key, _, value = token.partition("=")
            out[key] = value
        else:
            out[token] = ""
    return out


# --------------------------------------------------------------------------- #
# Geometry parsing
# --------------------------------------------------------------------------- #


def _num(value: Optional[str], *, path: str, page: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DrawioParseError(
            f"non-numeric-geometry:{value!r}", path=path, page=page
        ) from exc


def _point(node: _Node, *, path: str, page: Optional[str]) -> Tuple[float, float]:
    x = _num(node.attrs.get("x"), path=path, page=page) or 0.0
    y = _num(node.attrs.get("y"), path=path, page=page) or 0.0
    return (x, y)


def _parse_geom(
    cell_node: _Node, *, path: str, page: Optional[str]
) -> Optional[Geom]:
    geom_node = cell_node.find("mxGeometry")
    if geom_node is None:
        return None
    x = _num(geom_node.attrs.get("x"), path=path, page=page) or 0.0
    y = _num(geom_node.attrs.get("y"), path=path, page=page) or 0.0
    w = _num(geom_node.attrs.get("width"), path=path, page=page) or 0.0
    h = _num(geom_node.attrs.get("height"), path=path, page=page) or 0.0
    relative = geom_node.attrs.get("relative") == "1"

    points: List[Tuple[float, float]] = []
    source_point: Optional[Tuple[float, float]] = None
    target_point: Optional[Tuple[float, float]] = None
    for child in geom_node.children:
        if child.tag == "Array" and child.attrs.get("as") == "points":
            for pt in child.find_all("mxPoint"):
                points.append(_point(pt, path=path, page=page))
        elif child.tag == "mxPoint":
            role = child.attrs.get("as")
            if role == "sourcePoint":
                source_point = _point(child, path=path, page=page)
            elif role == "targetPoint":
                target_point = _point(child, path=path, page=page)
            # the label `offset` mxPoint is deliberately ignored (R1.6)
    return Geom(
        x=x,
        y=y,
        w=w,
        h=h,
        relative=relative,
        points=tuple(points),
        source_point=source_point,
        target_point=target_point,
    )


# --------------------------------------------------------------------------- #
# <root> -> cells
# --------------------------------------------------------------------------- #

_WRAPPER_TAGS = ("UserObject", "object")


def _build_cell(
    cell_node: _Node,
    *,
    wrapper: Optional[str],
    wrapper_attrs: Mapping[str, str],
    override_id: Optional[str],
    override_label: Optional[str],
    path: str,
    page: Optional[str],
) -> Cell:
    attrs = cell_node.attrs
    cid = override_id if override_id is not None else attrs.get("id", "")
    raw_label = override_label if override_label is not None else attrs.get("value", "")
    style = attrs.get("style", "")
    style_map = _parse_style(style)
    is_html = style_map.get("html") == "1"
    label = _decode_label(raw_label or "", is_html)
    return Cell(
        id=cid,
        parent=attrs.get("parent", ""),
        label=label,
        style=style,
        style_map=style_map,
        vertex=attrs.get("vertex") == "1",
        edge=attrs.get("edge") == "1",
        source=attrs.get("source"),
        target=attrs.get("target"),
        geom=_parse_geom(cell_node, path=path, page=page),
        wrapper=wrapper,
        wrapper_attrs=dict(wrapper_attrs),
    )


def _cells_from_root(
    root_node: _Node, *, path: str, page: Optional[str]
) -> Dict[str, Cell]:
    cells: Dict[str, Cell] = {}
    for child in root_node.children:
        if child.tag == "mxCell":
            cell = _build_cell(
                child,
                wrapper=None,
                wrapper_attrs={},
                override_id=None,
                override_label=None,
                path=path,
                page=page,
            )
            cells[cell.id] = cell
        elif child.tag in _WRAPPER_TAGS:
            inner = child.find_all("mxCell")
            if len(inner) != 1:
                raise DrawioParseError(
                    f"wrapper-cell-count:{child.tag}:{len(inner)}",
                    path=path,
                    page=page,
                )
            wrapper_attrs = {
                k: v for k, v in child.attrs.items() if k not in ("id", "label")
            }
            cell = _build_cell(
                inner[0],
                wrapper=child.tag,
                wrapper_attrs=wrapper_attrs,
                override_id=child.attrs.get("id"),
                override_label=child.attrs.get("label", ""),
                path=path,
                page=page,
            )
            cells[cell.id] = cell
    return cells


def _grid_size(model_node: _Node, *, path: str, page: Optional[str]) -> int:
    raw = model_node.attrs.get("gridSize")
    if raw is None:
        return 10
    value = _num(raw, path=path, page=page)
    if value is None:
        return 10
    return int(value)


def _page_from_model(
    model_node: _Node,
    *,
    name: str,
    page_id: str,
    compressed: bool,
    path: str,
) -> Page:
    root_node = model_node.find("root")
    if root_node is None:
        raise DrawioParseError("missing-root", path=path, page=name)
    cells = _cells_from_root(root_node, path=path, page=name)
    return Page(
        name=name,
        id=page_id,
        grid_size=_grid_size(model_node, path=path, page=name),
        cells=cells,
        compressed=compressed,
    )


def _dedupe(name: str, seen: Dict[str, int]) -> str:
    """Disambiguate duplicate page names as ``name``, ``name (2)``, …."""
    count = seen.get(name, 0) + 1
    seen[name] = count
    if count == 1:
        return name
    return f"{name} ({count})"


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def parse_drawio(data: "bytes | str", *, path: str) -> List[Page]:
    """Parse ``.drawio`` bytes/text into one :class:`Page` per ``<diagram>``.

    Roots accepted: ``<mxfile>`` with one or more ``<diagram>`` children, or a
    bare ``<mxGraphModel>`` (one page named after the file's stem). A compressed
    ``<diagram>`` body is decompressed and its inner model parsed with the same
    guarded parser. Any parse failure raises :class:`DrawioParseError`.
    """
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DrawioParseError(f"unicode:{exc}", path=path) from exc
    else:
        text = data

    root = _parse_xml(text, path=path, page=None)
    stem = Path(path).stem or "diagram"

    if root.tag == "mxGraphModel":
        return [
            _page_from_model(
                root, name=stem, page_id="", compressed=False, path=path
            )
        ]

    if root.tag != "mxfile":
        raise DrawioParseError(f"unexpected-root:{root.tag}", path=path)

    diagrams = root.find_all("diagram")
    if not diagrams:
        raise DrawioParseError("no-diagram", path=path)

    pages: List[Page] = []
    seen: Dict[str, int] = {}
    for index, diagram in enumerate(diagrams):
        base_name = diagram.attrs.get("name") or f"Page-{index + 1}"
        name = _dedupe(base_name, seen)
        page_id = diagram.attrs.get("id", "")

        model_node = diagram.find("mxGraphModel")
        compressed = False
        if model_node is None:
            payload = diagram.text.strip()
            if not payload:
                raise DrawioParseError("empty-diagram", path=path, page=name)
            try:
                inner = decode_compressed(payload)
            except (binascii.Error, zlib.error) as exc:
                raise DrawioParseError(
                    f"decompress:{type(exc).__name__}:{exc}", path=path, page=name
                ) from exc
            except UnicodeDecodeError as exc:
                raise DrawioParseError(
                    f"decompress-unicode:{exc}", path=path, page=name
                ) from exc
            inner_root = _parse_xml(inner, path=path, page=name)
            if inner_root.tag != "mxGraphModel":
                raise DrawioParseError(
                    f"decompressed-root:{inner_root.tag}", path=path, page=name
                )
            model_node = inner_root
            compressed = True

        pages.append(
            _page_from_model(
                model_node,
                name=name,
                page_id=page_id,
                compressed=compressed,
                path=path,
            )
        )
    return pages


# --------------------------------------------------------------------------- #
# Absolute coordinates
# --------------------------------------------------------------------------- #

_ROOT_IDS = frozenset({"", "0", "1", None})


def absolute_origin(page: Page, cell_id: str) -> Tuple[float, float]:
    """Return the absolute ``(x, y)`` origin of ``cell_id`` in page coordinates.

    Walks the parent chain, summing each cell's geometry origin. A parent cycle
    raises ``DrawioParseError("parent-cycle:<id>")`` instead of silently
    returning ``(0, 0)`` (which is what the pre-1.7 ``geometry.origin`` did).
    A cell parented to the root layer (``"0"``/``"1"``), or an id not present in
    the page, contributes ``(0, 0)``.
    """
    x = 0.0
    y = 0.0
    seen: set = set()
    current: Optional[str] = cell_id
    while current is not None and current not in _ROOT_IDS:
        if current in seen:
            raise DrawioParseError(
                f"parent-cycle:{current}", path="", page=page.name
            )
        seen.add(current)
        cell = page.cells.get(current)
        if cell is None:
            break
        if cell.geom is not None:
            x += cell.geom.x
            y += cell.geom.y
        current = cell.parent
    return (x, y)
