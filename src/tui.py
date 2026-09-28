"""A quiet, chat-first terminal interface; supporting details open on demand."""
from __future__ import annotations

from pathlib import Path

from rich import box
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Input, Label, ListItem, ListView, RichLog, Select, Static, TabbedContent, TabPane, TextArea

from src.config import AIConfig
from src.connection import check_connection
from src.retrieval import search_context
from src.database import get_schema
from src.importer import import_csv, inspect_csv
from src.sample import ensure_sample
from src.storage import Store
from src.workflow import EXAMPLES, ask


PAPER = '#fafaf8'
INK = '#302f2c'
MUTED = '#73716c'


def safe(value) -> str:
    """Display data as literal text, never terminal controls or Rich markup."""
    return ''.join(c if c.isprintable() or c == '\n' else ' ' for c in str(value))[:10000]


def result_table(query):
    table = Table(box=box.SIMPLE, show_header=True, header_style=f'bold {INK}',
                  border_style='#d6d4ce', padding=(0, 1), expand=False)
    for column in query['columns']:
        table.add_column(Text(safe(column)), overflow='fold', max_width=36)
    for row in query['rows']:
        table.add_row(*(Text('—' if value is None else safe(value)) for value in row))
    return table


class Dialog(ModalScreen):
    """Shared, restrained styling for secondary tasks."""
    BINDINGS = [('escape', 'close', 'Close')]
    CSS = '''
    .overlay { align: center middle; background: #302f2c 25%; }
    .dialog { width: 82; max-width: 96%; height: 28; max-height: 94%;
        border: round #b4b1a9; padding: 1 2; background: #fafaf8; color: #302f2c; }
    .dialog-title { text-style: bold; height: 1; margin-bottom: 1; }
    .dialog-note { height: auto; color: #73716c; margin-bottom: 1; }
    .dialog-actions { height: 3; margin-top: 1; align-horizontal: right; }
    .dialog-actions Button { margin-left: 1; }
    .dialog RichLog { background: #fafaf8; color: #302f2c; }
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_class('overlay')

    def action_close(self):
        self.dismiss(None)


class ImportScreen(Dialog):
    def __init__(self):
        super().__init__()
        self.inspected = None

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog'):
            yield Label('Use your own data', classes='dialog-title')
            yield Static('Choose a CSV file. A copy will be saved on this device.\nUp to 5 MB · UTF-8 format', classes='dialog-note')
            yield Input(placeholder='Paste the file path here', id='csv-path')
            yield RichLog(id='import-preview', wrap=True, min_width=20)
            with Horizontal(classes='dialog-actions'):
                yield Button('Cancel', id='cancel')
                yield Button('Preview', id='preview')
                yield Button('Use this file', id='confirm', classes='solid', disabled=True)

    @on(Input.Changed, '#csv-path')
    def changed(self):
        self.inspected = None
        self.query_one('#confirm', Button).disabled = True

    @on(Button.Pressed, '#preview')
    def preview(self):
        log = self.query_one('#import-preview', RichLog)
        log.clear()
        try:
            self.inspected = inspect_csv(Path(self.query_one('#csv-path', Input).value))
            data = self.inspected
            log.write(Text(f'{safe(data["name"])} · {len(data["rows"]):,} rows', style='bold'))
            for name, dtype in zip(data['headers'], data['types']):
                log.write(Text(f'{safe(name)} · {dtype.lower()} · {data["null_counts"][name]} empty'))
            log.write(Text('\nColumn meanings can be clarified when you ask a question.', style=MUTED))
            self.query_one('#confirm', Button).disabled = False
        except (ValueError, OSError) as exc:
            log.write(Text(str(exc)))

    @on(Button.Pressed, '#confirm')
    def confirm(self):
        if self.inspected:
            self.dismiss(self.inspected)

    @on(Button.Pressed, '#cancel')
    def cancel(self):
        self.dismiss(None)


class ChatsScreen(Dialog):
    def __init__(self, store: Store, active: str):
        super().__init__()
        self.store = store
        self.active = active

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog'):
            yield Label('Your chats', classes='dialog-title')
            yield Static('Choose a conversation to pick up where you left off.', classes='dialog-note')
            with ListView(id='chats'):
                for chat in self.store.chats():
                    messages = self.store.messages(chat['id'])
                    question = next((m['payload']['answer'] for m in messages if m['role'] == 'user'), 'New conversation')
                    name = self.store.dataset(chat['dataset_id'])['name']
                    label = safe(question).replace('\n', ' ')[:60]
                    yield ListItem(Label(f'{label}\n{safe(name)}', markup=False), id='chat-' + chat['id'])
            with Horizontal(classes='dialog-actions'):
                yield Button('Close', id='close-chats')

    @on(ListView.Selected, '#chats')
    def selected(self, event):
        if event.item.id:
            self.dismiss(event.item.id.removeprefix('chat-'))

    @on(Button.Pressed, '#close-chats')
    def close_clicked(self):
        self.dismiss(None)


class DetailsScreen(Dialog):
    """Evidence remains accessible without occupying the chat screen."""
    CSS = '''
    #details-dialog { width: 104; height: 35; }
    #answer-choice { margin-bottom: 1; }
    #evidence { height: 1fr; }
    #evidence TabPane { padding: 1 0; }
    #sql { background: #fafaf8; color: #302f2c; border: none; }
    '''

    def __init__(self, store: Store, chat_id: str):
        super().__init__()
        self.store = store
        self.chat_id = chat_id
        history = store.messages(chat_id)
        self.answers = [m for m in history if m['role'] == 'assistant']
        self.labels = {}
        question = 'Answer'
        for message in history:
            if message['role'] == 'user':
                question = message['payload']['answer']
            elif message['role'] == 'assistant':
                self.labels[message['id']] = safe(question).replace('\n', ' ')[:80]

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog', id='details-dialog'):
            yield Label('Answer details', classes='dialog-title')
            yield Select([(Text(self.labels[m['id']]), m['id']) for m in reversed(self.answers)],
                         prompt='Choose an answer', id='answer-choice')
            yield Static('', id='evidence-dataset', classes='dialog-note', markup=False)
            with TabbedContent(id='evidence'):
                with TabPane('Results', id='results-tab'):
                    yield RichLog(id='results', wrap=False, min_width=20, auto_scroll=False)
                with TabPane('SQL', id='sql-tab'):
                    yield TextArea('', read_only=True, id='sql')
                with TabPane('Definitions', id='sources-tab'):
                    yield RichLog(id='sources', wrap=True, min_width=20, auto_scroll=False)
                with TabPane('Columns', id='schema-tab'):
                    yield RichLog(id='schema', wrap=True, min_width=20, auto_scroll=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('Back to chat', id='close-details', classes='solid')

    def on_mount(self):
        self.query_one('#answer-choice', Select).display = len(self.answers) > 1
        if self.answers:
            # Prefer the active dataset; older answers remain explicitly selectable.
            current = self.store.messages(self.chat_id, current_only=True)
            latest = next((m for m in reversed(current) if m['role'] == 'assistant'), self.answers[-1])
            self.query_one('#answer-choice', Select).value = latest['id']
            self.show_answer(latest)

    @on(Select.Changed, '#answer-choice')
    def selected(self, event):
        for message in self.answers:
            if message['id'] == event.value:
                self.show_answer(message)
                break

    def show_answer(self, message):
        dataset_id = message['dataset_id']
        name = self.store.dataset(dataset_id)['name']
        self.query_one('#evidence-dataset', Static).update(f'Data used: {safe(name)}')
        payload = message['payload']
        results = self.query_one('#results', RichLog)
        results.clear()
        queries = payload.get('queries', [])
        for query in queries:
            results.write(result_table(query))
            note = f'{len(query["rows"])} row' + ('' if len(query['rows']) == 1 else 's')
            if query['truncated']:
                note += ' shown · additional rows not displayed'
            results.write(Text(note, style=MUTED))
        if not queries:
            results.write(Text('No query was run for this answer.'))
        self.query_one('#sql', TextArea).load_text('\n\n'.join(q['sql'] for q in queries))
        sources = self.query_one('#sources', RichLog)
        sources.clear()
        for source in payload.get('sources', []):
            sources.write(Text(source['source'], style='bold'))
            sources.write(Text(source['text']))
        schema = self.query_one('#schema', RichLog)
        schema.clear()
        for table, columns in get_schema(self.store.dataset_path(dataset_id)).items():
            schema.write(Text(table, style='bold'))
            for column in columns:
                schema.write(Text(f'  {safe(column["name"])} · {column["type"].lower()}'))

    @on(Button.Pressed, '#close-details')
    def close_clicked(self):
        self.dismiss(None)


class SettingsScreen(Dialog):
    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog', id='settings-menu'):
            yield Label('Settings', classes='dialog-title')
            yield Button('AI connection', id='choose-ai')
            yield Button('Data definitions', id='choose-definitions')
            with Horizontal(classes='dialog-actions'):
                yield Button('Close', id='settings-close')

    @on(Button.Pressed)
    def choose(self, event):
        choices = {'choose-ai': 'ai', 'choose-definitions': 'definitions'}
        self.dismiss(choices.get(event.button.id))


class DefinitionsScreen(Dialog):
    def __init__(self, store: Store, chat_id: str):
        super().__init__()
        self.store = store
        self.chat_id = chat_id
        self.dataset = store.dataset(store.chat(chat_id)['dataset_id'])
        self.editable = self.dataset['kind'] == 'csv'

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog', id='definitions-dialog'):
            yield Label('What does your data mean?', classes='dialog-title')
            yield Static(safe(self.dataset['name']), classes='dialog-note', markup=False)
            if self.editable:
                yield Static('Describe the columns, currency and any calculation rules.\nExample: price is the unit price in AUD; quantity is units sold.', classes='dialog-note')
                text = self.dataset['metadata'].get('confirmed_definitions', '')
            else:
                yield Static('The sample already has reviewed definitions.', classes='dialog-note')
                text = '\n\n'.join(s['text'] for s in search_context(self.store, self.dataset['id'], ''))
            yield TextArea(text, id='definition-text', read_only=not self.editable, soft_wrap=True)
            yield Static('Saved with this dataset. No model call is made.', id='definition-status', classes='dialog-note')
            with Horizontal(classes='dialog-actions'):
                yield Button('Close', id='definitions-close')
                if self.editable:
                    yield Button('Save definitions', id='definitions-save', classes='solid')

    @on(Button.Pressed, '#definitions-save')
    def save(self):
        try:
            revision = self.store.save_definitions(self.chat_id, self.query_one('#definition-text', TextArea).text)
        except ValueError as exc:
            self.query_one('#definition-status', Static).update(str(exc))
            return
        self.dismiss(revision)

    @on(Button.Pressed, '#definitions-close')
    def close_clicked(self):
        self.dismiss(None)


class AISetupScreen(Dialog):
    def __init__(self, config: AIConfig, enabled: bool):
        super().__init__()
        self.config = config
        self.enabled = enabled
        self.checked = None
        self.testing = False

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog', id='ai-dialog'):
            yield Label('Connect AI', classes='dialog-title')
            yield Static('Uses your OpenAI API account and API credits.\nKeys entered here stay in memory for this session.', classes='dialog-note')
            yield Input(password=True, placeholder='API key (leave blank to keep configured key)' if self.config.api_key else 'API key (hidden)', id='api-key')
            yield Input(value=self.config.model, placeholder='API model ID, e.g. gpt-6-luna', id='api-model')
            yield Static('Enter a key and model, then test. The test uses disposable data only.', id='connection-status', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('Close', id='ai-close')
                yield Button('Use demo', id='use-demo')
                yield Button('Test connection', id='test-connection')
                yield Button('Use AI', id='use-ai', classes='solid', disabled=True)

    @on(Input.Changed)
    def changed(self):
        self.checked = None
        self.query_one('#use-ai', Button).disabled = True

    @on(Button.Pressed, '#test-connection')
    def test_clicked(self):
        if self.testing:
            return
        config = AIConfig(self.query_one('#api-key', Input).value.strip() or self.config.api_key,
                          self.query_one('#api-model', Input).value.strip())
        try:
            config.validate()
        except ValueError as exc:
            self.query_one('#connection-status', Static).update(str(exc))
            return
        self.testing = True
        self.checked = None
        self.query_one('#use-ai', Button).disabled = True
        for selector in ('#api-key', '#api-model', '#test-connection', '#use-demo'):
            self.query_one(selector).disabled = True
        self.query_one('#connection-status', Static).update('Checking model access and a SQL tool call…')
        self.test_config(config)

    @work(exclusive=True)
    async def test_config(self, config):
        try:
            report = await check_connection(config)
            self.checked = config if report['ok'] else None
            self.query_one('#connection-status', Static).update(report['message'])
            self.query_one('#use-ai', Button).disabled = not report['ok']
        except Exception:
            self.query_one('#connection-status', Static).update('The connection check could not finish. Please try again.')
        finally:
            self.testing = False
            for selector in ('#api-key', '#api-model', '#test-connection', '#use-demo'):
                self.query_one(selector).disabled = False

    @on(Button.Pressed, '#use-demo')
    def use_demo(self):
        self.dismiss({'enabled': False, 'config': self.config})

    @on(Button.Pressed, '#use-ai')
    def use_ai(self):
        if self.checked is not None:
            config = self.checked
            self.query_one('#api-key', Input).value = ''
            self.dismiss({'enabled': True, 'config': config})

    @on(Button.Pressed, '#ai-close')
    def close_clicked(self):
        self.dismiss(None)


class DataChatApp(App):
    TITLE = 'Ask your data'
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [('ctrl+n', 'new_chat', 'New chat'), ('ctrl+o', 'import_csv', 'Load CSV'),
                ('ctrl+r', 'saved_chats', 'Saved chats'),
                Binding('ctrl+q', 'quit', 'Quit', priority=True)]
    CSS = '''
    Screen { background: #fafaf8; color: #302f2c; align-horizontal: center; }
    Button { background: #eeede8; color: #494741; border: none;
        height: 3; min-width: 10; padding: 0 2; text-style: none; }
    Button:hover { background: #e3e1da; }
    Button:focus { background: #e3e1da; text-style: bold; }
    Button.-active { background: #d6d4ce; color: #302f2c; }
    Button.solid { background: #373631; color: #fafaf8; }
    Button.solid:hover, Button.solid:focus { background: #55534c; }
    Button:disabled { background: #f0efeb; color: #aaa79f; }
    Input { background: #fafaf8; color: #302f2c; border: round #cfccc3; padding: 0 1; }
    Input:focus { border: round #73716c; }
    Input > .input--placeholder { color: #89867e; }
    Input > .input--cursor { background: #494741; color: #fafaf8; }
    RichLog { scrollbar-color: #c9c6bd; scrollbar-background: #fafaf8; }
    ListView, ListItem { background: #fafaf8; color: #302f2c; }
    ListItem { padding: 1; }
    ListView > ListItem.--highlight { background: #eeede8; }
    ListView > ListItem.--highlight Label { color: #302f2c; }
    #page { width: 100%; max-width: 100; height: 100%; padding: 1 3; }
    #topbar { height: 3; }
    #settings-menu { width: 52; height: 16; }
    #settings-menu > Button { width: 100%; margin-bottom: 1; }
    #definitions-dialog { height: 30; }
    #definition-text { height: 1fr; background: #fafaf8; color: #302f2c; border: round #cfccc3; }
    #definition-status { margin-top: 1; margin-bottom: 0; }
    #ai-dialog { height: 25; }
    #ai-dialog .dialog-note { margin-bottom: 0; }
    #connection-status { height: 1fr; padding-top: 1; color: #73716c; }
    #title { width: 1fr; height: 3; content-align: left middle; text-style: bold; }
    #topbar Button { min-width: 10; padding: 0 1; margin-left: 1; background: #fafaf8; color: #73716c; }
    #topbar Button:hover, #topbar Button:focus { background: #eeede8; color: #302f2c; }
    #dataset { height: 2; color: #73716c; }
    #chat-area { height: 1fr; }
    #welcome { height: 1fr; align: center middle; }
    #welcome-title { height: 1; text-align: center; text-style: bold; margin-bottom: 1; }
    #welcome-note { height: 2; text-align: center; color: #73716c; }
    #suggestions { height: auto; width: 100%; }
    #suggestions Button { width: 100%; content-align: center middle; padding: 0 2; background: #fafaf8; color: #55534c; }
    #suggestions Button:hover, #suggestions Button:focus { background: #eeede8; color: #302f2c; }
    #conversation { height: 1fr; background: #fafaf8; color: #302f2c; padding: 1 0; }
    #details-row { height: 3; }
    #details-button { background: #fafaf8; color: #73716c; padding: 0; }
    #details-button:hover, #details-button:focus { color: #302f2c; background: #eeede8; }
    #composer { height: 3; margin-top: 1; }
    #question { width: 1fr; }
    #send { min-width: 10; width: 10; padding: 0 1; margin-left: 1; }
    #bottomline { height: 1; margin-top: 1; }
    #status { width: 1fr; color: #73716c; }
    #hint { width: auto; color: #89867e; }
    .compact #page { padding: 0 2; }
    .compact #composer { margin: 0; }
    .compact #bottomline { margin: 0; }
    .compact #welcome-title { margin: 0; }
    .compact #welcome-note { height: 1; }
    .compact #suggestions Button { height: 2; }
    ''' + Dialog.CSS + DetailsScreen.CSS

    def __init__(self, store: Store | None = None, *, use_ai=False):
        super().__init__()
        self.register_theme(Theme(name='paper', primary='#65625b', secondary='#73716c',
                                  accent='#65625b', foreground=INK, background=PAPER,
                                  surface=PAPER, panel='#eeede8', dark=False,
                                  variables={'footer-key-foreground': MUTED}))
        self.theme = 'paper'
        self.store = store or Store()
        self.sample_id = ensure_sample(self.store)
        chats = self.store.chats()
        self.chat_id = chats[0]['id'] if chats else self.store.new_chat(self.sample_id)
        self.use_ai = use_ai
        self.ai_config = AIConfig.from_env()
        self.busy = False

    def compose(self) -> ComposeResult:
        with Vertical(id='page'):
            with Horizontal(id='topbar'):
                yield Static('Ask your data', id='title')
                yield Button('New chat', id='new-chat')
                yield Button('Saved chats', id='saved-chats')
                yield Button('Load CSV', id='load-csv')
                yield Button('Settings', id='settings')
            yield Static('', id='dataset', markup=False)
            with Vertical(id='chat-area'):
                with Vertical(id='welcome'):
                    yield Static('What would you like to know?', id='welcome-title')
                    yield Static('Start with a question about your data.', id='welcome-note')
                    with Vertical(id='suggestions'):
                        yield Button('What is the total revenue?', id='example-total')
                        yield Button('Which products earned the most?', id='example-products')
                        yield Button('Show monthly revenue', id='example-monthly')
                yield RichLog(id='conversation', wrap=True, markup=False, min_width=20, auto_scroll=True)
            with Horizontal(id='details-row'):
                yield Button('View answer details', id='details-button')
            with Horizontal(id='composer'):
                yield Input(placeholder='Ask a question…', id='question', max_length=4000)
                yield Button('Ask', id='send', classes='solid')
            with Horizontal(id='bottomline'):
                yield Static('', id='status', markup=False)
                yield Static('Enter to send · Ctrl+Q to quit', id='hint')

    def on_mount(self):
        self.restore_chat()
        self.query_one('#question', Input).focus()

    def on_resize(self, event):
        self.screen.set_class(event.size.height < 32, 'compact')

    def restore_chat(self):
        dataset_id = self.store.chat(self.chat_id)['dataset_id']
        dataset = self.store.dataset(dataset_id)
        name = 'Online retail sample · GBP' if dataset['kind'] == 'sample' else safe(dataset['name'])
        mode = 'AI mode' if self.use_ai else 'Demo · example questions only'
        self.query_one('#dataset', Static).update(f'{name}   /   {mode}')
        log = self.query_one('#conversation', RichLog)
        log.clear()
        history = self.store.messages(self.chat_id)
        self.query_one('#welcome').display = not history
        log.display = bool(history)
        self.query_one('#details-row').display = any(m['role'] == 'assistant' for m in history)
        # A previously hidden RichLog has no usable width until layout runs.
        # It retains wrapped lines, so writing now would lock in a narrow column.
        self.call_after_refresh(self.render_history)
        is_sample = dataset['kind'] == 'sample'
        self.query_one('#example-total', Button).label = 'What is the total revenue?' if is_sample else 'Show a few rows'
        self.query_one('#example-products', Button).label = 'Which products earned the most?' if is_sample else 'How many rows are there?'
        self.query_one('#example-monthly').display = is_sample
        self.query_one('#status', Static).update('Saved on this device')

    def render_history(self):
        log = self.query_one('#conversation', RichLog)
        log.clear()
        dataset_id = self.store.chat(self.chat_id)['dataset_id']
        for message in self.store.messages(self.chat_id):
            self.render_message(message, dataset_id)

    def render_message(self, message, active_dataset):
        log = self.query_one('#conversation', RichLog)
        role = {'user': 'You', 'assistant': 'Ask your data', 'system': 'Data updated'}.get(message['role'], 'Note')
        if message['dataset_id'] != active_dataset:
            role += ' · ' + safe(self.store.dataset(message['dataset_id'])['name'])
        log.write(Text(role, style=f'bold {INK}'))
        log.write(Text(safe(message['payload'].get('answer', ''))))
        log.write(Text(''))

    def show_help(self):
        self.query_one('#welcome').display = False
        log = self.query_one('#conversation', RichLog)
        log.display = True
        log.write(Text('Questions to try', style='bold'))
        for question in EXAMPLES:
            log.write(Text('  ' + question))
        log.write(Text('\nFor a CSV: “show data” or “how many rows”.\nCommands: /new · /load · /sample · /sql SELECT …', style=MUTED))

    @on(Button.Pressed, '#settings')
    def settings_clicked(self):
        if not self.busy:
            self.push_screen(SettingsScreen(), self.open_setting)

    def open_setting(self, choice):
        if choice == 'ai':
            self.push_screen(AISetupScreen(self.ai_config, self.use_ai), self.finish_ai_setup)
        elif choice == 'definitions':
            self.push_screen(DefinitionsScreen(self.store, self.chat_id), self.finish_definitions)

    def finish_ai_setup(self, result):
        if result:
            self.use_ai = result['enabled']
            self.ai_config = result['config']
            self.restore_chat()
            self.query_one('#status', Static).update('AI connected for this session' if self.use_ai else 'Demo mode · no API calls')
        self.query_one('#question', Input).focus()

    def finish_definitions(self, revision):
        if revision is not None:
            self.restore_chat()
            self.query_one('#status', Static).update('Data definitions saved')
        self.query_one('#question', Input).focus()

    @on(Button.Pressed, '#details-button')
    def details_clicked(self):
        if not self.busy:
            self.push_screen(DetailsScreen(self.store, self.chat_id))

    @on(Button.Pressed, '#saved-chats')
    def saved_clicked(self):
        self.action_saved_chats()

    def action_saved_chats(self):
        if not self.busy:
            self.push_screen(ChatsScreen(self.store, self.chat_id), self.open_chat)

    def open_chat(self, chat_id):
        if chat_id:
            self.chat_id = chat_id
            self.restore_chat()
        self.query_one('#question', Input).focus()

    @on(Button.Pressed, '#new-chat')
    def new_clicked(self):
        self.action_new_chat()

    def action_new_chat(self):
        if not self.busy:
            self.chat_id = self.store.new_chat(self.sample_id)
            self.restore_chat()
            self.query_one('#question', Input).focus()

    @on(Button.Pressed, '#load-csv')
    def import_clicked(self):
        self.action_import_csv()

    def action_import_csv(self):
        if not self.busy:
            self.push_screen(ImportScreen(), self.finish_import)

    def finish_import(self, inspected):
        if inspected:
            try:
                dataset_id = import_csv(self.store, inspected)
                self.store.activate(self.chat_id, dataset_id)
                self.restore_chat()
                self.query_one('#status', Static).update('File ready. Define columns in Settings.')
            except (ValueError, OSError) as exc:
                self.notify(str(exc), severity='error')
        self.query_one('#question', Input).focus()

    @on(Button.Pressed, '#example-total')
    @on(Button.Pressed, '#example-products')
    @on(Button.Pressed, '#example-monthly')
    def example_clicked(self, event):
        is_sample = self.store.chat(self.chat_id)['dataset_id'] == self.sample_id
        questions = {'example-total': EXAMPLES[0] if is_sample else 'show data',
                     'example-products': EXAMPLES[2] if is_sample else 'how many rows',
                     'example-monthly': EXAMPLES[1]}
        field = self.query_one('#question', Input)
        field.value = questions[event.button.id]
        field.focus()
        field.cursor_position = len(field.value)

    @on(Button.Pressed, '#send')
    def send_clicked(self):
        self.submit_question()

    @on(Input.Submitted, '#question')
    def submitted(self):
        self.submit_question()

    def submit_question(self):
        field = self.query_one('#question', Input)
        question = field.value.strip()
        if not question or self.busy:
            return
        field.value = ''
        if question == '/help':
            self.show_help()
        elif question == '/new':
            self.action_new_chat()
        elif question == '/load':
            self.action_import_csv()
        elif question == '/sample':
            self.store.activate(self.chat_id, self.sample_id)
            self.restore_chat()
        else:
            self.busy = True
            field.disabled = True
            self.query_one('#send', Button).disabled = True
            self.query_one('#status', Static).update('Looking at your data…')
            self.answer_question(question)

    @work(exclusive=True)
    async def answer_question(self, question):
        try:
            await ask(self.store, self.chat_id, question, use_ai=self.use_ai, config=self.ai_config)
            self.restore_chat()
        except Exception:
            self.query_one('#status', Static).update('Something went wrong. Please try again.')
        finally:
            self.busy = False
            self.query_one('#send', Button).disabled = False
            self.query_one('#question', Input).disabled = False
            self.query_one('#question', Input).focus()
