"""Small live regression suites; references come from CSV/Decimal, never model SQL."""
import csv
from collections import Counter, defaultdict
from decimal import Decimal

from src.storage import ROOT


FILES = {
    'tips': ROOT / 'data/sample/tips.csv',
    'retail': ROOT / 'data/sample/online_retail_sample.csv',
    'supermarket': ROOT / 'data/sample/supermarket_sales - Sheet1.csv',
}


def read_rows(suite):
    with FILES[suite].open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


def case(suite, name, question, **checks):
    return {'id': f'{suite}_{name}', 'suite': suite, 'question': question, **checks}


def cases_for(suite):
    if suite == 'all':
        return [c for name in FILES for c in cases_for(name)]
    rows = read_rows(suite)
    if suite == 'tips':
        result = []
        filters = [
            ('dinner', 'Across the whole dataset, show total tip and row count for Dinner.',
             lambda r: r['time'] == 'Dinner'),
            ('sunday', 'Now only Sunday, keeping Dinner.',
             lambda r: r['time'] == 'Dinner' and r['day'] == 'Sun'),
            ('nonsmokers', 'Now only non-smokers, keeping both previous filters.',
             lambda r: r['time'] == 'Dinner' and r['day'] == 'Sun' and r['smoker'] == 'No'),
        ]
        for name, question, predicate in filters:
            selected = [r for r in rows if predicate(r)]
            expected = [float(sum((Decimal(r['tip']) for r in selected), Decimal(0))), len(selected)]
            result.append(case(suite, name, question, expected_rows=[expected], answer_numbers=expected))
        grouped = defaultdict(list)
        for r in rows:
            grouped[int(r['size'])].append(Decimal(r['tip']))
        winner = max(grouped, key=lambda size: sum(grouped[size]) / len(grouped[size]))
        expected = [winner, float(sum(grouped[winner]) / len(grouped[winner])), len(grouped[winner])]
        result.append(case(suite, 'clarification',
            'Across the whole dataset, which party size has the highest average tip? '
            'Include its row count. First ask me to confirm whether size means the number of people in the party.',
            behavior='clarify', pending_column='size'))
        result.append(case(suite, 'confirmation', 'Yess', expected_rows=[expected], answer_numbers=expected,
                           saved_column='size', saved_notice=True))
        result.append(case(suite, 'restart',
            'Across the whole dataset, which party size has the highest average tip? Include its row count.',
            expected_rows=[expected], answer_numbers=expected, saved_column='size', new_chat=True))
        return result
    if suite == 'retail':
        def revenue(selected):
            return float(sum((Decimal(r['quantity']) * Decimal(r['unit_price']) for r in selected
                              if Decimal(r['unit_price']) >= 0), Decimal(0)))
        total, france = revenue(rows), revenue(r for r in rows if r['country'] == 'France')
        return [
            case(suite, 'revenue', 'What is the total net revenue, including cancellations?',
                 expected_rows=[[total]], answer_numbers=[total]),
            case(suite, 'france', 'Only for France.', expected_rows=[[france]], answer_numbers=[france]),
            case(suite, 'profit', 'Across the whole dataset, what was our profit?',
                 behavior='missing_input', answer_terms=['cost']),
        ]
    totals = defaultdict(Decimal)
    lines = defaultdict(Decimal)
    for r in rows:
        totals[r['Branch']] += Decimal(r['Total'])
        if r['Branch'] == 'A':
            lines[r['Product line']] += Decimal(r['Total'])
    branch = max(totals, key=totals.get)
    payments = Counter(r['Payment'] for r in rows)
    payment, count = payments.most_common(1)[0]
    return [
        case(suite, 'branch', 'Which branch has the highest sum of the numeric values in Total as stored? No currency symbol is needed.',
             expected_rows=[[branch, float(totals[branch])]], answer_numbers=[float(totals[branch])], answer_terms=[branch]),
        case(suite, 'product_lines', 'For branch A, show the sum of Total as stored for each product line. No currency symbol is needed.',
             expected_rows=[[line, float(value)] for line, value in lines.items()]),
        case(suite, 'payment', 'Across the whole dataset, which payment method is used most often? Include the row count.',
             expected_rows=[[payment, count]], answer_numbers=[count], answer_terms=[payment]),
    ]
