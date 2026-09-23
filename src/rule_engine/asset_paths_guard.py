"""Asset-path guard — verify mapping icon file paths exist under the asset root.

Some provider mappings (`mappings/<provider>-icons.yaml`) reference an icon by a
**file path** in their draw.io style string, e.g. GCP:

    image=assets/vendor/gcp-category/Category Icons/Storage/SVG/Storage-512-color.svg

Those files are fetched on demand by ``scripts/fetch_assets.py`` into a
git-ignored asset root; they are never committed. This guard checks that every
such declared path actually exists, so a typo or a stale rename is caught in CI
rather than silently rendering an empty box (which the linter's ``icon-resolved``
rule would only catch on a generated diagram, not in the mapping itself).

Scope of the check (deliberately narrow to avoid false positives):

* Only ``image=<path>`` style tokens whose path is a **relative filesystem path**
  are checked. A path is skipped when it is:
  - a ``data:`` URI (inline base64 — a separate concern; the linter blocks those),
  - a draw.io-internal ``img/lib/...`` reference (Azure ``azure2`` image shapes
    ship inside draw.io itself, not under the repo asset root),
  - an absolute URL (``http://`` / ``https://``).
* ``shape=mxgraph.*`` stencil styles carry no filesystem path and are not checked
  here (stencil-id correctness is a separate, source-verified concern).

Fetch-awareness (Requirement: CI fetches first, local dev may not):

* :func:`check_mapping_assets` reports every declared path together with whether
  it exists. The CLI's exit policy depends on whether the **asset root exists**:
  - asset root present  -> a missing declared path is a hard failure (exit 1);
  - asset root absent    -> the packs were never fetched, so the check is skipped
    with a warning (exit 0). CI runs ``scripts/fetch_assets.py`` before this
    guard, so in CI the asset root is always present and the check is enforced.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# Extract the path from an ``image=<path>`` draw.io style token. The value runs
# to the next ``;`` or the end of the style string.
_IMAGE_RE = re.compile(r"image=([^;]+)")

# Prefixes that are NOT repo-relative asset files and must be skipped.
_SKIP_PREFIXES = ("data:", "img/lib/", "http://", "https://")

EXIT_OK = 0
EXIT_MISSING = 1
EXIT_USAGE = 2


@dataclass
class AssetRef:
    """One icon file path declared by a mapping."""

    mapping: str          # mapping filename (e.g. "gcp-icons.yaml")
    resource: str         # resource key (e.g. "object_store")
    path: str             # declared path, relative to the repo root
    exists: bool          # whether the file exists under the asset root


@dataclass
class StencilRef:
    """One OCI stencil slug declared by a mapping's ``stencil`` field."""

    mapping: str          # mapping filename (e.g. "oci-icons.yaml")
    resource: str         # resource key (e.g. "object_store")
    manifest: str         # manifest path, relative to the repo root
    slug: str             # stencil slug expected as a key in the manifest
    manifest_exists: bool # whether the manifest JSON file exists
    slug_present: bool    # whether the slug is a key in the manifest


def _iter_style_images(entry: object):
    """Yield each ``image=<path>`` value found in a mapping entry's style."""
    if not isinstance(entry, dict):
        return
    style = entry.get("style")
    if not isinstance(style, str):
        return
    for m in _IMAGE_RE.finditer(style):
        yield m.group(1).strip()


def _is_checkable(path: str) -> bool:
    """True when ``path`` is a repo-relative asset file we should verify."""
    low = path.strip().lower()
    if not low:
        return False
    return not low.startswith(_SKIP_PREFIXES)


