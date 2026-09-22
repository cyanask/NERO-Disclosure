"""Focused public-interface tests; fake provider, real scoped Harness and journal."""
import json
import threading
import time
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from internal_workflow import CALLERS, install_callers
from backend.pi_runtime import safe
from test_agent_tasks import candidate, event, latest, confirm_stage

ROOT=Path(__file__).resolve().parents[1]
from conftest import isolated_root
CONFIG={'workflow_policy':'legacy-v1','models':[{'key':'fixture-a','label':'离线模型 A','provider':'fixture','api':'openai-completions','id':'offline-a',
 'baseUrl':'http://127.0.0.1:1','api_key_env':'DISCLOSURE_TEST_KEY','enabled':True,'contextWindow':200000,'maxTokens':1024},
 {'key':'fixture-b','label':'离线模型 B','provider':'fixture-b','api':'anthropic-messages','id':'offline-b',
 'baseUrl':'https://example.invalid','api_key_env':'DISCLOSURE_TEST_KEY','enabled':True,'contextWindow':200000,'maxTokens':1024}]}


@pytest.fixture
def client(tmp_path,monkeypatch):
    install_callers(monkeypatch)
    monkeypatch.setenv('DISCLOSURE_TEST_KEY','test-credential-not-real-123456')
    app=create_app(tmp_path/'var',isolated_root(tmp_path),{'allowed_hosts':['testserver']},legacy_test_mode=True,pi_config=CONFIG,
        pi_runner=lambda packet,emit,bridge,stop:(emit({'type':'started'}),emit({'type':'assistant','text':'离线测试回复','message':0}),emit({'type':'done'})))
    with TestClient(app) as c:
        session=c.get('/api/session').json();c.headers.update({'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']})
        yield c,app.state.pi_runtime,tmp_path


def new_session(c,e=None):
    e=e or event(c)
    r=c.post('/api/chat/sessions',json={'event_id':e['id'],'board':e['layer'],'title':'隔离测试会话','request_id':str(uuid4())})
    assert r.status_code==200,r.text
    return r.json(),e


def test_runtime_has_no_fixed_round_limit(client):
    _,runtime,_=client
    assert runtime.capabilities()['max_round_seconds'] is None
    assert '五分钟' not in runtime.capabilities()['notice']
    assert runtime.capabilities()['research_call_limit'] is None


def test_pi_packet_has_no_fixed_round_deadline(client):
    c,runtime,_=client;s,e=new_session(c);seen=[]
    def runner(packet,emit,bridge,stop):
        seen.append(packet);emit({'type':'started'});emit({'type':'assistant','text':'公开回复','message':0});emit({'type':'done'})
    runtime.runner=runner;r,_=send(c,s,e);assert settled(c,r)['run']['status']=='incomplete'
    assert seen[0]['max_round_seconds'] is None


def send(c,s,e,stage='chat',**extra):
    # The fixture model explicitly selects its test intent through the real routing guard.
    runtime=c.app.state.pi_runtime
    original=getattr(runtime.runner,'_unrouted_fixture',runtime.runner)
    if original:
        def scoped(packet,emit,bridge,stop):
            if packet.get('routeFirst'):
                choice={'domain':'disclosure','intent':'consult' if stage=='chat' else 'workflow','reason':'隔离测试模型按用例选择意图'}
                if stage!='chat':choice['stage']=stage
                routed=bridge('route_request',choice)
                packet={**packet,'system':routed['next_context']['system'],'tools':routed['next_context']['tools'],'routeFirst':False}
            return original(packet,emit,bridge,stop)
        scoped._unrouted_fixture=original
        runtime.runner=scoped
    body={'text':'测试本轮','model_key':'fixture-a','stage':stage,'expected_revision':latest(c,e)['revision'],'request_id':str(uuid4()),**extra}
    return c.post(f"/api/chat/sessions/{s['id']}/runs",json=body),body


def settled(c,r,timeout=15):
    assert r.status_code==200,r.text
    rid=r.json()['id'];deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=c.get('/api/chat/runs/'+rid).json()
        if result['run']['status'] not in ('accepted','running','cancelling'):return result
        time.sleep(.02)
    pytest.fail('isolated runtime did not settle')


