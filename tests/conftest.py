import sqlite3

import pytest

from src.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'storage')


@pytest.fixture
def simple_dataset(store):
    dataset_id = 'test-sales'
    with sqlite3.connect(store.dataset_path(dataset_id)) as db:
        db.executescript('CREATE TABLE records (item TEXT, amount REAL); INSERT INTO records VALUES ("pen", 10), ("book", 20), ("refund", -5);')
    store.add_dataset(dataset_id, 'test.csv', 'csv', {'definitions': 'Each record is a transaction. Amount has unspecified units.'})
    return dataset_id
