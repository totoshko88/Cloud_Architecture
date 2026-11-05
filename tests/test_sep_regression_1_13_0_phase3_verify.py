"""SEP 01-13 regression proof against the final 1.13.0 engine (phase 3 verify).

The 13 production SEP diagrams (14 builders — 01 / 01b / 02 / 03 / 04 / 05 / 06 /
07 / 08 / 09 / 10 / 11 / 12 / 13) are the REAL diagrams the engine ships for. A
verbatim copy of the CURRENT SEPARCH builders lives under
``tests/fixtures/sep/separch/`` (``scripts/`` + ``.build-tools/`` mirror the
SEPARCH layout; ``companions/`` holds each ``NN-*.diagram.md``; ``mappings/local``
holds SEP's role/icon overlays so the SEP-specific roles — ``dial`` / ``argocd`` /
``neptune`` / … — resolve). This test:

* copies one builder into a TEMP dir that mirrors the SEPARCH layout (so
  ``Path(__file__).parent.parent`` and any ``ROOT``-relative write land in the
  temp, never in SEPARCH);
* symlinks ``mappings`` (SEP's local overlays) and ``assets`` into the temp CWD so
  the merged mapping tree resolves the SEP roles;
* builds the ``.drawio`` (``build()`` / ``_build()`` / a module-level writer),
  drops the matching committed companion beside it, and lints the pair with the
  FINAL engine;
* asserts the diagram is **lint-eligible** — ZERO ERROR / CRITICAL findings —
  under the stricter 1.13.0 rules.

Nothing is written into the SEPARCH workspace. Marked ``slow`` + ``sep``.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from rule_engine.cli import parse_artifacts
from rule_engine.linter import lint

_SEPARCH = Path(__file__).resolve().parent / "fixtures" / "sep" / "separch"
_SCRIPTS = _SEPARCH / "scripts"
_BUILD_TOOLS = _SEPARCH / ".build-tools"
_COMPANIONS = _SEPARCH / "companions"
_MAPPINGS = _SEPARCH / "mappings"
#: Vendor asset packs are NOT required: with the packs absent the engine embeds a
#: file-path icon reference (not a data-URI), which still lints eligible. If a
#: workspace ``assets/`` tree is present it is symlinked so the icons inline, but
#: the test does not depend on it.
_ASSETS = Path(__file__).resolve().parents[2] / "assets"

#: (diagram number, builder filename, output basename). Covers SEP 01-13.
_BUILDERS = [
    ("01", "build_01_sep_context.py", "01-sep-context"),
    ("01b", "build_01b_sep_context_c4.py", "01b-sep-context-c4"),
    ("02", "build_02_sep_summary.py", "02-sep-summary"),
    ("03", "build_sep_account_landscape.py", "03-sep-account-landscape"),
    ("04", "build_04_flow_lms_launch.py", "04-flow-lms-launch"),
    ("05", "build_flow_sandbox_lifecycle.py", "05-flow-sandbox-lifecycle"),
    ("06", "build_06_flow_task_verification.py", "06-flow-task-verification"),
    ("07", "build_07_flow_support_syndi.py", "07-flow-support-syndi"),
    ("08", "build_08_network_crossaccount.py", "08-network-crossaccount"),
    ("09", "build_09_crosscloud_landscape.py", "09-crosscloud-landscape"),
    ("10", "build_10_network_topology.py", "10-network-topology"),
    ("11", "build_11_hybrid_eks.py", "11-hybrid-eks"),
    ("12", "build_12_sep_access.py", "12-sep-access"),
    ("13", "build_13_sep_dataflow.py", "13-sep-dataflow"),
]


def _clear_mapping_caches() -> None:
    """Clear every CWD-dependent ``lru_cache`` that reads a mappings file, so a
    mapping loaded from another test's CWD cannot hide SEP's local overlays."""
    import rule_engine.icon_resolver as ir
    import rule_engine.reconcile as rec
    for mod in (ir, rec):
        for obj in vars(mod).values():
            clear = getattr(obj, "cache_clear", None)
            if callable(clear):
                clear()


def _locate(name: str):
    for base, sub in ((_SCRIPTS, "scripts"), (_BUILD_TOOLS, ".build-tools")):
        if (base / name).exists():
            return base / name, sub
    raise FileNotFoundError(name)


def _build_xml(num: str, name: str, tmp: Path) -> str:
    src, sub = _locate(name)
    (tmp / "scripts").mkdir(exist_ok=True)
    (tmp / ".build-tools").mkdir(exist_ok=True)
    dst = tmp / sub / name
    shutil.copy2(src, dst)
    # SEP's local overlays resolve the SEP-specific roles; assets back the icons.
    if _MAPPINGS.exists() and not (tmp / "mappings").exists():
        os.symlink(_MAPPINGS, tmp / "mappings")
    if _ASSETS.exists() and not (tmp / "assets").exists():
        os.symlink(_ASSETS, tmp / "assets")
    cwd = os.getcwd()
    os.chdir(tmp)
    # The mapping cache is keyed per provider and ignores a later CWD change, so
    # a mapping loaded from another test's CWD would hide SEP's local overlays
    # (``argocd`` / ``dial`` / …). Clear it so the SEP overlays under this temp
    # CWD's ``mappings/local`` are read.
    _clear_mapping_caches()
    try:
        spec = importlib.util.spec_from_file_location(f"sep_{num}", dst)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"sep_{num}"] = mod
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(mod)          # a module-level writer emits here
            xml = None
            for fn in ("build", "_build"):
                if hasattr(mod, fn):
                    xml = getattr(mod, fn)()
                    break
            if xml is None:
                drawios = sorted(tmp.rglob("*.drawio"))
                xml = drawios[-1].read_text(encoding="utf-8") if drawios else None
        return xml
    finally:
        os.chdir(cwd)
        sys.modules.pop(f"sep_{num}", None)


@pytest.mark.slow
@pytest.mark.sep
@pytest.mark.skipif(not _MAPPINGS.exists(),
                    reason="SEP local mappings not synced into the fixture")
@pytest.mark.parametrize("num,name,base", _BUILDERS, ids=[b[0] for b in _BUILDERS])
def test_sep_diagram_is_lint_eligible_on_the_final_engine(num, name, base):
    tmp = Path(tempfile.mkdtemp(prefix=f"sepreg_{num}_"))
    try:
        xml = _build_xml(num, name, tmp)
        assert xml and "<mxGraphModel" in xml, f"{name} produced no diagram XML"
        dpath = tmp / f"{base}.drawio"
        dpath.write_text(xml, encoding="utf-8")
        companion = _COMPANIONS / f"{base}.diagram.md"
        if companion.exists():
            shutil.copy2(companion, tmp / f"{base}.diagram.md")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            blocking = []
            for art in parse_artifacts(str(dpath)):
                for f in lint(art)["findings"]:
                    if f["severity"] in ("ERROR", "CRITICAL"):
                        blocking.append(f'{f["rule"]}:{f.get("reason", "")}')
        finally:
            os.chdir(cwd)
        assert blocking == [], f"SEP {num} ({base}) has blocking findings: {blocking}"
    finally:
        # Drop the SEP-CWD mappings from the cache so a later test re-reads its
        # own workspace mappings rather than SEP's local overlays.
        _clear_mapping_caches()
        shutil.rmtree(tmp, ignore_errors=True)
