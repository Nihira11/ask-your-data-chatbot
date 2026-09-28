"""Bounded, atomic local CSV imports. No user CSV is sent to a service here."""
from __future__ import annotations

import csv
import io
import math
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from src.database import quote
from src.storage import Store

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50000
MAX_COLUMNS = 100


def inspect_csv(path: Path) -> dict:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.csv':
        raise ValueError('Choose an existing .csv file.')
    with source.open('rb') as file:
        raw = file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('CSV files must be 5 MB or smaller.')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Save the CSV with UTF-8 encoding and try again.') from exc
    if '\x00' in text:
        raise ValueError('CSV contains invalid null bytes.')
    try:
        reader = csv.reader(io.StringIO(text), strict=True)
        headers = next(reader, [])
        if not headers or len(headers) > MAX_COLUMNS or any(not h.strip() or len(h) > 100 for h in headers):
            raise ValueError('CSV needs 1–100 non-empty column headers, each at most 100 characters.')
        if len({h.strip().casefold() for h in headers}) != len(headers):
            raise ValueError('Duplicate column headers are not supported.')
        if any(h.casefold().startswith('sqlite_') for h in headers):
            raise ValueError('Column names beginning sqlite_ are reserved.')
        rows = []
        for row in reader:
            if not row:
                continue
            if len(row) != len(headers):
                raise ValueError(f'Row {reader.line_num} has {len(row)} values; expected {len(headers)}.')
            if any(len(v) > 10000 for v in row):
                raise ValueError('CSV cells must be at most 10,000 characters.')
            rows.append([v if v.strip() else None for v in row])
            if len(rows) > MAX_ROWS:
                raise ValueError('CSV files must have 50,000 rows or fewer.')
    except csv.Error as exc:
        raise ValueError(f'Invalid CSV: {exc}') from exc
    if not rows:
        raise ValueError('The CSV has headers but no data rows.')
    types = []
    for values in zip(*rows):
        present = [v for v in values if v is not None]
        # Leading zeros are identifiers, never numbers. Mixed types stay as text.
        integer = present and all(re.fullmatch(r'-?(0|[1-9]\d*)', v) and -(2**63) <= int(v) < 2**63 for v in present)
        real = present and all(re.fullmatch(r'-?(0|[1-9]\d*)\.\d+', v) and math.isfinite(float(v)) for v in present)
        types.append('INTEGER' if integer else 'REAL' if real else 'TEXT')
    return {'name': source.name, 'headers': headers, 'types': types, 'rows': rows, 'raw': raw,
            'null_counts': {h: sum(row[i] is None for row in rows) for i, h in enumerate(headers)}}


def import_csv(store: Store, inspected: dict) -> str:
    dataset_id = uuid.uuid4().hex
    path = store.dataset_path(dataset_id)
    copy = path.with_suffix('.csv')
    try:
        with closing(sqlite3.connect(path)) as db, db:
            columns = ', '.join(f'{quote(h)} {t}' for h, t in zip(inspected['headers'], inspected['types']))
            db.execute(f'CREATE TABLE records ({columns})')
            db.executemany(f'INSERT INTO records VALUES ({", ".join("?" for _ in inspected["headers"])})', inspected['rows'])
        copy.write_bytes(inspected['raw'])
        store.add_dataset(dataset_id, inspected['name'], 'csv', {
            'row_count': len(inspected['rows']), 'null_counts': inspected['null_counts'],
            'definitions': 'One row is one CSV record. Blank cells are NULL. Column meanings and units have not been confirmed. Ask before assuming financial or business definitions. Dates are stored as text; inspect their format before filtering.',
        })
    except Exception:
        path.unlink(missing_ok=True)
        copy.unlink(missing_ok=True)
        raise
    return dataset_id
