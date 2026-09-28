"""Dataset-scoped definitions. Small-schema baseline: provide all reviewed context.

No embeddings or vector retrieval yet; there are only two short source documents.
"""
from src.storage import ROOT, Store


def search_context(store: Store, dataset_id: str, question: str) -> list[dict[str, str]]:
    dataset = store.dataset(dataset_id)
    if dataset['kind'] == 'sample':
        return [{'source': name, 'dataset_id': dataset_id,
                 'text': (ROOT / 'data' / 'knowledge' / name).read_text()}
                for name in ('data_dictionary.md', 'business_rules.md')]
    metadata = dataset['metadata']
    notes = metadata['definitions']
    if metadata.get('confirmed_definitions'):
        notes = notes.replace('Column meanings and units have not been confirmed.',
                              'See user-confirmed definitions; ask about meanings not covered there.')
    sources = [{'source': 'CSV import notes', 'dataset_id': dataset_id, 'text': notes}]
    if metadata.get('confirmed_definitions'):
        sources.append({'source': 'Your saved definitions', 'dataset_id': dataset_id,
                        'revision': str(metadata.get('definitions_revision', 0)),
                        'text': metadata['confirmed_definitions']})
    return sources
