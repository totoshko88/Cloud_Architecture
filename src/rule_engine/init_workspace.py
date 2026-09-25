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

Source resolution order (first that contains ``.kiro/steering`` + ``mappings``):
  1. ``--source`` if given;
  2. the bundled payload shipped inside the installed package
     (``rule_engine/_bootstrap``) — present in every pip/Power install, so this
     works with no repo checkout at all;
  3. the installed engine repo root (this file's ``parents[2]``) — the dev/repo
     case;
  4. the cloned power repo at ``~/.kiro/powers/repos/rule-engine-artifacts``.

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

# What a bootstrapped workspace needs for the always-on rules + icon resolution,
# expressed as WORKSPACE-relative destinations (always dot-prefixed for .kiro):
#   .kiro/steering  — the six always-on steering documents (the rules)
#   .kiro/hooks     — the lint-on-save / validate-on-task / bootstrap-check hooks
#   mappings        — role table, per-provider icon maps, committed icon-index
#   schemas         — the Normalized Resource JSON Schema
_BOOTSTRAP_DIRS = (
    ".kiro/steering",
    ".kiro/hooks",
    "mappings",
    "schemas",
    # profiles/terminology.yaml — the terminology source of truth that
    # rule_engine.constants loads. Copying it lets a bootstrapped workspace also
    # run the engine from its own root (repo-root path resolution).
    "profiles",
)

_POWER_REPO = Path.home() / ".kiro" / "powers" / "repos" / "rule-engine-artifacts"

# Bundled payload copied into the package at build time (see build_backend.py).
# Present in every pip / Kiro-Power install, so rule-engine-init can bootstrap a
# workspace with no repo checkout. This is the primary source for a new user.
_BUNDLED = Path(__file__).resolve().parent / "_bootstrap"

# setuptools' package-data collection drops dot-directories, so the bundled
# payload stores the .kiro trees under DOT-FREE names ("kiro/..."). This maps a
# workspace-relative destination to where it lives inside the bundle. Keep in
# sync with build_backend._PAYLOAD. Non-.kiro dirs (mappings, schemas) are stored
# under their own name and need no remap.
_BUNDLE_MAP = {
    ".kiro/steering": "kiro/steering",
    ".kiro/hooks": "kiro/hooks",
}


def _source_subdir(source: Path, dest_rel: str) -> Path:
    """Return the directory inside ``source`` that holds ``dest_rel``.

    A repo source stores files at the dot-prefixed path (``.kiro/steering``); the
    bundled package payload stores them dot-free (``kiro/steering``). Prefer the
    dot-prefixed layout, fall back to the bundle's dot-free layout.
    """
    direct = source / dest_rel
    if direct.is_dir():
        return direct
    remapped = _BUNDLE_MAP.get(dest_rel)
    if remapped:
        return source / remapped
    return direct


def _looks_like_source(root: Path) -> bool:
    """True when ``root`` holds a usable payload (repo dot layout OR bundle layout)."""
    has_steering = (root / ".kiro" / "steering").is_dir() or (
        root / "kiro" / "steering"
    ).is_dir()
    return has_steering and (root / "mappings").is_dir()


def resolve_source(explicit: Optional[str]) -> Optional[Path]:
    """Find the engine source tree that holds steering + mappings.

    Preference order: an explicit ``--source``; the payload bundled inside the
    installed package (works with no repo); the installed repo root (dev case);
    the cloned power repo. The bundled payload comes before the repo root so a
    normal install self-configures even when the caller sits inside an unrelated
    checkout.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    # Bundled package payload first: this is what a pip/Power install ships.
    candidates.append(_BUNDLED)
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
    for dest_rel in _BOOTSTRAP_DIRS:
        src_dir = _source_subdir(source, dest_rel)
        if not src_dir.is_dir():
            continue
        dest_base = Path(dest_rel)  # always the dot-prefixed workspace path
        for src_file in _iter_files(src_dir):
            # Reconstruct the workspace-relative path from the destination base
            # plus the file's position within the source subdir — so a dot-free
            # bundle path ("kiro/steering/x.md") lands at ".kiro/steering/x.md".
            rel_path = dest_base / src_file.relative_to(src_dir)
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
