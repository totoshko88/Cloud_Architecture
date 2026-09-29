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

    rule-engine-init                 # bootstrap / update the current directory
    rule-engine-init /path/to/ws     # bootstrap an explicit workspace
    rule-engine-init --force         # back up edited files, then overwrite
    rule-engine-init --check         # report state per file, write nothing

Lock file (R7). A normal run records ``.kiro/rule-engine-init.lock.json`` — the
engine version, which source tree was used, and the sha256 of every copied file.
On a later run the command classifies each bootstrap file against that lock:

  * **missing** — absent from the target: copied.
  * **current** — target hash equals the source hash: kept.
  * **stale**   — target hash equals the *lock* hash but the source moved on:
    updated (the file is an unedited engine file that an upgrade changed).
  * **edited**  — target hash differs from the lock (a user edit): kept on a
    bare run; backed up then overwritten under ``--force``.
  * **extra**   — present in the target's bootstrap dirs but not in the source:
    kept and reported.

``--check`` reports all five groups and exits non-zero if anything is missing or
stale; it never creates the target directory (R7.5). Nothing outside the target
workspace is ever written (R7.6).

Source resolution order (R7.7). When run from a repository checkout the repo tree
is preferred over the bundled ``_bootstrap`` payload (which may be stale):
  1. ``--source`` if given (recorded as ``explicit``);
  2. the repository checkout when this file's ``parents[2]`` holds a
     ``pyproject.toml`` naming ``rule-engine`` plus ``.kiro/steering`` (``repo``);
  3. the bundled payload shipped inside the installed package (``bundle``);
  4. the cloned power repo at ``~/.kiro/powers/repos/rule-engine-artifacts``
     (``power``).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
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
#   .kiro/agents    — diagram-author / inventory-collector / rule-engine-reviewer
#   mappings        — role table, per-provider icon maps, committed icon-index
#   schemas         — the Normalized Resource JSON Schema
_BOOTSTRAP_DIRS = (
    ".kiro/steering",
    ".kiro/hooks",
    # .kiro/agents (v1.6.0) — diagram-author, inventory-collector,
    # rule-engine-reviewer. A clean-room install copied the always-on rules but
    # none of the agents that apply them, so a fresh workspace had the standard
    # without the roles. Pure configuration, like steering.
    ".kiro/agents",
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

# The repository checkout root (src/rule_engine/init_workspace.py -> parents[2]).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Workspace-relative lock file (Glossary → Workspace_Lock_File).
LOCK_REL = ".kiro/rule-engine-init.lock.json"
LOCK_VERSION = 1

# --force backs edited files up here (outside .kiro/steering, so a backup is
# never loaded as steering). One timestamped subdir per --force run.
BACKUP_DIR_REL = ".kiro/rule-engine-init-backup"

# setuptools' package-data collection drops dot-directories, so the bundled
# payload stores the .kiro trees under DOT-FREE names ("kiro/..."). This maps a
# workspace-relative destination to where it lives inside the bundle. Keep in
# sync with build_backend._PAYLOAD. Non-.kiro dirs (mappings, schemas) are stored
# under their own name and need no remap.
_BUNDLE_MAP = {
    ".kiro/steering": "kiro/steering",
    ".kiro/hooks": "kiro/hooks",
    ".kiro/agents": "kiro/agents",
}


def _engine_version() -> str:
    """Return the installed engine version from the package.

    Prefer the package metadata (authoritative for an installed wheel); fall
    back to ``rule_engine.__version__`` and finally to a repo ``pyproject.toml``
    so a dev checkout still records a real version in the lock file.
    """
    try:
        from importlib import metadata as _md

        return _md.version("rule-engine")
    except Exception:  # noqa: BLE001 — not installed as a dist; fall through
        pass
    try:
        from rule_engine import __version__ as _v

        if _v and _v != "0.0.0":
            return _v
    except Exception:  # noqa: BLE001
        pass
    pyproject = _REPO_ROOT / "pyproject.toml"
    if pyproject.is_file():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version") and "=" in stripped:
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _within(root: Path, path: Path) -> bool:
    """True when ``path`` resolves inside ``root`` (write-safety guard, R7.6)."""
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


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


def _is_repo_checkout(root: Path) -> bool:
    """True when ``root`` is the engine's own repository checkout (R7.7).

    A repo checkout has a ``pyproject.toml`` naming ``rule-engine`` and the
    dot-prefixed ``.kiro/steering`` tree. The built ``_bootstrap`` bundle has
    neither, so this cleanly distinguishes the two.
    """
    if not (root / ".kiro" / "steering").is_dir():
        return False
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "rule-engine"' in text or "name = 'rule-engine'" in text


def resolve_source(explicit: Optional[str]) -> Optional[Path]:
    """Find the engine source tree that holds steering + mappings.

    Preference order (R7.7): an explicit ``--source``; the **repository
    checkout** when this file lives inside one (its tree is authoritative and
    the built ``_bootstrap`` may be stale); the bundled package payload (a
    pip/Power install with no repo); the cloned power repo.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    # Repository checkout first when this file is inside one — its tree is the
    # live source of truth, so an in-repo run never reads a stale bundle (R7.7).
    if _is_repo_checkout(_REPO_ROOT):
        candidates.append(_REPO_ROOT)
    # Bundled package payload: what a pip/Power install ships.
    candidates.append(_BUNDLED)
    # Installed engine repo root (dev case) even if the pyproject probe missed.
    candidates.append(_REPO_ROOT)
    candidates.append(_POWER_REPO)
    for root in candidates:
        if root.is_dir() and _looks_like_source(root):
            return root
    return None


def source_kind(source: Path, explicit: Optional[str]) -> str:
    """Classify a resolved source for the lock file's ``source`` field."""
    if explicit and Path(explicit).expanduser().resolve() == source:
        return "explicit"
    if source == _BUNDLED:
        return "bundle"
    if source == _POWER_REPO:
        return "power"
    if source == _REPO_ROOT:
        return "repo"
    return "explicit"


def _iter_files(src_dir: Path) -> Iterable[Path]:
    for p in sorted(src_dir.rglob("*")):
        if p.is_file():
            yield p


def _source_files(source: Path) -> dict[str, Path]:
    """Map every bootstrap file's workspace-relative path to its source path."""
    out: dict[str, Path] = {}
    for dest_rel in _BOOTSTRAP_DIRS:
        src_dir = _source_subdir(source, dest_rel)
        if not src_dir.is_dir():
            continue
        dest_base = Path(dest_rel)  # always the dot-prefixed workspace path
        for src_file in _iter_files(src_dir):
            rel_path = dest_base / src_file.relative_to(src_dir)
            out[rel_path.as_posix()] = src_file
    return out


def _target_bootstrap_files(target: Path) -> set[str]:
    """Every existing file under the target's bootstrap dirs (for extra detection)."""
    out: set[str] = set()
    for dest_rel in _BOOTSTRAP_DIRS:
        base = target / dest_rel
        if not base.is_dir():
            continue
        for p in _iter_files(base):
            out.add(p.relative_to(target).as_posix())
    return out


def load_lock(target: Path) -> dict:
    """Read the workspace lock file, or an empty structure when absent/unreadable."""
    lock_path = target / LOCK_REL
    if not lock_path.is_file():
        return {}
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _lock_hashes(lock: dict) -> dict[str, str]:
    files = lock.get("files")
    return dict(files) if isinstance(files, dict) else {}


def classify(
    source: Path,
    target: Path,
    lock: dict,
) -> dict[str, list[str]]:
    """Classify every bootstrap file into missing/current/stale/edited/extra.

    The state machine follows design §9:

    ======= ============================================ 
    missing  dst absent
    current  dst == src
    stale    dst == lock != src
    edited   dst != lock (or no lock and dst != src)
    extra    in target bootstrap dirs, not in source
    ======= ============================================ 
    """
    src_files = _source_files(source)
    lock_hashes = _lock_hashes(lock)
    groups: dict[str, list[str]] = {
        "missing": [],
        "current": [],
        "stale": [],
        "edited": [],
        "extra": [],
    }

    for rel, src_path in src_files.items():
        dst_path = target / rel
        if not dst_path.is_file():
            groups["missing"].append(rel)
            continue
        src_hash = _sha256_file(src_path)
        dst_hash = _sha256_file(dst_path)
        lock_hash = lock_hashes.get(rel)
        if dst_hash == src_hash:
            groups["current"].append(rel)
        elif lock_hash is not None and dst_hash == lock_hash:
            # Unedited engine file that the source has since moved past.
            groups["stale"].append(rel)
        else:
            # dst != lock (edited), or no lock recorded and dst != src.
            groups["edited"].append(rel)

    # Extra: present in the target's bootstrap dirs but not in the source. The
    # lock file itself is engine bookkeeping, not an extra bootstrap file.
    for rel in _target_bootstrap_files(target):
        if rel not in src_files and rel != LOCK_REL:
            groups["extra"].append(rel)

    for key in groups:
        groups[key].sort()
    return groups


def write_lock(
    target: Path,
    source: Path,
    src_files: dict[str, Path],
    copied_now: set[str],
    prior_lock: dict,
    *,
    explicit: Optional[str] = None,
) -> None:
    """Write the workspace lock recording the hash of every copied file (R7.1).

    A file written on this run is locked at its source hash. An **edited** file
    that was left in place keeps its *prior* lock hash, so it still reads as
    edited on the next run (design §9). A file present and matching the source
    but not copied this run is locked at its (identical) source hash.
    """
    prior = _lock_hashes(prior_lock)
    files: dict[str, str] = {}
    for rel, src_path in src_files.items():
        dst_path = target / rel
        if rel in copied_now:
            files[rel] = _sha256_file(src_path)
        elif dst_path.is_file():
            dst_hash = _sha256_file(dst_path)
            src_hash = _sha256_file(src_path)
            if dst_hash == src_hash:
                # Current / freshly-in-sync: lock at the shared hash.
                files[rel] = src_hash
            elif rel in prior:
                # Left-in-place edited file: keep its old lock hash.
                files[rel] = prior[rel]
            else:
                # No prior lock and dst != src: still user content, lock to dst
                # so a later engine change surfaces as stale, not edited-again.
                files[rel] = dst_hash
        elif rel in prior:
            files[rel] = prior[rel]

    lock = {
        "lock_version": LOCK_VERSION,
        "engine_version": _engine_version(),
        "source": source_kind(source, explicit),
        "files": dict(sorted(files.items())),
    }
    lock_path = target / LOCK_REL
    if not _within(target, lock_path):  # defensive (R7.6)
        raise ValueError(f"lock path escapes target: {lock_path}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def bootstrap(
    source: Path,
    target: Path,
    *,
    force: bool = False,
    check: bool = False,
    explicit: Optional[str] = None,
) -> dict[str, list[str]]:
    """Apply the lock-file state machine from ``source`` into ``target``.

    Returns the classification groups (missing/current/stale/edited/extra). In
    ``check`` mode nothing is written. On a bare run missing files are copied and
    stale files are updated; edited files are kept. Under ``--force`` edited files
    are backed up then overwritten, and stale files are updated. The lock file is
    (re)written after any write run.
    """
    lock = load_lock(target)
    groups = classify(source, target, lock)
    if check:
        return groups

    src_files = _source_files(source)
    copied_now: set[str] = set()
    backup_root: Optional[Path] = None

    def _copy(rel: str) -> None:
        src_file = src_files[rel]
        dst_file = target / rel
        if not _within(target, dst_file):  # defensive (R7.6)
            raise ValueError(f"destination escapes target: {dst_file}")
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        copied_now.add(rel)

    # missing -> copy (always); stale -> update (always).
    for rel in groups["missing"]:
        _copy(rel)
    for rel in groups["stale"]:
        _copy(rel)

    # edited -> keep on a bare run; under --force back up then overwrite (R7.4).
    if force:
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for rel in groups["edited"]:
            if backup_root is None:
                backup_root = target / BACKUP_DIR_REL / stamp
            backup_path = backup_root / rel
            if not _within(target, backup_path):  # defensive (R7.6)
                raise ValueError(f"backup path escapes target: {backup_path}")
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target / rel, backup_path)
            _copy(rel)

    write_lock(target, source, src_files, copied_now, lock, explicit=explicit)
    # Re-classify so the return value reflects the post-write state.
    return {**classify(source, target, load_lock(target)), "_copied": sorted(copied_now)}


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
        help="Explicit engine source tree (default: repo checkout, then the "
        "bundled payload, then the cloned power repo).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Back up every edited file, then overwrite it from the source.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report the state of each file (missing/edited/stale/extra) "
        "without writing anything; exits non-zero if any file is missing or "
        "stale. Does not create the target directory.",
    )
    parser.add_argument(
        "--with-assets", action="store_true",
        help="After copying, download the official provider icon packs into the "
        "target workspace (assets/vendor) and rebuild its icon-index.json. "
        "Required for AWS/GCP/OCI icons to render and to embed as data-URIs "
        "(since v1.10.2 they are file/stencil assets that are not committed; only "
        "Azure's bulk icons are built into draw.io).",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Print the installed engine version and exit. Lets the power "
        "bootstrap compare the installed engine against its pinned release "
        "and upgrade a stale install rather than reusing old rules.",
    )
    args = parser.parse_args(argv)

    # --version is answerable with no source tree (a bare install), so it is
    # handled before resolve_source, which can fail on a fresh machine.
    if args.version:
        print(_engine_version())
        return EXIT_OK

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

    # --check must NOT create the target directory (R7.5). A non-existent target
    # reports every source file as missing.
    if args.check:
        lock = load_lock(target) if target.is_dir() else {}
        groups = classify(source, target, lock)
        return _report_check(source, target, groups)

    target.mkdir(parents=True, exist_ok=True)
    result = bootstrap(source, target, force=args.force, explicit=args.source)
    copied = result.get("_copied", [])

    print(f"rule-engine-init: source {source} ({source_kind(source, args.source)})")
    print(f"rule-engine-init: target {target}")
    print(
        f"  copied {len(copied)} file(s); "
        f"kept {len(result['edited'])} edited, {len(result['extra'])} extra "
        f"(use --force to back up and overwrite edited files)."
    )
    if copied:
        for rel in copied[:12]:
            print(f"  + {rel}")
        if len(copied) > 12:
            print(f"  … and {len(copied) - 12} more")
    if result["edited"]:
        for rel in result["edited"][:12]:
            print(f"  ~ edited (kept): {rel}")
    print(f"  lock: {target / LOCK_REL}")
    print("Done. The .kiro/steering rules are now always-on in this workspace.")

    if args.with_assets:
        rc = _fetch_assets_into(target)
        if rc != EXIT_OK:
            return rc

    return EXIT_OK


