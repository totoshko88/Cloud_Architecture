"""Example (unit) tests for Lint_CLI artifact discovery and routing (task 9.6).

These cover the discovery contract of ``design.md`` §2 (the Discovery table) and
decision D5 (``inventory-*/00-MANIFEST.md`` is exempt from the KB rule):

* Steering files, ``SKILL.md`` and README are *not* KB documents.
* ``inventory-*/00-MANIFEST.md`` is exempt from the KB rule, but a manifest
  *outside* a snapshot folder (``examples/azure/00-MANIFEST.md``) and companion
  documents *are* KB documents.
* ``.md``, ``.yaml``, ``.txt`` and ``.csv`` files inside an ``inventory-*``
  folder are snapshot artifacts; a binary file there produces ``parse-error``
  (``not-text``).
* ``.puml`` / ``.mmd`` files are discovered by the ``--all`` walk and routed to
  a diagram artifact with ``source_format`` set.

_Requirements: R2.8, R3.5, R10.3_
"""

from __future__ import annotations

import os

from rule_engine.cli import (
    _in_inventory_folder,
    _is_kb_document,
    _is_snapshot_manifest,
    discover_artifacts,
    parse_artifacts,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_bytes(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# A snapshot folder name per inventory-standards §3:
# inventory-<provider>-<boundary>-<region>-<YYYY-MM-DD_HHMM>
_SNAP = "inventory-aws-123456789012-us-east-1-2025-01-15_1430"


# --- KB-document classification (R2.8, D5) --------------------------------- #


def test_steering_skill_and_readme_are_not_kb_documents():
    # Steering files are rule sources (a power ships them under dev.kiro/steering,
    # which the --all walk does descend into), SKILL.md is an agent manifest, and
    # README is a hand-authored repo doc. None is a generated KB document.
    assert _is_kb_document(".kiro/steering/diagram-standards.md") is False
    assert (
        _is_kb_document("powers/p/dev.kiro/steering/diagram-lint.md") is False
    )
    assert _is_kb_document(".kiro/skills/rule-engine-artifacts/SKILL.md") is False
    assert _is_kb_document("README.md") is False
    assert _is_kb_document("examples/aws/README.md") is False


def test_snapshot_manifest_is_exempt_from_kb_rule():
    manifest = os.path.join("out", _SNAP, "00-MANIFEST.md")
    # It lives inside a snapshot folder, so it is a snapshot manifest ...
    assert _is_snapshot_manifest(manifest) is True
    assert _in_inventory_folder(manifest) is True
    # ... and therefore NOT a KB document (D5: owned by snapshot_gate).
    assert _is_kb_document(manifest) is False


def test_manifest_outside_snapshot_and_companions_are_kb_documents():
    # A 00-MANIFEST.md that is NOT inside an inventory-* folder is a normal KB doc.
    ex_manifest = "examples/azure/00-MANIFEST.md"
    assert _is_snapshot_manifest(ex_manifest) is False
    assert _is_kb_document(ex_manifest) is True
    # Companion documents are always KB documents.
    assert _is_kb_document("examples/azure/01-azure-agent-platform.diagram.md") is True


# --- inventory-* snapshot routing (R3.5) ----------------------------------- #


def test_inventory_text_files_are_snapshot_artifacts(tmp_path):
    """.md / .yaml / .txt / .csv inside inventory-* route to snapshot artifacts."""
    snap = tmp_path / _SNAP
    files = {
        "network.yaml": "vpc: vpc-abc123\nregion: us-east-1\n",
        "notes.txt": "enumerated 3 subnets\n",
        "resources.csv": "id,type\ni-123,compute_instance\n",
    }
    for name, body in files.items():
        _write(str(snap / name), body)

    for name, body in files.items():
        [artifact] = parse_artifacts(str(snap / name))
        assert artifact.kind == "snapshot", name
        assert artifact.in_snapshot is True, name
        assert artifact.is_snapshot_file is True, name
        assert artifact.text == body, name
        assert list(artifact.parse_errors) == [], name


def test_inventory_markdown_is_snapshot_and_kb_when_not_manifest(tmp_path):
    """A non-manifest .md inside inventory-* is a document artifact but also
    in_snapshot (secret-scanned), and it is a KB document; the 00-MANIFEST.md
    beside it is in_snapshot too but exempt from the KB rule."""
    snap = tmp_path / _SNAP
    readme = snap / "delta-report.md"
    manifest = snap / "00-MANIFEST.md"
    _write(str(readme), "# Delta\n\nprose\n")
    _write(str(manifest), "# Manifest\n\nprovider: aws\n")

    [doc] = parse_artifacts(str(readme))
    assert doc.in_snapshot is True
    assert _is_kb_document(str(readme)) is True

    [man] = parse_artifacts(str(manifest))
    assert man.in_snapshot is True
    assert _is_kb_document(str(manifest)) is False


def test_inventory_binary_file_produces_parse_error(tmp_path):
    """A binary (non-UTF-8) file inside inventory-* is a parse-error: not-text."""
    snap = tmp_path / _SNAP
    blob = snap / "screenshot.bin"
    # Bytes that are not valid UTF-8 (a lone continuation byte / 0xFF).
    _write_bytes(str(blob), b"\xff\xfe\x00\x01\x80\x81binary\x00\xff")

    [artifact] = parse_artifacts(str(blob))
    assert artifact.kind == "snapshot"
    assert artifact.in_snapshot is True
    assert list(artifact.parse_errors) == ["not-text"]


# --- .puml / .mmd source-diagram routing (D1, R10.3) ----------------------- #


def test_puml_and_mmd_route_to_diagram_with_source_format(tmp_path):
    puml = tmp_path / "01-topic.puml"
    mmd = tmp_path / "02-topic.mmd"
    _write(str(puml), "@startuml\nA -> B\n@enduml\n")
    _write(str(mmd), "flowchart LR\n  A --> B\n")

    [p] = parse_artifacts(str(puml))
    assert p.kind == "diagram"
    assert p.source_format == "plantuml"
    assert p.is_drawio is False

    [m] = parse_artifacts(str(mmd))
    assert m.kind == "diagram"
    assert m.source_format == "mermaid"
    assert m.is_drawio is False


# --- discover_artifacts end-to-end walk ------------------------------------ #


def test_discover_artifacts_classifies_a_mixed_tree(tmp_path):
    """A single --all walk picks up exactly the lintable files: .puml/.mmd,
    companion + example manifest KB docs, and every file inside inventory-*
    (including the binary and the exempt 00-MANIFEST.md); it skips steering,
    SKILL.md and README."""
    root = str(tmp_path)

    # Diagram sources (discovered so source-format can report them).
    _write(os.path.join(root, "examples", "aws", "01-topic.puml"), "@startuml\n@enduml\n")
    _write(os.path.join(root, "examples", "aws", "02-topic.mmd"), "flowchart LR\n")

    # KB documents.
    companion = os.path.join(root, "examples", "aws", "01-topic.diagram.md")
    ex_manifest = os.path.join(root, "examples", "azure", "00-MANIFEST.md")
    _write(companion, "---\nid: x\n---\n# c\n")
    _write(ex_manifest, "---\nid: y\n---\n# m\n")

    # NOT KB documents / not discovered as docs.
    _write(os.path.join(root, "README.md"), "# readme\n")
    _write(os.path.join(root, ".kiro", "skills", "s", "SKILL.md"), "# skill\n")
    _write(
        os.path.join(root, "powers", "p", "dev.kiro", "steering", "diagram-lint.md"),
        "---\ninclusion: always\n---\n# steering\n",
    )

    # An inventory-* snapshot folder with mixed content.
    snap = os.path.join(root, _SNAP)
    snap_manifest = os.path.join(snap, "00-MANIFEST.md")
    snap_yaml = os.path.join(snap, "network.yaml")
    snap_txt = os.path.join(snap, "notes.txt")
    snap_csv = os.path.join(snap, "resources.csv")
    snap_bin = os.path.join(snap, "screenshot.bin")
    _write(snap_manifest, "# manifest\nprovider: aws\n")
    _write(snap_yaml, "vpc: vpc-abc\n")
    _write(snap_txt, "notes\n")
    _write(snap_csv, "id,type\ni-1,compute_instance\n")
    _write_bytes(snap_bin, b"\xff\xfebinary\x00")

    found = set(discover_artifacts(root))

    # Discovered.
    for path in (
        os.path.join(root, "examples", "aws", "01-topic.puml"),
        os.path.join(root, "examples", "aws", "02-topic.mmd"),
        companion,
        ex_manifest,
        snap_manifest,
        snap_yaml,
        snap_txt,
        snap_csv,
        snap_bin,
    ):
        assert path in found, f"expected discovered: {path}"

    # Skipped.
    for path in (
        os.path.join(root, "README.md"),
        os.path.join(root, ".kiro", "skills", "s", "SKILL.md"),
    ):
        assert path not in found, f"expected skipped: {path}"

    # The power's steering file is under dev.kiro/steering: walked but not a KB doc.
    steering = os.path.join(
        root, "powers", "p", "dev.kiro", "steering", "diagram-lint.md"
    )
    assert steering not in found


def test_discover_artifacts_excludes_the_tests_tree(tmp_path):
    """The ``tests/`` tree is test *input*, not a workspace artifact, so the
    ``--all`` walk prunes it (like ``.git`` / ``.venv`` / ``assets``).

    ``tests/fixtures/drawio/*`` holds deliberately-invalid diagrams (billion-laughs,
    xxe, parent-cycle, …) that MUST lint as BLOCKED — that is their purpose for the
    parser tests. Scanning them under ``--all`` would wrongly block the CI lint step,
    so ``tests`` is in ``_EXCLUDED_DIRS`` and nothing under it is discovered."""
    root = str(tmp_path)

    # A real diagram outside tests/ IS discovered ...
    good = os.path.join(root, "examples", "aws", "01-topic.drawio")
    _write(good, '<mxGraphModel><root></root></mxGraphModel>')

    # ... while a fixture under tests/ is pruned from the walk.
    fixture = os.path.join(root, "tests", "fixtures", "drawio", "billion-laughs.drawio")
    _write(fixture, '<mxGraphModel><root></root></mxGraphModel>')

    found = set(discover_artifacts(root))
    assert good in found
    assert fixture not in found
    assert not any(os.sep + "tests" + os.sep in p for p in found)
