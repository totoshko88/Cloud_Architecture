"""Property tests for the pinned, HTTPS-only asset Fetcher.

Feature: honest-gates (release 1.7.0), task 14.2 — Property 23.

The Fetcher (``rule_engine.fetch_assets``) may only unpack bytes that were
delivered over HTTPS (including at every redirect step) *and* whose ``sha256``
and byte ``size`` match the provider's declared Pack_Pin (R6.1, R6.2). It
downloads atomically into a digest-keyed cache and unpacks into a fresh
directory (R6.3). This module drives that contract with an **injectable fake
opener** that serves arbitrary bytes from an in-test fixture, so no network and
no real vendor pack is touched.

The fake opener models a redirect chain: it runs the *production*
``_HTTPSOnlyRedirectHandler.redirect_request`` over the chain, so a non-HTTPS
hop is refused by the real code path rather than by test-only logic. Only the
final HTTPS response streams the fixture bytes.
"""

from __future__ import annotations

import hashlib
import io
import urllib.request

import pytest
from pathlib import Path
from typing import List, Optional, Sequence

from hypothesis import given
from hypothesis import strategies as st

from rule_engine import fetch_assets
from rule_engine.fetch_assets import (
    InsecureURLError,
    PackPinError,
    _download_verified,
    _https_opener,
    fetch_provider,
)
from tests.strategies import fs_settings


# --------------------------------------------------------------------------- #
# A network-free fake opener that serves fixture bytes over a redirect chain.
# --------------------------------------------------------------------------- #


class _FakeResponse(io.BytesIO):
    """A minimal urllib-response stand-in: a readable, closable stream."""

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class _FakeOpener:
    """An opener that serves ``payload`` after walking a redirect ``chain``.

    ``chain`` is the ordered list of URLs the request visits, starting with the
    initial URL. Every hop after the first is validated with the *real*
    ``_HTTPSOnlyRedirectHandler.redirect_request`` (which raises
    :class:`InsecureURLError` on a non-HTTPS ``Location``), so the production
    redirect-refusal path is exercised without any network. The final URL's
    response streams ``payload``.
    """

    def __init__(self, payload: bytes, chain: Sequence[str]) -> None:
        self.payload = payload
        self.chain = list(chain)
        self._redirect_handler = fetch_assets._HTTPSOnlyRedirectHandler()

    def open(self, req, timeout: Optional[float] = None):  # noqa: A003
        # Walk each redirect hop through the production handler. A non-HTTPS
        # Location raises InsecureURLError exactly as the real opener would.
        for newurl in self.chain[1:]:
            self._redirect_handler.redirect_request(
                req, io.BytesIO(b""), 302, "Found", {}, newurl
            )
        return _FakeResponse(self.payload)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_zips(cache_dir: Path) -> List[Path]:
    """Cache files named after a 64-hex digest (the only landed-pack shape)."""
    if not cache_dir.exists():
        return []
    out: List[Path] = []
    for p in cache_dir.iterdir():
        if p.is_file() and p.suffix == ".zip" and len(p.stem) == 64:
            try:
                int(p.stem, 16)
            except ValueError:
                continue
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #

# A tiny, deterministic zip archive built from a payload; unpacking it must
# yield exactly one file, so a successful fetch has an observable result.
def _zip_bytes(inner: bytes) -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("icon.svg", inner)
    return buf.getvalue()


_payload_inner = st.binary(min_size=0, max_size=64)

#: A non-HTTPS scheme for the insecure-URL cases.
_insecure_schemes = st.sampled_from(["http", "ftp", "file"])


@st.composite
def _scenario(draw: st.DrawFn):
    """Generate (payload, pin, chain, expect) for one fetch attempt.

    ``expect`` is one of:
      * ``"ok"``       — HTTPS chain, pin matches the payload -> unpacks;
      * ``"mismatch"`` — HTTPS chain, pin does NOT match -> PackPinError;
      * ``"insecure"`` — a non-HTTPS hop somewhere in the chain -> InsecureURLError.
    """
    payload = _zip_bytes(draw(_payload_inner))
    real_sha = _sha256(payload)
    real_size = len(payload)

    kind = draw(st.sampled_from(["ok", "mismatch", "insecure"]))

    # Build the redirect chain. For "insecure" we inject a non-HTTPS URL either
    # as the initial URL or as an intermediate/final redirect hop.
    n_redirects = draw(st.integers(min_value=0, max_value=3))
    chain = ["https://example.test/pack.zip"]
    for i in range(n_redirects):
        chain.append(f"https://cdn{i}.example.test/pack-{i}.zip")

    if kind == "insecure":
        bad = draw(_insecure_schemes) + "://evil.example.test/pack.zip"
        pos = draw(st.integers(min_value=0, max_value=len(chain) - 1))
        chain[pos] = bad

    # Build the pin. For "ok" it matches; for "mismatch" the sha and/or size is
    # perturbed so verification must fail.
    if kind == "mismatch":
        break_sha = draw(st.booleans())
        break_size = draw(st.booleans())
        if not break_sha and not break_size:
            break_sha = True  # ensure at least one field is wrong
        pin_sha = real_sha
        pin_size = real_size
        if break_sha:
            # Flip the first hex nibble to a different value.
            other = "0" if real_sha[0] != "0" else "1"
            pin_sha = other + real_sha[1:]
        if break_size:
            pin_size = real_size + draw(st.integers(min_value=1, max_value=9))
        pin = {"sha256": pin_sha, "size": pin_size}
    else:
        pin = {"sha256": real_sha, "size": real_size}

    return payload, pin, chain, kind


