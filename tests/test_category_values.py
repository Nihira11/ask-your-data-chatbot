import json
from types import SimpleNamespace

import pytest

from src.config import AIConfig
from src.importer import import_csv, inspect_csv
from src.storage import ROOT
from src.tools import DatasetTools
from src.workflow import ai_answer


@pytest.fixture
def tips_tools(store):
    dataset = import_csv(store, inspect_csv(ROOT / 'data/sample/tips.csv'))
    tools = DatasetTools(store, dataset)
    tools.check_categories = True
    return tools


def test_category_mismatch_requires_repair_and_preserves_filters(tips_tools):
    values = tips_tools.category_values()
    assert 'Sun' in values['day']
    assert 'Sunday' not in values['day']
    sql = "SELECT SUM(tip), COUNT(*) FROM records WHERE time='Dinner' AND day='Sunday' AND smoker='No'"
    failed = tips_tools.run_checked_query(sql)
    assert "stores 'Sun', not 'Sunday'" in failed['error']
    assert not tips_tools.results
    repaired = tips_tools.run_checked_query(sql.replace("'Sunday'", "'Sun'"))
    assert repaired['rows'][0][0] == pytest.approx(180.57)
    assert repaired['rows'][0][1] == 57
    assert tips_tools.attempts == 2
    assert len(tips_tools.results) == 1


def test_true_empty_filter_and_explicit_sql_are_not_rewritten(tips_tools):
    result = tips_tools.run_checked_query("SELECT * FROM records WHERE day='Mon'")
    assert result['rows'] == []
    tips_tools.check_categories = False
    sql = "SELECT COUNT(*) FROM records WHERE day='Sunday'"
    result = tips_tools.run_checked_query(sql)
    assert result['rows'] == [[0]]
    assert result['sql'] == sql


async def test_sdk_receives_actual_values_and_can_repair_sunday(tips_tools, monkeypatch):
    from agents import Runner
    from agents.tool_context import ToolContext

    async def fake_run(agent, recent, **kwargs):
        current = json.loads(recent[-1]['content'])
        assert 'Sun' in current['category_values']['day']
        tool = next(t for t in agent.tools if t.name == 'run_checked_query')
        sql = "SELECT SUM(tip), COUNT(*) FROM records WHERE time='Dinner' AND day='Sunday'"
        async def query(statement):
            args = json.dumps({'sql': statement})
            context = ToolContext(context=None, tool_name=tool.name, tool_call_id='test', tool_arguments=args)
            return json.loads(await tool.on_invoke_tool(context, args))
        assert 'Category mismatch' in (await query(sql))['error']
        result = await query(sql.replace("'Sunday'", "'Sun'"))
        assert result['rows'][0][0] == pytest.approx(247.39)
        assert result['rows'][0][1] == 76
        return SimpleNamespace(
            final_output=agent.output_type(status='answer', answer='Dinner on Sunday: 247.39 across 76 rows.'),
            context_wrapper=SimpleNamespace(usage=SimpleNamespace(requests=2, input_tokens=10, output_tokens=10)))
    monkeypatch.setattr(Runner, 'run', fake_run)
    result = await ai_answer('Now only Sunday, keeping Dinner', tips_tools, [], config=AIConfig('test', 'test'))
    assert result['status'] == 'answer'
    assert len(tips_tools.results) == 1


def test_high_cardinality_text_is_not_presented_as_complete_categories(store, tmp_path):
    path = tmp_path / 'many.csv'
    path.write_text('label\n' + '\n'.join(f'item-{i}' for i in range(30)))
    tools = DatasetTools(store, import_csv(store, inspect_csv(path)))
    assert tools.category_values() == {}
