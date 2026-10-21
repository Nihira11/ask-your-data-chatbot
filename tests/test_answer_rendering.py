from io import StringIO

from rich.console import Console
from textual.widgets import Input, Static

from src.answer_rendering import AnswerText, answer_markdown
from src.tui import DataChatApp


def rendered(text, width=64):
    stream = StringIO()
    Console(file=stream, width=width, color_system=None).print(answer_markdown(text))
    return stream.getvalue()


def test_markdown_formats_numbers_tables_and_preserves_plain_line_breaks():
    result = rendered('Revenue: **£117,058.55**; column `total_bill`.\n\n'
                      '| Product line | Total |\n|---|---:|\n| Food | 17163.1005 |\n\n'
                      'Monday: 10\nTuesday: 20\n\n```sql\nSELECT total_bill FROM records\n```')
    assert '**' not in result and '`' not in result and '|---' not in result
    assert '£117,058.55' in result and 'total_bill' in result and '17163.1005' in result
    assert result.index('Monday: 10') < result.index('Tuesday: 20')
    assert all(not ('Monday' in line and 'Tuesday' in line) for line in result.splitlines())
    assert 'SELECT total_bill FROM records' in result


def test_html_rich_markup_and_identifiers_are_literal():
    result = rendered('<script>alert(1)</script>\n\n[red]not Rich markup[/red]\n\n'
                      'total_bill and 2 * 3 = 6.\n\n[reference](https://example.com)', width=100)
    assert '<script>alert(1)</script>' in result
    assert '[red]not Rich markup[/red]' in result
    assert 'total_bill' in result and '2 * 3 = 6' in result
    assert 'https://example.com' in result
    assert '\x1b' not in result


async def test_saved_answers_render_in_small_terminal_without_changing_history(store):
    app = DataChatApp(store)
    question = 'Keep **my literal input**'
    answer = '**Total:** 42\n\n| Item | Value |\n|---|---:|\n| Pen | 42 |'
    store.append(app.chat_id, app.sample_id, 'user', {'answer': question})
    store.append(app.chat_id, app.sample_id, 'assistant', {'answer': answer})
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        widget = app.query_one(AnswerText)
        assert str(widget.content) == answer
        assert widget.region.height > 3
        assert app.query_one('#question', Input).region.bottom <= 24
        assert any(str(w.content) == question and not isinstance(w, AnswerText)
                   for w in app.query('#conversation Static'))
        assert store.messages(app.chat_id)[-1]['payload']['answer'] == answer
