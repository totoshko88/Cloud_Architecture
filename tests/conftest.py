"""Shared pytest / Hypothesis configuration for the honest-gates property tests.

Feature: honest-gates (release 1.7.0), task 1.1 — shared test infrastructure.

Two Hypothesis profiles are registered and the ``honest-gates`` profile is
loaded by default so every property test in the suite runs at least
``max_examples=100`` (the convention the tasks file mandates: "Each property
test uses Hypothesis with ``max_examples >= 100``"):

* ``honest-gates`` — the default: ``max_examples=100`` with Hypothesis' normal
  per-example deadline. Use it for the pure-logic properties (parsers,
  validators, redaction, identity, classification).
* ``honest-gates-fs`` — the same example budget but ``deadline=None``, for the
  filesystem-backed properties (the Collector writing snapshot folders, the
  Fetcher unpacking archives, ``rule-engine-init`` copying trees). Disk I/O
  makes per-example timing noisy, so a deadline there produces flaky
  ``DeadlineExceeded`` failures rather than real defects. A test opts in with
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
