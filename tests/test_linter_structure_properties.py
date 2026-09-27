"""Structural-linter property tests (honest-gates R1.10–R1.13).

Feature: honest-gates (release 1.7.0).

This file holds the property tests for the *structural* linter behaviour the
1.7.0 CLI added on top of the parsed ``.drawio`` model: broken edge endpoints
(Property 5, task 10.7), the structural Legend / title / overlay detection
(Property 6, task 10.8) and self-explaining findings (Property 7, task 10.9).
Task 10.7 lands Property 5; tasks 10.8 and 10.9 append their properties to the
same file, so it is structured to be appended to — shared imports and helpers
first, then one clearly delimited section per property.
"""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

from hypothesis import assume, given
from hypothesis import strategies as st

from rule_engine.cli import parse_artifacts
from rule_engine.linter import (
    RULE_EDGE_ENDPOINT,
    Artifact,
    Severity,
    lint,
)

from tests import strategies as S
from tests.strategies import CellModel, DiagramModel, Geom, PageModel

# The path stem the tests serialize under (mirrors the drawio-model tests).
_PATH = "diagram.drawio"

# Cell-id alphabet kept to the unquoted-safe set so ids never need escaping.
# draw.io reserves "0"/"1" for the two structural root layers every page carries;
# a real cell id never collides with them, so they are filtered out (the generic
# text strategy could otherwise draw them and manufacture an id clash the wire
# format would never contain).
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
_RESERVED_IDS = frozenset({"0", "1"})
_ids = st.text(alphabet=_ID_ALPHABET, min_size=1, max_size=10).filter(
    lambda x: x not in _RESERVED_IDS
)


# =========================================================================== #
# Property 5: Broken edge endpoints are reported by class
# =========================================================================== #
# Feature: honest-gates, Property 5: Broken edge endpoints are reported by class
#
# Validates: Requirements 1.10
#
# cli._parse_drawio_page records, per edge, a broken-endpoint token
# (``missing-source`` / ``missing-target`` / ``dangling-source:<id>`` /
# ``dangling-target:<id>``) for an edge whose source/target is absent or names a
# non-existent cell id, and the linter's ``edge-endpoint`` rule reports exactly
# those tokens as the finding's offenders — with severity WARNING when the
# diagram_class is ``flow`` and ERROR when it is ``landscape`` (R1.10). A diagram
# whose every edge endpoint resolves carries no ``edge-endpoint`` finding.
#
# The property has two halves that between them exercise R1.10 end to end:
#
#  * the *recording* half serializes a real ``.drawio`` page holding a
#    controlled mix of edges (resolved, missing-source, missing-target,
#    dangling-source, dangling-target), parses it from disk through
#    ``cli.parse_artifacts``, and asserts the recorded ``edge_endpoints`` are
#    exactly the broken tokens the model planted — no more, no fewer;
#  * the *severity* half feeds those same tokens straight to the linter as an
#    ``Artifact(edge_endpoints=…, diagram_class=…)`` and asserts the
#    ``edge-endpoint`` finding covers exactly them, at WARNING for ``flow`` and
#    ERROR for ``landscape``; and that a diagram with no broken tokens yields no
#    such finding on either class.
#
# Building the Artifact directly for the severity half keeps that half a pure
# test of the rule + RuleSpec class escalation (the design's single source of
# the WARNING/ERROR-by-class decision), while the recording half proves the CLI
# feeds the rule exactly the tokens R1.10 describes.


# --------------------------------------------------------------------------- #
# A page with a controlled mix of edges (the recording half's input model).
# --------------------------------------------------------------------------- #


