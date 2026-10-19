"""WS9 (1.10.12): one merged mapping tree + bundled education/organizations roles.

SEP feedback §4.1: ``resolve_icon``, ``build_icon_index`` and
``check-asset-paths`` read three different mapping trees, so a workspace role
either rendered without being path-checked or was path-checked without ever
rendering. These tests pin the single tree (bundled mappings + every
``mappings/local/`` overlay, ``roles.yaml`` included), the no-effect-edit
warning, the engine-bundled education asset, MIME sniffing in the inliners,
and the asar-manifest-only acceptance of built-in stencils under
``verify-icon --strict``.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
import yaml

from rule_engine import asset_index, asset_paths_guard, icon_resolver, mapping_tree
from rule_engine import diagram_layout, export_raster
from rule_engine.drawio_model import parse_drawio
from rule_engine.engine_assets import bundled_path, locate_asset, sniff_mime
from rule_engine.icon_refs import (
    RESOLVED,
    UNVERIFIED,
    IconSources,
    extract_refs,
    resolve,
)
from rule_engine.verify_icon import _exit_code_for, verify_drawio

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
    elif isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A bootstrapped workspace as the CWD, with an empty mappings/local/."""
    (tmp_path / "mappings" / "local").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    icon_resolver._load_mapping_cached.cache_clear()
    yield tmp_path
    icon_resolver._load_mapping_cached.cache_clear()


# --------------------------------------------------------------------------- #
# The merged tree
# --------------------------------------------------------------------------- #


def test_roles_overlay_reaches_the_icon_index(workspace):
    """A role in mappings/local/roles.yaml lands in build_icon_index's roles layer."""
    _write(workspace / "mappings" / "local" / "roles.yaml",
           {"roles": {"lms_custom": {"asset": "assets/vendor/education/mortarboard.svg"}}})
    payload = asset_index.build_icon_index({})
    assert "lms_custom" in payload["roles"]
    assert payload["roles"]["lms_custom"]["aws"]["source"] == "bundled"
    # bundled roles are still there (per-role merge, not replacement)
    assert "object_store" in payload["roles"]


