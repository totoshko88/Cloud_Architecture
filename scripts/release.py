#!/usr/bin/env python3
"""Release tooling: bump the version, run the local gate suite, publish a release.

Three subcommands replace the hand-run release sequence::

    python scripts/release.py bump 1.10.2 [--dry-run] [--date YYYY-MM-DD]
    python scripts/release.py preflight [--fast]
    python scripts/release.py publish [--dry-run] [--yes] [--skip-preflight]

``bump``
    Rewrites every version pin listed in ``rule_engine.version_pins.PINS`` (and
    nothing else, so historical prose such as "New in 1.10.0" is untouched), then
    turns an ``## [Unreleased]`` CHANGELOG section into ``## [X.Y.Z] - <today>``
    or, when there is none, inserts a skeleton section dated today. The date is
    the local system date, never a guess. ``--dry-run`` prints the diff only.

``preflight``
    Runs the same gates CI runs, in one command, with the project interpreter:
    version pins and CHANGELOG dates, example freshness, lint, icon, raster,
    snapshot, edge-alignment and reconcile gates, then the full test suite
    (``--fast`` skips the tests). Stops at nothing; reports every failure.

``publish``
    For a release branch named ``X.Y.Z`` that matches ``pyproject.toml``: pushes
    the branch, opens the PR (body = the CHANGELOG section), waits for the PR
    checks, merges, and only then tags ``vX.Y.Z`` on the **merge commit on main**
    and pushes the tag. The tag push is what triggers ``release.yml``, so tagging
    after the merge means nothing is released before the PR is accepted (the
    1.10.x releases tagged the branch commit before merging). Every command is
    printed first; nothing runs without confirmation unless ``--yes``.

If SSH push fails for lack of a loaded key, git operations retry over HTTPS
through the GitHub CLI credential helper (``gh auth git-credential``); the
``origin`` remote is never modified.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shlex
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]


def _ensure_project_interpreter() -> None:
    """Re-exec under ``.venv/bin/python`` when the current one lacks the deps."""
    try:
        import yaml  # noqa: F401
        import rule_engine  # noqa: F401
    except ImportError:
        venv = REPO / ".venv" / "bin" / "python"
        # Compare prefixes, not resolved paths: a venv interpreter is a symlink
        # to the base interpreter, so the two resolve to the same file.
        in_venv = Path(sys.prefix).resolve() == (REPO / ".venv").resolve()
        if venv.is_file() and not in_venv:
            os.execv(str(venv), [str(venv), *sys.argv])
        sys.path.insert(0, str(REPO / "src"))


_ensure_project_interpreter()
sys.path.insert(0, str(REPO / "src"))

from rule_engine.version_guard import (  # noqa: E402
    changelog_date_problems,
    latest_changelog_version,
    read_pyproject_version,
)
from rule_engine.version_pins import PINS, SEMVER_RE, read_pin, rewrite_pin  # noqa: E402

CHANGELOG = REPO / "CHANGELOG.md"
UNRELEASED_RE = re.compile(r"^## \[Unreleased\][^\n]*\n", re.MULTILINE | re.IGNORECASE)
FIRST_RELEASE_RE = re.compile(r"^## \[v?\d", re.MULTILINE)
PLACEHOLDER = "TODO: describe this release"

#: Snapshot -> diagram pairs the reconcile gate checks (mirrors ci.yml).
RECONCILE_PAIRS: Tuple[Tuple[str, str, str], ...] = (
    ("aws", "examples/aws/inventory-aws-123456789012-us-east-1-2026-09-22_1430",
     "examples/aws/01-aws-agent-platform.drawio"),
    ("generic", "examples/generic/inventory-generic-env-prod-region-1-2026-09-22_1430",
     "examples/generic/01-generic-reference-architecture.drawio"),
)


def _semver(v: str) -> Tuple[int, int, int]:
    a, b, c = (int(x) for x in v.split("."))
    return a, b, c


# --------------------------------------------------------------------------- #
# bump
# --------------------------------------------------------------------------- #


def changelog_with_release(text: str, version: str, day: date) -> str:
    """Return ``text`` with a ``## [version] - day`` section at the top."""
    heading = f"## [{version}] - {day.isoformat()}\n"
    if re.search(rf"^## \[v?{re.escape(version)}\]", text, re.MULTILINE):
        raise ValueError(f"CHANGELOG already has a [{version}] section")
    if UNRELEASED_RE.search(text):
        return UNRELEASED_RE.sub(heading, text, count=1)
    match = FIRST_RELEASE_RE.search(text)
    skeleton = f"{heading}\n### Fixed\n\n- {PLACEHOLDER}\n\n"
    if match is None:
        return text.rstrip("\n") + "\n\n" + skeleton
    return text[: match.start()] + skeleton + text[match.start():]


