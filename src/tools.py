"""Tools bind to trusted application state, never to a model-supplied file path."""
import sqlglot
from sqlglot import exp

from src.database import get_schema, run_query, quote
from src.retrieval import search_context
from src.storage import Store
from src.validation import validate_sql


def category_key(value):
    value = value.casefold()
    for names in (
        ('mon', 'monday'), ('tue', 'tues', 'tuesday'), ('wed', 'wednesday'),
        ('thu', 'thur', 'thurs', 'thursday'), ('fri', 'friday'),
        ('sat', 'saturday'), ('sun', 'sunday'),
    ):
        if value in names:
            return names[0]
    return value


class DatasetTools:
    def __init__(self, store: Store, dataset_id: str):
        self.store = store
        self.dataset_id = dataset_id
        dataset = store.dataset(dataset_id)
        self.definition_revision = dataset['metadata'].get('definitions_revision', 0)
        self.path = store.dataset_path(dataset_id)
        # Snapshot definitions for this turn; evidence matches what the model saw.
        self.context = search_context(store, dataset_id, '')
        self.attempts = 0
        self.results = []
        self.errors = []
        self.check_categories = False
        self._category_values = None

    def get_schema(self) -> dict:
        return get_schema(self.path)

    def search_context(self, question: str) -> list[dict]:
        return self.context

    def category_values(self) -> dict:
        """Bounded actual category values, not inferred business definitions."""
        if self._category_values is not None:
            return self._category_values
        self._category_values = {}
        if self.store.dataset(self.dataset_id)['kind'] != 'csv':
            return self._category_values
        columns = [c['name'] for c in self.get_schema().get('records', []) if c['type'] == 'TEXT'][:8]
        for name in columns:
            column = quote(name)
            try:
                result = run_query(self.path, f'SELECT DISTINCT {column} FROM records '
                                   f'WHERE {column} IS NOT NULL LIMIT 21', max_rows=21, timeout=0.5)
            except ValueError:
                continue
            values = [r[0] for r in result['rows']]
            if 0 < len(values) <= 20 and all(isinstance(v, str) and len(v) <= 100 for v in values):
                self._category_values[name] = values
        return self._category_values

    def check_category_literals(self, sql: str) -> None:
        """Reject a known spelling mismatch so AI can repair it; never rewrite SQL."""
        checked = validate_sql(sql, set(self.get_schema()))
        tree = sqlglot.parse_one(checked, read='sqlite')
        # Derived columns may have different meanings; only inspect direct queries.
        if tree.find(exp.CTE) or tree.find(exp.Subquery):
            return
        categories = {name.casefold(): values for name, values in self.category_values().items()}
        for comparison in tree.find_all(exp.EQ):
            column, literal = comparison.this, comparison.expression
            if isinstance(literal, exp.Column):
                column, literal = literal, column
            if not isinstance(column, exp.Column) or not isinstance(literal, exp.Literal) or not literal.is_string:
                continue
            values = categories.get(column.name.casefold(), [])
            value = literal.this
            if value in values:
                continue
            matches = [v for v in values if category_key(v) == category_key(value)]
            if len(matches) == 1:
                raise ValueError(
                    f'Category mismatch: {column.name!r} stores {matches[0]!r}, not {value!r}. '
                    'Check that this matches the question, then retry with the stored value '
                    'and keep the other requested filters. This query has not been executed.')

    def run_checked_query(self, sql: str) -> dict:
        if self.attempts >= 3:
            return {'error': 'The three-query budget is exhausted. Stop and explain the limitation.'}
        self.attempts += 1
        try:
            if self.check_categories:
                self.check_category_literals(sql)
            result = run_query(self.path, sql)
        except ValueError as exc:
            self.errors.append(str(exc))
            return {'error': str(exc), 'attempt': self.attempts}
        self.results.append(result)
        return result
