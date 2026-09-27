"""Property tests for ``rule_engine.drawio_model`` (honest-gates R1).

Feature: honest-gates (release 1.7.0).

This file holds the ``.drawio`` model property tests. Task 2.2 lands Property 1
(the XML round trip); tasks 9.2, 9.5 and 10.6 append Property 2 (waypoints),
Property 3 (one artifact per page) and Property 4 (parse or block) to the same
file, so it is structured to be appended to: shared imports and helpers first,
then one clearly delimited section per property.
"""

from __future__ import annotations

from typing import Dict, List

from hypothesis import assume, given, settings

from rule_engine.drawio_model import Page, parse_drawio

from tests import strategies as S
from tests.strategies import DiagramModel, PageModel

# The path stem the tests serialize under. A bare single-page diagram is named
# after this stem, so the expected-name computation below uses it too.
_PATH = "diagram.drawio"

# draw.io reserves ids "0" and "1" for the two structural root layers that every
# page's <root> carries; a real cell id never collides with them. The generic id
# strategy can nonetheless draw "0"/"1", producing an id clash the wire format
# would never contain, so the round-trip properties assume authored ids avoid
# the reserved set.
_RESERVED_IDS = frozenset({"0", "1"})


def _no_reserved_ids(model: DiagramModel) -> bool:
    return all(
        c.id not in _RESERVED_IDS for page in model.pages for c in page.cells
    )


def _consistent_html_flag(model: DiagramModel) -> bool:
    """Every cell's ``html_label`` flag agrees with its effective style.

    ``CellModel.expected_label`` decodes as HTML exactly when ``html_label`` is
    set, whereas the parser decodes as HTML whenever the *style* carries
    ``html=1``. When a plain-text cell is sampled with a style that already
    contains ``html=1`` (and the label was written plain, not as HTML markup),
    the two disagree on labels containing ``&``/``<`` — an inconsistent model,
    not a parser defect. The round-trip contract is that ``html_label`` and the
    ``html=1`` style token move together, so such degenerate cells are excluded.
    """
    for page in model.pages:
        for cell in page.cells:
            style_is_html = "html=1" in cell.effective_style
            if style_is_html != cell.html_label:
                return False
    return True


def _well_formed(model: DiagramModel) -> bool:
    return _no_reserved_ids(model) and _consistent_html_flag(model)


def _expected_page_names(model: DiagramModel) -> List[str]:
    """Mirror ``parse_drawio``'s page naming for the given model.

    A bare single-page model is named after the file stem. Otherwise each page
    keeps its ``<diagram name>``, with duplicates disambiguated ``name``,
    ``name (2)``, ``name (3)``, … in document order.
    """
    if model.bare and len(model.pages) == 1 and not model.pages[0].compressed:
        return ["diagram"]  # Path("diagram.drawio").stem
    seen: Dict[str, int] = {}
    names: List[str] = []
    for page in model.pages:
        base = page.name
        count = seen.get(base, 0) + 1
        seen[base] = count
        names.append(base if count == 1 else f"{base} ({count})")
    return names


