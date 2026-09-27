"""Unit tests for the rules rewired in honest-gates 1.7.0 (task 10.10).

These exercise the four gates that 1.6.1 could pass without actually checking
anything, now end-to-end through the parsed-model CLI (``cli.parse_artifacts`` /
``cli.parse_artifact``) and the Lint_CLI ``--json`` output:

* **frontmatter** now validates the whole ``kb-frontmatter.md`` contract via
  :mod:`rule_engine.kb_validator`, so ``status: bogus`` and the impossible date
  ``updated: 2026-02-30`` are named CRITICAL findings, not merely a present key
  (R2.7).
* **secret-safety** now parses content via :mod:`rule_engine.secret_safety`, so
  a snapshot ``.yaml`` carrying ``password: x`` is flagged at ``line:<n>`` and
  the finding never contains the secret value (R3.5).
* **icon-resolved** now resolves ``resIcon`` / ``grIcon`` / ``azure2`` against
  the committed manifests, so an unknown ``mxgraph.aws4.<typo>`` id is an ERROR
  whose offender is the cell id (R4.5).
* the Lint_CLI ``--json`` output carries each finding's ``offenders`` and
  ``reason`` (R1.13).

The tests write real files under ``tmp_path`` and route them through the CLI
parser (not a hand-built ``Artifact``), so they exercise the same code path the
``rule-engine-lint`` command and the hooks use.
"""

from __future__ import annotations

import json

import pytest

