"""Opt-in live AI regression runner. Preview is free; --live uses API credits."""
import argparse
import asyncio
import hashlib
import json
import math
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from evaluation.live_cases import FILES, cases_for
from src.config import AIConfig
from src.importer import import_csv, inspect_csv
from src.sample import ensure_sample
from src.storage import ROOT, Store
from src.workflow import ask


def close_number(actual, expected):
    return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isclose(
        actual, expected, abs_tol=0.005000001, rel_tol=0)


def row_matches(actual, expected):
    # Accept extra identifying columns and different column orders, not lost rows.
    remaining = list(actual)
    for value in expected:
        index = next((i for i, item in enumerate(remaining) if (
            close_number(item, value) if isinstance(value, (int, float)) else item == value)), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


def judge(case, response, store, dataset, chat):
    checks = {'real_ai_route': response.get('mode') == 'ai'}
    status, text = response.get('status'), response.get('answer', '')
    behavior = case.get('behavior', 'answer')
    if behavior == 'missing_input':
        checks['declined_missing_input'] = status in {'unable', 'clarify'}
    else:
        checks['status'] = status == behavior
    if 'expected_rows' in case:
        actual_rows = [row for query in response.get('queries', []) for row in query['rows']]
        checks['reference_values_in_query_results'] = all(
            any(row_matches(row, expected) for row in actual_rows) for expected in case['expected_rows'])
    if 'answer_numbers' in case:
        numbers = [float(n.replace(',', '')) for n in re.findall(r'(?<!\w)-?\d[\d,]*(?:\.\d+)?(?!\w)', text)]
        checks['reference_numbers_in_answer'] = all(
            any(close_number(n, expected) for n in numbers) for expected in case['answer_numbers'])
    if 'answer_terms' in case:
        checks['required_terms_in_answer'] = all(
            re.search(r'\b' + re.escape(term) + r'\w*\b', text, re.I) for term in case['answer_terms'])
    if 'pending_column' in case:
        checks['saveable_clarification'] = response.get('pending_definition', {}).get('column') == case['pending_column']
    if 'saved_column' in case:
        definitions = Store(store.home).dataset(dataset)['metadata'].get('confirmed_definitions', '')
        checks['definition_persisted'] = bool(re.search(r'\b' + re.escape(case['saved_column']) + r'\b', definitions, re.I))
    if case.get('saved_notice'):
        checks['definition_notice_visible'] = any(m['payload'].get('answer', '').startswith('Definition saved:')
                                                   for m in store.messages(chat))
    return {name: bool(value) for name, value in checks.items()}


def write_report(path, report, secret):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if secret:
        text = text.replace(secret, '[REDACTED]')
    pending = path.with_suffix('.tmp')
    pending.write_text(text + '\n', encoding='utf-8')
    pending.replace(path)


async def evaluate(cases, config, output, *, max_questions=6, token_limit=30000, seconds_limit=480, ask_fn=ask):
    config.validate()
    selected = cases[:max_questions]
    report = {
        'mode': 'live AI regression; bounded numerical/behavior checks, not general accuracy',
        'started_at': datetime.now(timezone.utc).isoformat(), 'model': config.model,
        'limits': {'max_questions': max_questions, 'reported_token_stop': token_limit,
                   'seconds_stop': seconds_limit, 'automatic_retries': 0},
        'limits_note': 'Token/time stops are checked between questions; an in-flight question may exceed them. '
                       'Each question uses the app limits of eight agent turns, 90 seconds and 2,500 output tokens per model request.',
        'planned_cases': [c['id'] for c in selected], 'checks': [], 'passed': 0,
        'reported_usage': {'requests': 0, 'input_tokens': 0, 'output_tokens': 0},
        'usage_complete': True, 'stop_reason': 'running',
        'dataset_sha256': {suite: hashlib.sha256(FILES[suite].read_bytes()).hexdigest() for suite in {c['suite'] for c in selected}},
        'code_sha256': hashlib.sha256(b''.join(p.name.encode() + p.read_bytes() for p in sorted((ROOT / 'src').glob('*.py')))).hexdigest(),
        'review_note': 'Read answers and SQL for semantic errors. Passing numeric/behavior checks does not certify every claim. '
                       'Usage is reported by the SDK; no dollar cost is inferred.',
    }
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='live-ai-eval-') as directory:
            store = Store(Path(directory))
            datasets, chats = {}, {}
            for case in selected:
                usage = report['reported_usage']
                if usage['input_tokens'] + usage['output_tokens'] >= token_limit:
                    report['stop_reason'] = 'token_stop'; break
                if time.monotonic() - started >= seconds_limit:
                    report['stop_reason'] = 'time_stop'; break
                suite = case['suite']
                if suite not in datasets:
                    datasets[suite] = ensure_sample(store) if suite == 'retail' else import_csv(store, inspect_csv(FILES[suite]))
                    chats[suite] = store.new_chat(datasets[suite])
                if case.get('new_chat'):
                    store = Store(store.home)
                    chats[suite] = store.new_chat(datasets[suite])
                entry = {'id': case['id'], 'question': case['question'], 'expected': case, 'state': 'running'}
                report['checks'].append(entry)
                write_report(output, report, config.api_key)
                print(f'[{len(report["checks"])}/{len(selected)}] {case["id"]} ...', flush=True)
                turn_started = time.monotonic()
                response = await ask_fn(store, chats[suite], case['question'], use_ai=True, config=config)
                checks = judge(case, response, store, datasets[suite], chats[suite])
                entry.update(state='complete', seconds=round(time.monotonic() - turn_started, 2),
                             passed=all(checks.values()), criteria=checks, response=response)
                report['passed'] += int(entry['passed'])
                print(f'  {"PASS" if entry["passed"] else "FAIL"} ({entry["seconds"]}s)' +
                      ('' if entry['passed'] else ' — ' + ', '.join(k for k, v in checks.items() if not v)), flush=True)
                turn_usage = response.get('usage')
                if not isinstance(turn_usage, dict) or any(not isinstance(turn_usage.get(k), int) for k in usage):
                    report.update(usage_complete=False, stop_reason='usage_unavailable')
                else:
                    for key in usage:
                        usage[key] += turn_usage[key]
                    if turn_usage['requests'] < 1:
                        report.update(usage_complete=False, stop_reason='no_live_request_verified')
                write_report(output, report, config.api_key)
                if report['stop_reason'] != 'running':
                    break
                if not entry['passed']:
                    report['stop_reason'] = 'failed_check'; break
            else:
                report['stop_reason'] = 'completed' if len(selected) == len(cases) else 'question_limit'
    except BaseException as exc:
        report['stop_reason'] = 'interrupted' if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)) else 'runner_error'
        report['error_type'] = type(exc).__name__  # Never serialize raw exception bodies/keys.
        raise
    finally:
        report['seconds'] = round(time.monotonic() - started, 2)
        write_report(output, report, config.api_key)
    return report