def test_chat_identity_project_skill_and_model_switch(client):
    c,runtime,_=client;s,e=new_session(c);seen=[]
    def runner(packet,emit,bridge,stop):
        seen.append(packet);emit({'type':'started'});emit({'type':'assistant','text':'公开回复','message':0});emit({'type':'done'})
    runtime.semantic_review=lambda rid,run,items,stop: ([{'item_id':r['item_id'],'verdict':'supported' if r['value']=='公开回复' else 'insufficient','reason':'固定隔离回复，不含业务结论'} for r in items],'fixture')
    original=runner
    def checked(packet,emit,bridge,stop):
        original(packet,emit,bridge,stop)
        bridge('submit_consultation',{'text':'公开回复','basis':[]})
    runtime.runner=checked
    r,_=send(c,s,e);a=settled(c,r)
    assert a['run']['status']=='completed' and a['run']['skill_status']=='loaded'
    assert a['run']['skill']['id']=='disclosure-consultation'
    r,_=send(c,s,e,model_key='fixture-b');b=settled(c,r)
    assert b['run']['model']['id']=='offline-b' and a['run']['model']['id']=='offline-a'
    assert '公开回复' in json.dumps(seen[1]['history'],ensure_ascii=False)
    assert not latest(c,e)['assessment']
    assert {'read_event','search_library','read_library','submit_consultation','read_document_context','read_document','knowledge_web_search','knowledge_download','knowledge_download_read','read_attachment','make_word','save_announcement','assess_document_readiness','submit_candidate'} <= {x['name'] for x in seen[0]['tools']}


def test_stage_load_submit_verify_and_human_boundary(client):
    c,runtime,_=client;s,e=new_session(c)
    def runner(packet,emit,bridge,stop):
        assert 'stage_skill' in packet['system'] and 'result_schema' in packet['system']
        emit({'type':'started'})
        assert bridge('search_library',{'collection':'laws','query':'董事会'})['data']
        result=bridge('submit_candidate',{'result':candidate()})
        assert result['terminate'] is True
        emit({'type':'done'})
    runtime.runner=runner;r,_=send(c,s,e,'assessment');result=settled(c,r)
    assert result['run']['status']=='waiting_approval',result['run']
    assert result['run']['skill_status']=='loaded'
    current=latest(c,e);assert current['stage']=='awaiting_assessment_confirmation'
    assert not current.get('approval_records')
    assert current['assessment']['producer']['host_family']=='pi'
    kinds=[x['kind'] for x in result['events']]
    assert 'skill_loaded' in kinds and 'verification' in kinds and 'tool_returned' in kinds
    assert all(x['body']['transport']=='in_process_harness' for x in result['events'] if x['kind']=='tool_requested')
    assert confirm_stage(c,e,'assessment','prepare_mandatory').status_code==200


def test_no_candidate_is_not_success(client):
    c,_,_=client;s,e=new_session(c);r,_=send(c,s,e,'assessment');result=settled(c,r)
    assert result['run']['status']=='incomplete'
    assert latest(c,e)['assessment'] is None


def test_questions_release_task_and_never_confirm(client):
    c,runtime,_=client;s,e=new_session(c)
    runtime.runner=lambda p,emit,bridge,stop:(emit({'type':'started'}),bridge('request_information',{'questions':['请补充会议日期']}),emit({'type':'done'}))
    r,_=send(c,s,e,'assessment');result=settled(c,r)
    assert result['run']['status']=='waiting_user' and result['run']['questions']
    assert latest(c,e)['agent_tasks'][-1]['status']=='cancelled'
    assert not latest(c,e)['assessment']


def test_provider_failure_redaction_and_no_fallback(client):
    c,runtime,_=client;s,e=new_session(c)
    def fail(*args):raise RuntimeError('test-credential-not-real-123456')
    runtime.runner=fail;r,_=send(c,s,e);result=settled(c,r)
    assert result['run']['status']=='failed'
    assert 'test-credential-not-real-123456' not in json.dumps(result)
    assert len(runtime.store.runs(s['id']))==1


def test_duplicate_and_concurrent_event_rejected_and_cancel(client):
    c,runtime,_=client;s,e=new_session(c);started=threading.Event()
    def wait(p,emit,bridge,stop):emit({'type':'started'});started.set();stop.wait(10)
    runtime.runner=wait;r,body=send(c,s,e);assert started.wait(3)
    rid=r.json()['id']
    replay=c.post(f"/api/chat/sessions/{s['id']}/runs",json=body);assert replay.json()['id']==rid
    s2,_=new_session(c,e);other,_=send(c,s2,e);assert other.status_code==409
    changed=c.post(f"/api/chat/sessions/{s['id']}/runs",json={**body,'text':'不同消息'});assert changed.status_code==409
    assert c.patch('/api/chat/sessions/'+s['id'],json={'archived':True}).status_code==409
    assert c.post('/api/chat/runs/'+rid+'/cancel',json={}).status_code==200
    assert settled(c,r)['run']['status']=='cancelled'


