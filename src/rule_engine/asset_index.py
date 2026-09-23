"""Asset Index & Icon Fallback.

The Icon Resolver (:mod:`rule_engine.icon_resolver`) maps the nine *neutral*
resource types to a provider's built-in draw.io stencil. Real diagrams, however,
often reference **specific** services that are newer than, or simply absent from,
the built-in ``mxgraph.*`` stencil libraries — for example ``AWS DevOps agent``,
``AWS FinOps agent``, or ``AWS Security agent``. For those, the deterministic
answer is to fall back to the provider's **official icon asset pack** (the SVG or
PNG shipped by the cloud vendor) rather than emit an unresolved placeholder.

This module indexes a local directory of unpacked official asset packs and
resolves a free-form service name to the best available asset, in this order:

1. **built-in stencil** — when the service maps to a known ``mxgraph.<lib>.*``
   stencil id (the preferred, editable form),
2. **official asset file** — the vendor SVG (preferred) or PNG from the pack,
3. **unresolved** — no asset found; the caller must supply one.

The index is provider-scoped and content-addressable by a normalized *slug* of
the service name, so ``"AWS Security Agent"``, ``"security-agent"`` and
``"Security  Agent"`` all resolve to the same entry.

Pack layouts understood (see steering ``asset-packs.md``):

- **aws**   ``Architecture-Service-Icons_*/Arch_<Category>/<size>/Arch_<Service>_<size>.svg``
            and ``Resource-Icons_*/Res_<Category>/<size>/Res_<Service>_<size>.svg``
- **azure** ``Azure_Public_Service_Icons/Icons/<category>/NNNNN-icon-service-<Name>.svg``
- **gcp**   ``Category Icons/<category>/... .svg`` and ``Unique Icons/<product>/SVG/<Name>-....svg``
- **oci**   a draw.io ``<mxlibrary>`` (``OCI Library.xml``); OCI ships shapes, not
            per-service SVGs, so OCI fallback resolves to the library id.

This module performs no network access: it only reads a local asset root that a
build step (or the ``add-a-provider`` runbook) has populated. The asset root is
never committed; it is produced on demand and lives outside version control.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional

from rule_engine.constants import PROVIDERS  # single source of truth

# Preferred asset formats, best first. SVG is vector (scales cleanly in draw.io);
# PNG is the raster fallback.
_PREFERRED_EXTS = (".svg", ".png")


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

# Vendor prefixes / decoration stripped before slugging so that
# "Amazon Simple Storage Service", "AWS S3" and "S3" collapse toward a common
# core where possible. We keep this conservative: we strip only unambiguous
# vendor words and size/format suffixes.
_STRIP_TOKENS = (
    "amazon", "aws", "arch", "res", "icon", "service",
    "azure", "microsoft", "public",
    "google", "cloud", "gcp",
    "oracle", "oci",
    "color", "rgb", "dark", "light",
)

_SIZE_SUFFIX_RE = re.compile(r"(?:^|[-_ ])(?:16|24|32|48|64|128|256|512)(?:px)?$", re.I)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_slug(name: str, *, strip_vendor: bool = False) -> str:
    """Return a canonical slug for a service/file name.

    ``"AWS Security Agent"`` -> ``"aws-security-agent"`` (default), or
    ``"security-agent"`` when ``strip_vendor`` is set. Slugs are lowercase,
    hyphen-separated, and free of size/format decoration. An empty result is
    returned as the empty string.
    """
    text = name.strip().lower()
    # Drop a file extension if present.
    text = re.sub(r"\.[a-z0-9]+$", "", text)
    # Normalize separators to spaces.
    text = _NON_ALNUM_RE.sub(" ", text)
    # Drop trailing size tokens like "32", "512".
    text = _SIZE_SUFFIX_RE.sub("", text).strip()
    tokens = [t for t in text.split() if t]
    if strip_vendor:
        tokens = [t for t in tokens if t not in _STRIP_TOKENS]
    # Also drop bare size tokens anywhere.
    tokens = [t for t in tokens if not re.fullmatch(r"(?:16|24|32|48|64|128|256|512)", t)]
    return "-".join(tokens)


# ---------------------------------------------------------------------------
# Index model
# ---------------------------------------------------------------------------


@dataclass
class AssetEntry:
    """One indexed official asset for a provider."""

    provider: str
    slug: str            # vendor-stripped canonical slug (primary key within provider)
    display_name: str    # human-readable service name derived from the file
    path: str            # path to the asset file, relative to the asset root
    ext: str             # ".svg" or ".png"
    category: str = ""   # source category folder, when known


@dataclass
class ResolvedAsset:
    """Result of :func:`resolve_asset`."""

    provider: str
    query: str
    source: str          # "builtin" | "official-asset" | "unresolved"
    stencil: Optional[str] = None     # mxgraph stencil id, when source == builtin
    asset_path: Optional[str] = None  # official file path, when source == official-asset
    ext: Optional[str] = None
    note: str = ""


# ---------------------------------------------------------------------------
# Per-provider pack scanning
# ---------------------------------------------------------------------------


def _iter_files(root: Path) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip mac cruft.
        dirnames[:] = [d for d in dirnames if d != "__MACOSX"]
        for name in filenames:
            if name == ".DS_Store":
                continue
            out.append(Path(dirpath) / name)
    return out


def _best_ext(path: Path) -> Optional[str]:
    ext = path.suffix.lower()
    return ext if ext in _PREFERRED_EXTS else None


def _aws_display(path: Path) -> str:
    # Arch_Amazon-WorkSpaces_32.svg -> "Amazon WorkSpaces"
    stem = path.stem
    stem = re.sub(r"^(?:Arch|Res)_", "", stem)
    stem = re.sub(r"_(?:16|24|32|48|64|128|256|512)$", "", stem)
    return stem.replace("-", " ").replace("_", " ").strip()


def _azure_display(path: Path) -> str:
    # 00028-icon-service-Batch-AI.svg -> "Batch AI"
    stem = path.stem
    stem = re.sub(r"^\d+-icon-service-", "", stem)
    return stem.replace("-", " ").replace("_", " ").strip()


def _gcp_display(path: Path) -> str:
    # Cloud_Storage-512-color.svg -> "Cloud Storage"
    stem = path.stem
    stem = re.sub(r"[-_](?:16|24|32|48|64|128|256|512)(?:[-_](?:color|rgb|dark|light))*$", "", stem, flags=re.I)
    return stem.replace("_", " ").replace("-", " ").strip()


def _category_from_path(root: Path, path: Path) -> str:
    parts = path.relative_to(root).parts
    # Heuristic: the folder two levels above the file, else the parent.
    if len(parts) >= 3:
        return parts[-2] if parts[-2].upper() not in {"SVG", "PNG"} else parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return ""


_DISPLAY_FN = {
    "aws": _aws_display,
    "azure": _azure_display,
    "gcp": _gcp_display,
}


def _find_oci_stencils_json(root: Path) -> Optional[Path]:
    """Locate the decoded OCI ``stencils.json`` at/under ``root``.

    Accepts ``root`` pointing directly at the file, at the ``oci-stencils``
    folder, or at the asset root that contains it."""
    if root.is_file() and root.name == "stencils.json":
        return root
    for cand in (root / "stencils.json", root / "oci-stencils" / "stencils.json"):
        if cand.is_file():
            return cand
    matches = sorted(root.glob("**/stencils.json"))
    return matches[0] if matches else None


def _index_oci_stencils(root: Path) -> Dict[str, AssetEntry]:
    """Index OCI from the decoded ``stencils.json`` (slug -> stencil metadata).

    Each entry's ``path`` is a ``<manifest>#<slug>`` reference (the same form the
    OCI mapping uses), and ``ext`` is ``.stencil`` to mark an embedded glyph
    rather than a file. The ``category`` is taken from the stencil title prefix
    (``"Networking - CDN"`` -> ``Networking``). ``display_name`` is the title's
    service part."""
    manifest = _find_oci_stencils_json(root)
    if manifest is None:
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    rel = "assets/vendor/oci-stencils/stencils.json"
    index: Dict[str, AssetEntry] = {}
    for slug, meta in data.items():
        title = str(meta.get("title") or slug)
        category = title.split(" - ", 1)[0] if " - " in title else ""
        service = title.split(" - ", 1)[-1] if " - " in title else title
        index[slug] = AssetEntry(
            provider="oci",
            slug=slug,
            display_name=service,
            path=f"{rel}#{slug}",
            ext=".stencil",
            category=category,
        )
    return index


def index_provider(provider: str, pack_root: str) -> Dict[str, AssetEntry]:
    """Index one provider's unpacked official asset pack rooted at ``pack_root``.

    Returns a mapping of vendor-stripped slug -> :class:`AssetEntry`. When both an
    SVG and a PNG exist for the same slug, the SVG wins; when several sizes exist,
    the largest available is kept (later files of the preferred ext overwrite only
    when strictly better). Providers without per-service files (``oci``) yield an
    empty map; use :func:`resolve_asset` for their library-based fallback.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    root = Path(pack_root)

    # OCI ships no per-service files — its shapes live in a draw.io <mxlibrary>
    # decoded to a slug->stencil JSON by scripts/fetch_assets.py. Index that
    # instead of walking a file tree so all four providers land in one index.
    # ``pack_root`` may point at the stencils.json file, the oci-stencils dir, or
    # the asset root that contains it.
    if provider == "oci":
        return _index_oci_stencils(root)

    if not root.is_dir():
        raise FileNotFoundError(f"asset pack root not found: {pack_root}")

    display_fn = _DISPLAY_FN.get(provider, lambda p: p.stem.replace("-", " ").replace("_", " "))
    index: Dict[str, AssetEntry] = {}
    ext_rank = {".svg": 2, ".png": 1}

    for path in _iter_files(root):
        ext = _best_ext(path)
        if ext is None:
            continue
        display = display_fn(path)
        slug = normalize_slug(display, strip_vendor=True)
        if not slug:
            continue
        entry = AssetEntry(
            provider=provider,
            slug=slug,
            display_name=display,
            path=str(path.relative_to(root)),
            ext=ext,
            category=_category_from_path(root, path),
        )
        existing = index.get(slug)
        if existing is None or ext_rank[ext] > ext_rank[existing.ext]:
            index[slug] = entry
    return index


