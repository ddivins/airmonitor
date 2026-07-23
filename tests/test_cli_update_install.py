from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from airmonitor.cli import _read_repo_dir, main, resolve_repo_dir


# --- _read_repo_dir / resolve_repo_dir -----------------------------------------

def test_read_repo_dir_missing_file_returns_none(tmp_path: Path) -> None:
    assert _read_repo_dir(tmp_path / "does-not-exist.conf") is None


def test_read_repo_dir_parses_value(tmp_path: Path) -> None:
    conf = tmp_path / "install.conf"
    conf.write_text("MODE=full\nREPO_DIR=/home/dsd/airmonitor\nDOMAIN=example.com\n", encoding="utf-8")
    assert _read_repo_dir(conf) == "/home/dsd/airmonitor"


def test_read_repo_dir_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    conf = tmp_path / "install.conf"
    conf.write_text("# a comment\n\nREPO_DIR=/opt/repo\n", encoding="utf-8")
    assert _read_repo_dir(conf) == "/opt/repo"


def test_read_repo_dir_blank_value_returns_none(tmp_path: Path) -> None:
    conf = tmp_path / "install.conf"
    conf.write_text("REPO_DIR=\n", encoding="utf-8")
    assert _read_repo_dir(conf) is None


def test_resolve_repo_dir_prefers_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    assert resolve_repo_dir() == str(tmp_path)


def test_resolve_repo_dir_falls_back_to_install_conf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIRMONITOR_REPO_DIR", raising=False)
    repo = tmp_path / "airmonitor"
    repo.mkdir()
    conf = tmp_path / "install.conf"
    conf.write_text(f"REPO_DIR={repo}\n", encoding="utf-8")
    with mock.patch("airmonitor.cli.DEFAULT_INSTALL_CONF", str(conf)):
        assert resolve_repo_dir() == str(repo)


def test_resolve_repo_dir_raises_when_unresolvable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AIRMONITOR_REPO_DIR", raising=False)
    with mock.patch("airmonitor.cli.DEFAULT_INSTALL_CONF", str(tmp_path / "no-such-file.conf")):
        with pytest.raises(SystemExit):
            resolve_repo_dir()


def test_resolve_repo_dir_raises_when_path_does_not_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", "/no/such/directory")
    with pytest.raises(SystemExit):
        resolve_repo_dir()


# --- install/update CLI behavior -----------------------------------------------

def test_install_dry_run_shows_passthrough_args(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    with mock.patch("airmonitor.cli.subprocess.run") as run:
        exit_code = main(["install", "--full", "--non-interactive"])
        run.assert_not_called()
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "dry run" in output
    assert "--full --non-interactive" in output


def test_install_no_dry_run_executes_install_sh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    with mock.patch("airmonitor.cli.subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0)
        exit_code = main(["install", "--no-dry-run", "--full"])
    assert exit_code == 0
    command = run.call_args[0][0]
    assert command[:2] == ["bash", str(tmp_path / "tools" / "install.sh")]
    assert "--full" in command


def test_update_dry_run_does_not_touch_git_or_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    with mock.patch("airmonitor.cli.subprocess.run") as run:
        exit_code = main(["update"])
        run.assert_not_called()
    assert exit_code == 0
    assert "dry run" in capsys.readouterr().out


def test_update_no_dry_run_pulls_then_runs_update_sh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    with mock.patch("airmonitor.cli.subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0)
        exit_code = main(["update", "--no-dry-run"])
    assert exit_code == 0
    assert run.call_count == 2
    pull_call, update_call = run.call_args_list
    assert pull_call[0][0] == ["git", "-C", str(tmp_path), "pull", "--ff-only"]
    assert update_call[0][0] == ["bash", str(tmp_path / "tools" / "update.sh")]


def test_update_no_dry_run_stops_if_pull_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    with mock.patch("airmonitor.cli.subprocess.run") as run:
        run.return_value = mock.Mock(returncode=1)
        exit_code = main(["update", "--no-dry-run"])
    assert exit_code == 1
    run.assert_called_once()  # update.sh must not run after a failed pull


# --- general CLI arg-error behavior ---------------------------------------------

def test_unrecognized_argument_on_non_install_command_errors() -> None:
    with pytest.raises(SystemExit):
        main(["doctor", "--bogus-flag"])
