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


def test_linter_and_normalizer_share_secret_vocabulary():
    from rule_engine import linter, normalizer
    # The linter's content markers are exactly the shared vocabulary.
    assert linter._SECRET_MARKERS is C.SECRET_MARKERS
    # The normalizer's key-drop list is the shared vocabulary minus the PEM
    # content marker.
    assert set(normalizer._SECRET_KEY_SUBSTRINGS) <= set(C.SECRET_MARKERS)
    assert "password" in normalizer._SECRET_KEY_SUBSTRINGS


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
