"""1.11.0 ITEM A: the ``scope-placement`` geometry lint.

A node drawn geometrically inside a boundary STRICTER than its EFFECTIVE role
scope allows, independent of the declared container — the geometry companion to
the ``layout()`` SpecError (which catches only the declared-container case). The
four cases:

* ``global-in-region``       — a global/edge service inside a region/VPC,
* ``regional-in-vpc``        — a regional service inside a VPC/network boundary,
* ``vpc-scoped-outside-vpc`` — a VPC-scoped service outside every VPC,
* ``external-in-account``    — an external actor/system inside the account.

Effective scope = a node's ``scope=`` style-token override else its role →
``ROLE_SCOPE`` (role recovered from the icon reference); an unresolvable scope is
NOT judged. ERROR on a network diagram, WARNING otherwise. Lint-only.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine import icon_resolver
from rule_engine.cli import parse_artifacts
from rule_engine.geometry import Box, DiagramGeometry, check_scope_placement
from rule_engine.icon_refs import IconRef
from rule_engine.linter import Artifact, lint

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = sorted(
    glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"), recursive=True)
)


def _aws_containers():
    return {"aws": icon_resolver.load_mapping("aws")["containers"]}


def _cstyle(kind: str) -> str:
    return icon_resolver.resolve_container(kind, "aws")["style_string"]


def _nested_geo():
    """account(0,0,2000,2000) ⊃ region(100,100,1600,1600) ⊃ vpc(200,200,1200,1200),
    all drawn with the real AWS container styles (unambiguous ``grIcon`` groups)."""
    g = DiagramGeometry()
    g.containers = {
        "acct": Box("acct", 0, 0, 2000, 2000),
        "region": Box("region", 100, 100, 1600, 1600),
        "vpc": Box("vpc", 200, 200, 1200, 1200),
    }
    g.container_styles = {
        "acct": _cstyle("boundary"),
        "region": _cstyle("region"),
        "vpc": _cstyle("network_boundary"),
    }
    return g


# --------------------------------------------------------------------------- #
# The four cases, as a pure geometry call with explicit scope/external closures.
# --------------------------------------------------------------------------- #


def test_scope_placement_four_cases():
    g = _nested_geo()
    # case 1: global cdn inside the region (left of the vpc) -> global-in-region
    g.nodes["cdn"] = Box("cdn", 150, 150, 78, 78)
    # case 2: regional object_store inside the vpc -> regional-in-vpc
    g.nodes["s3"] = Box("s3", 300, 300, 78, 78)
    # case 3: network compute inside the region but outside the vpc -> outside-vpc
    g.nodes["ec2"] = Box("ec2", 130, 1500, 78, 78)
    # case 4: external node inside the account -> external-in-account
    g.nodes["ext"] = Box("ext", 1800, 40, 78, 78)
    scope = {"cdn": "global", "s3": "regional", "ec2": "network", "ext": None}
    external = {"ext"}
    # The two provider-DEPENDENT cases (regional-in-vpc, vpc-scoped-outside-vpc)
    # fire ONLY from an explicit scope= override, so s3/ec2 are marked explicit.
    explicit = {"s3", "ec2"}
    out = dict(
        check_scope_placement(
            g,
            lambda n: scope.get(n),
            lambda n: n in external,
            ["aws"],
            _aws_containers(),
            scope_is_explicit=lambda n: n in explicit,
        )
    )
    assert out["cdn"] == "global-in-region:cdn"
    assert out["s3"] == "regional-in-vpc:s3"
    assert out["ec2"] == "vpc-scoped-outside-vpc:ec2"
    assert out["ext"] == "external-in-account:ext"


def test_provider_dependent_cases_need_explicit_scope():
    """regional-in-vpc / vpc-scoped-outside-vpc do NOT fire from the role
    fallback (scope_is_explicit False) — they require an explicit scope= token.

    Locks the owner's precision-over-noise narrowing so nobody re-introduces the
    noisy behaviour that flagged correct goldens (Azure SQL, EFS)."""
    g = _nested_geo()
    g.nodes["s3"] = Box("s3", 300, 300, 78, 78)   # regional role, inside the vpc
    g.nodes["ec2"] = Box("ec2", 130, 1500, 78, 78)  # network role, outside the vpc
    scope = {"s3": "regional", "ec2": "network"}
    # scope_is_explicit defaults to "never explicit" -> neither fires.
    out = check_scope_placement(
        g,
        lambda n: scope.get(n),
        lambda n: False,
        ["aws"],
        _aws_containers(),
    )
    assert out == []
    # A global role in the same spot still fires (provider-independent).
    g.nodes["cdn"] = Box("cdn", 150, 150, 78, 78)
    out = check_scope_placement(
        g,
        lambda n: "global" if n == "cdn" else scope.get(n),
        lambda n: False,
        ["aws"],
        _aws_containers(),
    )
    assert dict(out) == {"cdn": "global-in-region:cdn"}


def test_scope_placement_severity_network_vs_flow():
    """ERROR on a network diagram (diagram_type network / class landscape),
    WARNING otherwise."""
    g = _nested_geo()
    g.nodes["cdn"] = Box("cdn", 150, 150, 78, 78)
    g.node_styles["cdn"] = "image;image=assets/vendor/aws-icons/arch/cloudfront.svg;scope=global;"
    base = dict(
        kind="diagram",
        node_names=[],
        geometry=g,
        title_cell="aws x — a / b | 2026-10-07 | v1",
    )

    flow = lint(Artifact(diagram_type="flow", **base))
    sp = [f for f in flow["findings"] if f["rule"] == "scope-placement"]
    assert len(sp) == 1 and sp[0]["severity"] == "WARNING"
    assert "global-in-region:cdn" in sp[0]["reason"]

    net = lint(Artifact(diagram_type="network", **base))
    sp = [f for f in net["findings"] if f["rule"] == "scope-placement"]
    assert len(sp) == 1 and sp[0]["severity"] == "ERROR"

    land = lint(Artifact(diagram_class="landscape", **base))
    sp = [f for f in land["findings"] if f["rule"] == "scope-placement"]
    assert len(sp) == 1 and sp[0]["severity"] == "ERROR"


# --------------------------------------------------------------------------- #
# The WAF effective-scope nuance (design §2.4).
# --------------------------------------------------------------------------- #


def _waf_ref(cell_id: str) -> IconRef:
    # The AWS WAF icon reverse-maps to the ``waf`` role (ROLE_SCOPE -> global).
    return IconRef(cell_id, "image", "assets/vendor/aws-icons/arch/waf.svg")


def test_scope_placement_waf_nuance():
    g = _nested_geo()
    # waf1: default WAF (no scope override) inside the region -> role=waf=global
    #       -> global-in-region.
    g.nodes["waf1"] = Box("waf1", 150, 150, 78, 78)
    g.node_styles["waf1"] = "image;image=assets/vendor/aws-icons/arch/waf.svg;"
    # waf2: scope=regional WAF-on-ALB inside the region, outside the vpc -> fine.
    g.nodes["waf2"] = Box("waf2", 130, 1500, 78, 78)
    g.node_styles["waf2"] = "image;image=assets/vendor/aws-icons/arch/waf.svg;scope=regional;"
    # waf3: the same scope=regional WAF but drawn INSIDE the vpc -> regional-in-vpc.
    g.nodes["waf3"] = Box("waf3", 300, 300, 78, 78)
    g.node_styles["waf3"] = "image;image=assets/vendor/aws-icons/arch/waf.svg;scope=regional;"
    refs = [_waf_ref("waf1"), _waf_ref("waf2"), _waf_ref("waf3")]
    art = Artifact(
        kind="diagram",
        node_names=[],
        geometry=g,
        icon_refs=refs,
        title_cell="aws x — a / b | 2026-10-07 | v1",
        diagram_type="flow",
    )
    sp = [f for f in lint(art)["findings"] if f["rule"] == "scope-placement"]
    assert len(sp) == 1, sp
    reason = sp[0]["reason"]
    assert "global-in-region:waf1" in reason      # default WAF in region
    assert "regional-in-vpc:waf3" in reason        # regional WAF inside the vpc
    assert "waf2" not in reason                     # regional WAF outside vpc: fine


# --------------------------------------------------------------------------- #
# External exemption (R2-2): external OUTSIDE the account raises nothing.
# --------------------------------------------------------------------------- #


def test_scope_placement_external_outside_account_is_exempt():
    g = _nested_geo()
    # An external=1 peer node drawn to the RIGHT of the account (outside it).
    g.nodes["eks_peer"] = Box("eks_peer", 2100, 100, 78, 78)
    g.node_styles["eks_peer"] = "image;image=assets/vendor/aws-icons/arch/eks.svg;external=1;"
    out = check_scope_placement(
        g,
        lambda n: None,
        lambda n: g.node_styles.get(n, "").find("external=1") >= 0,
        ["aws"],
        _aws_containers(),
    )
    assert out == []  # external OUTSIDE the account -> no finding

    # Moved INSIDE the account -> external-in-account fires.
    g.nodes["eks_peer"] = Box("eks_peer", 1800, 60, 78, 78)
    out = check_scope_placement(
        g,
        lambda n: None,
        lambda n: g.node_styles.get(n, "").find("external=1") >= 0,
        ["aws"],
        _aws_containers(),
    )
    assert dict(out)["eks_peer"] == "external-in-account:eks_peer"


# --------------------------------------------------------------------------- #
# Default-inert: unresolvable scope and bespoke containers are never judged.
# --------------------------------------------------------------------------- #


def test_scope_placement_unresolvable_scope_is_skipped():
    g = _nested_geo()
    g.nodes["mystery"] = Box("mystery", 300, 300, 78, 78)  # inside the vpc
    # No scope token, no role -> scope_of returns None -> not judged.
    out = check_scope_placement(
        g, lambda n: None, lambda n: False, ["aws"], _aws_containers()
    )
    assert out == []


def test_scope_placement_unrecognised_container_is_skipped():
    g = DiagramGeometry()
    bespoke = "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFEEDD;strokeColor=#123456;dashed=0"
    g.containers = {"grp": Box("grp", 0, 0, 1000, 1000)}
    g.container_styles = {"grp": bespoke}
    g.nodes["s3"] = Box("s3", 100, 100, 78, 78)  # inside the bespoke box
    # regional node inside a box matching no declared containers.*.style -> skip.
    out = check_scope_placement(
        g, lambda n: "regional", lambda n: False, ["aws"], _aws_containers()
    )
    assert out == []


# --------------------------------------------------------------------------- #
# Corpus-inert: ZERO scope-placement findings across every shipped golden.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: Path(p).name)
def test_scope_placement_inert_on_corpus(path):
    findings = []
    for art in parse_artifacts(path):
        findings += [
            f for f in lint(art)["findings"] if f["rule"] == "scope-placement"
        ]
    assert findings == [], findings
