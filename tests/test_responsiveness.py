"""Exercise genuinely blocking work while Textual's event loop remains usable."""
import asyncio
import threading

import pytest
from textual.widgets import Button, Input

from src.importer import inspect_csv
from src.tui import DataChatApp, ImportScreen
from src.workflow import ask


class BlockingCall:
    def __init__(self, original):
        self.original = original
        self.started = threading.Event()
        self.release = threading.Event()
        self.thread = None

    def __call__(self, *args, **kwargs):
        self.thread = threading.get_ident()
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError('Test did not release blocking work')
        return self.original(*args, **kwargs)

    async def wait_started(self):
        assert await asyncio.to_thread(self.started.wait, 3)
        assert self.thread != threading.get_ident(), 'Blocking work ran on the event loop'


@pytest.mark.parametrize('question', ['how many rows', 'describe my data', '/sql SELECT SUM(amount) FROM records'])
async def test_local_queries_do_not_block_drafting(store, simple_dataset, monkeypatch, question):
    from src import workflow
    blocking = BlockingCall(workflow.offline_answer)
    monkeypatch.setattr(workflow, 'offline_answer', blocking)
    chat = store.new_chat(simple_dataset)
    app = DataChatApp(store)
    async with app.run_test() as pilot:
        assert app.chat_id == chat
        field = app.query_one('#question', Input)
        try:
            field.value = question
            await pilot.press('enter')
            await blocking.wait_started()
            await pilot.press(*'Next question')
            assert app.busy
            assert field.value == 'Next question'
            assert app.query_one('#send', Button).disabled
        finally:
            blocking.release.set()
        await app.workers.wait_for_complete()
        assert not app.busy
        assert field.value == 'Next question'
        assert store.messages(chat)[-1]['payload']['status'] == 'answer'


async def test_csv_preview_can_be_closed_while_inspecting(store, tmp_path, monkeypatch):
    from src import tui
    path = tmp_path / 'preview.csv'
    path.write_text('amount\n5\n')
    async def picker():
        return path
    monkeypatch.setattr(tui, 'choose_csv_file', picker)
    blocking = BlockingCall(tui.inspect_csv)
    monkeypatch.setattr(tui, 'inspect_csv', blocking)
    app = DataChatApp(store)
    async with app.run_test() as pilot:
        try:
            await pilot.click('#load-csv')
            await pilot.click('#choose-csv')
            await blocking.wait_started()
            assert app.screen.query_one('#confirm', Button).disabled
            await pilot.press('escape')
            assert not isinstance(app.screen, ImportScreen)
        finally:
            blocking.release.set()
        await pilot.pause()
        assert store.chat(app.chat_id)['dataset_id'] == app.sample_id


async def test_csv_import_keeps_draft_and_prevents_dataset_switch(store, tmp_path, monkeypatch):
    from src import tui
    path = tmp_path / 'import.csv'
    path.write_text('amount\n5\n')
    inspected = inspect_csv(path)
    blocking = BlockingCall(tui.import_csv)
    monkeypatch.setattr(tui, 'import_csv', blocking)
    app = DataChatApp(store)
    async with app.run_test() as pilot:
        original_chat = app.chat_id
        try:
            app.finish_import(inspected)
            await blocking.wait_started()
            await pilot.press(*'Next question')
            await pilot.press('enter', 'ctrl+n')
            assert app.chat_id == original_chat
            assert app.busy and app.query_one('#send', Button).disabled
            assert app.query_one('#question', Input).value == 'Next question'
            assert store.chat(app.chat_id)['dataset_id'] == app.sample_id
        finally:
            blocking.release.set()
        await app.workers.wait_for_complete()
        assert not app.busy
        assert app.query_one('#question', Input).value == 'Next question'
        assert store.dataset(store.chat(original_chat)['dataset_id'])['name'] == 'import.csv'


