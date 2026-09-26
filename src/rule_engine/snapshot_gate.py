"""Validate an inventory Snapshot folder against ``inventory-standards.md`` (v1.6.0).

Why this exists
---------------
The linter checks the *contents* of individual snapshot files: every Markdown
document goes through the ``frontmatter`` CRITICAL gate, and every snapshot JSON
goes through the ``secret-safety`` CRITICAL gate. Nothing checked the **shape of
the snapshot folder** — and a from-scratch install showed exactly why that
matters.

In that clean-room run the agent collected an AWS account by shelling out to the
provider CLI and hand-writing the files, rather than going through
:mod:`rule_engine.collector`. The result linted completely clean while breaking
two mandated contracts:

* ``resources/`` was created but left **empty**, though the snapshot had
  enumerated a VPC, two EC2 instances, an ALB, a CloudFront distribution, a
  hosted zone, seven buckets, an EFS filesystem, an RDS instance, and ten KMS
  keys. §5 requires *one per-resource subfolder for each enumerated resource*.
* ``file_count`` in the manifest recorded 12 against 13 real files.

Both are invisible to a content-only check, and both degrade silently: the next
session's delta has nothing per-resource to diff against. The collector gets this
right, so the gap only opens when a snapshot is produced by hand — which is the
normal case for an agent driving a provider CLI. A folder-shape gate closes it
regardless of who wrote the files.

What is checked (``inventory-standards.md`` §3–§5)
-------------------------------------------------
============================  ========  ======================================
Finding                       Severity  Condition
============================  ========  ======================================
``folder-name``               error     folder name is not
                                        ``inventory-<provider>-<boundary>-<region>-<YYYY-MM-DD_HHMM>``
``manifest-missing``          error     no ``00-MANIFEST.md`` at the root
``manifest-field``            error     a required manifest field is absent or empty
``no-domain-json``            error     no per-service-domain ``.json`` at the root
``resources-missing``         error     no ``resources/`` folder
``resources-empty``           error     ``resources/`` holds no per-resource
                                        subfolder although resources were enumerated
``file-count``                warning   the manifest's ``file_count`` disagrees
                                        with the real recursive file count
============================  ========  ======================================

The manifest parser accepts the field in any of the three shapes a snapshot is
written in — the collector's Markdown table row (``| provider | aws |``), a
bullet list (``- **provider**: aws``, what the clean-room agent wrote), or a
plain ``provider: aws`` line — because the contract is about the *field being
recorded*, not about one rendering of it.

Dependency-free by design (``json`` + ``re`` from the standard library), matching
the other gates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:  # package-relative import
    from .constants import PROVIDERS
except ImportError:  # pragma: no cover - flat-module execution
    from constants import PROVIDERS  # type: ignore[no-redef]

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2

#: The manifest filename mandated at the root of every snapshot folder (§4).
MANIFEST_NAME = "00-MANIFEST.md"

#: The per-resource subfolder parent mandated by §5.
RESOURCES_DIRNAME = "resources"

#: The seven fields every manifest must record as non-empty values (§4).
REQUIRED_MANIFEST_FIELDS = (
    "provider",
    "boundary_id",
    "region_set",
    "caller_identity",
    "tool_versions",
    "file_count",
    "delta_instructions",
)

#: ``inventory-<provider>-<boundary-id>-<region>-<YYYY-MM-DD_HHMM>`` (§3). The
#: boundary id and region may themselves contain hyphens (``eu-central-1``), so
#: the pattern anchors on the provider prefix and the trailing UTC timestamp and
#: treats everything between as the boundary + region.
_FOLDER_RE = re.compile(
    r"^inventory-(?P<provider>[a-z]+)-(?P<middle>.+)-"
    r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{4})$"
)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One snapshot-shape violation."""

    rule: str
    severity: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"{self.rule}: {self.detail}"


@dataclass
class SnapshotReport:
    """The result of validating one snapshot folder."""

    path: str
    findings: List[Finding] = field(default_factory=list)
    domain_files: List[str] = field(default_factory=list)
    resource_dirs: int = 0
    enumerated_resources: int = 0
    file_count_actual: int = 0
    file_count_recorded: Optional[int] = None

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]

    @property
    def ok(self) -> bool:
        """True when the snapshot has no error-severity finding."""
        return not self.errors


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------

# ``| provider | aws |`` — the collector's Markdown table row.
_TABLE_ROW_RE = re.compile(r"^\|\s*\**([A-Za-z_][A-Za-z0-9_]*)\**\s*\|\s*(.*?)\s*\|\s*$")
# ``- **provider**: aws`` / ``* provider: aws`` — a bullet list.
_BULLET_RE = re.compile(
    r"^\s*[-*+]\s*\**`?([A-Za-z_][A-Za-z0-9_]*)`?\**\s*[:=]\s*(.*)$"
)
# ``provider: aws`` — a bare key/value line (also matches YAML frontmatter).
_KV_RE = re.compile(r"^\s*\**`?([A-Za-z_][A-Za-z0-9_]*)`?\**\s*:\s*(.*)$")


