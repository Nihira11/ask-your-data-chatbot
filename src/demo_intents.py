"""Recognize a bounded set of demo phrasings without discarding filters."""
import re


SAMPLE_PATTERNS = {
    'what is the total revenue': (
        r'(?:total|overall|net)(?: net)? (?:revenue|sales)',
    ),
    'show monthly revenue': (
        r'monthly (?:net )?(?:revenue|sales)',
        r'(?:net )?(?:revenue|sales) (?:by|per|each) month',
    ),
    'show revenue by country': (
        r'(?:net )?(?:revenue|sales) (?:by|per|for each) country',
        r'country (?:revenue|sales)',
    ),
    'which five products generated the most revenue': (
        r'top (?:5|five) products (?:by|ranked by) (?:net )?(?:revenue|sales)',
        r'which (?:5|five) products (?:generated|earned) the most (?:revenue|sales)',
        r'which products earned the most',
    ),
    'how many orders are there': (
        r'(?:total )?(?:number|count) of (?:orders|invoices)',
        r'(?:order|invoice) count',
        r'total (?:orders|invoices)',
        r'how many (?:orders|invoices)(?: are there| do we have)?',
    ),
}
CSV_PATTERNS = {
    'describe my data': (r'(?:describe|summarize) (?:my |this |the )?(?:data|dataset|file|csv)', r'(?:data|dataset|file|csv) (?:summary|overview)'),
    'show columns': (r'(?:my )?columns', r'column (?:names|types)', r'which columns(?: are there)?'),
    'show missing values': (r'(?:missing values|empty cells|blank cells)(?: by column)?', r'how many (?:missing values|empty cells)(?: are there)?'),
    'show data': (r'(?:data|preview|preview data|first rows|(?:a )?few rows)',),
    'how many rows': (r'how many rows(?: are there)?', r'(?:number|count) of rows', r'row count', r'total rows'),
}


def demo_question(question: str, kind: str) -> str:
    normalized = ' '.join(question.lower().replace('’', "'").split()).rstrip('?.!').strip()
    normalized = re.sub(r"^what's\b", 'what is', normalized)
    phrase = re.sub(r'^please\s+', '', normalized)
    phrase = re.sub(r',?\s+please$', '', phrase)
    phrase = re.sub(r'^(?:(?:can|could|would) you )?(?:show(?: me)?|give me|tell me|list|calculate)\s+', '', phrase)
    phrase = re.sub(r'^what (?:is|are)\s+', '', phrase)
    phrase = re.sub(r'^the\s+', '', phrase)
    patterns = SAMPLE_PATTERNS if kind == 'sample' else CSV_PATTERNS
    for canonical, alternatives in patterns.items():
        if normalized == canonical or any(re.fullmatch(pattern, phrase) for pattern in alternatives):
            return canonical
    # Full matches are intentional: never drop dates, exclusions or ranking sizes.
    return normalized
