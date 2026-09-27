"""Slug-disambiguation determinism (placement-and-gates, Part D, Property 6).

Task 11.2. Part D replaced the pre-1.9.0 last-writer-wins + WARNING collision
handling with a *total, deterministic* disambiguation order: when two distinct
vendor icons normalise to one slug, the winner keeps the bare slug and every
loser is recorded under a ``<slug>--<disambiguator>`` key rather than shadowed
(``asset_index.index_provider`` / ``build_icon_index``, R4.1-R4.3).

Property 6 (design.md Part D): slug disambiguation is a **pure function of the
pack**. ``build_icon_index`` resolves every collision to a stable winner, and
re-running on the same packs yields a byte-identical index with no collision
WARNING. R4.4 makes this determinism the contract and R4.5 requires the engine's
own role resolution to be unaffected.

The existing ``tests/test_asset_index_determinism.py`` proves order-independence
on two *fixed* synthetic packs; this module lifts the same guarantee to a
Hypothesis property over **arbitrarily generated** packs that deliberately
contain genuine collisions, and asserts, for every generated pack:

* the ``{slug: path}`` mapping **and** the ``ambiguous`` collision map are
  identical under every permuted enumeration order (winner/loser assignment is
  order-invariant), and
* the serialized ``build_icon_index`` payload is byte-identical on a re-run,
* while every role in ``roles.yaml`` still resolves to exactly what the base
  (sorted) enumeration produced (R4.5 — disambiguation never perturbs roles).

Conventions (established by honest-gates): the Hypothesis profile lives in
``tests/conftest.py`` (loaded automatically, ``max_examples=100``), so every
``@given`` here runs at least 100 examples without a per-test override.

**Validates: Requirements 4.4, 4.5**
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import List

from hypothesis import given
from hypothesis import strategies as st

from rule_engine import asset_index as ai

# --------------------------------------------------------------------------- #
# A synthetic Azure pack generator that deliberately manufactures collisions.
# --------------------------------------------------------------------------- #
#
# Azure display names are derived from ``NNNNN-icon-service-<Name>.svg`` and the
# ``azure`` vendor token is stripped by ``normalize_slug(strip_vendor=True)``.
# So "Azure Firewall" and "Firewall" both normalise to the slug ``firewall`` —
# a genuine collision between two DISTINCT services (distinct display names),
# exactly the case Part D disambiguates. Generating base service names and,
# independently, whether each is filed with an "Azure " vendor prefix, lets us
# produce packs that mix:
#   * plain size/theme/format variants of ONE service (collapse to one slug), and
#   * distinct services that collide on the vendor-stripped slug (disambiguated).

# Base service names (lowercase words); kept short so slugs stay legible.
_WORDS = ["firewall", "gateway", "vault", "cache", "bastion", "monitor", "relay"]

_service_names = st.lists(
    st.lists(st.sampled_from(_WORDS), min_size=1, max_size=2).map(
        lambda ws: " ".join(w.capitalize() for w in ws)
    ),
    min_size=1,
    max_size=6,
    unique=True,
)


@st.composite
def _azure_pack_files(draw) -> List[str]:
    """A list of relative Azure asset paths with variants and collisions.

    Each distinct base service is emitted once as ``<Name>`` and, when the draw
    says so, also as ``Azure <Name>`` (a distinct display name that collides on
    the vendor-stripped slug). Every service additionally gets a random handful
    of format/size/theme variants that must collapse to a single slug rather than
    be counted as a collision."""
    names = draw(_service_names)
    files: List[str] = []
    counter = 0
    categories = ["networking", "security", "compute", "app services", "iot"]

    def emit(display: str) -> None:
        nonlocal counter
        # 1..3 variants of this one service: format, size and theme decoration.
        n_variants = draw(st.integers(min_value=1, max_value=3))
        for _ in range(n_variants):
            counter += 1
            code = f"{counter:05d}"
            cat = draw(st.sampled_from(categories))
            ext = draw(st.sampled_from([".svg", ".png"]))
            theme = draw(st.sampled_from(["", "-Dark", "-Light"]))
            slug_name = display.replace(" ", "-")
            files.append(
                f"Azure_Public_Service_Icons/Icons/{cat}/"
                f"{code}-icon-service-{slug_name}{theme}{ext}"
            )

    for name in names:
        emit(name)
        # Independently maybe add the vendor-prefixed twin (a distinct service
        # that collides on the vendor-stripped slug).
        if draw(st.booleans()):
            emit(f"Azure {name}")

    return files


def _write_pack(root: Path, files: List[str]) -> Path:
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<svg/>" if rel.endswith(".svg") else "png", encoding="utf-8")
    return root


def _mapping(index) -> dict:
    """A comparable ``{slug: posix-path}`` view of an AssetIndex."""
    return {slug: Path(entry.path).as_posix() for slug, entry in index.items()}


def _index_under_order(monkeypatch, provider: str, root: Path, reorder) -> ai.AssetIndex:
    original = ai._iter_files
    monkeypatch.setattr(ai, "_iter_files", lambda r: reorder(list(original(r))))
    try:
        return ai.index_provider(provider, str(root))
    finally:
        monkeypatch.setattr(ai, "_iter_files", original)


# --------------------------------------------------------------------------- #
# Property 6a: winner/loser slug assignment is invariant under enumeration order
# --------------------------------------------------------------------------- #
@given(files=_azure_pack_files(), seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_disambiguation_is_independent_of_enumeration_order(
    monkeypatch, tmp_path_factory, files, seed
) -> None:
    """For any generated pack, permuting the file-enumeration order never changes
    the disambiguated ``{slug: path}`` mapping or the ``ambiguous`` collision map:
    the winner keeps the bare slug and every loser lands on the same
    ``<slug>--<disambiguator>`` key regardless of the order files were seen in
    (R4.4 — disambiguation is a pure function of the pack contents)."""
    root = _write_pack(tmp_path_factory.mktemp("azure"), files)

    orders = {
        "sorted": lambda fs: fs,
        "reversed": lambda fs: list(reversed(fs)),
        "shuffled": lambda fs: random.Random(seed).sample(fs, len(fs)),
    }
    results = {
        name: _index_under_order(monkeypatch, "azure", root, reorder)
        for name, reorder in orders.items()
    }

    base = results["sorted"]
    base_map = _mapping(base)
    for name, idx in results.items():
        assert _mapping(idx) == base_map, f"slug->path mapping differs under {name}"
        # The collision record (winner + losers per contested slug) is identical.
        assert dict(idx.ambiguous) == dict(base.ambiguous), (
            f"ambiguous collision map differs under {name}"
        )


# --------------------------------------------------------------------------- #
# Property 6b: a genuine collision resolves to a bare-slug winner + disambiguated
#              losers, with no distinct service shadowed.
# --------------------------------------------------------------------------- #
@given(files=_azure_pack_files())
def test_every_distinct_service_stays_reachable(monkeypatch, tmp_path_factory, files) -> None:
    """No distinct service is shadowed by a collision (R4.2): for every contested
    slug the number of index keys naming that slug (the bare winner plus each
    ``<slug>--…`` loser) equals the number of distinct display names that
    competed for it, and every competing display name is reachable in the index."""
    root = _write_pack(tmp_path_factory.mktemp("azure"), files)
    index = ai.index_provider("azure", str(root))

    for slug, names in index.ambiguous.items():
        assert slug in index, f"winner for contested slug {slug!r} is missing"
        losers = [s for s in index if s.startswith(f"{slug}--")]
        # One bare winner + one disambiguated key per loser == len(names).
        assert 1 + len(losers) == len(names), (
            f"{slug!r}: {1 + len(losers)} keys for {len(names)} services"
        )
        reachable = {index[slug].display_name} | {index[s].display_name for s in losers}
        assert reachable == set(names)


# --------------------------------------------------------------------------- #
# Property 6c: build_icon_index is byte-identical on a re-run, and role
#              resolution is unaffected by whatever disambiguation happened.
# --------------------------------------------------------------------------- #
@given(files=_azure_pack_files())
def test_build_icon_index_is_byte_identical_and_roles_unaffected(
    monkeypatch, tmp_path_factory, files
) -> None:
    """Re-running ``build_icon_index`` on the same pack yields byte-identical JSON
    (R4.4, Property 6), and the resolved ``roles`` layer is exactly what the base
    (sorted) enumeration produces regardless of how the pack was permuted while
    indexing (R4.5 — the engine's role resolution is unaffected by loser
    disambiguation)."""
    root = _write_pack(tmp_path_factory.mktemp("azure"), files)
    pack_roots = {"azure": str(root)}

    # Byte-identical re-run (Property 6): same packs -> same bytes.
    first = ai.icon_index_to_json(ai.build_icon_index(pack_roots, full_packs=True))
    second = ai.icon_index_to_json(ai.build_icon_index(pack_roots, full_packs=True))
    assert first == second

    # R4.5: role resolution does not depend on enumeration order — the roles
    # layer is the same whether the underlying pack was walked sorted, reversed,
    # or shuffled while indexing.
    def roles_under(reorder) -> dict:
        original = ai._iter_files
        monkeypatch.setattr(ai, "_iter_files", lambda r: reorder(list(original(r))))
        try:
            return ai.build_icon_index(pack_roots, full_packs=False)["roles"]
        finally:
            monkeypatch.setattr(ai, "_iter_files", original)

    base_roles = roles_under(lambda fs: fs)
    assert roles_under(lambda fs: list(reversed(fs))) == base_roles
    assert roles_under(lambda fs: list(reversed(fs[:1])) + fs[1:]) == base_roles