def parse_manifest_fields(text: str) -> Dict[str, str]:
    """Return the manifest's recorded fields, whichever shape they are written in.

    A snapshot manifest may be rendered as a Markdown table (the collector), a
    bullet list (an agent writing prose), or plain ``key: value`` lines. All three
    record the same contract, so all three are read. The first non-empty value
    wins, so a table row is not shadowed by a later mention of the same word.
    """
    out: Dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        for pattern in (_TABLE_ROW_RE, _BULLET_RE, _KV_RE):
            m = pattern.match(line)
            if not m:
                continue
            key, value = m.group(1).strip().lower(), m.group(2).strip()
            # Strip Markdown emphasis / code fences around the value.
            value = value.strip("`").strip("*").strip()
            if key and value and key not in out:
                out[key] = value
            break
    return out


# ---------------------------------------------------------------------------
# Resource counting
# ---------------------------------------------------------------------------


def _count_list_items(payload: object) -> int:
    """Return the total number of elements across every list in ``payload``.

    A provider response nests its resources in a list somewhere (``Buckets``,
    ``Reservations``, ``DBInstances``, …), and the shape differs per service, so
    the count is structural rather than schema-aware: every list element anywhere
    in the document counts as one enumerated item. That is enough to answer the
    only question asked — "did this snapshot enumerate anything at all?" — without
    the gate needing to know any provider's response schema.
    """
    if isinstance(payload, dict):
        return sum(_count_list_items(v) for v in payload.values())
    if isinstance(payload, list):
        return len(payload) + sum(_count_list_items(v) for v in payload)
    return 0


def count_enumerated_resources(snapshot_dir: str | Path) -> int:
    """Return how many resources the snapshot's per-domain JSON files enumerate.

    ``failures.json`` records services that could NOT be enumerated, so its list
    items are not resources (v1.6.1). Counting them made an empty inventory whose
    only entry was a failure — e.g. a cost request with no declared endpoint —
    fail ``resources-empty``.
    """
    total = 0
    for name in sorted(os.listdir(snapshot_dir)):
        if not name.lower().endswith(".json"):
            continue
        if name.lower() == "failures.json":
            continue
        path = Path(snapshot_dir) / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        total += _count_list_items(payload)
    return total


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def looks_like_snapshot_dir(path: str | Path) -> bool:
    """True when ``path`` is a directory whose name starts with ``inventory-``."""
    p = Path(path)
    return p.is_dir() and p.name.startswith("inventory-")


def discover_snapshots(root: str | Path) -> List[str]:
    """Return every snapshot folder under ``root`` (recursive), sorted."""
    found: List[str] = []
    for dirpath, dirnames, _files in os.walk(root):
        for name in list(dirnames):
            if name.startswith("inventory-"):
                found.append(os.path.join(dirpath, name))
                # Do not descend into a snapshot looking for nested snapshots.
                dirnames.remove(name)
    return sorted(found)


def _check_folder_name(name: str) -> Optional[Finding]:
    m = _FOLDER_RE.match(name)
    if not m:
        return Finding(
            "folder-name",
            SEVERITY_ERROR,
            f"{name!r} is not "
            "inventory-<provider>-<boundary-id>-<region>-<YYYY-MM-DD_HHMM>",
        )
    provider = m.group("provider")
    if provider not in PROVIDERS:
        return Finding(
            "folder-name",
            SEVERITY_ERROR,
            f"provider segment {provider!r} is not one of {sorted(PROVIDERS)}",
        )
    hhmm = m.group("time")
    if not (0 <= int(hhmm[:2]) <= 23 and 0 <= int(hhmm[2:]) <= 59):
        return Finding(
            "folder-name", SEVERITY_ERROR,
            f"timestamp {hhmm!r} is not a valid UTC HHMM",
        )
    return None