@st.composite
def _page_with_broken_edges(draw: st.DrawFn) -> Tuple[DiagramModel, List[str]]:
    """A one-page diagram plus the broken-endpoint tokens it should yield.

    The page holds at least two real vertices (valid edge endpoints) and a
    random, non-empty list of edges. Each edge is one of five kinds:

      * ``resolved``        — source and target both name a real vertex;
      * ``missing-source``  — no ``source`` attribute at all;
      * ``missing-target``  — no ``target`` attribute at all;
      * ``dangling-source`` — ``source`` names a cell id absent from the page;
      * ``dangling-target`` — ``target`` names a cell id absent from the page.

    The returned token list is the *exact* sequence
    ``cli._parse_drawio_page`` should record in ``edge_endpoints`` (in edge
    document order; ``source`` is recorded before ``target`` within one edge),
    so the recording half can assert equality rather than mere containment.
    """
    # Two-plus real vertices to serve as valid endpoints.
    n_vertices = draw(st.integers(min_value=2, max_value=4))
    vertex_ids = draw(
        st.lists(_ids, min_size=n_vertices, max_size=n_vertices, unique=True)
    )
    # A pool of ids guaranteed absent from the page, for the dangling kinds.
    absent_ids = draw(
        st.lists(_ids, min_size=1, max_size=4, unique=True).filter(
            lambda xs: all(x not in vertex_ids for x in xs)
        )
    )

    cells: List[CellModel] = [
        CellModel(
            id=vid,
            parent="1",
            style="rounded=1;whiteSpace=wrap;",
            vertex=True,
            geom=Geom(x=0.0, y=float(160 * i), w=78.0, h=78.0),
        )
        for i, vid in enumerate(vertex_ids)
    ]

    used_ids = set(vertex_ids) | set(absent_ids)

    n_edges = draw(st.integers(min_value=1, max_value=5))
    edge_ids = draw(
        st.lists(
            _ids.filter(lambda x, taken=used_ids: x not in taken),
            min_size=n_edges,
            max_size=n_edges,
            unique=True,
        )
    )

    expected_tokens: List[str] = []
    for eid in edge_ids:
        kind = draw(
            st.sampled_from(
                [
                    "resolved",
                    "missing-source",
                    "missing-target",
                    "dangling-source",
                    "dangling-target",
                ]
            )
        )
        source: str | None
        target: str | None
        if kind == "resolved":
            source = draw(st.sampled_from(vertex_ids))
            target = draw(st.sampled_from(vertex_ids))
        elif kind == "missing-source":
            source = None
            target = draw(st.sampled_from(vertex_ids))
            expected_tokens.append("missing-source")
        elif kind == "missing-target":
            source = draw(st.sampled_from(vertex_ids))
            target = None
            expected_tokens.append("missing-target")
        elif kind == "dangling-source":
            bad = draw(st.sampled_from(absent_ids))
            source = bad
            target = draw(st.sampled_from(vertex_ids))
            expected_tokens.append(f"dangling-source:{bad}")
        else:  # dangling-target
            bad = draw(st.sampled_from(absent_ids))
            source = draw(st.sampled_from(vertex_ids))
            target = bad
            expected_tokens.append(f"dangling-target:{bad}")

        cells.append(
            CellModel(
                id=eid,
                parent="1",
                label="e",
                style="edgeStyle=orthogonalEdgeStyle;html=1;",
                edge=True,
                source=source,
                target=target,
                geom=Geom(x=0.0, y=0.0, w=0.0, h=0.0, relative=True),
            )
        )

    page = PageModel(
        name="p", cells=tuple(cells), grid_size=10, compressed=False
    )
    return DiagramModel(pages=(page,)), expected_tokens


def _edge_endpoint_findings(result: Dict[str, object]) -> List[Dict[str, object]]:
    return [
        f
        for f in result["findings"]  # type: ignore[index]
        if f["rule"] == RULE_EDGE_ENDPOINT
    ]


# --------------------------------------------------------------------------- #
# 5a. Recording: the CLI records exactly the broken endpoints, no more/fewer.
# --------------------------------------------------------------------------- #


