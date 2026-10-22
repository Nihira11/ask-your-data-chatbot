"""A quiet, chat-first terminal interface; supporting details open on demand."""
from __future__ import annotations

import asyncio
from pathlib import Path

from rich import box
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Input, Label, ListItem, ListView, RichLog, Static, TabbedContent, TabPane, TextArea

from src.config import AIConfig
from src.answer_rendering import AnswerText
from src.export import export_chat_results
from src.file_picker import choose_csv_file, choose_export_folder
from src.formatting import format_gbp
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


def result_table(query, *, sample=False):
    table = Table(box=box.SIMPLE, show_header=True, header_style=f'bold {INK}',
                  border_style='#d6d4ce', padding=(0, 1), expand=False)
    if query.get('display') == 'empty_cells_by_column':
        table.add_column('Column', max_width=36, overflow='fold')
        table.add_column('Empty cells', justify='right')
        for column, count in zip(query['columns'][1:], query['rows'][0][1:]):
            table.add_row(Text(safe(column.removeprefix('empty_cells__'))), Text(str(count)))
        return table
    for column in query['columns']:
        table.add_column(Text(safe(column)), overflow='fold', max_width=36,
                         justify='right' if sample and column == 'revenue_gbp' else 'left')
    for row in query['rows']:
        cells = []
        for column, value in zip(query['columns'], row):
            if sample and column == 'revenue_gbp' and isinstance(value, (int, float)):
                cells.append(Text(format_gbp(value)))
            else:
                cells.append(Text('—' if value is None else safe(value)))
        table.add_row(*cells)
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
            yield Button('Choose CSV file…', id='choose-csv', classes='solid')
            yield Static('No file selected', id='csv-name', classes='dialog-note', markup=False)
            yield RichLog(id='import-preview', wrap=True, min_width=20)
            with Horizontal(classes='dialog-actions'):
                yield Button('Cancel', id='cancel')
                yield Button('Use this file', id='confirm', classes='solid', disabled=True)

    @on(Button.Pressed, '#choose-csv')
    @work(exclusive=True)
    async def browse(self):
        button = self.query_one('#choose-csv', Button)
        confirm = self.query_one('#confirm', Button)
        button.disabled = True
        confirm.disabled = True
        try:
            path = await choose_csv_file()
            await self.file_chosen(path)
        except RuntimeError as exc:
            self.notify(str(exc), severity='error')
        finally:
            button.disabled = False
            confirm.disabled = self.inspected is None

    async def file_chosen(self, path):
        if path is None:
            return
        self.inspected = None
        self.query_one('#confirm', Button).disabled = True
        self.query_one('#csv-name', Static).update(safe(path.name))
        log = self.query_one('#import-preview', RichLog)
        log.clear()
        try:
            self.inspected = await asyncio.to_thread(inspect_csv, path)
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
    def __init__(self, store: Store, active: str, drafts=None):
        super().__init__()
        self.store = store
        self.active = active
        self.drafts = drafts or {}

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog'):
            yield Label('Your chats', classes='dialog-title')
            yield Static('Choose a conversation to pick up where you left off.', classes='dialog-note')
            entries = []
            for chat in self.store.chats():
                messages = self.store.messages(chat['id'])
                dataset = self.store.dataset(chat['dataset_id'])
                draft = self.drafts.get(chat['id'], '')
                if not messages and not draft.strip() and dataset['kind'] == 'sample':
                    continue
                question = next((m['payload']['answer'] for m in messages if m['role'] == 'user'),
                                f'Draft: {draft}' if draft.strip() else 'New conversation')
                entries.append((chat['id'], question, dataset['name']))
            if not entries:
                yield Static('No saved chats yet. Send a question to start one.', classes='dialog-note')
            with ListView(id='chats'):
                for chat_id, question, name in entries:
                    label = safe(question).replace('\n', ' ')[:60]
                    yield ListItem(Label(f'{label}\n{safe(name)}', markup=False), id='chat-' + chat_id)
            with Horizontal(classes='dialog-actions'):
                yield Button('Close', id='close-chats')

    @on(ListView.Selected, '#chats')
    def selected(self, event):
        if event.item.id:
            self.dismiss(event.item.id.removeprefix('chat-'))

    @on(Button.Pressed, '#close-chats')
    def close_clicked(self):
        self.dismiss(None)


