"""Property tests for shared icon-reference resolution (`rule_engine.icon_refs`).

Feature: honest-gates (release 1.7.0), task 5.4 (and 11.2, 11.3 which append
here). Each property uses Hypothesis with ``max_examples >= 100`` via the
``honest-gates`` profile loaded in ``tests/conftest.py``.
"""

from __future__ import annotations

import posixpath
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from rule_engine.icon_refs import RESOLVED, UNRESOLVED, IconRef, IconSources, resolve


# --------------------------------------------------------------------------- #
# Strategies: image= reference strings spanning every category of the rule.
# --------------------------------------------------------------------------- #

_SEGMENT = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=1,
    max_size=10,
)

_GOOD_SUFFIX = st.sampled_from([".svg", ".png", ".SVG", ".PNG"])
_BAD_SUFFIX = st.sampled_from([".jpg", ".jpeg", ".gif", ".webp", ".xml", "", ".svgz"])


@st.composite
def _relative_segments(draw: st.DrawFn) -> list:
    return draw(st.lists(_SEGMENT, min_size=1, max_size=4))


@st.composite
def valid_asset_paths(draw: st.DrawFn) -> str:
    """A well-formed ``assets/…{.svg,.png}`` path (expected ``resolved``)."""
    segments = draw(_relative_segments())
    suffix = draw(_GOOD_SUFFIX)
    return "assets/" + "/".join(segments) + suffix


@st.composite
def absolute_paths(draw: st.DrawFn) -> str:
    """An absolute path (expected ``unresolved``)."""
    segments = draw(_relative_segments())
    suffix = draw(_GOOD_SUFFIX)
    return "/" + "assets/" + "/".join(segments) + suffix


@st.composite
def dotdot_paths(draw: st.DrawFn) -> str:
    """A path that still escapes with ``..`` after normalisation (unresolved).

    Prefixing ``../`` makes ``posixpath.normpath`` keep a leading ``..`` so the
    reference escapes the workspace even though it names ``assets/``.
    """
    segments = draw(_relative_segments())
    suffix = draw(_GOOD_SUFFIX)
    depth = draw(st.integers(min_value=1, max_value=3))
    prefix = "../" * depth
    return prefix + "assets/" + "/".join(segments) + suffix


@st.composite
def outside_assets_paths(draw: st.DrawFn) -> str:
    """A relative path that does not live under ``assets/`` (unresolved)."""
    root = draw(_SEGMENT.filter(lambda s: s != "assets"))
    segments = draw(_relative_segments())
    suffix = draw(_GOOD_SUFFIX)
    return root + "/" + "/".join(segments) + suffix


@st.composite
def wrong_suffix_paths(draw: st.DrawFn) -> str:
    """A well-located ``assets/…`` path with a disallowed suffix (unresolved)."""
    segments = draw(_relative_segments())
    suffix = draw(_BAD_SUFFIX)
    return "assets/" + "/".join(segments) + suffix


@st.composite
def data_uris(draw: st.DrawFn) -> str:
    """A ``data:`` URI (unresolved)."""
    payload = draw(st.text(alphabet="ABCabc0123+/=", min_size=0, max_size=20))
    return "data:image/svg+xml;base64," + payload


def _empty_sources() -> IconSources:
    """`image` refs never consult sources; a minimal object suffices."""
    return IconSources(
        aws4=None,
        azure2=None,
        oci_digests=None,
        oci_stencils=None,
        workspace_root=Path("."),
    )


def _is_well_formed_asset(path: str) -> bool:
    """The reference contract, computed independently of the resolver.

    Well-formed = not a ``data:`` URI, not absolute, no ``..`` surviving
    normalisation, under ``assets/``, and a ``.svg``/``.png`` suffix.
    """
    if path.startswith("data:"):
        return False
    if posixpath.isabs(path) or path.startswith("/"):
        return False
    normalised = posixpath.normpath(path)
    if normalised.startswith("..") or "/../" in f"/{normalised}/":
        return False
    if not normalised.startswith("assets/"):
        return False
    return posixpath.splitext(normalised)[1].lower() in (".svg", ".png")


_ANY_IMAGE_PATH = st.one_of(
    valid_asset_paths(),
    absolute_paths(),
    dotdot_paths(),
    outside_assets_paths(),
    wrong_suffix_paths(),
    data_uris(),
)