# --------------------------------------------------------------------------- #
# Property 23
# --------------------------------------------------------------------------- #


# Feature: honest-gates, Property 23: Only pinned bytes over HTTPS are unpacked
@fs_settings
@given(scenario=_scenario())
def test_only_pinned_bytes_over_https_are_unpacked(scenario, tmp_path_factory):
    """The Fetcher unpacks iff the whole chain is HTTPS and the pin matches.

    On any other outcome (a pin mismatch, or a non-HTTPS hop) it raises the
    matching error and leaves no digest-named cache file and no unpacked
    directory behind (R6.1, R6.2, R6.3).
    """
    payload, pin, chain, expect = scenario
    root = tmp_path_factory.mktemp("fetch")
    asset_root = root / "assets"
    cache_dir = root / "cache"
    out_dir = asset_root / "prov-icons"

    spec = {
        "url": chain[0],
        "sha256": pin["sha256"],
        "size": pin["size"],
        "unpack_to": "prov-icons",
    }
    opener = _FakeOpener(payload, chain)

    if expect == "ok":
        result = fetch_provider(
            "prov", spec, asset_root, cache_dir, opener=opener
        )
        # (a) matching pinned bytes over https land at <sha256>.zip and unpack.
        landed = _digest_zips(cache_dir)
        assert len(landed) == 1
        assert landed[0].name == f"{_sha256(payload)}.zip"
        assert out_dir.is_dir()
        assert (out_dir / "icon.svg").is_file()
        assert result["files"] == 1
        return

    if expect == "mismatch":
        # (b) a digest/size mismatch raises PackPinError, nothing is unpacked.
        try:
            fetch_provider("prov", spec, asset_root, cache_dir, opener=opener)
        except PackPinError:
            pass
        else:
            raise AssertionError("expected PackPinError on a pin mismatch")
        assert _digest_zips(cache_dir) == []
        assert not out_dir.exists()
        return

    # expect == "insecure":
    # (c) a non-HTTPS URL (or a redirect to one) raises InsecureURLError.
    try:
        fetch_provider("prov", spec, asset_root, cache_dir, opener=opener)
    except InsecureURLError:
        pass
    else:
        raise AssertionError("expected InsecureURLError on a non-HTTPS hop")
    assert _digest_zips(cache_dir) == []
    assert not out_dir.exists()


# --------------------------------------------------------------------------- #
# The "no pin" refusal (R6.1) — an example-based leg of the same property.
# --------------------------------------------------------------------------- #


def test_provider_without_a_pin_is_refused_referencing_update_pins(tmp_path):
    """(d) A provider with no Pack_Pin is refused, pointing at --update-pins."""
    asset_root = tmp_path / "assets"
    cache_dir = tmp_path / "cache"
    out_dir = asset_root / "prov-icons"

    # An HTTPS URL but empty pin fields (the placeholder shape in
    # mappings/asset-sources.yaml before `--update-pins` runs).
    spec = {
        "url": "https://example.test/pack.zip",
        "sha256": "",
        "size": "",
        "unpack_to": "prov-icons",
    }
    opener = _FakeOpener(_zip_bytes(b"x"), ["https://example.test/pack.zip"])

    try:
        fetch_provider("prov", spec, asset_root, cache_dir, opener=opener)
    except PackPinError as exc:
        assert "--update-pins" in str(exc)
    else:
        raise AssertionError("expected PackPinError for a provider with no pin")

    assert _digest_zips(cache_dir) == []
    assert not out_dir.exists()


# --------------------------------------------------------------------------- #
# The real _https_opener refuses a non-HTTPS redirect (unit anchor for R6.2).
# --------------------------------------------------------------------------- #


def test_https_opener_redirect_handler_refuses_non_https_location():
    """The production redirect handler raises on a non-HTTPS ``Location``."""
    opener = _https_opener()
    handler = None
    for h in opener.handlers:
        if isinstance(h, fetch_assets._HTTPSOnlyRedirectHandler):
            handler = h
            break
    assert handler is not None, "opener is missing the HTTPS-only redirect handler"

    req = urllib.request.Request("https://example.test/a.zip")
    try:
        handler.redirect_request(
            req, io.BytesIO(b""), 302, "Found", {}, "http://evil.test/a.zip"
        )
    except InsecureURLError:
        pass
    else:
        raise AssertionError("expected InsecureURLError on an http redirect")


# --------------------------------------------------------------------------- #
# Property 24 — Unpacking yields exactly the current pack (R6.3)
# --------------------------------------------------------------------------- #


def _zip_of(names_to_bytes) -> bytes:
    """A zip archive whose members are exactly ``names_to_bytes`` (name -> bytes)."""
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in names_to_bytes.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _members_on_disk(out_dir: Path) -> set:
    """Every file under ``out_dir``, as posix-relative paths (mac cruft skipped)."""
    members = set()
    for p in out_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(out_dir).as_posix()
        if "__MACOSX" in rel or rel.endswith(".DS_Store"):
            continue
        members.add(rel)
    return members


