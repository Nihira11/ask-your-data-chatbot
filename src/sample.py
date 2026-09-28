"""Build the bundled, attributed UCI sample into relational SQLite tables."""
import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from src.storage import ROOT, Store

SAMPLE_DIR = ROOT / 'data' / 'sample'


def ensure_sample(store: Store) -> str:
    manifest = json.loads((SAMPLE_DIR / 'manifest.json').read_text())
    dataset_id = manifest['version']
    try:
        store.dataset(dataset_id)
        return dataset_id
    except ValueError:
        pass
    source = SAMPLE_DIR / 'online_retail_sample.csv'
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('Bundled sample checksum does not match its manifest.')
    path = store.dataset_path(dataset_id)
    try:
        with source.open(newline='', encoding='utf-8') as file, closing(sqlite3.connect(path)) as db, db:
            db.execute('PRAGMA foreign_keys = ON')
            db.executescript('''
                CREATE TABLE customers (customer_id TEXT PRIMARY KEY);
                CREATE TABLE products (product_id TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_id TEXT REFERENCES customers,
                    order_date TEXT NOT NULL, country TEXT, is_cancellation INTEGER NOT NULL);
                CREATE TABLE order_items (line_id INTEGER PRIMARY KEY, order_id TEXT REFERENCES orders,
                    product_id TEXT REFERENCES products, quantity INTEGER NOT NULL, unit_price REAL NOT NULL,
                    invoice_date TEXT NOT NULL);
                CREATE INDEX items_order ON order_items(order_id);
                CREATE INDEX items_product ON order_items(product_id);
                CREATE INDEX orders_date ON orders(order_date);
            ''')
            for row in csv.DictReader(file):
                customer = row['customer_id'] or None
                if customer:
                    db.execute('INSERT OR IGNORE INTO customers VALUES (?)', (customer,))
                db.execute('INSERT OR IGNORE INTO products VALUES (?, ?)', (row['product_id'], row['description'] or None))
                db.execute('INSERT OR IGNORE INTO orders VALUES (?, ?, ?, ?, ?)',
                           (row['invoice_id'], customer, row['invoice_date'], row['country'] or None,
                            int(row['invoice_id'].upper().startswith('C'))))
                db.execute('UPDATE orders SET order_date = MIN(order_date, ?) WHERE order_id = ?',
                           (row['invoice_date'], row['invoice_id']))
                db.execute('INSERT INTO order_items (order_id, product_id, quantity, unit_price, invoice_date) VALUES (?, ?, ?, ?, ?)',
                           (row['invoice_id'], row['product_id'], int(row['quantity']), float(row['unit_price']), row['invoice_date']))
        store.add_dataset(dataset_id, 'UCI Online Retail · sample', 'sample', manifest)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return dataset_id