def cmd_bump(args: argparse.Namespace) -> int:
    new = args.version.lstrip("v")
    if not SEMVER_RE.match(new):
        print(f"error: {args.version!r} is not X.Y.Z", file=sys.stderr)
        return 2
    current = read_pyproject_version(REPO)
    if current and _semver(new) <= _semver(current) and not args.force:
        print(f"error: {new} is not newer than {current} (use --force)", file=sys.stderr)
        return 2
    day = date.fromisoformat(args.date) if args.date else date.today()

    edits: List[Tuple[Path, str, str]] = []
    for pin in PINS:
        path = REPO / pin.path
        if not path.is_file():
            if pin.required:
                print(f"error: required pin file missing: {pin.path}", file=sys.stderr)
                return 1
            continue
        old, new_text = rewrite_pin(REPO, pin, new)
        edits.append((path, old, new_text))
    old_cl = CHANGELOG.read_text(encoding="utf-8")
    edits.append((CHANGELOG, old_cl, changelog_with_release(old_cl, new, day)))

    for path, old, new_text in edits:
        rel = str(path.relative_to(REPO))
        if args.dry_run:
            sys.stdout.writelines(difflib.unified_diff(
                old.splitlines(True), new_text.splitlines(True), f"a/{rel}", f"b/{rel}", n=1))
        elif old != new_text:
            path.write_text(new_text, encoding="utf-8")
            print(f"bumped {rel}")
    if not args.dry_run:
        print(f"OK: {current} -> {new}, CHANGELOG dated {day.isoformat()}. "
              f"Fill in the CHANGELOG section, then run preflight.")
    return 0


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #


def pin_problems(root: Path = REPO) -> List[str]:
    """Every present pin must hold the ``pyproject.toml`` version."""
    expected = read_pyproject_version(root)
    problems: List[str] = []
    for pin in PINS:
        found = read_pin(root, pin)
        if found is None:
            if pin.required:
                problems.append(f"{pin.path}: required pin file is missing")
            continue
        if len(found) != pin.count:
            problems.append(f"{pin.path}: expected {pin.count} pin(s), found {len(found)}")
        for value in found:
            if value != expected:
                problems.append(f"{pin.path}: pins {value}, pyproject.toml says {expected}")
    newest = latest_changelog_version((Path(root) / "CHANGELOG.md").read_text(encoding="utf-8"))
    if newest != expected:
        problems.append(f"CHANGELOG.md newest section is {newest}, pyproject.toml says {expected}")
    return problems


