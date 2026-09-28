"""Planned tool functions. Register their schemas with the model during implementation.

These functions are not yet bound to an LLM. The application must execute approved
tool requests and return their outputs to the model.
"""

from typing import Any

from src.database import get_schema
from src.retrieval import search_context
from src.validation import validate_sql

__all__ = ["get_schema", "search_context", "run_checked_query"]


def run_checked_query(sql: str) -> dict[str, Any]:
    """Validate before execution; return columns, rows, and truncation metadata.

    There is deliberately no raw execution tool that bypasses validation.
    """
    validate_sql(sql)
    raise NotImplementedError("Implement restricted execution after SQL validation.")
