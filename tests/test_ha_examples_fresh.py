"""Freshness guard: the committed HA golden .drawio match the generator (1.10.1).

The 1.10.1 hotfix surfaced a governance gap. The HA multi-region landscape
goldens (``examples/<provider>/02-<provider>-ha-multiregion-landscape.drawio``)
had drifted from the shared generator — an older router had merged edges ``l1``
(``dns->lb``) and ``l15`` (``cdn->lb``) onto one y=240 corridor, and the
committed files were never regenerated after the router was improved to separate
them. Nothing caught it: ``test_ha_generator_parity.py`` builds from the
*generator* (so it validated the fresh, clean geometry), and ``corridor-sharing``
had a blind spot that exempted any two same-target edges wholesale — so the stale
merge linted clean and shipped.

This test wires the generators' own ``--check`` freshness comparison into the
suite: for every buildable provider it regenerates the summary and landscape in
memory and asserts they are byte-identical to the committed files. A committed
golden that drifts from the generator now fails here, on any provider, rather
than silently shipping stale.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "src"))
sys.path.insert(0, os.path.join(HERE, "scripts"))

from ha_multiregion_common import build_summary, build_landscape  # noqa: E402

PROVIDERS = ("aws", "azure", "gcp", "oci")

# OCI renders via embedded stencils fetched on demand; absent in a bare CI
# checkout. Geometry/serialization is skin-independent, so aws/azure/gcp still
# exercise the shared generator when OCI's stencils are missing.
_OCI_STENCILS = os.path.join(HERE, "assets", "vendor", "oci-stencils", "stencils.json")
_BUILDABLE = tuple(p for p in PROVIDERS if p != "oci" or os.path.isfile(_OCI_STENCILS))


def _skin(provider: str):
    return importlib.import_module(f"build_{provider}_ha_example").SKIN


def _committed(provider: str, kind: str) -> str:
    path = os.path.join(
        HERE, "examples", provider, f"02-{provider}-ha-multiregion-{kind}.drawio"
    )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("provider", _BUILDABLE)
def test_committed_landscape_matches_generator(provider):
    """The committed landscape .drawio is byte-identical to the generator's
    output — the guard the stale l1/l15 merge slipped past before 1.10.1."""
    regenerated = build_landscape(_skin(provider))
    assert regenerated == _committed(provider, "landscape"), (
        f"{provider} landscape is STALE — regenerate with "
        f"scripts/build_{provider}_ha_example.py"
    )


@pytest.mark.parametrize("provider", _BUILDABLE)
def test_committed_summary_matches_generator(provider):
    """The committed summary .drawio is byte-identical to the generator."""
    regenerated = build_summary(_skin(provider))
    assert regenerated == _committed(provider, "summary"), (
        f"{provider} summary is STALE — regenerate with "
        f"scripts/build_{provider}_ha_example.py"
    )