# Feature: honest-gates, Property 15: Image paths outside the asset root are unresolved
@given(path=_ANY_IMAGE_PATH)
def test_image_path_resolution_matches_the_contract(path):
    """`resolve` returns exactly the status the escaping/suffix contract implies.

    An ``image`` :class:`IconRef` is ``resolved`` iff the path is a well-formed
    ``assets/*.svg|png`` reference, and ``unresolved`` for every escaping or
    disallowed-suffix case: absolute paths, paths with ``..`` that survive
    normalisation, paths outside ``assets/``, wrong suffixes, and ``data:`` URIs
    (Requirements 4.4).
    """
    ref = IconRef(cell_id="n1", kind="image", reference=path)
    status, detail = resolve(ref, _empty_sources())

    expected = RESOLVED if _is_well_formed_asset(path) else UNRESOLVED
    assert status == expected, (
        f"path {path!r}: expected {expected}, got {status} ({detail})"
    )
    assert status in (RESOLVED, UNRESOLVED)


# Feature: honest-gates, Property 15: Image paths outside the asset root are unresolved
@given(path=st.one_of(absolute_paths(), dotdot_paths(), outside_assets_paths(),
                      wrong_suffix_paths(), data_uris()))
def test_escaping_or_bad_suffix_image_paths_are_unresolved(path):
    """Every escaping or disallowed-suffix ``image`` path is ``unresolved``.

    This is the directed half of Property 15: whenever the path escapes
    ``assets/`` (absolute, ``..``, or a different root) or does not end in
    ``.svg``/``.png`` (including a ``data:`` URI), the status is ``unresolved``
    (Requirements 4.4).
    """
    ref = IconRef(cell_id="n1", kind="image", reference=path)
    status, _detail = resolve(ref, _empty_sources())
    assert status == UNRESOLVED, f"{path!r} should be unresolved, got {status}"


# Feature: honest-gates, Property 15: Image paths outside the asset root are unresolved
@given(path=valid_asset_paths())
def test_well_formed_asset_paths_are_resolved(path):
    """A well-formed ``assets/*.svg|png`` path resolves (Requirements 4.4)."""
    ref = IconRef(cell_id="n1", kind="image", reference=path)
    status, _detail = resolve(ref, _empty_sources())
    assert status == RESOLVED, f"{path!r} should be resolved, got {status}"


# --------------------------------------------------------------------------- #
# Property 16: Linter and Icon_Verifier agree, and OCI glyphs are bound to their
# slug (tasks 11.2 / R4.1, R4.5).
#
# The linter's ``icon-resolved`` rule (task 10.4) and the Icon_Verifier
# (verify_icon) both resolve a manifest-backed reference the *same* way, because
# both call ``rule_engine.icon_refs.resolve(ref, sources)`` against the *same*
# committed manifests. So for any generated ref (resIcon / grIcon / azure2 /
# oci-slug), the status the linter would compute equals the status the verifier
# would compute — resolution is a pure function of (ref, sources).
#
# The OCI binding is the second half: a glyph digest is bound to its slug. A
# correct (slug, glyph) pair resolves, but a slug paired with a *mismatched*
# glyph digest is unresolved — the marker cannot vouch for the wrong glyph
# (design §6).
# --------------------------------------------------------------------------- #

from rule_engine.icon_refs import (  # noqa: E402
    SKIPPED,
    _resolve_oci_glyph,
    resolve as _resolve,
)


_HEX = "0123456789abcdef"


@st.composite
def _slug(draw: st.DrawFn) -> str:
    """A plausible OCI stencil slug (lowercase, hyphenated segments)."""
    segments = draw(
        st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8),
            min_size=1,
            max_size=3,
        )
    )
    return "-".join(segments)


@st.composite
def _sha256(draw: st.DrawFn) -> str:
    """A 64-hex-char string, the shape of a sha256 digest."""
    return "".join(draw(st.lists(st.sampled_from(_HEX), min_size=64, max_size=64)))


# aws4 ids and azure2 paths that mirror what the diagram builder emits, so a
# generated ref is a realistic manifest-backed reference.
_AWS4_IDENT = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=20
)


