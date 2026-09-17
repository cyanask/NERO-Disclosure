"""Real HTTP retirement checks plus the unchanged private Pi execution path."""
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.app import create_app
from conftest import isolated_root
from test_agent_tasks import candidate
from test_pi_runtime import CONFIG, settled

ROOT=Path(__file__).resolve().parents[1]

def test_external_entry_is_gone_and_pi_can_still_submit(tmp_path,monkeypatch):
    monkeypatch.setenv('DISCLOSURE_TEST_KEY','offline-fixture-key')
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'})
        bridge('route_request',{'domain':'disclosure','intent':'workflow','reason':'隔离测试'})
        assert bridge('read_event',{})['data']['layer']=='chinext'
        assert bridge('submit_candidate',{'result':candidate()})['data']['outcome']=='waiting_approval'
        emit({'type':'done'})
    app=create_app(tmp_path/'var',isolated_root(tmp_path),{'allowed_hosts':['testserver']},legacy_test_mode=True,pi_config=CONFIG,pi_runner=runner)
    with TestClient(app) as c:
        session=c.get('/api/session').json();c.headers.update({'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']})
        assert c.post('/api/agent-tokens',json={'name':'old'}).status_code==404
        assert c.post('/api/agent/route',json={'operation':'event.list','args':{}}).status_code==404
        assert c.get('/api/agent-tasks').status_code==404
        assert c.get('/api/events',headers={'Authorization':'Bearer old-token'}).status_code==403
        meta=c.get('/api/meta').json();assert 'agent_entry' not in meta
        assert meta['workflow']['transport']=='in_process'
        e=c.post('/api/scenarios/chinext-board-01/import',json={'request_id':str(uuid4())}).json()
        for action in ['claim','submit','evaluate','heartbeat','context']:
            path=f"/api/events/{e['id']}/agent-tasks/missing/{action}"
            assert (c.get(path) if action=='context' else c.post(path,json={})).status_code==404
        s=c.post('/api/chat/sessions',json={'event_id':e['id'],'board':'chinext','title':'Pi removal regression','request_id':str(uuid4())}).json()
        r=c.post(f"/api/chat/sessions/{s['id']}/runs",json={'text':'offline check','model_key':'fixture-a','stage':'assessment','expected_revision':e['revision'],'request_id':str(uuid4())})
        result=settled(c,r);assert result['run']['status']=='waiting_approval'
        saved=c.get('/api/events/'+e['id']).json();assert not saved.get('approval_records')
        assert saved['assessment']['producer']['host_family']=='pi'
        assert c.get('/api/model-settings').status_code==200


def test_retired_page_and_public_schema_are_not_shipped():
    assert not (ROOT/'frontend/src/components/ConnectionPage.tsx').exists()
    assert not (ROOT/'backend/agent_router.py').exists()
    for name in ['harness_client.py','codex_client.py']:
        assert not (ROOT/'scripts'/name).exists()
    for name in ['App.tsx','components/CompanyEntrance.tsx']:
        source=(ROOT/'frontend/src'/name).read_text()
        assert '本机工作空间' not in source and 'ConnectionPage' not in source
    assert "label:'Agent 接入'" not in (ROOT/'frontend/src/App.tsx').read_text()
