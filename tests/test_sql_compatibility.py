"""Native SQLite compatibility, including optional build-dependent functions."""
import json
import sqlite3
from contextlib import contextmanager

import pytest

from src.database import allowed_functions, query_capabilities, readonly_connection, run_query


SCALARS = {
    'abs': 'abs(-2)', 'acos': 'acos(0.5)', 'acosh': 'acosh(2)',
    'asin': 'asin(0.5)', 'asinh': 'asinh(2)', 'atan': 'atan(1)',
    'atan2': 'atan2(1, 2)', 'atanh': 'atanh(0.5)',
    'ceil': 'ceil(1.2)', 'ceiling': 'ceiling(1.2)', 'floor': 'floor(1.2)',
    'cos': 'cos(1)', 'cosh': 'cosh(1)', 'sin': 'sin(1)', 'sinh': 'sinh(1)',
    'tan': 'tan(1)', 'tanh': 'tanh(1)', 'degrees': 'degrees(1)',
    'radians': 'radians(90)', 'exp': 'exp(1)', 'ln': 'ln(2)',
    'log': 'log(2, 8)', 'log10': 'log10(100)', 'log2': 'log2(8)',
    'mod': 'mod(7, 3)', 'pi': 'pi()', 'pow': 'pow(2, 3)',
    'power': 'power(2, 3)', 'sqrt': 'sqrt(9)', 'trunc': 'trunc(1.2)',
    'sign': 'sign(-5)', 'round': 'round(1.234, 2)',
    'char': 'char(65, 66)', 'coalesce': 'coalesce(NULL, 2)',
    'concat': "concat('a', 'b')", 'concat_ws': "concat_ws('-', 'a', 'b')",
    'format': "format('%s:%d', 'a', 2)", 'printf': "printf('%s:%d', 'a', 2)",
    'glob': "glob('a*', 'abc')", 'like': "like('a%', 'abc')",
    'hex': "hex('ab')", 'unhex': "unhex('4142')",
    'if': "if(1, 'yes', 'no')", 'iif': "iif(1, 'yes', 'no')",
    'ifnull': 'ifnull(NULL, 2)', 'nullif': 'nullif(2, 2)',
    'instr': "instr('abc', 'b')", 'length': "length('abc')",
    'octet_length': "octet_length('abc')", 'lower': "lower('ABC')",
    'upper': "upper('abc')", 'trim': "trim(' ab ')",
    'ltrim': "ltrim(' ab ')", 'rtrim': "rtrim(' ab ')",
    'replace': "replace('abc', 'a', 'x')", 'quote': "quote('a''b')",
    'substr': "substr('abc', 1, 2)", 'substring': "substring('abc', 2, 2)",
    'typeof': 'typeof(2.5)', 'unicode': "unicode('A')", 'subtype': 'subtype(1)',
    'unistr': r"unistr('\u0041')", 'unistr_quote': "unistr_quote('abc')",
    'likely': 'likely(1)', 'unlikely': 'unlikely(0)', 'likelihood': 'likelihood(1, 0.5)',
    'date': "date('2026-01-15', '+1 month')",
    'time': "time('12:30:00', '+1 hour')", 'datetime': "datetime('2026-01-15')",
    'julianday': "julianday('2026-01-15')", 'unixepoch': "unixepoch('2026-01-15')",
    'strftime': "strftime('%Y-%m', '2026-01-15')",
    'timediff': "timediff('2026-01-16', '2026-01-15')",
    'current_date': "date(CURRENT_DATE)", 'current_time': "time(CURRENT_TIME)",
    'current_timestamp': "datetime(CURRENT_TIMESTAMP)",
    'changes': 'changes()', 'total_changes': 'total_changes()',
    'last_insert_rowid': 'last_insert_rowid()', 'sqlite_version': 'sqlite_version()',
    'sqlite_source_id': 'sqlite_source_id()',
    'sqlite_compileoption_get': 'sqlite_compileoption_get(0)',
    'sqlite_compileoption_used': "sqlite_compileoption_used('ENABLE_MATH_FUNCTIONS')",
    'random': 'random()',
    'json': "json('{\"a\":1}')", 'jsonb': "jsonb('{\"a\":1}')",
    'json_array': 'json_array(1, 2)', 'jsonb_array': 'jsonb_array(1, 2)',
    'json_array_insert': "json_array_insert('[1,2]', '$[1]', 3)",
    'jsonb_array_insert': "jsonb_array_insert('[1,2]', '$[1]', 3)",
    'json_array_length': "json_array_length('[1,2]')",
    'json_error_position': "json_error_position('{')",
    'json_extract': "json_extract('{\"a\":1}', '$.a')",
    'jsonb_extract': "jsonb_extract('{\"a\":[1,2]}', '$.a')",
    'json_insert': "json_insert('{}', '$.a', 1)",
    'jsonb_insert': "jsonb_insert('{}', '$.a', 1)",
    'json_object': "json_object('a', 1)", 'jsonb_object': "jsonb_object('a', 1)",
    'json_patch': "json_patch('{\"a\":1}', '{\"b\":2}')",
    'jsonb_patch': "jsonb_patch('{\"a\":1}', '{\"b\":2}')",
    'json_pretty': "json_pretty('{\"a\":1}')", 'json_quote': "json_quote('abc')",
    'json_remove': "json_remove('{\"a\":1}', '$.a')",
    'jsonb_remove': "jsonb_remove('{\"a\":1}', '$.a')",
    'json_replace': "json_replace('{\"a\":1}', '$.a', 2)",
    'jsonb_replace': "jsonb_replace('{\"a\":1}', '$.a', 2)",
    'json_set': "json_set('{}', '$.a', 1)", 'jsonb_set': "jsonb_set('{}', '$.a', 1)",
    'json_type': "json_type('{\"a\":1}', '$.a')", 'json_valid': "json_valid('{}')",
    '->': "'{\"a\":1}' -> '$.a'", '->>': "'{\"a\":1}' ->> '$.a'",
}
AGGREGATES = {
    'avg': 'avg(amount)', 'count': 'count(*)', 'min': 'min(amount)',
    'max': 'max(amount)', 'sum': 'sum(amount)', 'total': 'total(amount)',
    'group_concat': "group_concat(item, ',')", 'string_agg': "string_agg(item, ',')",
    'median': 'median(amount)', 'percentile': 'percentile(amount, 50)',
    'percentile_cont': 'percentile_cont(amount, 0.5)',
    'percentile_disc': 'percentile_disc(amount, 0.5)',
    'json_group_array': 'json_group_array(amount)',
    'jsonb_group_array': 'jsonb_group_array(amount)',
    'json_group_object': 'json_group_object(item, amount)',
    'jsonb_group_object': 'jsonb_group_object(item, amount)',
}
WINDOWS = {
    'row_number': 'row_number()', 'rank': 'rank()', 'dense_rank': 'dense_rank()',
    'percent_rank': 'percent_rank()', 'cume_dist': 'cume_dist()', 'ntile': 'ntile(2)',
    'lag': 'lag(amount)', 'lead': 'lead(amount)', 'first_value': 'first_value(amount)',
    'last_value': 'last_value(amount)', 'nth_value': 'nth_value(amount, 2)',
}
CASES = {name: f'SELECT {expression}' for name, expression in SCALARS.items()}
CASES.update({name: f'SELECT {expression} FROM records' for name, expression in AGGREGATES.items()})
CASES.update({name: f'SELECT {expression} OVER (ORDER BY amount) FROM records ORDER BY amount'
              for name, expression in WINDOWS.items()})


