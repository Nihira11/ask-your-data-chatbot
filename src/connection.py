"""Explicit live model/tool check using two disposable, non-user data rows."""
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from src.config import AIConfig
from src.storage import Store
from src.tools import DatasetTools
from src.workflow import ai_answer


async def check_connection(config: AIConfig) -> dict:
    try:
        config.validate()
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}
    with tempfile.TemporaryDirectory(prefix='ask-your-data-connection-') as directory:
        store = Store(Path(directory))
        dataset_id = 'connection-check'
        with closing(sqlite3.connect(store.dataset_path(dataset_id))) as db, db:
            db.execute('CREATE TABLE records (amount INTEGER)')
            db.executemany('INSERT INTO records VALUES (?)', [(20,), (22,)])
        store.add_dataset(dataset_id, 'Connection test', 'csv', {
            'definitions': 'Disposable connection check. records has two rows. amount is an integer count. Add the amounts using SUM(amount). No currency or dates apply.'
        })
        tools = DatasetTools(store, dataset_id)
        response = await ai_answer('What is the total amount? Run SELECT SUM(amount) AS total FROM records and explain the result.', tools, [], config=config)
        verified = response['status'] == 'answer' and any(q['rows'] == [[42]] for q in tools.results)
        return {'ok': verified,
                'message': 'Connected. The model called the checked SQL tool and returned the expected result.' if verified else (
                    response['answer'] if response['status'] == 'unable' else 'The model responded, but the expected tool result was not verified. Try another supported model.'),
                'usage': response.get('usage', {})}
