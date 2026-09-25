"""Bootstrap a target workspace with the Rule Engine's always-on rules.

The Rule Engine's authoritative rules live in ``.kiro/steering/*.md`` and the
icon/role mappings in ``mappings/`` — these are **workspace** files, not part of
the Kiro Power (a power carries only the skill + MCP). So when an agent runs the
skill in an *empty* workspace, the steering rules and mapping tables are absent:
the linter never runs, and the agent guesses icon colors and boundary placement.
That is the root cause of "diagrams generated in a fresh directory ignore the
rules".

``rule-engine-init`` closes that gap. It copies the engine's steering documents,
mapping tables, and schema into a target workspace so every subsequent agent turn
inherits the always-on rules and can resolve icons through the committed mappings
— exactly as in the engine's own repo.

Usage::

    rule-engine-init                 # bootstrap the current directory
    rule-engine-init /path/to/ws     # bootstrap an explicit workspace
    rule-engine-init --force         # overwrite existing copies
    rule-engine-init --check         # report what is missing, write nothing

Source resolution order (first that contains ``.kiro/steering``):
  1. ``--source`` if given;
  2. the installed engine repo root (this file's ``parents[2]``);
  3. the cloned power repo at ``~/.kiro/powers/repos/rule-engine-artifacts``.

The copy is idempotent: existing files are skipped unless ``--force`` is given.
Nothing outside the target workspace is ever written.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

# What a bootstrapped workspace needs for the always-on rules + icon resolution.
#   .kiro/steering  — the six always-on steering documents (the rules)
#   mappings        — role table, per-provider icon maps, committed icon-index
#   schemas         — the Normalized Resource JSON Schema
_BOOTSTRAP_DIRS = (
    ".kiro/steering",
    ".kiro/hooks",
    "mappings",
    "schemas",
)

_POWER_REPO = Path.home() / ".kiro" / "powers" / "repos" / "rule-engine-artifacts"


def _looks_like_source(root: Path) -> bool:
    return (root / ".kiro" / "steering").is_dir() and (root / "mappings").is_dir()


def resolve_source(explicit: Optional[str]) -> Optional[Path]:
    """Find the engine source tree that holds steering + mappings."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    # Installed engine repo root: src/rule_engine/init_workspace.py -> parents[2].
    candidates.append(Path(__file__).resolve().parents[2])
    candidates.append(_POWER_REPO)
    for root in candidates:
        if root.is_dir() and _looks_like_source(root):
            return root
    return None


def _iter_files(src_dir: Path) -> Iterable[Path]:
    for p in sorted(src_dir.rglob("*")):
        if p.is_file():
            yield p


