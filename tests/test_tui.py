import asyncio

import pytest

from textual.containers import VerticalScroll
from textual.widgets import Button, Input, ListView, RichLog, Static, TextArea

from src.tui import ChatsScreen, DataChatApp, DetailsScreen, ImportScreen


def conversation_lines(app):
    return [line for widget in app.query('#conversation Static')
            for line in str(widget.content).splitlines()]


async def click_results(app, pilot, answer_id):
    button = app.query_one(f'#results-{answer_id}', Button)
    button.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(button)
    await pilot.pause()


async def test_leaving_empty_chat_removes_it_but_keeps_saved_conversation(store):
    from src.workflow import ask
    app = DataChatApp(store)
    saved = app.chat_id
    await ask(store, saved, 'total revenue')
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click('#new-chat')
        await pilot.pause()
        empty = app.chat_id
        await pilot.click('#saved-chats')
        await pilot.pause()
        assert not app.screen.query('#chat-' + empty)
        await pilot.click('#chat-' + saved)
        await pilot.pause()
        assert app.chat_id == saved
        assert empty not in {chat['id'] for chat in store.chats()}
        assert len(store.messages(saved)) == 2


async def test_repeated_empty_chats_and_quitting_leave_no_unused_chats(store):
    app = DataChatApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(3):
            await pilot.press('ctrl+n')
            await pilot.pause()
            assert len(store.chats()) == 1
        await pilot.click('#saved-chats')
        await pilot.pause()
        assert len(app.screen.query_one('#chats', ListView).children) == 0
        await pilot.press('escape')
        assert store.chat(app.chat_id)
        await pilot.press('ctrl+q')
        assert app._exit
        assert store.chats() == []


async def test_unsent_draft_is_kept_when_switching_chats(store):
    app = DataChatApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        draft_chat = app.chat_id
        app.query_one('#question', Input).value = 'My unfinished question'
        await pilot.click('#new-chat')
        await pilot.pause()
        assert app.query_one('#question', Input).value == ''
        await pilot.click('#saved-chats')
        await pilot.pause()
        await pilot.click('#chat-' + draft_chat)
        await pilot.pause()
        assert app.query_one('#question', Input).value == 'My unfinished question'
        assert len(store.chats()) == 1


@pytest.mark.parametrize('existing_chat', [False, True])
@pytest.mark.parametrize('outcome', ['answer', 'unable', 'exception'])
async def test_pending_answer_shows_question_and_preserves_unsent_draft(store, monkeypatch, existing_chat, outcome):
    from src.workflow import ask
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def delayed_answer(question, tools, history, **kwargs):
        calls.append(question)
        started.set()
        await finish.wait()
        if outcome == 'exception':
            raise RuntimeError('internal details must not be displayed')
        return {'status': outcome, 'answer': 'Test answer complete.' if outcome == 'answer' else 'The model timed out. Please try again.'}

    monkeypatch.setattr('src.workflow.ai_answer', delayed_answer)
    app = DataChatApp(store, use_ai=True)
    if existing_chat:
        await ask(store, app.chat_id, 'total revenue')
    async with app.run_test(size=(80, 24)) as pilot:
        field = app.query_one('#question', Input)
        field.value = 'Only for France.'
        await pilot.press('enter')
        await asyncio.wait_for(started.wait(), timeout=2)
        await pilot.pause()
        log = app.query_one('#conversation', VerticalScroll)
        lines = conversation_lines(app)
        assert log.display
        assert not app.query_one('#welcome').display
        assert lines.count('Only for France.') == 1
        assert 'Thinking…' in lines
        assert app.busy and app.query_one('#send', Button).disabled
        assert not field.disabled
        assert field.has_focus
        assert field.region.bottom <= 24
        if existing_chat:
            assert any('117,058.55' in line for line in lines)
        await pilot.press(*'My next question')
        await pilot.press('enter')
        await pilot.click('#send')
        await pilot.pause()
        assert field.value == 'My next question'
        assert calls == ['Only for France.']
        assert store.messages(app.chat_id)[-1]['role'] == 'user'
        finish.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert field.value == 'My next question'
        assert not app.busy and not app.query_one('#send', Button).disabled
        lines = conversation_lines(app)
        assert lines.count('Only for France.') == 1
        assert 'Thinking…' not in lines
        assert 'My next question' not in lines
        if outcome == 'exception':
            assert any('Could not finish this answer.' in line for line in lines)
            assert not any('internal details' in line for line in lines)
        else:
            assert store.messages(app.chat_id)[-1]['role'] == 'assistant'
        # Finishing never auto-sends a draft: the next explicit Enter submits it.
        field.focus()
        await pilot.press('enter')
        await app.workers.wait_for_complete()
        assert calls == ['Only for France.', 'My next question']


