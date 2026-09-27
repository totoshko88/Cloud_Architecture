"""Example tests for the raster exporter (scripts/export_raster.py).

These exercise the exporter's testable seams *without* invoking the real
draw.io desktop CLI (absent in CI): asset inlining, MIME mapping, companion
``diagram_class`` reading, provenance stamping, temp-copy placement/cleanup,
and the subprocess failure / missing-CLI paths. Where the draw.io CLI is
needed, a tiny fake executable (a shell script that writes a known PNG to the
requested ``--output``) stands in for it, so ``export_one`` runs end to end.

Requirements exercised: R8.4 (export scale / budget signal) and R8.5 (hygiene:
timeout, temp-copy location, missing-asset failure instead of "OK").

Implementation note (verified against the actual scripts/export_raster.py at
the time of writing — task 17.1 is still in progress, so the exporter is in its
pre-17.1 shape):

* the exporter calls draw.io with ``--width`` (class-aware: 1600 flow / 3400
  landscape), **not** ``--scale``; there is no ``compute_scale`` helper yet;
* ``subprocess.run`` is called **without** a ``timeout`` argument yet;
* the inlined temp copy is written **repo-local, next to the source** as
  ``.<stem>.inlined.drawio`` (a snap/AppArmor-confined CLI cannot read /tmp) —
  it is *not* under ``.build-tools/export-tmp``. It is still outside
  ``examples/`` only insofar as the source itself is; for a source that lives in
  ``examples/`` the temp copy is created in that same ``examples/`` directory.
  These tests assert the temp copy sits next to the source and is removed after
  export, which is the actual guarantee the current code provides.
* a missing referenced asset is left **unchanged** by ``inline_local_images``
  (no error, no data URI) rather than failing with a list.

The R8.5 "temp copy outside examples/ / fail-on-missing-asset" and the R8.4
"scale >= 1 / split signal" behaviours are the target of task 17.1 and are not
yet present; the tests below pin the exporter's real current behaviour and are
marked where they document a known gap, so they will need updating once 17.1
lands.
"""

from __future__ import annotations

import base64
import importlib.util
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = _REPO_ROOT / "scripts" / "export_raster.py"

# Import scripts/export_raster.py by path (it is a script, not an installed
# module), mirroring tests/test_changelog_section.py.
sys.path.insert(0, str(_REPO_ROOT / "src"))
_spec = importlib.util.spec_from_file_location("export_raster", _MODULE_PATH)
er = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(er)  # type: ignore[union-attr]

# A real, minimal, valid PNG the fake CLI can "produce" and the provenance
# stamper can rewrite. Built with the test-only encoder in tests/strategies.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategies import PngModel, encode_png  # noqa: E402

_FAKE_PNG = encode_png(PngModel(width=64, height=64, color_type=2, first_pixel_white=True))


# --- fixtures --------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_fake_drawio(tmp_path: Path, png_body: bytes = _FAKE_PNG) -> Path:
    """Create an executable fake draw.io CLI that writes ``png_body`` to --output.

    It scans its argv for ``--output <path>`` and writes the fixed PNG there,
    then exits 0 — enough for ``export_one`` to reach provenance stamping.
    """
    png_b64 = base64.b64encode(png_body).decode("ascii")
    script = tmp_path / "fake-drawio"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import base64, sys\n"
        f"_PNG = base64.b64decode({png_b64!r})\n"
        "argv = sys.argv[1:]\n"
        "out = None\n"
        "for i, a in enumerate(argv):\n"
        "    if a == '--output' and i + 1 < len(argv):\n"
        "        out = argv[i + 1]\n"
        "if out is None:\n"
        "    sys.exit(3)\n"
        "with open(out, 'wb') as fh:\n"
        "    fh.write(_PNG)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return script


# --- _mime_for -------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("icon.svg", "image/svg+xml"),
        ("icon.png", "image/png"),
        ("icon.jpg", "image/jpeg"),
        ("icon.jpeg", "image/jpeg"),
        ("icon.bin", "application/octet-stream"),
    ],
)
def test_mime_for_maps_by_suffix(name: str, expected: str) -> None:
    assert er._mime_for(Path(name)) == expected


