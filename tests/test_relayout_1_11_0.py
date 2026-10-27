"""``rule-engine-relayout`` (1.11.0 FEAT-004, E-07): best-effort re-layout.

The command re-flows an engine-emitted ``.drawio`` through the deterministic
``build_diagram`` finishing, so a second pass is byte-identical (idempotent),
and FAILS HONESTLY on a hand-authored / hand-pinned source it cannot faithfully
reconstruct. Hand-authored ``.drawio`` is explicitly NOT first-class.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from rule_engine import relayout_cli  # noqa: E402
from rule_engine.relayout_cli import RelayoutError, relayout_text  # noqa: E402

# An engine-emitted golden (produced by layout() + build_diagram()).
_ENGINE_GOLDEN = _REPO_ROOT / "examples" / "aws" / "01-aws-agent-platform.drawio"

# A hand-pinned sketch: plain boxes at pinned coordinates, NO Legend furniture
# and NO engine structure — the shape relayout must refuse.
_HAND_PINNED = """<mxfile host="app.diagrams.net">
  <diagram id="hp" name="hand-pinned">
    <mxGraphModel gridSize="10" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="a" value="Box A" style="rounded=0;whiteSpace=wrap;html=1" vertex="1" parent="1">
          <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
        </mxCell>
        <mxCell id="b" value="Box B" style="rounded=0;whiteSpace=wrap;html=1" vertex="1" parent="1">
          <mxGeometry x="300" y="200" width="120" height="60" as="geometry" />
        </mxCell>
        <mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle" edge="1" source="a" target="b" parent="1">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""

# A hand-pinned sketch that DOES carry a Legend cell but hangs an edge off a
# detached endpoint — the second honest-failure signal.
_DETACHED_EDGE = """<mxfile host="app.diagrams.net">
  <diagram id="de" name="detached">
    <mxGraphModel gridSize="10" pageWidth="800" pageHeight="600">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="a" value="Box A" style="rounded=0;whiteSpace=wrap;html=1" vertex="1" parent="1">
          <mxGeometry x="40" y="40" width="120" height="60" as="geometry" />
        </mxCell>
        <mxCell id="legend" value="Legend&#10;Solid line = primary flow" style="text;html=1;whiteSpace=wrap;fillColor=#FFFFFF;strokeColor=#000000" vertex="1" parent="1">
          <mxGeometry x="600" y="40" width="160" height="60" as="geometry" />
        </mxCell>
        <mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle" edge="1" source="a" target="ghost" parent="1">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""


def test_relayout_idempotent_on_engine_output():
    """Re-laying out an engine-emitted golden is idempotent (byte-identical).

    The first pass canonicalises the diagram into ``build_diagram``'s emitted
    form; a SECOND pass over that output reproduces it byte-for-byte, which is
    the guarantee ``rule-engine-relayout`` offers for an engine-emitted shape."""
    original = _ENGINE_GOLDEN.read_text(encoding="utf-8")
    once = relayout_text(original, path=str(_ENGINE_GOLDEN))
    twice = relayout_text(once, path=str(_ENGINE_GOLDEN))
    assert once == twice, "relayout is not idempotent on engine output"


def test_relayout_preserves_nodes_and_edges():
    """The re-laid-out golden keeps every node and edge id (no silent drop)."""
    from rule_engine.drawio_model import parse_drawio

    original = _ENGINE_GOLDEN.read_text(encoding="utf-8")
    once = relayout_text(original, path=str(_ENGINE_GOLDEN))

    before = parse_drawio(original.encode("utf-8"), path="before")[0]
    after = parse_drawio(once.encode("utf-8"), path="after")[0]
    before_nodes = {cid for cid, c in before.cells.items() if c.vertex}
    after_nodes = {cid for cid, c in after.cells.items() if c.vertex}
    before_edges = {cid for cid, c in before.cells.items() if c.edge}
    after_edges = {cid for cid, c in after.cells.items() if c.edge}
    assert before_nodes == after_nodes
    assert before_edges == after_edges


def test_relayout_output_is_publication_eligible():
    """The re-laid-out golden lints with zero ERROR / CRITICAL findings."""
    from rule_engine import cli
    from rule_engine.linter import Severity, lint_with_ruleset

    original = _ENGINE_GOLDEN.read_text(encoding="utf-8")
    once = relayout_text(original, path=str(_ENGINE_GOLDEN))

    artifact = cli.parse_drawio_text(once, "relayout.drawio") if hasattr(cli, "parse_drawio_text") else None
    if artifact is None:
        # Fall back to writing a temp file and parsing it as the CLI would.
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "relayout.drawio"
            p.write_text(once, encoding="utf-8")
            # Ship the companion beside it so the triple is complete and the
            # test judges relayout's own output, not a missing companion-doc.
            companion = _ENGINE_GOLDEN.with_suffix("").with_suffix(".diagram.md")
            (Path(d) / "relayout.diagram.md").write_text(
                companion.read_text(encoding="utf-8"), encoding="utf-8"
            )
            artifact = cli.parse_artifact(str(p))
            result = lint_with_ruleset(artifact, workspace_root=str(_REPO_ROOT))
    else:
        result = lint_with_ruleset(artifact, workspace_root=str(_REPO_ROOT))

    blocking = [
        f for f in result["findings"]
        if f["severity"] in (Severity.CRITICAL.value, Severity.ERROR.value)
    ]
    assert not blocking, f"relayout output is blocked: {blocking}"


def test_relayout_fails_honestly_on_hand_pinned():
    """A hand-pinned sketch (no Legend furniture) fails with a named limitation."""
    with pytest.raises(RelayoutError) as exc:
        relayout_text(_HAND_PINNED, path="01-hand-pinned.drawio")
    msg = str(exc.value)
    assert "01-hand-pinned.drawio" in msg
    assert "not engine-emitted" in msg or "Legend" in msg


def test_relayout_fails_honestly_on_detached_edge():
    """An edge detached from any node fails with a named limitation."""
    with pytest.raises(RelayoutError) as exc:
        relayout_text(_DETACHED_EDGE, path="01b-detached.drawio")
    msg = str(exc.value)
    assert "ghost" in msg
    assert "hand-authored" in msg or "hand-pinned" in msg


def test_relayout_cli_exit_codes(tmp_path):
    """The CLI exits 0 on an engine golden and 2 on a hand-pinned source."""
    good = tmp_path / "good.drawio"
    good.write_text(_ENGINE_GOLDEN.read_text(encoding="utf-8"), encoding="utf-8")
    assert relayout_cli.main([str(good), "--out", str(tmp_path / "good-out.drawio")]) == 0

    bad = tmp_path / "01-bad.drawio"
    bad.write_text(_HAND_PINNED, encoding="utf-8")
    assert relayout_cli.main([str(bad), "--out", str(tmp_path / "bad-out.drawio")]) == 2
