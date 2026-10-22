"""Read-only SQLite execution isolated to a single active dataset."""
from __future__ import annotations

import math
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from src.validation import JSON_TABLE_FUNCTIONS, validate_sql


# SQLite documents SQLITE_INNOCUOUS as having no external side effects. Require
# builtin=1 as well: extensions/UDFs must not opt themselves into our policy.
SQLITE_INNOCUOUS = 0x200000
BLOCKED_FUNCTIONS = frozenset({'load_extension', 'sqlite_log', 'randomblob', 'zeroblob'})
# Some builds expose these built-in aggregates without SQLITE_INNOCUOUS.
REVIEWED_AGGREGATES = frozenset({'median', 'percentile', 'percentile_cont', 'percentile_disc'})


def allowed_functions(db: sqlite3.Connection) -> frozenset[str]:
    catalog = db.execute('PRAGMA function_list').fetchall()
    # An application-defined overload must not inherit a builtin's permission.
    shadowed = {row[0].lower() for row in catalog if not row[1]}
    return frozenset(row[0].lower() for row in catalog
                     if row[1] and (row[5] & SQLITE_INNOCUOUS or row[0].lower() in REVIEWED_AGGREGATES)
                     and row[0].lower() not in BLOCKED_FUNCTIONS | shadowed)


def prepare_json_tables(db: sqlite3.Connection) -> frozenset[str]:
    available = set()
    for name in sorted(JSON_TABLE_FUNCTIONS):
        try:
            # Initialize known JSON virtual tables before the untrusted query's
            # authorizer is installed. SQLite may otherwise request internal
            # schema writes while connecting its read-only eponymous module.
            db.execute(f"SELECT * FROM {name}('[]') LIMIT 0").fetchall()
        except sqlite3.OperationalError:
            continue  # Older SQLite builds may not include JSON/JSONB support.
        available.add(name)
    return frozenset(available)


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


def query_capabilities(path: Path) -> dict:
    with readonly_connection(path) as db:
        return {'dialect': 'sqlite', 'version': sqlite3.sqlite_version,
                'functions': sorted(allowed_functions(db)),
                'json_table_functions': sorted(prepare_json_tables(db))}


def run_query(path: Path, sql: str, *, max_rows: int = 100, timeout: float = 3.0) -> dict:
    if not 1 <= max_rows <= 1000 or not 0 < timeout <= 30:
        raise ValueError('Invalid query limits.')
    tables = set(get_schema(path))
    checked = validate_sql(sql, tables)
    started = time.monotonic()
    deadline = started + timeout
    with readonly_connection(path) as db:
        functions = allowed_functions(db)
        json_tables = prepare_json_tables(db)
        def authorize(action, arg1, arg2, database, trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            # SQLite reports database=None for COUNT(*) without a column read.
            if action == sqlite3.SQLITE_READ and arg1 in tables | json_tables and (
                database == 'main' or (database is None and arg2 == '')
            ):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in functions:
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
    rows = []
    nonfinite = False
    binary = False
    for row in fetched[:max_rows]:
        values = []
        for value in row:
            if isinstance(value, float) and not math.isfinite(value):
                nonfinite = True
                value = 'NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity'
            elif isinstance(value, bytes):
                binary = True
                value = "X'" + value.hex().upper() + "'"
            values.append(value)
        rows.append(values)
    result = {'sql': checked, 'columns': columns, 'rows': rows,
              'truncated': len(fetched) > max_rows,
              'elapsed_ms': round((time.monotonic() - started) * 1000, 1)}
    if nonfinite:
        result['warnings'] = ['Non-finite numeric results are shown as Infinity, -Infinity or NaN; these are not finite numbers.']
    if binary:
        result.setdefault('warnings', []).append("BLOB results are shown as hexadecimal SQL literals (X'...').")
    return result
