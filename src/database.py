"""Read-only SQLite execution isolated to a single active dataset."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from src.validation import FUNCTIONS, validate_sql


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def readonly_connection(path: Path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only = ON')
        db.execute('PRAGMA trusted_schema = OFF')
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        yield db
    finally:
        db.close()


def get_schema(path: Path) -> dict[str, list[dict]]:
    with readonly_connection(path) as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: [{'name': r[1], 'type': r[2]} for r in db.execute(f'PRAGMA table_info({quote(name)})')] for name in names}


def run_query(path: Path, sql: str, *, max_rows: int = 100, timeout: float = 3.0) -> dict:
    if not 1 <= max_rows <= 1000 or not 0 < timeout <= 30:
        raise ValueError('Invalid query limits.')
    tables = set(get_schema(path))
    checked = validate_sql(sql, tables)
    started = time.monotonic()
    deadline = started + timeout
    with readonly_connection(path) as db:
        def authorize(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            # SQLite reports database=None for COUNT(*) without a column read.
            if action == sqlite3.SQLITE_READ and arg1 in tables and (
                database == 'main' or (database is None and arg2 == '')
            ):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or '').upper() in FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        db.set_authorizer(authorize)
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            cursor = db.execute(checked)
            columns = [item[0] for item in cursor.description]
            fetched = cursor.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as exc:
            if 'interrupted' in str(exc):
                raise ValueError('Query exceeded the time limit. Try a narrower question.') from exc
            raise ValueError(f'Query failed: {exc}') from exc
    # Positional rows preserve duplicate SQL column labels without losing values.
    rows = [list(r) for r in fetched[:max_rows]]
    return {'sql': checked, 'columns': columns, 'rows': rows,
            'truncated': len(fetched) > max_rows,
            'elapsed_ms': round((time.monotonic() - started) * 1000, 1)}