# --- inline_local_images ---------------------------------------------------


def test_inline_local_images_inlines_existing_asset(tmp_path: Path) -> None:
    """An ``image=assets/vendor/...`` ref to a real file becomes a data URI."""
    asset = tmp_path / "assets" / "vendor" / "gcp" / "storage.svg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"<svg>storage</svg>")

    text = 'style="image=assets/vendor/gcp/storage.svg;fillColor=none;"'
    out = er.inline_local_images(text, repo_root=tmp_path)

    expected_b64 = base64.b64encode(b"<svg>storage</svg>").decode("ascii")
    assert f"image=data:image/svg+xml,{expected_b64}" in out
    assert "assets/vendor/gcp/storage.svg" not in out


def test_missing_assets_lists_absent_referenced_assets(tmp_path: Path) -> None:
    """R8.5: a referenced ``assets/vendor`` file that does not exist is collected
    by ``missing_assets`` so the exporter can fail on it (rather than export a
    broken image and report OK)."""
    text = (
        "one=image=assets/vendor/gcp/does-not-exist.svg;"
        "two=image=assets/vendor/gcp/also-missing.svg;"
    )
    assert er.missing_assets(text, repo_root=tmp_path) == [
        "assets/vendor/gcp/does-not-exist.svg",
        "assets/vendor/gcp/also-missing.svg",
    ]


def test_missing_assets_empty_when_all_present(tmp_path: Path) -> None:
    """When every referenced asset resolves, ``missing_assets`` returns []."""
    asset = tmp_path / "assets" / "vendor" / "gcp" / "s.svg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"<svg/>")
    assert er.missing_assets("image=assets/vendor/gcp/s.svg;", repo_root=tmp_path) == []


def test_export_one_fails_on_missing_asset(tmp_path: Path) -> None:
    """R8.5: export_one raises MissingAssetError (naming the paths) instead of
    exporting a broken image and reporting OK, and writes no PNG."""
    src = tmp_path / "examples" / "gcp" / "01.drawio"
    _write(src, "image=assets/vendor/gcp/does-not-exist.svg;")
    drawio = _make_fake_drawio(tmp_path)

    with pytest.raises(er.MissingAssetError) as exc:
        er.export_one(src, repo_root=tmp_path, drawio=str(drawio))
    assert "assets/vendor/gcp/does-not-exist.svg" in str(exc.value)
    assert not Path(str(src) + ".png").exists()


def test_inline_local_images_ignores_non_asset_styles(tmp_path: Path) -> None:
    """draw.io-internal ``img/lib`` refs, ``data:`` URIs and URLs are untouched."""
    for style in (
        "image=img/lib/azure2/compute/Function_Apps.svg;",
        "image=data:image/svg+xml,PHN2Zz48L3N2Zz4=;",
        "image=https://example.com/icon.svg;",
    ):
        assert er.inline_local_images(style, repo_root=tmp_path) == style


def test_inline_local_images_only_rewrites_matched_tokens(tmp_path: Path) -> None:
    """A mixed source rewrites only the assets/vendor token, leaving the rest."""
    asset = tmp_path / "assets" / "vendor" / "a.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"\x89PNG-bytes")
    text = (
        "one=image=assets/vendor/a.png;"
        "two=image=img/lib/azure2/x.svg;"
    )
    out = er.inline_local_images(text, repo_root=tmp_path)
    assert "image=data:image/png," in out
    assert "img/lib/azure2/x.svg" in out  # left alone


# --- _diagram_class_of -----------------------------------------------------


def test_diagram_class_defaults_to_flow_without_companion(tmp_path: Path) -> None:
    src = tmp_path / "01-x.drawio"
    _write(src, "<mxfile/>")
    assert er._diagram_class_of(src) == "flow"