@pytest.mark.parametrize('name,sql', CASES.items(), ids=CASES.keys())
def test_native_function_compatibility(store, simple_dataset, name, sql):
    path = store.dataset_path(simple_dataset)
    capabilities = query_capabilities(path)
    if name not in capabilities['functions']:
        pytest.skip(f'{name} is unavailable in this SQLite build')
    with readonly_connection(path) as db:
        native = [list(row) for row in db.execute(sql).fetchall()]
    actual = run_query(path, sql)
    if name == 'random':
        assert isinstance(actual['rows'][0][0], int)
    elif name in {'current_time', 'current_timestamp'}:
        assert actual['rows'][0][0]  # The two executions can cross a second boundary.
    else:
        expected = [["X'" + value.hex().upper() + "'" if isinstance(value, bytes) else value
                     for value in row] for row in native]
        assert actual['rows'] == expected
    json.dumps(actual, allow_nan=False)


def test_catalog_functions_have_execution_coverage(store, simple_dataset):
    capabilities = query_capabilities(store.dataset_path(simple_dataset))
    assert not set(capabilities['functions']) - CASES.keys()
    assert capabilities['dialect'] == 'sqlite'
    assert capabilities['version'] == sqlite3.sqlite_version


@pytest.mark.parametrize('name', ['json_each', 'json_tree', 'jsonb_each', 'jsonb_tree'])
def test_json_table_functions_expand_active_dataset_values(store, simple_dataset, name):
    path = store.dataset_path(simple_dataset)
    if name not in query_capabilities(path)['json_table_functions']:
        pytest.skip(f'{name} is unavailable in this SQLite build')
    result = run_query(path, f'SELECT r.item, j.value FROM records r, {name}(json_array(r.amount)) j '
                             "WHERE r.item = 'pen' AND j.type = 'real'")
    assert result['rows'] == [['pen', 10.0]]


