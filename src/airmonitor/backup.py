"""SQLite backup, restore, and retention pruning for the appliance database.

Backups use SQLite's online backup API (via `sqlite3.Connection.backup`),
which is WAL-safe and produces a consistent snapshot without requiring
sensor/filter services to stop, then gzip-compresses the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import logging
from pathlib import Path
import shutil
import sqlite3

LOG = logging.getLogger("airmonitor.backup")

DEFAULT_DATABASE = "/var/lib/airmonitor/airmonitor.sqlite3"
DEFAULT_BACKUP_DIR = "/var/lib/airmonitor/backups"
DEFAULT_RETENTION = 14
BACKUP_PREFIX = "airmonitor-"
BACKUP_SUFFIX = ".sqlite3.gz"


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size_bytes: int
    removed: list[Path]


def _timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def list_backups(backup_dir: str | Path) -> list[Path]:
    """Return backup files oldest-first, based on their filename timestamp."""

    directory = Path(backup_dir)
    if not directory.is_dir():
        return []
    matches = sorted(directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))
    return matches


def prune_backups(backup_dir: str | Path, *, retention: int) -> list[Path]:
    """Delete the oldest backups beyond `retention`, returning what was removed."""

    if retention < 0:
        raise ValueError("retention must be >= 0")
    backups = list_backups(backup_dir)
    excess = len(backups) - retention
    if excess <= 0:
        return []
    to_remove = backups[:excess]
    for path in to_remove:
        path.unlink(missing_ok=True)
        LOG.info("Pruned old backup: %s", path)
    return to_remove


def create_backup(
    *,
    database: str = DEFAULT_DATABASE,
    backup_dir: str = DEFAULT_BACKUP_DIR,
    retention: int = DEFAULT_RETENTION,
    now: datetime | None = None,
) -> BackupResult:
    """Create a compressed, consistent snapshot of the live database and prune old ones."""

    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)

    destination = directory / f"{BACKUP_PREFIX}{_timestamp(now)}{BACKUP_SUFFIX}"
    tmp_uncompressed = destination.with_suffix("")

    source_conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(tmp_uncompressed)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    try:
        with open(tmp_uncompressed, "rb") as raw, gzip.open(destination, "wb") as compressed:
            shutil.copyfileobj(raw, compressed)
    finally:
        tmp_uncompressed.unlink(missing_ok=True)

    removed = prune_backups(directory, retention=retention)
    size_bytes = destination.stat().st_size
    LOG.info("Created backup: %s (%d bytes)", destination, size_bytes)
    return BackupResult(path=destination, size_bytes=size_bytes, removed=removed)


def verify_backup(path: str | Path) -> str:
    """Return the SQLite integrity_check result for a (possibly gzipped) backup file."""

    source = Path(path)
    if source.suffix == ".gz":
        tmp = source.with_suffix("")
        with gzip.open(source, "rb") as compressed, open(tmp, "wb") as raw:
            shutil.copyfileobj(compressed, raw)
        try:
            return _integrity_check(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    return _integrity_check(source)


def _integrity_check(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def restore_backup(path: str | Path, *, database: str = DEFAULT_DATABASE) -> Path:
    """Restore a backup file over the live database, keeping a safety copy of the prior file.

    Callers are responsible for stopping services that write to `database`
    before calling this; it only operates on files.
    """

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"backup not found: {source}")

    integrity = verify_backup(source)
    if integrity != "ok":
        raise ValueError(f"backup failed integrity check: {integrity}")

    destination = Path(database)
    destination.parent.mkdir(parents=True, exist_ok=True)

    pre_restore_copy: Path | None = None
    if destination.exists():
        pre_restore_copy = destination.with_name(f"{destination.name}.pre-restore.{_timestamp()}")
        shutil.copy2(destination, pre_restore_copy)
        LOG.info("Saved pre-restore copy of live database: %s", pre_restore_copy)

    if source.suffix == ".gz":
        with gzip.open(source, "rb") as compressed, open(destination, "wb") as out:
            shutil.copyfileobj(compressed, out)
    else:
        shutil.copy2(source, destination)

    for side_file in (destination.with_name(f"{destination.name}-wal"), destination.with_name(f"{destination.name}-shm")):
        side_file.unlink(missing_ok=True)

    LOG.info("Restored %s -> %s", source, destination)
    return pre_restore_copy