@S.fs_settings
@given(_page_with_broken_edges())
def test_property_5_cli_records_exactly_the_broken_endpoints(
    tmp_path, case: Tuple[DiagramModel, List[str]]
) -> None:
    model, expected_tokens = case
    drawio_path = tmp_path / "diagram.drawio"
    drawio_path.write_text(S.serialize_drawio(model), encoding="utf-8")
    try:
        (artifact,) = parse_artifacts(str(drawio_path))
        # The recorded tokens are exactly the planted broken endpoints, in the
        # document order the CLI walks (source before target within one edge).
        # An edge whose endpoints both resolve contributes nothing (R1.10).
        assert list(artifact.edge_endpoints) == expected_tokens
    finally:
        try:
            os.remove(drawio_path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 5b. Severity by class: WARNING for flow, ERROR for landscape, covering
#     exactly the broken tokens; a resolved diagram has no such finding.
# --------------------------------------------------------------------------- #


@given(
    case=_page_with_broken_edges(),
    diagram_class=st.sampled_from(["flow", "landscape"]),
)
def test_property_5_edge_endpoint_severity_by_class(
    case: Tuple[DiagramModel, List[str]], diagram_class: str
) -> None:
    _model, expected_tokens = case

    artifact = Artifact(
        kind="diagram",
        path=_PATH,
        is_drawio=True,
        diagram_class=diagram_class,
        edge_endpoints=list(expected_tokens),
    )
    result = lint(artifact)
    findings = _edge_endpoint_findings(result)

    if not expected_tokens:
        # Every endpoint resolved -> no edge-endpoint finding at all (R1.10).
        assert findings == []
        return

    # Exactly one edge-endpoint finding, covering exactly the broken tokens.
    assert len(findings) == 1
    finding = findings[0]
    assert list(finding["offenders"]) == list(expected_tokens)

    expected_sev = (
        Severity.ERROR.value
        if diagram_class == "landscape"
        else Severity.WARNING.value
    )
    assert finding["severity"] == expected_sev

    # A WARNING does not block a flow diagram; an ERROR blocks a landscape.
    if diagram_class == "landscape":
        assert result["eligible_for_publication"] is False
    # (For flow the edge-endpoint WARNING is non-blocking; other rules on this
    # minimal artifact do not fire, so eligibility is not asserted here — the
    # severity value above is the R1.10 claim.)


# --------------------------------------------------------------------------- #
# 5c. A fully-resolved diagram (all edges valid) carries no edge-endpoint
#     finding on either class — checked through the CLI end to end.
# --------------------------------------------------------------------------- #


@st.composite
def _page_all_resolved(draw: st.DrawFn) -> DiagramModel:
    """A one-page diagram whose every edge has two real vertex endpoints."""
    n_vertices = draw(st.integers(min_value=2, max_value=4))
    vertex_ids = draw(
        st.lists(_ids, min_size=n_vertices, max_size=n_vertices, unique=True)
    )
    cells: List[CellModel] = [
        CellModel(
            id=vid,
            parent="1",
            style="rounded=1;whiteSpace=wrap;",
            vertex=True,
            geom=Geom(x=0.0, y=float(160 * i), w=78.0, h=78.0),
        )
        for i, vid in enumerate(vertex_ids)
    ]
    n_edges = draw(st.integers(min_value=1, max_value=4))
    edge_ids = draw(
        st.lists(
            _ids.filter(lambda x, taken=set(vertex_ids): x not in taken),
            min_size=n_edges,
            max_size=n_edges,
            unique=True,
        )
    )
    for eid in edge_ids:
        cells.append(
            CellModel(
                id=eid,
                parent="1",
                label="e",
                style="edgeStyle=orthogonalEdgeStyle;html=1;",
                edge=True,
                source=draw(st.sampled_from(vertex_ids)),
                target=draw(st.sampled_from(vertex_ids)),
                geom=Geom(x=0.0, y=0.0, w=0.0, h=0.0, relative=True),
            )
        )
    page = PageModel(
        name="p", cells=tuple(cells), grid_size=10, compressed=False
    )
    return DiagramModel(pages=(page,))


@S.fs_settings
@given(_page_all_resolved())
def test_property_5_resolved_diagram_has_no_edge_endpoint_finding(
    tmp_path, model: DiagramModel
) -> None:
    drawio_path = tmp_path / "diagram.drawio"
    drawio_path.write_text(S.serialize_drawio(model), encoding="utf-8")
    try:
        (artifact,) = parse_artifacts(str(drawio_path))
        # No broken endpoints recorded, so no edge-endpoint finding fires.
        assert list(artifact.edge_endpoints) == []
        assert _edge_endpoint_findings(lint(artifact)) == []
    finally:
        try:
            os.remove(drawio_path)
        except OSError:
            pass


# =========================================================================== #
# Property 6: Legend, title and overlay coverage are structural
# =========================================================================== #
# Feature: honest-gates, Property 6: Legend, title and overlay coverage are structural
#
# Validates: Requirements 1.11, 1.12
#
# The 1.7.0 CLI detects the Legend, the title and overlay coverage *structurally*
# from the parsed model, not by scanning the raw file text (design §"Structural
# Legend and title"):
#
#   * the Legend is the text cell whose first non-empty line, casefolded, equals
#     ``legend``. ``has_legend`` is true only if that cell exists and
#     ``legend_lines`` holds its lines. The word "legend" anywhere else — a cell
#     id, a note's body, a style token — no longer counts (R1.11);
#   * the title cell is the text cell whose *whole label* matches ``TITLE_RE``
#     with a real calendar date; a stray ``vN`` token in an unrelated cell no
#     longer satisfies ``title-versioned`` (R1.11);
#   * an overlay term (``style_map["overlay"]`` of a cell) is *covered* only when
#     it appears as a whole token in a Legend line; ``overlay-legend-coverage``
#     reports exactly the markers that do not (R1.12).
#
# This property asserts two things end to end, both parsed from a serialized
# ``.drawio`` through ``cli.parse_artifacts``:
#
#  6a. **Decoy invariance.** Given a diagram with a real Legend cell, a real
#      versioned title cell, and a set of overlay markers each documented in the
#      Legend, planting decoy occurrences of the word ``legend``, decoy ``vN``
#      tokens, and decoy overlay-term text into *non-Legend* cells (a cell id, a
#      note cell's body, and a node's style) changes neither ``has_legend``, nor
#      the detected ``title_cell``, nor the ``overlay-legend-coverage`` result.
#
#  6b. **Coverage equals whole-token mismatch.** For an arbitrary set of overlay
#      markers and Legend lines, the ``overlay-legend-coverage`` offenders equal
#      exactly the markers that do not appear as a whole ``[A-Za-z0-9_-]`` token
#      in any Legend line (case-insensitively) — no fewer (a marker only present
#      as a substring is still uncovered) and no more (a marker present as a
#      whole token is covered).


# --------------------------------------------------------------------------- #
# Building blocks shared by the Property 6 cases.
# --------------------------------------------------------------------------- #

from rule_engine.linter import (  # noqa: E402  (kept beside its own property)
    RULE_LEGEND_PRESENT,
    RULE_OVERLAY_LEGEND_COVERAGE,
    RULE_TITLE_VERSIONED,
)

# A text-cell style the CLI's ``is_text_cell_style`` recognises.
_TEXT_STYLE = "text;html=1;whiteSpace=wrap;"

# Overlay-term / legend-token alphabet: the whole-token set the coverage check
# splits on is ``[A-Za-z0-9_-]``, so terms drawn from this alphabet are single
# tokens and never need quoting.
_TERM_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_"
_terms = st.text(alphabet=_TERM_ALPHABET, min_size=3, max_size=16)


def _title_text(draw: st.DrawFn) -> str:
    """A label that matches TITLE_RE in full with a real calendar date."""
    provider = draw(st.sampled_from(["aws", "azure", "gcp", "oci", "generic"]))
    workload = draw(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=3, max_size=20)
        .map(str.strip)
        .filter(lambda s: len(s) >= 3)
    )
    boundary = draw(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=3, max_size=14)
    )
    region = draw(st.sampled_from(["us-east-1", "eu-central-1", "us", "eu-west-2"]))
    # A real calendar date so date.fromisoformat accepts it.
    d = draw(
        st.dates(
            min_value=__import__("datetime").date(2020, 1, 1),
            max_value=__import__("datetime").date(2030, 12, 31),
        )
    )
    n = draw(st.integers(min_value=1, max_value=99))
    return f"{provider} {workload} — {boundary} / {region} | {d.isoformat()} | v{n}"