async def test_export_does_not_block_drafting(store, tmp_path, monkeypatch):
    from src import tui
    app = DataChatApp(store)
    await ask(store, app.chat_id, 'total revenue')
    async def picker(default):
        return tmp_path
    monkeypatch.setattr(tui, 'choose_export_folder', picker)
    blocking = BlockingCall(tui.export_chat_results)
    monkeypatch.setattr(tui, 'export_chat_results', blocking)
    async with app.run_test() as pilot:
        try:
            await pilot.click('#export-chat')
            await pilot.pause()
            await pilot.click('#confirm-export')
            await blocking.wait_started()
            app.query_one('#question', Input).focus()
            await pilot.press(*'Next question')
            assert app.exporting
            assert app.query_one('#question', Input).value == 'Next question'
        finally:
            blocking.release.set()
        await app.workers.wait_for_complete()
        assert not app.exporting
        assert len(list(tmp_path.glob('chat-results-*'))) == 1


async def test_quitting_during_answer_persists_interruption(store, monkeypatch):
    started = asyncio.Event()
    async def waiting(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr('src.workflow.ai_answer', waiting)
    app = DataChatApp(store, use_ai=True)
    chat = app.chat_id
    async with app.run_test() as pilot:
        app.query_one('#question', Input).value = 'A pending question'
        await pilot.press('enter')
        await asyncio.wait_for(started.wait(), 2)
        await pilot.press('ctrl+q')
    saved = store.messages(chat)
    assert [m['role'] for m in saved] == ['user', 'assistant']
    assert 'interrupted' in saved[-1]['payload']['answer']


async def test_ai_category_inspection_and_registered_query_run_off_loop(store, simple_dataset, monkeypatch):
    import json
    from types import SimpleNamespace
    from agents import Runner
    from agents.tool_context import ToolContext
    from src.config import AIConfig
    from src.tools import DatasetTools
    from src.workflow import ai_answer

    main_thread = threading.get_ident()
    original_categories = DatasetTools.category_values
    original_query = DatasetTools.run_checked_query
    original_schema = DatasetTools.get_schema
    original_capabilities = DatasetTools.sql_capabilities
    calls = set()

    def categories(self):
        assert threading.get_ident() != main_thread
        calls.add('categories')
        return original_categories(self)

    def query(self, sql):
        assert threading.get_ident() != main_thread
        calls.add('query')
        return original_query(self, sql)

    def schema(self):
        assert threading.get_ident() != main_thread
        calls.add('schema')
        return original_schema(self)

    def capabilities(self):
        assert threading.get_ident() != main_thread
        calls.add('capabilities')
        return original_capabilities(self)

    monkeypatch.setattr(DatasetTools, 'category_values', categories)
    monkeypatch.setattr(DatasetTools, 'run_checked_query', query)
    monkeypatch.setattr(DatasetTools, 'get_schema', schema)
    monkeypatch.setattr(DatasetTools, 'sql_capabilities', capabilities)

    async def fake_run(agent, recent, **kwargs):
        registered = {tool.name: tool for tool in agent.tools}
        for name, arguments in [('get_schema', '{}'), ('run_checked_query', '{"sql":"SELECT SUM(amount) FROM records"}')]:
            context = ToolContext(context=None, tool_name=name, tool_call_id='test', tool_arguments=arguments)
            output = json.loads(await registered[name].on_invoke_tool(context, arguments))
            assert 'records' in output if name == 'get_schema' else output['rows'] == [[25.0]]
        return SimpleNamespace(final_output=agent.output_type(status='answer', answer='The sum is 25.'),
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace(requests=1, input_tokens=1, output_tokens=1)))

    monkeypatch.setattr(Runner, 'run', fake_run)
    result = await ai_answer('sum', DatasetTools(store, simple_dataset), [], config=AIConfig('test-key', 'test-model'))
    assert result['status'] == 'answer'
    assert calls == {'categories', 'query', 'schema', 'capabilities'}
