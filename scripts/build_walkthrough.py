"""Build the screenshot-led project walkthrough: pip install reportlab."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/ask-your-data-walkthrough.pdf'
WIDTH, HEIGHT = 1120, 840
PAPER = '#F7F5EF'
INK = '#272F2C'
MUTED = '#596660'
ACCENT = '#116B61'
LINE = '#D9DED6'


PAGES = [
    {
        'section': 'PRODUCT OVERVIEW',
        'title': 'Ask your data.\nSee the evidence.',
        'intro': 'A local terminal app for exploring CSV data through questions, follow-ups and inspectable SQL.',
        'points': [
            ('Start free', 'Use the bundled retail demo without an API key.'),
            ('Bring a CSV', 'Import your own data, then use AI for broader questions.'),
            ('Check the answer', 'Open the saved query results and SQL for each reply.'),
        ],
        'image': '04-ai-formatted-answer.png',
        'caption': 'Imported supermarket data: a formatted AI answer with its branch filter stated explicitly.',
        'note': 'Python / Textual / SQLite / SQLGlot / OpenAI Agents SDK',
    },
    {
        'section': '01 / IMPORT',
        'title': 'Know what\nyou imported.',
        'intro': 'Review a file before making it the active dataset. The original CSV stays unchanged.',
        'points': [
            ('Preview before use', 'See the row count, inferred column types and empty-cell counts.'),
            ('Keep identifiers intact', 'Leading-zero identifiers remain text. Dates remain text; blank cells become NULL.'),
            ('Bounded input', 'UTF-8 CSV; up to 5 MB, 50,000 rows and 100 columns.'),
        ],
        'image': '03-csv-import-preview.png',
        'caption': 'tips.csv: 244 rows and seven columns. The native macOS chooser is not shown in this capture.',
        'note': 'One active dataset per chat. A local snapshot is stored for later use.',
    },
    {
        'section': '02 / RESULTS',
        'title': 'Every answer\nhas its evidence.',
        'intro': 'A View results button belongs to the answer immediately above it, including follow-up answers.',
        'points': [
            ('Saved rows', 'Inspect the exact values returned by the query, alongside the dataset name.'),
            ('Separate evidence', 'Results, SQL, Definitions and Columns are available in the detail view.'),
            ('No empty controls', 'Clarification-only replies do not receive a results button.'),
        ],
        'image': '06-answer-results.png',
        'caption': 'Six product-line totals for branch A. The viewer shows saved evidence rather than rerunning the query.',
        'note': 'Query results are bounded to at most 100 returned rows.',
    },
    {
        'section': '03 / SQL',
        'title': 'Inspect how\nit was calculated.',
        'intro': 'Move from a natural-language answer to the actual SQL used to calculate it.',
        'points': [
            ('Understand the scope', 'Read the selected columns, filter, grouping and aggregation.'),
            ('Read-only execution', 'SQL validation and SQLite read-only access constrain queries. Time and output limits also apply.'),
            ('Review interpretation', 'A query can run successfully and still misunderstand a question. The evidence makes that review possible.'),
        ],
        'image': '07-answer-sql.png',
        'caption': 'The same branch-A answer: SUM(Total), grouped by Product line, with the executed filter visible.',
        'note': 'Explicit /sql commands run locally in either Demo or AI mode.',
    },
    {
        'section': '04 / FOLLOW-UPS',
        'title': 'Refine the\nsame question.',
        'intro': 'AI mode can retain earlier filters as you narrow an analysis across several messages.',
        'points': [
            ('Dinner', 'Total tip 546.07 across 176 rows.'),
            ('Then Sunday', 'Retaining Dinner: total tip 247.39 across 76 rows.'),
            ('Then non-smokers', 'Retaining both filters: total tip 180.57 across 57 rows.'),
        ],
        'image': '08-follow-up-filters.png',
        'caption': 'Verified tips.csv sequence. Sunday is stored as Sun; no currency has been assumed for tip.',
        'note': 'These are tested examples, not a guarantee for every possible follow-up.',
    },
    {
        'section': '05 / SAVED MEANINGS',
        'title': 'Clarify once.\nReuse the meaning.',
        'intro': 'A clear confirmation of a proposed column meaning becomes a saved dataset definition.',
        'points': [
            ('Visible confirmation', 'The chat displays a Definition saved notice so the change is explicit.'),
            ('Persistent context', 'The meaning survives new chats and restarts, and is reused for an exact re-upload.'),
            ('Editable definitions', 'Review or change meanings in Settings. Definitions remain local to this installation.'),
        ],
        'image': '09-clarification-saved.png',
        'caption': 'Confirmed size meaning: party size 6 has the highest average tip, 5.225, based on four rows.',
        'note': 'Filters and qualified confirmations are not saved as general definitions.',
    },
    {
        'section': '06 / WORKING IN CHAT',
        'title': 'Keep your place\nwhile it thinks.',
        'intro': 'Submitting a question immediately shows it in the conversation, with a waiting indicator below.',
        'points': [
            ('Draft the next question', 'The input stays editable while the reply is being prepared.'),
            ('Prevent double sends', 'Ask and Enter cannot submit a second question until the first finishes.'),
            ('Keep the draft', 'A reply, error or cancelled export does not discard the next question or send it automatically.'),
        ],
        'image': '05-thinking-and-draft.png',
        'caption': 'Actual waiting-state UI captured with a controlled delay. No live API request was made for this image.',
        'note': 'Saved chats can be reopened; unsent drafts persist during chat switching in the same session.',
    },
    {
        'section': '07 / EXPORT',
        'title': 'Take the\nresults with you.',
        'intro': 'Export all saved query results in a chat to a destination you choose on your computer.',
        'points': [
            ('One CSV per query', 'Different result shapes and follow-ups remain separate. Clarification-only replies are skipped.'),
            ('Keep the context', 'index.csv maps files to questions and datasets. details.json includes SQL and truncation information.'),
            ('Confirm or cancel', 'Nothing is written before Save results. Cancel preserves the draft.'),
        ],
        'image': '10-export-confirmation.png',
        'caption': 'Three result CSVs plus an index and query details. This is the app confirmation after destination selection.',
        'note': 'Exports use saved rows only. They do not rerun SQL or make another model call.',
    },
    {
        'section': '08 / GET STARTED',
        'title': 'Demo first.\nYour AI account next.',
        'intro': 'A fresh installation opens in Demo mode. Broader natural-language analysis uses your own API account.',
        'points': [
            ('Bring your own key', 'The repository includes no API credential. AI calls use your account and credits.'),
            ('Optional connection test', 'Enter your key and model, then Use AI. Test connection checks disposable data and is optional.'),
            ('Restart without setup', 'Mode and model are remembered. Configure the key in a local .env to restore AI mode after restarting.'),
        ],
        'image': '12-connect-your-own-ai.png',
        'caption': 'Unconfigured AI settings. Keys entered here are kept in session memory; this capture contains no credential.',
        'note': 'AI sends questions, limited context, schema, definitions, category values and query results to OpenAI.',
    },
]


def paragraph(c, text, x, top, width, size=15, color=INK, bold=False, leading=None):
    style = ParagraphStyle('body', fontName='Helvetica-Bold' if bold else 'Helvetica',
                           fontSize=size, leading=leading or size * 1.38,
                           textColor=colors.HexColor(color), spaceAfter=0)
    flow = Paragraph(escape(text).replace('\n', '<br/>'), style)
    _, height = flow.wrap(width, HEIGHT)
    assert top - height >= 25, f'Text outside page: {text}'
    flow.drawOn(c, x, top - height)
    return top - height


def frame(c, page, section):
    c.setFillColor(colors.HexColor(PAPER))
    c.rect(0, 0, WIDTH, HEIGHT, stroke=0, fill=1)
    paragraph(c, 'ASK YOUR DATA', 40, 806, 250, 13, ACCENT, True)
    paragraph(c, section, 320, 806, 700, 11, MUTED, True)
    c.setStrokeColor(colors.HexColor(LINE))
    c.line(40, 778, 1080, 778)
    c.line(40, 55, 1080, 55)
    paragraph(c, 'PRODUCT WALKTHROUGH  /  21 OCTOBER 2026', 40, 39, 700, 9, MUTED)
    c.setFont('Helvetica', 10)
    c.setFillColor(colors.HexColor(MUTED))
    c.drawRightString(1080, 27, f'{page:02d} / 10')


def feature_page(c, page, entry):
    frame(c, page, entry['section'])
    bookmark = f'page-{page}'
    c.bookmarkPage(bookmark)
    c.addOutlineEntry(entry['title'].replace('\n', ' '), bookmark, level=0)
    y = paragraph(c, entry['title'], 40, 735, 250, 30, INK, True, 35) - 22
    y = paragraph(c, entry['intro'], 40, y, 250, 15, MUTED) - 28
    for title, body in entry['points']:
        y = paragraph(c, title, 40, y, 250, 14, ACCENT, True) - 7
        y = paragraph(c, body, 40, y, 250, 13, INK) - 24
    note_bottom = paragraph(c, entry['note'], 40, y - 2, 250, 11, MUTED)
    assert note_bottom > 65
    image = ImageReader(str(ROOT / 'screenshots' / entry['image']))
    iw, ih = image.getSize()
    width = 760
    height = width * ih / iw
    top = 750
    c.drawImage(image, 320, top - height, width=width, height=height, mask='auto')
    paragraph(c, entry['caption'], 320, top - height - 13, width, 11, MUTED)
    c.showPage()


def verification_page(c):
    frame(c, 10, 'VERIFICATION / SCOPE / NEXT STEPS')
    c.bookmarkPage('verification')
    c.addOutlineEntry('Verification and scope', 'verification', level=0)
    paragraph(c, 'What has been checked', 40, 746, 1040, 33, INK, True)
    paragraph(c, 'Completed development checks, with the remaining limits made explicit.', 40, 691, 1040, 17, MUTED)
    for x, number, title, body in [
        (40, '153', 'AUTOMATED TESTS PASSED', 'Fresh Python 3.12 environment; local logic, SDK mocks and headless UI.'),
        (395, '31 / 31', 'OFFLINE CHECKS PASSED', '12 retail cases and 19 tips checks, including independent CSV/Decimal references.'),
        (750, '12 / 12', 'LIVE AI CASES PASSED', '6 tips, 3 retail and 3 supermarket cases; answers and SQL reviewed.'),
    ]:
        c.setFillColor(colors.HexColor('#E6EEE7'))
        c.roundRect(x, 475, 330, 169, 10, stroke=0, fill=1)
        paragraph(c, number, x + 19, 627, 292, 32, ACCENT, True)
        paragraph(c, title, x + 19, 581, 292, 11, ACCENT, True)
        paragraph(c, body, x + 19, 554, 292, 13, INK)

    left = 433
    left = paragraph(c, 'What these results mean', 40, left, 490, 18, INK, True) - 13
    left = paragraph(c, 'The live suites used gpt-6-luna and covered totals, follow-up filters, saved definitions and refusing unsupported profit calculations. One rejected table-name attempt was repaired before its final answer. The user also confirmed that the native macOS file picker opens correctly.', 40, left, 490, 14) - 18
    left = paragraph(c, 'These are small development regressions, not a broad accuracy benchmark. A valid SQL query is not proof of a correct business interpretation. Review the evidence for important conclusions.', 40, left, 490, 14) - 22
    left = paragraph(c, 'Future improvements', 40, left, 490, 16, ACCENT, True) - 10
    paragraph(c, 'Extend this completed milestone with Windows/Linux file dialogs, more held-out questions and messy-data fixtures, optional charts, and model comparisons for quality, latency and token usage.', 40, left, 490, 13, MUTED)

    right = 433
    right = paragraph(c, 'Try it or review the source', 590, right, 490, 18, INK, True) - 13
    right = paragraph(c, 'See README.md for setup and evaluation commands; screenshots/ for all 12 full-resolution images; docs/architecture.md for implementation boundaries.', 590, right, 490, 14) - 18
    right = paragraph(c, 'After creating a virtual environment:', 590, right, 490, 13, MUTED) - 8
    c.setFillColor(colors.HexColor('#E6EEE7'))
    c.roundRect(590, right - 65, 490, 65, 6, stroke=0, fill=1)
    c.setFont('Courier', 12)
    c.setFillColor(colors.HexColor(INK))
    c.drawString(605, right - 24, 'python -m pip install -r requirements.txt')
    c.drawString(605, right - 46, 'python app.py')
    right -= 88
    right = paragraph(c, 'Capture and data provenance', 590, right, 490, 16, ACCENT, True) - 10
    paragraph(c, 'Screens come from the actual Textual renderer. AI examples replay verified live answers with their SQL rechecked locally; the loading state uses a controlled delay. The retail sample is from Daqing Chen (2015), UCI Online Retail, CC BY 4.0. Other examples use the supplied tips and supermarket CSV fixtures.', 590, right, 490, 13, MUTED)
    c.linkURL('https://doi.org/10.24432/C5BW33', (590, 67, 1080, 86), relative=0)
    paragraph(c, 'Retail source: doi.org/10.24432/C5BW33', 590, 83, 490, 10, ACCENT)
    c.showPage()


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT), pagesize=(WIDTH, HEIGHT), pageCompression=1)
    c.setTitle('Ask Your Data - Product Walkthrough')
    c.setAuthor('Ask Your Data')
    c.setSubject('A screenshot-led tour of CSV analysis, inspectable SQL, saved definitions and exports.')
    for index, entry in enumerate(PAGES, 1):
        feature_page(c, index, entry)
    verification_page(c)
    c.save()
    print(OUTPUT)


if __name__ == '__main__':
    main()
