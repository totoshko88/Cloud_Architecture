"""One merged mapping tree: bundled ``mappings/`` + ``mappings/local/`` overlays.

Before 1.10.12 three tools disagreed about which mapping tree was
authoritative (SEP feedback §4.1): ``icon_resolver.resolve_icon`` read the
bundled ``<provider>-icons.yaml`` plus a ``mappings/local/`` overlay,
``asset_index.build_icon_index`` read only the bundled ``roles.yaml``, and
``rule-engine-check-asset-paths`` read the workspace's own ``mappings/`` copy.
A role added to the workspace ``mappings/aws-icons.yaml`` therefore passed the
asset-path gate but never rendered, and a role added to the overlay rendered
but was never path-checked.

This module is the single definition of the effective tree every reader uses:

1. the **bundled** mappings dir (``constants.resolve_bundled_dir("mappings")``:
   repo checkout, else the package payload, else the CWD), then
2. each existing **overlay** dir, in order: ``<bundled>/local`` and
   ``<cwd>/mappings/local`` (deduplicated, so a repo checkout run from its own
   root applies its overlay once).

Overlay files are merged **per key**: in ``<provider>-icons.yaml`` the
``resources`` / ``containers`` tables merge entry by entry (a local role
replaces only that role), any other top-level key is replaced; in
``roles.yaml`` the ``roles`` table merges role by role. Everything the overlay
does not mention keeps the bundled value, so an engine upgrade still delivers
its corrected styles.

The workspace's own top-level ``mappings/*.yaml`` (the copies
``rule-engine-init`` writes) are **not** part of the tree. :func:`no_effect_edits`
reports every entry in them that the effective tree does not carry, so an edit
that would silently do nothing is named (``rule-engine-build-icon-sets
--check`` and ``rule-engine-check-asset-paths`` print these warnings).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml

from rule_engine.constants import resolve_bundled_dir

#: Sub-directory of a mappings dir that holds the workspace-local overlay.
LOCAL_SUBDIR = "local"

#: The provider-mapping tables merged entry by entry.
_ENTRY_TABLES = ("resources", "containers")

#: Name of the roles file (bundled and overlay).
ROLES_FILE = "roles.yaml"


class MappingTreeError(ValueError):
    """An overlay file exists but cannot be read, parsed, or is not a mapping."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def bundled_dir() -> Path:
    """The bundled mappings dir (repo checkout → package payload → CWD)."""
    return resolve_bundled_dir("mappings")


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def overlay_dirs(
    bundled: Optional[Path] = None, extra: Sequence[Path] = ()
) -> List[Path]:
    """Existing overlay dirs in merge order, deduplicated by resolved path.

    ``<bundled>/local`` first, then ``<cwd>/mappings/local``, then ``extra``.
    A later dir wins over an earlier one for the keys it defines.
    """
    base = Path(bundled) if bundled is not None else bundled_dir()
    candidates = [base / LOCAL_SUBDIR, Path.cwd() / "mappings" / LOCAL_SUBDIR]
    candidates.extend(Path(p) for p in extra)
    out: List[Path] = []
    for cand in candidates:
        if not cand.is_dir():
            continue
        if any(_same(cand, seen) for seen in out):
            continue
        out.append(cand)
    return out