def test_overlays_merge_in_order_and_dedupe(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    _write(bundled / "roles.yaml", {"roles": {"a": {"aws": "A"}, "b": {"aws": "B"}}})
    _write(bundled / "local" / "roles.yaml", {"roles": {"b": {"aws": "B1"}}})
    ws = tmp_path / "ws"
    _write(ws / "mappings" / "local" / "roles.yaml", {"roles": {"b": {"aws": "B2"}, "c": {"aws": "C"}}})
    monkeypatch.chdir(ws)
    roles = mapping_tree.load_roles(bundled)["roles"]
    assert roles == {"a": {"aws": "A"}, "b": {"aws": "B2"}, "c": {"aws": "C"}}
    # run from the bundled tree's own root: its overlay applies once
    monkeypatch.chdir(tmp_path)
    assert len(mapping_tree.overlay_dirs(bundled)) == 1


def test_workspace_overlay_resolves_and_is_path_checked(workspace):
    """One overlay entry is seen by resolve_icon AND by the asset-path guard."""
    _write(workspace / "mappings" / "local" / "aws-icons.yaml", {"resources": {"ws_role": {
        "brand_hex": "#E7157B",
        "style": "image;html=1;image=assets/vendor/aws-icons/missing/Ws_48.svg",
    }}})
    assert "Ws_48.svg" in icon_resolver.resolve_icon("ws_role", "aws")["style_string"]
    refs = asset_paths_guard.check_mapping_assets(mapping_tree.bundled_dir(), workspace)
    hit = [r for r in refs if r.resource == "ws_role"]
    assert hit and hit[0].mapping == "aws-icons.yaml" and not hit[0].exists


def test_no_effect_edits_name_ignored_workspace_entries(tmp_path):
    bundled = tmp_path / "bundled"
    _write(bundled / "aws-icons.yaml", {"resources": {"lambda": {"style": "s"}}})
    _write(bundled / "roles.yaml", {"roles": {"lambda": {"aws": "Lambda"}}})
    ws = tmp_path / "ws" / "mappings"
    _write(ws / "aws-icons.yaml", {"resources": {
        "lambda": {"style": "s"},          # identical -> silent
        "license_manager": {"style": "x"},  # absent -> warned
    }})
    _write(ws / "roles.yaml", {"roles": {"lambda": {"aws": "Other"}}})  # differs
    warnings = mapping_tree.no_effect_edits(ws, bundled)
    assert len(warnings) == 2
    assert any("resources.license_manager" in w and "mappings/local/aws-icons.yaml" in w
               for w in warnings)
    assert any("roles.lambda" in w for w in warnings)
    # once the overlay carries the role, the workspace edit is no longer dead
    _write(bundled / "local" / "aws-icons.yaml",
           {"resources": {"license_manager": {"style": "x"}}})
    assert not any("license_manager" in w for w in mapping_tree.no_effect_edits(ws, bundled))
    # the bundled tree itself is never "a workspace edit"
    assert mapping_tree.no_effect_edits(bundled, bundled) == []


def test_build_icon_sets_check_warns_on_no_effect_edit(workspace, capsys):
    from rule_engine import build_icon_sets_cli

    _write(workspace / "mappings" / "aws-icons.yaml",
           {"resources": {"dead_role": {"style": "image;html=1", "brand_hex": "#000000"}}})
    rc = build_icon_sets_cli.main(["--check", "--allow-missing",
                                   "--asset-root", str(workspace / "nope")])
    assert rc == 0
    assert "resources.dead_role" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Bundled roles: education + organizations
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci", "generic", "kubernetes"])
def test_education_resolves_on_every_profile_to_the_bundled_asset(provider):
    icon_resolver._load_mapping_cached.cache_clear()
    style = icon_resolver.resolve_icon("education", provider)["style_string"]
    assert "image=assets/vendor/education/mortarboard.svg" in style
    asset = bundled_path("assets/vendor/education/mortarboard.svg")
    assert asset is not None and asset.read_bytes().lstrip().startswith(b"<svg")
    assert b"CC0" in asset.read_bytes()


def test_organizations_role_is_the_org_service_not_the_account_glyph():
    icon_resolver._load_mapping_cached.cache_clear()
    org = icon_resolver.resolve_icon("organizations", "aws")["style_string"]
    acct = icon_resolver.resolve_icon("peer_account", "aws")["style_string"]
    assert org.endswith("Arch_Management-Tools/48/Arch_AWS-Organizations_48.svg")
    assert org != acct


def test_committed_index_carries_both_roles():
    import json

    idx = json.loads((mapping_tree.bundled_dir() / "icon-index.json").read_text(encoding="utf-8"))
    edu = idx["roles"]["education"]
    assert {e["source"] for e in edu.values()} == {"bundled"}
    assert "Arch_AWS-Organizations" in idx["roles"]["organizations"]["aws"]["ref"]


def test_locate_asset_prefers_workspace_then_bundled(tmp_path):
    rel = "assets/vendor/education/mortarboard.svg"
    assert locate_asset(rel, tmp_path) == bundled_path(rel)
    own = _write(tmp_path / rel, b"<svg>mine</svg>")
    assert locate_asset(rel, tmp_path) == own
    assert locate_asset("assets/vendor/education/../../x.svg", tmp_path / "none") is None
    assert locate_asset("assets/vendor/aws-icons/none.svg", tmp_path) is None


def test_guard_counts_bundled_education_asset_as_present(tmp_path):
    mappings = tmp_path / "mappings"
    _write(mappings / "generic-icons.yaml", {"resources": {"education": {
        "style": "image;html=1;image=assets/vendor/education/mortarboard.svg"}}})
    (tmp_path / "assets" / "vendor").mkdir(parents=True)
    refs = asset_paths_guard.check_mapping_assets(mappings, tmp_path, overlays=[])
    assert [r.exists for r in refs] == [True]


# --------------------------------------------------------------------------- #
# MIME sniffing in both inliners
# --------------------------------------------------------------------------- #


def test_sniff_mime_reads_content_before_suffix():
    assert sniff_mime(_PNG, "logo.svg") == "image/png"
    assert sniff_mime(b"<svg xmlns='x'/>", "logo.png") == "image/svg+xml"
    assert sniff_mime(b"<?xml version='1.0'?><svg/>", "a") == "image/svg+xml"
    assert sniff_mime(b"\xff\xd8\xff\xe0", "a") == "image/jpeg"
    assert sniff_mime(b"", "a.png") == "image/png"


def test_builder_embed_uses_png_mime_for_png_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "assets/vendor/brand/logo.svg", _PNG)  # a PNG under an .svg name
    value, ref = diagram_layout._embed_asset_image("assets/vendor/brand/logo.svg")
    assert ref == "assets/vendor/brand/logo.svg"
    assert value == "data:image/png," + base64.b64encode(_PNG).decode("ascii")