class ExportConfirmScreen(Dialog):
    """Choose a destination first, then explicitly save or cancel."""

    def __init__(self, destination: Path, count: int):
        super().__init__()
        self.destination = destination
        self.count = count

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog'):
            yield Label('Save chat results?', classes='dialog-title')
            yield Static(f'{self.count} result CSV files, plus an index and query details.\n'
                         'A new folder will be created here:', classes='dialog-note')
            yield Static(safe(self.destination), markup=False)
            yield Static('Nothing is saved until you select Save results.', classes='dialog-note')
            with Horizontal(classes='dialog-actions'):
                yield Button('Cancel', id='cancel-export')
                yield Button('Save results', id='confirm-export', classes='solid')

    @on(Button.Pressed, '#cancel-export')
    def cancel(self):
        self.dismiss(False)

    @on(Button.Pressed, '#confirm-export')
    def save(self):
        self.dismiss(True)


class ExportScreen(Dialog):
    def __init__(self, folder: Path, count: int, truncated: bool):
        super().__init__()
        self.folder, self.count, self.truncated = folder, count, truncated

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog', id='export-dialog'):
            yield Label('Results saved', classes='dialog-title')
            note = f'Saved {self.count} result CSV file' + ('' if self.count == 1 else 's') + ', index.csv and query details.'
            if self.truncated:
                note += '\nSome results were limited. Only their saved rows were exported.'
            yield Static(note, classes='dialog-note')
            yield Static('Folder path (select and copy):', classes='dialog-note')
            yield TextArea(str(self.folder), read_only=True, id='export-path')
            with Horizontal(classes='dialog-actions'):
                yield Button('Back to chat', id='close-export', classes='solid')

    @on(Button.Pressed, '#close-export')
    def close_clicked(self):
        self.dismiss(None)


