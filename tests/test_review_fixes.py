"""Regression tests for the architecture-review fixes (REVIEW.md).

Covers:
- C1: the terminology source of truth (profiles/terminology.yaml via
  rule_engine.constants) agrees with what the core modules use.
- C3: inventory Snapshot JSON files are discovered and routed through the
  Linter's ``secret-safety`` gate.
- U1/U2: the shared constants are the ones the modules consume.
"""

from __future__ import annotations

import json
import os
import tempfile

from rule_engine import constants as C
from rule_engine import cli
from rule_engine.linter import lint


# --- C1: single terminology source of truth --------------------------------


def test_terminology_covers_all_types_and_providers():
    labels = C.provider_labels()
    assert set(labels) == set(C.NEUTRAL_RESOURCE_TYPES)
    for rtype, per_provider in labels.items():
        assert set(per_provider) == set(C.PROVIDERS), rtype


def test_contract_labels_come_from_terminology_source():
    from rule_engine import contract
    assert contract._PROVIDER_LABELS == C.provider_labels()


def test_normalizer_aliases_come_from_terminology_source():
    from rule_engine import normalizer
    # A few representative native types resolve via the shared aliases.
    assert normalizer.resolve_resource_type("aws_lambda_function", "aws") == "serverless_fn"
    assert normalizer.resolve_resource_type("azurerm_key_vault", "azure") == "secrets_store"
    assert normalizer.resolve_resource_type("google_container_cluster", "gcp") == "managed_k8s"
    assert normalizer.resolve_resource_type("oci_core_vcn", "oci") == "network_boundary"


def test_seed_icons_come_from_terminology_source():
    from rule_engine.assets import enumerate as en
    assert en._SEED == C.seed_icons()
    assert en._SEED["aws"]["serverless_fn"][0] == "mxgraph.aws4.lambda"


# --- U1/U2: shared constants ------------------------------------------------


def test_modules_share_providers_constant():
    from rule_engine import icon_resolver, contract, asset_index
    assert icon_resolver.PROVIDERS is C.PROVIDERS
    assert contract.PROVIDERS is C.PROVIDERS
    assert asset_index.PROVIDERS is C.PROVIDERS


def test_linter_and_normalizer_secret_vocabularies():
    from rule_engine import linter, normalizer
    # Two matching semantics, two vocabularies from one place:
    # - the normalizer matches broad key-name tokens against object keys;
    assert normalizer._SECRET_KEY_SUBSTRINGS is C.SECRET_MARKERS
    assert "password" in normalizer._SECRET_KEY_SUBSTRINGS
    # - the linter scans raw content with the narrow value-oriented list.
    assert linter._SECRET_MARKERS is C.SECRET_CONTENT_MARKERS
    # The narrow content list must exclude broad single-word tokens that occur
    # in ordinary metadata (else secret-free snapshots would be blocked).
    for broad in ("secret", "token", "credential", "access_key", "apikey"):
        assert broad not in C.SECRET_CONTENT_MARKERS


# --- C3: snapshot JSON discovery + secret-safety ----------------------------


def test_snapshot_json_discovered_and_secret_scanned():
    with tempfile.TemporaryDirectory() as d:
        snap_dir = os.path.join(d, "inventory-aws-123-us-east-1-2026-01-01_0000")
        os.makedirs(snap_dir)
        clean = os.path.join(snap_dir, "storage.json")
        with open(clean, "w", encoding="utf-8") as fh:
            json.dump([{"resource_type": "object_store", "provider": "aws", "name": "b"}], fh)
        leaky = os.path.join(snap_dir, "secrets.json")
        with open(leaky, "w", encoding="utf-8") as fh:
            json.dump([{"resource_type": "secrets_store", "provider": "aws",
                        "aws_secret_access_key": "AKIAEXAMPLESECRET"}], fh)

        found = cli.discover_artifacts(d)
        assert clean in found and leaky in found

        clean_art = cli.parse_artifact(clean)
        assert clean_art.kind == "snapshot"
        assert lint(clean_art)["eligible_for_publication"] is True

        leaky_art = cli.parse_artifact(leaky)
        result = lint(leaky_art)
        rules = {f["rule"] for f in result["findings"]}
        assert "secret-safety" in rules
        assert result["eligible_for_publication"] is False


