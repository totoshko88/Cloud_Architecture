"""S-b: the asset fetcher must unpack a gzip tarball, not just a ZIP.

The AWS/Azure/GCP packs are ZIPs, but the Kubernetes community pack is a
``codeload`` git-archive ``tar.gz`` and the opensource Simple Icons pack is an
npm ``.tgz`` — both gzip tarballs. ``_unpack`` dispatches on the leading magic
bytes (``PK`` → zip, ``\\x1f\\x8b`` → gzip tar), keeping the same slip guard and
mac-cruft skip for both, so ``fetch_provider`` unpacks either shape.

Network-free: a fake opener (reused shape from ``test_fetch_properties``) serves
fixture bytes, and the spec carries the matching sha256/size pin.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from rule_engine import fetch_assets
from rule_engine.fetch_assets import _unpack, fetch_provider


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _FakeOpener:
    def __init__(self, payload: bytes):
        self.payload = payload

    def open(self, req, timeout=None):  # noqa: A003
        return _FakeResponse(self.payload)


def _targz_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _pin(payload: bytes) -> dict:
    return {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}


def test_unpack_dispatches_zip_and_targz(tmp_path):
    z = tmp_path / "a.zip"
    z.write_bytes(_zip_bytes({"icons/svg/pod.svg": b"<svg/>"}))
    n = _unpack(z, tmp_path / "zout")
    assert (tmp_path / "zout/icons/svg/pod.svg").is_file()
    assert n == 1

    t = tmp_path / "b.tar.gz"
    t.write_bytes(_targz_bytes({"community-abc/icons/svg/pod.svg": b"<svg/>"}))
    n = _unpack(t, tmp_path / "tout")
    assert (tmp_path / "tout/community-abc/icons/svg/pod.svg").is_file()
    assert n == 1


def test_unpack_rejects_non_archive(tmp_path):
    h = tmp_path / "err.html"
    h.write_bytes(b"<html>404 Not Found</html>")
    with pytest.raises(ValueError, match="not a ZIP or gzip tarball"):
        _unpack(h, tmp_path / "out")


def test_unpack_tar_rejects_slip(tmp_path):
    t = tmp_path / "evil.tar.gz"
    t.write_bytes(_targz_bytes({"../../escape.svg": b"x"}))
    with pytest.raises(ValueError, match="escapes"):
        _unpack(t, tmp_path / "out")


def test_fetch_provider_unpacks_a_gzip_tarball(tmp_path):
    """A git-archive-style tar.gz pack (the Kubernetes pack shape) is fetched,
    pin-verified, and unpacked end-to-end — the exact S-b blocker."""
    payload = _targz_bytes(
        {
            "community-53c/icons/svg/pod.svg": b"<svg>pod</svg>",
            "community-53c/icons/svg/deploy.svg": b"<svg>deploy</svg>",
        }
    )
    spec = dict(_pin(payload), url="https://example.test/pack.tar.gz",
                unpack_to="k8s-icons", kind="svg-png-tree")
    asset_root = tmp_path / "assets"
    cache_dir = tmp_path / "cache"
    result = fetch_provider(
        "kubernetes", spec, asset_root, cache_dir, opener=_FakeOpener(payload)
    )
    assert result["files"] == 2
    assert (asset_root / "k8s-icons/community-53c/icons/svg/pod.svg").is_file()
    assert (asset_root / "k8s-icons/community-53c/icons/svg/deploy.svg").is_file()
