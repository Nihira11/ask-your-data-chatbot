"""Fail-closed SQL policy, backed by SQLite's read-only mode and authorizer."""
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


class QueryValidationError(ValueError):
    """The query is not approved for execution."""


# A deliberately small analytical function surface. SQLite repeats this check.
FUNCTIONS = {'ABS', 'AVG', 'CAST', 'COALESCE', 'COUNT', 'DATE', 'DATETIME',
             'IF', 'IFNULL', 'JULIANDAY', 'LENGTH', 'LOWER', 'MAX', 'MIN',
             'NULLIF', 'ROUND', 'STRFTIME', 'SUBSTR', 'SUBSTRING', 'SUM',
             'TIME', 'TRIM', 'UPPER', 'ROW_NUMBER', 'RANK', 'DENSE_RANK',
             'LAG', 'LEAD', 'TOTAL', 'TIMETOSTR', 'TSTORDS', 'EXTRACT'}


def validate_sql(sql: str, allowed_tables: set[str]) -> str:
    if not sql.strip() or len(sql) > 16000:
        raise QueryValidationError('Enter a SELECT query of at most 16,000 characters.')
    try:
        statements = sqlglot.parse(sql, read='sqlite')
    except (SqlglotError, RecursionError) as exc:
        raise QueryValidationError('The SQL could not be parsed.') from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise QueryValidationError('Only one read-only SELECT statement is allowed.')
    tree = statements[0]
    forbidden = (exp.DDL, exp.DML, exp.Command, exp.Into, exp.Lock, exp.Pragma)
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise QueryValidationError('Writes, commands, and SELECT INTO are not allowed.')
    if any(node.args.get('recursive') for node in tree.find_all(exp.With)):
        raise QueryValidationError('Recursive queries are not supported.')
    ctes = {node.alias_or_name.lower() for node in tree.find_all(exp.CTE)}
    permitted = {name.lower() for name in allowed_tables}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier) or table.db or table.catalog:
            raise QueryValidationError('External databases and table functions are not allowed.')
        if table.name.lower() not in permitted | ctes:
            raise QueryValidationError(f'Table {table.name!r} is not in the active dataset.')
    for func in tree.find_all(exp.Func):
        name = func.name.upper() if isinstance(func, exp.Anonymous) else func.sql_name().upper()
        if name not in FUNCTIONS:
            raise QueryValidationError(f'Function {name} is not supported.')
    return sql.strip().rstrip(';')