def test_json_schema_file_is_not_treated_as_snapshot():
    # A JSON file with no resource_type/provider and not under inventory-* is
    # not a snapshot.
    with tempfile.TemporaryDirectory() as d:
        cfg = os.path.join(d, "config.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"$schema": "x", "title": "y"}, fh)
        assert cli.discover_artifacts(d) == []


# --- D1: accessibility / minimum font size ---------------------------------


def test_min_font_size_rule_fires_below_floor():
    from rule_engine.linter import Artifact, lint, RULE_MIN_FONT_SIZE
    below = Artifact(kind="diagram", font_sizes=[12, 11, 16])
    result = lint(below)
    rules = {f["rule"] for f in result["findings"]}
    assert RULE_MIN_FONT_SIZE in rules
    # Advisory (WARNING) — must not block publication on its own.
    assert result["eligible_for_publication"] is True


def test_min_font_size_passes_at_floor_and_skips_when_empty():
    from rule_engine.linter import Artifact, lint, RULE_MIN_FONT_SIZE
    ok = Artifact(kind="diagram", font_sizes=[12, 12, 16])
    empty = Artifact(kind="diagram")  # not parsed -> rule skipped
    for art in (ok, empty):
        rules = {f["rule"] for f in lint(art)["findings"]}
        assert RULE_MIN_FONT_SIZE not in rules


def test_golden_examples_carry_no_sub_12px_text():
    import glob
    from rule_engine import cli as _cli
    from rule_engine.linter import lint, RULE_MIN_FONT_SIZE
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    drawios = glob.glob(os.path.join(here, "examples", "**", "*.drawio"), recursive=True)
    assert drawios, "no golden .drawio examples found"
    for path in drawios:
        art = _cli.parse_artifact(path)
        rules = {f["rule"] for f in lint(art)["findings"]}
        assert RULE_MIN_FONT_SIZE not in rules, f"{path} has sub-12px text"


# --- D2/D3/D6: geometry-aware layout rules ---------------------------------


def test_golden_examples_pass_all_geometry_rules():
    """The four golden .drawio examples must be clean under every geometry rule
    (no false positives) — grid-alignment, container-padding, edge-routing,
    node-overlap."""
    from rule_engine import cli as _cli
    from rule_engine.linter import (
        lint, RULE_GRID_ALIGNMENT, RULE_CONTAINER_PADDING,
        RULE_EDGE_ROUTING, RULE_NODE_OVERLAP,
    )
    geo_rules = {RULE_GRID_ALIGNMENT, RULE_CONTAINER_PADDING,
                 RULE_EDGE_ROUTING, RULE_NODE_OVERLAP}
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Use the CLI discovery so scratch/copy files (… копія.drawio, … - Copy.drawio)
    # are excluded exactly as the --all scan and golden-example tests exclude them.
    drawios = [
        a for a in _cli.discover_artifacts(here)
        if a.endswith(".drawio") and (os.sep + "examples" + os.sep) in a
    ]
    assert drawios
    for path in drawios:
        art = _cli.parse_artifact(path)
        assert art.geometry is not None, path
        fired = {f["rule"] for f in lint(art)["findings"]} & geo_rules
        assert not fired, f"{path} unexpectedly fired {fired}"


def test_geometry_grid_alignment_fires_off_grid():
    from rule_engine import geometry as g
    geo = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="n1" vertex="1" parent="1" style="shape=x" value="A">'
        '<mxGeometry x="43" y="55" width="78" height="78"/></mxCell>'
        '</root></mxGraphModel>'
    )
    assert g.check_grid_alignment(geo) == ["n1"]