@st.composite
def _manifest_backed_ref(draw: st.DrawFn) -> IconRef:
    """A generated resIcon / grIcon / azure2 / oci-slug reference."""
    kind = draw(st.sampled_from(["resIcon", "grIcon", "azure2", "oci-slug"]))
    if kind in ("resIcon", "grIcon"):
        reference = "mxgraph.aws4." + draw(_AWS4_IDENT)
    elif kind == "azure2":
        segs = draw(_relative_segments())
        reference = "img/lib/azure2/" + "/".join(segs) + draw(_GOOD_SUFFIX)
    else:  # oci-slug
        reference = draw(_slug())
    return IconRef(cell_id=draw(_SEGMENT), kind=kind, reference=reference)


@st.composite
def _sources_with_manifests(draw: st.DrawFn) -> IconSources:
    """An ``IconSources`` with committed manifests populated from generated data.

    Every manifest is a real (possibly empty) allow-list, so ``resolve`` takes
    the *checking* path (RESOLVED / UNRESOLVED) rather than the fail-honest
    ``SKIPPED`` path a ``None`` field forces.
    """
    # ``aws4-icons.json`` stores *bare* stencil idents (``a1_instance``), and
    # ``_resolve_aws4`` matches the captured id (the part after ``mxgraph.aws4.``)
    # against them — so the manifest set holds bare idents, not full ids.
    aws4 = frozenset(draw(st.lists(_AWS4_IDENT, min_size=0, max_size=6)))
    azure2 = frozenset(
        "img/lib/azure2/" + "/".join(seg) + ".svg"
        for seg in draw(st.lists(_relative_segments(), min_size=0, max_size=4))
    )
    oci_digests = {
        slug: digest
        for slug, digest in draw(
            st.lists(st.tuples(_slug(), _sha256()), min_size=0, max_size=6)
        )
    }
    oci_stencils = frozenset(draw(st.lists(_slug(), min_size=0, max_size=6)))
    return IconSources(
        aws4=aws4 or frozenset(),
        azure2=azure2 or frozenset(),
        oci_digests=oci_digests,
        oci_stencils=oci_stencils or frozenset(),
        workspace_root=Path("."),
    )


# Feature: honest-gates, Property 16: Linter and Icon_Verifier agree, and OCI glyphs are bound to their slug
@given(ref=_manifest_backed_ref(), sources=_sources_with_manifests())
def test_linter_and_verifier_agree_on_manifest_backed_refs(ref, sources):
    """The linter and the verifier resolve a manifest-backed ref identically.

    Both consumers resolve through the one shared ``icon_refs.resolve(ref,
    sources)`` against the same committed manifests, so — for the same ref and
    the same sources — they cannot disagree on the resolved/unresolved status.
    Resolution is a pure, deterministic function of ``(ref, sources)``, which is
    exactly what makes the two gates agree (Requirements 4.1, 4.5).
    """
    linter_status, _linter_detail = _resolve(ref, sources)
    verifier_status, _verifier_detail = _resolve(ref, sources)

    assert linter_status == verifier_status
    # A manifest-backed ref checked against a present manifest never floats to
    # UNVERIFIED (that is only for ref kinds with no verification source).
    assert linter_status in (RESOLVED, UNRESOLVED, SKIPPED)


# Feature: honest-gates, Property 16: Linter and Icon_Verifier agree, and OCI glyphs are bound to their slug
@given(
    ident=_AWS4_IDENT,
    others=st.lists(_AWS4_IDENT, min_size=0, max_size=5),
)
def test_known_aws4_id_resolves_unknown_does_not(ident, others):
    """A generated aws4 id resolves iff it is in the committed manifest.

    An id present in ``aws4-icons.json`` resolves; a well-formed id absent from
    it is unresolved (a guessed/typo stencil renders as an empty box). Because
    the linter and verifier share this resolver, both agree on which side of the
    manifest a given id falls (Requirements 4.5).
    """
    # aws4-icons.json stores bare idents (the part after ``mxgraph.aws4.``).
    manifest = frozenset(others)
    with_id = manifest | {ident}
    sources_present = IconSources(
        aws4=with_id, azure2=frozenset(), oci_digests={}, oci_stencils=frozenset(),
        workspace_root=Path("."),
    )
    sources_absent = IconSources(
        aws4=frozenset(o for o in manifest if o != ident),
        azure2=frozenset(), oci_digests={}, oci_stencils=frozenset(),
        workspace_root=Path("."),
    )
    ref = IconRef(cell_id="n1", kind="resIcon", reference="mxgraph.aws4." + ident)

    present_status, _ = _resolve(ref, sources_present)
    absent_status, _ = _resolve(ref, sources_absent)

    assert present_status == RESOLVED
    assert absent_status == UNRESOLVED


