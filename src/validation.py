"""Fail-closed SQL policy, backed by SQLite's read-only mode and authorizer."""
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


class QueryValidationError(ValueError):
    """The query is not approved for execution."""


# These functions only expand supplied JSON values into rows. Arbitrary table
# functions (including pragma_*, dbstat and extension modules) remain forbidden.
JSON_TABLE_FUNCTIONS = frozenset({'json_each', 'json_tree', 'jsonb_each', 'jsonb_tree'})


def validate_sql(sql: str, allowed_tables: set[str]) -> str:
    if not sql.strip() or len(sql) > 16000:
        raise QueryValidationError('Enter a SELECT query of at most 16,000 characters.')
    try:
        statements = sqlglot.parse(sql, read='sqlite')
    except (SqlglotError, RecursionError) as exc:
        raise QueryValidationError('The SQL could not be parsed.') from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Values)):
        raise QueryValidationError('Only one read-only SELECT or VALUES statement is allowed.')
    tree = statements[0]
    forbidden = (exp.DDL, exp.DML, exp.Command, exp.Into, exp.Lock, exp.Pragma)
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise QueryValidationError('Writes, commands, and SELECT INTO are not allowed.')
    if any(node.args.get('recursive') for node in tree.find_all(exp.With)):
        raise QueryValidationError('Recursive queries are not supported.')
    ctes = {node.alias_or_name.lower() for node in tree.find_all(exp.CTE)}
    permitted = {name.lower() for name in allowed_tables}
    for table in tree.find_all(exp.Table):
        if (isinstance(table.this, exp.Anonymous) and table.this.name.lower() in JSON_TABLE_FUNCTIONS
                and not table.db and not table.catalog):
            continue
        if not isinstance(table.this, exp.Identifier) or table.db or table.catalog:
            raise QueryValidationError('External databases and table functions are not allowed.')
        if table.name.lower() not in permitted | ctes:
            raise QueryValidationError(f'Table {table.name!r} is not in the active dataset.')
    # Validate structure here, then let SQLite authorize actual native function
    # names during preparation. Never rewrite SQL through SQLGlot: its normalized
    # names are not SQLite names, and can change across parser versions.
    return sql.strip().rstrip(';')
