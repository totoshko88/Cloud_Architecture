"""Tests for the changelog/version guard logic (task 12.3).

Exercises the release version guard (``src/rule_engine/version_guard.py``) and
the CI wiring in ``.gitlab-ci.yml`` that enforce the two Requirement 10 fail
conditions:

- Requirement 10.7 (hand-curated CHANGELOG contract): IF a release trigger
  specifies a Semantic Version that has NO curated section in the Changelog,
  THEN the CI Pipeline fails the run and produces no Release Bundle. The
  Changelog is authored by hand and CI never rewrites it, so a release must not
  proceed until its section exists. Covered by the ``version_guard`` unit
  (``changelog_has_version``, ``assert_version_present``, ``MissingVersionError``,
  and the ``main`` CLI), which fails-closed on a missing version section.
- Requirement 10.3: IF the Linter reports >=1 CRITICAL/ERROR finding, THEN the
  CI Pipeline fails the run and produces no Release Bundle. The testable proxy
  in the pipeline definition is the stage/needs graph: the ``build`` job (which
  packages the Release Bundle) ``needs`` the ``lint`` gate (and ``validate`` /
  ``version-guard``), so a failed lint short-circuits the pipeline before any
  bundle is built. The ``lint`` job runs the fail-closed lint command.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rule_engine.version_guard import (
    MissingVersionError,
    assert_version_present,
    changelog_has_version,
    main,
    normalize_version,
)

# Repository root is one level up from this tests/ directory.
REPO_ROOT = Path(__file__).resolve().parents[1]
GITLAB_CI = REPO_ROOT / ".gitlab-ci.yml"

# A Changelog with a single released version section heading.
_CHANGELOG_WITH_123 = """# Changelog

All notable changes are recorded here in reverse chronological order.

## [1.2.3] - 2025-01-15

### Added
- Initial release.
"""

# A Changelog whose version heading carries a leading "v".
_CHANGELOG_WITH_V123 = """# Changelog

## [v1.2.3] - 2025-01-15

### Added
- Initial release.
"""


# =========================================================================== #
# Requirement 10.7 — a release requires a curated Changelog section (present).
# =========================================================================== #


def test_normalize_version_drops_leading_v_and_whitespace() -> None:
    """normalize_version yields the bare MAJOR.MINOR.PATCH string."""
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("  1.2.3 ") == "1.2.3"
    assert normalize_version("1.2.3") == "1.2.3"


def test_changelog_has_version_true_for_present_version() -> None:
    """A version present as a `## [1.2.3]` heading is detected."""
    assert changelog_has_version(_CHANGELOG_WITH_123, "1.2.3") is True


@pytest.mark.parametrize("requested", ["1.2.3", "v1.2.3"])
def test_changelog_has_version_is_v_prefix_tolerant(requested: str) -> None:
    """The presence check tolerates an optional leading `v` on either side."""
    # Recorded without a "v"; requested with or without a "v".
    assert changelog_has_version(_CHANGELOG_WITH_123, requested) is True
    # Recorded with a "v"; requested with or without a "v".
    assert changelog_has_version(_CHANGELOG_WITH_V123, requested) is True


def test_changelog_has_version_false_for_absent_version() -> None:
    """A version that has no heading is reported absent."""
    assert changelog_has_version(_CHANGELOG_WITH_123, "9.9.9") is False


def test_changelog_has_version_false_for_empty_changelog() -> None:
    """An empty changelog contains no version."""
    assert changelog_has_version("", "1.2.3") is False


def test_changelog_has_version_does_not_match_substring_version() -> None:
    """`1.2.3` must not be reported present merely because `1.2.30` exists."""
    changelog = "## [1.2.30] - 2025-01-15\n"
    assert changelog_has_version(changelog, "1.2.3") is False


def test_assert_version_present_ok_for_curated_version(tmp_path: Path) -> None:
    """assert_version_present does not raise when the section exists."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG_WITH_123, encoding="utf-8")

    # No exception for a version that has a curated section.
    assert assert_version_present(changelog, "1.2.3") is None


def test_assert_version_present_ok_for_v_prefix(tmp_path: Path) -> None:
    """A v-prefixed request for a recorded bare version is present."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG_WITH_123, encoding="utf-8")

    assert assert_version_present(changelog, "v1.2.3") is None


def test_assert_version_present_raises_when_section_missing(tmp_path: Path) -> None:
    """assert_version_present raises MissingVersionError when absent."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG_WITH_123, encoding="utf-8")

    with pytest.raises(MissingVersionError) as excinfo:
        assert_version_present(changelog, "2.0.0")

    # The error is fail-closed and names the offending version.
    assert excinfo.value.version == "2.0.0"
    assert "2.0.0" in str(excinfo.value)


def test_assert_version_present_raises_on_missing_changelog(tmp_path: Path) -> None:
    """A missing changelog file means the curated section cannot exist."""
    missing = tmp_path / "does-not-exist" / "CHANGELOG.md"
    assert not missing.exists()

    with pytest.raises(MissingVersionError):
        assert_version_present(missing, "1.2.3")