# A file name that stays inside the pack: a single path segment from a safe
# alphabet, with a fixed suffix so it never ends in "/" (a directory entry).
_pack_name = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1,
    max_size=12,
).map(lambda s: s + ".svg")


# Feature: honest-gates, Property 24: Unpacking yields exactly the current pack
@fs_settings
@given(
    names_a=st.lists(_pack_name, min_size=1, max_size=6, unique=True),
    names_b=st.lists(_pack_name, min_size=1, max_size=6, unique=True),
    body=st.binary(min_size=0, max_size=32),
)
def test_unpacking_yields_exactly_the_current_pack(
    names_a, names_b, body, tmp_path_factory
):
    """Unpacking pack B over pack A leaves exactly B's files — nothing from A.

    ``_unpack_fresh`` stages into a sibling directory and swaps it into place,
    so a file present only in the earlier pack A cannot survive into
    ``out_dir`` after B is unpacked (R6.3).
    """
    root = tmp_path_factory.mktemp("freshunpack")
    out_dir = root / "prov-icons"

    pack_a = {name: b"A:" + body for name in names_a}
    pack_b = {name: b"B:" + body for name in names_b}
    zip_a = root / "a.zip"
    zip_b = root / "b.zip"
    zip_a.write_bytes(_zip_of(pack_a))
    zip_b.write_bytes(_zip_of(pack_b))

    # First pack A, then pack B, into the same out_dir.
    fetch_assets._unpack_fresh(zip_a, out_dir)
    assert _members_on_disk(out_dir) == set(pack_a)

    n_b = fetch_assets._unpack_fresh(zip_b, out_dir)

    # Exactly pack B remains: every A-only file is gone, and B's contents win.
    assert _members_on_disk(out_dir) == set(pack_b)
    assert n_b == len(pack_b)
    for gone in set(pack_a) - set(pack_b):
        assert not (out_dir / gone).exists()
    for name in pack_b:
        assert (out_dir / name).read_bytes() == pack_b[name]


def test_unpack_fresh_rejects_zip_slip_entry(tmp_path):
    """The zip-slip guard rejects an entry whose path escapes ``out_dir`` (R6.3).

    A malicious archive with a ``../`` member must raise rather than write
    outside the pack directory, and it must not leave ``out_dir`` in place.
    """
    import zipfile

    zip_path = tmp_path / "evil.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("icon.svg", b"ok")
        zf.writestr("../escape.svg", b"pwned")
    zip_path.write_bytes(buf.getvalue())

    out_dir = tmp_path / "assets" / "prov-icons"
    try:
        fetch_assets._unpack_fresh(zip_path, out_dir)
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("expected the zip-slip guard to reject ../escape.svg")

    # Nothing escaped, and the staged pack was not swapped into place.
    assert not (tmp_path / "assets" / "escape.svg").exists()
    assert not (tmp_path / "escape.svg").exists()
    assert not out_dir.exists()

# --------------------------------------------------------------------------- #
# Property 26 — Slugs keep meaningful words, ambiguity is never guessed (R6.6, R6.7)
# --------------------------------------------------------------------------- #
#
# Two legs, matching design.md → Correctness Properties → Property 26:
#
#   (leg 1, R6.6) For any service name containing ``service``, ``cloud`` or
#   ``public``, the vendor-stripped slug RETAINS those words, so two names that
#   differ only by one of them get different slugs. Before this fix those three
#   words were in ``_STRIP_TOKENS`` and were dropped, collapsing e.g. "Private
#   Link" and "Private Link Service" onto one slug and making one unreachable.
#
#   (leg 2, R6.7) For any index in which two DISTINCT services share an exact
#   slug, ``resolve_asset`` for that slug returns ``unresolved`` listing both
#   services as candidates — it never guesses an arbitrary winner.

from rule_engine.asset_index import (  # noqa: E402
    _BUILTIN_STENCILS,
    _STRIP_TOKENS,
    index_provider,
    normalize_slug,
    resolve_asset,
)

#: The three meaning-carrying words that must survive vendor-stripping (R6.6).
_MEANINGFUL_WORDS = ("service", "cloud", "public")

# A "core" token that is never a vendor/decoration word (``_STRIP_TOKENS``) nor
# one of the three meaningful words — so a slug built from these tokens is
# stable and non-empty after vendor-stripping, and adding a meaningful word
# genuinely lengthens it rather than being the whole (then-empty) name.
_core_token = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz",
    min_size=3,
    max_size=8,
).filter(
    lambda t: t not in _MEANINGFUL_WORDS
    and t not in _STRIP_TOKENS
    and t not in _BUILTIN_STENCILS["aws"]
)

# One or two core tokens joined by a space form a base service name like
# "private link" — a realistic multi-word service without any stripped word.
_base_name = st.lists(_core_token, min_size=1, max_size=2).map(" ".join)


