"""State carried between the planned LangGraph steps."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    schema: str
    context: list[dict[str, str]]
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    result_truncated: bool
    clarification: str
    error: str
    retry_count: int
    answer: str
