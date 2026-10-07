"""Property/example tests for the reconciliation gate ``reconcile.reconcile``.

Feature: placement-and-gates (release 1.9.0), Component B2 — the
``rule-engine-reconcile`` gate that compares a committed inventory Snapshot
against the diagram generated from it and blocks when a role-bearing enumerated
resource is silently absent from the diagram.

This is **Property 4** of the design ("Reconciliation catches an omission"):

* a ``landscape`` diagram missing a role-bearing enumerated resource is
  **blocked** and the omission is **named** (Requirement 2.3);
* a **complete** diagram (every role-bearing enumerated resource drawn)
  **passes** (Requirement 2.3);
* a resource with **no resolvable role** is **never** flagged as an omission
  (Requirement 2.5).

**Validates: Requirements 2.3, 2.5**

The tests craft a Snapshot/diagram pair two ways:

1. A hand-built minimal AWS ``.drawio`` (a boundary container plus a chosen set
   of ``resIcon`` service nodes) paired with a Snapshot written by the real
   Collector, so the expected role set (from the Snapshot) and the drawn role
   set (from the diagram) are both produced by the shipped code paths — the gate
   cannot drift from what a generator draws.
2. The shipped AWS HA landscape (``examples/aws/02-…-landscape.drawio``), paired
   with a Snapshot built from the roles that landscape actually draws, so the
   gate is exercised against a real corpus artifact: a complete Snapshot passes,
   and adding one enumerated resource of a role the landscape does not draw is
   blocked and named.

Everything reads only committed files (Decision D5); the Collector writes its
Snapshot under a ``tmp_path`` and is strictly read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.collector import collect
from rule_engine.drawio_model import parse_drawio
from rule_engine.reconcile import (
    ReconcileError,
    drawn_roles,
    reconcile,
)

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# AWS native types (aliases straight from the terminology table) for each role a
# crafted Snapshot may enumerate, plus the resIcon id the diagram draws for it.
# The nine neutral types use their terminology seed ids; the presentation roles
# use the ids the AWS generators draw (see reconcile._AWS_PRESENTATION_RESICON).
_ROLE_TO_NATIVE: Dict[str, str] = {
    "serverless_fn": "AWS::Lambda::Function",
    "object_store": "aws::s3::bucket",
    "managed_sql": "aws::rds::dbinstance",
    "message_queue": "aws::sqs::queue",
    "secrets_store": "aws::secretsmanager::secret",
    "managed_k8s": "aws::eks::cluster",
    "llm_platform": "bedrock",
    "compute_instance": "AWS::EC2::Instance",
    "file_system": "AWS::EFS::FileSystem",
    "cdn": "cloudfront",
    "dns": "aws::route53::hostedzone",
    "waf": "aws::wafv2::webacl",
    "lb": "aws::elasticloadbalancingv2::loadbalancer",
    "cache": "elasticache",
}

_ROLE_TO_RESICON: Dict[str, str] = {
    "serverless_fn": "lambda",
    "object_store": "s3",
    "managed_sql": "rds",
    "message_queue": "sqs",
    "secrets_store": "secrets_manager",
    "managed_k8s": "eks",
    "llm_platform": "bedrock",
    "compute_instance": "ec2",
    "file_system": "efs_standard",
    "cdn": "cloudfront",
    "dns": "route_53",
    "waf": "waf",
    "lb": "application_load_balancer",
    "cache": "elasticache",
}

_ACCOUNT = "111122223333"
_REGION = "us-east-1"


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _write_snapshot(
    tmp_path: Path,
    resources_by_domain: Dict[str, List[dict]],
) -> Path:
    """Write a real AWS Snapshot via the Collector; return its folder Path.

    ``resources_by_domain`` maps a service-domain name to a list of raw native
    resource dicts (each with a ``native_type`` and identity fields). The
    Collector runs a read-only enumerator per domain and writes the committed
    ``<domain>.json`` files the reconciler reads.
    """
    enumerators: List[dict] = []
    for domain, resources in resources_by_domain.items():
        # Bind ``resources`` per-domain via a default arg so the closure is not
        # late-binding to the loop variable.
        enumerators.append(
            {
                "service": domain,
                "verb": f"describe_{domain}",
                "fn": (lambda _res=resources, **_kw: _res),
            }
        )
    result = collect(
        "aws",
        _ACCOUNT,
        _REGION,
        output_root=str(tmp_path),
        enumerators=enumerators,
    )
    return Path(result["snapshot_folder"])


def _resource(native_type: str, name: str) -> dict:
    """A raw native AWS resource dict as a Snapshot per-domain file records it."""
    return {
        "native_type": native_type,
        "id": name,
        "name": name,
        "boundary": _ACCOUNT,
        "region": _REGION,
        "tags": {},
    }


def _service_node(cell_id: str, name: str, res_icon: str) -> str:
    """An AWS service-vertex cell drawing ``res_icon``, parented to the layer.

    A service node must be parented to the page layer (``parent="1"``), not to a
    boundary container: ``icon_refs.service_vertices`` treats a vertex nested
    inside another vertex as that node's internal geometry, so a node parented to
    the boundary group would not contribute its role (this mirrors how the
    shipped generators emit top-level service nodes).
    """
    style = f"sketch=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res_icon}"
    return (
        f'<mxCell id="{cell_id}" value="{name}" style="{style}" '
        f'vertex="1" parent="1">'
        f'<mxGeometry x="80" y="80" width="78" height="78" as="geometry"/>'
        f"</mxCell>"
    )


def _write_diagram(
    tmp_path: Path,
    roles: Sequence[str],
    *,
    diagram_class: str = "landscape",
    stem: str = "02-crafted-landscape",
) -> Path:
    """Write a minimal AWS ``.drawio`` drawing ``roles`` plus a companion.

    The diagram carries an AWS Account boundary container (covering the
    structural ``boundary`` / ``network_boundary`` roles) and one service node
    per requested presentation/neutral role. The companion ``.diagram.md``
    frontmatter declares ``diagram_class`` so the reconciler reads the coverage
    class exactly as the Linter does. Returns the ``.drawio`` path.
    """
    nodes = [
        _service_node(f"n-{i}", f"{role}-node", _ROLE_TO_RESICON[role])
        for i, role in enumerate(roles)
    ]
    boundary = (
        '<mxCell id="boundary-account" value="Account 111122223333" '
        'style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;dashed=1" '
        'vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="1200" height="600" as="geometry"/>'
        "</mxCell>"
    )
    body = "\n        ".join([boundary, *nodes])
    xml = (
        '<mxfile host="rule-engine">\n'
        '  <diagram id="p1" name="crafted">\n'
        '    <mxGraphModel gridSize="10">\n'
        "      <root>\n"
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f"        {body}\n"
        "      </root>\n"
        "    </mxGraphModel>\n"
        "  </diagram>\n"
        "</mxfile>\n"
    )
    drawio_path = tmp_path / f"{stem}.drawio"
    drawio_path.write_text(xml, encoding="utf-8")

    # A companion with a valid twelve-key frontmatter block so the coverage class
    # loads exactly as the Linter reads it. summary_of is present so the file is
    # a well-formed landscape companion (orphan-landscape is a linter concern,
    # not the reconciler's, but keeping it correct avoids surprises).
    companion = tmp_path / f"{stem}.diagram.md"
    companion.write_text(
        "---\n"
        f"id: {stem}\n"
        "title: Crafted reconcile fixture\n"
        "kb_namespace: cloud-architecture\n"
        "section: tests\n"
        "category: fixture\n"
        "status: draft\n"
        "updated: 2027-01-01\n"
        "owner: rule-engine\n"
        "author: rule-engine\n"
        "next_review_date: 2027-07-01\n"
        f"diagram_class: {diagram_class}\n"
        "summary_of: 02-crafted-summary\n"
        "tags:\n"
        "  - fixture\n"
        "related_docs: []\n"
        "---\n\n"
        "# Crafted reconcile fixture\n",
        encoding="utf-8",
    )
    return drawio_path


# --------------------------------------------------------------------------- #
# Property 4 (a): a landscape missing a role-bearing resource is blocked + named
# --------------------------------------------------------------------------- #


def test_landscape_omission_is_blocked_and_named(tmp_path: Path) -> None:
    """A role-bearing enumerated resource with no drawn node blocks and is named.

    Snapshot enumerates an S3 bucket, an EFS filesystem, and an EC2 instance; the
    landscape draws only the bucket. The EFS and EC2 resources are omissions:
    the report is blocked, names both offending resources, and identifies their
    roles. (Requirement 2.3, Property 4.)
    """
    snapshot = _write_snapshot(
        tmp_path,
        {
            "storage": [
                _resource("aws::s3::bucket", "my-bucket"),
                _resource("AWS::EFS::FileSystem", "my-filesystem"),
            ],
            "compute": [_resource("AWS::EC2::Instance", "my-instance")],
        },
    )
    # The diagram draws only object_store — file_system and compute_instance are
    # enumerated but never drawn.
    diagram = _write_diagram(tmp_path, ["object_store"], diagram_class="landscape")

    report = reconcile(snapshot, diagram, "aws")

    assert report.coverage_class == "landscape"
    assert not report.eligible, "a landscape missing enumerated roles must block"

    omitted_roles = {om["role"] for om in report.omissions}
    omitted_names = {om["resource"] for om in report.omissions}
    assert omitted_roles == {"file_system", "compute_instance"}
    # Each omission NAMES the offending resource (Requirement 2.3).
    assert omitted_names == {"my-filesystem", "my-instance"}
    # The drawn object_store resource is NOT an omission.
    assert "my-bucket" not in omitted_names


# --------------------------------------------------------------------------- #
# Property 4 (b): a complete landscape passes
# --------------------------------------------------------------------------- #


def test_complete_landscape_passes(tmp_path: Path) -> None:
    """When every role-bearing enumerated resource is drawn, the gate passes.

    The same three resources are enumerated, and the landscape draws all three
    roles (object_store, file_system, compute_instance). No omissions ⇒ eligible.
    (Requirement 2.3, Property 4.)
    """
    snapshot = _write_snapshot(
        tmp_path,
        {
            "storage": [
                _resource("aws::s3::bucket", "my-bucket"),
                _resource("AWS::EFS::FileSystem", "my-filesystem"),
            ],
            "compute": [_resource("AWS::EC2::Instance", "my-instance")],
        },
    )
    diagram = _write_diagram(
        tmp_path,
        ["object_store", "file_system", "compute_instance"],
        diagram_class="landscape",
    )

    report = reconcile(snapshot, diagram, "aws")

    assert report.coverage_class == "landscape"
    assert report.eligible, f"complete landscape should pass, got {report.omissions}"
    assert report.omissions == []
    # Expected roles are exactly the three enumerated ones; all are drawn.
    assert report.expected_roles == frozenset(
        {"object_store", "file_system", "compute_instance"}
    )
    assert report.expected_roles <= report.drawn_roles


# --------------------------------------------------------------------------- #
# Property 4 (c): a resource with no resolvable role is never an omission
# --------------------------------------------------------------------------- #


def test_unresolvable_role_resource_is_never_flagged(tmp_path: Path) -> None:
    """An enumerated resource with no role mapping is not an omission (Req 2.5).

    The Snapshot enumerates an S3 bucket (role object_store) and an AWS Glacier
    vault (no role mapping). The landscape draws only object_store. Glacier has
    no resolvable role, so it never enters the expected set and can never be
    reported as an omission — the report is eligible.
    """
    snapshot = _write_snapshot(
        tmp_path,
        {
            "storage": [
                _resource("aws::s3::bucket", "my-bucket"),
                # Glacier has no role mapping (see test_reconcile_role_of.py).
                _resource("AWS::Glacier::Vault", "cold-archive"),
            ],
        },
    )
    diagram = _write_diagram(tmp_path, ["object_store"], diagram_class="landscape")

    report = reconcile(snapshot, diagram, "aws")

    assert report.eligible, "an unresolvable-role resource must not block"
    assert report.omissions == []
    # Glacier never becomes an expected role, and is never named as an omission.
    assert report.expected_roles == frozenset({"object_store"})
    assert "cold-archive" not in {om["resource"] for om in report.omissions}


def test_unresolvable_role_not_flagged_even_when_other_roles_omitted(
    tmp_path: Path,
) -> None:
    """Req 2.5 holds even alongside a genuine omission: only the mapped role blocks.

    The Snapshot enumerates a bucket (drawn), an EFS filesystem (NOT drawn → a
    real omission), and a Glacier vault (no role). The gate blocks on the EFS
    filesystem alone; the Glacier vault is never named.
    """
    snapshot = _write_snapshot(
        tmp_path,
        {
            "storage": [
                _resource("aws::s3::bucket", "my-bucket"),
                _resource("AWS::EFS::FileSystem", "my-filesystem"),
                _resource("AWS::Glacier::Vault", "cold-archive"),
            ],
        },
    )
    diagram = _write_diagram(tmp_path, ["object_store"], diagram_class="landscape")

    report = reconcile(snapshot, diagram, "aws")

    assert not report.eligible
    assert [om["resource"] for om in report.omissions] == ["my-filesystem"]
    assert {om["role"] for om in report.omissions} == {"file_system"}
    assert "cold-archive" not in {om["resource"] for om in report.omissions}


# --------------------------------------------------------------------------- #
# Structural roles: a boundary the diagram draws is not a spurious omission
# --------------------------------------------------------------------------- #


def test_structural_boundary_role_is_covered_by_the_container(tmp_path: Path) -> None:
    """A Snapshot enumerating the account/VPC boundary is covered by the frame.

    The Boundary / Network-Boundary are drawn as container frames, not service
    icons, so a Snapshot that enumerates them must be reconciled against the
    diagram's boundary container — never reported as an omission just because no
    service icon carries the role.
    """
    snapshot = _write_snapshot(
        tmp_path,
        {
            "identity": [_resource("aws::organizations::account", "acct-111122223333")],
            "network": [_resource("aws::ec2::vpc", "vpc-primary")],
            "storage": [_resource("aws::s3::bucket", "my-bucket")],
        },
    )
    diagram = _write_diagram(tmp_path, ["object_store"], diagram_class="landscape")

    report = reconcile(snapshot, diagram, "aws")

    assert {"boundary", "network_boundary"} <= report.expected_roles
    assert {"boundary", "network_boundary"} <= report.drawn_roles
    assert report.eligible, f"boundary roles must be covered, got {report.omissions}"


# --------------------------------------------------------------------------- #
# flow coverage is scoped: an out-of-scope role is not an omission
# --------------------------------------------------------------------------- #


def test_flow_coverage_is_scoped_not_total(tmp_path: Path) -> None:
    """A ``flow`` diagram does not block on a role it simply does not draw (Req 2.4).

    The same omission that blocks a ``landscape`` (an undrawn EFS filesystem) is
    out of scope for a ``flow`` summary, so the flow reconciliation is eligible.
    This is the coverage-class contrast that makes the landscape check meaningful.
    """
    snapshot = _write_snapshot(
        tmp_path,
        {
            "storage": [
                _resource("aws::s3::bucket", "my-bucket"),
                _resource("AWS::EFS::FileSystem", "my-filesystem"),
            ],
        },
    )
    diagram = _write_diagram(
        tmp_path, ["object_store"], diagram_class="flow", stem="01-crafted-flow"
    )

    report = reconcile(snapshot, diagram, "aws")

    assert report.coverage_class == "flow"
    assert report.eligible, "a scoped flow must not block on an out-of-scope role"
    assert report.omissions == []


# --------------------------------------------------------------------------- #
# Gate errors (Error Handling): unparsable / missing inputs fail closed
# --------------------------------------------------------------------------- #


def test_reconcile_unknown_provider_raises(tmp_path: Path) -> None:
    """An unknown provider is a gate error, never a silent pass."""
    diagram = _write_diagram(tmp_path, ["object_store"])
    snapshot = _write_snapshot(tmp_path, {"storage": [_resource("aws::s3::bucket", "b")]})
    with pytest.raises(ReconcileError):
        reconcile(snapshot, diagram, "not-a-provider")


def test_reconcile_missing_diagram_raises(tmp_path: Path) -> None:
    """A missing diagram file is a gate error."""
    snapshot = _write_snapshot(tmp_path, {"storage": [_resource("aws::s3::bucket", "b")]})
    with pytest.raises(ReconcileError):
        reconcile(snapshot, tmp_path / "nope.drawio", "aws")


def test_reconcile_unparsable_diagram_raises(tmp_path: Path) -> None:
    """A diagram that does not parse is reported, not treated as drawing nothing."""
    snapshot = _write_snapshot(tmp_path, {"storage": [_resource("aws::s3::bucket", "b")]})
    bad = tmp_path / "bad.drawio"
    bad.write_text("<mxfile><not-closed>", encoding="utf-8")
    with pytest.raises(ReconcileError):
        reconcile(snapshot, bad, "aws")


# --------------------------------------------------------------------------- #
# Shipped corpus: the real AWS HA landscape (Decision D5, "exercise the corpus")
# --------------------------------------------------------------------------- #

_AWS_LANDSCAPE = _EXAMPLES / "aws" / "02-aws-ha-multiregion-landscape.drawio"


def _aws_landscape_drawn_roles() -> frozenset:
    """The roles the shipped AWS landscape actually draws (union across pages)."""
    pages = parse_drawio(_AWS_LANDSCAPE.read_bytes(), path=str(_AWS_LANDSCAPE))
    drawn: set = set()
    for page in pages:
        drawn |= drawn_roles(page, "aws")
    return frozenset(drawn)


@pytest.mark.skipif(not _AWS_LANDSCAPE.is_file(), reason="shipped AWS landscape absent")
def test_shipped_landscape_complete_snapshot_passes(tmp_path: Path) -> None:
    """A Snapshot built from the shipped landscape's drawn roles reconciles clean.

    Every role the landscape draws (minus the structural boundary roles, which
    are the container frames, not enumerable service icons) is enumerated once in
    a crafted Snapshot; reconciling that Snapshot against the real landscape must
    be eligible — a complete diagram passes (Requirement 2.3).
    """
    drawn = _aws_landscape_drawn_roles()
    enumerable = sorted(
        r for r in drawn if r not in ("boundary", "network_boundary") and r in _ROLE_TO_NATIVE
    )
    resources = [
        _resource(_ROLE_TO_NATIVE[role], f"{role}-res") for role in enumerable
    ]
    snapshot = _write_snapshot(tmp_path, {"all": resources})

    report = reconcile(snapshot, _AWS_LANDSCAPE, "aws")

    assert report.coverage_class == "landscape"
    assert report.eligible, f"shipped landscape should cover its own roles: {report.omissions}"
    assert frozenset(enumerable) <= report.drawn_roles


@pytest.mark.skipif(not _AWS_LANDSCAPE.is_file(), reason="shipped AWS landscape absent")
def test_shipped_landscape_blocks_an_undrawn_role(tmp_path: Path) -> None:
    """Adding an enumerated resource of a role the landscape omits blocks + names it.

    The shipped landscape draws no ``file_system``; enumerating an EFS filesystem
    alongside its real roles makes that filesystem a named omission on the real
    corpus artifact (Requirement 2.3, Property 4).
    """
    drawn = _aws_landscape_drawn_roles()
    assert "file_system" not in drawn, "fixture assumes the landscape draws no file_system"

    enumerable = sorted(
        r for r in drawn if r not in ("boundary", "network_boundary") and r in _ROLE_TO_NATIVE
    )
    resources = [_resource(_ROLE_TO_NATIVE[role], f"{role}-res") for role in enumerable]
    resources.append(_resource("AWS::EFS::FileSystem", "orphan-filesystem"))
    snapshot = _write_snapshot(tmp_path, {"all": resources})

    report = reconcile(snapshot, _AWS_LANDSCAPE, "aws")

    assert not report.eligible
    assert [om["resource"] for om in report.omissions] == ["orphan-filesystem"]
    assert {om["role"] for om in report.omissions} == {"file_system"}


# --------------------------------------------------------------------------- #
# Property: a landscape blocks iff some enumerated role is undrawn, always naming
# --------------------------------------------------------------------------- #

_PRESENTATION_AND_NEUTRAL = sorted(_ROLE_TO_NATIVE)


@settings(max_examples=100, deadline=None)
@given(
    drawn_roles_choice=st.lists(
        st.sampled_from(_PRESENTATION_AND_NEUTRAL), min_size=0, max_size=6, unique=True
    ),
    enumerated_choice=st.lists(
        st.sampled_from(_PRESENTATION_AND_NEUTRAL), min_size=1, max_size=6, unique=True
    ),
    include_unresolvable=st.booleans(),
)
def test_property_landscape_blocks_iff_enumerated_role_undrawn(
    tmp_path_factory: pytest.TempPathFactory,
    drawn_roles_choice: List[str],
    enumerated_choice: List[str],
    include_unresolvable: bool,
) -> None:
    """Property 4: a landscape is blocked exactly on the enumerated roles it omits.

    For any crafted (drawn role set, enumerated role set) pair:

    * the omitted role set is exactly ``enumerated - drawn`` (Requirement 2.3);
    * every omission names an enumerated resource of an omitted role;
    * an added unresolvable-role resource is never named (Requirement 2.5);
    * eligibility ⇔ no enumerated role is undrawn.

    Validates: Requirements 2.3, 2.5
    """
    tmp_path = tmp_path_factory.mktemp("recon")

    # One enumerated resource per role, named so we can assert on the names.
    resources = [
        _resource(_ROLE_TO_NATIVE[role], f"{role}-res") for role in enumerated_choice
    ]
    if include_unresolvable:
        resources.append(_resource("AWS::Glacier::Vault", "unresolvable-res"))
    snapshot = _write_snapshot(tmp_path, {"all": resources})

    diagram = _write_diagram(tmp_path, drawn_roles_choice, diagram_class="landscape")

    report = reconcile(snapshot, diagram, "aws")

    expected_omitted = set(enumerated_choice) - set(drawn_roles_choice)
    got_omitted_roles = {om["role"] for om in report.omissions}
    assert got_omitted_roles == expected_omitted

    # Every omission names the enumerated resource of its (omitted) role.
    for om in report.omissions:
        assert om["resource"] == f"{om['role']}-res"

    # The unresolvable resource is never an omission (Req 2.5).
    assert "unresolvable-res" not in {om["resource"] for om in report.omissions}

    # Eligibility is exactly "no enumerated role is undrawn".
    assert report.eligible == (not expected_omitted)


# --------------------------------------------------------------------------- #
# S2 (1.10.7): role-less resources are reported, never silently invisible
# --------------------------------------------------------------------------- #


def test_roleless_resources_are_counted_and_warned(tmp_path: Path, capsys) -> None:
    """One role-bearing and two unknown-type resources: the report stays
    eligible (role-less resources are never omissions) but counts and names the
    two the check could not see, and the CLI prints a WARNING line."""
    from rule_engine.reconcile import main as reconcile_main

    snapshot = _write_snapshot(
        tmp_path,
        {
            "storage": [
                _resource("aws::s3::bucket", "my-bucket"),
                _resource("AWS::Glacier::Vault", "cold-archive"),
            ],
            "analytics": [_resource("AWS::QuickSight::Dashboard", "partner-dash")],
        },
    )
    diagram = _write_diagram(tmp_path, ["object_store"], diagram_class="landscape")
    report = reconcile(snapshot, diagram, "aws")
    assert report.eligible
    assert report.enumerated_count == 3
    assert sorted(report.roleless) == ["cold-archive", "partner-dash"]
    data = report.to_dict()
    assert data["roleless_count"] == 2 and data["enumerated_count"] == 3
    assert sorted(data["roleless"]) == ["cold-archive", "partner-dash"]

    rc = reconcile_main(["--provider", "aws", "--snapshot", str(snapshot),
                         "--diagram", str(diagram)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[OK]" in out
    assert "[WARNING] 2 of 3" in out
    assert "mappings/roles.yaml" in out


def test_no_roleless_warning_when_every_resource_has_a_role(tmp_path: Path, capsys) -> None:
    from rule_engine.reconcile import main as reconcile_main

    snapshot = _write_snapshot(tmp_path, {"storage": [_resource("aws::s3::bucket", "b")]})
    diagram = _write_diagram(tmp_path, ["object_store"], diagram_class="landscape")
    assert reconcile_main(["--provider", "aws", "--snapshot", str(snapshot),
                           "--diagram", str(diagram)]) == 0
    assert "[WARNING]" not in capsys.readouterr().out