# Feature: honest-gates, Property 26: Slugs keep meaningful words, ambiguity is never guessed
@given(
    base=_base_name,
    word=st.sampled_from(_MEANINGFUL_WORDS),
    trailing=st.booleans(),
)
def test_slug_retains_meaningful_words(base, word, trailing):
    """R6.6: adding ``service``/``cloud``/``public`` changes the slug.

    The plain base name and the name that differs only by an added meaningful
    word normalise to DIFFERENT slugs, and the added word is present as a whole
    token in the longer slug — so the two distinct services stay reachable.
    """
    other = f"{base} {word}" if trailing else f"{word} {base}"

    base_slug = normalize_slug(base, strip_vendor=True)
    other_slug = normalize_slug(other, strip_vendor=True)

    # The base name is a clean, non-empty slug (built from core tokens only).
    assert base_slug
    # The meaningful word survives stripping and lengthens the slug.
    assert other_slug != base_slug
    assert word in other_slug.split("-")


# A single core-token service name, used as the display core of two distinct
# vendor-prefixed services that collide on one vendor-stripped slug.
_collision_core = st.lists(_core_token, min_size=1, max_size=2).map(
    lambda ts: "-".join(ts)
)

# Two DISTINCT vendor prefixes that ``_STRIP_TOKENS`` drops, so
# "<prefix-a>-<core>" and "<prefix-b>-<core>" share the vendor-stripped slug
# ``<core>`` while keeping distinct display names (a genuine R6.7 collision).
_vendor_prefix_pair = st.sampled_from(
    [("Amazon", "AWS"), ("AWS", "Amazon")]
)


# Feature: honest-gates, Property 26: Slugs keep meaningful words, ambiguity is never guessed
@fs_settings
@given(core=_collision_core, prefixes=_vendor_prefix_pair)
def test_ambiguous_exact_slug_is_unresolved_with_candidates(
    core, prefixes, tmp_path_factory
):
    """R6.7: an exact slug claimed by two distinct services is never guessed.

    Build an AWS pack with two files whose display names differ only by a
    vendor prefix that is stripped, so both normalise to the same slug. The
    index records the slug as ambiguous and ``resolve_asset`` returns
    ``unresolved`` listing both display names — rather than the arbitrary
    winner the index happened to keep.
    """
    prefix_a, prefix_b = prefixes
    slug = core  # both files vendor-strip to exactly this slug
    display_a = f"{prefix_a} {core.replace('-', ' ')}"
    display_b = f"{prefix_b} {core.replace('-', ' ')}"

    root = tmp_path_factory.mktemp("awspack") / "aws"
    svc = root / "Architecture-Service-Icons_07312026"
    (svc / "Arch_A" / "32").mkdir(parents=True)
    (svc / "Arch_A" / "32" / f"Arch_{prefix_a}-{core}_32.svg").write_text("<svg/>")
    (svc / "Arch_B" / "32").mkdir(parents=True)
    (svc / "Arch_B" / "32" / f"Arch_{prefix_b}-{core}_32.svg").write_text("<svg/>")

    idx = index_provider("aws", str(root))

    # The slug is recorded as ambiguous with BOTH distinct display names.
    assert slug in idx.ambiguous
    assert {display_a, display_b} <= set(idx.ambiguous[slug])

    # Resolving the ambiguous slug is fail-honest: unresolved, no asset guessed,
    # and every competing service listed as a candidate for the caller to pick.
    r = resolve_asset("aws", slug, idx)
    assert r.source == "unresolved"
    assert r.asset_path is None and r.stencil is None
    assert {display_a, display_b} <= set(r.candidates)


# --------------------------------------------------------------------------- #
# Preservation (honest-gates-slug-builtin-flake, task 2)
# Property 2: Preservation — Non-Built-in Ambiguity And Slug Retention Unchanged
# --------------------------------------------------------------------------- #
#
# Observation-first: the behaviours below are what the fix must PRESERVE, and
# they already hold on the UNFIXED suite. They are captured as their own
# deterministic property tests so the baseline is pinned independently of the
# flaky R6.7 test (whose ``_core_token`` generator is still under-constrained
# until task 3 and so can wander into the built-in bug condition).
#
#   * leg 1 (R6.6) — meaningful words survive vendor-stripping. This is exactly
#     ``test_slug_retains_meaningful_words`` above, which passes unchanged; it is
#     the retention leg of Property 2 and needs no duplicate here.
#
#   * leg 2 (R6.7, non-built-in) — an ambiguous slug that is NOT a curated
#     built-in stencil slug resolves to ``unresolved`` with both display names in
#     ``candidates`` (e.g. the ``core='vpc'`` control from design.md). This is
#     the fail-honest behaviour the fix must leave intact for every non-built-in
#     ambiguous core.

#: A single-token collision core guaranteed NOT to be a curated built-in AWS
#: stencil slug — so this preservation test only ever exercises the non-built-in
#: ambiguous path (the behaviour to preserve), never the built-in bug condition
#: that task 1 surfaces. Referencing ``_BUILTIN_STENCILS['aws']`` (the real
#: table) keeps it correct if a future built-in is added.
_non_builtin_collision_core = st.lists(_core_token, min_size=1, max_size=2).map(
    lambda ts: "-".join(ts)
).filter(lambda slug: slug not in _BUILTIN_STENCILS["aws"])


