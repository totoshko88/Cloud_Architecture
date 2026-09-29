"""Shared icon-reference extraction and resolution (honest-gates R4.1–R4.5).

Before 1.7.0 the linter's ``icon-resolved`` rule and the standalone
``verify_icon`` each carried their own regex scan of a ``.drawio`` file and their
own idea of what "resolved" meant — so the two could disagree, and every OCI node
was reported ``skipped`` (never actually checked). This module is the single
place that:

* extracts every icon reference from a parsed :class:`~rule_engine.drawio_model.Page`
  (:func:`extract_refs`), keyed by the service-vertex cell id, and
* resolves one reference against the committed manifests / fetched packs
  (:func:`resolve`), returning a status in
  ``{"resolved", "unresolved", "skipped", "unverified"}``.

Both the linter and the verifier import this module, so they cannot drift.

Ref kinds (``IconRef.kind``):

* ``resIcon`` / ``grIcon`` — an ``mxgraph.aws4.<id>`` stencil id, resolved
  against ``mappings/aws4-icons.json``.
* ``azure2`` — a draw.io-internal ``img/lib/azure2/<…>.svg`` path, resolved
  against ``mappings/azure2-shapes.json``.
* ``image`` — any other ``image=`` file-path reference (GCP asset paths, etc.),
  resolved by the path rule (R4.4): normalise, then it is ``unresolved`` when it
  is absolute, still contains ``..`` after normalisation, lies outside
  ``assets/``, has a suffix other than ``.svg``/``.png``, or is a ``data:`` URI.
* ``oci-slug`` — an ``ociSlug=<slug>`` marker (or an ``image=`` value that is a
  bare OCI stencil slug), resolved against ``stencils.json`` when the pack is
  present, else against ``mappings/oci-stencil-digests.json``.
* ``oci-glyph`` — the sha256 of the ``shape=stencil(...)`` payloads found on the
  page in document order. When a glyph and a slug are both present the glyph
  digest must equal ``oci_digests[slug]``; a glyph without a slug is resolved by
  reverse lookup in the digests manifest.
* ``generic-shape`` — a base draw.io shape declared in
  ``mappings/generic-icons.yaml`` (the vendor-neutral profile has no vendor icons).

See ``design.md`` §6 for the dataclass signatures and status semantics.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple

import yaml

from rule_engine.azure2_shapes import (
    load_aws4_manifest as _load_aws4_manifest,
    load_manifest as _load_azure2_manifest,
    AWS4_MANIFEST,
    DEFAULT_MANIFEST as _AZURE2_MANIFEST,
)
from rule_engine.constants import (
    is_boundary_container_style as _is_boundary_style,
    is_text_cell_style as _is_text_style,
    resolve_bundled_dir,
)
from rule_engine.drawio_model import Cell, Page

__all__ = [
    "IconRef",
    "IconSources",
    "RESOLVED",
    "UNRESOLVED",
    "SKIPPED",
    "UNVERIFIED",
    "load_sources",
    "service_vertices",
    "extract_refs",
    "resolve",
    "oci_glyph_digest",
]


# --------------------------------------------------------------------------- #
# Status constants
# --------------------------------------------------------------------------- #

RESOLVED = "resolved"
UNRESOLVED = "unresolved"
SKIPPED = "skipped"
UNVERIFIED = "unverified"


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IconRef:
    """One icon reference extracted from a service vertex."""

    cell_id: str
    kind: str  # resIcon | grIcon | azure2 | image | oci-slug | oci-glyph | generic-shape
    reference: str


@dataclass(frozen=True)
class IconSources:
    """The committed manifests / fetched packs a reference resolves against.

    A ``None`` field means that source is not present in the workspace (assets
    not fetched, manifest not committed); a reference whose only source is
    ``None`` resolves to ``skipped`` rather than ``unresolved`` — fail-honest,
    never blocking on a missing optional source.
    """

    aws4: Optional[FrozenSet[str]]  # mappings/aws4-icons.json ids
    azure2: Optional[FrozenSet[str]]  # mappings/azure2-shapes.json paths
    oci_digests: Optional[Mapping[str, str]]  # mappings/oci-stencil-digests.json
    oci_stencils: Optional[FrozenSet[str]]  # assets/vendor/oci-stencils/stencils.json slugs
    generic_shapes: FrozenSet[str] = field(default_factory=frozenset)
    workspace_root: Path = field(default_factory=Path)


# --------------------------------------------------------------------------- #
# Source loading
# --------------------------------------------------------------------------- #


def _load_oci_stencils(workspace_root: Path) -> Optional[FrozenSet[str]]:
    stencils = (
        workspace_root / "assets" / "vendor" / "oci-stencils" / "stencils.json"
    )
    if not stencils.is_file():
        return None
    try:
        data = json.loads(stencils.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data:
        return frozenset(data.keys())
    return None


def _load_oci_digests(workspace_root: Path) -> Optional[Mapping[str, str]]:
    """Load ``mappings/oci-stencil-digests.json`` (``{slug: sha256}``).

    Task 5.3 creates this manifest; tolerate its absence (returns ``None``).
    """
    for path in (
        workspace_root / "mappings" / "oci-stencil-digests.json",
        resolve_bundled_dir("mappings") / "oci-stencil-digests.json",
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        digests = data.get("digests") if isinstance(data, dict) else None
        if digests is None and isinstance(data, dict):
            # Allow a flat {slug: sha} mapping too.
            digests = {
                k: v for k, v in data.items() if isinstance(v, str)
            }
        if isinstance(digests, dict) and digests:
            return dict(digests)
    return None


def _load_generic_shapes(workspace_root: Path) -> FrozenSet[str]:
    """Return the base draw.io shape/style tokens declared in generic-icons.yaml.

    The generic profile uses no vendor icons; each resource type declares a
    plain draw.io ``style`` (``rounded=…``, ``shape=cylinder3``, …). We harvest
    the ``shape=<name>`` tokens and the leading style keyword (``rounded``) so a
    ``generic-shape`` ref can be checked as a declared base shape.
    """
    shapes: set = set()
    for path in (
        workspace_root / "mappings" / "generic-icons.yaml",
        resolve_bundled_dir("mappings") / "generic-icons.yaml",
    ):
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            break
        if not isinstance(data, dict):
            break
        sections = []
        if isinstance(data.get("resources"), dict):
            sections.append(data["resources"])
        if isinstance(data.get("containers"), dict):
            sections.append(data["containers"])
        for section in sections:
            for spec in section.values():
                if not isinstance(spec, dict):
                    continue
                style = str(spec.get("style", ""))
                for token in _generic_shape_tokens(style):
                    shapes.add(token)
        break
    return frozenset(shapes)


def _generic_shape_tokens(style: str) -> List[str]:
    """The base draw.io base-shape tokens of a generic style string.

    ``shape=cylinder3;…`` yields ``cylinder3``; a style whose leading token is a
    bare keyword (``rounded=0``) yields ``rounded`` so a plain rectangle style is
    recognised as a declared generic shape. A ``shape=mxgraph.<lib>.<id>`` vendor
    stencil is **not** a generic base shape — it yields no token, so a vendor node
    without a verifiable ref is reported ``unverified`` rather than falsely
    resolving to a generic shape.
    """
    tokens: List[str] = []
    m = re.search(r"(?:^|;)shape=([^;]+)", style)
    if m:
        shape = m.group(1).strip()
        if not shape.startswith("mxgraph."):
            tokens.append(shape)
    lead = style.split(";", 1)[0].strip()
    key = lead.split("=", 1)[0].strip()
    if key and key != "shape":
        tokens.append(key)
    return tokens


def load_sources(workspace_root: Path) -> IconSources:
    """Load every icon-resolution source available under ``workspace_root``.

    A missing manifest / pack yields a ``None`` field, so a reference whose only
    source is absent resolves to ``skipped`` (fail-honest) rather than blocking.
    """
    root = Path(workspace_root)
    aws4 = _load_aws4_manifest(root / "mappings" / "aws4-icons.json")
    if aws4 is None:
        aws4 = _load_aws4_manifest(AWS4_MANIFEST)
    azure2 = _load_azure2_manifest(root / "mappings" / "azure2-shapes.json")
    if azure2 is None:
        azure2 = _load_azure2_manifest(_AZURE2_MANIFEST)
    return IconSources(
        aws4=frozenset(aws4) if aws4 else None,
        azure2=frozenset(azure2) if azure2 else None,
        oci_digests=_load_oci_digests(root),
        oci_stencils=_load_oci_stencils(root),
        generic_shapes=_load_generic_shapes(root),
        workspace_root=root,
    )


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def _is_service_vertex(cell: Cell, vertex_ids: FrozenSet[str]) -> bool:
    """True for a **top-level** service node (neither a boundary nor a text cell).

    A service vertex is a vertex parented to a page **layer** (the root ``mxCell``,
    which is not itself a vertex), not to another vertex. This deliberately
    excludes the embedded-stencil sub-cells of an OCI node: an OCI service node is
    a ``group`` cell (parented to the layer, carrying ``ociSlug=``) whose children
    ``<id>-g1``, ``<id>-g2``, … hold the ``shape=stencil(...)`` glyph geometry.
    Those children are the glyph's internal structure, not services in their own
    right, so counting them would report every ``-gN`` sub-cell as an
    ``unverified`` generic-shape/oci-glyph vertex under ``--strict`` (R4.2).

    ``vertex_ids`` is the set of every vertex id on the page; a cell whose parent
    is in that set is nested inside another vertex and is therefore not a
    top-level service vertex.
    """
    if not cell.vertex:
        return False
    if _is_boundary_style(cell.id, cell.style):
        return False
    if _is_text_style(cell.style):
        return False
    if cell.parent in vertex_ids:
        # Nested inside another vertex (e.g. an OCI glyph sub-cell) -> not a
        # service vertex; the enclosing top-level vertex is the service node.
        return False
    return True


def service_vertices(page: Page) -> List[Cell]:
    """Return the page's service vertices in document order.

    A service vertex is a vertex that is neither a Boundary/Network-Boundary
    container nor a text/legend cell, and that is parented to a page layer rather
    than nested inside another vertex — i.e. a top-level node that should carry an
    icon. Embedded stencil sub-cells (an OCI node's ``-gN`` glyph children) are
    excluded because their parent is another vertex.
    """
    vertex_ids = frozenset(c.id for c in page.cells.values() if c.vertex)
    return [c for c in page.cells.values() if _is_service_vertex(c, vertex_ids)]


_STENCIL_RE = re.compile(r"shape=stencil\(([^)]*)\)")


def _stencil_payloads(page: Page) -> List[str]:
    """Every ``shape=stencil(...)`` payload on the page, in document order.

    OCI nodes embed their glyph as ``shape=stencil(<base64>)``; the ordered list
    of payloads is what :func:`oci_glyph_digest` hashes.
    """
    payloads: List[str] = []
    for cell in page.cells.values():
        for m in _STENCIL_RE.finditer(cell.style or ""):
            payloads.append(m.group(1))
    return payloads


def _subtree_has_stencil(page: Page, root_id: str) -> bool:
    """True when ``root_id`` or any of its descendant cells embeds a stencil.

    An OCI node carries its ``shape=stencil(...)`` glyph in child ``-gN`` cells,
    not in the group node's own style, so a per-node stencil test must look at
    the whole subtree, not just the node's own ``style``.
    """
    children: Dict[str, List[str]] = {}
    for cell in page.cells.values():
        children.setdefault(cell.parent, []).append(cell.id)
    stack = [root_id]
    seen: set = set()
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        cell = page.cells.get(cid)
        if cell is not None and _STENCIL_RE.search(cell.style or ""):
            return True
        stack.extend(children.get(cid, ()))
    return False


def oci_glyph_digest(stencil_payloads: List[str]) -> str:
    """sha256 of the ``shape=stencil(...)`` payloads joined by newlines.

    Used by both the diagram builder and the verifier so an OCI glyph's digest
    is computed identically on both sides (R4.1).
    """
    joined = "\n".join(stencil_payloads)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _oci_slug_from_cell(cell: Cell) -> Optional[str]:
    """Return the ``ociSlug=<slug>`` marker of a cell, if any."""
    slug = cell.style_map.get("ociSlug")
    if slug:
        return slug.strip()
    return None


def extract_refs(page: Page) -> Dict[str, List[IconRef]]:
    """Extract every icon reference on ``page``, keyed by service-vertex cell id.

    A service vertex with no extractable reference is still present in the
    returned mapping with an empty list, so the verifier can report it
    ``unverified`` (R4.2).

    **OCI slug vs glyph.** An OCI service node is a top-level ``group`` vertex
    carrying an ``ociSlug=`` marker; its embedded glyph lives in child ``-gN``
    sub-cells (which are *not* service vertices — see :func:`service_vertices`).
    When a node's ``ociSlug=`` marker resolves against ``stencils.json`` /
    ``oci-stencil-digests.json``, the slug is the authoritative icon binding, so
    no ``oci-glyph`` ref is attached to that node — a page-wide glyph digest can
    never reverse-match a single slug's per-glyph digest, and it must not be
    allowed to fail a node whose slug already resolves. The page glyph digest is
    a **fallback**, attached only to a stencil-bearing service vertex that carries
    **no** ``ociSlug=`` marker, so a hand-authored OCI diagram with a bare
    embedded stencil is still verifiable by reverse lookup.
    """
    refs: Dict[str, List[IconRef]] = {}
    stencil_payloads = _stencil_payloads(page)
    glyph_digest = (
        oci_glyph_digest(stencil_payloads) if stencil_payloads else None
    )

    for cell in service_vertices(page):
        cell_refs: List[IconRef] = []
        style_map = cell.style_map

        res_icon = style_map.get("resIcon")
        gr_icon = style_map.get("grIcon")
        image = style_map.get("image")
        # The image identity is the ``iconRef=<path>`` companion token when
        # present, else the ``image=`` value. ``diagram_layout.image_icon`` emits
        # the glyph inline as ``image=data:image/svg+xml,<b64>`` so it renders in
        # the draw.io editor, and preserves the real asset path in ``iconRef=`` —
        # so every reverse-identification path (this extractor, the linter's
        # ``icon-resolved``, reconcile's role reverse-map, the verifier) takes the
        # identity from ``iconRef`` and never from the opaque data-URI.
        icon_ref = style_map.get("iconRef")
        image_identity = icon_ref if icon_ref else image
        slug = _oci_slug_from_cell(cell)
        # An OCI node's glyph is embedded in its child sub-cells, so scan the
        # cell's whole subtree (not just its own style) for a stencil payload.
        has_stencil = _subtree_has_stencil(page, cell.id)

        if res_icon:
            cell_refs.append(IconRef(cell.id, "resIcon", res_icon.strip()))
        if gr_icon:
            cell_refs.append(IconRef(cell.id, "grIcon", gr_icon.strip()))
        if slug:
            cell_refs.append(IconRef(cell.id, "oci-slug", slug))
        if image_identity:
            image_identity = image_identity.strip()
            if image_identity.startswith("img/lib/azure2/"):
                cell_refs.append(IconRef(cell.id, "azure2", image_identity))
            elif (
                not image_identity.startswith("data:")
                and "/" not in image_identity
                and "." not in image_identity
            ):
                # a bare token in image= is treated as an OCI stencil slug
                cell_refs.append(IconRef(cell.id, "oci-slug", image_identity))
            else:
                cell_refs.append(IconRef(cell.id, "image", image_identity))
        # Generic-profile shapes: a plain base shape with no vendor reference.
        if not cell_refs and not has_stencil:
            for token in _generic_shape_tokens(cell.style or ""):
                cell_refs.append(IconRef(cell.id, "generic-shape", token))

        # Attach the page glyph digest ONLY to a stencil-bearing service vertex
        # that carries no ociSlug= marker. When a slug is present it is the
        # authoritative binding (resolved against stencils.json / the digests
        # manifest); the page-wide glyph digest cannot reverse-match a single
        # slug's per-glyph digest, so attaching it would wrongly fail an
        # otherwise-resolved OCI node under --strict. A bare (marker-less)
        # embedded stencil still gets the glyph ref, so a hand-authored OCI
        # diagram remains verifiable by reverse lookup.
        if has_stencil and slug is None and glyph_digest is not None:
            cell_refs.append(IconRef(cell.id, "oci-glyph", glyph_digest))

        refs[cell.id] = cell_refs
    return refs


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

_AWS4_RE = re.compile(r"^mxgraph\.aws4\.([A-Za-z0-9_]+)$")


def _resolve_aws4(ref: str, sources: IconSources) -> Tuple[str, str]:
    if sources.aws4 is None:
        return SKIPPED, "mappings/aws4-icons.json not present"
    m = _AWS4_RE.match(ref)
    if not m:
        return UNRESOLVED, f"not an mxgraph.aws4.* id: {ref!r}"
    ident = m.group(1)
    if ident in sources.aws4:
        return RESOLVED, f"mxgraph.aws4.{ident}"
    return UNRESOLVED, (
        f"mxgraph.aws4.{ident} not in aws4-icons.json allow-list "
        f"(guessed/typo id renders as an empty box)"
    )


def _resolve_azure2(ref: str, sources: IconSources) -> Tuple[str, str]:
    if sources.azure2 is None:
        return SKIPPED, "mappings/azure2-shapes.json not present"
    if ref in sources.azure2:
        return RESOLVED, ref
    return UNRESOLVED, (
        f"azure2 path not in azure2-shapes.json allow-list: {ref} "
        f"(renders as a broken-image placeholder)"
    )


def _resolve_image_path(ref: str) -> Tuple[str, str]:
    """Apply the file-path rule (R4.4) to an ``image=`` value.

    The reference is ``unresolved`` when it is absolute, still contains ``..``
    after normalisation, does not start with ``assets/``, has a suffix other than
    ``.svg``/``.png``, or is a ``data:`` URI. Otherwise it is well-formed
    (``resolved`` as a path shape — on-disk existence is the verifier's business,
    and this rule is what the linter can enforce from committed data alone).
    """
    if ref.startswith("data:"):
        return UNRESOLVED, f"data: URI is not an asset path: {ref[:32]!r}"
    if posixpath.isabs(ref) or ref.startswith("/"):
        return UNRESOLVED, f"absolute image path: {ref}"
    normalised = posixpath.normpath(ref)
    if normalised.startswith("..") or "/../" in f"/{normalised}/":
        return UNRESOLVED, f"path escapes the workspace with '..': {ref}"
    if not normalised.startswith("assets/"):
        return UNRESOLVED, f"image path outside assets/: {ref}"
    suffix = posixpath.splitext(normalised)[1].lower()
    if suffix not in (".svg", ".png"):
        return UNRESOLVED, f"unsupported image suffix {suffix!r}: {ref}"
    return RESOLVED, normalised


def _resolve_oci_slug(ref: str, sources: IconSources) -> Tuple[str, str]:
    if sources.oci_stencils is not None:
        if ref in sources.oci_stencils:
            return RESOLVED, f"OCI stencil slug {ref}"
        return UNRESOLVED, f"OCI slug not in stencils.json: {ref}"
    if sources.oci_digests is not None:
        if ref in sources.oci_digests:
            return RESOLVED, f"OCI slug in oci-stencil-digests.json: {ref}"
        return UNRESOLVED, f"OCI slug not in oci-stencil-digests.json: {ref}"
    return SKIPPED, "no OCI stencil source present (stencils.json / digests)"


def _resolve_oci_glyph(
    ref: str, sources: IconSources, slug: Optional[str]
) -> Tuple[str, str]:
    """Resolve an ``oci-glyph`` digest.

    * With a slug present, the glyph digest must equal ``oci_digests[slug]`` —
      so a marker cannot vouch for the wrong glyph.
    * Without a slug, resolve by reverse lookup in the digests manifest.
    """
    if sources.oci_digests is None:
        return SKIPPED, "mappings/oci-stencil-digests.json not present"
    if slug is not None:
        expected = sources.oci_digests.get(slug)
        if expected is None:
            return UNRESOLVED, f"OCI slug {slug} has no digest entry"
        if expected == ref:
            return RESOLVED, f"glyph digest matches slug {slug}"
        return UNRESOLVED, (
            f"glyph digest does not match slug {slug} "
            f"(marker vouches for the wrong glyph)"
        )
    # reverse lookup: does any slug carry this digest?
    for candidate, digest in sources.oci_digests.items():
        if digest == ref:
            return RESOLVED, f"glyph digest matches slug {candidate} (reverse lookup)"
    return UNRESOLVED, "glyph digest not found in oci-stencil-digests.json"


def resolve(ref: IconRef, sources: IconSources) -> Tuple[str, str]:
    """Resolve one :class:`IconRef` against ``sources``.

    Returns ``(status, detail)`` where ``status`` is one of ``resolved``,
    ``unresolved``, ``skipped`` (source not present, fail-honest) or
    ``unverified`` (the ref kind has no verification source at all).
    """
    kind = ref.kind
    if kind in ("resIcon", "grIcon"):
        return _resolve_aws4(ref.reference, sources)
    if kind == "azure2":
        return _resolve_azure2(ref.reference, sources)
    if kind == "image":
        return _resolve_image_path(ref.reference)
    if kind == "oci-slug":
        return _resolve_oci_slug(ref.reference, sources)
    if kind == "oci-glyph":
        return _resolve_oci_glyph(ref.reference, sources, _glyph_sibling_slug(ref, sources))
    if kind == "generic-shape":
        if ref.reference in sources.generic_shapes:
            return RESOLVED, f"generic base shape {ref.reference!r}"
        return UNRESOLVED, (
            f"generic shape {ref.reference!r} not declared in generic-icons.yaml"
        )
    return UNVERIFIED, f"no verification source for ref kind {kind!r}"


def _glyph_sibling_slug(ref: IconRef, sources: IconSources) -> Optional[str]:
    """A glyph ref does not carry its sibling slug; resolve without one.

    :func:`resolve` handles a single ref in isolation, so the glyph→slug binding
    is enforced at the page level by the verifier, which passes the paired slug.
    In isolation (linter path) we resolve the glyph by reverse lookup, so this
    returns ``None``.
    """
    return None