# ---------------------------------------------------------------------------
# Built-in stencil hints (a small, high-value subset; extend via mappings)
# ---------------------------------------------------------------------------

# Known service slug -> built-in mxgraph stencil id. This is intentionally a
# thin, curated set: the nine neutral types are already handled by the Icon
# Resolver; this table lets the asset resolver prefer an editable built-in
# stencil for a few common *specific* services before falling back to a file.
_BUILTIN_STENCILS: Dict[str, Dict[str, str]] = {
    "aws": {
        "eks": "mxgraph.aws4.eks",
        "lambda": "mxgraph.aws4.lambda",
        "s3": "mxgraph.aws4.s3",
        "rds": "mxgraph.aws4.rds",
        "sqs": "mxgraph.aws4.sqs",
        "secrets-manager": "mxgraph.aws4.secrets_manager",
        "bedrock": "mxgraph.aws4.bedrock",
    },
}


def _singularize(token: str) -> str:
    """Naive singular form: drop a trailing plural 's' (keeps short tokens intact)."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _canon_tokens(tokens: List[str]) -> List[str]:
    return [_singularize(t) for t in tokens]


def _tokens_are_contiguous_run(needle: List[str], haystack: List[str]) -> bool:
    """True when ``needle`` appears as a contiguous run of whole tokens in ``haystack``.

    Comparison is singular-insensitive (``vaults`` matches ``vault``). As a
    secondary check, the concatenated (de-spaced) forms are compared so that a
    packed filename like ``vertexai`` matches the query ``vertex ai``.
    """
    n = _canon_tokens(needle)
    h = _canon_tokens(haystack)
    if not n:
        return False
    if len(n) <= len(h):
        for i in range(len(h) - len(n) + 1):
            if h[i : i + len(n)] == n:
                return True
    # Concatenated-form fallback (handles missing separators in file names).
    if "".join(n) == "".join(h):
        return True
    return False


def _best_token_match(
    q_tokens: List[str], index: Dict[str, AssetEntry]
) -> Optional[AssetEntry]:
    """Return the best whole-token subsequence match, or None.

    A candidate qualifies when the query tokens form a contiguous whole-token run
    inside the candidate slug, or the candidate slug's tokens form such a run
    inside the query. Requires at least two shared tokens, or a single token of
    length >= 4, to avoid trivial matches. Prefers SVG, then the fewest extra
    tokens, then the shortest slug for determinism.
    """
    if not q_tokens:
        return None
    q_canon = _canon_tokens(q_tokens)
    q_concat = "".join(q_canon)
    strong_single = len(q_tokens) == 1 and len(q_tokens[0]) >= 4
    candidates: List[AssetEntry] = []
    for slug, entry in index.items():
        c_tokens = [t for t in slug.split("-") if t]
        c_concat = "".join(_canon_tokens(c_tokens))
        concat_equal = q_concat == c_concat
        if (
            concat_equal
            or _tokens_are_contiguous_run(q_tokens, c_tokens)
            or _tokens_are_contiguous_run(c_tokens, q_tokens)
        ):
            shared = min(len(q_tokens), len(c_tokens))
            if concat_equal or shared >= 2 or strong_single:
                candidates.append(entry)
    if not candidates:
        return None
    candidates.sort(
        key=lambda e: (
            e.ext != ".svg",
            abs(len(e.slug.split("-")) - len(q_tokens)),
            len(e.slug),
        )
    )
    return candidates[0]


def resolve_asset(
    provider: str,
    service_name: str,
    index: Optional[Dict[str, AssetEntry]] = None,
) -> ResolvedAsset:
    """Resolve ``service_name`` for ``provider`` to the best available icon.

    Resolution order (deterministic):

    1. a curated **built-in stencil** id, when the vendor-stripped slug is known;
    2. an **official asset file** from ``index`` (exact slug, then substring);
    3. **unresolved**, when nothing matches — the caller must supply an asset.

    For ``oci`` (a shape library, not per-service files), a non-built-in match
    resolves to the OCI draw.io library note rather than a file path.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")

    slug = normalize_slug(service_name, strip_vendor=True)

    builtin = _BUILTIN_STENCILS.get(provider, {}).get(slug)
    if builtin:
        return ResolvedAsset(
            provider=provider, query=service_name, source="builtin",
            stencil=builtin, note="matched curated built-in stencil",
        )

    if index:
        exact = index.get(slug)
        if exact is not None:
            return ResolvedAsset(
                provider=provider, query=service_name, source="official-asset",
                asset_path=exact.path, ext=exact.ext,
                note=f"official {exact.ext} for {exact.display_name!r}",
            )
        # Token-subsequence match: the query tokens must all appear, in order, as
        # a contiguous run of whole tokens in the candidate slug (or vice versa).
        # This avoids 1–2 character false positives like "a" matching "azure-a".
        q_tokens = [t for t in slug.split("-") if t]
        best = _best_token_match(q_tokens, index)
        if best is not None:
            return ResolvedAsset(
                provider=provider, query=service_name, source="official-asset",
                asset_path=best.path, ext=best.ext,
                note=f"nearest official asset {best.display_name!r}",
            )

    if provider == "oci":
        return ResolvedAsset(
            provider=provider, query=service_name, source="official-asset",
            asset_path="OCI Style Guide for Drawio/OCI Library.xml",
            ext=".xml",
            note="embed the OCI stencil (shape=stencil(...) glyph decoded from OCI Library.xml; no mxgraph.oci.* namespace)",
        )

    return ResolvedAsset(
        provider=provider, query=service_name, source="unresolved",
        note="no built-in stencil and no official asset found; supply an icon",
    )


