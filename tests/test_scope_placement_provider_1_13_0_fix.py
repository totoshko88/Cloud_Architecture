"""1.13.0 fix (ITEM 6): ``scope-placement`` judges a node's ROLE against the
provider's Service Scope table (``profiles/service-scope.yaml``).

Before the fix the provider-dependent cases (``regional-in-vpc``,
``vpc-scoped-outside-vpc``) fired only from an explicit ``scope=`` token, so an
S3 bucket drawn inside a VPC linted clean.
"""
from __future__ import annotations

from rule_engine import icon_resolver
from rule_engine.geometry import Box, DiagramGeometry
from rule_engine.icon_refs import IconRef
from rule_engine.layout.base import provider_role_scope
from rule_engine.linter import Artifact, lint

_S3 = ("assets/vendor/aws-icons/Architecture-Service-Icons_07312026/Arch_Storage/32/"
       "Arch_Amazon-Simple-Storage-Service_32.svg")
_RDS = ("assets/vendor/aws-icons/Architecture-Service-Icons_07312026/Arch_Databases/32/"
        "Arch_Amazon-RDS_32.svg")
_LAMBDA = ("assets/vendor/aws-icons/Architecture-Service-Icons_07312026/Arch_Compute/32/"
           "Arch_AWS-Lambda_32.svg")
_AZ_SQL = "img/lib/azure2/databases/SQL_Database.svg"


def _geo(provider: str) -> DiagramGeometry:
    """account(0,0,2000,2000) ⊃ region(100,100,1600,1600) ⊃ network(200,200,1200,1200)."""
    style = lambda kind: icon_resolver.resolve_container(kind, provider)["style_string"]  # noqa: E731
    g = DiagramGeometry()
    g.containers = {
        "acct": Box("acct", 0, 0, 2000, 2000),
        "region": Box("region", 100, 100, 1600, 1600),
        "vpc": Box("vpc", 200, 200, 1200, 1200),
    }
    g.container_styles = {
        "acct": style("boundary"), "region": style("region"), "vpc": style("network_boundary"),
    }
    return g


def _scope_findings(g, refs, title):
    art = Artifact(kind="diagram", node_names=[], geometry=g, icon_refs=refs,
                   title_cell=title, diagram_type="flow")
    return [f for f in lint(art)["findings"] if f["rule"] == "scope-placement"]


def _place(g, nid, x, y, ref):
    g.nodes[nid] = Box(nid, x, y, 78, 78)
    g.node_styles[nid] = f"image;image={ref};"
    return IconRef(nid, "image", ref)


def test_table_loader():
    assert provider_role_scope("object_store", "aws") == "outside_vpc"
    assert provider_role_scope("managed_sql", "aws") == "network"
    assert provider_role_scope("managed_sql", "azure") == "outside_vpc"
    assert provider_role_scope("serverless_fn", "aws") is None   # VPC-attachable
    assert provider_role_scope("serverless_fn", "gcp") == "outside_vpc"
    assert provider_role_scope("file_system", "aws") is None
    assert provider_role_scope("object_store", "generic") is None


def test_aws_s3_inside_vpc_is_regional_in_vpc():
    g = _geo("aws")
    refs = [_place(g, "s3", 300, 300, _S3)]
    sp = _scope_findings(g, refs, "aws x — a / b | 2026-10-07 | v1")
    assert len(sp) == 1 and "regional-in-vpc:s3" in sp[0]["reason"], sp


def test_aws_rds_outside_vpc_is_vpc_scoped_outside_vpc():
    g = _geo("aws")
    refs = [_place(g, "rds", 130, 1500, _RDS)]   # in the region, below the vpc
    sp = _scope_findings(g, refs, "aws x — a / b | 2026-10-07 | v1")
    assert len(sp) == 1 and "vpc-scoped-outside-vpc:rds" in sp[0]["reason"], sp


def test_azure_sql_inside_vnet_is_regional_in_vpc():
    g = _geo("azure")
    refs = [_place(g, "sql", 300, 300, _AZ_SQL)]
    sp = _scope_findings(g, refs, "azure x — a / b | 2026-10-07 | v1")
    assert len(sp) == 1 and "regional-in-vpc:sql" in sp[0]["reason"], sp


def test_aws_lambda_inside_vpc_is_not_judged():
    g = _geo("aws")
    refs = [_place(g, "fn", 300, 300, _LAMBDA)]
    assert _scope_findings(g, refs, "aws x — a / b | 2026-10-07 | v1") == []


def test_multicloud_title_is_not_judged_by_role():
    g = _geo("aws")
    refs = [_place(g, "s3", 300, 300, _S3)]
    assert _scope_findings(g, refs, "multicloud x — a / b | 2026-10-07 | v1") == []


def test_unknown_icon_is_not_judged():
    g = _geo("aws")
    refs = [_place(g, "x", 300, 300, "assets/vendor/unknown/thing.svg")]
    assert _scope_findings(g, refs, "aws x — a / b | 2026-10-07 | v1") == []


def test_s3_in_the_regional_column_is_clean():
    g = _geo("aws")
    refs = [_place(g, "s3", 130, 1500, _S3), _place(g, "rds", 300, 300, _RDS)]
    assert _scope_findings(g, refs, "aws x — a / b | 2026-10-07 | v1") == []
