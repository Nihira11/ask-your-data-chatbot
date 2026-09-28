import json
from types import SimpleNamespace

import pytest

from src.config import AIConfig, provider_error
from src.connection import check_connection
from src.tools import DatasetTools
from src.workflow import ai_answer


def test_config_hides_secret_and_requires_explicit_model():
    config = AIConfig('secret-test-key', '')
    assert 'secret-test-key' not in repr(config)
    with pytest.raises(ValueError, match='OPENAI_MODEL'):
        config.validate()
    with pytest.raises(ValueError, match='spaces'):
        AIConfig('key', 'bad model').validate()


async def test_missing_config_does_not_call_runner(monkeypatch):
    from agents import Runner
    async def no_call(*args, **kwargs):
        raise AssertionError('Must not make a model call')
    monkeypatch.setattr(Runner, 'run', no_call)
    result = await check_connection(AIConfig())
    assert result['ok'] is False
    assert 'OPENAI_API_KEY' in result['message']


async def test_live_check_path_with_mocked_sdk_tool_roundtrip(monkeypatch):
    from agents import Runner
    from agents.tool_context import ToolContext

    async def fake_run(agent, recent, **kwargs):
        assert agent.model.model == 'configured-model'
        assert agent.model._client.api_key == 'in-memory-test-key'
        current = json.loads(recent[-1]['content'])
        assert current['active_schema'] == {'records': [{'name': 'amount', 'type': 'INTEGER'}]}
        assert current['definitions'][0]['dataset_id'] == 'connection-check'
        tool = next(t for t in agent.tools if t.name == 'run_checked_query')
        args = json.dumps({'sql': 'SELECT SUM(amount) AS total FROM records'})
        context = ToolContext(context=None, tool_name=tool.name, tool_call_id='test', tool_arguments=args)
        result = json.loads(await tool.on_invoke_tool(context, args))
        assert result['rows'] == [[42]]
        return SimpleNamespace(final_output=agent.output_type(status='answer', answer='Total is 42.'),
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace(requests=2, input_tokens=20, output_tokens=10)))

    monkeypatch.setattr(Runner, 'run', fake_run)
    report = await check_connection(AIConfig('in-memory-test-key', 'configured-model'))
    assert report['ok'] is True
    assert report['usage']['requests'] == 2
    assert 'in-memory-test-key' not in json.dumps(report)


async def test_failed_or_skipped_tool_never_reports_connected(monkeypatch):
    async def fake_answer(*args, **kwargs):
        return {'status': 'answer', 'answer': 'It works!'}
    monkeypatch.setattr('src.connection.ai_answer', fake_answer)
    report = await check_connection(AIConfig('test-key', 'test-model'))
    assert report['ok'] is False
    assert 'not verified' in report['message']


async def test_provider_failure_is_actionable_without_secret_body(store, simple_dataset, monkeypatch):
    from agents import Runner
    AuthenticationError = type('AuthenticationError', (Exception,), {})
    async def fail(*args, **kwargs):
        raise AuthenticationError('server body containing private-key-123')
    monkeypatch.setattr(Runner, 'run', fail)
    answer = await ai_answer('sum amount', DatasetTools(store, simple_dataset), [], config=AIConfig('private-key-123', 'test'))
    assert 'not accepted' in answer['answer']
    assert 'private-key-123' not in json.dumps(answer)


async def test_saved_meanings_and_current_question_are_sent_to_model(store, simple_dataset, monkeypatch):
    from agents import Runner
    chat = store.new_chat(simple_dataset)
    store.save_definitions(chat, 'amount is a line total in AUD; do not multiply by quantity.')
    async def fake_run(agent, recent, **kwargs):
        content = json.loads(recent[-1]['content'])
        assert content['question'] == 'What is revenue?'
        assert 'do not multiply' in content['definitions'][-1]['text']
        return SimpleNamespace(final_output=agent.output_type(status='clarify', answer='Which period?'),
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace(requests=1, input_tokens=10, output_tokens=10)))
    monkeypatch.setattr(Runner, 'run', fake_run)
    response = await ai_answer('What is revenue?', DatasetTools(store, simple_dataset), [], config=AIConfig('test', 'test'))
    assert response['status'] == 'clarify'