def bootstrap(
    source: Path,
    target: Path,
    *,
    force: bool = False,
    check: bool = False,
) -> tuple[list[str], list[str]]:
    """Copy the bootstrap dirs from ``source`` into ``target``.

    Returns ``(written, skipped)`` as lists of workspace-relative paths. In
    ``check`` mode nothing is written; ``written`` lists what *would* be copied.
    """
    written: list[str] = []
    skipped: list[str] = []
    for rel in _BOOTSTRAP_DIRS:
        src_dir = source / rel
        if not src_dir.is_dir():
            continue
        for src_file in _iter_files(src_dir):
            rel_path = src_file.relative_to(source)
            dst_file = target / rel_path
            if dst_file.exists() and not force:
                skipped.append(str(rel_path))
                continue
            written.append(str(rel_path))
            if check:
                continue
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
    return written, skipped


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rule-engine-init",
        description="Bootstrap a workspace with the Rule Engine's always-on "
        "steering rules, icon mappings, and schema.",
    )
    parser.add_argument(
        "target", nargs="?", default=".",
        help="Target workspace directory (default: current directory).",
    )
    parser.add_argument(
        "--source", default=None,
        help="Explicit engine source tree (default: installed repo, then the "
        "cloned power repo).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite files that already exist in the target.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report what is missing without writing anything.",
    )
    parser.add_argument(
        "--with-assets", action="store_true",
        help="After copying, download the official provider icon packs into the "
        "target workspace (assets/vendor) and rebuild its icon-index.json. "
        "Required for GCP/OCI icons to actually render (AWS/Azure are built into "
        "draw.io; GCP/OCI icons are file/stencil assets that are not committed).",
    )
    args = parser.parse_args(argv)

    source = resolve_source(args.source)
    if source is None:
        print(
            "rule-engine-init: could not locate the engine source tree "
            "(needs .kiro/steering + mappings). Pass --source /path/to/repo.",
            file=sys.stderr,
        )
        return EXIT_FAIL

    target = Path(args.target).expanduser().resolve()
    if target == source:
        print(
            "rule-engine-init: target is the engine repo itself; nothing to do.",
            file=sys.stderr,
        )
        return EXIT_OK

    target.mkdir(parents=True, exist_ok=True)
    written, skipped = bootstrap(source, target, force=args.force, check=args.check)

    if args.check:
        if written:
            print(f"rule-engine-init --check: {len(written)} file(s) MISSING from "
                  f"{target} (run `rule-engine-init` to bootstrap):")
            for rel in written:
                print(f"  + {rel}")
            return EXIT_FAIL
        print(f"OK: workspace {target} already has the Rule Engine rules "
              f"({len(skipped)} file(s) present).")
        return EXIT_OK

    print(f"rule-engine-init: source {source}")
    print(f"rule-engine-init: target {target}")
    print(f"  copied {len(written)} file(s), skipped {len(skipped)} existing "
          f"(use --force to overwrite).")
    if written:
        for rel in written[:12]:
            print(f"  + {rel}")
        if len(written) > 12:
            print(f"  … and {len(written) - 12} more")
    print("Done. The .kiro/steering rules are now always-on in this workspace.")

    if args.with_assets:
        rc = _fetch_assets_into(target)
        if rc != EXIT_OK:
            return rc

    return EXIT_OK


def _fetch_assets_into(target: Path) -> int:
    """Download the official icon packs into ``target`` and rebuild its index.

    AWS/Azure icons ship inside the draw.io app, but GCP (file-path SVGs) and OCI
    (embedded stencils) resolve to files under ``assets/vendor`` — which are NOT
    committed (git-ignored). Without them a GCP/OCI diagram renders empty boxes in
    a fresh workspace. This fetches the packs into the target and rebuilds the
    target's ``mappings/icon-index.json`` so those references resolve on disk.
    """
    try:
        from rule_engine import fetch_assets
    except Exception as exc:  # noqa: BLE001
        print(f"rule-engine-init: --with-assets unavailable ({exc}).", file=sys.stderr)
        return EXIT_FAIL

    if not _sources_path(target).is_file():
        print("rule-engine-init: --with-assets needs mappings/asset-sources.yaml "
              "in the target (was the copy step skipped?).", file=sys.stderr)
        return EXIT_FAIL

    print("rule-engine-init: fetching official icon packs into "
          f"{target / 'assets' / 'vendor'} (GCP/OCI icons)...")
    try:
        failures = fetch_assets.fetch_all(target)
    except Exception as exc:  # noqa: BLE001
        print(f"rule-engine-init: asset fetch failed: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if failures:
        print(f"rule-engine-init: {len(failures)} provider pack(s) failed: "
              f"{', '.join(failures)} (check network access).", file=sys.stderr)
        return EXIT_FAIL

    # Rebuild the target's icon-index against the freshly-fetched packs.
    try:
        from rule_engine import build_icon_sets_cli
    except Exception as exc:  # noqa: BLE001
        print(f"rule-engine-init: icon-index rebuild unavailable ({exc}).", file=sys.stderr)
        return EXIT_FAIL
    asset_root = target / "assets" / "vendor"
    out = target / "mappings" / "icon-index.json"
    rc = build_icon_sets_cli.main([
        "--no-fetch", "--asset-root", str(asset_root), "--out", str(out),
    ])
    if rc != 0:
        print("rule-engine-init: icon-index rebuild failed.", file=sys.stderr)
        return EXIT_FAIL
    print("rule-engine-init: assets fetched and icon-index rebuilt. GCP/OCI icons "
          "now resolve in this workspace.")
    return EXIT_OK


def _sources_path(root: Path) -> Path:
    return root / "mappings" / "asset-sources.yaml"


if __name__ == "__main__":
    raise SystemExit(main())
