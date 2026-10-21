import json

import pytest

from evaluation.evaluate_live import evaluate, judge, row_matches
from evaluation.live_cases import cases_for
from src.config import AIConfig


def test_references_are_independent_and_cover_reported_failures():
    cases = cases_for('tips')
    assert cases[0]['expected_rows'] == [[546.07, 176]]
    assert cases[1]['expected_rows'] == [[247.39, 76]]
    assert cases[2]['expected_rows'] == [[180.57, 57]]
    assert cases[4]['expected_rows'] == [[6, 5.225, 4]]
    assert cases[5]['new_chat']
    assert cases_for('retail')[0]['expected_rows'] == [[117058.55]]
    assert cases_for('supermarket')[0]['expected_rows'] == [['C', 110568.7065]]


def test_judge_checks_prose_as_well_as_query_values(store, simple_dataset):
    case = cases_for('tips')[1]
    response = {'mode': 'ai', 'status': 'answer', 'answer': '0 rows and no tip.',
                'queries': [{'rows': [[247.39, 76]]}]}
    result = judge(case, response, store, simple_dataset, store.new_chat(simple_dataset))
    assert result['reference_values_in_query_results']
    assert not result['reference_numbers_in_answer']
    assert row_matches(['Sun', 76, 247.39], [247.39, 76])
    assert not row_matches([76], [76, 76])


@pytest.mark.parametrize('limit,token_stop,fail,usage_missing,expected_calls,reason', [
    (2, 30000, False, False, 2, 'question_limit'),
    (6, 10, False, False, 1, 'token_stop'),
    (6, 30000, True, False, 1, 'failed_check'),
    (6, 30000, False, True, 1, 'usage_unavailable'),
])
async def test_live_runner_limits_reports_and_never_retries(tmp_path, limit, token_stop, fail, usage_missing, expected_calls, reason):
    cases = cases_for('tips')
    calls = []
    config = AIConfig('never-save-this-secret', 'test-model')
    async def fake_ask(store, chat, question, **kwargs):
        assert kwargs == {'use_ai': True, 'config': config}
        assert store.home.name.startswith('live-ai-eval-')
        index = len(calls)
        calls.append(question)
        expected = cases[index]['expected_rows'][0]
        return {'status': 'answer', 'mode': 'ai',
                'answer': ('Wrong ' if fail else ', '.join(map(str, expected))) + ' never-save-this-secret',
                'queries': [{'rows': [expected]}],
                **({} if usage_missing else {'usage': {'requests': 2, 'input_tokens': 10, 'output_tokens': 10}})}
    path = tmp_path / 'report.json'
    report = await evaluate(cases, config, path, max_questions=limit, token_limit=token_stop, ask_fn=fake_ask)
    assert len(calls) == expected_calls
    assert report['stop_reason'] == reason
    assert 'never-save-this-secret' not in path.read_text()
    assert '[REDACTED]' in path.read_text()
    saved = json.loads(path.read_text())
    assert saved['model'] == 'test-model'
    assert len(saved['checks']) == expected_calls
    assert saved['usage_complete'] is not usage_missing


def test_preview_never_enters_live_runner(monkeypatch, capsys):
    import evaluation.evaluate_live as runner
    def no_live(*args, **kwargs):
        raise AssertionError('Preview must not run evaluation')
    monkeypatch.setattr(runner, 'evaluate', no_live)
    monkeypatch.setattr('sys.argv', ['evaluate_live', '--suite', 'tips', '--max-questions', '2'])
    assert runner.main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert len(preview['cases']) == 2
    assert preview['mode'] == 'preview only; no API calls'
