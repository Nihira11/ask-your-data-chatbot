import pytest

from textual.widgets import Button, Input, ListView, RichLog, Select, TextArea

from src.tui import ChatsScreen, DataChatApp, DetailsScreen, ImportScreen


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
        assert not app.query_one('#details-row').display
        await pilot.click('#example-total')
        assert question.value == 'What is the total revenue?'
        await pilot.click('#send')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert store.messages(app.chat_id)[-1]['payload']['queries'][0]['rows'] == [[117058.55]]
        assert not app.query_one('#welcome').display
        assert app.query_one('#conversation').region.height >= 3
        assert app.query_one('#details-row').display


async def test_terminal_question_new_chat_and_restore(store):
    app = DataChatApp(store)
    async with app.run_test(size=(120, 40)) as pilot:
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
        await pilot.click('#details-button')
        await pilot.pause()
        assert isinstance(app.screen, DetailsScreen)
        assert 'SUM' in app.screen.query_one('#sql', TextArea).text
        await pilot.press('escape')
        await pilot.click('#new-chat')
        await pilot.pause()
        assert app.chat_id != first_chat
        assert not app.query_one('#details-row').display
        await pilot.click('#saved-chats')
        await pilot.pause()
        assert isinstance(app.screen, ChatsScreen)
        await pilot.click('#chat-' + first_chat)
        await pilot.pause()
        assert app.chat_id == first_chat
        # Opening a hidden conversation must use its full layout width on the
        # first click, rather than permanently wrapping it into a narrow column.
        log = app.query_one('#conversation', RichLog)
        lines = [line.text.rstrip() for line in log.lines]
        assert 'What is the total revenue?' in lines
        assert 'Net revenue is £117,058.55, including cancellation credits.' in lines
        assert 'Found 13 rows. Open “View answer details” to see the results.' in lines
        assert log.scroll_y == 0
        await pilot.click('#details-button')
        await pilot.pause()
        assert 'SUM' in app.screen.query_one('#sql', TextArea).text


async def test_csv_preview_confirmation_and_dataset_marker(store, tmp_path):
    path = tmp_path / 'custom.csv'
    path.write_text('sku,amount\n001,25\n002,40\n')
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
        app.screen.query_one('#csv-path', Input).value = str(path)
        await pilot.pause()
        await pilot.click('#preview')
        await pilot.pause()
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
        await pilot.click('#details-button')
        await pilot.pause()
        assert 'records' in app.screen.query_one('#sql', TextArea).text
        app.screen.query_one('#answer-choice', Select).value = old_answer
        await pilot.pause()
        assert 'orders' in app.screen.query_one('#sql', TextArea).text
        await pilot.click('#close-details')
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
        assert app.screen.query_one('#use-ai', Button).disabled
        await pilot.click('#test-connection')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(calls) == 1
        assert not app.screen.query_one('#use-ai', Button).disabled
        # Editing configuration invalidates the successful check.
        app.screen.query_one('#api-model', Input).value = 'other-model'
        # The mocked request finishes faster than Textual's button click debounce.
        await pilot.pause(0.35)
        assert app.screen.query_one('#use-ai', Button).disabled
        await pilot.click('#test-connection')
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(calls) == 2
        await pilot.click('#use-ai')
        await pilot.pause()
        assert app.use_ai
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