# --------------------------------------------------------------------------- #
# Requirement 10.7 — the CLI main() fail-closes when the section is missing.
# --------------------------------------------------------------------------- #


def test_main_returns_zero_when_version_present(tmp_path: Path) -> None:
    """main() exits 0 (safe to build) when the curated section exists."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG_WITH_123, encoding="utf-8")

    assert main([str(changelog), "1.2.3"]) == 0
    # v-prefix tolerant.
    assert main([str(changelog), "v1.2.3"]) == 0


def test_main_returns_one_when_version_absent(tmp_path: Path) -> None:
    """main() exits 1 (fail-closed, no bundle) when the section is missing."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG_WITH_123, encoding="utf-8")

    assert main([str(changelog), "2.0.0"]) == 1


def test_main_returns_one_for_missing_changelog(tmp_path: Path) -> None:
    """main() exits 1 when the changelog file does not exist."""
    missing = tmp_path / "CHANGELOG.md"
    assert main([str(missing), "1.2.3"]) == 1


def test_main_returns_two_on_bad_usage(tmp_path: Path) -> None:
    """main() exits 2 on incorrect argument counts (usage error)."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(_CHANGELOG_WITH_123, encoding="utf-8")

    assert main([]) == 2
    assert main([str(changelog)]) == 2
    assert main([str(changelog), "1.2.3", "extra"]) == 2


# =========================================================================== #
# Requirement 10.3 — a lint failure short-circuits the bundle step.
#
# Testable proxy: parse .gitlab-ci.yml and assert the stage/needs graph makes a
# failed lint stop the pipeline before the build job packages a Release Bundle.
# =========================================================================== #


@pytest.fixture(scope="module")
def ci_config() -> dict:
    """Parse the CI pipeline definition once for the pipeline-wiring tests."""
    assert GITLAB_CI.exists(), f"CI definition missing: {GITLAB_CI}"
    with GITLAB_CI.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_ci_defines_lint_before_build_stage(ci_config: dict) -> None:
    """The `lint` stage is ordered before the `build` stage."""
    stages = ci_config["stages"]
    assert "lint" in stages
    assert "build" in stages
    assert stages.index("lint") < stages.index("build")


def test_ci_lint_job_runs_fail_closed_linter(ci_config: dict) -> None:
    """The lint job runs `rule-engine-lint --all --fail-on error,critical`."""
    lint_job = ci_config["lint"]
    assert lint_job["stage"] == "lint"
    script = "\n".join(lint_job["script"])
    assert "rule-engine-lint --all --fail-on error,critical" in script


def test_ci_build_needs_lint_so_lint_failure_short_circuits_bundle(
    ci_config: dict,
) -> None:
    """The build job (which packages the bundle) needs the lint gate.

    Because `build` declares `needs: [lint, ...]`, a failed lint job means the
    build job never runs and therefore no Release Bundle is produced
    (Requirement 10.3).
    """
    build_job = ci_config["build"]
    assert build_job["stage"] == "build"

    needs = build_job["needs"]
    # `needs` entries may be strings or mappings ({"job": name, ...}).
    need_names = {n if isinstance(n, str) else n["job"] for n in needs}

    assert "lint" in need_names, (
        "build must depend on lint so a lint CRITICAL/ERROR short-circuits the "
        "pipeline before the Release Bundle is packaged (Requirement 10.3)"
    )
    # The release gate also depends on schema validation and the version guard.
    assert "validate" in need_names
    assert "version-guard" in need_names


def test_ci_release_gates_depend_on_lint_transitively(ci_config: dict) -> None:
    """version-guard also needs lint, so the whole release path is gated."""
    version_guard = ci_config["version-guard"]
    needs = version_guard["needs"]
    need_names = {n if isinstance(n, str) else n["job"] for n in needs}
    assert "lint" in need_names
    assert "validate" in need_names


def test_ci_version_guard_runs_the_guard_before_build(ci_config: dict) -> None:
    """The version-guard job runs the shared guard on CHANGELOG.md (10.7)."""
    version_guard = ci_config["version-guard"]
    assert version_guard["stage"] == "version-guard"

    stages = ci_config["stages"]
    assert stages.index("version-guard") < stages.index("build")

    script = "\n".join(version_guard["script"])
    assert "rule_engine.version_guard CHANGELOG.md" in script


def test_ci_changelog_stage_is_non_destructive(ci_config: dict) -> None:
    """The changelog stage verifies the curated entry; it never rewrites it.

    The hand-curated CHANGELOG.md is authoritative, so CI must not open it for
    writing. The stage only re-runs the version guard and publishes the file.
    """
    changelog_job = ci_config["changelog"]
    script = "\n".join(changelog_job["script"])
    # It re-verifies the curated section via the shared guard...
    assert "rule_engine.version_guard CHANGELOG.md" in script
    # ...and does not generate/insert a templated entry.
    assert "### Added" not in script
    assert "'w'" not in script and "open(path, 'w'" not in script