# Feature: honest-gates-slug-builtin-flake, Property 2: Preservation — Non-Built-in Ambiguity And Slug Retention Unchanged
# **Validates: Requirements 3.1, 3.2, 3.3**
@fs_settings
@given(core=_non_builtin_collision_core, prefixes=_vendor_prefix_pair)
def test_non_builtin_ambiguous_slug_preserved_unresolved(
    core, prefixes, tmp_path_factory
):
    """R6.7 (non-built-in): an ambiguous, non-built-in slug stays ``unresolved``.

    The preservation baseline: for any ambiguous slug that is NOT a curated
    built-in stencil slug (the ``core='vpc'`` control generalised), the resolver
    is fail-honest — ``source='unresolved'``, no asset/stencil guessed, and every
    competing display name listed as a candidate. Production code is unchanged,
    so this must continue to hold after the task-3 generator fix.
    """
    prefix_a, prefix_b = prefixes
    slug = core  # both files vendor-strip to exactly this slug
    display_a = f"{prefix_a} {core.replace('-', ' ')}"
    display_b = f"{prefix_b} {core.replace('-', ' ')}"

    root = tmp_path_factory.mktemp("awspack") / "aws"
    svc = root / "Architecture-Service-Icons_07312026"
    (svc / "Arch_A" / "32").mkdir(parents=True)
    (svc / "Arch_A" / "32" / f"Arch_{prefix_a}-{core}_32.svg").write_text("<svg/>")
    (svc / "Arch_B" / "32").mkdir(parents=True)
    (svc / "Arch_B" / "32" / f"Arch_{prefix_b}-{core}_32.svg").write_text("<svg/>")

    idx = index_provider("aws", str(root))

    # The non-built-in slug is recorded as ambiguous with BOTH display names.
    assert slug not in _BUILTIN_STENCILS["aws"]
    assert slug in idx.ambiguous
    assert {display_a, display_b} <= set(idx.ambiguous[slug])

    # Fail-honest: unresolved, nothing guessed, every competitor a candidate.
    r = resolve_asset("aws", slug, idx)
    assert r.source == "unresolved"
    assert r.asset_path is None and r.stencil is None
    assert {display_a, display_b} <= set(r.candidates)


# --------------------------------------------------------------------------- #
# Bug condition exploration → pinned expected behaviour
# (honest-gates-slug-builtin-flake, task 1 → task 3.2)
# Property 1: Bug Condition — Ambiguity Test Never Collides With A Built-in Slug
# --------------------------------------------------------------------------- #
#
# ORIGIN (task 1, bug-condition demonstration). This test began as the
# bug-condition exploration for the latent flake in
# ``test_ambiguous_exact_slug_is_unresolved_with_candidates`` (R6.7): its
# ``_core_token`` strategy could draw a ``core`` that is also a single-token
# curated AWS built-in stencil slug (``eks``/``s3``/``rds``/``sqs``/``lambda``/
# ``bedrock``). For such a core, ``resolve_asset`` correctly short-circuits to
# ``source='builtin'`` (step 1 of the documented resolution order) BEFORE the
# ambiguous map the R6.7 test tries to exercise — so the pre-fix ``unresolved``
# assertion failed, which is what demonstrated the flake existed.
#
# It is scoped (parametrized) to the concrete cores rather than left to
# Hypothesis, so it exercises the reported counterexample ``core='eks'`` and its
# five siblings deterministically on every run.
#
# TRANSITION (task 3.2, pinned expected behaviour). Once task 3.1 constrained
# ``_core_token`` to never draw a built-in slug, the flake is resolved and the
# bug-condition demonstration has done its job. A bug-condition test's pre-fix
# assertion is NOT the expected behaviour after the fix — leaving the old
# ``unresolved`` assertion here would hard-fail against the correct resolver
# (which returns ``builtin`` for a built-in core) and break the checkpoint.
# So the assertion is now flipped to the CORRECT post-fix expected behaviour:
# for a built-in core the resolver returns ``source='builtin'`` (built-in
# priority, step 1 of ``asset-packs.md`` "Icon Resolution Order"). This is
# Property 3 (built-in priority) generalised across ALL six single-token
# built-in slugs, and it is exactly why the R6.7 generator must exclude them.
#
# EXPECTED OUTCOME: all six parametrized cases PASS — ``resolve_asset`` returns
# ``source='builtin'`` with the stencil id set and ``asset_path``/``candidates``
# unused — pinning built-in-over-ambiguous priority for every single-token
# built-in AWS slug.

#: The single-token members of ``_BUILTIN_STENCILS['aws']`` — every core the
#: ``_core_token`` strategy can draw that collides with resolver step 1.
#: ``secrets-manager`` is excluded: it is two tokens, so it can never be a
#: single core token.
_SINGLE_TOKEN_BUILTIN_AWS_SLUGS = ("eks", "s3", "rds", "sqs", "lambda", "bedrock")


