"""Serializable response records persisted with their source dataset."""
from typing import TypedDict, Any


class Answer(TypedDict, total=False):
    answer: str
    status: str
    mode: str
    dataset_id: str
    queries: list[dict[str, Any]]
    sources: list[dict[str, str]]
    error: str
    usage: dict[str, int]