def test_geometry_node_overlap_fires():
    from rule_engine import geometry as g
    geo = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="a" vertex="1" parent="1" style="shape=x" value="A">'
        '<mxGeometry x="100" y="100" width="78" height="78"/></mxCell>'
        '<mxCell id="b" vertex="1" parent="1" style="shape=x" value="B">'
        '<mxGeometry x="120" y="120" width="78" height="78"/></mxCell>'
        '</root></mxGraphModel>'
    )
    assert ("a", "b") in g.check_node_overlap(geo)


def test_geometry_edge_routing_flags_nonorthogonal_and_straight_through():
    from rule_engine import geometry as g
    non_ortho = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="b" style="html=1">'
        '<mxGeometry/></mxCell>'
        '<mxCell id="a" vertex="1" parent="1" style="shape=x"><mxGeometry x="0" y="0" width="78" height="78"/></mxCell>'
        '<mxCell id="b" vertex="1" parent="1" style="shape=x"><mxGeometry x="300" y="0" width="78" height="78"/></mxCell>'
        '</root></mxGraphModel>'
    )
    assert any(r == "not-orthogonal" for _, r in g.check_edge_routing(non_ortho))

    through = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="c" '
        'style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5"><mxGeometry/></mxCell>'
        '<mxCell id="a" vertex="1" parent="1" style="shape=x"><mxGeometry x="0" y="0" width="78" height="78"/></mxCell>'
        '<mxCell id="b" vertex="1" parent="1" style="shape=x"><mxGeometry x="150" y="0" width="78" height="78"/></mxCell>'
        '<mxCell id="c" vertex="1" parent="1" style="shape=x"><mxGeometry x="300" y="0" width="78" height="78"/></mxCell>'
        '</root></mxGraphModel>'
    )
    assert any(r.startswith("straight-through") for _, r in g.check_edge_routing(through))


def test_geometry_edge_with_waypoints_not_flagged():
    """A waypoint-carrying orthogonal edge is deliberate routing — not flagged
    on the crossing criterion (guards the GCP/OCI golden e5 case)."""
    from rule_engine import geometry as g
    geo = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="c" '
        'style="edgeStyle=orthogonalEdgeStyle;exitX=0.25;exitY=1;entryX=0;entryY=0.5">'
        '<mxGeometry relative="1" as="geometry"><Array as="points">'
        '<mxPoint x="40" y="200"/></Array></mxGeometry></mxCell>'
        '<mxCell id="a" vertex="1" parent="1" style="shape=x"><mxGeometry x="0" y="0" width="78" height="78"/></mxCell>'
        '<mxCell id="b" vertex="1" parent="1" style="shape=x"><mxGeometry x="0" y="150" width="78" height="78"/></mxCell>'
        '<mxCell id="c" vertex="1" parent="1" style="shape=x"><mxGeometry x="0" y="300" width="78" height="78"/></mxCell>'
        '</root></mxGraphModel>'
    )
    assert g.check_edge_routing(geo) == []


def test_geometry_container_padding_fires_when_flush():
    from rule_engine import geometry as g
    geo = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="boundary-x" vertex="1" parent="1" '
        'style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc">'
        '<mxGeometry x="0" y="0" width="200" height="200"/></mxCell>'
        '<mxCell id="n" vertex="1" parent="1" style="shape=x">'
        '<mxGeometry x="2" y="2" width="78" height="78"/></mxCell>'
        '</root></mxGraphModel>'
    )
    viol = g.check_container_padding(geo)
    assert any(ncid == "n" for ncid, _, _ in viol)


# --- D5: arrow / line style ------------------------------------------------


