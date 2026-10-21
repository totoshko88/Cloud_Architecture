"""Shared pytest / Hypothesis configuration for the honest-gates property tests.

Feature: honest-gates (release 1.7.0), task 1.1 — shared test infrastructure.

Two Hypothesis profiles are registered and the ``honest-gates`` profile is
loaded by default so every property test in the suite runs at least
``max_examples=100`` (the convention the tasks file mandates: "Each property
test uses Hypothesis with ``max_examples >= 100``"):

* ``honest-gates`` — the default: ``max_examples=100`` with ``deadline=None``.
  The deadline is disabled because the placement/routing property tests exercise
  the real engine, whose per-example work exceeds Hypothesis' 200ms default on a
  loaded CI runner — a deadline there measured machine speed, not correctness,
  and produced flaky ``DeadlineExceeded`` failures under the parallel py3.x
  matrix. ``max_examples`` still enforces the example budget.
* ``honest-gates-fs`` — the same example budget, also ``deadline=None``, for the
  filesystem-backed properties (the Collector writing snapshot folders, the
  Fetcher unpacking archives, ``rule-engine-init`` copying trees). Disk I/O
  makes per-example timing noisy for the same reason. A test opts in with
  ``@settings(settings.get_profile("honest-gates-fs"))`` (or the
  ``fs_settings`` helper re-exported from :mod:`tests.strategies`).

Selecting a profile explicitly on the command line still works, e.g.::

    pytest --hypothesis-profile=honest-gates-fs

This module registers the profiles unconditionally and loads the default one;
tests never have to register them themselves.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings

#: Example budget shared by both profiles (tasks: ``max_examples >= 100``).
MAX_EXAMPLES = 100

settings.register_profile(
    "honest-gates",
    max_examples=MAX_EXAMPLES,
    # ``deadline=None``: these property tests exercise the real placement and
    # routing engine, whose per-example work legitimately exceeds Hypothesis's
    # default 200ms deadline on a loaded CI runner (e.g. the parallel py3.x
    # matrix). The deadline measured machine speed, not correctness, so a busy
    # runner produced spurious ``DeadlineExceeded`` failures
    # (``test_scored_router_is_deterministic`` / ``test_placement_deterministic``
    # at ~400ms under load) that blocked release while passing in isolation.
    # ``max_examples`` still guarantees the example budget.
    deadline=None,
    # ``function_scoped_fixture`` is suppressed so a property test may still take
    # a ``tmp_path`` fixture without Hypothesis warning about re-use across
    # examples — the filesystem properties manage their own per-example dirs.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

settings.register_profile(
    "honest-gates-fs",
    max_examples=MAX_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Load the default profile for the whole suite.
settings.load_profile("honest-gates")
