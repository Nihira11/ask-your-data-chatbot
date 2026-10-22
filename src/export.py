"""Export every saved query result in a chat, without SQL or model calls."""
import csv
import json
import shutil
import tempfile
from pathlib import Path


CSV_NOTES = 'NULL values are blank. Formula-like text is prefixed with an apostrophe. Numeric values are unchanged.'


def spreadsheet_cell(value):
    # Spreadsheet programs otherwise interpret untrusted text as formulas.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def write_csv(path, columns, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([spreadsheet_cell(column) for column in columns])
        writer.writerows([spreadsheet_cell(value) for value in row] for row in rows)


def export_chat_results(destination: Path, chat_id: str, history: list[dict], datasets: dict[str, str]) -> Path:
    """Create a new folder; each answer/query keeps its own original table shape."""
    answers = []
    question = ''
    for message in history:
        if message['role'] == 'user':
            question = message['payload'].get('answer', '')
        elif message['role'] == 'system' and message['payload'].get('context_reset', True):
            question = ''
        elif message['role'] == 'assistant' and message['payload'].get('queries'):
            answers.append((question, message))
    if not answers:
        raise ValueError('This chat has no query results to save.')
    # The selected parent must already exist; never overwrite an existing export.
    folder = Path(tempfile.mkdtemp(prefix='chat-results-', dir=destination))
    try:
        notes = {'chat_id': chat_id, 'answers': [], 'csv_notes': CSV_NOTES,
                 'scope': 'Saved query results only, including follow-ups and older datasets. Truncated results contain only the stored rows.'}
        index_rows = []
        for answer_number, (question, message) in enumerate(answers, 1):
            dataset_name = datasets[message['dataset_id']]
            answer = {'question': question, 'answer': message['payload'].get('answer', ''),
                      'answer_id': message['id'], 'dataset_id': message['dataset_id'],
                      'dataset': dataset_name, 'results': []}
            for query_number, query in enumerate(message['payload']['queries'], 1):
                name = f'answer-{answer_number:03d}-query-{query_number:02d}.csv'
                write_csv(folder / name, query['columns'], query['rows'])
                answer['results'].append({'file': name, 'rows': len(query['rows']),
                                          'truncated': query['truncated'], 'sql': query['sql'],
                                          'warnings': query.get('warnings', [])})
                index_rows.append([name, question, answer['answer'], dataset_name, message['id'],
                                   query_number, len(query['rows']), query['truncated']])
            notes['answers'].append(answer)
        write_csv(folder / 'index.csv', ['file', 'question', 'answer', 'dataset', 'answer_id',
                                         'query_number', 'saved_rows', 'truncated'], index_rows)
        (folder / 'details.json').write_text(json.dumps(notes, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    except BaseException:
        shutil.rmtree(folder)
        raise
    return folder