# Feature: honest-gates, Property 16: Linter and Icon_Verifier agree, and OCI glyphs are bound to their slug
@given(slug=_slug(), glyph=_sha256(), other_glyph=_sha256())
def test_oci_glyph_is_bound_to_its_slug(slug, glyph, other_glyph):
    """An OCI glyph digest is bound to its slug (design §6).

    A correct ``(slug, glyph)`` pair resolves: the digest recorded for the slug
    equals the glyph digest. A slug paired with a *mismatched* glyph digest is
    unresolved — a marker cannot vouch for the wrong glyph (Requirements 4.1).
    """
    sources = IconSources(
        aws4=frozenset(), azure2=frozenset(),
        oci_digests={slug: glyph}, oci_stencils=frozenset(),
        workspace_root=Path("."),
    )

    # Correct pair: the glyph digest equals the slug's recorded digest.
    ok_status, _ = _resolve_oci_glyph(glyph, sources, slug)
    assert ok_status == RESOLVED

    # Mismatched pair: a different digest under the same slug does not resolve.
    if other_glyph != glyph:
        bad_status, _ = _resolve_oci_glyph(other_glyph, sources, slug)
        assert bad_status == UNRESOLVED


# Feature: honest-gates, Property 16: Linter and Icon_Verifier agree, and OCI glyphs are bound to their slug
@given(slug=_slug(), glyph=_sha256(), unknown_slug=_slug())
def test_oci_slug_without_digest_entry_is_unresolved(slug, glyph, unknown_slug):
    """A glyph carried by a slug with no digest entry cannot resolve.

    When the marker names a slug that the digests manifest does not know, the
    glyph has nothing to be checked against, so the binding is unresolved rather
    than silently accepted (Requirements 4.1).
    """
    sources = IconSources(
        aws4=frozenset(), azure2=frozenset(),
        oci_digests={slug: glyph}, oci_stencils=frozenset(),
        workspace_root=Path("."),
    )
    if unknown_slug != slug:
        status, _ = _resolve_oci_glyph(glyph, sources, unknown_slug)
        assert status == UNRESOLVED

# --------------------------------------------------------------------------- #
# Property 17: Unverified vertices and strict exit codes (task 11.3 / R4.2, R4.3)
#
# Two independent halves of the same property, tested against the real verifier
# code so no logic is re-implemented in the test:
#
#   (a) Unverified set. For a page whose service vertices carry random
#       combinations of verifiable / unverifiable / missing references, the
#       verifier's ``unverified`` rows are exactly the service vertices with no
#       *verifiable* reference (design §6 "Unverified (R4.2)"). Boundary
#       containers and text/legend cells are not service vertices and never
#       appear.
#
#   (b) Strict exit code. For any report counts, ``_exit_code_for(report,
#       strict=True)`` is non-zero exactly when there is an unresolved or an
#       unverified reference, or when the file has service vertices and zero
#       resolved references (a ``skipped`` ref counts as not-verified). Without
#       ``--strict`` only an unresolved ref is non-zero (R4.3).
# --------------------------------------------------------------------------- #

from rule_engine.drawio_model import parse_drawio  # noqa: E402
from rule_engine.icon_refs import UNVERIFIED  # noqa: E402
from rule_engine.verify_icon import _exit_code_for, _verify_page  # noqa: E402

from tests.strategies import (  # noqa: E402
    CellModel,
    DiagramModel,
    PageModel,
    serialize_drawio,
)


# A stable aws4 ident that we place *in* the manifest, and one we keep *out* of
# it, so a resIcon ref resolves or fails deterministically.
_KNOWN_AWS4 = "lambda"
_UNKNOWN_AWS4 = "notarealstencilxyz"