def _gate_steps(fast: bool) -> List[Tuple[str, List[str]]]:
    py = sys.executable
    steps: List[Tuple[str, List[str]]] = [
        ("example freshness", [py, "scripts/regen_examples.py", "--check"]),
        ("lint", [py, "-m", "rule_engine.cli", "--all", "--fail-on", "error,critical"]),
        ("icon references", [py, "-m", "rule_engine.verify_icon", "--all", "--strict"]),
        ("raster budget", [py, "-m", "rule_engine.raster_gate"]),
        ("snapshot shape", [py, "-m", "rule_engine.snapshot_gate", "--root", "examples", "--strict"]),
    ]
    for provider, snap, diagram in RECONCILE_PAIRS:
        steps.append((f"reconcile {provider}", [py, "-m", "rule_engine.reconcile",
                                                "--provider", provider, "--snapshot", snap,
                                                "--diagram", diagram]))
    drawios = sorted(str(p.relative_to(REPO)) for p in (REPO / "examples").rglob("*.drawio"))
    for d in drawios:
        steps.append((f"edge alignment {d}", [py, "scripts/orthogonalise_drawio.py", "--check", d]))
    if not fast:
        steps.append(("test suite", [py, "-m", "pytest", "-q"]))
    return steps


def cmd_preflight(args: argparse.Namespace) -> int:
    failures: List[str] = []

    def report(name: str, problems: List[str]) -> None:
        if problems:
            failures.append(name)
            print(f"FAIL  {name}")
            for p in problems:
                print(f"        {p}")
        else:
            print(f"ok    {name}")

    report("version pins", pin_problems())
    report("changelog dates", changelog_date_problems(CHANGELOG.read_text(encoding="utf-8")))
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    for name, cmd in _gate_steps(args.fast):
        result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
        tail = (result.stdout + result.stderr).strip().splitlines()[-6:]
        report(name, [] if result.returncode == 0 else [f"exit {result.returncode}", *tail])
    if failures:
        print(f"\nBLOCKING: {len(failures)} gate(s) failed: {', '.join(failures)}")
        return 1
    print("\nOK: preflight passed" + (" (tests skipped: --fast)" if args.fast else ""))
    return 0


# --------------------------------------------------------------------------- #
# publish
# --------------------------------------------------------------------------- #


class Runner:
    """Print every command; run it only when not a dry run."""

    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run

    def __call__(self, cmd: Sequence[str], *, capture: bool = False,
                 check: bool = True) -> subprocess.CompletedProcess:
        print("  $ " + " ".join(shlex.quote(c) for c in cmd))
        if self.dry_run:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        result = subprocess.run(cmd, cwd=REPO, text=True, capture_output=capture)
        if check and result.returncode != 0:
            raise SystemExit(f"command failed (exit {result.returncode}): {' '.join(cmd)}\n"
                             f"{(result.stderr or '') if capture else ''}")
        return result


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, text=True, capture_output=True).stdout.strip()


def _https_url() -> str:
    name = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                          cwd=REPO, text=True, capture_output=True).stdout.strip()
    if not name:
        raise SystemExit("cannot resolve the GitHub repository (is `gh` authenticated?)")
    return f"https://github.com/{name}.git"


def _git_remote(run: Runner, *args: str) -> None:
    """``git <args> origin …``, retried over HTTPS via the gh credential helper."""
    result = run(["git", *args[:1], "origin", *args[1:]], capture=True, check=False)
    if result.returncode == 0:
        return
    err = result.stderr or ""
    if "publickey" in err or "Could not read from remote" in err:
        print("  SSH push failed; retrying over HTTPS with the gh credential helper")
        run(["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
             *args[:1], _https_url(), *args[1:]])
        return
    raise SystemExit(f"git {' '.join(args)} failed:\n{err}")


def _wait_for_checks(run: Runner, branch: str, attempts: int = 18, delay: float = 10.0) -> None:
    """Wait until GitHub has registered the PR's checks (up to ~3 minutes).

    Right after ``gh pr create`` the checks may not exist yet, and
    ``gh pr checks --watch`` then exits with "no checks reported" instead of
    waiting, which would let the merge step run without CI.
    """
    if run.dry_run:
        return
    import time

    for _ in range(attempts):
        result = subprocess.run(["gh", "pr", "checks", branch], cwd=REPO, text=True,
                                capture_output=True)
        if "no checks reported" not in (result.stdout + result.stderr):
            return
        time.sleep(delay)
    raise SystemExit(f"no checks were reported on {branch}; refusing to merge without CI")


