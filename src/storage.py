"""Local chat metadata; dataset databases live separately and are immutable after import."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOME = ROOT / 'data' / 'private'


class Store:
    def __init__(self, home: Path = DEFAULT_HOME):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / 'datasets').mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id),
                    dataset_id TEXT NOT NULL REFERENCES datasets(id),
                    role TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS ai_preferences (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL,
                    model TEXT NOT NULL);
            ''')

    def ai_preferences(self) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT enabled, model FROM ai_preferences WHERE id=1').fetchone()
        return {'enabled': bool(row['enabled']), 'model': row['model']} if row else {'enabled': False, 'model': ''}

    def save_ai_preferences(self, *, enabled: bool, model: str) -> None:
        """Remember only mode/model; credentials never enter local preferences."""
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO ai_preferences VALUES (1, ?, ?)',
                       (bool(enabled), model))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.home / 'chats.sqlite3')
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def dataset_path(self, dataset_id: str) -> Path:
        # Only application-generated identifiers may select a file.
        if not dataset_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in dataset_id):
            raise ValueError('Invalid dataset identifier.')
        return self.home / 'datasets' / f'{dataset_id}.sqlite3'

    def add_dataset(self, dataset_id: str, name: str, kind: str, metadata: dict) -> None:
        with self.connect() as db:
            db.execute('INSERT INTO datasets VALUES (?, ?, ?, ?)',
                       (dataset_id, name, kind, json.dumps(metadata)))

    def dataset(self, dataset_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM datasets WHERE id = ?', (dataset_id,)).fetchone()
        if row is None:
            raise ValueError('Dataset not found.')
        result = dict(row)
        result['metadata'] = json.loads(result['metadata'])
        return result

    def new_chat(self, dataset_id: str, title: str = 'Sales exploration') -> str:
        chat_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO chats (id, title, dataset_id) VALUES (?, ?, ?)',
                       (chat_id, title, dataset_id))
        return chat_id

    def save_definitions(self, chat_id: str, definitions: str, *,
                         append: bool = False, expected_revision: int | None = None) -> int:
        """Save user-confirmed meanings for this CSV, preserving historical evidence."""
        definitions = definitions.strip()
        if len(definitions) > 8000:
            raise ValueError('Keep your definitions under 8,000 characters.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT d.* FROM datasets d JOIN chats c ON c.dataset_id=d.id WHERE c.id=?', (chat_id,)).fetchone()
            if row is None:
                raise ValueError('Chat not found.')
            if row['kind'] != 'csv':
                raise ValueError('The sample has reviewed definitions. Import a CSV to add your own.')
            metadata = json.loads(row['metadata'])
            revision = metadata.get('definitions_revision', 0)
            if expected_revision is not None and revision != expected_revision:
                raise ValueError('Definitions changed since this clarification. Please confirm again.')
            if append:
                existing = metadata.get('confirmed_definitions', '')
                if definitions in existing.splitlines():
                    return revision
                definitions = '\n'.join(filter(None, (existing, definitions)))
                if len(definitions) > 8000:
                    raise ValueError('Keep your definitions under 8,000 characters.')
            if metadata.get('confirmed_definitions', '') == definitions:
                return revision
            revision += 1
            metadata.update(confirmed_definitions=definitions, definitions_revision=revision)
            db.execute('UPDATE datasets SET metadata=? WHERE id=?', (json.dumps(metadata), row['id']))
            # Every chat sharing the dataset needs a context boundary after a meaning changes.
            for chat in db.execute('SELECT id FROM chats WHERE dataset_id=?', (row['id'],)).fetchall():
                db.execute('INSERT INTO messages (chat_id,dataset_id,role,payload) VALUES (?,?,?,?)',
                           (chat['id'], row['id'], 'system', json.dumps({
                               'answer': f'Definition saved: {definitions.splitlines()[-1]}' if append else 'Data definitions updated. New answers will use the saved meanings.',
                               'definitions_revision': revision,
                               # An accepted clarification continues this conversation.
                               # Other chats must stop using their older definitions.
                               'context_reset': not (append and chat['id'] == chat_id),
                           })))
        return revision

    def discard_empty_chat(self, chat_id: str) -> bool:
        """Remove only an unused sample chat; keep messages and imported datasets."""
        with self.connect() as db:
            return bool(db.execute('''DELETE FROM chats WHERE id = ?
                AND NOT EXISTS (SELECT 1 FROM messages WHERE chat_id = chats.id)
                AND dataset_id IN (SELECT id FROM datasets WHERE kind = 'sample')''',
                (chat_id,)).rowcount)

    def chats(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM chats ORDER BY rowid DESC')]

    def chat(self, chat_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM chats WHERE id = ?', (chat_id,)).fetchone()
        if row is None:
            raise ValueError('Chat not found.')
        return dict(row)

    def activate(self, chat_id: str, dataset_id: str) -> None:
        dataset = self.dataset(dataset_id)
        with self.connect() as db:
            if not db.execute('UPDATE chats SET dataset_id = ? WHERE id = ?',
                              (dataset_id, chat_id)).rowcount:
                raise ValueError('Chat not found.')
            db.execute('INSERT INTO messages (chat_id, dataset_id, role, payload) VALUES (?, ?, ?, ?)',
                       (chat_id, dataset_id, 'system', json.dumps({'answer': f'Dataset changed to {dataset["name"]}. Earlier answers belong to their original dataset.'})))

    def append(self, chat_id: str, dataset_id: str, role: str, payload: dict) -> None:
        with self.connect() as db:
            db.execute('INSERT INTO messages (chat_id, dataset_id, role, payload) VALUES (?, ?, ?, ?)',
                       (chat_id, dataset_id, role, json.dumps(payload, allow_nan=False)))

    def messages(self, chat_id: str, *, current_only: bool = False) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT * FROM messages WHERE chat_id = ? ORDER BY id', (chat_id,)).fetchall()
        result = [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]
        if current_only:
            # A replacement is a context boundary, even when restoring an older dataset.
            boundary = max((i + 1 for i, r in enumerate(result)
                            if r['role'] == 'system' and r['payload'].get('context_reset', True)), default=0)
            active = self.chat(chat_id)['dataset_id']
            result = [r for r in result[boundary:] if r['dataset_id'] == active]
        return result