@pytest.mark.parametrize('dialog', [None, '#saved-chats', '#settings', '#load-csv'])
async def test_ctrl_q_exits_from_input_and_dialogs(store, dialog):
    app = DataChatApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        if dialog:
            await pilot.click(dialog)
        else:
            app.query_one('#question', Input).focus()
        await pilot.press('ctrl+q')
        await pilot.pause()
        assert app._exit


async def test_default_terminal_keeps_input_visible(store):
    app = DataChatApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        question = app.query_one('#question', Input)
        assert question.region.bottom <= 24
        assert app.query_one('#welcome').display
        assert not app.query('.answer-results')
        await pilot.click('#example-total')
        assert question.value == 'What is the total revenue?'
        await pilot.click('#send')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert store.messages(app.chat_id)[-1]['payload']['queries'][0]['rows'] == [[117058.55]]
        assert not app.query_one('#welcome').display
        assert app.query_one('#conversation').region.height >= 3
        assert app.query('.answer-results')
        mode = app.query_one('#mode-label', Static)
        assert mode.content == 'Demo mode · no API charges'
        assert mode.region.bottom <= question.region.y
        assert mode.region.width >= len(mode.content)


async def test_terminal_question_new_chat_and_restore(store):
    app = DataChatApp(store)
    async with app.run_test(size=(120, 60)) as pilot:
        first_chat = app.chat_id
        question = app.query_one('#question', Input)
        question.value = 'What is the total revenue?'
        await pilot.press('enter')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert store.messages(first_chat)[-1]['payload']['queries']
        question.value = 'Show monthly revenue'
        await pilot.press('enter')
        await pilot.pause()
        await app.workers.wait_for_complete()
        await click_results(app, pilot, store.messages(app.chat_id)[-1]['id'])
        await pilot.pause()
        assert isinstance(app.screen, DetailsScreen)
        assert 'SUM' in app.screen.query_one('#sql', TextArea).text
        await pilot.press('escape')
        await pilot.click('#new-chat')
        await pilot.pause()
        assert app.chat_id != first_chat
        assert app.query_one('#mode-label', Static).content == 'Demo mode · no API charges'
        assert not app.query('.answer-results')
        await pilot.click('#saved-chats')
        await pilot.pause()
        assert isinstance(app.screen, ChatsScreen)
        await pilot.click('#chat-' + first_chat)
        await pilot.pause()
        assert app.chat_id == first_chat
        # Opening a hidden conversation must use its full layout width on the
        # first click, rather than permanently wrapping it into a narrow column.
        log = app.query_one('#conversation', VerticalScroll)
        lines = conversation_lines(app)
        assert 'What is the total revenue?' in lines
        assert 'Net revenue is £117,058.55, including cancellation credits.' in lines
        assert 'Net revenue by month, including cancellation credits:' in lines
        assert 'Dec 2010 — £11,039.40' in lines
        assert log.scroll_y == 0
        await click_results(app, pilot, store.messages(app.chat_id)[-1]['id'])
        await pilot.pause()
        assert 'SUM' in app.screen.query_one('#sql', TextArea).text