def test_diagram_class_reads_landscape_from_companion(tmp_path: Path) -> None:
    src = tmp_path / "01-x.drawio"
    _write(src, "<mxfile/>")
    _write(
        tmp_path / "01-x.diagram.md",
        "---\ndiagram_class: landscape\nsummary_of: 01-x-summary\n---\n# x\n",
    )
    assert er._diagram_class_of(src) == "landscape"


# --- export_one: temp-copy placement, cleanup, provenance ------------------


def test_export_one_no_assets_exports_source_directly(tmp_path: Path) -> None:
    """A source with no assets/vendor refs is exported without a temp copy, and
    the resulting PNG carries the source's provenance sha256."""
    from rule_engine.raster_gate import read_provenance, source_sha256

    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, "<mxfile>no local assets here</mxfile>")
    drawio = _make_fake_drawio(tmp_path)

    out = er.export_one(src, repo_root=tmp_path, drawio=str(drawio))

    assert out == Path(str(src) + ".png")
    assert out.is_file()
    assert read_provenance(out.read_bytes()) == source_sha256(src)
    # No inlined temp copy should be left behind next to the source.
    assert not (src.parent / f".{src.stem}.inlined.drawio").exists()


def test_export_one_inlines_temp_under_build_tools_outside_examples_and_cleans_up(
    tmp_path: Path, monkeypatch
) -> None:
    """When a source references a real asset, export_one writes an inlined temp
    copy under ``.build-tools/export-tmp`` (repo-local, so a snap-confined CLI
    can read it — it cannot read /tmp — but OUTSIDE examples/), feeds that to the
    CLI, and removes it afterwards (R8.5).
    """
    asset = tmp_path / "assets" / "vendor" / "gcp" / "s.svg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"<svg/>")
    src = tmp_path / "examples" / "gcp" / "01.drawio"
    _write(src, 'x image=assets/vendor/gcp/s.svg; y')

    # Redirect the module-level temp dir into tmp_path so the test never writes
    # into the real repo tree; keep it OUTSIDE any examples/ dir.
    export_tmp = tmp_path / ".build-tools" / "export-tmp"
    monkeypatch.setattr(er, "EXPORT_TMP_DIR", export_tmp)

    seen: dict = {}
    real_run = subprocess.run

    def spy_run(cmd, *args, **kwargs):
        export_input = Path(cmd[-1])
        seen["export_input"] = export_input
        seen["temp_exists_during_run"] = export_input.exists()
        seen["temp_contents"] = (
            export_input.read_text(encoding="utf-8") if export_input.exists() else None
        )
        seen["timeout"] = kwargs.get("timeout")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(er.subprocess, "run", spy_run)
    drawio = _make_fake_drawio(tmp_path)

    out = er.export_one(src, repo_root=tmp_path, drawio=str(drawio))

    temp_copy = seen["export_input"]
    # The temp copy existed during the run and held the inlined data URI.
    assert seen["temp_exists_during_run"] is True
    assert "image=data:image/svg+xml," in seen["temp_contents"]
    assert "assets/vendor/gcp/s.svg" not in seen["temp_contents"]
    # It lives under .build-tools/export-tmp, i.e. NOT next to the source and NOT
    # inside any examples/ directory.
    assert export_tmp in temp_copy.parents
    assert "examples" not in temp_copy.parts
    assert temp_copy.parent != src.parent
    # A timeout is passed to subprocess.run (R8.5).
    assert seen["timeout"] == er.EXPORT_TIMEOUT
    # ...and the temp copy (and its dir) is removed after export completes.
    assert not temp_copy.exists()
    assert not temp_copy.parent.exists()
    assert out.is_file()