@pytest.mark.parametrize('sql,expected', [
    ('VALUES (1), (2)', [[1], [2]]),
    ('SELECT SUM(amount) FILTER (WHERE amount > 0) FROM records', [[30.0]]),
    ('SELECT item, SUM(amount) OVER (ORDER BY amount ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) '
     'FROM records ORDER BY amount', [['refund', -5.0], ['pen', 5.0], ['book', 25.0]]),
    ("SELECT item FROM records WHERE EXISTS (SELECT 1 FROM records b WHERE b.amount > 0 AND b.item = records.item) ORDER BY item", [['book'], ['pen']]),
    ("SELECT item FROM records WHERE item IN ('pen', 'book') INTERSECT SELECT item FROM records WHERE amount > 15", [['book']]),
    ("SELECT item FROM records EXCEPT SELECT item FROM records WHERE amount < 0 ORDER BY item", [['book'], ['pen']]),
    ('SELECT item FROM records UNION SELECT item FROM records ORDER BY item', [['book'], ['pen'], ['refund']]),
    ('SELECT a.item, b.amount FROM records a LEFT JOIN records b ON a.item=b.item ORDER BY a.item', [['book', 20.0], ['pen', 10.0], ['refund', -5.0]]),
    ("SELECT item FROM records WHERE amount BETWEEN 0 AND 20 AND item NOT GLOB 'p*'", [['book']]),
])
def test_readonly_sql_features_are_usable(store, simple_dataset, sql, expected):
    assert run_query(store.dataset_path(simple_dataset), sql)['rows'] == expected


@pytest.mark.parametrize('sql', [
    "SELECT * FROM pragma_database_list()", 'SELECT * FROM dbstat',
    "SELECT * FROM json_each(readfile('/tmp/no'))", "SELECT json_array(load_extension('/tmp/no'))",
    "SELECT IIF(0, load_extension('/tmp/no'), 1)", "SELECT randomblob(1000000000)",
    "SELECT writefile('/tmp/no', 'bad')", "SELECT fts5_source_id()",
])
def test_broader_support_preserves_external_access_boundary(store, simple_dataset, sql):
    with pytest.raises(ValueError):
        run_query(store.dataset_path(simple_dataset), sql)


def test_user_defined_overload_cannot_inherit_builtin_permission(store, simple_dataset, monkeypatch):
    invoked = []
    @contextmanager
    def shadowed_connection(path):
        with readonly_connection(path) as db:
            db.create_function('abs', 1, lambda value: invoked.append(value) or value)
            assert 'abs' not in allowed_functions(db)
            yield db
    monkeypatch.setattr('src.database.readonly_connection', shadowed_connection)
    with pytest.raises(ValueError, match='not authorized'):
        run_query(store.dataset_path(simple_dataset), 'SELECT ABS(-1)')
    assert invoked == []


async def test_binary_results_can_be_saved_and_exported(store, simple_dataset, tmp_path):
    from src.export import export_chat_results
    from src.workflow import ask
    chat = store.new_chat(simple_dataset)
    response = await ask(store, chat, "/sql SELECT CAST('AB' AS BLOB)")
    assert response['status'] == 'answer'
    assert response['queries'][0]['rows'] == [["X'4142'"]]
    assert 'hexadecimal' in response['answer']
    folder = export_chat_results(tmp_path, chat, store.messages(chat), {simple_dataset: 'test.csv'})
    assert "X'4142'" in (folder / 'answer-001-query-01.csv').read_text()