def _report_check(source: Path, target: Path, groups: dict[str, list[str]]) -> int:
    """Print the five --check groups and return the exit code (R7.2)."""
    if not target.is_dir():
        print(f"rule-engine-init --check: target {target} does not exist; "
              f"all {len(groups['missing'])} file(s) are MISSING.")
    else:
        print(f"rule-engine-init --check: target {target}")

    def _emit(label: str, sign: str, rels: list[str]) -> None:
        if not rels:
            return
        print(f"  {label}: {len(rels)}")
        for rel in rels:
            print(f"    {sign} {rel}")

    _emit("MISSING", "+", groups["missing"])
    _emit("EDITED", "~", groups["edited"])
    _emit("STALE", "*", groups["stale"])
    _emit("EXTRA", "?", groups["extra"])

    blocking = len(groups["missing"]) + len(groups["stale"])
    if blocking:
        print(
            f"rule-engine-init --check: {len(groups['missing'])} missing, "
            f"{len(groups['stale'])} stale — run `rule-engine-init` to update."
        )
        return EXIT_FAIL
    print(
        f"OK: {len(groups['current'])} current, {len(groups['edited'])} edited, "
        f"{len(groups['extra'])} extra; nothing missing or stale."
    )
    return EXIT_OK


def _fetch_assets_into(target: Path) -> int:
    """Download the official icon packs into ``target`` and rebuild its index.

    Since v1.10.2 AWS, GCP and OCI all resolve their icons to files under
    ``assets/vendor`` (AWS + GCP as file-path SVGs, OCI as embedded stencils) —
    which are NOT committed (git-ignored) — and the generator EMBEDS each SVG as a
    ``data:image/svg+xml`` data-URI so the glyph renders in the draw.io editor.
    Without the packs a fresh workspace generates those icons in the legacy
    ``image=<path>`` form, which renders blank in the editor. Only Azure's bulk
    icons ship inside the draw.io app (``img/lib/azure2``); its two fetched-pack
    icons need the packs like the others. This fetches the packs into the target
    and rebuilds the target's ``mappings/icon-index.json`` so every reference
    resolves and embeds on disk. Every write stays inside ``target`` (R7.6).
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
          f"{target / 'assets' / 'vendor'} (AWS/GCP/OCI + Azure fetched icons)...")
    try:
        failures = fetch_assets.fetch_all(target)
    except Exception as exc:  # noqa: BLE001
        print(f"rule-engine-init: asset fetch failed: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if failures:
        print(f"rule-engine-init: {len(failures)} provider pack(s) failed: "
              f"{', '.join(failures)} (check network access).", file=sys.stderr)
        return EXIT_FAIL

    # Rebuild the target's icon-index against the freshly-fetched packs. The
    # manifests dir is pinned to the TARGET's mappings so the builder never
    # refreshes the engine's own committed manifests (R7.6 — writes stay inside
    # the target).
    try:
        from rule_engine import build_icon_sets_cli
    except Exception as exc:  # noqa: BLE001
        print(f"rule-engine-init: icon-index rebuild unavailable ({exc}).", file=sys.stderr)
        return EXIT_FAIL
    asset_root = target / "assets" / "vendor"
    out = target / "mappings" / "icon-index.json"
    manifests_dir = target / "mappings"
    if not (_within(target, asset_root) and _within(target, out)
            and _within(target, manifests_dir)):  # defensive (R7.6)
        print("rule-engine-init: asset paths escape target; refusing.", file=sys.stderr)
        return EXIT_FAIL
    # --manifests-dir pins the committed manifests (icon-index, oci digests,
    # azure2/aws4) into the TARGET's mappings/, so the builder never writes into
    # the engine's own mappings/ tree (R7.6 — writes stay inside the target).
    rc = build_icon_sets_cli.main([
        "--no-fetch",
        "--asset-root", str(asset_root),
        "--out", str(out),
        "--manifests-dir", str(manifests_dir),
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
