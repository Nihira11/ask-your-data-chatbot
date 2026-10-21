"""Save an explicit confirmation of one displayed CSV column definition."""
import re


def normalized(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


def pending_definition(response, tools):
    """Only attach proposals whose exact meaning was actually shown to the user."""
    proposal = response.pop('proposed_definition', None)
    dataset = tools.store.dataset(tools.dataset_id)
    if dataset['kind'] != 'csv' or response.get('status') != 'clarify' or not isinstance(proposal, dict):
        return
    column, meaning = proposal.get('column'), proposal.get('meaning')
    if not isinstance(column, str) or not isinstance(meaning, str):
        return
    column, meaning = column.strip(), meaning.strip()
    columns = {c['name'] for c in tools.get_schema().get('records', [])}
    if column not in columns or not meaning or len(meaning) > 250 or any(c in meaning for c in '\n\r'):
        return
    displayed = ' ' + normalized(response.get('answer', '')) + ' '
    if any(' ' + normalized(value) + ' ' not in displayed for value in (column, meaning)):
        return
    metadata = dataset['metadata']
    if metadata.get('definitions_revision', 0) != tools.definition_revision:
        return
    # Do not append a second, potentially conflicting meaning to a defined column.
    existing = ' ' + normalized(metadata.get('confirmed_definitions', '')) + ' '
    if ' ' + normalized(column) + ' ' in existing:
        return
    response['pending_definition'] = {
        'column': column, 'meaning': meaning, 'dataset_id': tools.dataset_id,
        'revision': tools.definition_revision,
    }


def remember_confirmation(store, chat_id, dataset_id, question, history):
    """An unrelated question, denial, or qualified yes never becomes a definition."""
    previous = next((m for m in reversed(history) if m['role'] in {'user', 'assistant'}), None)
    if not previous or previous['role'] != 'assistant' or previous['payload'].get('status') != 'clarify':
        return None
    pending = previous['payload'].get('pending_definition')
    if not pending or pending.get('dataset_id') != dataset_id:
        return None
    text = normalized(question)
    # Accept an emphatic "yess", without accepting qualified confirmations.
    text = re.sub(r'^yes+\b', 'yes', text)
    definition = f'{pending["column"]} means {pending["meaning"].rstrip(".")}.'
    accepted = {
        'yes', 'yes please', 'yes correct', 'yes that is correct', 'yes that s correct',
        'correct', 'that s correct', 'that is correct', 'exactly', 'yes exactly',
        'yep', 'yup', 'yeah', 'yes that s right', 'that s right',
        normalized(definition), 'yes ' + normalized(definition),
        normalized(f'{pending["meaning"]} means {pending["column"]}'),
    }
    if text not in accepted:
        return None
    try:
        store.save_definitions(chat_id, definition, append=True,
                               expected_revision=pending['revision'])
    except ValueError as exc:
        return f'Definition was not saved: {exc}'
    return None