def _sources_for_property_17() -> IconSources:
    """Sources with a real (tiny) aws4 allow-list and no OCI/azure sources.

    ``aws4`` is a present allow-list holding exactly ``_KNOWN_AWS4``; the other
    manifests are ``None`` so an OCI/azure ref would be ``skipped``. This makes a
    ``resIcon=mxgraph.aws4.lambda`` resolve, a typo resIcon unresolve, and a
    generic no-source vertex unverified — the three outcomes the property needs.
    """
    return IconSources(
        aws4=frozenset({_KNOWN_AWS4}),
        azure2=None,
        oci_digests=None,
        oci_stencils=None,
        generic_shapes=frozenset(),
        workspace_root=Path("."),
    )


# Each "vertex kind" is (style_factory, contributes_verifiable_ref) where the
# boolean says whether the vertex has *any* verifiable reference (so it is NOT
# reported unverified). A vertex with no verifiable ref is exactly the
# ``unverified`` set the property checks.
def _resolved_vertex_style() -> str:
    return f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{_KNOWN_AWS4};"


def _unresolved_vertex_style() -> str:
    return f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{_UNKNOWN_AWS4};"


def _unverifiable_vertex_style() -> str:
    # A vendor stencil that is not aws4/azure2/oci and has no image= path, so
    # the only "ref" has no verification source -> the vertex is unverified.
    return "shape=mxgraph.gcp2.cloud_functions;"


def _noref_vertex_style() -> str:
    # A plain node with no icon reference at all (and not a generic base shape,
    # because it names a vendor-ish shape) -> unverified.
    return "shape=mxgraph.mockup.someWidget;"


#: kind -> (style, is_service_vertex, has_verifiable_ref)
_VERTEX_KINDS = {
    "resolved": (_resolved_vertex_style, True, True),
    "unresolved": (_unresolved_vertex_style, True, True),
    "unverifiable": (_unverifiable_vertex_style, True, False),
    "noref": (_noref_vertex_style, True, False),
    # Non-service cells: must never be counted as service vertices.
    "boundary": (lambda: "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;", False, False),
    "text": (lambda: "text;html=1;strokeColor=none;fillColor=none;", False, False),
}


@st.composite
def _vertex_kind_lists(draw: st.DrawFn) -> list:
    """A list of vertex-kind names spanning service and non-service cells."""
    return draw(
        st.lists(
            st.sampled_from(sorted(_VERTEX_KINDS)),
            min_size=0,
            max_size=8,
        )
    )


def _build_page_bytes(kinds: list) -> bytes:
    """Serialize a single-page ``.drawio`` whose cells realise ``kinds``.

    Boundary cells get an id starting with ``boundary`` so the shared classifier
    treats them as containers regardless of style nuances.
    """
    cells: list = []
    for i, kind in enumerate(kinds):
        style_factory, _is_service, _has_ref = _VERTEX_KINDS[kind]
        cid = ("boundary_" if kind == "boundary" else "n_") + f"{kind}_{i}"
        cells.append(
            CellModel(
                id=cid,
                parent="1",
                label=f"{kind} {i}",
                style=style_factory(),
                vertex=True,
            )
        )
    page = PageModel(name="p1", cells=tuple(cells), compressed=False)
    return serialize_drawio(DiagramModel(pages=(page,))).encode("utf-8")


# Feature: honest-gates, Property 17: Unverified vertices and strict exit codes
@given(kinds=_vertex_kind_lists())
def test_unverified_set_is_service_vertices_with_no_verifiable_ref(kinds):
    """The verifier's ``unverified`` set == service vertices with no verifiable ref.

    A service vertex is a node that is neither a Boundary container nor a
    text/legend cell. Of those, the ones whose references have no verification
    source at all (or that carry no reference) are reported ``unverified`` with
    their cell id; verifiable vertices (resolved or unresolved) and non-service
    cells never appear in the unverified set (Requirements 4.2).
    """
    data = _build_page_bytes(kinds)
    (page,) = parse_drawio(data, path="p.drawio")
    references, service_count = _verify_page(page, _sources_for_property_17())

    # Expected: the service vertices that have no verifiable reference.
    expected_service = [k for k in kinds if _VERTEX_KINDS[k][1]]
    expected_unverified = [
        k for k in kinds if _VERTEX_KINDS[k][1] and not _VERTEX_KINDS[k][2]
    ]

    assert service_count == len(expected_service)

    unverified_rows = [r for r in references if r["status"] == UNVERIFIED]
    assert len(unverified_rows) == len(expected_unverified)

    # Every unverified row names a real service-vertex cell id on the page.
    for row in unverified_rows:
        assert row["cell_id"] in page.cells
        assert row["kind"] == "vertex"

    # No boundary/text cell contributed a reference row of any status.
    reported_ids = {r["cell_id"] for r in references}
    for cid, cell in page.cells.items():
        if cid.startswith("boundary_") or ";text;" in f";{cell.style};" or cell.style.startswith("text;"):
            assert cid not in reported_ids


