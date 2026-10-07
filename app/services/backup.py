"""Consistent SQLite snapshots, including committed data in the WAL journal."""

import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import Engine


def backup_database(engine: Engine, destination: Path) -> None:
    source = engine.raw_connection()
    try:
        with closing(sqlite3.connect(destination)) as target:
            source.driver_connection.backup(target, pages=256)
    finally:
        source.close()