def test_builder_embeds_bundled_education_svg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no workspace copy
    value, ref = diagram_layout._embed_asset_image("assets/vendor/education/mortarboard.svg")
    assert ref == "assets/vendor/education/mortarboard.svg"
    assert value.startswith("data:image/svg+xml,")


def test_exporter_inliner_sniffs_png_and_finds_bundled_assets(tmp_path):
    _write(tmp_path / "assets/vendor/brand/logo.svg", _PNG)
    text = ('style="image=assets/vendor/brand/logo.svg;"'
            ' style2="image=assets/vendor/education/mortarboard.svg;"')
    out = export_raster.inline_local_images(text, repo_root=tmp_path)
    assert "image=data:image/png," in out
    assert "image=data:image/svg+xml," in out
    assert export_raster.missing_assets(text, repo_root=tmp_path) == []


# --------------------------------------------------------------------------- #
# verify-icon --strict: built-in stencils only from the asar-extracted manifest
# --------------------------------------------------------------------------- #

_PAGE = """<mxfile><diagram id="d" name="p"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="n1" value="LMS" style="{style}" vertex="1" parent="1">
<mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def _sources(stencils):
    return IconSources(aws4=None, azure2=None, oci_digests=None, oci_stencils=None,
                       drawio_stencils=stencils)


def _ref(style: str):
    (page,) = parse_drawio(_PAGE.format(style=style).encode(), path="p.drawio")
    return extract_refs(page)["n1"]


def test_builtin_stencil_resolves_only_from_the_manifest():
    (ref,) = _ref("shape=mxgraph.ios7.icons.book;html=1;")
    assert ref.kind == "builtin-stencil"
    assert resolve(ref, _sources(frozenset({"mxgraph.ios7.icons.book"})))[0] == RESOLVED
    assert resolve(ref, _sources(frozenset({"mxgraph.ios7.icons.box"})))[0] == UNVERIFIED
    assert resolve(ref, _sources(None))[0] == UNVERIFIED


def test_neutral_family_stays_a_generic_shape_ref():
    (ref,) = _ref("shape=mxgraph.flowchart.process;html=1;")
    assert ref.kind == "generic-shape"


def test_verify_strict_passes_a_manifest_stencil_and_fails_an_unknown_one(tmp_path):
    import json

    ws = tmp_path
    _write(ws / "mappings" / "drawio-stencils.json",
           json.dumps({"ids": ["mxgraph.ios7.icons.book"]}))
    good = _write(ws / "good.drawio", _PAGE.format(style="shape=mxgraph.ios7.icons.book;"))
    bad = _write(ws / "bad.drawio", _PAGE.format(style="shape=mxgraph.ios7.icons.bookz;"))
    rg = verify_drawio(str(good), str(ws))
    rb = verify_drawio(str(bad), str(ws))
    assert rg["resolved"] == 1 and _exit_code_for(rg, strict=True) == 0
    assert rb["unverified"] == 1 and _exit_code_for(rb, strict=True) == 1
    assert _exit_code_for(rb, strict=False) == 0
    assert "drawio-stencils.json" in rb["references"][0]["detail"]


def test_committed_stencil_manifest_is_asar_extracted():
    import json

    data = json.loads((mapping_tree.bundled_dir() / "drawio-stencils.json").read_text(encoding="utf-8"))
    assert data["source"] == "draw.io app.asar"
    ids = set(data["ids"])
    assert "mxgraph.ios7.icons.book" in ids
    assert "mxgraph.ios7.icons" not in ids  # a library name, not a shape