def check_mapping_assets(
    mappings_dir: str | Path,
    repo_root: str | Path = REPO_ROOT,
) -> List[AssetRef]:
    """Return an :class:`AssetRef` for every checkable icon path in the mappings.

    Scans ``mappings_dir/*-icons.yaml``, reads each ``resources``/``containers``
    entry's ``image=<path>`` style token, and records whether the file exists
    under ``repo_root``. Non-file styles (stencils, ``data:`` URIs, draw.io
    ``img/lib`` references, URLs) are skipped.
    """
    mappings_dir = Path(mappings_dir)
    repo_root = Path(repo_root)
    refs: List[AssetRef] = []
    for map_path in sorted(glob.glob(str(mappings_dir / "*-icons.yaml"))):
        try:
            data = yaml.safe_load(Path(map_path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        for section in ("resources", "containers"):
            table = data.get(section)
            if not isinstance(table, dict):
                continue
            for resource, entry in table.items():
                for img_path in _iter_style_images(entry):
                    if not _is_checkable(img_path):
                        continue
                    exists = (repo_root / img_path).is_file()
                    refs.append(
                        AssetRef(
                            mapping=os.path.basename(map_path),
                            resource=str(resource),
                            path=img_path,
                            exists=exists,
                        )
                    )
    return refs


def check_mapping_stencils(
    mappings_dir: str | Path,
    repo_root: str | Path = REPO_ROOT,
) -> List[StencilRef]:
    """Return a :class:`StencilRef` for every ``stencil: <manifest>#<slug>`` entry.

    OCI resolves icons by embedding a decoded stencil (keyed by a title slug)
    rather than by a draw.io shape id — the mapping declares
    ``stencil: oci-stencils/stencils.json#<slug>``. ``scripts/fetch_assets.py``
    decodes ``OCI Library.xml`` into that manifest. This records, per entry,
    whether the manifest exists and whether the slug is one of its keys, so a
    stale/renamed slug is caught in CI. Manifest JSON is read once and cached.
    """
    mappings_dir = Path(mappings_dir)
    repo_root = Path(repo_root)
    manifest_cache: dict = {}

    def _keys(rel_manifest: str):
        if rel_manifest not in manifest_cache:
            mpath = repo_root / rel_manifest
            try:
                data = json.loads(mpath.read_text(encoding="utf-8"))
                manifest_cache[rel_manifest] = (
                    set(data) if isinstance(data, dict) else None
                )
            except (OSError, ValueError):
                manifest_cache[rel_manifest] = None
        return manifest_cache[rel_manifest]

    refs: List[StencilRef] = []
    for map_path in sorted(glob.glob(str(mappings_dir / "*-icons.yaml"))):
        try:
            data = yaml.safe_load(Path(map_path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        for section in ("resources", "containers"):
            table = data.get(section)
            if not isinstance(table, dict):
                continue
            for resource, entry in table.items():
                if not isinstance(entry, dict):
                    continue
                stencil = entry.get("stencil")
                if not isinstance(stencil, str) or "#" not in stencil:
                    continue
                rel_manifest, _, slug = stencil.partition("#")
                keys = _keys(rel_manifest)
                refs.append(
                    StencilRef(
                        mapping=os.path.basename(map_path),
                        resource=str(resource),
                        manifest=rel_manifest,
                        slug=slug,
                        manifest_exists=keys is not None,
                        slug_present=(keys is not None and slug in keys),
                    )
                )
    return refs


def asset_root_present(repo_root: str | Path = REPO_ROOT) -> bool:
    """True when the fetched asset root exists (packs have been downloaded)."""
    return (Path(repo_root) / "assets" / "vendor").is_dir()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for the CI ``asset-paths`` check.

    Usage::

        python -m rule_engine.asset_paths_guard [--mappings DIR] [--repo-root DIR]

    Exit codes:
      0  all declared icon paths exist, or the asset root is absent (skipped).
      1  the asset root is present but one or more declared paths are missing.
      2  usage error.
    """
    parser = argparse.ArgumentParser(
        prog="asset-paths-guard",
        description="Verify mapping icon file paths exist under the asset root.",
    )
    parser.add_argument("--mappings", default=str(REPO_ROOT / "mappings"))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(list(argv) if argv is not None else None)

    refs = check_mapping_assets(args.mappings, args.repo_root)
    checkable = len(refs)

    if not asset_root_present(args.repo_root):
        print(
            "asset-paths-guard: asset root assets/vendor is absent "
            "(run scripts/fetch_assets.py); skipping "
            f"{checkable} file-path check(s).",
        )
        return EXIT_OK

    missing = [r for r in refs if not r.exists]
    if missing:
        print("BLOCKING: mapping icon file(s) not found under the asset root:",
              file=sys.stderr)
        for r in missing:
            print(f"    - {r.mapping} [{r.resource}] -> {r.path}", file=sys.stderr)
        print(
            "Run scripts/fetch_assets.py to populate the pack, or fix the path in "
            "the mapping.",
            file=sys.stderr,
        )
        return EXIT_MISSING

    # --- OCI stencil-slug check ------------------------------------------
    stencil_refs = check_mapping_stencils(args.mappings, args.repo_root)
    # Only enforce for manifests that actually exist (fetch-aware, like above):
    # a missing manifest means fetch_assets has not decoded the library yet.
    present_manifest = [r for r in stencil_refs if r.manifest_exists]
    bad_slugs = [r for r in present_manifest if not r.slug_present]
    skipped_manifests = sorted(
        {r.manifest for r in stencil_refs if not r.manifest_exists}
    )
    if bad_slugs:
        print("BLOCKING: mapping stencil slug(s) not found in the decoded manifest:",
              file=sys.stderr)
        for r in bad_slugs:
            print(f"    - {r.mapping} [{r.resource}] -> {r.manifest}#{r.slug}",
                  file=sys.stderr)
        print(
            "Run scripts/fetch_assets.py to (re)decode the library, or fix the slug "
            "in the mapping.",
            file=sys.stderr,
        )
        return EXIT_MISSING
    for man in skipped_manifests:
        print(
            f"asset-paths-guard: stencil manifest {man} is absent "
            "(run scripts/fetch_assets.py); skipping its slug check(s).",
        )

    checked_slugs = len(present_manifest)
    tail = (f"; all {checked_slugs} stencil slug(s) present"
            if checked_slugs else "")
    print(f"OK: all {checkable} mapping icon file path(s) exist under the asset "
          f"root{tail}.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