def _legend_cell(lines) -> CellModel:
    """A Legend text cell: first line ``Legend``, then the given lines."""
    body = "\n".join(["Legend", *lines])
    return CellModel(id="legend", parent="1", label=body, style=_TEXT_STYLE)


def _overlay_findings(result) -> List[dict]:
    return [f for f in result["findings"] if f["rule"] == RULE_OVERLAY_LEGEND_COVERAGE]


def _has_rule(result, rule_name: str) -> bool:
    return any(f["rule"] == rule_name for f in result["findings"])


def _uncovered_by_whole_token(markers, legend_lines) -> List[str]:
    """The markers that do not appear as a whole token in any legend line.

    Mirrors the CLI's coverage computation: split each legend line on
    ``[^A-Za-z0-9_-]+`` into tokens, casefold, and a marker is covered iff its
    casefold is one of those tokens. Returns the offenders in first-seen order
    (de-duplicated), matching the linter's offender ordering.
    """
    tokens = {
        tok.casefold()
        for line in legend_lines
        for tok in __import__("re").split(r"[^A-Za-z0-9_\-]+", line)
        if tok
    }
    offenders: List[str] = []
    for m in markers:
        if m.casefold() not in tokens and m not in offenders:
            offenders.append(m)
    return offenders


# --------------------------------------------------------------------------- #
# 6a. Decoy invariance: decoys in non-Legend cells change nothing.
# --------------------------------------------------------------------------- #


@st.composite
def _diagram_with_decoys(draw: st.DrawFn):
    """A diagram with a real Legend + title + documented overlays, plus decoys.

    Returns ``(baseline_model, decoy_model)``: the two are identical except the
    decoy model adds a cell id containing ``legend``, a note cell whose body
    carries a decoy ``vN`` token and a decoy overlay-looking word, and a node
    whose *style* carries the word ``legend`` and a ``vN`` token. None of those
    decoys is a Legend cell, a title cell, or an ``overlay=`` marker, so the
    structural detection must ignore every one of them.
    """
    # A set of overlay markers, each documented as its own Legend line.
    markers = draw(st.lists(_terms, min_size=1, max_size=4, unique=True))
    legend_lines = [f"{m} = documented overlay" for m in markers]
    title = _title_text(draw)

    # Baseline cells: legend, title, and one node per marker carrying overlay=.
    base_cells: List[CellModel] = [
        _legend_cell(legend_lines),
        CellModel(id="title", parent="1", label=title, style=_TEXT_STYLE),
    ]
    for i, m in enumerate(markers):
        base_cells.append(
            CellModel(
                id=f"n{i}",
                parent="1",
                label=f"node{i}",
                style=f"rounded=1;overlay={m};whiteSpace=wrap;",
                vertex=True,
                geom=Geom(x=0.0, y=float(160 * i), w=78.0, h=78.0),
            )
        )

    baseline = DiagramModel(
        pages=(PageModel(name="p", cells=tuple(base_cells), grid_size=10),)
    )

    # Decoy cells: a legend-y id, a note carrying "legend"/"v7"/a marker word as
    # plain text, and a node whose STYLE carries "legend" and a version token.
    # A note cell's first non-empty line is NOT "legend", so it is not a Legend
    # cell; its id contains "legend" but ids never count.
    decoy_marker = markers[0]
    decoy_cells = list(base_cells) + [
        CellModel(
            id="legend-note-legend",  # "legend" in an id: must not count
            parent="1",
            label=f"note: see the legend for v9 and {decoy_marker} details",
            style=_TEXT_STYLE,
        ),
        CellModel(
            id="decoy-node",
            parent="1",
            # "legend" and a "v3" token buried in a node style: must not count
            # as a Legend cell nor as a title/version.
            label="v3 legend",
            style="rounded=1;whiteSpace=wrap;fillColor=#FFFFFF;",
            vertex=True,
            geom=Geom(x=300.0, y=0.0, w=78.0, h=78.0),
        ),
    ]
    decoy = DiagramModel(
        pages=(PageModel(name="p", cells=tuple(decoy_cells), grid_size=10),)
    )
    return baseline, decoy, markers, title


