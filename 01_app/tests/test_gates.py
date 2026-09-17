"""Public API regressions for the local, identity-free Verify/Gate contract."""
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from internal_workflow import CALLERS,install_callers,route as internal_route

ROOT = Path(__file__).resolve().parents[1]
from conftest import seed_project, seed_tree

@pytest.fixture
def gate_env(tmp_path,monkeypatch):
    install_callers(monkeypatch)
    seed_project(tmp_path)
    app = create_app(tmp_path/'var', tmp_path, {'allowed_hosts':['testserver']},legacy_test_mode=True)
    with TestClient(app) as client:
        session = client.get('/api/session').json()
        client.headers.update({'Origin':'http://testserver', 'X-CSRF-Token':session['csrf_token']})
        token = CALLERS[0]
        yield client, token, tmp_path

def sample(c):
    r=c.post('/api/scenarios/chinext-board-01/import',json={'request_id':str(uuid4())})
    assert r.status_code==200,r.text
    return r.json()

def command(c,e,op,**args):
    e=c.get('/api/events/'+e['id']).json()
    
    from test_agent_tasks import post
    return post(c,e,op,**args)

def test_no_login_or_human_approval(gate_env):
    c,_,_=gate_env
    assert 'authenticated' not in c.get('/api/session').json()
    assert c.post('/api/session',json={'password':'anything'}).status_code==410
    e=sample(c)
    assert command(c,e,'approve',stage='assessment',decision='accept').status_code==410

def test_expired_law_blocks_every_entry(gate_env):
    c,agent,_=gate_env;e=sample(c)
    facts={**e['facts'],'event_date':'2024-01-01'}
    e=c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':facts}).json()
    check=c.get('/api/events/'+e['id']+'/verify',params={'stage':'assessment'}).json()
    assert check['status']=='BLOCKED'
    assert 'law_out_of_period' in {i['code'] for i in check['issues']}
    assert check['next_action']['action']=='review_law_library'
    assert command(c,e,'advance',stage='assessment').status_code==409
    assert command(c,e,'plan').status_code in (409,410)
    r=internal_route(c,agent,{'operation':'gate.advance','args':{'event_id':e['id'],'stage':'assessment','expected_revision':e['revision'],'request_id':str(uuid4())}})
    assert r.status_code==409

def test_missing_law_has_external_search_and_stop_feedback(gate_env):
    c,agent,root=gate_env;e=sample(c)
    p=root/'data/public/boards/chinext/catalog.json';cat=json.loads(p.read_text())
    # Remove a source the board-resolution rules bind, so the missing-law path is exercised.
    cat['sources']=[s for s in cat['sources'] if s['id']!='szse-chinext-2026-5.1.1']
    p.write_text(json.dumps(cat))
    gate=c.get('/api/events/'+e['id']+'/verify',params={'stage':'assessment'}).json()
    assert gate['status']=='BLOCKED' and gate['next_action']['action']=='search_official_web'
    r=command(c,e,'source-search',input_fingerprint=gate['input_fingerprint'],status='not_found',queries=['创业板上市规则 4.1.7 官方原文'],urls=[],message='已检索官方来源，未取得适用版本。')
    assert r.status_code==200,r.text
    stopped=c.get('/api/events/'+e['id']+'/verify',params={'stage':'assessment'}).json()
    assert stopped['next_action']['action']=='notify_user_stop'
    assert command(c,e,'advance',stage='assessment').status_code==409

def test_search_route_matches_direct_pagination(gate_env):
    c,agent,_=gate_env
    direct=c.get('/api/library/search',params={'board':'chinext','collection':'laws','q':'公司','offset':5,'limit':2}).json()
    routed=internal_route(c,agent,{'operation':'library.search','args':{'board':'chinext','collection':'laws','query':'公司','offset':5,'limit':2}}).json()['data']
    assert routed==direct
    cases=c.get('/api/library/search',params={'board':'chinext','collection':'cases','kind':'shareholder_notice','view':'candidates'}).json()
    assert any(x.get('document_path') for x in cases['items'])
    grouped=c.get('/api/library/search',params={'board':'chinext','collection':'cases','view':'groups'}).json()
    assert grouped['view']=='groups' and grouped['items'][0]['id'].startswith('category-case-')


def test_missing_original_and_freshness_fail_closed(gate_env):
    c,_,root=gate_env;e=sample(c)
    path=root/'data/public/boards/chinext/catalog.json';cat=json.loads(path.read_text())
    row=next(x for x in cat['sources'] if x['id']=='szse-chinext-2026-5.1.1')
    row['original_path']='data/public/originals/nonexistent.pdf';row['sha256']='0'*64
    path.write_text(json.dumps(cat))
    gate=c.get('/api/events/'+e['id']+'/verify').json()
    assert 'law_integrity' in {i['code'] for i in gate['issues']}
    e=c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':{**e['facts'],'event_date':'2026-09-09'}}).json()
    gate=c.get('/api/events/'+e['id']+'/verify').json()
    # A review date older than the assessment date is a maintenance note, not a
    # blocker: the law library owns refreshing it.
    assert 'law_review_due' in {w['code'] for w in gate['warnings']}


def test_blocked_advance_is_audited_and_retry_keeps_status(gate_env):
    c,_,_=gate_env;e=sample(c);url='/api/events/'+e['id']+'/advance'
    body={'expected_revision':e['revision'],'stage':'assessment','request_id':str(uuid4())}
    first=c.post(url,json=body);second=c.post(url,json=body)
    assert first.status_code==second.status_code==409 and first.json()==second.json()
    event=c.get('/api/events/'+e['id']).json()
    assert sum(a['action']=='advance_blocked' for a in event['audit'])==1
    assert event['stage']=='intake' and event['verification']['status']=='BLOCKED'


def test_host_no_disclosure_cannot_downgrade_out_of_period_rule(gate_env):
    from test_agent_tasks import claimed,submit,candidate
    c,token,_=gate_env;e=sample(c)
    e=c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':{**e['facts'],'event_date':'2024-01-01'}}).json()
    task,lease=claimed(c,e,token)
    assert submit(c,e,task,lease,token,{**candidate(),'status':'no_disclosure'}).status_code==200
    r=command(c,e,f"agent-tasks/{task['id']}/adopt")
    assert r.status_code==409
    assert 'law_out_of_period' in {i['code'] for i in r.json()['detail']['gate']['issues']}
    fresh=c.get('/api/events/'+e['id']).json()
    assert fresh['assessment'] is None and fresh['stage']!='closed'
    assert fresh['agent_tasks'][-1]['status']=='submitted'
