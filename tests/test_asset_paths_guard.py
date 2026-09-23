"""Tests for the asset-path guard (rule_engine.asset_paths_guard).

Covers the file-path existence check for mapping icon styles: checkable vs
skipped path forms, present vs missing files, and the fetch-aware exit policy
(asset root present -> enforce; absent -> skip).
"""

from __future__ import annotations

import os

from rule_engine.asset_paths_guard import (
    check_mapping_assets,
    asset_root_present,
    main,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _mapping(image_path):
    return (
        "provider: test\n"
        "asset_pack: t\n"
        "icon_source: custom\n"
        "resources:\n"
        "  object_store:\n"
        "    icon_id: t.obj\n"
        '    brand_hex: "#4285F4"\n'
        f'    style: "image;html=1;image={image_path}"\n'
    )


def test_present_file_passes(tmp_path):
    repo = tmp_path
    # asset file exists under the repo root
    _write(str(repo / "assets/vendor/pack/Icon.svg"), "<svg/>")
    _write(str(repo / "mappings/test-icons.yaml"),
           _mapping("assets/vendor/pack/Icon.svg"))

    refs = check_mapping_assets(repo / "mappings", repo)
    assert len(refs) == 1
    assert refs[0].exists is True
    assert asset_root_present(repo) is True
    assert main(["--mappings", str(repo / "mappings"), "--repo-root", str(repo)]) == 0


def test_missing_file_fails_when_asset_root_present(tmp_path):
    repo = tmp_path
    # asset root exists (some pack fetched) but the declared file is absent
    _write(str(repo / "assets/vendor/pack/Other.svg"), "<svg/>")
    _write(str(repo / "mappings/test-icons.yaml"),
           _mapping("assets/vendor/pack/Missing.svg"))

    refs = check_mapping_assets(repo / "mappings", repo)
    assert refs and refs[0].exists is False
    assert main(["--mappings", str(repo / "mappings"), "--repo-root", str(repo)]) == 1


def test_skips_when_asset_root_absent(tmp_path):
    repo = tmp_path
    # No assets/vendor at all -> packs not fetched -> skip (exit 0) even though
    # the declared file does not exist.
    _write(str(repo / "mappings/test-icons.yaml"),
           _mapping("assets/vendor/pack/Missing.svg"))

    assert asset_root_present(repo) is False
    assert main(["--mappings", str(repo / "mappings"), "--repo-root", str(repo)]) == 0


def test_non_file_styles_are_skipped(tmp_path):
    repo = tmp_path
    _write(str(repo / "assets/vendor/.keep"), "")  # asset root present
    # data-URI, draw.io img/lib, a URL, and a plain stencil are all skipped.
    _write(str(repo / "mappings/data-icons.yaml"),
           _mapping("data:image/svg+xml,PHN2Zy8+"))
    _write(str(repo / "mappings/lib-icons.yaml"),
           _mapping("img/lib/azure2/storage/Storage_Accounts.svg"))
    _write(str(repo / "mappings/url-icons.yaml"),
           _mapping("https://example.com/x.svg"))
    _write(str(repo / "mappings/stencil-icons.yaml"),
           "provider: t\nasset_pack: t\nicon_source: builtin\nresources:\n"
           "  object_store:\n    icon_id: t\n    brand_hex: \"#232F3E\"\n"
           '    style: "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.s3"\n')

    refs = check_mapping_assets(repo / "mappings", repo)
    # None of these styles are checkable file paths.
    assert refs == []
    assert main(["--mappings", str(repo / "mappings"), "--repo-root", str(repo)]) == 0

# --- OCI stencil-slug checks -----------------------------------------------

import json as _json

from rule_engine.asset_paths_guard import check_mapping_stencils


def _oci_mapping(slug):
    return (
        "provider: oci\n"
        "asset_pack: t\n"
        "icon_source: custom\n"
        "resources:\n"
        "  serverless_fn:\n"
        "    icon_id: o\n"
        '    brand_hex: "#F80000"\n'
        f'    stencil: "assets/vendor/oci-stencils/stencils.json#{slug}"\n'
        '    style: "rounded=0;html=1;strokeColor=#F80000"\n'
    )


def _write_manifest(repo, keys):
    path = repo / "assets/vendor/oci-stencils/stencils.json"
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as fh:
        _json.dump({k: {} for k in keys}, fh)


def test_oci_slug_present_passes(tmp_path):
    repo = tmp_path
    _write_manifest(repo, ["functions"])
    _write(str(repo / "mappings/oci-icons.yaml"), _oci_mapping("functions"))
    refs = check_mapping_stencils(repo / 'mappings', repo)
    assert len(refs) == 1 and refs[0].manifest_exists and refs[0].slug_present
    assert main(["--mappings", str(repo / "mappings"), "--repo-root", str(repo)]) == 0


def test_oci_missing_slug_fails(tmp_path):
    repo = tmp_path
    _write_manifest(repo, ["functions"])
    _write(str(repo / "mappings/oci-icons.yaml"), _oci_mapping("nonexistent-slug"))
    refs = check_mapping_stencils(repo / 'mappings', repo)
    assert refs[0].manifest_exists and not refs[0].slug_present
    assert main(["--mappings", str(repo / "mappings"), "--repo-root", str(repo)]) == 1


def test_oci_absent_manifest_skips(tmp_path):
    repo = tmp_path
    _write(str(repo / "assets/vendor/.keep"), "")
    _write(str(repo / "mappings/oci-icons.yaml"), _oci_mapping("functions"))
    refs = check_mapping_stencils(repo / 'mappings', repo)
    assert refs and refs[0].manifest_exists is False
    assert main(["--mappings", str(repo / "mappings"), "--repo-root", str(repo)]) == 0