def _split_style_paren_aware(style: str) -> List[str]:
    """Split a draw.io style on ``;`` but only outside parentheses.

    Independent of the parser: a ``shape=stencil(a;b)`` value embeds ``;`` inside
    the ``stencil(...)`` payload, which draw.io does not treat as a separator.
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


def _expected_style_map(style: str) -> Dict[str, str]:
    """The style map the parser should produce for ``style`` (test authority)."""
    out: Dict[str, str] = {}
    for token in _split_style_paren_aware(style):
        if "=" in token:
            key, _, value = token.partition("=")
            out[key] = value
        else:
            out[token] = ""
    return out


def _assert_cell_matches(cell, model_cell) -> None:
    """Assert one parsed ``Cell`` equals its :class:`CellModel`."""
    assert cell.id == model_cell.id
    assert cell.parent == model_cell.parent
    # Labels: decoded, HTML-stripped, line-stripped (R1.5).
    assert cell.label == model_cell.expected_label
    assert list(cell.lines) == (
        model_cell.expected_label.split("\n") if model_cell.expected_label else []
    )
    assert cell.vertex is model_cell.vertex
    assert cell.edge is model_cell.edge
    assert cell.source == model_cell.source
    assert cell.target == model_cell.target

    # Style: the parsed structural style map equals the authored style tokens,
    # with the folded ``html=1``, a bare leading token as ``{token: ""}`` and a
    # ``shape=stencil(...)`` value kept whole — ``;`` inside parentheses is not
    # a separator (R1.5 keeps the style intact).
    assert dict(cell.style_map) == _expected_style_map(model_cell.effective_style)

    # Wrapper: id + label lifted onto the cell, other attrs kept aside (R1.4).
    assert cell.wrapper == model_cell.wrapper
    if model_cell.wrapper is not None:
        assert dict(cell.wrapper_attrs) == dict(model_cell.wrapper_attrs)

    # Geometry: omitted coordinates read as 0 (R1.6 for the base box).
    if model_cell.geom is None:
        assert cell.geom is None
    else:
        assert cell.geom is not None
        exp_x, exp_y, exp_w, exp_h = model_cell.geom.expected()
        assert (cell.geom.x, cell.geom.y, cell.geom.w, cell.geom.h) == (
            exp_x,
            exp_y,
            exp_w,
            exp_h,
        )


# =========================================================================== #
# Property 1: `.drawio` round trip
# =========================================================================== #
# Feature: honest-gates, Property 1: .drawio round trip
#
# Validates: Requirements 1.1, 1.2, 1.4, 1.5, 1.7
#
# For any generated diagram model (pages, cells with random ids and parents,
# optional UserObject/object wrappers, labels with XML-special characters, HTML
# line breaks and entities, geometry with omitted coordinates, any gridSize or
# none), serializing it to .drawio uncompressed or as a compressed page and
# parsing it with parse_drawio yields pages whose cells, decoded label lines,
# styles and geometry equal the model (omitted coordinates read as 0, a missing
# gridSize read as 10).


@settings(max_examples=100)
@given(S.diagram_models())
def test_property_1_drawio_round_trip(model: DiagramModel) -> None:
    assume(_well_formed(model))
    xml = S.serialize_drawio(model)
    pages: List[Page] = parse_drawio(xml, path=_PATH)

    # R1.2 / R1.3: one page per <diagram> (or the single bare model), in order,
    # with duplicate names disambiguated exactly as the model predicts.
    expected_names = _expected_page_names(model)
    assert [p.name for p in pages] == expected_names
    assert len(pages) == len(model.pages)

    for parsed_page, model_page in zip(pages, model.pages):
        _assert_page_matches(parsed_page, model_page)


def _assert_page_matches(parsed_page: Page, model_page: PageModel) -> None:
    # R1.7: gridSize round trips, and a missing one reads as 10.
    assert parsed_page.grid_size == model_page.expected_grid
    # R1.1: compressed and plain pages parse to the same model shape.
    assert parsed_page.compressed is model_page.compressed

    # Every authored cell is present, in its authored form. The two draw.io
    # root layers ("0"/"1") are structural, never authored by the model.
    assert set(parsed_page.cells) - {"0", "1"} == {c.id for c in model_page.cells}
    for model_cell in model_page.cells:
        assert model_cell.id in parsed_page.cells
        _assert_cell_matches(parsed_page.cells[model_cell.id], model_cell)


@settings(max_examples=100)
@given(S.diagram_models(min_pages=1, max_pages=1, allow_bare=False, allow_duplicate_names=False))
def test_property_1_compressed_matches_plain(model: DiagramModel) -> None:
    """A page parses identically whether stored plain or compressed (R1.1)."""
    assume(_well_formed(model))
    (page,) = model.pages
    plain = DiagramModel(
        pages=(PageModel(
            name=page.name,
            cells=page.cells,
            grid_size=page.grid_size,
            compressed=False,
            page_id=page.page_id,
        ),),
    )
    packed = DiagramModel(
        pages=(PageModel(
            name=page.name,
            cells=page.cells,
            grid_size=page.grid_size,
            compressed=True,
            page_id=page.page_id,
        ),),
    )
    plain_pages = parse_drawio(S.serialize_drawio(plain), path=_PATH)
    packed_pages = parse_drawio(S.serialize_drawio(packed), path=_PATH)

    assert not plain_pages[0].compressed
    assert packed_pages[0].compressed
    # Same cells, labels, styles, geometry regardless of storage form.
    assert set(plain_pages[0].cells) == set(packed_pages[0].cells)
    for cid in plain_pages[0].cells:
        a = plain_pages[0].cells[cid]
        b = packed_pages[0].cells[cid]
        assert a.label == b.label
        assert dict(a.style_map) == dict(b.style_map)
        assert a.geom == b.geom
        assert a.wrapper == b.wrapper
        assert dict(a.wrapper_attrs) == dict(b.wrapper_attrs)

# =========================================================================== #
# Property 2: Waypoints are exactly the authored points in page coordinates
# =========================================================================== #
# Feature: honest-gates, Property 2: Waypoints are exactly the authored points in page coordinates
#
# Validates: Requirements 1.6
#
# For any edge placed under a random chain of parent containers and given random
# <Array as="points"> waypoints plus random sourcePoint, targetPoint and
# label-offset points, the edge geometry built by geometry.build_geometry
# contains exactly the Array points, each translated by the absolute origin of
# the edge's parent, and none of the other points (sourcePoint / targetPoint /
# offset are NOT waypoints — R1.6).

from hypothesis import strategies as st  # noqa: E402

from rule_engine.drawio_model import absolute_origin  # noqa: E402
from rule_engine.geometry import build_geometry  # noqa: E402
from tests.strategies import (  # noqa: E402
    CellModel,
    DiagramModel,
    Geom,
    PageModel,
    serialize_drawio,
)

# Coordinates on a coarse grid so the round trip through the serializer's number
# formatter is exact (integral values render without a trailing ``.0``), keeping
# the expected-vs-parsed float comparison exact.
_P2_COORDS = st.integers(min_value=-2000, max_value=4000).map(float)
_P2_IDS = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=1,
    max_size=10,
)


@st.composite
def _edge_under_parent_chain(draw: st.DrawFn) -> DiagramModel:
    """A page holding a chain of nested container vertices and one edge.

    The chain ``c0 ⊃ c1 ⊃ … ⊃ cN`` is rooted at the ``"1"`` layer; each container
    carries its own geometry origin, so the edge parented to the deepest one is
    authored in coordinates relative to a non-trivial absolute origin. The edge
    is given random ``<Array as="points">`` waypoints plus decoy
    ``sourcePoint`` / ``targetPoint`` / label ``offset`` points that the parser
    must keep out of the waypoint list (R1.6).
    """
    # Unique ids for the containers, the edge and its two endpoint vertices.
    n_containers = draw(st.integers(min_value=1, max_value=4))
    n_ids = n_containers + 3
    ids = draw(
        st.lists(_P2_IDS, min_size=n_ids, max_size=n_ids, unique=True).filter(
            lambda xs: all(x not in ("0", "1") for x in xs)
        )
    )
    container_ids = ids[:n_containers]
    edge_id = ids[n_containers]
    src_id, tgt_id = ids[n_containers + 1], ids[n_containers + 2]

    cells: list[CellModel] = []
    # Nested container chain: each parented to the previous (first to "1"),
    # each with its own geometry origin so absolute_origin accumulates a shift.
    parent = "1"
    for cid in container_ids:
        cells.append(
            CellModel(
                id=cid,
                parent=parent,
                style="rounded=0;dashed=1;",
                vertex=True,
                geom=Geom(
                    x=draw(_P2_COORDS),
                    y=draw(_P2_COORDS),
                    w=1000.0,
                    h=1000.0,
                ),
            )
        )
        parent = cid
    edge_parent = container_ids[-1]

    # Two endpoint vertices for the edge (parented to the deepest container).
    for vid in (src_id, tgt_id):
        cells.append(
            CellModel(
                id=vid,
                parent=edge_parent,
                style="rounded=1;whiteSpace=wrap;",
                vertex=True,
                geom=Geom(x=draw(_P2_COORDS), y=draw(_P2_COORDS), w=78.0, h=78.0),
            )
        )

    # The edge itself: authored waypoints (the only real waypoints) plus decoy
    # source/target/offset points the parser must ignore.
    waypoints = tuple(
        draw(st.lists(st.tuples(_P2_COORDS, _P2_COORDS), min_size=0, max_size=5))
    )
    edge_geom = Geom(
        x=0.0,
        y=0.0,
        w=0.0,
        h=0.0,
        relative=True,
        points=waypoints,
        source_point=draw(st.one_of(st.none(), st.tuples(_P2_COORDS, _P2_COORDS))),
        target_point=draw(st.one_of(st.none(), st.tuples(_P2_COORDS, _P2_COORDS))),
        offset_point=draw(st.one_of(st.none(), st.tuples(_P2_COORDS, _P2_COORDS))),
    )
    cells.append(
        CellModel(
            id=edge_id,
            parent=edge_parent,
            style="edgeStyle=orthogonalEdgeStyle;html=1;",
            edge=True,
            source=src_id,
            target=tgt_id,
            geom=edge_geom,
        )
    )

    page = PageModel(name="p", cells=tuple(cells), grid_size=10, compressed=False)
    return DiagramModel(pages=(page,))


@settings(max_examples=100)
@given(_edge_under_parent_chain())
def test_property_2_waypoints_in_page_coordinates(model: DiagramModel) -> None:
    xml = serialize_drawio(model)
    (page,) = parse_drawio(xml, path=_PATH)

    # The one edge cell in the model, with its authored Array waypoints.
    (edge_model,) = [c for c in model.pages[0].cells if c.edge]
    authored = list(edge_model.geom.points)  # type: ignore[union-attr]

    # The absolute origin of the edge's parent, in page coordinates.
    ox, oy = absolute_origin(page, edge_model.parent)

    expected = [(px + ox, py + oy) for px, py in authored]

    geo = build_geometry(page)
    (built_edge,) = [e for e in geo.edges if e.id == edge_model.id]

    # Exactly the Array points, each translated by the parent absolute origin —
    # same count, same order, no phantom points (R1.6).
    assert [tuple(p) for p in built_edge.points] == expected

    # The decoy sourcePoint / targetPoint / offset points are never waypoints.
    decoys = set()
    if edge_model.geom.source_point is not None:  # type: ignore[union-attr]
        decoys.add(
            (
                edge_model.geom.source_point[0] + ox,  # type: ignore[union-attr,index]
                edge_model.geom.source_point[1] + oy,  # type: ignore[union-attr,index]
            )
        )
    if edge_model.geom.target_point is not None:  # type: ignore[union-attr]
        decoys.add(
            (
                edge_model.geom.target_point[0] + ox,  # type: ignore[union-attr,index]
                edge_model.geom.target_point[1] + oy,  # type: ignore[union-attr,index]
            )
        )
    if edge_model.geom.offset_point is not None:  # type: ignore[union-attr]
        decoys.add(
            (
                edge_model.geom.offset_point[0] + ox,  # type: ignore[union-attr,index]
                edge_model.geom.offset_point[1] + oy,  # type: ignore[union-attr,index]
            )
        )
    built_set = {tuple(p) for p in built_edge.points}
    # A decoy only counts as a leak when it is not also a legitimate authored
    # waypoint (a random draw can coincide); the exact-list assertion above
    # already pins the waypoints, so this guards the "no phantom point" half.
    assert (decoys - set(expected)) & built_set == set()

# =========================================================================== #
# Property 3: One artifact per page with unique labels
# =========================================================================== #
# Feature: honest-gates, Property 3: One artifact per page with unique labels
#
# Validates: Requirements 1.3
#
# For a generated .drawio file written to disk, cli.parse_artifacts returns
# exactly one Artifact per page, in document order, and the artifact labels are
# all unique: `<file>#<page>` for a multi-page file, plain `<file>` for a single
# page. parse_artifacts reads from disk, so each example is serialized to a tmp
# path under the deadline=None filesystem profile. Duplicate <diagram name>s are
# disambiguated `name`, `name (2)`, … exactly as parse_drawio names its pages,
# which keeps the labels unique even when two pages share a name.

import os  # noqa: E402

from rule_engine.cli import parse_artifacts  # noqa: E402


@S.fs_settings
@given(model=S.diagram_models(min_pages=1, max_pages=4))
def test_property_3_one_artifact_per_page_unique_labels(
    tmp_path, model: DiagramModel
) -> None:
    assume(_well_formed(model))

    # parse_artifacts reads from disk; serialize this example to a fresh tmp
    # file named ``diagram.drawio`` so its labels match ``_PATH``'s stem. The
    # ``function_scoped_fixture`` health check is suppressed by the honest-gates
    # profiles, so reusing ``tmp_path`` across examples is fine; each example
    # rewrites and then removes its own file.
    drawio_path = tmp_path / "diagram.drawio"
    drawio_path.write_text(S.serialize_drawio(model), encoding="utf-8")

    try:
        artifacts = parse_artifacts(str(drawio_path))

        # R1.3: exactly one Artifact per page.
        assert len(artifacts) == len(model.pages)

        # The pages parse_drawio produced, in order, with duplicate names
        # disambiguated. The parser is the authority; _expected_page_names
        # mirrors its naming so the label shape can be checked independently.
        pages = parse_drawio(drawio_path.read_text(encoding="utf-8"), path=_PATH)
        assert len(pages) == len(artifacts)
        expected_names = _expected_page_names(model)

        multi = len(pages) > 1
        # Zip artifacts against the expected page names in document order.
        for artifact, page_name in zip(artifacts, expected_names):
            assert artifact.page == page_name
            # Label is <file>#<page> for a multi-page file, plain <file> for a
            # single page.
            expected_label = (
                f"{str(drawio_path)}#{page_name}" if multi else str(drawio_path)
            )
            assert artifact.label == expected_label

        # All labels are unique across the returned artifacts, whichever form
        # they took (the single-page file has one label; a multi-page file's
        # labels differ by their disambiguated page name).
        labels = [a.label for a in artifacts]
        assert len(set(labels)) == len(labels)
    finally:
        # Clean up the per-example temp file/dir.
        try:
            os.remove(drawio_path)
        except OSError:
            pass

# =========================================================================== #
# Property 4: Parse or block
# =========================================================================== #
# Feature: honest-gates, Property 4: Parse or block
#
# Validates: Requirements 1.8, 1.9
#
# Rule 1 of the design ("Parse or block"): anything a gate cannot read becomes a
# Blocking_Finding, never a silent skip. Concretely, for any input that
# parse_drawio cannot parse — malformed XML, a DTD / entity declaration, an
# undecompressable page, or non-numeric geometry — cli.parse_artifacts (which
# reads from disk) returns an Artifact whose lint result carries a parse-error
# ERROR finding, so the artifact is blocked from publication. It is never
# returned silently clean. Conversely, a well-formed generated diagram parses
# with no parse-error finding.
#
# parse_artifacts reads the file from disk, so each malformed / well-formed
# example is written to a fresh tmp path under the deadline=None filesystem
# profile, then removed.

from rule_engine.linter import RULE_PARSE_ERROR, Severity, lint  # noqa: E402

# Local id alphabet (the unquoted-safe set) for the page/cell names woven into
# the malformed documents below — kept independent of the strategies module.
_P4_IDS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"


def _lint_from_disk(tmp_path, text: str):
    """Write ``text`` to a tmp ``.drawio``, parse + lint every artifact, clean up.

    Returns the list of ``(artifact, lint_result)`` pairs. parse_artifacts reads
    from disk (R1.8 is about the on-disk file), so the example is materialized to
    a fresh file that is removed in the ``finally`` — reusing ``tmp_path`` across
    Hypothesis examples is safe because each example rewrites then deletes it.
    """
    drawio_path = tmp_path / "diagram.drawio"
    drawio_path.write_text(text, encoding="utf-8")
    try:
        artifacts = parse_artifacts(str(drawio_path))
        return [(art, lint(art)) for art in artifacts]
    finally:
        try:
            os.remove(drawio_path)
        except OSError:
            pass


def _has_parse_error(result) -> bool:
    return any(
        f["rule"] == RULE_PARSE_ERROR
        and f["severity"] == Severity.ERROR.value
        for f in result["findings"]
    )


# --------------------------------------------------------------------------- #
# 4a. Every unparsable input is blocked with a parse-error ERROR.
# --------------------------------------------------------------------------- #

# The four unparsable shapes design §1 enumerates as DrawioParseError causes:
#   * malformed XML (expat error),
#   * a DTD / entity declaration (billion-laughs, external entity — R1.9),
#   * an undecompressable compressed page,
#   * non-numeric geometry.
# Each combinator returns a .drawio *text* that parse_drawio must reject. The
# strategy draws which shape to build plus a little randomness within it, so the
# property covers the whole class rather than one fixed document.


@st.composite
def _malformed_drawio(draw: st.DrawFn) -> str:
    kind = draw(
        st.sampled_from(
            [
                "not-xml",
                "unclosed-tag",
                "junk-prefix",
                "doctype",
                "internal-entity",
                "billion-laughs",
                "external-entity",
                "bad-compressed-page",
                "non-numeric-geometry",
            ]
        )
    )
    name = draw(st.text(alphabet=_P4_IDS, min_size=1, max_size=6))

    if kind == "not-xml":
        # Arbitrary non-whitespace characters that never form an XML document
        # (whitespace-only text has no root element — a different, valid-input
        # edge case that is not what this shape is exercising).
        return draw(st.text(alphabet="quxz{}[]!@#", min_size=1, max_size=40))

    if kind == "unclosed-tag":
        return f"<mxfile><diagram name=\"{name}\"><mxGraphModel><root>"

    if kind == "junk-prefix":
        # Well-formed model with non-whitespace junk before the root element.
        # (Leading *whitespace* before the root is valid XML, so the junk is
        # drawn from a non-space, non-'<' alphabet to guarantee an expat error.)
        junk = draw(st.text(alphabet="zx09!?", min_size=1, max_size=8))
        return junk + "<mxfile><diagram name=\"p\"><mxGraphModel><root>" \
            "<mxCell id=\"0\" /></root></mxGraphModel></diagram></mxfile>"

    if kind == "doctype":
        return (
            "<!DOCTYPE mxfile>"
            "<mxfile><diagram name=\"p\"><mxGraphModel><root>"
            "<mxCell id=\"0\" /></root></mxGraphModel></diagram></mxfile>"
        )

    if kind == "internal-entity":
        return (
            "<!DOCTYPE mxfile [ <!ENTITY x \"y\"> ]>"
            "<mxfile><diagram name=\"p\"><mxGraphModel><root>"
            "<mxCell id=\"0\" /></root></mxGraphModel></diagram></mxfile>"
        )

    if kind == "billion-laughs":
        # The classic entity-expansion bomb (R1.9): rejected at the DOCTYPE.
        return (
            "<!DOCTYPE lolz ["
            "  <!ENTITY lol \"lol\">"
            "  <!ENTITY lol2 \"&lol;&lol;&lol;&lol;&lol;\">"
            "  <!ENTITY lol3 \"&lol2;&lol2;&lol2;&lol2;&lol2;\">"
            "]>"
            "<mxfile><diagram name=\"p\"><mxGraphModel><root>"
            "<mxCell id=\"0\" value=\"&lol3;\" /></root>"
            "</mxGraphModel></diagram></mxfile>"
        )

    if kind == "external-entity":
        return (
            "<!DOCTYPE mxfile [ <!ENTITY ext SYSTEM \"file:///etc/passwd\"> ]>"
            "<mxfile><diagram name=\"p\"><mxGraphModel><root>"
            "<mxCell id=\"0\" value=\"&ext;\" /></root>"
            "</mxGraphModel></diagram></mxfile>"
        )

    if kind == "bad-compressed-page":
        # A <diagram> with no <mxGraphModel> child, whose text is not a valid
        # base64(deflateRaw(...)) payload — decompression raises.
        garbage = draw(
            st.text(
                alphabet="!@#$%^&*() ", min_size=1, max_size=20
            )
        )
        return f"<mxfile><diagram name=\"{name}\">{garbage}</diagram></mxfile>"

    # non-numeric-geometry: a well-formed model whose mxGeometry x is not a
    # number, so geometry parsing raises DrawioParseError("non-numeric-geometry").
    bogus = draw(st.text(alphabet="abcXYZ", min_size=1, max_size=6))
    return (
        "<mxfile><diagram name=\"p\"><mxGraphModel><root>"
        "<mxCell id=\"0\" /><mxCell id=\"1\" parent=\"0\" />"
        f"<mxCell id=\"n1\" style=\"rounded=1;\" vertex=\"1\" parent=\"1\">"
        f"<mxGeometry x=\"{bogus}\" y=\"0\" width=\"78\" height=\"78\" "
        "as=\"geometry\" /></mxCell>"
        "</root></mxGraphModel></diagram></mxfile>"
    )


@S.fs_settings
@given(text=_malformed_drawio())
def test_property_4_unparsable_input_is_blocked(tmp_path, text: str) -> None:
    pairs = _lint_from_disk(tmp_path, text)

    # An unparsable file yields at least one artifact, and every artifact it
    # yields is blocked from publication by a parse-error ERROR — never returned
    # silently clean (design rule 1, R1.8 / R1.9).
    assert pairs, "parse_artifacts must not return an empty list for a bad file"
    assert any(_has_parse_error(result) for _art, result in pairs)
    for _art, result in pairs:
        if _has_parse_error(result):
            # The blocking finding is the reason it is ineligible.
            assert result["eligible_for_publication"] is False


# --------------------------------------------------------------------------- #
# 4b. A well-formed generated diagram parses without a parse-error.
# --------------------------------------------------------------------------- #
# The converse half: the same on-disk path that blocks a malformed file must NOT
# manufacture a parse-error for a diagram that parse_drawio can read. Any other
# (layout / style) findings are irrelevant here — the claim is only that a
# parseable file is never reported as unparsable.


@S.fs_settings
@given(model=S.diagram_models(min_pages=1, max_pages=3))
def test_property_4_well_formed_diagram_has_no_parse_error(
    tmp_path, model: DiagramModel
) -> None:
    assume(_well_formed(model))
    pairs = _lint_from_disk(tmp_path, S.serialize_drawio(model))

    # One artifact per page (Property 3), and none of them carries a parse-error.
    assert len(pairs) == len(model.pages)
    for _art, result in pairs:
        assert not _has_parse_error(result)
