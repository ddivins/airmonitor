from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from unittest import mock

from airmonitor.update_check import check_for_update, fetch_remote_head, read_installed_commit


# --- read_installed_commit ---------------------------------------------------

def test_read_installed_commit_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_installed_commit(tmp_path) is None


def test_read_installed_commit_reads_and_strips(tmp_path: Path) -> None:
    (tmp_path / "installed-commit").write_text("abc123\n", encoding="utf-8")
    assert read_installed_commit(tmp_path) == "abc123"


def test_read_installed_commit_blank_file_returns_none(tmp_path: Path) -> None:
    (tmp_path / "installed-commit").write_text("\n", encoding="utf-8")
    assert read_installed_commit(tmp_path) is None


# --- fetch_remote_head (mocked subprocess, never a real network call) -------

def test_fetch_remote_head_parses_ls_remote_output() -> None:
    runner = mock.Mock(return_value=subprocess.CompletedProcess(
        [], 0, stdout="abc123def456\trefs/heads/main\n", stderr=""
    ))
    sha = fetch_remote_head("https://example.invalid/repo.git", "main", runner=runner)
    assert sha == "abc123def456"
    args = runner.call_args[0][0]
    assert args == ["git", "ls-remote", "https://example.invalid/repo.git", "refs/heads/main"]


def test_fetch_remote_head_returns_none_on_nonzero_exit() -> None:
    runner = mock.Mock(return_value=subprocess.CompletedProcess([], 128, stdout="", stderr="fatal: repo not found"))
    assert fetch_remote_head(runner=runner) is None


def test_fetch_remote_head_returns_none_on_empty_output() -> None:
    runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    assert fetch_remote_head(runner=runner) is None


def test_fetch_remote_head_returns_none_on_timeout() -> None:
    runner = mock.Mock(side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5))
    assert fetch_remote_head(runner=runner) is None


def test_fetch_remote_head_returns_none_when_git_missing() -> None:
    runner = mock.Mock(side_effect=FileNotFoundError())
    assert fetch_remote_head(runner=runner) is None


# --- check_for_update (pure orchestration, injected readers) -----------------

def test_check_for_update_reports_update_available() -> None:
    result = check_for_update(
        installed_commit_reader=lambda: "old-sha",
        remote_head_reader=lambda: "new-sha",
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result["update_available"] is True
    assert result["installed_commit"] == "old-sha"
    assert result["latest_commit"] == "new-sha"
    assert result["error"] is None


def test_check_for_update_reports_up_to_date() -> None:
    result = check_for_update(installed_commit_reader=lambda: "same-sha", remote_head_reader=lambda: "same-sha")
    assert result["update_available"] is False
    assert result["error"] is None


def test_check_for_update_reports_error_when_installed_commit_unknown() -> None:
    result = check_for_update(installed_commit_reader=lambda: None, remote_head_reader=lambda: "new-sha")
    assert result["update_available"] is None
    assert result["error"] == "installed commit unknown"


def test_check_for_update_reports_error_when_remote_unreachable() -> None:
    result = check_for_update(installed_commit_reader=lambda: "some-sha", remote_head_reader=lambda: None)
    assert result["update_available"] is None
    assert result["error"] == "could not reach upstream repository"
