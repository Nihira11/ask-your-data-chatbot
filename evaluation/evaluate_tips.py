"""Independent Decimal references for tips.csv; no API calls or real chat changes."""
import asyncio
import csv
import json
import tempfile
from decimal import Decimal
from pathlib import Path

from evaluation.evaluate import equivalent
from src.export import export_chat_results
from src.importer import import_csv, inspect_csv
from src.storage import ROOT, Store
from src.workflow import ask


def references(rows):
    def total(field, selected=rows):
        return sum((Decimal(r[field]) for r in selected), Decimal(0))
    def grouped(field, measure, average=False):
        result = []
        for group in sorted({r[field] for r in rows}, key=int if field == 'size' else str):
            selected = [r for r in rows if r[field] == group]
            value = total(measure, selected) / (len(selected) if average else 1)
            result.append([int(group) if field == 'size' else group, float(value)])
        return result
    yield 'row_count', 'How many rows are there?', 'SELECT COUNT(*) FROM records', [[len(rows)]]
    yield 'total_bill', 'What is the sum of total_bill?', 'SELECT SUM(total_bill) FROM records', [[float(total('total_bill'))]]
    yield 'total_tip', 'What is the sum of tip?', 'SELECT SUM(tip) FROM records', [[float(total('tip'))]]
    yield 'average_tip', 'What is the average tip?', 'SELECT AVG(tip) FROM records', [[float(total('tip') / len(rows))]]
    yield 'time_average', 'Compare average tip for Lunch and Dinner.', 'SELECT time, AVG(tip) FROM records GROUP BY time ORDER BY time', grouped('time', 'tip', True)
    yield 'day_totals', 'Show sum of tip by day.', 'SELECT day, SUM(tip) FROM records GROUP BY day ORDER BY day', grouped('day', 'tip')
    yield 'day_average_bill', 'Show average total_bill by day.', 'SELECT day, AVG(total_bill) FROM records GROUP BY day ORDER BY day', grouped('day', 'total_bill', True)
    yield 'size_average_tip', 'Show average tip by size.', 'SELECT size, AVG(tip) FROM records GROUP BY size ORDER BY size', grouped('size', 'tip', True)
    yield 'weighted_tip_percentage', 'Calculate 100 * SUM(tip) / SUM(total_bill).', 'SELECT 100.0 * SUM(tip) / SUM(total_bill) FROM records', [[float(100 * total('tip') / total('total_bill'))]]
    yield 'over_40', 'How many rows have total_bill greater than 40?', 'SELECT COUNT(*) FROM records WHERE total_bill > 40', [[sum(Decimal(r['total_bill']) > 40 for r in rows)]]
    highest = sorted(rows, key=lambda r: Decimal(r['total_bill']), reverse=True)[:5]
    yield 'top_five_bills', 'Show the five largest total_bill values.', 'SELECT total_bill FROM records ORDER BY total_bill DESC LIMIT 5', [[float(r['total_bill'])] for r in highest]
    for name, sql_filter, select in [
        ('dinner', "time = 'Dinner'", lambda r: r['time'] == 'Dinner'),
        ('dinner_sunday', "time = 'Dinner' AND day = 'Sun'", lambda r: r['time'] == 'Dinner' and r['day'] == 'Sun'),
        ('dinner_sunday_nonsmoker', "time = 'Dinner' AND day = 'Sun' AND smoker = 'No'", lambda r: r['time'] == 'Dinner' and r['day'] == 'Sun' and r['smoker'] == 'No'),
    ]:
        selected = [r for r in rows if select(r)]
        yield name, 'Follow-up filter: ' + sql_filter, 'SELECT SUM(tip), COUNT(*) FROM records WHERE ' + sql_filter, [[float(total('tip', selected)), len(selected)]]
    yield 'no_monday_rows', 'Show rows where day is Mon.', "SELECT * FROM records WHERE day = 'Mon'", []


async def evaluate():
    path = ROOT / 'data/sample/tips.csv'
    with path.open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    checks = []
    with tempfile.TemporaryDirectory(prefix='tips-eval-') as directory:
        store = Store(Path(directory))
        inspected = inspect_csv(path)
        dataset = import_csv(store, inspected)
        chat = store.new_chat(dataset)
        for name, question, sql, expected in references(rows):
            answer = await ask(store, chat, '/sql ' + sql)
            actual = answer['queries'][-1]['rows'] if answer['queries'] else None
            checks.append({'id': name, 'question': question, 'expected': expected,
                           'passed': answer['status'] == 'answer' and equivalent(actual, expected)})
        overview = await ask(store, chat, 'describe my data')
        checks.append({'id': 'overview_and_missing_values', 'passed': '244 rows and 7 columns' in overview['answer']
                       and all(v == 0 for v in inspected['null_counts'].values())})
        preview = await ask(store, chat, '/sql SELECT * FROM records')
        checks.append({'id': 'row_limit', 'passed': len(preview['queries'][0]['rows']) == 100 and preview['queries'][0]['truncated']})
        denied = await ask(store, chat, '/sql DELETE FROM records')
        checks.append({'id': 'write_refused', 'passed': denied['status'] == 'unable' and not denied['queries']})
        history = Store(store.home).messages(chat)
        exported = export_chat_results(store.home, chat, history, {dataset: path.name})
        manifest = json.loads((exported / 'details.json').read_text())
        expected_answers = [m for m in history if m['role'] == 'assistant' and m['payload'].get('queries')]
        all_files_match = len(manifest['answers']) == len(expected_answers)
        for entry, answer in zip(manifest['answers'], expected_answers):
            for saved, query in zip(entry['results'], answer['payload']['queries']):
                with (exported / saved['file']).open(encoding='utf-8-sig', newline='') as file:
                    data = list(csv.reader(file))
                all_files_match &= data == [query['columns']] + [[str(v) if v is not None else '' for v in row] for row in query['rows']]
        checks.append({'id': 'saved_chat_and_all_exports', 'passed': bool(all_files_match)})
    report = {'mode': 'Independent CSV/Decimal versus local checked SQL; not live AI accuracy',
              'total': len(checks), 'passed': sum(c['passed'] for c in checks), 'checks': checks}
    output = ROOT / 'evaluation/results'
    output.mkdir(exist_ok=True)
    (output / 'tips.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return all(c['passed'] for c in checks)


if __name__ == '__main__':
    raise SystemExit(0 if asyncio.run(evaluate()) else 1)
