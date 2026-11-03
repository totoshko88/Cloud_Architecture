"""1.13.0 (FEAT-005, task item 4c): the spec levers on the SEP fixtures.

Each 1.13.0 lever was proven on a synthetic spec in its own test file. This file
pins what each lever does on the real SEP diagram it was written for, so a
change that silently undoes it fails here:

* **L1** ``DiagramSpec.vpc_side="right-keep-regional-left"`` on the
  coordinate-free SEP 03 account landscape (``build_03_coordfree.py``);
* **L2** ``NodeSpec.exit_face="up"`` on the Syndicate Server and on the Lambda
  that feeds MongoDB Atlas, on the coordinate-free SEP 09 cross-cloud landscape
  (``build_09_coordfree.py``);
* **L5** ``build_diagram(container_caption_wrap=2)`` on the synced SEP 08
  network diagram: no edge crosses the long ``peer-ext`` caption;
* **L6** ``ContainerSpec(fit_content=True)`` on the asymmetric AZ (``az-b``)
  of the coordinate-free SEP 10 network topology (``build_10_coordfree.py``).

Every lever is applied in-test (``dataclasses.replace`` on the fixture's spec,
or a wrapped ``build_diagram``); the fixtures stay untouched. Each case asserts
upper bounds equal to the numbers measured in FEAT-005 (crossings X,
own-caption cuts, collinear pairs), so a regression fails while an improvement
passes. Lint: L1 is asserted eligible (zero ERROR / CRITICAL). The 08 / 09 / 10
fixtures carry ERRORs that no lever touches (long node captions outside their
box, ``container-padding`` ``caption-outside-container``; SEP 09's Syndicate
Server, an EC2, declared in an external band, ``scope-placement``), so for
L2 / L5 / L6 the assertion is that the lever adds no blocking finding beyond
that recorded builder-side set.
"""
from __future__ import annotations

import dataclasses
import functools
import importlib.util
import os
import shutil
from pathlib import Path

import pytest

from rule_engine import collinear_repair as col
from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.linter import lint

