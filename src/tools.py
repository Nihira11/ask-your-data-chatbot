"""Tools bind to trusted application state, never to a model-supplied file path."""
from src.database import get_schema, run_query
from src.retrieval import search_context
from src.storage import Store


class DatasetTools:
    def __init__(self, store: Store, dataset_id: str):
        self.store = store
        self.dataset_id = dataset_id
        store.dataset(dataset_id)
        self.path = store.dataset_path(dataset_id)
        # Snapshot definitions for this turn; evidence matches what the model saw.
        self.context = search_context(store, dataset_id, '')
        self.attempts = 0
        self.results = []
        self.errors = []

    def get_schema(self) -> dict:
        return get_schema(self.path)

    def search_context(self, question: str) -> list[dict]:
        return self.context

    def run_checked_query(self, sql: str) -> dict:
        if self.attempts >= 3:
            return {'error': 'The three-query budget is exhausted. Stop and explain the limitation.'}
        self.attempts += 1
        try:
            result = run_query(self.path, sql)
        except ValueError as exc:
            self.errors.append(str(exc))
            return {'error': str(exc), 'attempt': self.attempts}
        self.results.append(result)
        return result