# Feature: honest-gates-slug-builtin-flake, Property 1: Bug Condition — Ambiguity Test Never Collides With A Built-in Slug
# **Validates: Requirements 1.1, 1.2**
@pytest.mark.parametrize("core", _SINGLE_TOKEN_BUILTIN_AWS_SLUGS)
def test_bug_condition_ambiguous_builtin_slug_collides(core, tmp_path):
    """Built-in priority pinned across every single-token built-in AWS slug.

    Build the same two-file AWS pack as
    ``test_ambiguous_exact_slug_is_unresolved_with_candidates`` — two display
    names differing only by a stripped vendor prefix, both normalising to
    ``core`` — where ``core`` is a single-token curated AWS built-in stencil
    slug. The slug IS recorded as ambiguous, yet ``resolve_asset`` consults
    ``_BUILTIN_STENCILS`` (step 1 of the ``asset-packs.md`` "Icon Resolution
    Order") BEFORE the ambiguous map (step 2), so it returns
    ``source='builtin'`` with the stencil id set and ``asset_path``/
    ``candidates`` unused.

    This began (task 1) as the bug-condition exploration and asserted the
    pre-fix ``unresolved`` expectation to demonstrate the flake. Once task 3.1
    constrained ``_core_token`` to never draw a built-in slug, the flake was
    resolved; per task 3.2 the assertion is flipped to the CORRECT post-fix
    behaviour (built-in priority), Property 3 generalised across all six
    single-token built-in slugs. Leaving the old ``unresolved`` assertion here
    would hard-fail against the correct resolver and break the checkpoint.
    """
    prefix_a, prefix_b = ("Amazon", "AWS")
    slug = core  # both files vendor-strip to exactly this slug
    display_a = f"{prefix_a} {core.replace('-', ' ')}"
    display_b = f"{prefix_b} {core.replace('-', ' ')}"

    root = tmp_path / "aws"
    svc = root / "Architecture-Service-Icons_07312026"
    (svc / "Arch_A" / "32").mkdir(parents=True)
    (svc / "Arch_A" / "32" / f"Arch_{prefix_a}-{core}_32.svg").write_text("<svg/>")
    (svc / "Arch_B" / "32").mkdir(parents=True)
    (svc / "Arch_B" / "32" / f"Arch_{prefix_b}-{core}_32.svg").write_text("<svg/>")

    idx = index_provider("aws", str(root))

    # The slug is genuinely ambiguous with BOTH distinct display names — exactly
    # as the R6.7 test sets up (these asserts pass; the collision is real).
    assert slug in idx.ambiguous
    assert {display_a, display_b} <= set(idx.ambiguous[slug])

    # Post-fix expected behaviour: resolve_asset consults _BUILTIN_STENCILS
    # (step 1) before the ambiguous map (step 2), so a built-in core resolves to
    # source='builtin' (e.g. mxgraph.aws4.eks) with the stencil id set and no
    # asset path / candidate list used.
    r = resolve_asset("aws", slug, idx)
    assert r.source == "builtin"
    assert r.stencil == _BUILTIN_STENCILS["aws"][slug]
    assert r.asset_path is None
    assert not r.candidates


# --------------------------------------------------------------------------- #
# Built-in priority contract (honest-gates-slug-builtin-flake, task 3.1)
# Property 3: Built-in Priority — A Built-in Slug That Is Also Ambiguous
#             Resolves To Built-in
# --------------------------------------------------------------------------- #
#
# The companion to the bug-condition test above. It documents, as a DELIBERATE
# contract rather than an accident, that the resolver's built-in stencil (step 1
# of the asset-packs.md "Icon Resolution Order") takes priority over the
# ambiguous-slug fail-honest path (which lives inside step 2). This is exactly
# why the R6.7 ambiguity test must never draw a built-in slug as its collision
# core — and the reason the ``_core_token`` generator is now constrained to
# exclude ``_BUILTIN_STENCILS['aws']``.
#
# A plain deterministic unit test (not property-based): the input is a single
# concrete built-in slug that is ALSO ambiguous, and the asserted outcome is
# fixed.


# Feature: honest-gates-slug-builtin-flake, Property 3: Built-in Priority — A Built-in Slug That Is Also Ambiguous Resolves To Built-in
# **Validates: Requirements 2.2**
def test_builtin_slug_that_is_also_ambiguous_resolves_to_builtin(tmp_path):
    """R2.2: a built-in slug that is also ambiguous resolves to ``builtin``.

    Build the same two-file AWS pack the R6.7 test uses, colliding on ``eks`` —
    a single-token curated AWS built-in stencil slug. The index genuinely
    records ``eks`` as ambiguous (two distinct display names), yet
    ``resolve_asset`` consults ``_BUILTIN_STENCILS`` (step 1) BEFORE the
    ambiguous map (step 2), so it returns ``source='builtin'`` with the stencil
    id set and ``asset_path``/``candidates`` unused. This pins built-in priority
    as a deliberate contract.
    """
    core = "eks"  # a single-token curated AWS built-in stencil slug
    assert core in _BUILTIN_STENCILS["aws"]  # guard: the premise still holds

    prefix_a, prefix_b = ("Amazon", "AWS")
    slug = core  # both files vendor-strip to exactly this slug
    display_a = f"{prefix_a} {core}"
    display_b = f"{prefix_b} {core}"

    root = tmp_path / "aws"
    svc = root / "Architecture-Service-Icons_07312026"
    (svc / "Arch_A" / "32").mkdir(parents=True)
    (svc / "Arch_A" / "32" / f"Arch_{prefix_a}-{core}_32.svg").write_text("<svg/>")
    (svc / "Arch_B" / "32").mkdir(parents=True)
    (svc / "Arch_B" / "32" / f"Arch_{prefix_b}-{core}_32.svg").write_text("<svg/>")

    idx = index_provider("aws", str(root))

    # The slug IS genuinely ambiguous in the index (the collision is real) ...
    assert slug in idx.ambiguous
    assert {display_a, display_b} <= set(idx.ambiguous[slug])

    # ... but the built-in stencil (step 1) wins over the ambiguous path (step 2):
    # source='builtin', the stencil id is set, and no asset/candidate is used.
    r = resolve_asset("aws", slug, idx)
    assert r.source == "builtin"
    assert r.stencil == _BUILTIN_STENCILS["aws"][slug]
    assert r.asset_path is None
    assert not r.candidates


