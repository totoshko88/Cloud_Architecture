#!/usr/bin/env python3
"""Regenerate (or check) every generated example and its raster in one command.

Before this script, a regeneration was a sequence of hand-run commands: each
``build_*_example.py``, then ``build_example_snapshots.py``, then
``rule-engine-export-raster`` once per changed ``.drawio``. Forgetting one left a
stale file behind. This script owns the one table of Example_Generators (the
freshness test imports it, so the two cannot drift) and runs them in order.

Usage::

    python scripts/regen_examples.py            # regenerate + re-export stale rasters
    python scripts/regen_examples.py --check    # write nothing; exit 1 if anything is stale
    python scripts/regen_examples.py --no-raster

Exit codes: 0 everything fresh / regenerated; 1 something stale or failed;
2 usage error. A generator that exits 2 because the OCI stencil pack is not
fetched is reported as SKIPPED (a build-environment condition), not a failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
EXAMPLES = REPO / "examples"


@dataclass(frozen=True)
class Generator:
    """One Example_Generator: its script and the committed examples it owns."""

    script: str
    #: Committed ``.drawio`` paths (relative to ``examples/``) this script writes.
    examples: Tuple[str, ...]
    extra_args: Tuple[str, ...] = field(default_factory=tuple)


#: Every Example_Generator (9) and the Generated_Examples it owns (13).
GENERATORS: Tuple[Generator, ...] = (
    Generator("build_aws_ha_example.py",
              ("aws/02-aws-ha-multiregion-summary.drawio",
               "aws/02-aws-ha-multiregion-landscape.drawio")),
    Generator("build_azure_ha_example.py",
              ("azure/02-azure-ha-multiregion-summary.drawio",
               "azure/02-azure-ha-multiregion-landscape.drawio")),
    Generator("build_gcp_ha_example.py",
              ("gcp/02-gcp-ha-multiregion-summary.drawio",
               "gcp/02-gcp-ha-multiregion-landscape.drawio")),
    Generator("build_oci_ha_example.py",
              ("oci/02-oci-ha-multiregion-summary.drawio",
               "oci/02-oci-ha-multiregion-landscape.drawio")),
    Generator("build_aws_infra_example.py", ("aws/03-aws-hybrid-infrastructure.drawio",)),
    Generator("build_gcp_example.py", ("gcp/01-gcp-vertex-pipeline.drawio",)),
    Generator("build_oci_example.py", ("oci/01-oci-genai-stack.drawio",)),
    Generator("build_generic_example.py", ("generic/01-generic-reference-architecture.drawio",)),
    Generator("build_cross_cloud_example.py", ("cross-cloud/01-cross-cloud-composition.drawio",)),
)

#: The Snapshot data generator (per-domain JSON + per-resource docs); not a diagram.
SNAPSHOT_GENERATOR = "build_example_snapshots.py"

#: Messages a generator prints when it exits 2 for a missing OCI stencil pack.
MISSING_PACK_MARKERS = ("stencils not found", "fetch_assets")


def run_script(script: str, *args: str) -> subprocess.CompletedProcess:
    """Run ``python scripts/<script> <args>`` with the current interpreter."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )


def is_missing_pack(result: subprocess.CompletedProcess) -> bool:
    message = f"{result.stdout}\n{result.stderr}"
    return result.returncode == 2 and any(m in message for m in MISSING_PACK_MARKERS)


def _run_generators(check: bool) -> Tuple[List[str], List[str]]:
    """Return ``(failures, skipped)`` after running every generator."""
    failures: List[str] = []
    skipped: List[str] = []
    scripts = [g.script for g in GENERATORS] + [SNAPSHOT_GENERATOR]
    for script in scripts:
        result = run_script(script, *(["--check"] if check else []))
        tail = (result.stderr or result.stdout).strip().splitlines()
        last = tail[-1] if tail else ""
        if result.returncode == 0:
            print(f"  ok       {script}")
        elif is_missing_pack(result):
            skipped.append(script)
            print(f"  SKIPPED  {script} (OCI stencil pack not fetched: "
                  "python scripts/fetch_assets.py --only oci)")
        else:
            failures.append(script)
            state = "STALE" if check and result.returncode == 1 else f"FAILED(exit {result.returncode})"
            print(f"  {state:<8} {script}: {last}")
    return failures, skipped


def _stale_rasters() -> list:
    """Raster refs whose PNG is missing or whose provenance no longer matches."""
    sys.path.insert(0, str(REPO / "src"))
    from rule_engine.raster_gate import check_rasters

    return [r for r in check_rasters(EXAMPLES, REPO) if not r.exists or not r.provenance_ok]


def _export(stale: list) -> List[str]:
    from rule_engine.export_raster import export_one

    failures: List[str] = []
    for ref in stale:
        try:
            out = export_one(REPO / ref.source, repo_root=REPO)
            print(f"  exported {out.relative_to(REPO)}")
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            failures.append(ref.source)
            print(f"  FAILED   {ref.source}: {type(exc).__name__}: {exc}")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="regen_examples", description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 1 when any example or raster is stale")
    ap.add_argument("--no-raster", action="store_true",
                    help="skip the raster step (diagrams and snapshots only)")
    args = ap.parse_args(argv)

    print("generators" + (" (--check)" if args.check else ""))
    failures, skipped = _run_generators(args.check)

    if not args.no_raster:
        print("rasters" + (" (--check)" if args.check else ""))
        stale = _stale_rasters()
        if not stale:
            print("  ok       every raster matches its source")
        elif args.check:
            for ref in stale:
                why = "missing" if not ref.exists else "stale provenance"
                print(f"  STALE    {ref.png} ({why})")
            failures += [r.png for r in stale]
        else:
            failures += _export(stale)

    if skipped:
        print(f"skipped: {', '.join(skipped)}")
    if failures:
        print(f"BLOCKING: {len(failures)} item(s) stale or failed", file=sys.stderr)
        return 1
    print("OK: every generated example" + ("" if args.no_raster else " and raster")
          + (" is fresh" if args.check else " is regenerated"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
