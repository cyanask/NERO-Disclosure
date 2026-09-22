"""Public API regressions for the local, identity-free Verify/Gate contract."""
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
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


def test_successful_advance_evaluates_once_and_replay_keeps_one_receipt(gate_env,monkeypatch):
    from test_agent_tasks import candidate, claimed, submit
    c,agent,_=gate_env;e=sample(c)
    task,lease=claimed(c,e,agent)
    assert submit(c,e,task,lease,agent,candidate()).status_code==200
    assert command(c,e,f"agent-tasks/{task['id']}/adopt").status_code==200
    current=c.get('/api/events/'+e['id']).json()
    payload={'expected_revision':current['revision'],'stage':'assessment','request_id':str(uuid4())}
    evaluations=[];advances=[]
    original_evaluate=__import__('backend.api_gates',fromlist=['gates']).gates.evaluate
    original_advance=__import__('backend.api_gates',fromlist=['gates']).gates.advance

    def counted_evaluate(*args,**kwargs):
        receipt=original_evaluate(*args,**kwargs);evaluations.append(receipt);return receipt

    def counted_advance(*args,**kwargs):
        advances.append(args[2]);return original_advance(*args,**kwargs)

    monkeypatch.setattr('backend.api_gates.gates.evaluate',counted_evaluate)
    monkeypatch.setattr('backend.api_gates.gates.advance',counted_advance)
    url='/api/events/'+e['id']+'/advance'
    first=c.post(url,json=payload);second=c.post(url,json=payload)
    assert first.status_code==second.status_code==200
    assert len(evaluations)==1 and len(advances)==1 and advances==['assessment']
    assert first.json()==second.json()
    saved=first.json();assert saved['verification']==saved['verified_stages']['assessment']
    assert sum(row['action']=='advance' for row in saved['audit'])==1


def test_pending_review_advance_is_recorded_as_blocked(gate_env,monkeypatch):
    c,_,_=gate_env;e=sample(c);url='/api/events/'+e['id']+'/advance'
    pending={'status':'PENDING_REVIEW','stage':'assessment','input_fingerprint':'0'*64,
             'issues':[],'warnings':[],'semantic_review':[{'item_id':'fact:amount'}],
             'next_action':{'action':'semantic_review'}}
    monkeypatch.setattr('backend.api_gates.gates.evaluate',lambda *args,**kwargs:pending)
    body={'expected_revision':e['revision'],'stage':'assessment','request_id':str(uuid4())}
    response=c.post(url,json=body)
    assert response.status_code==409 and response.json()['detail']['gate']['status']=='PENDING_REVIEW'
    saved=c.get('/api/events/'+e['id']).json()
    assert saved['verification']==pending
    assert saved['stage']=='intake'
    assert sum(row['action']=='advance_blocked' for row in saved['audit'])==1
    assert saved['repair_attempts']


def test_advance_rejects_stale_revision_and_forged_pass_field(gate_env):
    c,_,_=gate_env;e=sample(c);url='/api/events/'+e['id']+'/advance'
    stale={'expected_revision':e['revision'],'stage':'assessment','request_id':str(uuid4())}
    changed=c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'summary':'模拟版本变化'}).json()
    assert c.post(url,json=stale).status_code==409
    forged={'expected_revision':changed['revision'],'stage':'assessment','request_id':str(uuid4()),'status':'PASS'}
    assert c.post(url,json=forged).status_code==422


def test_non_gate_409_from_advance_propagates_and_rolls_back(gate_env,monkeypatch):
    c,_,_=gate_env;e=sample(c);before=c.get('/api/events/'+e['id']).json()
    def reject(*args,**kwargs):
        raise HTTPException(409,'模拟非 Gate 冲突')
    monkeypatch.setattr('backend.api_gates.gates.advance',reject)
    response=c.post('/api/events/'+e['id']+'/advance',json={
        'expected_revision':before['revision'],'stage':'assessment','request_id':str(uuid4())})
    assert response.status_code==409 and response.json()['detail']=='模拟非 Gate 冲突'
    saved=c.get('/api/events/'+e['id']).json()
    assert saved['revision']==before['revision']
    assert not any(row['action']=='advance_blocked' for row in saved['audit'])
    assert 'verification' not in saved and 'repair_attempts' not in saved


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
