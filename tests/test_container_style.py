"""``container-style`` lint rule (hotfix 1.10.7).

The 1.10.0 quick run drew its AWS account box in the provider brand anchor
``#232F3E`` (Squid Ink) instead of the Account group colour ``#CD2264`` that
``mappings/aws-icons.yaml`` declares, and nothing caught it. ``container-style``
recognises every drawn Boundary container against the provider's declared
``containers.*.style`` and fails (ERROR) when its stroke / caption colour differs.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine import icon_resolver
from rule_engine.cli import parse_artifacts
from rule_engine.constants import PROVIDERS
from rule_engine.geometry import Box, DiagramGeometry
from rule_engine.linter import Artifact, lint

REPO_ROOT = Path(__file__).resolve().parents[1]
QUICK = REPO_ROOT / "tests" / "fixtures" / "drawio" / "quick-1.10.0"
QUICK_FIXTURES = (
    QUICK / "01-quick-partner-data-summary.drawio",
    QUICK / "02-quick-partner-data-landscape.drawio",
)
CORPUS = sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"), recursive=True))


def _findings(path, rule):
    out = []
    for art in parse_artifacts(str(path)):
        out += [f for f in lint(art)["findings"] if f["rule"] == rule]
    return out


def _mappings(*providers):
    return {p: icon_resolver.load_mapping(p)["containers"] for p in providers}


def _style(provider, kind):
    return icon_resolver.resolve_container(kind, provider)["style_string"]


def _geo(**styles):
    return DiagramGeometry(
        containers={cid: Box(cid, 0, 0, 400, 400) for cid in styles},
        container_styles=dict(styles),
    )


# --------------------------------------------------------------------------- #
# (a) the quick 1.10.0 fixtures: exactly one ERROR, on the account box
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", QUICK_FIXTURES, ids=lambda p: p.name)
def test_quick_black_account_is_one_container_style_error(path):
    found = _findings(path, "container-style")
    assert len(found) == 1, found
    f = found[0]
    assert f["severity"] == "ERROR"
    assert f["offenders"] == ["boundary-account"]
    assert "expected #CD2264 got #232F3E" in f["reason"]
    assert f["reason"].startswith("aws.boundary:")


# --------------------------------------------------------------------------- #
# (b) the shipped corpus is clean
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: str(Path(p).relative_to(REPO_ROOT)))
def test_corpus_has_no_container_style_finding(path):
    assert _findings(path, "container-style") == []


# --------------------------------------------------------------------------- #
# (c) unit tests on hand-built geometry
# --------------------------------------------------------------------------- #


def test_grIcon_match_passes():
    g = _geo(acct=_style("aws", "boundary"), vpc=_style("aws", "network_boundary"))
    assert geo.check_container_style(g, ["aws"], _mappings("aws")) == []


def test_grIcon_match_with_wrong_colour_fails():
    bad = _style("aws", "boundary").replace("#CD2264", "#232F3E")
    found = geo.check_container_style(_geo(acct=bad), ["aws"], _mappings("aws"))
    assert found == [
        ("acct", "aws.boundary:strokeColor expected #CD2264 got #232F3E; "
                 "fontColor expected #CD2264 got #232F3E")
    ]


def test_grIcon_candidates_narrowed_by_fill():
    # private and public subnets share group_security_group; fill tells them apart.
    pub = _style("aws", "public_subnet")
    assert geo.check_container_style(_geo(s=pub), ["aws"], _mappings("aws")) == []
    bad = pub.replace("strokeColor=#7AA116", "strokeColor=#00A4A6")
    found = geo.check_container_style(_geo(s=bad), ["aws"], _mappings("aws"))
    assert len(found) == 1 and found[0][1].startswith("aws.public_subnet:strokeColor")


def test_structural_signature_match_fails_on_colour():
    bad = _style("generic", "boundary").replace("#333333", "#00A000")
    found = geo.check_container_style(_geo(env=bad), ["generic"], _mappings("generic"))
    assert len(found) == 1
    assert found[0][0] == "env"
    assert "strokeColor expected #333333 got #00A000" in found[0][1]


def test_unrecognised_container_is_skipped():
    bespoke = "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFEEDD;strokeColor=#123456;dashed=0"
    assert geo.check_container_style(
        _geo(b=bespoke), list(PROVIDERS), _mappings(*PROVIDERS)
    ) == []


#: The pre-restyle generic/01 environment / network boxes (HEAD before 1.10.7
#: M2): green and blue, ``dashPattern=8 4`` and no caption alignment tokens.
_PRE_RESTYLE_GENERIC = (
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#00A000;"
    "fillColor=none;verticalAlign=top;fontColor=#00A000;fontSize=12",
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#0062AD;"
    "fillColor=none;verticalAlign=top;fontColor=#0062AD;fontSize=12",
)


@pytest.mark.parametrize("style", _PRE_RESTYLE_GENERIC)
def test_off_signature_hand_authored_box_is_not_recognised(style):
    # R1 (documented recall limit): recognition is precision-first, so a box
    # whose dashPattern / caption alignment differ from the declared style is
    # unrecognised and not judged, even though its colours are off-profile.
    assert geo.check_container_style(_geo(env=style), ["generic"], _mappings("generic")) == []


def test_lowercase_hex_is_accepted():
    lower = _style("aws", "boundary").replace("#CD2264", "#cd2264")
    assert geo.check_container_style(_geo(acct=lower), ["aws"], _mappings("aws")) == []


def test_multicloud_title_checks_all_providers():
    # An Azure VNet box (shape=label + Virtual Networks corner image) on a
    # "multicloud" diagram is recognised (all five profiles are candidates) and
    # judged; under an "aws" title no aws container has that signature, so it is
    # unrecognised and skipped.
    vnet = _style("azure", "network_boundary")
    stroke = geo._style_tokens(vnet)["strokeColor"]
    bad = vnet.replace(f"strokeColor={stroke}", "strokeColor=#000000")
    g = _geo(boundary_vnet=bad)
    base = dict(kind="diagram", node_names=[], geometry=g)
    multi = lint(Artifact(title_cell="multicloud x — a / b | 2026-10-06 | v1", **base))
    hits = [f for f in multi["findings"] if f["rule"] == "container-style"]
    assert len(hits) == 1 and hits[0]["severity"] == "ERROR"
    assert hits[0]["reason"].startswith("azure.network_boundary:strokeColor")
    aws_only = lint(Artifact(title_cell="aws x — a / b | 2026-10-06 | v1", **base))
    assert not [f for f in aws_only["findings"] if f["rule"] == "container-style"]


def test_closest_candidate_is_named_on_a_shared_signature():
    # GCP's project box shares the plain dashed-rectangle signature with AWS's
    # AZ box; on a multi-cloud diagram the reason names the closer one.
    bad = _style("gcp", "boundary").replace("#4285F4", "#000000")
    found = geo.check_container_style(_geo(p=bad), list(PROVIDERS), _mappings(*PROVIDERS))
    assert len(found) == 1
    assert found[0][1] == "gcp.boundary:strokeColor expected #4285F4 got #000000"


# --------------------------------------------------------------------------- #
# (d) overlay markers and bespoke grouping boxes are never judged
# --------------------------------------------------------------------------- #

#: The sanctioned spec-required-not-deployed overlay (red dashed box).
_OVERLAY = ("rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;"
            "strokeColor=#D64550;fontColor=#D64550;fontSize=12;"
            "overlay=spec-required-not-deployed")
#: A hand-drawn functional group ("Ingest") — a plain dashed borderless box.
_BESPOKE = ("rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;"
            "strokeColor=#666666;fontColor=#333333;fontSize=12")


def _container_style_hits(provider, **styles):
    art = Artifact(kind="diagram", node_names=[], geometry=_geo(**styles),
                   title_cell=f"{provider} x — a / b | 2026-10-06 | v1")
    return [f for f in lint(art)["findings"] if f["rule"] == "container-style"]


@pytest.mark.parametrize("provider", ["aws", "gcp", "generic"])
def test_overlay_box_is_not_a_container(provider):
    assert _container_style_hits(provider, ovl=_OVERLAY) == []


@pytest.mark.parametrize("provider", ["aws", "gcp", "generic"])
def test_bespoke_dashed_group_is_not_a_container(provider):
    assert _container_style_hits(provider, grp=_BESPOKE) == []


def test_overlay_exempts_even_a_declared_signature():
    # An overlay drawn with exactly AWS's AZ structure is still an overlay.
    az = _style("aws", "availability_domain")
    stroke = geo._style_tokens(az)["strokeColor"]
    ovl = az.replace(f"strokeColor={stroke}", "strokeColor=#D64550") + ";overlay=standby"
    assert _container_style_hits("aws", az=ovl) == []


def test_declared_az_box_off_colour_is_still_judged():
    # Narrowing recognition must not lose the declared kinds themselves.
    az = _style("aws", "availability_domain")
    stroke = geo._style_tokens(az)["strokeColor"]
    hits = _container_style_hits("aws", az=az.replace(f"strokeColor={stroke}", "strokeColor=#000000"))
    assert len(hits) == 1 and hits[0]["reason"].startswith("aws.availability_domain:strokeColor")


def test_overlay_and_bespoke_boxes_on_a_parsed_drawio(tmp_path):
    acct = _style("aws", "boundary")
    cells = [
        ('title', 'aws demo — 123456789012 / us-east-1 | 2026-10-06 | v1',
         'text;html=1;fontSize=12;', (30, 0, 400, 30)),
        ('boundary-account', 'Account', acct, (30, 40, 600, 400)),
        ('ovl', 'spec-required-not-deployed', _OVERLAY, (100, 120, 200, 200)),
        ('grp', 'Ingest', _BESPOKE, (350, 120, 200, 200)),
        ('legend', 'Legend&#10;spec-required-not-deployed', 'text;html=1;fontSize=12;',
         (700, 40, 200, 60)),
    ]
    body = "".join(
        f'<mxCell id="{cid}" value="{val}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        for cid, val, style, (x, y, w, h) in cells
    )
    path = tmp_path / "01-fp.drawio"
    path.write_text(
        '<mxfile><diagram id="d" name="p"><mxGraphModel gridSize="10"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>' + body +
        '</root></mxGraphModel></diagram></mxfile>',
        encoding="utf-8",
    )
    assert _findings(path, "container-style") == []


def test_rule_is_an_error_and_blocks_publication():
    bad = _style("aws", "boundary").replace("#CD2264", "#232F3E")
    res = lint(Artifact(kind="diagram", node_names=[], geometry=_geo(acct=bad),
                        title_cell="aws x — a / b | 2026-10-06 | v1"))
    assert any(f["rule"] == "container-style" and f["severity"] == "ERROR"
               for f in res["findings"])
    assert res["eligible_for_publication"] is False