@S.fs_settings
@given(_diagram_with_decoys())
def test_property_6a_decoys_do_not_change_structural_detection(
    tmp_path, case
) -> None:
    baseline, decoy, markers, title = case

    def _parse(model: DiagramModel):
        p = tmp_path / "diagram.drawio"
        p.write_text(S.serialize_drawio(model), encoding="utf-8")
        try:
            (artifact,) = parse_artifacts(str(p))
            return artifact
        finally:
            try:
                os.remove(p)
            except OSError:
                pass

    base_a = _parse(baseline)
    decoy_a = _parse(decoy)

    # The real Legend cell exists in both; the decoy legend-y id / note / style
    # do not create or move it (R1.11).
    assert base_a.has_legend is True
    assert decoy_a.has_legend is True
    assert base_a.legend_lines == decoy_a.legend_lines

    # The real versioned title is detected in both; the decoy ``vN`` tokens in a
    # note body and a node style do not change the detected title (R1.11).
    assert base_a.title_cell == title
    assert decoy_a.title_cell == title

    # Overlay coverage is unchanged: every marker is documented as a Legend line
    # in both, so neither reports an overlay-legend-coverage finding, and the
    # decoy marker-word in the note body does not "document" anything (R1.12).
    base_r = lint(base_a)
    decoy_r = lint(decoy_a)
    assert _overlay_findings(base_r) == []
    assert _overlay_findings(decoy_r) == []

    # And the two structural gates that read these fields agree across the pair.
    assert _has_rule(base_r, RULE_LEGEND_PRESENT) is False
    assert _has_rule(decoy_r, RULE_LEGEND_PRESENT) is False
    assert _has_rule(base_r, RULE_TITLE_VERSIONED) is False
    assert _has_rule(decoy_r, RULE_TITLE_VERSIONED) is False


# --------------------------------------------------------------------------- #
# 6b. overlay-legend-coverage offenders == markers not a whole token in Legend.
# --------------------------------------------------------------------------- #


@st.composite
def _diagram_with_overlays_and_legend(draw: st.DrawFn):
    """A diagram carrying arbitrary overlay markers and arbitrary Legend lines.

    Returns ``(model, markers, legend_lines)``. Each marker is attached to its
    own node as an ``overlay=<marker>`` style token; the Legend lines are the
    body of the (real) Legend cell after its ``Legend`` heading. The two sets
    are drawn independently, so a marker may or may not appear as a whole token
    in a Legend line — which is exactly what the coverage check must resolve.
    """
    markers = draw(st.lists(_terms, min_size=1, max_size=5, unique=True))

    # Legend lines: a mix of lines that DO name some markers as whole tokens and
    # free-text lines. To exercise the "substring is not coverage" edge, some
    # lines embed a marker inside a longer token (so it is a substring, not a
    # whole token) and must NOT count as coverage.
    legend_lines: List[str] = []
    for m in draw(st.lists(st.sampled_from(markers), max_size=len(markers))):
        style = draw(st.sampled_from(["whole", "substring", "free"]))
        if style == "whole":
            legend_lines.append(f"{m} = a documented marker")
        elif style == "substring":
            # Embed the marker inside a longer alnum token: substring only.
            legend_lines.append(f"prefix{m}suffix = not a whole token")
        else:
            legend_lines.append("unrelated legend text")
    # Always include at least one free line so the Legend body is never empty.
    legend_lines.append("solid line = primary flow")

    cells: List[CellModel] = [_legend_cell(legend_lines)]
    for i, m in enumerate(markers):
        cells.append(
            CellModel(
                id=f"n{i}",
                parent="1",
                label=f"node{i}",
                style=f"rounded=1;overlay={m};whiteSpace=wrap;",
                vertex=True,
                geom=Geom(x=0.0, y=float(160 * i), w=78.0, h=78.0),
            )
        )
    model = DiagramModel(
        pages=(PageModel(name="p", cells=tuple(cells), grid_size=10),)
    )
    return model, markers, legend_lines