async def test_csv_preview_confirmation_and_dataset_marker(store, tmp_path, monkeypatch):
    path = tmp_path / 'custom.csv'
    path.write_text('sku,amount\n001,25\n002,40\n')
    selections = iter([path, None])
    async def fake_picker():
        return next(selections)
    monkeypatch.setattr('src.tui.choose_csv_file', fake_picker)
    app = DataChatApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        # Create an answer before replacing the dataset, to check historical evidence.
        app.query_one('#question', Input).value = 'How many orders are there?'
        await pilot.press('enter')
        await pilot.pause()
        await app.workers.wait_for_complete()
        old_answer = store.messages(app.chat_id)[-1]['id']
        await pilot.click('#load-csv')
        await pilot.pause()
        assert isinstance(app.screen, ImportScreen)
        await pilot.click('#choose-csv')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert isinstance(app.screen, ImportScreen)
        assert not app.screen.query_one('#confirm', Button).disabled
        assert store.chat(app.chat_id)['dataset_id'] == app.sample_id
        preview = app.screen.inspected
        await pilot.click('#choose-csv')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.screen.inspected is preview
        assert not app.screen.query_one('#confirm', Button).disabled
        await pilot.click('#confirm')
        await pilot.pause()
        active = store.chat(app.chat_id)['dataset_id']
        assert store.dataset(active)['name'] == 'custom.csv'
        assert store.messages(app.chat_id)[-1]['role'] == 'system'
        app.query_one('#question', Input).value = 'how many rows'
        app.query_one('#question', Input).focus()
        await pilot.press('enter')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert store.messages(app.chat_id)[-1]['payload']['queries'][0]['rows'] == [[2]]
        await click_results(app, pilot, store.messages(app.chat_id)[-1]['id'])
        await pilot.pause()
        assert 'records' in app.screen.query_one('#sql', TextArea).text
        await pilot.click('#close-details')
        await pilot.pause()
        await click_results(app, pilot, old_answer)
        assert 'orders' in app.screen.query_one('#sql', TextArea).text
        await pilot.click('#close-details')
        await pilot.pause()
        async def export_picker(default):
            assert default == store.home / 'exports'
            return tmp_path
        monkeypatch.setattr('src.tui.choose_export_folder', export_picker)
        await pilot.click('#export-chat')
        await pilot.pause()
        assert app.screen.query_one('#cancel-export', Button).region.bottom <= 24
        assert not list(tmp_path.glob('chat-results-*'))
        await pilot.click('#confirm-export')
        await pilot.pause()
        await app.workers.wait_for_complete()
        from pathlib import Path
        import json
        folder = Path(app.screen.query_one('#export-path', TextArea).text)
        notes = json.loads((folder / 'details.json').read_text())
        assert len(notes['answers']) == 2
        assert notes['answers'][0]['answer_id'] == old_answer
        assert notes['answers'][0]['dataset_id'] != active
        assert notes['answers'][1]['dataset_id'] == active
        assert folder.parent == tmp_path
        assert '390' in (folder / 'answer-001-query-01.csv').read_text()
        assert app.screen.query_one('#close-export', Button).region.bottom <= 24
        await pilot.click('#close-export')
        await pilot.pause()
        assert app.query_one('#question', Input).region.bottom <= 24


async def test_definition_editor_saves_without_changing_dataset(store, simple_dataset):
    from src.tui import DefinitionsScreen
    chat = store.new_chat(simple_dataset)
    app = DataChatApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click('#settings')
        await pilot.pause()
        await pilot.click('#choose-definitions')
        await pilot.pause()
        assert isinstance(app.screen, DefinitionsScreen)
        app.screen.query_one('#definition-text', TextArea).load_text('amount is in AUD.')
        await pilot.click('#definitions-save')
        await pilot.pause()
        assert store.chat(chat)['dataset_id'] == simple_dataset
        assert store.dataset(simple_dataset)['metadata']['confirmed_definitions'] == 'amount is in AUD.'
        assert app.query_one('#question', Input).region.bottom <= 24