def check_snapshot(snapshot_dir: str | Path) -> SnapshotReport:
    """Validate one snapshot folder; return its :class:`SnapshotReport`."""
    path = Path(snapshot_dir)
    report = SnapshotReport(path=str(path))

    name_finding = _check_folder_name(path.name)
    if name_finding:
        report.findings.append(name_finding)

    # Every file under the folder, for the file_count contract.
    report.file_count_actual = sum(1 for p in path.rglob("*") if p.is_file())

    # Per-service-domain JSON files at the ROOT of the folder (§5).
    report.domain_files = sorted(
        p.name for p in path.iterdir()
        if p.is_file() and p.name.lower().endswith(".json")
    )
    if not report.domain_files:
        report.findings.append(Finding(
            "no-domain-json", SEVERITY_ERROR,
            "no per-service-domain .json file at the snapshot root "
            "(§5 requires exactly one per service domain)",
        ))

    # Manifest (§4).
    manifest = path / MANIFEST_NAME
    if not manifest.is_file():
        report.findings.append(Finding(
            "manifest-missing", SEVERITY_ERROR,
            f"no {MANIFEST_NAME} at the snapshot root",
        ))
    else:
        fields = parse_manifest_fields(manifest.read_text(encoding="utf-8"))
        for key in REQUIRED_MANIFEST_FIELDS:
            if not fields.get(key):
                report.findings.append(Finding(
                    "manifest-field", SEVERITY_ERROR,
                    f"{MANIFEST_NAME} records no non-empty {key!r}",
                ))
        raw_count = fields.get("file_count", "")
        digits = re.search(r"\d+", raw_count)
        if digits:
            report.file_count_recorded = int(digits.group(0))

    # Per-resource subfolders (§5).
    resources = path / RESOURCES_DIRNAME
    report.enumerated_resources = count_enumerated_resources(path)
    if not resources.is_dir():
        report.findings.append(Finding(
            "resources-missing", SEVERITY_ERROR,
            f"no {RESOURCES_DIRNAME}/ folder (§5 requires one subfolder per "
            "enumerated resource)",
        ))
    else:
        report.resource_dirs = sum(1 for p in resources.iterdir() if p.is_dir())
        if report.resource_dirs == 0 and report.enumerated_resources > 0:
            report.findings.append(Finding(
                "resources-empty", SEVERITY_ERROR,
                f"{RESOURCES_DIRNAME}/ holds no per-resource subfolder although "
                f"the per-domain JSON enumerates {report.enumerated_resources} "
                "item(s)",
            ))

    # file_count accuracy (§4). A warning: the contract is that the field is
    # recorded and honest, and a stale count is a documentation defect rather
    # than a collection failure.
    if (
        report.file_count_recorded is not None
        and report.file_count_recorded != report.file_count_actual
    ):
        report.findings.append(Finding(
            "file-count", SEVERITY_WARNING,
            f"{MANIFEST_NAME} records file_count={report.file_count_recorded} "
            f"but the folder holds {report.file_count_actual} file(s)",
        ))

    return report


def check_snapshots(root: str | Path) -> List[SnapshotReport]:
    """Validate every snapshot folder found under ``root``."""
    return [check_snapshot(p) for p in discover_snapshots(root)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_root() -> Path:
    """Return the directory to scan for snapshots (the current workspace)."""
    return Path.cwd()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for the snapshot gate.

    Usage::

        rule-engine-check-snapshot [--root DIR] [--snapshot DIR] [--strict]

    Exit codes:
      0  every snapshot folder satisfies the mandated shape (warnings allowed).
      1  a snapshot breaches the folder-shape contract (or, with ``--strict``,
         carries any warning).
      2  usage error.
    """
    parser = argparse.ArgumentParser(
        prog="rule-engine-check-snapshot",
        description=(
            "Validate inventory Snapshot folder shape against "
            "inventory-standards.md (folder name, manifest fields, per-domain "
            "JSON, per-resource subfolders, file_count)."
        ),
    )
    parser.add_argument(
        "--root", default=None,
        help="directory to scan for inventory-* snapshot folders "
             "(default: the current directory)",
    )
    parser.add_argument(
        "--snapshot", action="append", default=[],
        help="validate this snapshot folder directly (repeatable); "
             "skips discovery",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="treat warnings (e.g. a stale file_count) as failures too",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.snapshot:
        missing = [s for s in args.snapshot if not Path(s).is_dir()]
        if missing:
            for s in missing:
                print(f"error: no such directory: {s}", file=sys.stderr)
            return EXIT_USAGE
        reports = [check_snapshot(s) for s in args.snapshot]
    else:
        root = Path(args.root) if args.root else _default_root()
        if not root.is_dir():
            print(f"error: no such directory: {root}", file=sys.stderr)
            return EXIT_USAGE
        reports = check_snapshots(root)
        if not reports:
            print(
                f"rule-engine-check-snapshot: no inventory-* snapshot folder "
                f"found under {root}."
            )
            return EXIT_OK

    failed = False
    for report in reports:
        rel = report.path
        if report.errors:
            failed = True
            print(f"[BLOCKED] {rel}", file=sys.stderr)
            for f in report.errors:
                print(f"    - ERROR {f}", file=sys.stderr)
            for f in report.warnings:
                print(f"    - WARNING {f}", file=sys.stderr)
        elif report.warnings:
            if args.strict:
                failed = True
            print(f"[WARN] {rel}")
            for f in report.warnings:
                print(f"    - WARNING {f}")
        else:
            print(
                f"[OK] {rel}: {len(report.domain_files)} domain file(s), "
                f"{report.resource_dirs} per-resource subfolder(s), "
                f"{report.file_count_actual} file(s)"
            )

    if failed:
        print(
            "Snapshot folder shape is mandated by inventory-standards.md "
            "(§3 folder name, §4 manifest, §5 one JSON per domain + one "
            "subfolder per resource). Prefer rule_engine.collector.collect(), "
            "which produces a conforming snapshot.",
            file=sys.stderr,
        )
        return EXIT_VIOLATION

    print(f"OK: all {len(reports)} snapshot folder(s) satisfy the mandated shape.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