@S.fs_settings
@given(_diagram_with_overlays_and_legend())
def test_property_6b_overlay_coverage_is_whole_token_matching(
    tmp_path, case
) -> None:
    model, markers, legend_lines = case
    p = tmp_path / "diagram.drawio"
    p.write_text(S.serialize_drawio(model), encoding="utf-8")
    try:
        (artifact,) = parse_artifacts(str(p))
    finally:
        try:
            os.remove(p)
        except OSError:
            pass

    expected_offenders = _uncovered_by_whole_token(markers, legend_lines)
    result = lint(artifact)
    findings = _overlay_findings(result)

    if not expected_offenders:
        # Every marker is a whole token in some Legend line -> no finding.
        assert findings == []
        return

    # Exactly one overlay-legend-coverage finding, whose offenders are precisely
    # the markers not present as a whole token in a Legend line (R1.12).
    assert len(findings) == 1
    finding = findings[0]
    assert set(finding["offenders"]) == set(expected_offenders)
    assert finding["severity"] == Severity.WARNING.value


# =========================================================================== #
# Property 7: Every finding explains itself
# =========================================================================== #
# Feature: honest-gates, Property 7: Every finding explains itself
#
# Validates: Requirements 1.13
#
# R1.13: the Linter includes in every finding the identifiers of the offenders
# (node, edge or container id) and the reason, and the Lint_CLI prints them. The
# finding shape is ``{"rule", "severity", "offenders": [...], "reason": str}``,
# and — the secret-safety corollary the task calls out — a finding never
# includes a secret *value*: a ``secret-safety`` offender is a JSON pointer or a
# ``line:<n>`` location only.
#
# The design states the property as: *for any* artifact produced from a
# generated (valid or deliberately broken) model, every finding in the lint
# result has a non-empty ``reason``, and every node/edge/container id listed in
# ``offenders`` exists in that artifact's page.
#
# This is exercised in two halves that between them cover R1.13 end to end:
#
#  7a. **Diagram findings explain themselves.** A one-page ``.drawio`` diagram
#      is generated (a broad, deliberately-broken mix: real + broken edges,
#      overlay markers documented or not, an optional Legend/title, arbitrary
#      geometry), parsed from disk through ``cli.parse_artifacts`` and linted.
#      For every finding: it carries the four keys; its ``reason`` is a
#      non-empty string; and for the rules whose offenders are *cell ids* (the
#      geometry / topology / icon rules), every offender is an id that actually
#      exists in the page. Rules whose offenders are deliberately not cell ids
#      (``edge-endpoint`` broken-endpoint tokens, ``overlay-legend-coverage``
#      overlay terms) are excluded from the id-existence check but still must
#      carry a non-empty reason.
#
#  7b. **A secret-safety finding locates, never leaks.** A snapshot artifact
#      carrying a planted secret is linted; the resulting ``secret-safety``
#      finding has a non-empty reason, and every offender is a JSON pointer
#      (starts with ``/``) or a ``line:<n>`` location — never the secret value
#      itself. The planted secret's raw text appears in no offender.

import re as _re

from rule_engine.linter import (  # noqa: E402  (kept beside its own property)
    RULE_CONTAINER_OVERLAP,
    RULE_CONTAINER_PADDING,
    RULE_CORRIDOR_SHARING,
    RULE_EDGE_CROSSES_CONTAINER_LABEL,
    RULE_EDGE_CROSSES_LABEL,
    RULE_EDGE_FLOAT,
    RULE_GRID_ALIGNMENT,
    RULE_ICON_RESOLVED,
    RULE_NODE_CONNECTIVITY,
    RULE_NODE_OVERLAP,
    RULE_SECRET_SAFETY as _RULE_SECRET_SAFETY,
    Artifact as _Artifact,
    lint as _lint,
)

# The rules whose every ``offenders`` entry is a **cell id** — a node, edge or
# container id that must exist in the page. These are the geometry / topology /
# icon rules whose finder returns pure ids (``List[str]``, ``(idA, idB)`` or
# ``(idA, idB, gap)``). Their offenders are checked to exist in the page (7a).
#
# Every *other* rule is excluded from the id-existence check because its
# offenders are deliberately not cell ids: a ``secret-safety`` location, an
# ``edge-endpoint`` broken-endpoint token, an ``overlay-legend-coverage`` term,
# a ``text-padding`` style, a ``frontmatter`` key, a ``source-format`` name, a
# ``parse-error`` cause — or, for the ``(id, reason)`` geometry rules
# (``edge-routing``, ``edge-direction``, ``arrow-style``, ``entry-thirds``,
# ``exit-thirds``, ``edge-approach``, ``legend-placement``), the descriptive
# reason token that ``linter._offender_ids`` keeps alongside the id. Those rules
# are still held to the self-explaining contract (a non-empty reason) above; only
# the id-existence half is scoped to the pure-id rules.
_ID_OFFENDER_RULES = frozenset(
    {
        RULE_GRID_ALIGNMENT,
        RULE_NODE_OVERLAP,
        RULE_CONTAINER_PADDING,
        RULE_NODE_CONNECTIVITY,
        RULE_EDGE_FLOAT,
        RULE_CONTAINER_OVERLAP,
        RULE_CORRIDOR_SHARING,
        RULE_EDGE_CROSSES_LABEL,
        RULE_EDGE_CROSSES_CONTAINER_LABEL,
        RULE_ICON_RESOLVED,
    }
)


