import csv
import sqlite3
from collections import defaultdict
from decimal import Decimal

from src.database import run_query
from src.sample import SAMPLE_DIR, ensure_sample


def test_normalization_and_revenue_against_source(store):
    dataset = ensure_sample(store)
    assert ensure_sample(store) == dataset
    rows = list(csv.DictReader((SAMPLE_DIR / 'online_retail_sample.csv').open()))
    expected = sum(Decimal(r['quantity']) * Decimal(r['unit_price']) for r in rows if Decimal(r['unit_price']) >= 0)
    result = run_query(store.dataset_path(dataset), 'SELECT ROUND(SUM(quantity * unit_price), 2) FROM order_items WHERE unit_price >= 0')
    assert Decimal(str(result['rows'][0][0])) == expected
    assert run_query(store.dataset_path(dataset), 'SELECT COUNT(*) FROM order_items')['rows'] == [[len(rows)]]
    with sqlite3.connect(store.dataset_path(dataset)) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    invoices = defaultdict(set)
    dates = defaultdict(list)
    for row in rows:
        invoices[row['invoice_id']].add((row['customer_id'], row['country']))
        dates[row['invoice_id']].append(row['invoice_date'])
    assert all(len(values) == 1 for values in invoices.values()), 'Normalization must not discard differing invoice attributes'
    with sqlite3.connect(store.dataset_path(dataset)) as db:
        for order_id, date in db.execute('SELECT order_id, order_date FROM orders'):
            assert date == min(dates[order_id])
        assert [r[0] for r in db.execute('SELECT invoice_date FROM order_items ORDER BY line_id')] == [r['invoice_date'] for r in rows]


def test_deleted_sample_file_is_rebuilt_without_replacing_metadata_or_chat(store):
    dataset = ensure_sample(store)
    chat = store.new_chat(dataset)
    store.append(chat, dataset, 'user', {'answer': 'An earlier question'})
    original = store.dataset(dataset)
    store.dataset_path(dataset).unlink()
    assert ensure_sample(store) == dataset
    assert store.dataset(dataset) == original
    assert store.chat(chat)['dataset_id'] == dataset
    assert len(store.messages(chat)) == 1
    assert run_query(store.dataset_path(dataset), 'SELECT COUNT(*) FROM orders')['rows'] == [[390]]
    assert ensure_sample(store) == dataset