def _theme(section: str) -> str:
    m = re.search(r"\*\*Theme:\s*(.+?)\*\*", section)
    return m.group(1).rstrip(".") if m else "release"


def cmd_publish(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(REPO / "scripts"))
    from changelog_section import extract_section

    version = read_pyproject_version(REPO)
    branch = _git("branch", "--show-current")
    tag = f"v{version}"
    problems: List[str] = []
    if branch != version:
        problems.append(f"current branch is {branch!r}; publish runs from the release branch {version!r}")
    if _git("status", "--porcelain"):
        problems.append("working tree is not clean; commit the release first")
    if _git("tag", "--list", tag):
        problems.append(f"tag {tag} already exists locally")
    section = extract_section(CHANGELOG.read_text(encoding="utf-8"), version) or ""
    if not section:
        problems.append(f"CHANGELOG.md has no [{version}] section")
    if PLACEHOLDER in section:
        problems.append("CHANGELOG section still contains the bump placeholder")
    problems += pin_problems()
    problems += changelog_date_problems(CHANGELOG.read_text(encoding="utf-8"))
    if problems:
        print("BLOCKING: cannot publish:")
        for p in problems:
            print(f"    - {p}")
        return 1

    if not args.skip_preflight and not args.dry_run:
        if cmd_preflight(argparse.Namespace(fast=False)) != 0:
            return 1

    title = f"{version}: {_theme(section)}"[:70]
    print(f"\nPublishing {tag} from branch {branch}: {title}")
    print("Steps: push branch -> open PR -> wait for checks -> merge -> tag the merge commit -> push tag")
    if not args.yes and not args.dry_run:
        if input("Proceed? This merges into main and triggers the release. [y/N] ").strip().lower() != "y":
            print("aborted")
            return 1

    run = Runner(args.dry_run)
    notes = REPO / ".git" / f"RELEASE_NOTES_{version}.md"
    if not args.dry_run:
        notes.write_text(section + "\n", encoding="utf-8")
    _git_remote(run, "push", "-u", branch)
    run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title,
         "--body-file", str(notes)])
    _wait_for_checks(run, branch)
    run(["gh", "pr", "checks", branch, "--watch", "--fail-fast"])
    run(["gh", "pr", "merge", branch, "--merge"])
    merge_sha = "<merge-commit>" if args.dry_run else subprocess.run(
        ["gh", "pr", "view", branch, "--json", "mergeCommit", "-q", ".mergeCommit.oid"],
        cwd=REPO, text=True, capture_output=True).stdout.strip()
    if not args.dry_run and not merge_sha:
        raise SystemExit("PR merged but no merge commit was reported; tag it by hand")
    _git_remote(run, "fetch", "main")
    run(["git", "tag", "-a", tag, merge_sha, "-m", title])
    _git_remote(run, "push", tag)
    run(["git", "checkout", "main"])
    run(["git", "merge", "--ff-only", "FETCH_HEAD"])
    if not args.dry_run:
        notes.unlink(missing_ok=True)
    print(f"\nOK: {tag} tagged on {merge_sha[:12]} and pushed; release.yml is running.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="release", description="Rule Engine release tooling.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bump", help="rewrite every version pin and date the CHANGELOG")
    b.add_argument("version")
    b.add_argument("--date", help="release date YYYY-MM-DD (default: today)")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--force", action="store_true", help="allow a non-increasing version")
    p = sub.add_parser("preflight", help="run the CI gate suite locally")
    p.add_argument("--fast", action="store_true", help="skip the pytest suite")
    u = sub.add_parser("publish", help="push, PR, wait, merge, then tag the merge commit")
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    u.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args(argv)
    return {"bump": cmd_bump, "preflight": cmd_preflight, "publish": cmd_publish}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