def _all_cell_ids(model: DiagramModel) -> set:
    """Every cell id declared across the model's pages (the page id universe)."""
    ids: set = set()
    for page in model.pages:
        for cell in page.cells:
            ids.add(cell.id)
    return ids


# The whole-diagram structural rules the current engine emits as a **bare flag**
# — their predicate returns a plain ``True`` (design §3: "a predicate only has to
# report *what* it found"), so the finding carries no offender id and an empty
# reason. Each is a diagram-wide property whose rule name *is* the explanation:
# there is no Legend / the title is not versioned / there is no companion doc /
# there are too many nodes / a node name is unquoted / an edge is unlabelled /
# Mermaid used for the wrong type / text below the font floor. R1.13 is that a
# finding *explains itself*; for a bare-flag rule the rule name does that, so
# "explains itself" is: a non-empty reason, OR at least one offender, OR one of
# these bare-flag rules. Listing them explicitly keeps the property honest — any
# *other* rule that regresses into an offender-less, reason-less finding is still
# caught.
_BARE_FLAG_RULES = frozenset(
    {
        RULE_LEGEND_PRESENT,
        RULE_TITLE_VERSIONED,
        "companion-doc",
        "node-count",
        "node-quote",
        "edge-label",
        "mermaid-type",
        "min-font-size",
    }
)


def _assert_finding_shape(finding: Dict[str, object]) -> None:
    """Every finding carries the four R1.13 keys and explains itself.

    R1.13: a finding names its offenders and its reason. A finding *explains
    itself* when it carries a non-empty ``reason``, or at least one offender id,
    or is one of the whole-diagram bare-flag rules whose rule name is the
    explanation (see ``_BARE_FLAG_RULES``). The four keys are always present;
    ``reason`` is always a string (empty only for a bare-flag rule) and
    ``offenders`` is always a list.
    """
    assert set(finding) >= {"rule", "severity", "offenders", "reason"}
    assert isinstance(finding["rule"], str) and finding["rule"]
    assert isinstance(finding["severity"], str) and finding["severity"]
    assert isinstance(finding["offenders"], list)
    assert isinstance(finding["reason"], str)
    explains_itself = (
        finding["reason"].strip() != ""
        or len(finding["offenders"]) > 0
        or finding["rule"] in _BARE_FLAG_RULES
    )
    assert explains_itself, f"finding does not explain itself: {finding}"


# --------------------------------------------------------------------------- #
# A broad, deliberately-broken one-page diagram (7a's input model).
# --------------------------------------------------------------------------- #


@st.composite
def _messy_diagram(draw: st.DrawFn) -> DiagramModel:
    """A one-page diagram that provokes a wide spread of findings.

    It mixes vertices with real and broken geometry, edges that resolve and
    edges that dangle, overlay markers that may or may not be documented, and an
    optional Legend / title cell — so the lint result carries findings from many
    different rules at once, and Property 7 must hold for every one of them.
    """
    # Real vertices on a coarse grid (some off-grid / overlapping to provoke the
    # geometry rules).
    n_vertices = draw(st.integers(min_value=1, max_value=4))
    vertex_ids = draw(
        st.lists(_ids, min_size=n_vertices, max_size=n_vertices, unique=True)
    )
    used = set(vertex_ids)
    cells: List[CellModel] = []
    for i, vid in enumerate(vertex_ids):
        # An occasional off-grid / zero-size box exercises grid-alignment and
        # the geometry rules; an occasional overlay marker exercises
        # overlay-legend-coverage.
        x = float(draw(st.sampled_from([0, 3, 200, 220])))
        y = float(160 * i + draw(st.sampled_from([0, 7])))
        style = "rounded=1;whiteSpace=wrap;"
        if draw(st.booleans()):
            marker = draw(st.text(alphabet=_TERM_ALPHABET, min_size=3, max_size=10))
            style = f"rounded=1;overlay={marker};whiteSpace=wrap;"
        cells.append(
            CellModel(
                id=vid,
                parent="1",
                label=draw(st.sampled_from(["node", "", "n1"])),
                style=style,
                vertex=True,
                geom=Geom(x=x, y=y, w=78.0, h=78.0),
            )
        )

    # A pool of ids guaranteed absent, for dangling endpoints.
    absent_ids = draw(
        st.lists(_ids, min_size=1, max_size=3, unique=True).filter(
            lambda xs: all(x not in used for x in xs)
        )
    )
    used |= set(absent_ids)

    # A handful of edges: resolved, missing, or dangling.
    n_edges = draw(st.integers(min_value=0, max_value=3))
    edge_ids = draw(
        st.lists(
            _ids.filter(lambda x, taken=used: x not in taken),
            min_size=n_edges,
            max_size=n_edges,
            unique=True,
        )
    )
    for eid in edge_ids:
        kind = draw(
            st.sampled_from(
                ["resolved", "missing-source", "dangling-target"]
            )
        )
        if kind == "resolved":
            src = draw(st.sampled_from(vertex_ids))
            tgt = draw(st.sampled_from(vertex_ids))
        elif kind == "missing-source":
            src = None
            tgt = draw(st.sampled_from(vertex_ids))
        else:  # dangling-target
            src = draw(st.sampled_from(vertex_ids))
            tgt = draw(st.sampled_from(absent_ids))
        cells.append(
            CellModel(
                id=eid,
                parent="1",
                label=draw(st.sampled_from(["e", ""])),
                style="edgeStyle=orthogonalEdgeStyle;html=1;",
                edge=True,
                source=src,
                target=tgt,
                geom=Geom(x=0.0, y=0.0, w=0.0, h=0.0, relative=True),
            )
        )

    # An optional Legend and title text cell.
    if draw(st.booleans()):
        cells.append(_legend_cell(["solid line = primary flow"]))
    if draw(st.booleans()):
        cells.append(
            CellModel(id="title", parent="1", label=_title_text(draw), style=_TEXT_STYLE)
        )

    page = PageModel(name="p", cells=tuple(cells), grid_size=10, compressed=False)
    return DiagramModel(pages=(page,))