def positive(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('Must be positive.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly make paid API calls; otherwise preview only')
    parser.add_argument('--suite', choices=['tips', 'retail', 'supermarket', 'all'], default='tips')
    parser.add_argument('--max-questions', type=positive, default=6)
    parser.add_argument('--token-stop', type=positive, default=30000, help='Stop starting questions after this many reported tokens')
    parser.add_argument('--seconds-stop', type=positive, default=480)
    parser.add_argument('--model', help='Override the saved/configured model')
    args = parser.parse_args()
    cases = cases_for(args.suite)
    if not args.live:
        print(json.dumps({'mode': 'preview only; no API calls', 'cases': cases[:args.max_questions]}, indent=2))
        return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    env = AIConfig.from_env()
    config = AIConfig(env.api_key, args.model or Store().ai_preferences()['model'] or env.model)
    try:
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))
    filename = datetime.now(timezone.utc).strftime('live-%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8] + '.json'
    output = ROOT / 'evaluation/results' / filename
    report = asyncio.run(evaluate(cases, config, output, max_questions=args.max_questions,
                                  token_limit=args.token_stop, seconds_limit=args.seconds_stop))
    print(json.dumps({'passed': report['passed'], 'attempted': len(report['checks']),
                      'stop_reason': report['stop_reason'], 'reported_usage': report['reported_usage'],
                      'usage_complete': report['usage_complete'], 'report': str(output)}, indent=2))
    return 0 if report['stop_reason'] in {'completed', 'question_limit'} and all(c.get('passed') for c in report['checks']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
