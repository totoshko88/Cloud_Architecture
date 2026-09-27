"""Tests for the ``rule-engine-draw`` command front-end (Part J, task 8).

Feature: provider-diagram-conventions (release 1.10.0), Part J, task 8 — the
``rule-engine-draw`` autogenerator *command* (:mod:`rule_engine.draw_cli`). Where
task 7 built the Snapshot→``DiagramSpec`` translator, this task hands that spec
to the existing ``layout()`` + ``build_diagram()`` pipeline, skins each node
through the committed mappings, writes a companion ``.diagram.md``, and
best-effort exports the raster.

These tests assert the design's J6 contract (Requirement 10.1, 10.8, 10.9):

* the command writes the ``.drawio`` and the companion (the raster is
  best-effort, so a missing draw.io CLI never blocks the pair);
* the companion satisfies the full ``kb-frontmatter.md`` document contract
  (twelve required keys + the four required sections), and a ``landscape`` is
  never ``orphan-landscape`` (it always carries a ``summary_of``);
* the produced triple is publication-eligible (zero CRITICAL / zero ERROR);
* generation is deterministic: two runs produce byte-identical ``.drawio`` and
  companion (Requirement 10.6);
* an over-budget ``landscape`` (> 50 role-bearing) is reported as split with a
  non-zero exit and no files written;
* ``rule-engine-draw`` is a packaged console script (Requirement 10.9).

**Validates: Requirements 10.1, 10.8, 10.9**
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from rule_engine.draw_cli import (
    build_companion,
    build_drawio,
    generate,
    main,
)
from rule_engine.kb_validator import validate_document

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The committed golden AWS example Snapshot (6 role-bearing resources).
_AWS_SNAPSHOT = (
    _REPO_ROOT
    / "examples"
    / "aws"
    / "inventory-aws-123456789012-us-east-1-2026-09-22_1430"
)


def _write_snapshot(root: Path, provider: str, boundary_id: str, region: str,
                    domains: dict) -> Path:
    folder = root / f"inventory-{provider}-{boundary_id}-{region}-2026-09-22_1430"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = (
        "---\nid: m\ntitle: t\n---\n\n# M\n\n"
        "| Field | Value |\n| --- | --- |\n"
        f"| provider | {provider} |\n"
        f"| boundary_id | {boundary_id} |\n"
        f"| region_set | {region} |\n"
    )
    (folder / "00-MANIFEST.md").write_text(manifest, encoding="utf-8")
    for domain, resources in domains.items():
        (folder / f"{domain}.json").write_text(
            json.dumps({"service": domain, "resources": resources}, sort_keys=True),
            encoding="utf-8",
        )
    return folder


def _resource(rt: str, rid: str, name: str) -> dict:
    return {"provider": "aws", "resource_type": rt, "id": rid, "name": name}


def _lint(drawio_path: Path) -> dict:
    """Lint one .drawio via the CLI JSON output; return the single artifact dict."""
    from rule_engine import cli

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(["--file", str(drawio_path), "--json"])
    data = json.loads(buf.getvalue())
    return data[0] if isinstance(data, list) else data


# --------------------------------------------------------------------------- #
# The triple is written (Requirement 10.1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("diagram_type", ["simple", "summary", "landscape"])
def test_generate_writes_drawio_and_companion(tmp_path, diagram_type):
    stem = tmp_path / f"10-{diagram_type}"
    result = generate(_AWS_SNAPSHOT, "aws", diagram_type, stem, export=False)

    drawio = Path(result["drawio"])
    companion = Path(result["companion"])
    assert drawio.is_file() and drawio.name == f"10-{diagram_type}.drawio"
    assert companion.is_file() and companion.name == f"10-{diagram_type}.diagram.md"
    # A valid .drawio and a non-empty companion.
    assert drawio.read_text(encoding="utf-8").startswith("<mxfile")
    assert companion.read_text(encoding="utf-8").startswith("---\n")


# --------------------------------------------------------------------------- #
# Companion satisfies the kb-frontmatter contract (Requirement 10.8)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("diagram_type", ["simple", "summary", "landscape"])
def test_companion_satisfies_kb_document_contract(diagram_type):
    text = build_companion("aws", diagram_type, f"10-{diagram_type}",
                           paired_basename=f"20-{diagram_type}")
    violations = validate_document(text)
    assert violations == [], [ (v.rule, v.message) for v in violations ]


def test_companion_has_the_twelve_required_keys():
    text = build_companion("aws", "landscape", "10-landscape")
    for key in (
        "id:", "title:", "kb_namespace:", "section:", "category:", "status:",
        "updated:", "owner:", "author:", "next_review_date:", "tags:",
        "related_docs:",
    ):
        assert key in text, f"missing required frontmatter key {key!r}"


def test_landscape_companion_carries_summary_of():
    # A landscape must cross-link a flow summary or it is orphan-landscape.
    # Standalone (no explicit pair): a summary_of is derived so it is not orphan.
    text = build_companion("aws", "landscape", "10-aws-landscape")
    assert "summary_of: 10-aws-summary" in text


def test_summary_companion_carries_detailed_view_when_paired():
    text = build_companion("aws", "summary", "10-aws-summary",
                           paired_basename="10-aws-landscape")
    assert "detailed_view: 10-aws-landscape" in text


def test_diagram_class_matches_the_type():
    assert "diagram_class: flow" in build_companion("aws", "simple", "s")
    assert "diagram_class: flow" in build_companion("aws", "summary", "s")
    assert "diagram_class: landscape" in build_companion("aws", "landscape", "l")


# --------------------------------------------------------------------------- #
# Publication eligibility of the produced triple (Requirement 10.7 / 11.4)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("diagram_type", ["simple", "summary", "landscape"])
def test_generated_diagram_is_publication_eligible(tmp_path, diagram_type):
    stem = tmp_path / f"10-{diagram_type}"
    result = generate(_AWS_SNAPSHOT, "aws", diagram_type, stem, export=False)
    report = _lint(Path(result["drawio"]))
    assert report["eligible_for_publication"] is True, report.get("findings")
    # No CRITICAL/ERROR finding; node-connectivity WARNING is expected (no
    # relationships fully connect the nodes) and does not block publication.
    blocking = [
        f for f in report.get("findings", [])
        if f.get("severity") in ("CRITICAL", "ERROR")
    ]
    assert blocking == [], blocking


# --------------------------------------------------------------------------- #
# Determinism (Requirement 10.6)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("diagram_type", ["simple", "summary", "landscape"])
def test_drawio_and_companion_are_byte_identical_across_runs(diagram_type):
    a = build_drawio(_AWS_SNAPSHOT, "aws", diagram_type, f"10-{diagram_type}")
    b = build_drawio(_AWS_SNAPSHOT, "aws", diagram_type, f"10-{diagram_type}")
    assert a == b
    ca = build_companion("aws", diagram_type, f"10-{diagram_type}")
    cb = build_companion("aws", diagram_type, f"10-{diagram_type}")
    assert ca == cb


# --------------------------------------------------------------------------- #
# Relationships become edges (Requirement 10.5)
# --------------------------------------------------------------------------- #


def _first_two_node_ids() -> List[str]:
    from rule_engine.draw import spec_from_snapshot

    spec = spec_from_snapshot(_AWS_SNAPSHOT, "aws", "landscape")
    ids = [n.id for n in spec.nodes]
    return ids[:2]


def test_supplied_relationships_are_drawn(tmp_path):
    a, b = _first_two_node_ids()
    rels = [{"source": a, "target": b, "label": "invokes"}]
    stem = tmp_path / "10-landscape"
    result = generate(_AWS_SNAPSHOT, "aws", "landscape", stem, relationships=rels,
                      export=False)
    text = Path(result["drawio"]).read_text(encoding="utf-8")
    # The edge label appears on the drawn edge.
    assert "invokes" in text
    # Still publication-eligible.
    assert _lint(Path(result["drawio"]))["eligible_for_publication"] is True


def test_no_relationships_draws_no_edges(tmp_path):
    stem = tmp_path / "10-landscape"
    result = generate(_AWS_SNAPSHOT, "aws", "landscape", stem, export=False)
    text = Path(result["drawio"]).read_text(encoding="utf-8")
    # No edge cells (an edge cell is an mxCell with edge="1").
    assert 'edge="1"' not in text


# --------------------------------------------------------------------------- #
# Over-budget landscape is reported as split, no files written (Requirement 10.7)
# --------------------------------------------------------------------------- #


def test_over_budget_landscape_exits_nonzero_and_writes_nothing(tmp_path):
    resources = [
        _resource("object_store", f"arn:aws:s3:::bucket-{i:03d}", f"bucket-{i:03d}")
        for i in range(60)
    ]
    folder = _write_snapshot(tmp_path, "aws", "444455556666", "us-east-1",
                             {"storage": resources})
    stem = tmp_path / "out" / "10-landscape"
    rc = main([
        "--snapshot", str(folder), "--provider", "aws",
        "--type", "landscape", "--out", str(stem), "--no-export",
    ])
    assert rc == 2
    assert not stem.with_name("10-landscape.drawio").exists()
    assert not stem.with_name("10-landscape.diagram.md").exists()


# --------------------------------------------------------------------------- #
# CLI main() end-to-end (Requirement 10.1)
# --------------------------------------------------------------------------- #


def test_main_writes_the_pair_and_exits_zero(tmp_path):
    stem = tmp_path / "10-landscape"
    rc = main([
        "--snapshot", str(_AWS_SNAPSHOT), "--provider", "aws",
        "--type", "landscape", "--out", str(stem), "--no-export",
    ])
    assert rc == 0
    assert stem.with_name("10-landscape.drawio").is_file()
    assert stem.with_name("10-landscape.diagram.md").is_file()


def test_main_rejects_unknown_provider(tmp_path):
    stem = tmp_path / "x"
    with pytest.raises(SystemExit):
        main([
            "--snapshot", str(_AWS_SNAPSHOT), "--provider", "nope",
            "--type", "simple", "--out", str(stem),
        ])


def test_main_loads_a_relationships_file(tmp_path):
    a, b = _first_two_node_ids()
    rels = [{"source": a, "target": b, "label": "invokes"}]
    rels_file = tmp_path / "rels.json"
    rels_file.write_text(json.dumps(rels), encoding="utf-8")
    stem = tmp_path / "10-landscape"
    rc = main([
        "--snapshot", str(_AWS_SNAPSHOT), "--provider", "aws",
        "--type", "landscape", "--out", str(stem),
        "--relationships", str(rels_file), "--no-export",
    ])
    assert rc == 0
    assert "invokes" in stem.with_name("10-landscape.drawio").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Best-effort raster export (Requirement 10.9) — a missing CLI is not fatal
# --------------------------------------------------------------------------- #


def test_raster_export_is_best_effort_when_drawio_is_absent(tmp_path):
    # Point --drawio at a CLI that does not exist; the .drawio + companion must
    # still be written and the command still succeeds.
    stem = tmp_path / "10-landscape"
    result = generate(
        _AWS_SNAPSHOT, "aws", "landscape", stem,
        export=True, drawio="definitely-not-a-real-drawio-cli",
    )
    assert Path(result["drawio"]).is_file()
    assert Path(result["companion"]).is_file()
    assert result["raster"] is None
    assert result["raster_error"] is not None


# --------------------------------------------------------------------------- #
# Packaged console script (Requirement 10.9)
# --------------------------------------------------------------------------- #


def test_rule_engine_draw_is_a_registered_console_script():
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'rule-engine-draw = "rule_engine.draw_cli:main"' in pyproject
