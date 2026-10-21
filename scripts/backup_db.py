"""Create a consistent SQLite backup using the online backup API."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the DigiScope SQLite database")
    parser.add_argument("destination", nargs="?", help="backup file or directory")
    args = parser.parse_args()
    url = make_url(Settings().database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        raise SystemExit("backup_db supports only a file-backed SQLite DATABASE_URL")
    source = Path(url.database).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"database does not exist: {source}")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = Path(args.destination or "./data/backups")
    if destination.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        destination.mkdir(parents=True, exist_ok=True)
        destination = destination / f"digiscope-{timestamp}.db"
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)
        result = backup_db.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise SystemExit("backup integrity check failed")
    destination.chmod(0o600)
    print(destination)


if __name__ == "__main__":
    main()