# --------------------------------------------------------------------------- #
# Property 25 — Pin rewriting preserves everything else (R6.5)
# --------------------------------------------------------------------------- #
#
# Two legs, matching design.md → Correctness Properties → Property 25:
#
#   (leg 1, the pure rewrite) For any asset-sources.yaml text with comments and
#   several providers, and any new (sha256, size) values for a SUBSET of them,
#   ``_rewrite_pin_lines`` output (a) parses to the new values for the rewritten
#   providers, (b) keeps the old values for the others, and (c) differs from the
#   input ONLY on the rewritten ``sha256:``/``size:`` lines — every comment,
#   blank line, indentation and non-pin key survives verbatim.
#
#   (leg 2, the round trip against real bytes) Driving ``--update-pins`` with an
#   injectable fake opener that serves fixture bytes, the pins written back into
#   asset-sources.yaml are exactly the sha256/size of the bytes that were
#   "downloaded" — the written pin verifies against the same bytes.

import hashlib as _hashlib

import yaml as _yaml
from hypothesis import settings as _settings

from rule_engine import build_icon_sets_cli as _bics
from rule_engine.build_icon_sets_cli import _rewrite_pin_lines


#: The five provider source keys as they appear in asset-sources.yaml.
_SOURCE_KEYS = ("aws", "azure", "gcp_category", "gcp_core", "oci")

#: A 64-hex sha256 digest string.
_sha_hex = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)

#: A byte size for a pack.
_pin_size = st.integers(min_value=0, max_value=1 << 32)


def _render_sources_doc(providers, *, pins) -> str:
    """Render an asset-sources.yaml-shaped document with comments and blanks.

    ``providers`` is the ordered list of source keys to emit; ``pins`` maps each
    key to its ``(sha256, size)`` starting values (empty string for a
    placeholder). The layout deliberately mirrors the real file: a leading
    comment block, top-level scalars, a ``providers:`` map at two-space indent,
    and per-provider ``sha256:``/``size:`` lines carrying trailing comments — so
    the rewrite is exercised against the exact shape it must preserve.
    """
    lines = [
        "# Official provider icon asset sources.",
        "#",
        "# A leading comment block that must survive a pin rewrite verbatim.",
        "",
        "version: 1",
        "asset_root: assets/vendor",
        "",
        "providers:",
    ]
    for key in providers:
        sha, size = pins[key]
        sha_val = f'"{sha}"' if sha != "" else '""'
        size_val = str(size) if size != "" else '""'
        lines += [
            f"  {key}:",
            f"    pack: {key} pack",
            f'    url: "https://example.test/{key}.zip"',
            f"    sha256: {sha_val}                  # populated by --update-pins",
            f"    size: {size_val}                    # populated by --update-pins",
            f"    unpack_to: {key}-icons",
            "    icon_source: custom         # a trailing comment on a non-pin line",
            "",
        ]
    return "\n".join(lines) + "\n"


@st.composite
def _rewrite_scenario(draw: st.DrawFn):
    """Generate (doc_text, providers, start_pins, updates).

    ``updates`` maps a non-empty SUBSET of providers to fresh ``(sha256, size)``
    values that differ from the starting pins, so the rewrite has observable
    work to do on some blocks and none on the others.
    """
    providers = draw(
        st.lists(st.sampled_from(_SOURCE_KEYS), min_size=2, max_size=5, unique=True)
    )
    # Starting pins: a mix of placeholders and already-populated values.
    start_pins = {}
    for key in providers:
        if draw(st.booleans()):
            start_pins[key] = ("", "")  # placeholder
        else:
            start_pins[key] = (draw(_sha_hex), draw(_pin_size))

    doc = _render_sources_doc(providers, pins=start_pins)

    # Choose a non-empty subset to update with values distinct from the start.
    to_update = draw(
        st.lists(st.sampled_from(providers), min_size=1, max_size=len(providers), unique=True)
    )
    updates = {}
    for key in to_update:
        new_sha = draw(_sha_hex.filter(lambda s, k=key: s != start_pins[k][0]))
        new_size = draw(_pin_size.filter(lambda n, k=key: n != start_pins[k][1]))
        updates[key] = (new_sha, new_size)
    return doc, providers, start_pins, updates


def _pins_from_yaml(text):
    """Return ``{source_key: (sha256, size)}`` parsed from a sources document."""
    data = _yaml.safe_load(text) or {}
    out = {}
    for key, spec in (data.get("providers") or {}).items():
        if isinstance(spec, dict):
            out[key] = (spec.get("sha256"), spec.get("size"))
    return out


def _diff_line_indices(before, after):
    """Indices of lines that differ between two equal-length line lists."""
    return {i for i, (a, b) in enumerate(zip(before, after)) if a != b}