def test_golden_examples_pass_arrow_style():
    import glob
    from rule_engine import cli as _cli
    from rule_engine.linter import lint, RULE_ARROW_STYLE
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in glob.glob(os.path.join(here, "examples", "**", "*.drawio"), recursive=True):
        art = _cli.parse_artifact(path)
        rules = {f["rule"] for f in lint(art)["findings"]}
        assert RULE_ARROW_STYLE not in rules, f"{path} tripped arrow-style"


def test_arrow_style_flags_filled_head_thin_stroke_and_unspecified():
    from rule_engine import geometry as g
    filled = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="b" '
        'style="edgeStyle=orthogonalEdgeStyle;endArrow=block;strokeWidth=1.5"><mxGeometry/></mxCell>'
        '<mxCell id="a" vertex="1" parent="1" style="s"><mxGeometry x="0" y="0" width="78" height="78"/></mxCell>'
        '<mxCell id="b" vertex="1" parent="1" style="s"><mxGeometry x="300" y="0" width="78" height="78"/></mxCell>'
        '</root></mxGraphModel>'
    )
    assert any(r.startswith("filled-arrowhead") for _, r in g.check_arrow_style(filled))

    thin = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="b" '
        'style="endArrow=open;endFill=0;strokeWidth=0.5"><mxGeometry/></mxCell></root></mxGraphModel>'
    )
    assert any(r.startswith("stroke-width") for _, r in g.check_arrow_style(thin))

    unspec = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="b" '
        'style="edgeStyle=orthogonalEdgeStyle"><mxGeometry/></mxCell></root></mxGraphModel>'
    )
    assert any("unspecified" in r for _, r in g.check_arrow_style(unspec))


def test_open_arrowhead_is_clean():
    from rule_engine import geometry as g
    ok = g.build_geometry(
        '<mxGraphModel><root><mxCell id="1"/>'
        '<mxCell id="e" edge="1" parent="1" source="a" target="b" '
        'style="edgeStyle=orthogonalEdgeStyle;endArrow=open;endFill=0;strokeWidth=1.5"><mxGeometry/></mxCell>'
        '</root></mxGraphModel>'
    )
    assert g.check_arrow_style(ok) == []


# --- C3 refinement: metadata-only snapshot must NOT trip secret-safety -------


def test_metadata_only_secrets_store_snapshot_is_clean():
    """A secret-FREE snapshot that merely enumerates a secrets store, with a
    non-secret identifier field (access_key_id), must be publishable — the raw
    content scan uses the narrow value vocabulary, not broad key-name tokens."""
    with tempfile.TemporaryDirectory() as d:
        snap = os.path.join(d, "inventory-aws-1-us-east-1-2026-01-01_0000")
        os.makedirs(snap)
        f = os.path.join(snap, "secrets.json")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(
                [{
                    "resource_type": "secrets_store",
                    "provider": "aws",
                    "native_type": "secrets_manager",
                    "name": "app-secrets",
                    "config": {"access_key_id": "AKIAEXAMPLEIDENTIFIER"},
                    "tags": {"team": "token-service"},
                }],
                fh,
            )
        result = lint(cli.parse_artifact(f))
        rules = {r["rule"] for r in result["findings"]}
        assert "secret-safety" not in rules
        assert result["eligible_for_publication"] is True


def test_real_secret_values_still_trip_secret_safety():
    """SecureString / PEM / aws_secret_access_key values remain CRITICAL."""
    for payload in (
        {"securestring": "p@ssw0rd"},
        {"key": "-----BEGIN RSA PRIVATE KEY-----abc"},
        {"aws_secret_access_key": "wJalrXUtnFEMIexampleKEY"},
    ):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "inventory-x", "s.json")
            os.makedirs(os.path.dirname(f))
            with open(f, "w", encoding="utf-8") as fh:
                json.dump([{"resource_type": "secrets_store", **payload}], fh)
            result = lint(cli.parse_artifact(f))
            rules = {r["rule"] for r in result["findings"]}
            assert "secret-safety" in rules, payload
            assert result["eligible_for_publication"] is False