async def test_ai_setup_verification_enable_and_demo_switch(store, monkeypatch):
    from src.tui import AISetupScreen
    calls = []
    async def fake_check(config):
        calls.append(config)
        return {'ok': True, 'message': 'Connected with verified test data.'}
    monkeypatch.setattr('src.tui.check_connection', fake_check)
    app = DataChatApp(store)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click('#settings')
        await pilot.pause()
        await pilot.click('#choose-ai')
        await pilot.pause()
        assert isinstance(app.screen, AISetupScreen)
        assert app.screen.query_one('#api-key', Input).password
        app.screen.query_one('#api-key', Input).value = 'test-key-private'
        app.screen.query_one('#api-model', Input).value = 'test-model'
        await pilot.pause()
        assert not app.screen.query_one('#use-ai', Button).disabled
        await pilot.click('#test-connection')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(calls) == 1
        assert not app.screen.query_one('#use-ai', Button).disabled
        # Editing configuration invalidates the successful check.
        app.screen.query_one('#api-model', Input).value = 'other-model'
        # The mocked request finishes faster than Textual's button click debounce.
        await pilot.pause(0.35)
        assert app.screen.checked is None
        assert not app.screen.query_one('#use-ai', Button).disabled
        await pilot.click('#test-connection')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(calls) == 2
        await pilot.click('#use-ai')
        await pilot.pause()
        assert app.use_ai
        assert app.query_one('#mode-label', Static).content == 'AI mode · uses paid API credits'
        await pilot.click('#new-chat')
        await pilot.pause()
        assert app.use_ai
        assert app.query_one('#mode-label', Static).content == 'AI mode · uses paid API credits'
        assert app.ai_config.model == 'other-model'
        assert app.ai_config.api_key == 'test-key-private'
        assert 'test-key-private' not in str(store.messages(app.chat_id))
        await pilot.click('#settings')
        await pilot.pause()
        await pilot.click('#choose-ai')
        await pilot.pause()
        await pilot.click('#use-demo')
        await pilot.pause()
        assert not app.use_ai
        app.query_one('#question', Input).value = 'total revenue'
        await pilot.press('enter')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert not app.use_ai
        assert app.query_one('#mode-label', Static).content == 'Demo mode · no API charges'
        assert store.messages(app.chat_id)[-1]['payload']['mode'] == 'offline'

async def test_ai_preference_restarts_without_test_or_secret_storage(store, monkeypatch):
    from src.storage import Store
    from agents import Runner

    async def no_network(*args, **kwargs):
        raise AssertionError('Startup and mode selection must not call the API')

    monkeypatch.setattr('src.tui.check_connection', no_network)
    monkeypatch.setattr(Runner, 'run', no_network)
    monkeypatch.setenv('OPENAI_API_KEY', 'configured-private-test-key')
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    app = DataChatApp(store)
    async with app.run_test(size=(100, 32)) as pilot:
        app.open_setting('ai')
        await pilot.pause()
        assert app.screen.query_one('#use-ai', Button).disabled
        app.screen.query_one('#api-model', Input).value = 'chosen-model'
        await pilot.pause()
        await pilot.click('#use-ai')
        await pilot.pause()
        assert app.use_ai
    reopened = DataChatApp(Store(store.home))
    async with reopened.run_test(size=(100, 32)) as pilot:
        assert reopened.use_ai
        assert reopened.ai_config.model == 'chosen-model'
        assert reopened.ai_config.api_key == 'configured-private-test-key'
        reopened.open_setting('ai')
        await pilot.pause()
        assert not reopened.screen.query_one('#use-ai', Button).disabled
        await pilot.click('#use-demo')
        await pilot.pause()
        assert not reopened.use_ai
    assert not DataChatApp(Store(store.home)).use_ai
    assert store.ai_preferences() == {'enabled': False, 'model': 'chosen-model'}
    assert b'configured-private-test-key' not in (store.home / 'chats.sqlite3').read_bytes()


