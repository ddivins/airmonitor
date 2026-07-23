"""Check whether a newer commit exists on the tracked upstream branch.

Deliberately avoids touching the local Git checkout at all: `git ls-remote`
is a read-only query against the remote that needs neither write access to
`.git` (a real `git fetch` does) nor stored credentials for a public
repository. That means this can run as the unprivileged status-service user
without the checkout-owner/SSH-credential constraints that apply to
`airmonitor update` (see `cli.resolve_repo_dir`) -- it never touches the
local checkout, just compares the commit tools/update.sh last recorded as
installed against upstream's current tip.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from typing import Callable

DEFAULT_STATE_DIR = os.environ.get("AIRMONITOR_UPDATE_STATE_DIR", "/var/lib/airmonitor/update-state")
DEFAULT_REMOTE_URL = os.environ.get("AIRMONITOR_UPDATE_REMOTE_URL", "https://github.com/ddivins/airmonitor.git")
DEFAULT_BRANCH = os.environ.get("AIRMONITOR_UPDATE_BRANCH", "main")


def read_installed_commit(state_dir: str | Path = DEFAULT_STATE_DIR) -> str | None:
    try:
        value = (Path(state_dir) / "installed-commit").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def fetch_remote_head(
    remote_url: str = DEFAULT_REMOTE_URL,
    branch: str = DEFAULT_BRANCH,
    *,
    timeout: float = 5.0,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str | None:
    try:
        result = runner(
            ["git", "ls-remote", remote_url, f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    sha = line.split("\t", 1)[0].strip() if line else ""
    return sha or None


def check_for_update(
    *,
    state_dir: str | Path = DEFAULT_STATE_DIR,
    remote_url: str = DEFAULT_REMOTE_URL,
    branch: str = DEFAULT_BRANCH,
    now: datetime | None = None,
    installed_commit_reader: Callable[[], str | None] | None = None,
    remote_head_reader: Callable[[], str | None] | None = None,
) -> dict[str, object]:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    installed_commit = (installed_commit_reader or (lambda: read_installed_commit(state_dir)))()
    latest_commit = (remote_head_reader or (lambda: fetch_remote_head(remote_url, branch)))()

    update_available = None
    if installed_commit and latest_commit:
        update_available = installed_commit != latest_commit

    error = None
    if installed_commit is None:
        error = "installed commit unknown"
    elif latest_commit is None:
        error = "could not reach upstream repository"

    return {
        "checked_at": checked_at,
        "installed_commit": installed_commit,
        "latest_commit": latest_commit,
        "update_available": update_available,
        "error": error,
    }
