"""Render answer Markdown locally, preserving data text and line breaks."""
from markdown_it import MarkdownIt
from rich.markdown import Markdown
from textual.widgets import Static


def answer_markdown(text: str) -> Markdown:
    rendered = Markdown(text, code_theme='github-light', style='#302f2c', hyperlinks=False)
    # HTML in a dataset or answer is text, never executable or silently hidden.
    rendered.parsed = MarkdownIt('commonmark', {'html': False}).enable('table').enable('strikethrough').parse(text)
    pending = list(rendered.parsed)
    while pending:
        token = pending.pop()
        if token.type == 'softbreak':
            token.type = 'hardbreak'
        pending.extend(token.children or [])
    return rendered


class AnswerText(Static):
    """Keep the saved answer verbatim; formatting affects only its presentation."""

    def render(self):
        return answer_markdown(str(self.content))
