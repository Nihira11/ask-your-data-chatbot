import sqlite3

import pytest

from src.database import get_schema, readonly_connection, run_query
from src.validation import QueryValidationError


def test_aggregate_and_readonly_cte(store, simple_dataset):
    path = store.dataset_path(simple_dataset)
    result = run_query(path, 'WITH totals AS (SELECT SUM(amount) AS total FROM records) SELECT * FROM totals')
    assert result['rows'] == [[25.0]]
    assert not result['truncated']
    assert get_schema(path)['records'][0] == {'name': 'item', 'type': 'TEXT'}


@pytest.mark.parametrize('sql', [
    'DELETE FROM records', 'DROP TABLE records', 'UPDATE records SET amount = 0',
    'SELECT * FROM records; DELETE FROM records',
    "ATTACH DATABASE '/tmp/other.db' AS other", 'PRAGMA table_info(records)',
    'SELECT * FROM sqlite_master', 'SELECT * FROM main.records',
    "SELECT load_extension('/tmp/test')", "SELECT readfile('/etc/passwd')",
    'SELECT * FROM pragma_table_info(\'records\')', 'SELECT randomblob(1000000000)',
    'SELECT * INTO other FROM records',
    'WITH wiped AS (DELETE FROM records RETURNING *) SELECT * FROM wiped',
    'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x',
    'SELECT * FROM other_chat', 'SELECT', '', "SELECT 'unterminated",
])
def test_reject_unsafe_queries(store, simple_dataset, sql):
    with pytest.raises(ValueError):
        run_query(store.dataset_path(simple_dataset), sql)


def test_cte_cannot_disguise_forbidden_table(store, simple_dataset):
    with pytest.raises(ValueError):
        run_query(store.dataset_path(simple_dataset), 'WITH sqlite_master AS (SELECT * FROM sqlite_master) SELECT * FROM sqlite_master')


def test_database_still_readonly_without_validator(store, simple_dataset):
    with readonly_connection(store.dataset_path(simple_dataset)) as db:
        with pytest.raises(sqlite3.DatabaseError):
            db.execute('DELETE FROM records')


def test_limit_does_not_change_aggregation(store, simple_dataset):
    path = store.dataset_path(simple_dataset)
    assert run_query(path, 'SELECT * FROM records', max_rows=2)['truncated']
    assert run_query(path, 'SELECT SUM(amount) FROM records', max_rows=1)['rows'] == [[25.0]]
    assert run_query(path, 'SELECT * FROM records WHERE amount > 999')['rows'] == []


def test_timeout_interrupts_expensive_query(store, simple_dataset):
    with pytest.raises(ValueError, match='time limit'):
        run_query(store.dataset_path(simple_dataset),
                  'SELECT COUNT(*) FROM records a, records b, records c, records d, records e, records f, records g, records h, records i, records j, records k, records l, records m, records n, records o', timeout=0.001)


def test_duplicate_column_names_keep_values(store, simple_dataset):
    result = run_query(store.dataset_path(simple_dataset), 'SELECT item AS x, amount AS x FROM records LIMIT 1')
    assert result['columns'] == ['x', 'x']
    assert result['rows'] == [['pen', 10.0]]