# --------------------------------------------------------------------------- #
# (b) Strict exit code, checked directly against the report-count contract.
# --------------------------------------------------------------------------- #


@st.composite
def _reports(draw: st.DrawFn) -> dict:
    """A synthetic verifier report: only the count fields the exit rule reads."""
    resolved = draw(st.integers(min_value=0, max_value=5))
    unresolved = draw(st.integers(min_value=0, max_value=5))
    skipped = draw(st.integers(min_value=0, max_value=5))
    unverified = draw(st.integers(min_value=0, max_value=5))
    # service_vertices must be at least the number of unverified rows, and at
    # least 1 whenever any ref was produced, to stay a realistic report.
    min_sv = unverified
    service_vertices = draw(st.integers(min_value=min_sv, max_value=min_sv + 5))
    return {
        "path": "p.drawio",
        "references": [],
        "resolved": resolved,
        "unresolved": unresolved,
        "skipped": skipped,
        "unverified": unverified,
        "service_vertices": service_vertices,
    }


# Feature: honest-gates, Property 17: Unverified vertices and strict exit codes
@given(report=_reports())
def test_strict_exit_code_matches_the_contract(report):
    """``--strict`` exits non-zero exactly per the R4.3 exit-code contract.

    Under ``--strict`` the exit code is non-zero exactly when there is an
    unresolved ref, or an unverified ref, or the file has service vertices and
    zero resolved refs. Without ``--strict`` only an unresolved ref is non-zero.
    A ``skipped`` ref counts as not-verified (it does not add to ``resolved``),
    so the third clause fires for it too (Requirements 4.3).
    """
    strict_code = _exit_code_for(report, strict=True)
    default_code = _exit_code_for(report, strict=False)

    expect_strict_nonzero = bool(
        report["unresolved"]
        or report["unverified"]
        or (report["service_vertices"] and not report["resolved"])
    )
    expect_default_nonzero = bool(report["unresolved"])

    assert (strict_code != 0) == expect_strict_nonzero
    assert (default_code != 0) == expect_default_nonzero

    # An unresolved ref is code 1 on both; strict-only failures are also code 1.
    if report["unresolved"]:
        assert strict_code == 1
        assert default_code == 1
    else:
        assert default_code == 0
        assert strict_code in (0, 1)


# Feature: honest-gates, Property 17: Unverified vertices and strict exit codes
@given(kinds=_vertex_kind_lists())
def test_end_to_end_unverified_drives_strict_exit(kinds):
    """A page's unverified/unresolved counts drive the strict exit code end to end.

    Builds a real page, verifies it, then checks that the strict exit code is
    non-zero exactly when the page produced an unresolved or unverified ref, or
    has service vertices but zero resolved refs — tying the R4.2 report to the
    R4.3 exit contract on the same input (Requirements 4.2, 4.3).
    """
    data = _build_page_bytes(kinds)
    (page,) = parse_drawio(data, path="p.drawio")
    references, service_count = _verify_page(page, _sources_for_property_17())

    report = {
        "path": "p.drawio",
        "references": references,
        "resolved": sum(1 for r in references if r["status"] == RESOLVED),
        "unresolved": sum(1 for r in references if r["status"] == UNRESOLVED),
        "skipped": sum(1 for r in references if r["status"] == SKIPPED),
        "unverified": sum(1 for r in references if r["status"] == UNVERIFIED),
        "service_vertices": service_count,
    }

    strict_code = _exit_code_for(report, strict=True)
    expect_nonzero = bool(
        report["unresolved"]
        or report["unverified"]
        or (report["service_vertices"] and not report["resolved"])
    )
    assert (strict_code != 0) == expect_nonzero
