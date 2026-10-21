"""Local CSV descriptions based on its schema and checked aggregate queries."""
import json

from src.database import quote


TYPE_LABELS = {'INTEGER': 'whole numbers', 'REAL': 'decimal numbers', 'TEXT': 'text'}


def csv_profile(question, tools):
    columns = tools.get_schema()['records']
    tools.context.append({'source': 'CSV column types', 'text': json.dumps(columns, ensure_ascii=False)})
    if question == 'show columns':
        lines = [f'{column["name"]} — {TYPE_LABELS.get(column["type"], column["type"])}' for column in columns]
        answer = f'Your CSV has {len(columns)} columns:\n\n' + '\n'.join(lines)
        return {'status': 'answer', 'answer': answer + '\n\nThese are detected storage types, not business definitions. Dates and leading-zero IDs stay as text.'}

    # Keep each statement below the SQL length limit, including quoted headers.
    # At the import limit (100 headers of 100 characters), at most 3 queries fit.
    groups, fields = [], []
    for column in columns:
        name = quote(column['name'])
        field = f'COUNT(*) - COUNT({name}) AS {quote("empty_cells__" + column["name"])}'
        if sum(map(len, fields)) + len(field) + 2 * len(fields) > 15500:
            groups.append(fields)
            fields = []
        fields.append(field)
    if fields:
        groups.append(fields)
    missing = []
    rows = 0
    for fields in groups:
        result = tools.run_checked_query('SELECT COUNT(*) AS row_count, ' + ', '.join(fields) + ' FROM records')
        if 'error' in result:
            return {'status': 'unable', 'answer': result['error']}
        result['display'] = 'empty_cells_by_column'
        rows = result['rows'][0][0]
        missing.extend(result['rows'][0][1:])
    if question == 'describe my data':
        name = tools.store.dataset(tools.dataset_id)['name']
        total = sum(missing)
        cells = rows * len(columns)
        row_label = 'row' if rows == 1 else 'rows'
        column_label = 'column' if len(columns) == 1 else 'columns'
        answer = (f'{name} contains {rows:,} {row_label} and {len(columns)} {column_label}.\n\n'
                  f'Empty cells: {total:,} of {cells:,} ({total / cells if cells else 0:.1%}).\n'
                  f'Columns with empty cells: {sum(count > 0 for count in missing)} of {len(columns)}.\n\n'
                  'Try “show columns”, “show missing values”, or “show data”.\n'
                  'Save column meanings and units in Settings → Data definitions before asking business questions.')
    else:
        pairs = sorted(zip(columns, missing), key=lambda pair: -pair[1])
        answer = f'Empty cells by column ({rows:,} rows):\n\n' + '\n'.join(
            f'{column["name"]}: {count:,} ({count / rows if rows else 0:.1%})' for column, count in pairs[:25]
        )
        if len(columns) > 25:
            answer += '\n\nShowing the 25 columns with the most empty cells. Full counts are in View results → Results.'
    answer += '\n\nBlank or whitespace-only cells count as empty. Literal text such as “N/A” does not.'
    return {'status': 'answer', 'answer': answer}
