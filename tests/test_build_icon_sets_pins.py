"""Feature: honest-gates (release 1.7.0), task 14.6.

``rule-engine-build-icon-sets --update-pins`` downloads each pack over HTTPS,
computes its sha256 and size, and rewrites ONLY the ``sha256:``/``size:`` lines
inside each provider block of ``mappings/asset-sources.yaml`` — comments, layout
and every other line survive (PyYAML cannot round-trip comments, so the rewrite
is line-oriented, not a full YAML dump). ``--manifests-dir`` redirects where the
committed manifests are written.

These tests drive the pin rewrite with an **injectable fake opener** (mirroring
``tests/test_fetch_properties.py``) so no network and no real vendor pack is
touched, and they assert the line-preserving property directly on the rewriter.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from typing import Optional

from rule_engine import build_icon_sets_cli as bics
from rule_engine.build_icon_sets_cli import _rewrite_pin_lines


# --------------------------------------------------------------------------- #
# A network-free fake opener that serves fixture bytes for every URL.
# --------------------------------------------------------------------------- #


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class _FakeOpener:
    """Serve fixed ``payload`` bytes for any request (all-HTTPS, no redirect)."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, req, timeout: Optional[float] = None):  # noqa: A003
        return _FakeResponse(self.payload)


def _zip_bytes(inner: bytes = b"icon") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("icon.svg", inner)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# The line-oriented rewriter preserves comments and every other line.
# --------------------------------------------------------------------------- #

_SAMPLE = """\
# a leading comment
version: 1
asset_root: assets/vendor

providers:
  aws:
    pack: AWS Architecture Icons
    url: "https://example.test/aws.zip"
    sha256: ""                  # populated by --update-pins
    size: ""                    # populated by --update-pins
    unpack_to: aws-icons
    icon_source: builtin        # keep me

  azure:
    pack: Azure Public Service Icons
    url: "https://example.test/azure.zip"
    sha256: "deadbeef"
    size: 42
    unpack_to: azure-icons
"""


def test_rewrite_only_touches_the_target_provider_pin_lines():
    new_sha = "a" * 64
    out = _rewrite_pin_lines(_SAMPLE, "aws", new_sha, 12345)

    lines = out.splitlines()
    # The aws block's pins were rewritten, comments intact.
    assert f'    sha256: "{new_sha}"                  # populated by --update-pins' in lines
    assert "    size: 12345                    # populated by --update-pins" in lines
    # Azure's pins are untouched (different provider block).
    assert '    sha256: "deadbeef"' in lines
    assert "    size: 42" in lines
    # Every non-pin line survives verbatim, including comments and the url.
    assert "# a leading comment" in lines
    assert "    icon_source: builtin        # keep me" in lines
    assert '    url: "https://example.test/aws.zip"' in lines
    # Same number of lines in and out (a pure value edit, no line added/removed).
    assert len(out.splitlines()) == len(_SAMPLE.splitlines())


def test_rewrite_a_second_provider_leaves_the_first_intact():
    first = _rewrite_pin_lines(_SAMPLE, "aws", "a" * 64, 111)
    both = _rewrite_pin_lines(first, "azure", "b" * 64, 222)
    lines = both.splitlines()
    assert f'    sha256: "{"a" * 64}"                  # populated by --update-pins' in lines
    assert "    size: 111                    # populated by --update-pins" in lines
    assert f'    sha256: "{"b" * 64}"' in lines
    assert "    size: 222" in lines


def test_rewrite_is_a_no_op_for_an_absent_provider():
    out = _rewrite_pin_lines(_SAMPLE, "gcp_core", "c" * 64, 999)
    assert out == _SAMPLE


# --------------------------------------------------------------------------- #
# --update-pins end to end with a fake opener (no network).
# --------------------------------------------------------------------------- #


def test_update_pins_writes_computed_digest_with_a_fake_opener(tmp_path, monkeypatch):
    """--update-pins hashes the served bytes and rewrites the pins in place,
    preserving the file's comments — all without any network."""
    payload = _zip_bytes(b"hello-icons")
    expected_sha = hashlib.sha256(payload).hexdigest()
    expected_size = len(payload)

    sources = tmp_path / "asset-sources.yaml"
    sources.write_text(_SAMPLE, encoding="utf-8")
    # Point the CLI's asset-sources path at our fixture.
    monkeypatch.setattr(bics, "_ASSET_SOURCES", sources)

    rc, changes = bics._update_pins(
        only=["aws"], opener_factory=lambda: _FakeOpener(payload)
    )
    assert rc == bics.EXIT_OK
    assert changes["aws"] == ("", expected_sha, expected_size)

    written = sources.read_text(encoding="utf-8")
    lines = written.splitlines()
    assert f'    sha256: "{expected_sha}"                  # populated by --update-pins' in lines
    assert f"    size: {expected_size}                    # populated by --update-pins" in lines
    # A different, untouched provider block is unchanged, comment survives.
    assert "# a leading comment" in lines
    assert '    sha256: "deadbeef"' in lines


def test_update_pins_unknown_provider_is_a_usage_error(tmp_path, monkeypatch):
    sources = tmp_path / "asset-sources.yaml"
    sources.write_text(_SAMPLE, encoding="utf-8")
    monkeypatch.setattr(bics, "_ASSET_SOURCES", sources)
    rc, changes = bics._update_pins(
        only=["nope"], opener_factory=lambda: _FakeOpener(_zip_bytes())
    )
    assert rc == bics.EXIT_USAGE
    assert changes == {}
    # The file is untouched on a usage error.
    assert sources.read_text(encoding="utf-8") == _SAMPLE


def test_update_pins_cannot_combine_with_check(monkeypatch):
    """--update-pins rewrites pins, so it is incompatible with --check."""
    rc = bics.main(["--update-pins", "--check"])
    assert rc == bics.EXIT_USAGE


# --------------------------------------------------------------------------- #
# --manifests-dir redirects the committed manifests.
# --------------------------------------------------------------------------- #


def test_manifests_dir_option_is_accepted_and_parsed():
    """The --manifests-dir flag parses; its default (the --out dir) is exercised
    by the existing icon-index tests. Here we only assert the arg exists so a
    parse error would fail loudly."""
    parser_ok = True
    try:
        # --check short-circuits before any network/pack work with a bad root,
        # so this only proves the new flags are wired into argparse.
        bics.main(
            [
                "--check",
                "--no-fetch",
                "--allow-missing",
                "--manifests-dir",
                "/tmp/does-not-matter",
                "--asset-root",
                "/nonexistent-root-xyz",
            ]
        )
    except SystemExit:
        parser_ok = False
    assert parser_ok