def test_model_and_board_scope_fail_closed(client):
    c,runtime,_=client;s,e=new_session(c)
    r,_=send(c,s,e,model_key='missing');assert r.status_code==409
    r=c.post('/api/chat/sessions',json={'event_id':e['id'],'board':'innovation','title':'错误板块','request_id':str(uuid4())});assert r.status_code==409
    def attempt(p,emit,bridge,stop):
        emit({'type':'started'})
        for name,args in [('read_event',{'event_id':'other'}),('human.confirm',{})]:
            with pytest.raises(HTTPException) as exc:bridge(name,args)
            assert exc.value.status_code==403
        emit({'type':'done'})
    runtime.runner=attempt;r,_=send(c,s,e);assert settled(c,r)['run']['status']=='incomplete'


def test_browser_security_csrf_and_agent_cannot_dispatch(client):
    c,runtime,_=client;s,e=new_session(c)
    token='retired-external-credential'
    r,_=send(c,s,e)
    assert settled(c,r)['run']['status']=='incomplete'
    assert c.get('/api/chat/models',headers={'Authorization':'Bearer '+token}).status_code==403
    assert c.post('/api/chat/runs/'+r.json()['id']+'/cancel',headers={'X-CSRF-Token':'bad'},json={}).status_code==403
    request=runtime.route('event.get',{'event_id':e['id']});assert request['id']==e['id']
    with pytest.raises(HTTPException):runtime.route('human.confirm',{})


def test_archive_rename_and_idempotent_session(client):
    c,_,_=client;s,e=new_session(c)
    assert c.patch('/api/chat/sessions/'+s['id'],json={'title':'新的名称'}).json()['title']=='新的名称'
    assert c.get('/api/chat/sessions?board=chinext&q=新的').json()[0]['id']==s['id']
    assert c.patch('/api/chat/sessions/'+s['id'],json={'archived':True}).status_code==200
    assert c.get('/api/chat/sessions?board=chinext').json()==[]
    assert len(c.get('/api/chat/sessions?board=chinext&archived=true').json())==1
    r,_=send(c,s,e);assert r.status_code==409
    assert c.patch('/api/chat/sessions/'+s['id'],json={'archived':False}).status_code==200
    body={'event_id':e['id'],'board':'chinext','title':'可重试','request_id':str(uuid4())}
    a=c.post('/api/chat/sessions',json=body);b=c.post('/api/chat/sessions',json=body)
    assert a.json()['id']==b.json()['id']


def test_restart_marks_orphan_and_retains_transcript(client):
    c,runtime,tmp=client;s,e=new_session(c);runtime.own()
    run,_=runtime.store.accept(s,{'session_id':s['id'],'text':'未完成','stage':'chat','request_id':str(uuid4())},CONFIG['models'][0])
    runtime.store.append(run['id'],'user',{'text':'中断前消息'});runtime.close()
    app=create_app(tmp/'var',isolated_root(tmp),{'allowed_hosts':['testserver']},legacy_test_mode=True,pi_config=CONFIG)
    with TestClient(app) as next_client:
        result=next_client.get('/api/chat/runs/'+run['id']).json()
        assert result['run']['status']=='interrupted'
        assert any(x['body'].get('text')=='中断前消息' for x in result['events'])
        assert not app.state.pi_runtime.active


def test_stream_cursor_replays_only_unseen_records(client):
    c,_,_=client;s,e=new_session(c);r,_=send(c,s,e);result=settled(c,r);rows=result['events']
    response=c.get('/api/chat/runs/'+r.json()['id']+'/stream',params={'after':rows[-2]['seq']})
    assert response.status_code==200 and 'event: state' in response.text
    assert f"id: {rows[-2]['seq']}\n" not in response.text
    assert f"id: {rows[-1]['seq']}\n" in response.text


