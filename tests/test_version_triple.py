"""Guard: ``VERSION``, ``pyproject.toml`` and ``CHANGELOG.md`` agree (v1.6.0).

The released version is recorded in three places. At 1.5.4 they drifted — the
working tree carried ``VERSION`` = 1.5.3 against ``pyproject.toml`` = 1.5.4 and
a top CHANGELOG heading of 1.5.4 — and nothing surfaced it, because CI rewrites
``VERSION`` at tag time so a stale file never broke a release. These tests make
the triple a checked contract, and exercise the ``--triple`` CLI mode the
release pipelines run right after writing ``VERSION`` from the tag (the GitHub
``release`` job and the GitLab ``build`` stage). Until 1.6.1 this docstring said
the CI version-guard stage ran it; no pipeline did — see
``tests/test_hooks_and_ci_gates.py``, which now pins the wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rule_engine.version_guard import (
    CHANGELOG_FILE,
    PYPROJECT_FILE,
    VERSION_FILE,
    VersionMismatchError,
    assert_version_triple_consistent,
    latest_changelog_version,
    main,
    read_changelog_version,
    read_pyproject_version,
    read_version_file,
    version_triple,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: ``VERSION`` is **git-ignored** and written by CI at tag time
#: (`.gitlab-ci.yml` → ``echo "${RELEASE_VERSION}" > VERSION``), so a fresh clone
#: legitimately has no such file. That is the designed state, not drift — CI's own
#: release gate checks the tag against the CHANGELOG instead
#: (``version_guard CHANGELOG.md "${RELEASE_VERSION}"``).
#:
#: The tests that build their **own** trees below therefore always run; only the
#: four that read the **real** repository are conditional. Whenever the file does
#: exist — a developer's working tree, or a CI job after the tag stage — they run
#: and a disagreement fails, which is exactly the 1.5.4 drift this module was
#: written to catch. Asserting the file's presence unconditionally would instead
#: turn every bare-checkout pipeline red.
requires_version_file = pytest.mark.skipif(
    read_version_file(_REPO_ROOT) is None,
    reason="VERSION is git-ignored and written by CI at tag time; absent in a bare checkout",
)


# ---------------------------------------------------------------------------
# The real repository
# ---------------------------------------------------------------------------


@requires_version_file
def test_this_repository_has_a_consistent_version_triple():
    """The shipped tree's three version sources agree.

    This is the regression that 1.6.0 adds: the check runs against the actual
    repo, so a bump that forgets one file fails the suite instead of shipping.
    """
    agreed = assert_version_triple_consistent(_REPO_ROOT)
    assert agreed, "the agreed version must be a non-empty Semantic Version"


@requires_version_file
def test_repo_version_sources_are_all_present():
    """Each of the three sources is readable and carries a version."""
    versions = version_triple(_REPO_ROOT)
    assert set(versions) == {VERSION_FILE, PYPROJECT_FILE, CHANGELOG_FILE}
    for name, value in versions.items():
        assert value, f"{name} records no version"


def test_the_two_committed_sources_always_agree():
    """``pyproject.toml`` and the top CHANGELOG heading are both **committed**, so
    they must agree in every checkout — including a bare one with no ``VERSION``.

    This is the part of the triple that a fresh clone can still check, and it is
    the half that a version bump actually has to edit by hand.
    """
    pyproject = read_pyproject_version(_REPO_ROOT)
    changelog = read_changelog_version(_REPO_ROOT)
    assert pyproject, "pyproject.toml records no version"
    assert pyproject == changelog, (
        f"pyproject.toml={pyproject!r} but the newest CHANGELOG section is "
        f"{changelog!r}; both are committed, so they must agree"
    )


# ---------------------------------------------------------------------------
# Per-source readers
# ---------------------------------------------------------------------------


def _write_triple(
    root: Path,
    version_txt: str | None = "1.6.0",
    pyproject_version: str | None = "1.6.0",
    changelog_version: str | None = "1.6.0",
) -> None:
    if version_txt is not None:
        (root / VERSION_FILE).write_text(f"{version_txt}\n", encoding="utf-8")
    if pyproject_version is not None:
        (root / PYPROJECT_FILE).write_text(
            "[project]\n"
            'name = "rule-engine"\n'
            f'version = "{pyproject_version}"\n'
            "dependencies = [\n"
            '    "jsonschema>=4.18",\n'
            "]\n",
            encoding="utf-8",
        )
    if changelog_version is not None:
        (root / CHANGELOG_FILE).write_text(
            "# Changelog\n\nIntro prose.\n\n"
            f"## [{changelog_version}] - 2026-09-25\n\n### Fixed\n\n- thing\n\n"
            "## [1.0.0] - 2026-01-01\n\n- first\n",
            encoding="utf-8",
        )


def test_read_version_file_strips_whitespace_and_v_prefix(tmp_path):
    (tmp_path / VERSION_FILE).write_text("  v1.6.0  \n", encoding="utf-8")
    assert read_version_file(tmp_path) == "1.6.0"


def test_read_version_file_missing_is_none(tmp_path):
    assert read_version_file(tmp_path) is None


def test_read_pyproject_version_ignores_dependency_pins(tmp_path):
    """A dependency floor like ``jsonschema>=4.18`` is not mistaken for the
    project version (the regex is line-anchored on ``version =``)."""
    _write_triple(tmp_path, pyproject_version="1.6.0")
    assert read_pyproject_version(tmp_path) == "1.6.0"


def test_read_pyproject_version_missing_is_none(tmp_path):
    assert read_pyproject_version(tmp_path) is None


def test_latest_changelog_version_takes_the_first_heading():
    """The Changelog is reverse chronological, so the newest section wins."""
    text = (
        "# Changelog\n\n"
        "## [1.6.0] - 2026-09-25\n\n"
        "## [1.5.4] - 2026-09-25\n\n"
        "## [1.0.0] - 2026-01-01\n"
    )
    assert latest_changelog_version(text) == "1.6.0"


def test_latest_changelog_version_tolerates_a_v_prefix():
    assert latest_changelog_version("## [v2.0.0] - 2026-09-25\n") == "2.0.0"


def test_latest_changelog_version_with_no_heading_is_none():
    assert latest_changelog_version("# Changelog\n\nNo releases yet.\n") is None


def test_read_changelog_version_missing_file_is_none(tmp_path):
    assert read_changelog_version(tmp_path) is None


# ---------------------------------------------------------------------------
# The consistency assertion
# ---------------------------------------------------------------------------


def test_consistent_triple_returns_the_agreed_version(tmp_path):
    _write_triple(tmp_path)
    assert assert_version_triple_consistent(tmp_path) == "1.6.0"


def test_stale_version_file_is_a_mismatch(tmp_path):
    """The exact 1.5.4 drift: VERSION lags pyproject and the Changelog."""
    _write_triple(tmp_path, version_txt="1.5.3", pyproject_version="1.5.4",
                  changelog_version="1.5.4")
    with pytest.raises(VersionMismatchError) as excinfo:
        assert_version_triple_consistent(tmp_path)
    # The error must NAME the offending sources, not just report a failure.
    assert excinfo.value.versions[VERSION_FILE] == "1.5.3"
    assert excinfo.value.versions[PYPROJECT_FILE] == "1.5.4"
    assert VERSION_FILE in str(excinfo.value)


def test_unwritten_changelog_section_is_a_mismatch(tmp_path):
    """Bumping the code but forgetting the Changelog entry is caught."""
    _write_triple(tmp_path, version_txt="1.6.0", pyproject_version="1.6.0",
                  changelog_version="1.5.4")
    with pytest.raises(VersionMismatchError):
        assert_version_triple_consistent(tmp_path)


def test_missing_source_is_fail_closed(tmp_path):
    """A deleted ``VERSION`` must not quietly reduce the contract to two sources."""
    _write_triple(tmp_path, version_txt=None)
    with pytest.raises(VersionMismatchError) as excinfo:
        assert_version_triple_consistent(tmp_path)
    assert excinfo.value.versions[VERSION_FILE] is None


# ---------------------------------------------------------------------------
# CLI (--triple), as the release pipelines invoke it after writing VERSION
# ---------------------------------------------------------------------------


def test_cli_triple_ok_on_a_consistent_tree(tmp_path, capsys):
    _write_triple(tmp_path)
    assert main(["--triple", str(tmp_path)]) == 0
    assert "agree" in capsys.readouterr().out


def test_cli_triple_blocks_on_a_mismatch(tmp_path, capsys):
    _write_triple(tmp_path, version_txt="1.5.3")
    assert main(["--triple", str(tmp_path)]) == 1
    assert "BLOCKING" in capsys.readouterr().err


def test_cli_triple_rejects_extra_arguments(capsys):
    assert main(["--triple", "a", "b"]) == 2


@requires_version_file
def test_cli_triple_on_this_repository(capsys):
    """The CLI mode CI runs passes against the real tree."""
    assert main(["--triple", str(_REPO_ROOT)]) == 0


def test_cli_still_supports_the_two_argument_changelog_check(tmp_path, capsys):
    """The pre-1.6.0 invocation (changelog + version) is unchanged."""
    _write_triple(tmp_path)
    assert main([str(tmp_path / CHANGELOG_FILE), "1.6.0"]) == 0
    assert main([str(tmp_path / CHANGELOG_FILE), "9.9.9"]) == 1