_SEP = Path(__file__).resolve().parent / "fixtures" / "sep"
_SCRIPTS = _SEP / "scripts"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _load(script: str, tag: str):
    """Import a fixture builder with cwd = the fixture root (asset paths are
    cwd-relative); restores cwd and the mapping cache afterwards."""
    from rule_engine.icon_resolver import _load_mapping_cached

    path = _SCRIPTS / script
    cwd = os.getcwd()
    os.chdir(_SEP)
    _load_mapping_cached.cache_clear()
    try:
        spec = importlib.util.spec_from_file_location(f"{path.stem}_{tag}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
        _load_mapping_cached.cache_clear()
    return module


def _run(module, fn):
    from rule_engine.icon_resolver import _load_mapping_cached

    cwd = os.getcwd()
    os.chdir(_SEP)
    _load_mapping_cached.cache_clear()
    try:
        return fn()
    finally:
        os.chdir(cwd)
        _load_mapping_cached.cache_clear()


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _crossings(g) -> int:
    return geo.edge_crossing_stats(g)[0]


def _metrics(text: str) -> dict:
    g = _geo(text)
    return {
        "X": _crossings(g),
        "own": len(geo.check_edge_crosses_own_label(g)),
        "col": len(col.collinear_pairs(g)),
    }


def _blocking(text: str, tmp_path: Path, basename: str):
    """ERROR / CRITICAL findings of ``text`` linted with the fixture companion."""
    src = tmp_path / f"{basename}.drawio"
    src.write_text(text, encoding="utf-8")
    companion = _SEP / f"{basename}.diagram.md"
    if companion.exists():
        shutil.copy(companion, tmp_path / companion.name)
    out = []
    for art in parse_artifacts(str(src)):
        out += [f for f in lint(art)["findings"] if f["severity"] in ("ERROR", "CRITICAL")]
    return out


def _findings(text: str, tmp_path: Path, basename: str, rule: str):
    src = tmp_path / f"{basename}.drawio"
    src.write_text(text, encoding="utf-8")
    companion = _SEP / f"{basename}.diagram.md"
    if companion.exists():
        shutil.copy(companion, tmp_path / companion.name)
    return [f for art in parse_artifacts(str(src)) for f in lint(art)["findings"]
            if f["rule"] == rule]


def _with_spec(module, patch):
    """Patch ``module._spec`` so ``module._build()`` lays out ``patch(spec)``."""
    original = module._spec
    module._spec = lambda: patch(original())
    return module


# --------------------------------------------------------------------------- #
# L1 — SEP 03 coordinate-free: vpc_side="right-keep-regional-left"
# --------------------------------------------------------------------------- #

#: Measured in FEAT-005. Without the lever: X 3, own 1 (e10), col 0, eligible,
#: ~130 s CPU. With it: X 6, own 0, col 0, eligible, ~21 s CPU. The lever keeps
#: the compute spine together left of the VPC and removes the own-caption cut,
#: at the price of three more crossings.
L1_BOUND = {"X": 6, "own": 0, "col": 0}


@pytest.mark.slow
@pytest.mark.sep
def test_l1_sep03_right_keep_regional_left_is_eligible_within_bounds(tmp_path):
    module = _with_spec(
        _load("build_03_coordfree.py", "l1"),
        lambda s: dataclasses.replace(s, vpc_side="right-keep-regional-left"),
    )
    text = _run(module, module._build)
    assert _blocking(text, tmp_path, "03-sep-account-landscape") == []
    m = _metrics(text)
    assert all(m[k] <= L1_BOUND[k] for k in L1_BOUND), m


# --------------------------------------------------------------------------- #
# L2 — SEP 09 coordinate-free: exit_face="up" on the Syndicate / Lambda sources
# --------------------------------------------------------------------------- #

L2_NODES = ("syndicate-server", "lambda")
#: Measured in FEAT-005, identical with and without the hint: X 5, own 2
#: (e10, e2), col 1 (e11/e8). The hint is INERT on this spec: it fires only for
#: an edge whose target is ``NodeSpec.external``, and every external target of
#: 09 (Atlas, DIAL, the sandbox fleets) is a member of an ``ext-*`` band;
#: declaring a band member ``external=True`` raises ``SpecError`` ("container
#: 'ext-ingress' has no children to size around"). Recorded as an engine gap
#: (the lever does not compose with external bands) in the phase-1 report.
L2_BOUND = {"X": 5, "own": 2, "col": 1}
#: Blocking findings of the 09 coordinate-free spec that the lever does not
#: touch (rule, reason): Atlas's caption outside ext-ingress; the Syndicate
#: Server (EC2, VPC-scoped) declared in the ext-integrations band.
L2_BUILDER_BLOCKING = {
    ("container-padding", "caption-outside-container"),
    ("scope-placement", "vpc-scoped-outside-vpc:syndicate-server"),
}


def _exit_up(spec):
    nodes = tuple(dataclasses.replace(n, exit_face="up") if n.id in L2_NODES else n
                  for n in spec.nodes)
    return dataclasses.replace(spec, nodes=nodes)


@pytest.mark.slow
@pytest.mark.sep
def test_l2_sep09_exit_face_up_adds_no_blocker_within_bounds(tmp_path):
    module = _load("build_09_coordfree.py", "l2")
    ids = {n.id for n in module._spec().nodes}
    assert set(L2_NODES) <= ids, ids
    _with_spec(module, _exit_up)
    text = _run(module, module._build)
    blocking = {(f["rule"], f["reason"]) for f in _blocking(text, tmp_path, "09-crosscloud-landscape")}
    assert blocking <= L2_BUILDER_BLOCKING, blocking
    m = _metrics(text)
    assert all(m[k] <= L2_BOUND[k] for k in L2_BOUND), m


# --------------------------------------------------------------------------- #
# L5 — SEP 08 (synced): build_diagram(container_caption_wrap=2)
# --------------------------------------------------------------------------- #

#: Measured in FEAT-005. Without the lever the peering legs e7-a / e8-a cross
#: the one-line ``peer-ext`` caption (``edge-crosses-container-label``); with
#: it the caption wraps onto two lines and no edge crosses it. X 1 and own 1
#: (e4) either way; collinear pairs go 1 -> 3 (e13/e8-a and e6/e8-a join
#: e5/e9-a), recorded as the bound. Integration trace: both builds start from
#: the same pre-finishing document (11 crossings, 6 pairs); with the shorter
#: wrapped caption the crossing repair may drop e8-a at x=480 through the
#: peer-ext caption column, next to e13 (x=480) and e6 (y=620). The collinear
#: shift runs after it but finds no admissible move for those two pairs, so
#: the extra pairs are a routing limit, not a skipped pass.
L5_BOUND = {"X": 1, "own": 1, "col": 3}
#: Blocking findings of the synced 08 that the lever does not touch: the CICD
#: and NAT captions run outside peer-ext / the VPC (caption-outside-container).
L5_BUILDER_BLOCKING = {("container-padding", "caption-outside-container")}


@pytest.mark.slow
@pytest.mark.sep
def test_l5_sep08_caption_wrap_clears_the_peer_ext_caption(tmp_path):
    module = _load("build_08_network_crossaccount.py", "l5")
    module.build_diagram = functools.partial(module.build_diagram, container_caption_wrap=2)
    text = _run(module, module._build)
    hits = _findings(text, tmp_path, "08-network-crossaccount", "edge-crosses-container-label")
    assert not any("peer-ext" in f["offenders"] for f in hits), hits
    blocking = {(f["rule"], f["reason"]) for f in _blocking(text, tmp_path, "08-network-crossaccount")}
    assert blocking <= L5_BUILDER_BLOCKING, blocking
    m = _metrics(text)
    assert all(m[k] <= L5_BOUND[k] for k in L5_BOUND), m


# --------------------------------------------------------------------------- #
# L6 — SEP 10 coordinate-free: fit_content on the asymmetric AZ
# --------------------------------------------------------------------------- #

#: The AZ whose content is narrower than its peer's (AZ-b: one node in
#: private-app, against two in AZ-a).
L6_FIT = ("az-b",)
#: Measured in FEAT-005. Without the lever az-b is equalized to az-a's 750 px
#: (VPC 1890 px wide); with it az-b is 438 px (VPC 1578 px). X 4 -> 3, own
#: 2 -> 1 (e8), col 0. One sibling-size-uniformity spread remains (228 px:
#: sub-app-b is still widened to its AZ-a subnet peer, 378 px, against
#: sub-pub-b 190 / sub-db-b 150); container-dead-space 0 either way.
#: Putting fit_content on sub-app-b instead cuts that spread to 110 px but
#: draws az-a over sub-batch-a (container-overlap ERROR), so it is not used.
L6_BOUND = {"X": 3, "own": 1, "col": 0, "spread": 1, "dead": 0}
L6_AZ_B_MAX_W = 438
L6_BUILDER_BLOCKING = {("container-padding", "caption-outside-container")}


def _fit(spec):
    containers = tuple(dataclasses.replace(c, fit_content=True) if c.id in L6_FIT else c
                       for c in spec.containers)
    return dataclasses.replace(spec, containers=containers)


def _l6_numbers(text: str):
    g = _geo(text)
    spread = [r for _, r in geo.check_sibling_size_uniformity(g)]
    dead = [c for c, _ in geo.check_container_dead_space(g)]
    return spread, dead


@pytest.mark.slow
@pytest.mark.sep
def test_l6_sep10_fit_content_keeps_sibling_spread_and_dead_space_in_bounds(tmp_path):
    module = _with_spec(_load("build_10_coordfree.py", "l6"), _fit)
    text = _run(module, module._build)
    blocking = {(f["rule"], f["reason"]) for f in _blocking(text, tmp_path, "10-network-topology")}
    assert blocking <= L6_BUILDER_BLOCKING, blocking
    assert _geo(text).containers["az-b"].w <= L6_AZ_B_MAX_W
    spread, dead = _l6_numbers(text)
    m = dict(_metrics(text), spread=len(spread), dead=len(dead))
    assert all(m[k] <= L6_BOUND[k] for k in L6_BOUND), (m, spread, dead)
