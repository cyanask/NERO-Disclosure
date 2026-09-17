"""V1 domain checks on task-owned public rule snapshots and synthetic scenarios."""
import copy
from pathlib import Path
import pytest
from backend.domain import Seeds, evaluate
from backend.workflow import new_event
from conftest import KNOWLEDGE

SEEDS=Seeds(KNOWLEDGE)
SCENARIOS=SEEDS.scenarios()


@pytest.mark.parametrize('sample', SCENARIOS, ids=[s['id'] for s in SCENARIOS])
def test_reviewed_scenario_expectation(sample):
    event=new_event(sample,{'actor':'synthetic-fixture','channel':'test'})
    result=evaluate(event,SEEDS)
    assert result['status']==sample['expected']['status']
    assert result['mode']=='rules_only'
    assert result['approved'] is False
    assert result['citations']
    assert set(sample['expected']['source_ids']) <= {s['id'] for s in SEEDS.for_event(event).knowledge()}


def test_market_requires_explicit_board_not_company_name():
    actor={'actor':'fixture','channel':'test'}
    for company in ('创业板公司','基础层公司'):
        event=new_event({'company_name':company,'board':'chinext','kind':'unclassified',
                         'title':'模拟事项','summary':'隔离测试','facts':{}},actor)
        assert event['layer']=='chinext'
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        new_event({'company_name':'创业板公司','board':'innovation','kind':'unclassified',
                   'title':'模拟事项','summary':'隔离测试','facts':{}},actor)
