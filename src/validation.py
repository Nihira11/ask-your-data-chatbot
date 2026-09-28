"""Fail-closed placeholder: no query is approved until validation is implemented."""


class QueryValidationError(ValueError):
    """The query is not approved for execution."""


def validate_sql(sql: str) -> str:
    """Eventually parse PostgreSQL SQL and enforce the application's query policy.

    Check the full syntax tree, permitted tables and functions, and statement count.
    Do not rely on a SELECT prefix or keyword blacklist. Validation complements,
    but does not replace, restricted DB permissions and server-side timeouts.
    """
    raise QueryValidationError("SQL validation is not implemented; execution is disabled.")
