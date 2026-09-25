"""Guard: the build-time bootstrap payload and the init-time bundle map agree.

``build_backend._PAYLOAD`` stages the workspace bootstrap trees into the wheel;
``init_workspace._BUNDLE_MAP`` / ``_BOOTSTRAP_DIRS`` reconstruct them in a target
workspace. The two are documented as "keep in sync" but nothing enforced it — a
tree added to one and forgotten in the other ships in the wheel yet is never
copied out (or vice versa), a silent bootstrap gap. These tests make the sync a
checked contract.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from rule_engine import init_workspace as iw

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_build_backend():
    spec = importlib.util.spec_from_file_location(
        "build_backend", _REPO_ROOT / "build_backend.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_payload_sources_match_bootstrap_dirs():
    """Every workspace tree init copies (_BOOTSTRAP_DIRS) is staged by the build
    backend (_PAYLOAD), and vice versa — no tree is bundled-but-uncopied or
    copied-but-unbundled."""
    bb = _load_build_backend()
    payload_sources = set(bb._PAYLOAD.keys())
    bootstrap_dirs = set(iw._BOOTSTRAP_DIRS)
    assert payload_sources == bootstrap_dirs, (
        "build_backend._PAYLOAD and init_workspace._BOOTSTRAP_DIRS diverged: "
        f"only in _PAYLOAD={payload_sources - bootstrap_dirs}, "
        f"only in _BOOTSTRAP_DIRS={bootstrap_dirs - payload_sources}"
    )


def test_dot_free_remap_matches_between_backend_and_init():
    """The dot-directory remap (``.kiro/steering`` -> ``kiro/steering``) is
    identical in the build backend and init, so a bundled tree lands where init
    looks for it."""
    bb = _load_build_backend()
    # The backend's remap = payload entries whose destination differs from source.
    backend_remap = {
        src: dst for src, dst in bb._PAYLOAD.items() if src != dst
    }
    assert backend_remap == iw._BUNDLE_MAP, (
        "the dot-free remap differs between build_backend._PAYLOAD and "
        f"init_workspace._BUNDLE_MAP: backend={backend_remap}, init={iw._BUNDLE_MAP}"
    )