from rule_engine.cli import main, parse_artifact, parse_artifacts
from rule_engine.linter import (
    RULE_FRONTMATTER,
    RULE_ICON_RESOLVED,
    RULE_SECRET_SAFETY,
    Severity,
    lint,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _findings_for(result, rule_name):
    """Return every finding dict for ``rule_name`` in a lint result."""
    return [f for f in result["findings"] if f["rule"] == rule_name]


def _rules(result):
    return {f["rule"] for f in result["findings"]}


# A complete, valid KB body: exactly one H1 and the four required sections, each
# within the 100-200-word bound, no fenced code block. The frontmatter is filled
# in per-test so we isolate the single frontmatter aspect under test.
_PARA = " ".join(f"word{i}" for i in range(130))
_VALID_BODY = (
    "\n# A Document\n\n"
    f"## Overview\n\n{_PARA}\n\n"
    f"## Main Content\n\n{_PARA}\n\n"
    f"## Troubleshooting\n\n{_PARA}\n\n"
    f"## See Also\n\n{_PARA}\n"
)


def _kb_document(*, status: str = "draft", updated: str = "2025-01-15") -> str:
    """A KB document whose ``status`` / ``updated`` are the only variables."""
    frontmatter = (
        "---\n"
        "id: doc-1\n"
        "title: A Document\n"
        "kb_namespace: arch\n"
        "section: diagrams\n"
        "category: reference\n"
        f"status: {status}\n"
        f"updated: {updated}\n"
        "owner: platform-team\n"
        "author: kiro\n"
        "next_review_date: 2025-07-15\n"
        "tags:\n  - cloud\n"
        "related_docs: []\n"
        "---\n"
    )
    return frontmatter + _VALID_BODY


def _drawio(body: str) -> str:
    return (
        '<mxfile><diagram id="d" name="d"><mxGraphModel gridSize="10"><root>'
        '<mxCell id="0" /><mxCell id="1" parent="0" />'
        f"{body}"
        "</root></mxGraphModel></diagram></mxfile>"
    )


# --------------------------------------------------------------------------- #
# frontmatter: malformed values are named CRITICAL findings (R2.7)
# --------------------------------------------------------------------------- #


def test_bogus_status_is_a_named_critical_frontmatter_finding(tmp_path):
    """``status: bogus`` is rejected — the value is present but out of the enum.

    1.6.1 accepted it (the key existed); 1.7.0 names the ``status-enum``
    constraint on the ``status`` key at CRITICAL.
    """
    doc = tmp_path / "kb.md"
    doc.write_text(_kb_document(status="bogus"), encoding="utf-8")

    result = lint(parse_artifact(str(doc)))

    findings = _findings_for(result, RULE_FRONTMATTER)
    assert findings, result["findings"]
    assert all(f["severity"] == Severity.CRITICAL.value for f in findings)
    # The offending key and the violated constraint are both named.
    reasons = {f["reason"] for f in findings}
    offenders = {o for f in findings for o in f["offenders"]}
    assert "status-enum" in reasons
    assert "status" in offenders
    assert result["eligible_for_publication"] is False


def test_impossible_date_is_a_named_critical_frontmatter_finding(tmp_path):
    """``updated: 2026-02-30`` is not a real calendar date — 30 Feb never exists.

    The date is well-formed ``YYYY-MM-DD`` (so a shape check alone would miss it)
    but ``date.fromisoformat`` rejects it, so ``date-format`` fires on ``updated``.
    """
    doc = tmp_path / "kb.md"
    doc.write_text(_kb_document(updated="2026-02-30"), encoding="utf-8")

    result = lint(parse_artifact(str(doc)))

    findings = _findings_for(result, RULE_FRONTMATTER)
    assert findings, result["findings"]
    assert all(f["severity"] == Severity.CRITICAL.value for f in findings)
    reasons = {f["reason"] for f in findings}
    offenders = {o for f in findings for o in f["offenders"]}
    assert "date-format" in reasons
    assert "updated" in offenders
    assert result["eligible_for_publication"] is False


def test_both_malformed_values_are_each_named(tmp_path):
    """A document with both defects reports one finding per constraint."""
    doc = tmp_path / "kb.md"
    doc.write_text(
        _kb_document(status="bogus", updated="2026-02-30"), encoding="utf-8"
    )

    result = lint(parse_artifact(str(doc)))
    reasons = {f["reason"] for f in _findings_for(result, RULE_FRONTMATTER)}
    assert {"status-enum", "date-format"} <= reasons


def test_valid_status_and_date_produce_no_frontmatter_finding(tmp_path):
    """The same document with valid values passes the frontmatter gate."""
    doc = tmp_path / "kb.md"
    doc.write_text(_kb_document(), encoding="utf-8")

    result = lint(parse_artifact(str(doc)))
    assert RULE_FRONTMATTER not in _rules(result), result["findings"]
    assert result["eligible_for_publication"] is True


# --------------------------------------------------------------------------- #
# secret-safety: a snapshot .yaml with a password is flagged at line:<n>,
# without the value (R3.5)
# --------------------------------------------------------------------------- #


def _inventory_dir(tmp_path):
    """A conforming ``inventory-*`` Snapshot folder (its contents are scanned)."""
    d = tmp_path / "inventory-aws-123456789012-us-east-1-2025-01-15_1430"
    d.mkdir()
    return d


def test_snapshot_yaml_password_is_flagged_at_a_line_without_the_value(tmp_path):
    """A ``.yaml`` under ``inventory-*`` with ``password: hunter2`` is CRITICAL.

    Every ``.yaml``/``.txt``/``.csv`` inside a snapshot folder is scanned as text
    (R3.5). The offender is a ``line:<n>`` location and the secret value
    (``hunter2``) appears nowhere in the finding.
    """
    secret_value = "hunter2"
    snap = _inventory_dir(tmp_path) / "config.yaml"
    snap.write_text(
        f"region: us-east-1\nname: db\npassword: {secret_value}\n",
        encoding="utf-8",
    )

    result = lint(parse_artifact(str(snap)))

    findings = _findings_for(result, RULE_SECRET_SAFETY)
    assert findings, result["findings"]
    f = findings[0]
    assert f["severity"] == Severity.CRITICAL.value
    # Located by line, not by value: password is on line 3.
    assert f["offenders"] == ["line:3"]
    # The finding NEVER carries the secret value.
    assert secret_value not in json.dumps(result)
    assert result["eligible_for_publication"] is False


def test_snapshot_json_password_is_flagged_by_json_pointer_without_the_value(
    tmp_path,
):
    """A Normalized-resource ``.json`` with a credential value is flagged by a
    JSON pointer (RFC 6901), again value-free."""
    secret_value = "s3cr3t-token-value"
    snap = _inventory_dir(tmp_path) / "storage.json"
    snap.write_text(
        json.dumps(
            {"resource_type": "managed_sql", "provider": "aws", "password": secret_value}
        ),
        encoding="utf-8",
    )

    result = lint(parse_artifact(str(snap)))

    findings = _findings_for(result, RULE_SECRET_SAFETY)
    assert findings, result["findings"]
    f = findings[0]
    assert f["severity"] == Severity.CRITICAL.value
    assert f["offenders"] == ["/password"]  # RFC 6901 pointer, not the value
    assert secret_value not in json.dumps(result)


def test_snapshot_yaml_metadata_is_not_flagged(tmp_path):
    """A snapshot with only non-secret metadata produces no secret finding."""
    snap = _inventory_dir(tmp_path) / "network.yaml"
    snap.write_text(
        "region: us-east-1\ninstance_id: i-0abc123\nvpc_id: vpc-999\n",
        encoding="utf-8",
    )
    result = lint(parse_artifact(str(snap)))
    assert RULE_SECRET_SAFETY not in _rules(result), result["findings"]


# --------------------------------------------------------------------------- #
# icon-resolved: an unknown resIcon is an ERROR whose offender is the cell id
# (R4.5)
# --------------------------------------------------------------------------- #


def test_unknown_res_icon_is_an_error_with_the_cell_id_as_offender(tmp_path):
    """A ``resIcon=mxgraph.aws4.<typo>`` id absent from the committed manifest
    would render as an empty box, so it is an ERROR naming the offending cell."""
    body = (
        '<mxCell id="typo-node" value="mystery" '
        'style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.notarealservice" '
        'vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="78" height="78" as="geometry"/></mxCell>'
    )
    drawio = tmp_path / "diagram.drawio"
    drawio.write_text(_drawio(body), encoding="utf-8")
    # A companion so companion-doc does not muddy the result.
    (tmp_path / "diagram.diagram.md").write_text(
        "---\ndiagram_class: flow\n---\n", encoding="utf-8"
    )

    result = lint(parse_artifact(str(drawio)))

    findings = _findings_for(result, RULE_ICON_RESOLVED)
    assert findings, result["findings"]
    f = findings[0]
    assert f["severity"] == Severity.ERROR.value
    assert f["offenders"] == ["typo-node"]
    assert result["eligible_for_publication"] is False


def test_known_res_icon_does_not_trip_icon_resolved(tmp_path):
    """A real ``mxgraph.aws4.s3`` id resolves against the manifest — no finding
    from the manifest half of the rule."""
    body = (
        '<mxCell id="s3-node" value="s3" '
        'style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.s3" '
        'vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="78" height="78" as="geometry"/></mxCell>'
    )
    drawio = tmp_path / "diagram.drawio"
    drawio.write_text(_drawio(body), encoding="utf-8")
    (tmp_path / "diagram.diagram.md").write_text(
        "---\ndiagram_class: flow\n---\n", encoding="utf-8"
    )

    result = lint(parse_artifact(str(drawio)))
    icon_findings = _findings_for(result, RULE_ICON_RESOLVED)
    # Any icon-resolved finding here would have to be the manifest half; there
    # should be none for a known id.
    assert icon_findings == [], icon_findings


# --------------------------------------------------------------------------- #
# Lint_CLI --json output includes offenders (R1.13)
# --------------------------------------------------------------------------- #


def test_cli_json_output_includes_offenders_and_reason(tmp_path, capsys):
    """``rule-engine-lint --file … --json`` prints each finding's offenders and
    reason. Uses the snapshot-secret case: its offender is a value-free
    ``line:<n>`` location, so the JSON stays secret-free too."""
    secret_value = "topsecretpw"
    snap = _inventory_dir(tmp_path) / "db.yaml"
    snap.write_text(f"password: {secret_value}\n", encoding="utf-8")

    exit_code = main(
        [
            "--file",
            str(snap),
            "--workspace-root",
            str(tmp_path),
            "--json",
        ]
    )
    # A CRITICAL secret blocks publication -> non-zero exit.
    assert exit_code == 1

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert isinstance(payload, list) and payload

    secret_findings = [
        f
        for result in payload
        for f in result["findings"]
        if f["rule"] == RULE_SECRET_SAFETY
    ]
    assert secret_findings, payload
    f = secret_findings[0]
    # The --json output carries offenders and reason for every finding.
    assert "offenders" in f and "reason" in f
    assert f["offenders"] == ["line:1"]
    assert f["reason"]  # non-empty (a credential-key:<normalized> kind)
    # And it never leaks the secret value.
    assert secret_value not in out


def test_cli_json_output_carries_icon_offender_cell_id(tmp_path, capsys):
    """The ``--json`` output of an unknown-resIcon diagram names the cell id."""
    body = (
        '<mxCell id="typo-node" value="mystery" '
        'style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.notarealservice" '
        'vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="78" height="78" as="geometry"/></mxCell>'
    )
    drawio = tmp_path / "diagram.drawio"
    drawio.write_text(_drawio(body), encoding="utf-8")
    (tmp_path / "diagram.diagram.md").write_text(
        "---\ndiagram_class: flow\n---\n", encoding="utf-8"
    )

    exit_code = main(
        ["--file", str(drawio), "--workspace-root", str(tmp_path), "--json"]
    )
    assert exit_code == 1

    payload = json.loads(capsys.readouterr().out)
    icon_findings = [
        f
        for result in payload
        for f in result["findings"]
        if f["rule"] == RULE_ICON_RESOLVED
    ]
    assert icon_findings, payload
    assert "typo-node" in icon_findings[0]["offenders"]


def test_parse_artifacts_returns_a_single_page_list(tmp_path):
    """Sanity: ``parse_artifacts`` returns one Artifact for a single-page file,
    labelled by the plain path (task 9.3)."""
    body = (
        '<mxCell id="n" value="n" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.s3" '
        'vertex="1" parent="1"><mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>'
    )
    drawio = tmp_path / "one.drawio"
    drawio.write_text(_drawio(body), encoding="utf-8")

    artifacts = parse_artifacts(str(drawio))
    assert len(artifacts) == 1
    assert artifacts[0].label == str(drawio)
