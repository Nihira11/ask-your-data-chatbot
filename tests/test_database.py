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


@pytest.mark.parametrize('sql,expected', [
    ("SELECT SUM(amount) FROM records WHERE amount >= 0 AND amount <= 10", [[10.0]]),
    ("SELECT SUM(amount) FROM records WHERE amount < 0 OR amount > 10", [[15.0]]),
    ("SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) FROM records", [[30.0]]),
])
def test_compound_filters_and_case_are_sql_syntax(store, simple_dataset, sql, expected):
    assert run_query(store.dataset_path(simple_dataset), sql)['rows'] == expected


@pytest.mark.parametrize('sql', [
    "SELECT * FROM records WHERE amount > 0 AND load_extension('/tmp/no') IS NULL",
    "SELECT * FROM records WHERE amount > 0 OR readfile('/tmp/no') IS NULL",
    "SELECT CASE WHEN amount > 0 THEN readfile('/tmp/no') ELSE '' END FROM records",
])
def test_operators_do_not_hide_unsafe_functions(store, simple_dataset, sql):
    with pytest.raises(ValueError):
        run_query(store.dataset_path(simple_dataset), sql)


@pytest.mark.parametrize('sql,expected', [
    ("SELECT COUNT(*) FROM records WHERE item LIKE 'p%'", [[1]]),
    ("SELECT COUNT(*) FROM records WHERE item GLOB 'b*'", [[1]]),
    ("SELECT COUNT(*) FROM records WHERE item NOT LIKE 'p%'", [[2]]),
    ("SELECT COUNT(*) FROM records WHERE item LIKE 'p!_%' ESCAPE '!'", [[0]]),
    ("SELECT SUM(IIF(amount > 0, amount, 0)) FROM records", [[30.0]]),
    ("SELECT strftime('%Y-%m', '2026-01-15')", [['2026-01']]),
    ("WITH dates AS (SELECT '2026-01-15' AS date, amount FROM records) "
     "SELECT strftime('%Y-%m', date) AS month, SUM(amount) FROM dates GROUP BY month", [['2026-01', 25.0]]),
    ("SELECT INSTR(item, 'e') FROM records WHERE item = 'pen'", [[2]]),
    ("SELECT REPLACE(item, 'p', 'h') FROM records WHERE item = 'pen'", [['hen']]),
    ("SELECT GROUP_CONCAT(item, ',') FROM (SELECT item FROM records ORDER BY item)", [['book,pen,refund']]),
    ("SELECT NTILE(2) OVER (ORDER BY amount) FROM records ORDER BY amount", [[1], [1], [2]]),
    ("SELECT PERCENT_RANK() OVER (ORDER BY amount) FROM records ORDER BY amount", [[0.0], [0.5], [1.0]]),
    ('SELECT ABS(-5)', [[5]]), ('SELECT AVG(amount) FROM records', [[25 / 3]]),
    ("SELECT CAST('12' AS INTEGER)", [[12]]), ('SELECT COALESCE(NULL, 5)', [[5]]),
    ('SELECT IFNULL(NULL, 5)', [[5]]), ("SELECT DATE('2026-01-15')", [['2026-01-15']]),
    ("SELECT DATETIME('2026-01-15')", [['2026-01-15 00:00:00']]),
    ("SELECT JULIANDAY('2000-01-01')", [[2451544.5]]),
    ("SELECT LENGTH('abc')", [[3]]), ("SELECT LOWER('ABC')", [['abc']]),
    ('SELECT MAX(amount), MIN(amount) FROM records', [[20.0, -5.0]]),
    ('SELECT NULLIF(1, 1)', [[None]]), ('SELECT ROUND(1.234, 2)', [[1.23]]),
    ("SELECT SUBSTR('abc', 1, 2), SUBSTRING('abc', 2, 2)", [['ab', 'bc']]),
    ("SELECT TIME('2026-01-15 12:34:56')", [['12:34:56']]),
    ("SELECT TRIM(' abc '), UPPER('abc')", [['abc', 'ABC']]),
    ('SELECT ROW_NUMBER() OVER (ORDER BY amount) FROM records ORDER BY amount', [[1], [2], [3]]),
    ('SELECT RANK() OVER (ORDER BY amount), DENSE_RANK() OVER (ORDER BY amount) FROM records ORDER BY amount', [[1, 1], [2, 2], [3, 3]]),
    ('SELECT LAG(amount) OVER (ORDER BY amount), LEAD(amount) OVER (ORDER BY amount) FROM records ORDER BY amount', [[None, 10.0], [-5.0, 20.0], [10.0, None]]),
    ('SELECT TOTAL(amount) FROM records', [[25.0]]),
])
def test_allowed_analytics_execute_through_parser_and_authorizer(store, simple_dataset, sql, expected):
    assert run_query(store.dataset_path(simple_dataset), sql)['rows'] == expected


@pytest.mark.parametrize('sql', [
    "SELECT IIF(1, readfile('/tmp/no'), 0)",
    "SELECT REPLACE(item, 'p', load_extension('/tmp/no')) FROM records",
    "SELECT * FROM records WHERE item LIKE readfile('/tmp/no')",
    "SELECT strftime('%Y', readfile('/tmp/no'))",
    "SELECT GROUP_CONCAT(readfile('/tmp/no')) FROM records",
    "SELECT NTILE(readfile('/tmp/no')) OVER (ORDER BY amount) FROM records",
    "SELECT EXTRACT(YEAR FROM '2026-01-15')",
])
def test_new_analytics_do_not_allow_unsafe_nested_functions(store, simple_dataset, sql):
    with pytest.raises(ValueError):
        run_query(store.dataset_path(simple_dataset), sql)


@pytest.mark.parametrize('sql', ["SELECT load_extension('/tmp/no')", 'SELECT sqlite_log(1, \'blocked\')', 'SELECT randomblob(1)', 'SELECT zeroblob(1)'])
def test_authorizer_independently_rejects_unapproved_function(store, simple_dataset, monkeypatch, sql):
    monkeypatch.setattr('src.database.validate_sql', lambda sql, tables: sql)
    with pytest.raises(ValueError, match='not authorized'):
        run_query(store.dataset_path(simple_dataset), sql)


def test_nonfinite_results_are_labelled_and_json_safe(store, simple_dataset):
    import json
    result = run_query(store.dataset_path(simple_dataset), 'SELECT 1e308 * 10, -1e308 * 10, NULL, 2.5')
    assert result['rows'] == [['Infinity', '-Infinity', None, 2.5]]
    assert 'Non-finite' in result['warnings'][0]
    json.dumps(result, allow_nan=False)