def test_redaction_preserves_usage_but_removes_credentials():
    result=safe({'apiKey':'abc','template_base64':'xyz','usage':{'inputTokens':10,'totalTokens':20},'text':'Bearer abcdef sk-aaaaaaaaaaaaaaaaaaaa','api_key_env':'DEDICATED_ENV'})
    assert result['apiKey']==result['template_base64']=='[redacted]'
    assert result['usage']['totalTokens']==20 and result['api_key_env']=='DEDICATED_ENV'
    assert 'abcdef' not in result['text']


def test_legacy_resume_registered_script_keeps_its_historical_confirmation_contract(client):
    from test_word_delivery import ready
    import hashlib
    c,runtime,_=client
    token=CALLERS[0]
    e,_=ready(c,token);s,e=new_session(c,e)
    def runner(p,emit,bridge,stop):
        emit({'type':'started'});assert bridge('make_word',{})['terminate'];emit({'type':'done'})
    runtime.runner=runner
    # Only an internal legacy continuation uses the historical frozen-word stage.
    # New browser requests route to the independent document capability.
    run=runtime.accept(s['id'],{'text':'继续已冻结的历史制作任务','stage':'word','model_key':'fixture-a',
                              'expected_revision':latest(c,e)['revision'],'request_id':str(uuid4())})
    class Accepted:
        status_code=200
        text='accepted'
        def json(self):return run
    result=settled(c,Accepted())
    assert result['run']['status']=='waiting_approval',result['run']
    artifact_id=result['run']['artifact_id'];current=latest(c,e)
    artifact=next(a for a in current['artifacts'] if a['id']==artifact_id)
    content=c.get(f"/api/events/{e['id']}/artifacts/{artifact_id}/file").content
    assert hashlib.sha256(content).hexdigest()==artifact['sha256']
    preview=c.get(f"/api/events/{e['id']}/artifacts/{artifact_id}/preview")
    assert preview.status_code==200 and preview.json()['text'].strip()
    assert artifact['verification']['visual_acceptance']=='not_verified'
    assert not any(a['node']=='word' and a['state']=='current' for a in current['approval_records'])
    kinds=[x['kind'] for x in result['events']]
    assert 'script_started' in kinds and 'script_returned' in kinds and 'artifact' in kinds


def test_fact_change_during_run_rejects_old_candidate(client):
    c,runtime,_=client;s,e=new_session(c);started=threading.Event();proceed=threading.Event()
    def runner(p,emit,bridge,stop):
        emit({'type':'started'});started.set();assert proceed.wait(5)
        bridge('submit_candidate',{'result':candidate()});emit({'type':'done'})
    runtime.runner=runner;r,_=send(c,s,e,'assessment');assert started.wait(5)
    current=latest(c,e)
    assert c.patch('/api/events/'+e['id'],json={'expected_revision':current['revision'],'summary':'模拟事实发生变化'}).status_code==200
    proceed.set();result=settled(c,r)
    assert result['run']['status']=='failed'
    assert latest(c,e)['assessment'] is None


def test_missing_skill_stops_before_model_call(client,monkeypatch):
    from backend import stage_skills
    c,runtime,_=client;s,e=new_session(c);called=[]
    def fail(*args):raise HTTPException(409,'模拟 Skill 哈希校验失败')
    monkeypatch.setattr(stage_skills,'get',fail)
    runtime.runner=lambda *args:called.append(True)
    r,_=send(c,s,e,'assessment');result=settled(c,r)
    assert result['run']['status']=='failed' and not called
    assert not any(x['kind']=='started' for x in result['events'])


def test_second_instance_cannot_interrupt_active_instance(client):
    c,runtime,tmp=client;s,e=new_session(c);runtime.own()
    app=create_app(tmp/'var',isolated_root(tmp),{'allowed_hosts':['testserver']},legacy_test_mode=True,pi_config=CONFIG)
    with TestClient(app) as other:
        r=other.get('/api/chat/models');assert r.status_code==409
    assert not runtime.closed


def test_cancellation_prevents_later_tools(client):
    c,runtime,_=client;s,e=new_session(c);started=threading.Event();attempted=threading.Event()
    def runner(p,emit,bridge,stop):
        emit({'type':'started'});started.set();assert stop.wait(5)
        with pytest.raises(HTTPException) as exc:bridge('read_event',{})
        assert exc.value.status_code==409;attempted.set()
    runtime.runner=runner;r,_=send(c,s,e);assert started.wait(5)
    c.post('/api/chat/runs/'+r.json()['id']+'/cancel',json={})
    assert settled(c,r)['run']['status']=='cancelled' and attempted.is_set()