async def test_saved_ai_without_key_starts_demo_with_setup_notice(store, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    store.save_ai_preferences(enabled=True, model='saved-model')
    app = DataChatApp(store)
    async with app.run_test(size=(100, 32)):
        assert not app.use_ai
        assert 'AI setup needed' in str(app.query_one('#status', Static).content)
        assert app.ai_config.model == 'saved-model'
    # Missing credentials do not erase the preference; explicit demo overrides it.
    assert store.ai_preferences()['enabled']
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    assert DataChatApp(store).use_ai
    assert not DataChatApp(store, use_ai=False).use_ai


async def test_each_answer_opens_its_own_results_including_followups(store):
    app = DataChatApp(store)
    chat, dataset = app.chat_id, app.sample_id
    answer_ids = []
    turns = [
        ('Which branch has the highest total?', 'What should Total mean?', []),
        ('Yes, use Total.', 'Branch C.', [{'sql': 'SELECT 3 AS total', 'columns': ['total'], 'rows': [[3]], 'truncated': False}]),
        ('Show that for branch A.', 'Branch A.', [{'sql': 'SELECT 1 AS total', 'columns': ['total'], 'rows': [[1]], 'truncated': False}]),
        ('How many units?', 'Use quantity?', []),
        ('yes please', '971 units.', [{'sql': 'SELECT 971 AS units', 'columns': ['units'], 'rows': [[971]], 'truncated': False}]),
        ('Only nonexistent products.', 'No matching rows.', [{'sql': 'SELECT 1 WHERE 0', 'columns': ['1'], 'rows': [], 'truncated': False}]),
    ]
    for question, answer, queries in turns:
        store.append(chat, dataset, 'user', {'answer': question})
        store.append(chat, dataset, 'assistant', {'answer': answer, 'queries': queries})
        answer_ids.append(store.messages(chat)[-1]['id'])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert len(app.query('.answer-results')) == 4
        assert not app.query('#details-button')
        for answer_id, (question, answer, queries) in zip(answer_ids, turns):
            if not queries:
                assert not app.query(f'#results-{answer_id}')
                continue
            await click_results(app, pilot, answer_id)
            assert isinstance(app.screen, DetailsScreen)
            assert app.screen.selected_answer['id'] == answer_id
            assert app.screen.query_one('#answer-question', Static).content == question
            assert app.screen.query_one('#sql', TextArea).text == queries[0]['sql']
            assert not app.screen.query('#answer-choice')
            await pilot.press('escape')
            await pilot.pause()
        # Stable message IDs preserve the same links after reopening a saved chat.
        await pilot.click('#new-chat')
        await pilot.click('#saved-chats')
        await pilot.pause()
        await pilot.click('#chat-' + chat)
        await pilot.pause()
        assert len(app.query('.answer-results')) == 4
        await click_results(app, pilot, answer_ids[4])
        assert app.screen.query_one('#sql', TextArea).text == 'SELECT 971 AS units'


@pytest.mark.parametrize('cancelled', [True, False])
async def test_chat_export_cancel_or_error_leaves_chat_intact(store, tmp_path, monkeypatch, cancelled):
    from src.workflow import ask
    app = DataChatApp(store)
    await ask(store, app.chat_id, 'total revenue')
    before = store.messages(app.chat_id)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def picker(default):
        calls.append(default)
        started.set()
        await release.wait()
        if cancelled:
            return None
        raise RuntimeError('chooser failed')
    monkeypatch.setattr('src.tui.choose_export_folder', picker)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        field = app.query_one('#question', Input)
        field.value = 'Keep my draft'
        button = app.query_one('#export-chat', Button)
        assert button.region.bottom <= 24
        await pilot.click(button)
        await asyncio.wait_for(started.wait(), 2)
        assert button.disabled
        await pilot.click(button)
        assert len(calls) == 1
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not button.disabled
        assert not app.exporting
        assert field.value == 'Keep my draft'
        assert store.messages(app.chat_id) == before
        assert not list(store.home.rglob('chat-results-*'))


@pytest.mark.parametrize('cancel_action', ['button', 'escape'])
async def test_export_confirmation_cancel_preserves_draft_and_writes_nothing(store, tmp_path, monkeypatch, cancel_action):
    from src.workflow import ask
    from src.tui import ExportConfirmScreen
    app = DataChatApp(store)
    await ask(store, app.chat_id, 'total revenue')
    before = store.messages(app.chat_id)
    async def picker(default):
        return tmp_path
    monkeypatch.setattr('src.tui.choose_export_folder', picker)
    async with app.run_test(size=(80, 24)) as pilot:
        field = app.query_one('#question', Input)
        field.value = 'My next question'
        await pilot.click('#export-chat')
        await pilot.pause()
        assert isinstance(app.screen, ExportConfirmScreen)
        assert not list(tmp_path.glob('chat-results-*'))
        if cancel_action == 'button':
            await pilot.click('#cancel-export')
        else:
            await pilot.press('escape')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert not list(tmp_path.glob('chat-results-*'))
        assert field.value == 'My next question'
        assert store.messages(app.chat_id) == before
        assert not app.exporting
        assert app.focused is field