class DetailsScreen(Dialog):
    """Evidence remains accessible without occupying the chat screen."""
    CSS = '''
    #details-dialog { width: 104; height: 35; }
    #answer-question { height: auto; max-height: 4; margin-bottom: 1; }
    #evidence { height: 1fr; }
    #evidence TabPane { padding: 1 0; }
    #sql { background: #fafaf8; color: #302f2c; border: none; }
    #export-dialog { height: 21; }
    #export-path { height: 1fr; background: #fafaf8; color: #302f2c; border: round #cfccc3; }
    '''

    def __init__(self, store: Store, chat_id: str, answer_id: int):
        super().__init__()
        self.store = store
        self.chat_id = chat_id
        history = store.messages(chat_id)
        self.selected_answer = next(m for m in history if m['id'] == answer_id
                                    and m['role'] == 'assistant' and m['payload'].get('queries'))
        self.question = 'Answer'
        for message in history:
            if message['id'] == answer_id:
                break
            if message['role'] == 'user':
                self.question = message['payload']['answer']

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog', id='details-dialog'):
            yield Label('Answer details', classes='dialog-title')
            yield Static(safe(self.question), id='answer-question', markup=False)
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
        self.show_answer(self.selected_answer)

    def show_answer(self, message):
        self.selected_answer = message
        dataset_id = message['dataset_id']
        dataset = self.store.dataset(dataset_id)
        name = dataset['name']
        self.query_one('#evidence-dataset', Static).update(f'Data used: {safe(name)}')
        payload = message['payload']
        results = self.query_one('#results', RichLog)
        results.clear()
        queries = payload.get('queries', [])
        for query in queries:
            if query.get('display') == 'empty_cells_by_column':
                results.write(Text(f'{query["rows"][0][0]:,} dataset rows checked · empty cells by column', style=f'bold {INK}'))
                results.write(Text('0 means no empty cells. These are not sums of the column values.', style=MUTED))
            results.write(result_table(query, sample=dataset['kind'] == 'sample'))
            if query.get('display') == 'empty_cells_by_column':
                continue
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
            yield Static('Mode and model are remembered. Use AI when ready; Test connection is optional.\nTo keep your key after restarting, configure OPENAI_API_KEY in your local .env.', id='connection-status', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('Close', id='ai-close')
                yield Button('Use demo', id='use-demo')
                yield Button('Test connection', id='test-connection')
                yield Button('Use AI', id='use-ai', classes='solid', disabled=True)

    @on(Input.Changed)
    def changed(self):
        if self.checked is not None:
            self.query_one('#connection-status', Static).update(
                'Configuration changed. Use AI when ready, or run the optional connection test.')
        self.checked = None
        self.refresh_use_ai()

    def on_mount(self):
        self.refresh_use_ai()

    def entered_config(self):
        return AIConfig(self.query_one('#api-key', Input).value.strip() or self.config.api_key,
                        self.query_one('#api-model', Input).value.strip())

    def refresh_use_ai(self):
        try:
            self.entered_config().validate()
            valid = True
        except ValueError:
            valid = False
        self.query_one('#use-ai', Button).disabled = self.testing or not valid

    @on(Button.Pressed, '#test-connection')
    def test_clicked(self):
        if self.testing:
            return
        config = self.entered_config()
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
            self.refresh_use_ai()

    @on(Button.Pressed, '#use-demo')
    def use_demo(self):
        self.dismiss({'enabled': False, 'config': self.config})

    @on(Button.Pressed, '#use-ai')
    def use_ai(self):
        if self.testing:
            return
        config = self.entered_config()
        try:
            config.validate()
        except ValueError as exc:
            self.query_one('#connection-status', Static).update(str(exc))
            return
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
    #choose-csv { margin-bottom: 1; }
    #welcome { height: 1fr; align: center middle; }
    #welcome-title { height: 1; text-align: center; text-style: bold; margin-bottom: 1; }
    #welcome-note { height: 2; text-align: center; color: #73716c; }
    #suggestions { height: auto; width: 100%; }
    #suggestions Button { width: 100%; content-align: center middle; padding: 0 2; background: #fafaf8; color: #55534c; }
    #suggestions Button:hover, #suggestions Button:focus { background: #eeede8; color: #302f2c; }
    #conversation { height: 1fr; background: #fafaf8; color: #302f2c; padding: 1 0; }
    .chat-message { height: auto; width: 1fr; margin-bottom: 1; }
    .chat-message Static { height: auto; width: 1fr; }
    .answer-results { height: 1; min-width: 0; width: auto; padding: 0; margin-top: 1;
        background: #fafaf8; color: #73716c; }
    .answer-results:hover, .answer-results:focus { color: #302f2c; background: #eeede8; }
    #export-chat { height: 1; min-width: 0; width: auto; padding: 0; margin-top: 1;
        background: #fafaf8; color: #73716c; }
    #export-chat:hover, #export-chat:focus { color: #302f2c; background: #eeede8; }
    #composer { height: 3; margin-top: 1; }
    #mode-label { height: 1; color: #302f2c; text-style: bold; }
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

    def __init__(self, store: Store | None = None, *, use_ai=None):
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
        preferences = self.store.ai_preferences()
        configured = AIConfig.from_env()
        self.ai_config = AIConfig(configured.api_key, preferences['model'] or configured.model)
        self.use_ai = preferences['enabled'] if use_ai is None else use_ai
        self.startup_notice = ''
        if use_ai is None and self.use_ai:
            try:
                self.ai_config.validate()
            except ValueError:
                self.use_ai = False
                self.startup_notice = 'AI setup needed: configure your key/model in Settings → AI connection.'
        self.busy = False
        self.closing = False
        self.exporting = False
        self.pending_history = None
        self.pending_label = ''
        self.response_error = None
        self.drafts = {}

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
                yield VerticalScroll(id='conversation')
            yield Button('Export chat results', id='export-chat')
            yield Static('', id='mode-label', markup=False)
            with Horizontal(id='composer'):
                yield Input(placeholder='Ask a question…', id='question', max_length=4000)
                yield Button('Ask', id='send', classes='solid')
            with Horizontal(id='bottomline'):
                yield Static('', id='status', markup=False)
                yield Static('/help · Enter to send · Ctrl+Q to quit', id='hint')

    def on_mount(self):
        self.restore_chat()
        if self.startup_notice:
            self.query_one('#status', Static).update(self.startup_notice)
        self.query_one('#question', Input).focus()

    def on_resize(self, event):
        self.screen.set_class(event.size.height < 32, 'compact')

    def restore_chat(self, *, scroll_to_end=False):
        if self.closing:
            return
        dataset_id = self.store.chat(self.chat_id)['dataset_id']
        dataset = self.store.dataset(dataset_id)
        name = 'Online retail sample · GBP' if dataset['kind'] == 'sample' else safe(dataset['name'])
        self.query_one('#dataset', Static).update(name)
        mode = 'AI mode · uses paid API credits' if self.use_ai else 'Demo mode · no API charges'
        self.query_one('#mode-label', Static).update(mode)
        log = self.query_one('#conversation', VerticalScroll)
        history = self.pending_history if self.pending_history is not None else self.store.messages(self.chat_id)
        export_button = self.query_one('#export-chat', Button)
        export_button.display = any(m['role'] == 'assistant' and m['payload'].get('queries') for m in history)
        export_button.disabled = self.busy or self.exporting
        self.query_one('#welcome').display = not history
        log.display = bool(history)
        self.call_after_refresh(self.render_history, scroll_to_end)
        is_sample = dataset['kind'] == 'sample'
        self.query_one('#example-total', Button).label = 'What is the total revenue?' if is_sample else 'Describe my data'
        self.query_one('#example-products', Button).label = 'Which products earned the most?' if is_sample else 'Show columns'
        self.query_one('#example-monthly', Button).label = 'Show monthly revenue' if is_sample else 'Show missing values'
        self.query_one('#status', Static).update('You can draft your next question.' if self.busy else 'Saved on this device')
        self.query_one('#hint', Static).update('Wait for reply to send · Ctrl+Q to quit' if self.busy else '/help · Enter to send · Ctrl+Q to quit')

    async def render_history(self, scroll_to_end=False):
        if self.closing:
            return
        log = self.query_one('#conversation', VerticalScroll)
        dataset_id = self.store.chat(self.chat_id)['dataset_id']
        history = self.pending_history if self.pending_history is not None else self.store.messages(self.chat_id)
        widgets = [self.message_widget(message, dataset_id) for message in history]
        if self.busy:
            widgets.append(Vertical(Static(Text('Ask your data', style=f'bold {INK}')),
                                    Static(Text(self.pending_label, style=MUTED)), classes='chat-message'))
        elif self.response_error and self.response_error[0] == self.chat_id:
            widgets.append(Vertical(Static(Text('Ask your data', style=f'bold {INK}')),
                                    Static(self.response_error[1], markup=False), classes='chat-message'))
        await log.remove_children()
        if widgets:
            await log.mount_all(widgets)
        if scroll_to_end:
            log.scroll_end(animate=False)
        else:
            log.scroll_home(animate=False)

    def message_widget(self, message, active_dataset):
        role = {'user': 'You', 'assistant': 'Ask your data', 'system': 'Data updated'}.get(message['role'], 'Note')
        if message['role'] == 'system' and 'definitions_revision' in message['payload']:
            role = 'Definitions'
        if message['dataset_id'] != active_dataset:
            role += ' · ' + safe(self.store.dataset(message['dataset_id'])['name'])
        body = AnswerText if message['role'] == 'assistant' else Static
        widgets = [Static(Text(role, style=f'bold {INK}')),
                   body(safe(message['payload'].get('answer', '')), markup=False)]
        if message['role'] == 'assistant' and message['payload'].get('queries'):
            widgets.append(Button('View results', id=f'results-{message["id"]}', classes='answer-results'))
        return Vertical(*widgets, classes='chat-message')

    def show_help(self):
        self.query_one('#welcome').display = False
        self.query_one('#conversation').display = True
        self.call_after_refresh(self.render_help)

    async def render_help(self):
        if self.closing:
            return
        log = self.query_one('#conversation', VerticalScroll)
        is_sample = self.store.chat(self.chat_id)['dataset_id'] == self.sample_id
        questions = EXAMPLES if is_sample else ['Describe my data', 'Show columns', 'Show missing values', 'Show data', 'How many rows are there?']
        text = Text('Questions to try\n', style='bold')
        text.append('\n'.join('  ' + question for question in questions), style=INK)
        if is_sample:
            text.append('\n\nCommon wording works too: “total sales”, “revenue per month”,\n“top 5 products by revenue”, “sales by country”, “number of orders”.', style=MUTED)
        text.append('\n\nCommands: /new · /load · /sample · /sql SELECT …', style=MUTED)
        await log.mount(Vertical(Static(text), classes='chat-message'))
        log.scroll_end(animate=False)

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
            self.store.save_ai_preferences(enabled=self.use_ai, model=self.ai_config.model)
            self.restore_chat()
            self.query_one('#status', Static).update('AI mode selected · mode and model saved' if self.use_ai else 'Demo mode saved · no API calls')
        self.query_one('#question', Input).focus()

    def finish_definitions(self, revision):
        if revision is not None:
            self.restore_chat()
            self.query_one('#status', Static).update('Data definitions saved')
        self.query_one('#question', Input).focus()

    @on(Button.Pressed, '.answer-results')
    def details_clicked(self, event):
        if not self.busy:
            answer_id = int(event.button.id.removeprefix('results-'))
            self.push_screen(DetailsScreen(self.store, self.chat_id, answer_id))

    @on(Button.Pressed, '#export-chat')
    @work
    async def save_chat_results(self):
        if self.busy or self.exporting:
            return
        self.exporting = True
        button = self.query_one('#export-chat', Button)
        button.disabled = True
        # Snapshot before opening Finder: later turns cannot change this export.
        chat_id = self.chat_id
        history = self.store.messages(chat_id)
        queries = [query for m in history if m['role'] == 'assistant'
                   for query in m['payload'].get('queries', [])]
        try:
            if not queries:
                return
            datasets = {m['dataset_id']: self.store.dataset(m['dataset_id'])['name']
                        for m in history if m['role'] == 'assistant' and m['payload'].get('queries')}
            destination = await choose_export_folder(self.store.home / 'exports')
            if destination is None:
                self.notify('Export cancelled. Nothing was saved.')
                return
            if not await self.push_screen_wait(ExportConfirmScreen(destination, len(queries))):
                self.notify('Export cancelled. Nothing was saved.')
                return
            folder = await asyncio.to_thread(export_chat_results, destination, chat_id, history, datasets)
            self.push_screen(ExportScreen(folder, len(queries), any(q['truncated'] for q in queries)))
        except (OSError, ValueError, RuntimeError):
            self.notify('Could not save the results. Please try again and choose a writable folder.', severity='error')
        finally:
            self.exporting = False
            if not self.closing:
                button.disabled = self.busy
                if not isinstance(self.screen, ExportScreen):
                    self.query_one('#question', Input).focus()

    @on(Button.Pressed, '#saved-chats')
    def saved_clicked(self):
        self.action_saved_chats()

    def action_saved_chats(self):
        if not self.busy:
            drafts = {**self.drafts, self.chat_id: self.query_one('#question', Input).value}
            self.push_screen(ChatsScreen(self.store, self.chat_id, drafts), self.open_chat)

    def leave_chat(self):
        draft = self.query_one('#question', Input).value
        if draft.strip():
            self.drafts[self.chat_id] = draft
        else:
            self.drafts.pop(self.chat_id, None)
            self.store.discard_empty_chat(self.chat_id)

    def open_chat(self, chat_id):
        if chat_id and chat_id != self.chat_id:
            self.store.chat(chat_id)
            self.leave_chat()
            self.chat_id = chat_id
            self.query_one('#question', Input).value = self.drafts.get(chat_id, '')
            self.restore_chat()
        self.query_one('#question', Input).focus()

    @on(Button.Pressed, '#new-chat')
    def new_clicked(self):
        self.action_new_chat()

    def action_new_chat(self):
        if not self.busy:
            self.leave_chat()
            self.chat_id = self.store.new_chat(self.sample_id)
            self.query_one('#question', Input).value = ''
            self.restore_chat()
            self.query_one('#question', Input).focus()

    async def action_quit(self):
        # Layout callbacks may still run after the unused chat has been deleted.
        self.closing = True
        if not self.busy:
            self.leave_chat()
        await super().action_quit()

    @on(Button.Pressed, '#load-csv')
    def import_clicked(self):
        self.action_import_csv()

    def action_import_csv(self):
        if not self.busy:
            self.push_screen(ImportScreen(), self.finish_import)

    def finish_import(self, inspected):
        if inspected and not self.busy:
            self.busy = True
            self.pending_label = 'Importing CSV…'
            self.query_one('#send', Button).disabled = True
            self.restore_chat()
            self.query_one('#status', Static).update('Importing CSV… You can draft your next question.')
            self.import_dataset(inspected, self.chat_id)
        self.query_one('#question', Input).focus()

    @work(group='import', exclusive=True)
    async def import_dataset(self, inspected, chat_id):
        ready = False
        try:
            dataset_id = await asyncio.to_thread(import_csv, self.store, inspected)
            self.store.activate(chat_id, dataset_id)
            ready = True
        except (ValueError, OSError) as exc:
            self.notify(str(exc), severity='error')
        finally:
            self.busy = False
            self.pending_label = ''
            if not self.closing:
                self.restore_chat()
                self.query_one('#send', Button).disabled = False
                if ready:
                    self.query_one('#status', Static).update('File ready. Try “describe my data”.')
                self.query_one('#question', Input).focus()

    @on(Button.Pressed, '#example-total')
    @on(Button.Pressed, '#example-products')
    @on(Button.Pressed, '#example-monthly')
    def example_clicked(self, event):
        is_sample = self.store.chat(self.chat_id)['dataset_id'] == self.sample_id
        questions = {'example-total': EXAMPLES[0] if is_sample else 'Describe my data',
                     'example-products': EXAMPLES[2] if is_sample else 'Show columns',
                     'example-monthly': EXAMPLES[1] if is_sample else 'Show missing values'}
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
        self.drafts.pop(self.chat_id, None)
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
            self.response_error = None
            dataset_id = self.store.chat(self.chat_id)['dataset_id']
            # Show the submitted turn immediately; ask() remains the sole writer
            # of saved messages. The snapshot prevents duplicate user messages.
            self.pending_history = self.store.messages(self.chat_id) + [
                {'role': 'user', 'dataset_id': dataset_id, 'payload': {'answer': question}}
            ]
            self.pending_label = 'Thinking…' if self.use_ai and not question.lower().startswith('/sql ') else 'Checking your data…'
            self.query_one('#send', Button).disabled = True
            self.restore_chat(scroll_to_end=True)
            field.focus()
            self.answer_question(question)

    @work(exclusive=True)
    async def answer_question(self, question):
        try:
            await ask(self.store, self.chat_id, question, use_ai=self.use_ai, config=self.ai_config)
        except Exception:
            self.response_error = (self.chat_id, 'Could not finish this answer. Please try again. Your next draft is still in the question box.')
        finally:
            self.busy = False
            self.pending_history = None
            self.pending_label = ''
            if not self.closing:
                self.restore_chat(scroll_to_end=True)
                self.query_one('#send', Button).disabled = False
                self.query_one('#question', Input).focus()
