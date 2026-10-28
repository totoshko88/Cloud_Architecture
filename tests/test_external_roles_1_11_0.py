"""1.11.0 ITEM B — neutral external role classes + ``NodeSpec.external``.

Two behaviours (SEP audit E-02 / E-03 / F7, corrections R2-2 / R2-3):

* **Role resolution.** ``actor`` / ``users`` resolve to AWS *General* glyphs —
  the user/users icons, **never** the IAM Role shield (the E-02 defect).
  ``saas`` / ``on_prem_app`` resolve to the NEUTRAL General Client / Server
  glyphs, which is what every un-curated SaaS/on-prem system (GitLab, Jenkins,
  Jira, Confluence, Slack, …) uses — never a claimed brand mark and never a
  random AWS service icon (R2-3). Brand marks exist ONLY for the curated
  ``mongodb_atlas`` / ``redis`` / ``postgresql`` / ``keycloak`` roles.
  ``egress_only_igw`` resolves to the IGW-family glyph (F7, closest-official).
  Every new role is a committed ``icon-index.json`` row that resolves to an
  official pack asset (``source: product``), i.e. it verifies under
  ``rule-engine-verify-icon --strict``.

* **Placement.** A ``NodeSpec`` with ``external=True`` is forced OUTSIDE every
  cloud boundary — parented to the root layer, never the account / region / VPC
  — **regardless of a declared cloud ``container``** (R2-2), and it emits an
  ``external=1`` style token the ``scope-placement`` lint (FEAT-001) reads.
  ``external=False`` is byte-identical to a pre-ITEM-B spec.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rule_engine.icon_resolver import resolve_icon
from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

_MAPPINGS = Path(__file__).resolve().parents[1] / "mappings"


# --------------------------------------------------------------------------- #
# Role resolution
# --------------------------------------------------------------------------- #

# The IAM Role shield glyph (the E-02 defect) — the AWS access `principal` role.
_IAM_ROLE_SVG = "Res_AWS-Identity-Access-Management_Role_48.svg"


def _img(role: str) -> str:
    style = resolve_icon(role, "aws")["style_string"]
    assert "image=" in style, f"{role!r} must resolve to an image glyph"
    return style.split("image=", 1)[1]


def test_actor_users_resolve_to_general_glyphs_not_iam_role():
    # actor -> General User glyph; users -> General Users glyph.
    assert _img("actor").endswith("Res_General-Icons/Res_48_Light/Res_User_48_Light.svg")
    assert _img("users").endswith("Res_General-Icons/Res_48_Light/Res_Users_48_Light.svg")
    # NEVER the IAM Role shield.
    assert _IAM_ROLE_SVG not in _img("actor")
    assert _IAM_ROLE_SVG not in _img("users")


def test_saas_on_prem_app_are_neutral_general_glyphs_not_aws_service():
    # saas -> General Client glyph; on_prem_app -> General Server glyph. Both
    # are neutral white-background General icons (no service family), so an
    # un-curated SaaS/on-prem node is never a random AWS SERVICE icon (R2-3).
    saas = _img("saas")
    onp = _img("on_prem_app")
    assert saas.endswith("Res_General-Icons/Res_48_Light/Res_Client_48_Light.svg")
    assert onp.endswith("Res_General-Icons/Res_48_Light/Res_Server_48_Light.svg")
    # The General-Icons family is the neutral glyph set — not an Architecture
    # SERVICE icon (Arch_*). Assert we did not pick up a service glyph.
    for ref in (saas, onp):
        assert "/Res_General-Icons/" in ref
        assert "/Architecture-Service-Icons" not in ref
    # Neutral Squid-Ink anchor, never a service brand colour.
    assert resolve_icon("saas", "aws")["brand_hex"] == "#232F3E"
    assert resolve_icon("on_prem_app", "aws")["brand_hex"] == "#232F3E"


def test_egress_only_igw_resolves_to_igw_family_glyph():
    # F7: no dedicated egress-only IGW asset exists; the role uses the
    # IGW-family glyph (closest-official), identity carried in the caption.
    assert _img("egress_only_igw").endswith(
        "Res_Networking-Content-Delivery/Res_Amazon-VPC_Internet-Gateway_48.svg"
    )


def test_curated_brand_roles_keep_their_colorized_marks():
    # The four curated brand marks are the ONLY SaaS roles that claim a brand
    # glyph; they stay the colorized Simple-Icons leaves (unchanged by ITEM B).
    for role, slug in (
        ("mongodb_atlas", "mongodb"),
        ("redis", "redis"),
        ("postgresql", "postgresql"),
        ("keycloak", "keycloak"),
    ):
        assert f"assets/vendor/opensource-colorized/{slug}.svg" in _img(role)


@pytest.mark.parametrize("saas", ["gitlab", "jenkins", "jira", "confluence", "slack"])
def test_non_curated_saas_claim_no_brand_role(saas):
    # R2-3: GitLab / Jenkins / Jira / Confluence / Slack must NOT be added as
    # brand-mark roles this wave. They are therefore absent from roles.yaml and
    # from the committed icon-index — a spec draws them with the NEUTRAL `saas`
    # role, never a claimed brand mark. (Asserting absence here, rather than
    # calling resolve_icon, avoids the slow exact-slug asset-index bridge.)
    roles = yaml.safe_load((_MAPPINGS / "roles.yaml").read_text())["roles"]
    index = json.loads((_MAPPINGS / "icon-index.json").read_text())["roles"]
    assert saas not in roles
    assert saas not in index


def test_new_roles_are_committed_index_rows_resolving_to_official_assets():
    # Every new role is an icon-index row whose AWS entry resolved to an official
    # pack asset (source == "product", a real `assets/vendor/aws-icons/...` ref)
    # — i.e. it verifies under rule-engine-verify-icon --strict rather than
    # falling back silently. Only an aws: query is declared (AWS General glyphs),
    # so azure/gcp/oci are legitimately unresolved (no neutral vendor equivalent).
    index = json.loads((_MAPPINGS / "icon-index.json").read_text())["roles"]
    for role in ("actor", "users", "saas", "on_prem_app", "egress_only_igw"):
        assert role in index, f"{role!r} missing from committed icon-index"
        aws = index[role]["aws"]
        assert aws["source"] == "product", (role, aws)
        assert aws["ref"].startswith("assets/vendor/aws-icons/"), (role, aws)


def test_new_roles_live_in_bundled_tree_not_local_overlay():
    # R2-med-4: the new roles are in the engine BUNDLED mapping tree (repo-root
    # mappings/, the resolution-authoritative source), NOT a mappings/local/
    # overlay.
    roles = yaml.safe_load((_MAPPINGS / "roles.yaml").read_text())["roles"]
    aws = yaml.safe_load((_MAPPINGS / "aws-icons.yaml").read_text())["resources"]
    for role in ("actor", "users", "saas", "on_prem_app", "egress_only_igw"):
        assert role in roles, f"{role!r} missing from bundled roles.yaml"
        assert role in aws, f"{role!r} missing from bundled aws-icons.yaml"
    local = _MAPPINGS / "local" / "roles.yaml"
    if local.is_file():
        local_roles = (yaml.safe_load(local.read_text()) or {}).get("roles", {}) or {}
        for role in ("actor", "users", "saas", "on_prem_app", "egress_only_igw"):
            assert role not in local_roles, f"{role!r} must not be in mappings/local/"


def test_e01_bedrock_guardrails_already_present_skipped():
    # E-01 is already fixed (bundled) and SKIPPED: bedrock_guardrails maps to the
    # BASE Bedrock icon, not a non-existent guardrails asset.
    aws = yaml.safe_load((_MAPPINGS / "aws-icons.yaml").read_text())["resources"]
    assert "bedrock_guardrails" in aws
    assert "Arch_Amazon-Bedrock_48.svg" in aws["bedrock_guardrails"]["style"]


# --------------------------------------------------------------------------- #
# NodeSpec.external placement
# --------------------------------------------------------------------------- #


def _external_spec(external: bool) -> DiagramSpec:
    """An account⊃VPC spec with one workload inside the VPC and one node that
    DECLARES the same VPC container but may be ``external``."""
    nodes = (
        NodeSpec(id="lambda", role="serverless_fn", lane="workers", region="a",
                 slot=0, scope="network", container="vpc-a"),
        # Declares a cloud container (vpc-a). When external=True that container
        # MUST be ignored for placement and the node forced outside the account.
        NodeSpec(id="ext", role="saas", lane="workers", region="a", slot=1,
                 container="vpc-a", external=external),
    )
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None,
                      label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct",
                      label_key="vpc"),
    )
    edges = (EdgeSpec(id="e1", source="lambda", target="ext", marker="1"),)
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. x"),
        title="aws t — 1 / r | 2026-10-19 | v1",
    )


def _icon_inside(nbox, cbox) -> bool:
    """True when the node icon box overlaps a container box at all."""
    return not (
        nbox.x >= cbox.x + cbox.w
        or nbox.x + 78 <= cbox.x
        or nbox.y >= cbox.y + cbox.h
        or nbox.y + 78 <= cbox.y
    )


def test_external_true_node_placed_outside_the_account_despite_declared_vpc():
    placed = layout(_external_spec(external=True), strict=False)
    ext = placed.nodes["ext"]
    # Forced outside every cloud boundary (R2-2): neither the account nor the VPC.
    assert not _icon_inside(ext, placed.containers["acct"])
    assert not _icon_inside(ext, placed.containers["vpc-a"])
    # The in-VPC workload is unaffected.
    assert _icon_inside(placed.nodes["lambda"], placed.containers["vpc-a"])


def test_external_node_not_assigned_to_any_container():
    from rule_engine.layout.base import _assign_nodes_to_leaves

    spec = _external_spec(external=True)
    placed = layout(spec, strict=False)
    boxes = {nid: placed.nodes[nid] for nid in placed.nodes}
    assignment = _assign_nodes_to_leaves(spec, boxes)
    # The external node is a member of no container; the in-VPC node still is.
    assert "ext" not in assignment.get("vpc-a", [])
    assert "ext" not in assignment.get("acct", [])
    assert "lambda" in assignment.get("vpc-a", [])


def test_external_false_keeps_the_declared_vpc_membership():
    # external=False is the pre-ITEM-B behaviour: the declared VPC container is
    # honoured, so the node sits inside the VPC (and the account).
    placed = layout(_external_spec(external=False), strict=False)
    ext = placed.nodes["ext"]
    assert _icon_inside(ext, placed.containers["vpc-a"])


def test_external_true_emits_external_token_and_false_emits_nothing():
    from rule_engine.diagram_layout import Node, overlay_suffix

    on = Node(id="n", label="n", x=0, y=0, external=True)
    off = Node(id="n", label="n", x=0, y=0, external=False)
    assert ";external=1" in overlay_suffix(on)
    assert "external" not in overlay_suffix(off)


def test_nodespec_external_defaults_false_and_is_inert():
    # Additive + default-inert: a NodeSpec that never mentions `external` has it
    # False, so no token is ever emitted for a pre-ITEM-B spec.
    n = NodeSpec(id="x", role="serverless_fn", lane="workers", region="", slot=0)
    assert n.external is False