def _read_yaml(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MappingTreeError(path, f"cannot read: {exc}") from exc
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise MappingTreeError(path, f"cannot parse: {exc}") from exc


def _read_overlay(path: Path) -> Dict[str, Any]:
    data = _read_yaml(path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MappingTreeError(path, "does not contain a mapping")
    return data


def merge_provider_mapping(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay one provider mapping onto ``base`` (per-key wins; ``base`` untouched).

    ``resources`` / ``containers`` merge entry by entry; every other top-level
    key is replaced when the overlay defines it.
    """
    merged: Dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key in _ENTRY_TABLES and isinstance(value, dict):
            sub = merged.get(key)
            sub = dict(sub) if isinstance(sub, dict) else {}
            sub.update(value)
            merged[key] = sub
        else:
            merged[key] = value
    return merged


def merge_roles(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay a ``roles.yaml`` onto ``base``: the ``roles`` table merges per role."""
    merged: Dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key == "roles" and isinstance(value, dict):
            sub = merged.get("roles")
            sub = dict(sub) if isinstance(sub, dict) else {}
            sub.update(value)
            merged["roles"] = sub
        else:
            merged[key] = value
    return merged


def overlay_files(
    name: str, bundled: Optional[Path] = None, extra: Sequence[Path] = ()
) -> List[Path]:
    """Every existing overlay file called ``name``, in merge order."""
    return [d / name for d in overlay_dirs(bundled, extra) if (d / name).is_file()]


def apply_provider_overlays(
    provider: str,
    data: Dict[str, Any],
    bundled: Optional[Path] = None,
    extra: Sequence[Path] = (),
) -> Dict[str, Any]:
    """Merge every ``local/<provider>-icons.yaml`` overlay onto ``data``.

    Raises :class:`MappingTreeError` naming the overlay path when one is
    unreadable, unparsable, or not a mapping (a broken overlay fails loudly).
    """
    for path in overlay_files(f"{provider}-icons.yaml", bundled, extra):
        data = merge_provider_mapping(data, _read_overlay(path))
    return data


def load_provider_mapping(
    provider: str, bundled: Optional[Path] = None, extra: Sequence[Path] = ()
) -> Optional[Dict[str, Any]]:
    """The effective ``<provider>-icons.yaml`` (bundled + overlays), or ``None``.

    ``None`` when neither the bundled file nor any overlay exists. An unreadable
    bundled file is treated as absent (callers that need a loud error — the
    icon resolver — read the bundled file themselves).
    """
    base_dir = Path(bundled) if bundled is not None else bundled_dir()
    path = base_dir / f"{provider}-icons.yaml"
    data: Optional[Dict[str, Any]] = None
    if path.is_file():
        try:
            loaded = _read_yaml(path)
        except MappingTreeError:
            loaded = None
        if isinstance(loaded, dict):
            data = loaded
    overlays = overlay_files(f"{provider}-icons.yaml", base_dir, extra)
    if data is None and not overlays:
        return None
    return apply_provider_overlays(provider, data or {}, base_dir, extra)


def provider_mapping_names(
    bundled: Optional[Path] = None, extra: Sequence[Path] = ()
) -> List[str]:
    """Sorted ``<provider>-icons.yaml`` file names present in the bundled dir or any overlay."""
    base_dir = Path(bundled) if bundled is not None else bundled_dir()
    names = {p.name for p in base_dir.glob("*-icons.yaml")}
    for d in overlay_dirs(base_dir, extra):
        names.update(p.name for p in d.glob("*-icons.yaml"))
    return sorted(names)


def effective_mappings(
    bundled: Optional[Path] = None, extra: Sequence[Path] = ()
) -> Dict[str, Dict[str, Any]]:
    """``{<provider>-icons.yaml: effective mapping}`` for every mapping in the tree."""
    base_dir = Path(bundled) if bundled is not None else bundled_dir()
    out: Dict[str, Dict[str, Any]] = {}
    for name in provider_mapping_names(base_dir, extra):
        provider = name[: -len("-icons.yaml")]
        data = load_provider_mapping(provider, base_dir, extra)
        if data is not None:
            out[name] = data
    return out


def load_roles(
    bundled: Optional[Path] = None,
    extra: Sequence[Path] = (),
    roles_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """The effective ``roles.yaml`` (bundled + ``local/roles.yaml`` overlays).

    ``roles_path`` overrides the bundled base file (the overlays still apply
    from ``bundled``). A missing base file yields ``{}`` as the base.
    """
    base_dir = Path(bundled) if bundled is not None else bundled_dir()
    base_file = Path(roles_path) if roles_path is not None else base_dir / ROLES_FILE
    data: Dict[str, Any] = {}
    if base_file.is_file():
        loaded = _read_yaml(base_file)
        if isinstance(loaded, dict):
            data = loaded
    for path in overlay_files(ROLES_FILE, base_dir, extra):
        data = merge_roles(data, _read_overlay(path))
    return data


# --------------------------------------------------------------------------- #
# No-effect workspace edits
# --------------------------------------------------------------------------- #


def _entries(data: Any, tables: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(data, dict):
        return out
    for table in tables:
        sub = data.get(table)
        if isinstance(sub, dict):
            out[table] = sub
    return out


def no_effect_edits(
    workspace_mappings: Path,
    bundled: Optional[Path] = None,
    extra: Sequence[Path] = (),
) -> List[str]:
    """Warnings for workspace ``mappings/`` entries the effective tree ignores.

    ``workspace_mappings`` is a workspace's top-level ``mappings/`` dir (the
    copies ``rule-engine-init`` wrote). Every ``resources`` / ``containers``
    entry of its ``*-icons.yaml`` and every ``roles`` entry of its
    ``roles.yaml`` that is absent from, or different in, the effective tree is
    reported: editing that file changes nothing, because resolution reads the
    bundled mappings plus ``mappings/local/``. Returns ``[]`` when
    ``workspace_mappings`` is the bundled dir itself (an engine checkout), or
    does not exist.
    """
    ws = Path(workspace_mappings)
    base_dir = Path(bundled) if bundled is not None else bundled_dir()
    if not ws.is_dir() or _same(ws, base_dir):
        return []
    warnings: List[str] = []

    def _hint(name: str) -> str:
        return f"move it to mappings/{LOCAL_SUBDIR}/{name}"

    for path in sorted(ws.glob("*-icons.yaml")):
        try:
            mine = _read_yaml(path)
        except MappingTreeError:
            continue
        provider = path.name[: -len("-icons.yaml")]
        effective = load_provider_mapping(provider, base_dir, extra) or {}
        theirs = _entries(effective, _ENTRY_TABLES)
        for table, entries in _entries(mine, _ENTRY_TABLES).items():
            for key, value in entries.items():
                actual = theirs.get(table, {}).get(key)
                if actual is None:
                    why = "is not in the bundled mapping or any overlay"
                elif actual != value:
                    why = "differs from the effective (bundled + overlay) entry"
                else:
                    continue
                warnings.append(
                    f"mappings/{path.name}: {table}.{key} {why} — this edit has "
                    f"no effect; {_hint(path.name)}"
                )

    roles_path = ws / ROLES_FILE
    if roles_path.is_file():
        try:
            mine = _read_yaml(roles_path)
        except MappingTreeError:
            mine = None
        effective_roles = (load_roles(base_dir, extra).get("roles") or {})
        mine_roles = (mine or {}).get("roles") if isinstance(mine, dict) else None
        if isinstance(mine_roles, dict):
            for key, value in mine_roles.items():
                actual = effective_roles.get(key)
                if actual is None:
                    why = "is not in the bundled roles.yaml or any overlay"
                elif actual != value:
                    why = "differs from the effective (bundled + overlay) role"
                else:
                    continue
                warnings.append(
                    f"mappings/{ROLES_FILE}: roles.{key} {why} — this edit has "
                    f"no effect; {_hint(ROLES_FILE)}"
                )
    return warnings


__all__ = [
    "LOCAL_SUBDIR",
    "ROLES_FILE",
    "MappingTreeError",
    "bundled_dir",
    "overlay_dirs",
    "overlay_files",
    "merge_provider_mapping",
    "merge_roles",
    "apply_provider_overlays",
    "load_provider_mapping",
    "provider_mapping_names",
    "effective_mappings",
    "load_roles",
    "no_effect_edits",
]