def _pin_line_indices(text, provider):
    """Line indices of the ``sha256:``/``size:`` lines inside a provider block.

    Recomputed with the same block-scoping logic the rewriter uses so the test
    asserts an independent oracle rather than trusting the code under test.
    """
    lines = text.splitlines()
    indices = set()
    in_block = False
    block_indent = -1
    for i, line in enumerate(lines):
        header = _bics._PROVIDER_HEADER_RE.match(line)
        if header:
            key = header.group("key")
            indent = len(header.group("indent"))
            if key == provider:
                in_block, block_indent = True, indent
            elif in_block and indent <= block_indent:
                in_block = False
            continue
        if in_block:
            stripped = line.strip()
            if stripped and (len(line) - len(line.lstrip())) <= block_indent:
                in_block = False
                continue
            pin = _bics._PIN_LINE_RE.match(line)
            if pin and pin.group("key") in ("sha256", "size"):
                indices.add(i)
    return indices


# Feature: honest-gates, Property 25: Pin rewriting preserves everything else
@given(scenario=_rewrite_scenario())
@_settings(max_examples=200)
def test_pin_rewrite_preserves_everything_else(scenario):
    """R6.5: the rewrite changes only the target providers' pin values.

    Rewrite each updated provider's ``(sha256, size)`` in turn, then assert:
      (a) the result parses to the NEW values for every updated provider;
      (b) the OLD values survive for every provider not updated;
      (c) the only lines that differ from the input are the ``sha256:``/``size:``
          lines inside the updated providers' blocks — every comment, blank,
          indentation and non-pin key is byte-identical.
    """
    doc, providers, start_pins, updates = scenario

    text = doc
    for key, (sha, size) in updates.items():
        text = _rewrite_pin_lines(text, key, sha, size)

    # (a) + (b): parsed pins match new-for-updated, old-for-untouched.
    parsed = _pins_from_yaml(text)
    for key in providers:
        want_sha, want_size = updates.get(key, start_pins[key])
        got_sha, got_size = parsed[key]
        # A placeholder "" round-trips as an empty string; a populated value as
        # itself (size as int, sha as the hex string).
        assert (got_sha or "") == (want_sha or "")
        assert (got_size if got_size not in (None, "") else "") == (
            want_size if want_size not in (None, "") else ""
        )

    # (c) only the updated providers' pin lines changed.
    before_lines = doc.splitlines()
    after_lines = text.splitlines()
    assert len(before_lines) == len(after_lines)  # no lines added/removed
    changed = _diff_line_indices(before_lines, after_lines)
    allowed = set()
    for key in updates:
        allowed |= _pin_line_indices(doc, key)
    assert changed <= allowed
    # Every trailing comment on a rewritten pin line survives.
    for i in changed:
        if "#" in before_lines[i]:
            assert before_lines[i].split("#", 1)[1] == after_lines[i].split("#", 1)[1]


# --------------------------------------------------------------------------- #
# Leg 2 — the round trip: --update-pins writes pins that match the real bytes.
# --------------------------------------------------------------------------- #


class _NoPinFakeOpener:
    """Serve fixed ``payload`` bytes for any provider's HTTPS url (no network)."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, req, timeout=None):  # noqa: A003
        return _FakeResponse(self.payload)


# Feature: honest-gates, Property 25: Pin rewriting preserves everything else
@fs_settings
@given(
    inner=st.binary(min_size=0, max_size=64),
    only=st.lists(st.sampled_from(_SOURCE_KEYS), min_size=1, max_size=3, unique=True),
)
def test_update_pins_round_trips_against_the_downloaded_bytes(
    inner, only, tmp_path_factory, monkeypatch
):
    """R6.5: after --update-pins, each written pin matches the fetched bytes.

    ``_update_pins`` downloads each pack (here, fixture bytes from a fake
    opener), hashes it, and rewrites the pins in asset-sources.yaml. The written
    ``sha256``/``size`` must equal the sha256/byte-count of exactly those bytes —
    a round trip: the pin the command wrote verifies against the same bytes the
    later fetcher would download.
    """
    payload = _zip_bytes(inner)
    expected_sha = _hashlib.sha256(payload).hexdigest()
    expected_size = len(payload)

    # Point the module's asset-sources path at a temp copy so the real committed
    # file is never touched, and every provider carries an empty placeholder pin.
    sources_text = _render_sources_doc(
        list(_SOURCE_KEYS), pins={k: ("", "") for k in _SOURCE_KEYS}
    )
    tmp = tmp_path_factory.mktemp("pins")
    sources_path = tmp / "asset-sources.yaml"
    sources_path.write_text(sources_text, encoding="utf-8")
    monkeypatch.setattr(_bics, "_ASSET_SOURCES", sources_path)

    rc, changes = _bics._update_pins(
        only=only, opener_factory=lambda: _NoPinFakeOpener(payload)
    )

    assert rc == _bics.EXIT_OK
    assert set(changes) == set(only)

    parsed = _pins_from_yaml(sources_path.read_text(encoding="utf-8"))
    for key in _SOURCE_KEYS:
        got_sha, got_size = parsed[key]
        if key in only:
            # Round trip: written pin == the fetched bytes' digest and length.
            assert got_sha == expected_sha
            assert got_size == expected_size
            assert changes[key] == ("", expected_sha, expected_size)
        else:
            # Untouched providers keep their empty placeholder.
            assert (got_sha or "") == ""
            assert (got_size if got_size not in (None, "") else "") == ""