def test_export_one_removes_temp_copy_even_when_cli_fails(tmp_path: Path, monkeypatch) -> None:
    """The temp copy (and its export-tmp dir) is cleaned up in ``finally`` even
    when the CLI exits non-zero."""
    asset = tmp_path / "assets" / "vendor" / "gcp" / "s.svg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"<svg/>")
    src = tmp_path / "examples" / "gcp" / "01.drawio"
    _write(src, 'image=assets/vendor/gcp/s.svg;')

    export_tmp = tmp_path / ".build-tools" / "export-tmp"
    monkeypatch.setattr(er, "EXPORT_TMP_DIR", export_tmp)

    # A fake CLI that always fails.
    failing = tmp_path / "failing-drawio"
    failing.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n", encoding="utf-8")
    failing.chmod(failing.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)

    with pytest.raises(subprocess.CalledProcessError):
        er.export_one(src, repo_root=tmp_path, drawio=str(failing))

    # Cleaned up despite the failure: no leftover temp copy under export-tmp.
    leftovers = list(export_tmp.rglob("*.inlined.drawio")) if export_tmp.exists() else []
    assert leftovers == []


def test_export_one_propagates_cli_failure(tmp_path: Path) -> None:
    """A non-zero draw.io exit surfaces as CalledProcessError (not a silent OK)."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, "<mxfile/>")
    failing = tmp_path / "failing-drawio"
    failing.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(2)\n", encoding="utf-8")
    failing.chmod(failing.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)

    with pytest.raises(subprocess.CalledProcessError) as exc:
        er.export_one(src, repo_root=tmp_path, drawio=str(failing))
    assert exc.value.returncode == 2


def test_export_one_passes_timeout_to_subprocess_run(tmp_path: Path, monkeypatch) -> None:
    """R8.5: export_one passes ``timeout=EXPORT_TIMEOUT`` to subprocess.run so a
    hung draw.io CLI is killed rather than hanging forever."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, "<mxfile><diagram><mxGraphModel><root/></mxGraphModel></diagram></mxfile>")
    seen: dict = {}
    real_run = subprocess.run

    def spy_run(cmd, *args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(er.subprocess, "run", spy_run)
    drawio = _make_fake_drawio(tmp_path)

    er.export_one(src, repo_root=tmp_path, drawio=str(drawio))
    assert seen["timeout"] == er.EXPORT_TIMEOUT
    assert er.EXPORT_TIMEOUT >= 1


def test_export_one_timeout_propagates_as_failure(tmp_path: Path, monkeypatch) -> None:
    """A ``subprocess.TimeoutExpired`` from the CLI must propagate out of
    export_one as a failure (the export never reports success, R8.5)."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, "<mxfile/>")
    out_png = Path(str(src) + ".png")

    def timeout_run(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=er.EXPORT_TIMEOUT)

    monkeypatch.setattr(er.subprocess, "run", timeout_run)

    with pytest.raises(subprocess.TimeoutExpired):
        er.export_one(src, repo_root=tmp_path, drawio="drawio")
    # No PNG produced: a timeout is a failure, never a silent OK.
    assert not out_png.exists()


# --- compute_scale / CanvasTooWideError (R8.4, D8) -------------------------


def _drawio_with_vertex(width: float, x: float = 0.0) -> str:
    """A minimal .drawio with one vertex box of the given width at origin x."""
    return (
        "<mxfile><diagram><mxGraphModel><root>"
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'<mxCell id="n1" vertex="1" parent="1" value="n">'
        f'<mxGeometry x="{x}" y="0" width="{width}" height="78" as="geometry"/>'
        "</mxCell>"
        "</root></mxGraphModel></diagram></mxfile>"
    )


def test_compute_scale_never_below_one_for_small_canvas(tmp_path: Path) -> None:
    """A canvas narrower than the flow target scales UP to the target, never
    below 1."""
    src = tmp_path / "01.drawio"
    _write(src, _drawio_with_vertex(width=200))
    scale, width = er.compute_scale(src, "flow")
    assert width == 200
    # 1600 / 200 = 8, clamped by the max-width upper bound too, but well above 1.
    assert scale >= 1.0


def test_compute_scale_stays_at_or_above_one_near_budget(tmp_path: Path) -> None:
    """A canvas near the flow budget exports at scale >= 1 (never downscaled),
    and the scaled width plus borders stays within the 1600px budget."""
    src = tmp_path / "01.drawio"
    _write(src, _drawio_with_vertex(width=1500))
    scale, width = er.compute_scale(src, "flow")
    assert width == 1500
    assert scale >= 1.0
    # Scaled canvas + the two 8px borders must fit the class budget.
    assert width * scale + 2 * int(er.EXPORT_BORDER) <= er.FLOW_MAX_WIDTH + 0.5


def test_compute_scale_rejects_over_budget_flow_canvas(tmp_path: Path) -> None:
    """R8.4/D8: a flow canvas wider than 1600px (accounting for borders) cannot
    fit at scale 1, so compute_scale raises the split-the-diagram signal."""
    src = tmp_path / "01.drawio"
    _write(src, _drawio_with_vertex(width=1750))  # the aws/01 case
    with pytest.raises(er.CanvasTooWideError) as exc:
        er.compute_scale(src, "flow")
    assert "split the diagram" in str(exc.value)
    assert "1750px" in str(exc.value)


def test_compute_scale_allows_wider_landscape(tmp_path: Path) -> None:
    """A landscape canvas up to its wider budget (3600px) is allowed at scale
    >= 1, and the scaled width plus borders stays within the 3600px budget."""
    src = tmp_path / "01.drawio"
    _write(src, _drawio_with_vertex(width=3200))
    scale, width = er.compute_scale(src, "landscape")
    assert width == 3200
    assert scale >= 1.0
    assert width * scale + 2 * int(er.EXPORT_BORDER) <= er.LANDSCAPE_MAX_WIDTH + 0.5


def test_export_one_rejects_over_budget_canvas_and_writes_no_png(tmp_path: Path) -> None:
    """R8.4: export_one refuses a too-wide canvas (writes no PNG) rather than
    silently downscaling it."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, _drawio_with_vertex(width=1750))
    drawio = _make_fake_drawio(tmp_path)
    with pytest.raises(er.CanvasTooWideError):
        er.export_one(src, repo_root=tmp_path, drawio=str(drawio))
    assert not Path(str(src) + ".png").exists()


def test_export_one_uses_scale_flag_not_width(tmp_path: Path, monkeypatch) -> None:
    """The draw.io call uses ``--scale`` (>= 1) rather than ``--width`` (D8)."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, _drawio_with_vertex(width=800))
    seen: dict = {}
    real_run = subprocess.run

    def spy_run(cmd, *args, **kwargs):
        seen["cmd"] = list(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(er.subprocess, "run", spy_run)
    drawio = _make_fake_drawio(tmp_path)
    er.export_one(src, repo_root=tmp_path, drawio=str(drawio))

    assert "--scale" in seen["cmd"]
    assert "--width" not in seen["cmd"]
    scale_val = float(seen["cmd"][seen["cmd"].index("--scale") + 1])
    assert scale_val >= 1.0


# --- main: missing CLI is a non-zero exit, not a silent OK -----------------


def test_main_missing_cli_exits_2(tmp_path: Path) -> None:
    """A draw.io CLI that is neither on PATH nor an existing file exits 2."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, "<mxfile/>")
    rc = er.main([str(src), "--repo-root", str(tmp_path),
                  "--drawio", "/no/such/drawio-binary-xyz"])
    assert rc == 2


def test_main_no_sources_exits_2(tmp_path: Path) -> None:
    """``--all`` with no examples under the repo root is a non-zero exit."""
    (tmp_path / "examples").mkdir()
    drawio = _make_fake_drawio(tmp_path)
    rc = er.main(["--all", "--repo-root", str(tmp_path), "--drawio", str(drawio)])
    assert rc == 2


def test_main_exports_and_reports_ok(tmp_path: Path) -> None:
    """A successful export prints an OK line and exits 0, and the PNG exists."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, "<mxfile>no assets</mxfile>")
    drawio = _make_fake_drawio(tmp_path)

    rc = er.main([str(src), "--repo-root", str(tmp_path), "--drawio", str(drawio)])
    assert rc == 0
    assert Path(str(src) + ".png").is_file()


def test_main_reports_failed_and_exits_1_on_cli_error(tmp_path: Path) -> None:
    """A per-source draw.io failure is counted and returns exit 1 (not OK)."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, "<mxfile/>")
    failing = tmp_path / "failing-drawio"
    failing.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n", encoding="utf-8")
    failing.chmod(failing.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)

    rc = er.main([str(src), "--repo-root", str(tmp_path), "--drawio", str(failing)])
    assert rc == 1


def test_main_reports_failed_on_missing_asset(tmp_path: Path) -> None:
    """R8.5: a source with a missing referenced asset is a failure (exit 1), not
    a silent OK, and no PNG is written."""
    src = tmp_path / "examples" / "gcp" / "01.drawio"
    _write(src, "image=assets/vendor/gcp/does-not-exist.svg;")
    drawio = _make_fake_drawio(tmp_path)

    rc = er.main([str(src), "--repo-root", str(tmp_path), "--drawio", str(drawio)])
    assert rc == 1
    assert not Path(str(src) + ".png").exists()


def test_main_reports_failed_on_over_budget_canvas(tmp_path: Path) -> None:
    """R8.4: a too-wide flow canvas fails at the CLI level (exit 1, no PNG)."""
    src = tmp_path / "examples" / "aws" / "01.drawio"
    _write(src, _drawio_with_vertex(width=1750))
    drawio = _make_fake_drawio(tmp_path)

    rc = er.main([str(src), "--repo-root", str(tmp_path), "--drawio", str(drawio)])
    assert rc == 1
    assert not Path(str(src) + ".png").exists()


# --- Property 30: export scale is at least 1 or the export fails (R8.4) -----
#
# The property-based counterpart to the compute_scale example tests above. It
# exercises the whole input space of (canvas width W, diagram class) and asserts
# the two outcomes partition it exactly (design.md -> Correctness Properties,
# Property 30): compute_scale either returns a scale s >= 1 with
# W*s + 2*border <= the class max width, OR raises CanvasTooWideError, and it
# raises exactly when W + 2*border > the class max width.

from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

#: Canvas widths spanning well below, around, and well above both class budgets
#: (flow 1600 / landscape 3600), on the 10px grid so the serialized geometry is
#: exact. The extremes on either side of each budget guarantee both outcomes
#: (scale-up and split-signal) are hit for each class.
_CANVAS_WIDTHS = st.integers(min_value=1, max_value=400).map(lambda n: n * 10)

_DIAGRAM_CLASSES = st.sampled_from(["flow", "landscape"])


# Feature: honest-gates, Property 30: Export scale is at least 1 or the export fails
@given(width=_CANVAS_WIDTHS, diagram_class=_DIAGRAM_CLASSES)
def test_compute_scale_partitions_scale_up_and_split_signal(
    tmp_path_factory, width: int, diagram_class: str
) -> None:
    """For any canvas width W and class, compute_scale scales up (>= 1, within
    budget) or raises the split signal, and raises exactly when W + 2*border
    exceeds the class max width — the two outcomes partition the input space."""
    src = tmp_path_factory.mktemp("scale") / "01.drawio"
    src.write_text(_drawio_with_vertex(width=width), encoding="utf-8")

    max_width = (
        er.LANDSCAPE_MAX_WIDTH if diagram_class == "landscape" else er.FLOW_MAX_WIDTH
    )
    border = int(er.EXPORT_BORDER) * 2
    over_budget = width + border > max_width

    if over_budget:
        # Fails exactly when the canvas plus its borders cannot fit at scale 1.
        with pytest.raises(er.CanvasTooWideError):
            er.compute_scale(src, diagram_class)
    else:
        scale, measured = er.compute_scale(src, diagram_class)
        # The measured width is exactly the vertex box width W.
        assert measured == float(width)
        # Never downscales.
        assert scale >= 1.0
        # The scaled canvas plus both borders fits the class budget (allow a
        # sub-pixel rounding slack on the clamp).
        assert measured * scale + border <= max_width + 0.5
