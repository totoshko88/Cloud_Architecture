"""Azure ``azure2`` shape manifest — extract & load the valid image paths.

Azure diagrams reference icons by a **draw.io-internal** path,
``image=img/lib/azure2/<category>/<Name>.svg``. Unlike the fetched
``assets/vendor/*`` file paths (checkable on disk by the asset-paths guard) and
the AWS ``mxgraph.aws4.*`` ids (checked against the curated ``aws-icons.yaml``),
the azure2 shapes ship **inside the draw.io application** (``app.asar``) and are
not present in the repository. So a *well-formed but non-existent* azure2 path
(e.g. ``…/databases/Azure_Cache_Redis.svg`` when the real file is
``Cache_Redis.svg``) rendered as a broken-image placeholder and slipped past
every guard — the exact defect this module closes.

The manifest ``mappings/azure2-shapes.json`` is a committed, sorted list of every
valid ``img/lib/azure2/*.svg`` path, extracted from a local draw.io desktop
``app.asar`` by :func:`extract_azure2_paths`. Committing the *list* (not the
binaries) lets the icon verifier and CI confirm an azure2 reference exists
without the draw.io app present — the same "index once, verify everywhere"
philosophy as ``mappings/icon-index.json``.

Public interface::

    extract_azure2_paths(asar_path) -> list[str]   # from a local app.asar
    load_manifest(path=DEFAULT_MANIFEST) -> set[str] | None
    DEFAULT_MANIFEST
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import List, Optional, Set

# Committed manifest location (repo root: this file is
# src/rule_engine/azure2_shapes.py -> ... -> root).
DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "mappings" / "azure2-shapes.json"

# Default draw.io desktop asar locations by platform (best-effort).
_ASAR_CANDIDATES = (
    "/Applications/draw.io.app/Contents/Resources/app.asar",  # macOS
    "/usr/lib/drawio/resources/app.asar",                     # Linux (deb)
    "/opt/drawio/resources/app.asar",                         # Linux (alt)
)


def _read_asar_header(asar_path: Path) -> dict:
    """Read and parse the JSON header of an Electron ``app.asar`` archive."""
    with open(asar_path, "rb") as fh:
        # Pickle framing: 4-byte size of the size field, then the header size,
        # then the JSON header string (padded).
        fh.read(8)
        header_size = struct.unpack("<I", fh.read(4))[0]
        fh.read(4)
        raw = fh.read(header_size).decode("utf-8", "replace")
    # Trim any padding past the balanced top-level object.
    depth = 0
    end = len(raw)
    for i, ch in enumerate(raw):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    return json.loads(raw[:end])


def _find_node(node: dict, target: str) -> Optional[dict]:
    """Depth-first search for the sub-tree named ``target`` (a directory)."""
    for name, child in node.get("files", {}).items():
        if name == target and "files" in child:
            return child
        if "files" in child:
            found = _find_node(child, target)
            if found is not None:
                return found
    return None


def extract_azure2_paths(asar_path: str | Path) -> List[str]:
    """Return every ``img/lib/azure2/*.svg`` path bundled in ``app.asar``.

    Raises :class:`FileNotFoundError` if the asar is missing, or ``ValueError``
    if the azure2 directory is not found in the archive header."""
    asar_path = Path(asar_path)
    if not asar_path.is_file():
        raise FileNotFoundError(f"draw.io app.asar not found: {asar_path}")
    header = _read_asar_header(asar_path)
    node = _find_node(header, "azure2")
    if node is None:
        raise ValueError(f"no azure2 shape directory found in {asar_path}")
    out: List[str] = []

    def walk(n: dict, path: str) -> None:
        for name, child in n.get("files", {}).items():
            child_path = f"{path}/{name}"
            if "files" in child:
                walk(child, child_path)
            elif name.endswith(".svg"):
                out.append(child_path)

    walk(node, "img/lib/azure2")
    return sorted(out)


def find_asar() -> Optional[Path]:
    """Return the first draw.io ``app.asar`` found in a default location."""
    for cand in _ASAR_CANDIDATES:
        p = Path(cand)
        if p.is_file():
            return p
    return None


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> Optional[Set[str]]:
    """Load the committed azure2 path manifest as a set, or ``None`` if absent."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    paths = data.get("paths") if isinstance(data, dict) else data
    if not isinstance(paths, list):
        return None
    return set(paths) or None


def write_manifest(paths: List[str], out: str | Path = DEFAULT_MANIFEST) -> None:
    """Write the sorted azure2 path manifest to ``out`` (deterministic JSON)."""
    payload = {"library": "azure2", "count": len(paths), "paths": sorted(paths)}
    Path(out).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# AWS aws4 stencil id manifest
# --------------------------------------------------------------------------- #

import re as _re

AWS4_MANIFEST = Path(__file__).resolve().parents[2] / "mappings" / "aws4-icons.json"


def extract_aws4_ids(asar_path: str | Path) -> List[str]:
    """Return every ``mxgraph.aws4.<id>`` stencil id referenced in ``app.asar``.

    The aws4 library registers service ``resIcon``s, group ``grIcon``s, and shape
    ids as ``mxgraph.aws4.<id>`` tokens in the sidebar JS. This harvests them all.
    The asar scan is not exhaustive (a few ids are built dynamically), so callers
    should union this with the curated ``mappings/aws-icons.yaml`` ids — see
    :func:`build_aws4_manifest`."""
    asar_path = Path(asar_path)
    if not asar_path.is_file():
        raise FileNotFoundError(f"draw.io app.asar not found: {asar_path}")
    data = asar_path.read_bytes().decode("latin-1")
    return sorted(set(_re.findall(r"mxgraph\.aws4\.([A-Za-z0-9_]+)", data)))


def _curated_aws4_ids(repo_root: Path) -> Set[str]:
    """The verified aws4 ids listed in the curated mappings/aws-icons.yaml."""
    mapping = repo_root / "mappings" / "aws-icons.yaml"
    if not mapping.is_file():
        return set()
    text = mapping.read_text(encoding="utf-8")
    return set(_re.findall(r"mxgraph\.aws4\.([A-Za-z0-9_]+)", text))


def build_aws4_manifest(asar_path: str | Path, repo_root: Optional[Path] = None) -> List[str]:
    """Return the union of asar-extracted and curated aws4 ids (sorted).

    The union covers ids the asar scan misses (e.g. ``bedrock``, ``group_account``,
    ``group_vpc2`` are constructed dynamically) but the repository has verified."""
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    extracted = set(extract_aws4_ids(asar_path))
    curated = _curated_aws4_ids(repo_root)
    return sorted(extracted | curated)


def load_aws4_manifest(path: str | Path = AWS4_MANIFEST) -> Optional[Set[str]]:
    """Load the committed aws4 id manifest as a set, or ``None`` if absent."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ids = data.get("ids") if isinstance(data, dict) else data
    if not isinstance(ids, list):
        return None
    return set(ids) or None


def write_aws4_manifest(ids: List[str], out: str | Path = AWS4_MANIFEST) -> None:
    """Write the sorted aws4 id manifest to ``out`` (deterministic JSON)."""
    payload = {"library": "mxgraph.aws4", "count": len(ids), "ids": sorted(ids)}
    Path(out).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


__all__ = [
    "DEFAULT_MANIFEST",
    "AWS4_MANIFEST",
    "extract_azure2_paths",
    "extract_aws4_ids",
    "build_aws4_manifest",
    "find_asar",
    "load_manifest",
    "load_aws4_manifest",
    "write_manifest",
    "write_aws4_manifest",
]
