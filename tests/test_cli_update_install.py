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


def _run_result(returncode: int = 0, stdout: str = "") -> mock.Mock:
    return mock.Mock(returncode=returncode, stdout=stdout)


def test_update_no_dry_run_pulls_then_runs_update_sh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    with mock.patch("airmonitor.cli.subprocess.run") as run:
        run.return_value = _run_result()
        exit_code = main(["update", "--no-dry-run"])
    assert exit_code == 0
    commands = [call[0][0] for call in run.call_args_list]
    assert commands[-2] == ["git", "-C", str(tmp_path), "pull", "--ff-only"]
    assert commands[-1] == ["bash", str(tmp_path / "tools" / "update.sh")]


def test_update_hands_the_pre_pull_commit_to_update_sh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Regression: the CLI pulls before update.sh runs, so update.sh used to
    see the new HEAD as its 'previous' commit and a rollback restored the
    very commit that had just failed."""

    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    monkeypatch.delenv("AIRMONITOR_PREVIOUS_COMMIT", raising=False)

    def fake_run(command, **kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return _run_result(stdout="abc123\n")
        return _run_result()

    with mock.patch("airmonitor.cli.subprocess.run", side_effect=fake_run) as run:
        assert main(["update", "--no-dry-run"]) == 0

    assert run.call_args_list[-1].kwargs["env"]["AIRMONITOR_PREVIOUS_COMMIT"] == "abc123"


def test_update_still_runs_when_head_cannot_be_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    monkeypatch.delenv("AIRMONITOR_PREVIOUS_COMMIT", raising=False)

    def fake_run(command, **kwargs):
        if command[-2:] == ["rev-parse", "HEAD"]:
            return _run_result(returncode=128)
        return _run_result()

    with mock.patch("airmonitor.cli.subprocess.run", side_effect=fake_run) as run:
        assert main(["update", "--no-dry-run"]) == 0

    assert "AIRMONITOR_PREVIOUS_COMMIT" not in run.call_args_list[-1].kwargs["env"]


def test_update_no_dry_run_stops_if_pull_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AIRMONITOR_REPO_DIR", str(tmp_path))
    with mock.patch("airmonitor.cli.subprocess.run") as run:
        run.return_value = _run_result(returncode=1)
        exit_code = main(["update", "--no-dry-run"])
    assert exit_code == 1
    # update.sh must not run after a failed pull
    assert not any(call[0][0][:1] == ["bash"] for call in run.call_args_list)


# --- general CLI arg-error behavior ---------------------------------------------

def test_unrecognized_argument_on_non_install_command_errors() -> None:
    with pytest.raises(SystemExit):
        main(["doctor", "--bogus-flag"])


# --- tools/update.sh rollback target ---------------------------------------------

def _previous_commit_snippet() -> str:
    script = (Path(__file__).parents[1] / "tools" / "update.sh").read_text(encoding="utf-8")
    start = script.index('PREVIOUS_COMMIT="$(git rev-parse HEAD)"')
    end = script.index("\nfi\n", start) + len("\nfi\n")
    return script[start:end]


def _git_repo_with_two_commits(path: Path) -> tuple[str, str]:
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    path.mkdir()
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (path / "f").write_text("1")
    git("add", "f")
    git("commit", "-q", "-m", "one")
    first = git("rev-parse", "HEAD")
    (path / "f").write_text("2")
    git("commit", "-q", "-am", "two")
    return first, git("rev-parse", "HEAD")


def _resolve_previous_commit(repo: Path, env_value: str | None) -> str:
    import subprocess

    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    if env_value is not None:
        env["AIRMONITOR_PREVIOUS_COMMIT"] = env_value
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail\ncd "{repo}"\n{_previous_commit_snippet()}\necho "$PREVIOUS_COMMIT"'],
        env=env, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def test_update_sh_defaults_previous_commit_to_head(tmp_path: Path) -> None:
    _first, second = _git_repo_with_two_commits(tmp_path / "repo")
    assert _resolve_previous_commit(tmp_path / "repo", None) == second


def test_update_sh_honors_the_pre_pull_commit_from_the_cli(tmp_path: Path) -> None:
    first, _second = _git_repo_with_two_commits(tmp_path / "repo")
    assert _resolve_previous_commit(tmp_path / "repo", first) == first


def test_update_sh_ignores_an_unknown_pre_pull_commit(tmp_path: Path) -> None:
    _first, second = _git_repo_with_two_commits(tmp_path / "repo")
    assert _resolve_previous_commit(tmp_path / "repo", "deadbeef" * 5) == second
