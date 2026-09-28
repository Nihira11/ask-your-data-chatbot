import json
from types import SimpleNamespace

import pytest

from src.tools import DatasetTools
from src.workflow import ai_answer, ask


async def test_offline_roundtrip_saved(store, simple_dataset):
    chat = store.new_chat(simple_dataset)
    answer = await ask(store, chat, 'how many rows')
    assert answer['queries'][0]['rows'] == [[3]]
    assert len(store.messages(chat)) == 2
    assert answer['mode'] == 'offline'
    assert '25' not in (await ask(store, chat, 'What is revenue?'))['answer']


async def test_refusal_clarification_and_empty(store, simple_dataset):
    chat = store.new_chat(simple_dataset)
    assert (await ask(store, chat, 'Delete all records'))['status'] == 'unable'
    assert (await ask(store, chat, 'Which performed best?'))['status'] == 'clarify'
    answer = await ask(store, chat, '/sql SELECT * FROM records WHERE amount > 100')
    assert answer['answer'] == 'No matching rows were found.'


def test_three_attempt_budget(store, simple_dataset):
    tools = DatasetTools(store, simple_dataset)
    for _ in range(3):
        assert 'error' in tools.run_checked_query('DROP TABLE records')
    assert 'budget' in tools.run_checked_query('SELECT * FROM records')['error']
    assert tools.results == []


async def test_ai_requires_configuration_without_network(store, simple_dataset, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    result = await ai_answer('hello', DatasetTools(store, simple_dataset), [])
    assert result['status'] == 'unable'
    assert 'OPENAI_API_KEY' in result['answer']


async def test_sdk_tool_roundtrip_with_fake_runner(store, simple_dataset, monkeypatch):
    from agents import Runner
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test-not-a-real-key')
    monkeypatch.setenv('OPENAI_MODEL', 'unit-test-model')
    tools = DatasetTools(store, simple_dataset)

    async def fake_run(agent, recent, **kwargs):
        assert kwargs['max_turns'] == 8
        assert kwargs['run_config'].tracing_disabled
        registered = {tool.name: tool for tool in agent.tools}
        assert set(registered) == {'get_schema', 'search_context', 'run_checked_query'}
        from agents.tool_context import ToolContext
        context = ToolContext(context=None, tool_name='get_schema', tool_call_id='test', tool_arguments='{}')
        schema = json.loads(await registered['get_schema'].on_invoke_tool(context, '{}'))
        assert 'records' in schema
        result = json.loads(await registered['run_checked_query'].on_invoke_tool(context, '{"sql":"SELECT SUM(amount) FROM records"}'))
        assert result['rows'] == [[25.0]]
        return SimpleNamespace(final_output=agent.output_type(status='answer', answer='The sum is 25.'), context_wrapper=SimpleNamespace(usage=SimpleNamespace(requests=1, input_tokens=10, output_tokens=10)))

    monkeypatch.setattr(Runner, 'run', fake_run)
    result = await ai_answer('sum amount', tools, [])
    assert result['status'] == 'answer'
    assert len(tools.results) == 1


async def test_no_model_answer_without_current_evidence(store, simple_dataset, monkeypatch):
    from agents import Runner
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test')
    monkeypatch.setenv('OPENAI_MODEL', 'unit-test')

    async def fake_run(agent, *args, **kwargs):
        return SimpleNamespace(final_output=agent.output_type(status='answer', answer='Revenue is 999.'), context_wrapper=SimpleNamespace(usage=SimpleNamespace(requests=1, input_tokens=1, output_tokens=1)))

    monkeypatch.setattr(Runner, 'run', fake_run)
    result = await ai_answer('revenue', DatasetTools(store, simple_dataset), [])
    assert result['status'] == 'unable'
    assert '999' not in result['answer']
