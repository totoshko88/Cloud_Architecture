"""Tests for the release tooling added after 1.10.1.

* ``rule_engine.version_pins`` — the single table of version pins, shared by
  ``scripts/release.py bump`` and these tests;
* ``rule_engine.version_guard.changelog_date_problems`` — the CHANGELOG date
  contract whose absence let 1.9.0-1.10.1 ship dated up to four days ahead;
* ``scripts/release.py`` — ``bump`` (pins + CHANGELOG heading) and the
  ``publish`` dry-run runner.
"""

from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

import release  # noqa: E402
from rule_engine.version_guard import changelog_date_problems, read_pyproject_version  # noqa: E402
from rule_engine.version_pins import PINS, read_pin, rewrite_pin  # noqa: E402

TODAY = date(2026, 9, 28)


# --------------------------------------------------------------------------- #
# Pin table
# --------------------------------------------------------------------------- #


def test_every_required_pin_matches_pyproject():
    """The committed tree is consistent: every pin holds the pyproject version."""
    assert release.pin_problems(_REPO) == []


@pytest.mark.parametrize("pin", [p for p in PINS if p.required], ids=lambda p: p.path)
def test_required_pins_exist_and_match_once(pin):
    found = read_pin(_REPO, pin)
    assert found is not None, f"{pin.path} is missing"
    assert len(found) == pin.count


def _copy_pinned_tree(tmp_path: Path) -> Path:
    for pin in PINS:
        src = _REPO / pin.path
        if src.is_file():
            dst = tmp_path / pin.path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    shutil.copy2(_REPO / "CHANGELOG.md", tmp_path / "CHANGELOG.md")
    return tmp_path


def test_rewrite_changes_only_the_version(tmp_path):
    root = _copy_pinned_tree(tmp_path)
    for pin in PINS:
        if read_pin(root, pin) is None:
            continue
        old, new = rewrite_pin(root, pin, "9.8.7")
        assert read_pin(root, pin) != ["9.8.7"]  # rewrite_pin never writes
        old_lines, new_lines = old.splitlines(), new.splitlines()
        assert len(old_lines) == len(new_lines)
        changed = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
        assert changed, f"{pin.path}: nothing rewritten"
        for a, b in changed:
            # the only difference on each changed line is the version itself
            assert a.replace(read_pyproject_version(_REPO), "9.8.7") == b


def test_rewrite_refuses_a_drifted_pin(tmp_path):
    root = _copy_pinned_tree(tmp_path)
    pin = PINS[0]
    (root / pin.path).write_text("no version here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        rewrite_pin(root, pin, "9.8.7")


def test_bump_updates_every_pin_and_dates_the_changelog(tmp_path, monkeypatch):
    root = _copy_pinned_tree(tmp_path)
    monkeypatch.setattr(release, "REPO", root)
    monkeypatch.setattr(release, "CHANGELOG", root / "CHANGELOG.md")
    current = read_pyproject_version(root)
    major, minor, patch = (int(x) for x in current.split("."))
    new = f"{major}.{minor}.{patch + 1}"
    had_unreleased = "## [Unreleased]" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    rc = release.main(["bump", new, "--date", TODAY.isoformat()])
    assert rc == 0
    assert release.pin_problems(root) == []
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{new}] - {TODAY.isoformat()}" in text
    if had_unreleased:
        # The [Unreleased] section became the release; nothing to fill in.
        assert "## [Unreleased]" not in text
        assert release.PLACEHOLDER not in text
    else:
        assert release.PLACEHOLDER in text  # publish refuses until it is filled in


def test_bump_refuses_a_non_increasing_version(tmp_path, monkeypatch):
    root = _copy_pinned_tree(tmp_path)
    monkeypatch.setattr(release, "REPO", root)
    monkeypatch.setattr(release, "CHANGELOG", root / "CHANGELOG.md")
    assert release.main(["bump", "1.0.0"]) == 2