# ---------------------------------------------------------------------------
# Index build / serialization
# ---------------------------------------------------------------------------


def build_index(pack_roots: Dict[str, str]) -> Dict[str, Dict[str, AssetEntry]]:
    """Index several providers at once.

    ``pack_roots`` maps provider -> unpacked pack directory. Providers absent
    from the mapping are skipped. Returns provider -> {slug -> AssetEntry}.
    """
    out: Dict[str, Dict[str, AssetEntry]] = {}
    for provider, root in pack_roots.items():
        out[provider] = index_provider(provider, root)
    return out


def index_to_json(index: Dict[str, Dict[str, AssetEntry]]) -> str:
    """Serialize a built index to a stable, sorted JSON manifest string."""
    payload = {
        provider: {
            slug: asdict(entry)
            for slug, entry in sorted(entries.items())
        }
        for provider, entries in sorted(index.items())
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Neutral-role resolution → committed icon-index.json (v1.3.x)
# ---------------------------------------------------------------------------
#
# A diagram *role* (how a node is drawn) is a superset of the nine neutral
# resource types: it adds presentation-only roles (cdn, dns, waf, lb, cache, …).
# mappings/roles.yaml declares, per role and provider, the service ``query`` to
# resolve against the indexed official pack — plus, for GCP, an optional
# ``gcp_category`` used when a service has no dedicated product icon (Google's
# product-first / category-fallback convention). build_icon_index() resolves
# every role against the packs and writes a committed, deterministic
# icon-index.json so generators and CI resolve/verify without the packs present.

ROLES_PATH = Path(__file__).resolve().parents[2] / "mappings" / "roles.yaml"

# Where each provider's pack unpacks under the asset root, and the on-disk path
# prefix a resolved file lives under (matches what the diagram generators emit).
# GCP resolves against two packs (core products first, then categories).
_PACK_PREFIX = {
    "aws": "assets/vendor/aws-icons",
    "azure": "assets/vendor/azure-icons",
    "gcp-core": "assets/vendor/gcp-core",
    "gcp-category": "assets/vendor/gcp-category",
    "oci": "assets/vendor/oci-stencils",
}


@dataclass
class ResolvedRoleIcon:
    """One role's resolved icon for one provider (an entry in icon-index.json)."""

    role: str
    provider: str
    source: str            # "product" | "category" | "stencil" | "builtin" | "unresolved"
    ref: str = ""          # file path (image providers), "<manifest>#slug" (oci), or stencil id
    display_name: str = ""
    note: str = ""


def _prefixed(pack_key: str, entry: AssetEntry) -> str:
    """Return the repo-relative icon reference for a resolved AssetEntry."""
    prefix = _PACK_PREFIX.get(pack_key, f"assets/vendor/{pack_key}")
    if entry.ext == ".stencil":
        return entry.path  # already an "assets/vendor/oci-stencils/...#slug" ref
    return f"{prefix}/{entry.path}"


def resolve_role_icon(
    role: str,
    provider: str,
    spec: Dict[str, str],
    pack_indexes: Dict[str, Dict[str, AssetEntry]],
) -> ResolvedRoleIcon:
    """Resolve one role for one provider against the indexed packs.

    ``spec`` is the role's per-provider entry from ``roles.yaml`` (keys such as
    ``aws``, ``azure``, ``gcp``, ``gcp_category``, ``oci``). ``pack_indexes`` maps
    a pack key (``aws``/``azure``/``gcp-core``/``gcp-category``/``oci``) to its
    slug index. GCP is product-first (``gcp`` query against ``gcp-core``), then
    category-fallback (``gcp_category`` against ``gcp-category``)."""
    if provider == "gcp":
        # product-first
        prod_q = spec.get("gcp")
        if prod_q:
            hit = _resolve_in(prod_q, pack_indexes.get("gcp-core", {}))
            if hit is not None:
                return ResolvedRoleIcon(role, "gcp", "product", _prefixed("gcp-core", hit),
                                        hit.display_name, "flagship product icon")
        cat = spec.get("gcp_category")
        if cat:
            hit = _resolve_in(cat, pack_indexes.get("gcp-category", {}))
            if hit is not None:
                return ResolvedRoleIcon(role, "gcp", "category", _prefixed("gcp-category", hit),
                                        hit.display_name, f"category icon ({cat}) — no product glyph")
        return ResolvedRoleIcon(role, "gcp", "unresolved", note="no gcp product or category match")

    query = spec.get(provider)
    if not query:
        return ResolvedRoleIcon(role, provider, "unresolved", note="no query declared")
    hit = _resolve_in(query, pack_indexes.get(provider, {}))
    if hit is None:
        return ResolvedRoleIcon(role, provider, "unresolved", note=f"no pack match for {query!r}")
    source = "stencil" if provider == "oci" else "product"
    return ResolvedRoleIcon(role, provider, source, _prefixed(provider, hit),
                            hit.display_name, f"resolved {query!r}")


def _resolve_in(query: str, index: Dict[str, AssetEntry]) -> Optional[AssetEntry]:
    """Resolve a service query within one pack index.

    Order: (1) the query verbatim as a literal slug key (OCI queries in
    roles.yaml are already the library slugs, e.g. ``virtual-cloud-network-vcn``);
    (2) the vendor-stripped normalized slug; (3) a whole-token subsequence match."""
    if not index:
        return None
    literal = index.get(query)
    if literal is not None:
        return literal
    # Try both the vendor-stripped and the full normalized slug (some pack slugs
    # keep the vendor word packed in, e.g. GCP "Cloud SQL" -> slug "cloudsql",
    # which vendor-stripping to "sql" would miss).
    for strip in (True, False):
        slug = normalize_slug(query, strip_vendor=strip)
        exact = index.get(slug)
        if exact is not None:
            return exact
        best = _best_token_match([t for t in slug.split("-") if t], index)
        if best is not None:
            return best
    return None


def build_icon_index(
    pack_roots: Dict[str, str],
    roles_path: Path = ROLES_PATH,
    full_packs: bool = False,
) -> Dict[str, object]:
    """Build the committed icon-index payload: ``packs`` + ``roles`` layers.

    ``pack_roots`` maps a pack key (``aws``/``azure``/``gcp-core``/``gcp-category``
    /``oci``) to its unpacked directory (or, for OCI, the stencils.json / its
    folder). Returns ``{"version", "packs": {provider: {slug: entry}}, "roles":
    {role: {provider: resolved}}}``, ready to serialize deterministically."""
    import yaml  # local import; PyYAML is already a runtime dep

    # Index each pack. GCP is two packs; the others map key==provider.
    pack_indexes: Dict[str, Dict[str, AssetEntry]] = {}
    for key, root in pack_roots.items():
        provider = "gcp" if key.startswith("gcp") else key
        pack_indexes[key] = index_provider(provider, root)

    # A per-provider "packs" view (gcp merges core+category for reference).
    packs_view: Dict[str, Dict[str, AssetEntry]] = {}
    for key, idx in pack_indexes.items():
        provider = "gcp" if key.startswith("gcp") else key
        packs_view.setdefault(provider, {}).update(idx)

    roles_cfg = yaml.safe_load(Path(roles_path).read_text(encoding="utf-8"))
    roles = (roles_cfg or {}).get("roles", {})

    resolved_roles: Dict[str, Dict[str, Dict[str, str]]] = {}
    for role, spec in roles.items():
        per_provider: Dict[str, Dict[str, str]] = {}
        for provider in ("aws", "azure", "gcp", "oci"):
            r = resolve_role_icon(role, provider, spec or {}, pack_indexes)
            per_provider[provider] = {
                "source": r.source, "ref": r.ref,
                "display_name": r.display_name, "note": r.note,
            }
        resolved_roles[role] = per_provider

    payload = {
        "version": 1,
        # Lightweight, committed-friendly pack summary (per-provider slug count +
        # a stable sample), NOT the full ~2000-entry dump — the committed index
        # exists to drive role→icon resolution and CI verification, and the full
        # pack tables are re-derivable on demand. Pass ``full_packs=True`` (or the
        # CLI ``--full``) to embed the complete per-slug tables when needed.
        "pack_summary": {
            provider: {"count": len(entries)}
            for provider, entries in sorted(packs_view.items())
        },
        "roles": {r: resolved_roles[r] for r in sorted(resolved_roles)},
    }
    if full_packs:
        payload["packs"] = {
            provider: {slug: asdict(e) for slug, e in sorted(entries.items())}
            for provider, entries in sorted(packs_view.items())
        }
    return payload


def icon_index_to_json(payload: Dict[str, object]) -> str:
    """Serialize the icon-index payload to stable, sorted JSON."""
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


__all__ = [
    "PROVIDERS",
    "AssetEntry",
    "ResolvedAsset",
    "ResolvedRoleIcon",
    "normalize_slug",
    "index_provider",
    "resolve_asset",
    "resolve_role_icon",
    "build_index",
    "build_icon_index",
    "index_to_json",
    "icon_index_to_json",
    "ROLES_PATH",
]
