"""Offline regression evaluation. This does not measure live-model accuracy."""
import asyncio
import json
import math
import tempfile
from pathlib import Path

from src.sample import ensure_sample
from src.storage import ROOT, Store
from src.workflow import ask


def equivalent(actual, expected):
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        return isinstance(actual, (float, int)) and math.isclose(actual, expected, abs_tol=0.005, rel_tol=0)
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(equivalent(a, b) for a, b in zip(actual, expected))
    return actual == expected


async def evaluate():
    cases = json.loads((ROOT / 'evaluation' / 'questions.json').read_text())
    if any(case.get('status') != 'verified' for case in cases):
        raise ValueError('Evaluation refuses draft/unverified reference cases.')
    checks = []
    with tempfile.TemporaryDirectory(prefix='ask-your-data-eval-') as folder:
        store = Store(Path(folder))
        dataset = ensure_sample(store)
        for case in cases:
            if case['dataset_version'] != dataset:
                raise ValueError('Reference dataset version mismatch.')
            result = await ask(store, store.new_chat(dataset), case['question'])
            passed = result['status'] == case['expected_behavior']
            if 'expected_rows' in case:
                actual = result['queries'][-1]['rows'] if result['queries'] else None
                passed = passed and equivalent(actual, case['expected_rows'])
            checks.append({'id': case['id'], 'passed': passed})
    report = {'mode': 'offline deterministic regression, not live-model accuracy',
              'dataset_version': dataset, 'total': len(checks),
              'passed': sum(check['passed'] for check in checks), 'checks': checks}
    output = ROOT / 'evaluation' / 'results'
    output.mkdir(exist_ok=True)
    (output / 'offline.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return all(check['passed'] for check in checks)


if __name__ == '__main__':
    raise SystemExit(0 if asyncio.run(evaluate()) else 1)