# --------------------------------------------------------------------------- #
# CHANGELOG heading insertion
# --------------------------------------------------------------------------- #

_CL = "# Changelog\n\nIntro.\n\n## [1.2.0] - 2026-09-20\n\n- a\n"


def test_unreleased_section_becomes_the_release():
    text = "# Changelog\n\n## [Unreleased]\n\n- pending\n\n## [1.2.0] - 2026-09-20\n"
    out = release.changelog_with_release(text, "1.3.0", TODAY)
    assert "## [Unreleased]" not in out
    assert "## [1.3.0] - 2026-09-28\n\n- pending" in out


def test_skeleton_goes_above_the_newest_release():
    out = release.changelog_with_release(_CL, "1.3.0", TODAY)
    assert out.index("## [1.3.0] - 2026-09-28") < out.index("## [1.2.0]")
    assert release.PLACEHOLDER in out


def test_duplicate_version_is_refused():
    with pytest.raises(ValueError):
        release.changelog_with_release(_CL, "1.2.0", TODAY)


# --------------------------------------------------------------------------- #
# CHANGELOG date contract
# --------------------------------------------------------------------------- #


def test_the_real_changelog_has_valid_dates():
    """The guard that would have caught the 1.9.0-1.10.1 future dates."""
    text = (_REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog_date_problems(text) == []


def _cl(*headings: str) -> str:
    return "# Changelog\n\n" + "".join(f"{h}\n\n- x\n\n" for h in headings)


def test_future_date_is_flagged():
    problems = changelog_date_problems(_cl("## [1.3.0] - 2026-10-02"), today=TODAY)
    assert any("future" in p for p in problems)


def test_one_day_timezone_slack_is_allowed():
    assert changelog_date_problems(_cl("## [1.3.0] - 2026-09-29"), today=TODAY) == []


def test_dates_must_not_increase_going_down():
    text = _cl("## [1.3.0] - 2026-09-20", "## [1.2.0] - 2026-09-25")
    problems = changelog_date_problems(text, today=TODAY)
    assert any("later than the newer release" in p for p in problems)


def test_equal_dates_are_fine():
    text = _cl("## [1.3.0] - 2026-09-28", "## [1.2.0] - 2026-09-28")
    assert changelog_date_problems(text, today=TODAY) == []


@pytest.mark.parametrize("bad", ["2026-02-30", "2026-9-28", "28-09-2026", "yesterday"])
def test_invalid_dates_are_flagged(bad):
    problems = changelog_date_problems(_cl(f"## [1.3.0] - {bad}"), today=TODAY)
    assert any("not a real" in p for p in problems)


def test_missing_date_is_flagged():
    problems = changelog_date_problems(_cl("## [1.3.0]"), today=TODAY)
    assert any("no release date" in p for p in problems)


def test_unreleased_heading_is_ignored():
    text = _cl("## [Unreleased]", "## [1.2.0] - 2026-09-20")
    assert changelog_date_problems(text, today=TODAY) == []


def test_dates_cli_mode(tmp_path):
    from rule_engine.version_guard import main

    good = tmp_path / "good.md"
    good.write_text(_cl("## [1.2.0] - 2026-09-20"), encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text(_cl("## [1.2.0] - 2099-01-01"), encoding="utf-8")
    assert main(["--dates", str(good)]) == 0
    assert main(["--dates", str(bad)]) == 1


# --------------------------------------------------------------------------- #
# publish runner
# --------------------------------------------------------------------------- #


def test_dry_run_runner_executes_nothing(capsys, tmp_path):
    marker = tmp_path / "ran"
    run = release.Runner(dry_run=True)
    result = run(["touch", str(marker)])
    assert result.returncode == 0
    assert not marker.exists()
    assert "touch" in capsys.readouterr().out


def test_theme_is_taken_from_the_changelog_section():
    assert release._theme("**Theme: faster gates.** More text.") == "faster gates"
    assert release._theme("no theme line") == "release"