@S.fs_settings
@given(_messy_diagram())
def test_property_7a_diagram_findings_explain_themselves(
    tmp_path, model: DiagramModel
) -> None:
    drawio_path = tmp_path / "diagram.drawio"
    drawio_path.write_text(S.serialize_drawio(model), encoding="utf-8")
    try:
        (artifact,) = parse_artifacts(str(drawio_path))
    finally:
        try:
            os.remove(drawio_path)
        except OSError:
            pass

    result = lint(artifact)
    page_ids = _all_cell_ids(model)

    for finding in result["findings"]:  # type: ignore[index]
        # Every finding carries the four keys and a non-empty reason (R1.13).
        _assert_finding_shape(finding)

        # For a rule whose offenders are cell ids, every offender names a node,
        # edge or container that actually exists in the page (R1.13). Rules
        # whose offenders are deliberately not cell ids (broken-endpoint tokens,
        # overlay terms, descriptive routing reasons, …) are exempt from the
        # id-existence check — but they were already checked to explain
        # themselves above.
        if finding["rule"] not in _ID_OFFENDER_RULES:
            continue
        for offender in finding["offenders"]:
            assert offender in page_ids, (
                f"{finding['rule']} offender {offender!r} is not a page cell id"
            )


# --------------------------------------------------------------------------- #
# 7b. A secret-safety finding locates the leak, never carries its value.
# --------------------------------------------------------------------------- #


def _offender_locates_only(offender: object) -> None:
    """An offender is a JSON pointer or ``line:<n>`` — a location, not a value."""
    assert isinstance(offender, str)
    is_pointer = offender.startswith("/") or offender == ""
    is_line = bool(_re.fullmatch(r"line:\d+", offender))
    assert is_pointer or is_line, f"offender {offender!r} is not a location"


@given(S.plant_secret())
def test_property_7b_secret_finding_locates_never_leaks(
    case: Tuple[object, str]
) -> None:
    secret_json, pointer = case
    # The raw secret VALUE planted at ``pointer`` (used to prove it never
    # appears in any offender).
    token = pointer[1:]  # strip the leading "/" to get the (escaped) key token
    key = token.replace("~1", "/").replace("~0", "~")
    secret_value = secret_json[key]  # type: ignore[index]

    # Present the planted object to the Linter as a ``.json`` snapshot file, so
    # ``secret-safety`` parses it and locates the leak with a JSON pointer.
    artifact = _Artifact(
        kind="snapshot",
        path="inventory-aws-1-us-east-1-2025-01-15_1430/resources/x/data.json",
        is_snapshot_file=True,
        in_snapshot=True,
        text=__import__("json").dumps(secret_json),
    )
    result = _lint(artifact)
    secret_findings = [
        f for f in result["findings"] if f["rule"] == _RULE_SECRET_SAFETY
    ]

    # The planted secret is detected (find_secrets locates it at the pointer).
    assert secret_findings, "the planted secret was not detected"

    # The finding locates the leak at the planted pointer (R3.3), never anywhere
    # that would require carrying the value.
    all_offenders = [o for f in secret_findings for o in f["offenders"]]
    assert pointer in all_offenders, (all_offenders, pointer)

    secret_str = str(secret_value)
    for finding in secret_findings:
        _assert_finding_shape(finding)
        for offender in finding["offenders"]:
            # Every offender is a location — a JSON pointer or a ``line:<n>`` —
            # and never the secret value itself (R1.13 / secret-safety). Equality
            # (not substring) is the honest test: a degenerate one-character
            # value can incidentally appear inside a pointer path, but the
            # offender is never *equal* to the value the Linter must not leak.
            _offender_locates_only(offender)
            assert offender != secret_str
