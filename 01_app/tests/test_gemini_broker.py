"""Banker Gemini reuse through public settings/run interfaces; no real provider."""
import json
import pytest
from backend.gemini_broker import BASE_URL, MODEL_IDS, PROVIDER, GeminiBroker
from test_model_settings import setup, snapshot, put
from test_pi_runtime import client, new_session, send, settled


def connect(c):
    return c.post('/api/model-settings/gemini/connect',json={'expected_revision':snapshot(c)['revision']})


def test_reuse_banker_models_without_changing_other_routes_or_credentials(setup):
    c,runtime,_=setup;before=snapshot(c)
    runtime.settings.gemini.model_ids=lambda:list(MODEL_IDS)
    result=connect(c);assert result.status_code==200,result.text
    state=result.json();rows=[r for r in state['models'] if r['provider']==PROVIDER]
    assert {r['id'] for r in rows}==set(MODEL_IDS)
    assert all(r['auth_type']=='google_oauth' and r['configured'] and r['reasoning_effort']=='high' and r['thinking_levels']==['low','high'] for r in rows)
    assert all(r['baseUrl']==BASE_URL and r['api']=='openai-responses' for r in rows)
    assert state['models'][:2]==before['models'] and state['routes']==before['routes']
    assert runtime.settings.vault.reads==[] and runtime.settings.vault.values=={}
    assert len(connect(c).json()['models'])==4


def test_gemini_uses_existing_pi_and_sends_only_selected_profile(setup):
    c,runtime,_=setup;runtime.settings.gemini.model_ids=lambda:list(MODEL_IDS);connect(c)
    rows=[r for r in snapshot(c)['models'] if r['provider']==PROVIDER];packets=[]
    def runner(packet,emit,bridge,stop):
        packets.append(packet);emit({'type':'started','engine':'pi-agent-core'})
        emit({'type':'assistant','message':0,'text':'离线测试','stopReason':'stop'});emit({'type':'done'})
    runtime.runner=runner;s,e=new_session(c)
    result,_=send(c,s,e,model_key=rows[0]['key']);done=settled(c,result)
    assert packets[0]['model']['id']==MODEL_IDS[0] and packets[0]['model']['api']=='openai-responses'
    assert packets[0]['model']['baseUrl']==BASE_URL and packets[0]['reasoning_effort']=='high'
    assert packets[0]['apiKey']=='nero-opencodex-local' and runtime.settings.vault.reads==[]
    assert done['run']['status']=='completed' and done['run']['model']['id']==MODEL_IDS[0]
    assert any(e['kind']=='started' and e['body']['engine']=='pi-agent-core' for e in done['events'])


def test_unavailable_shared_service_never_falls_back_or_claims_auth(setup):
    c,runtime,_=setup
    def unavailable():raise OSError('synthetic offline')
    runtime.settings.gemini.model_ids=unavailable
    state=connect(c).json();row=next(r for r in state['models'] if r['provider']==PROVIDER)
    assert not row['configured'] and not row['credential_configured']
    assert state['gemini_broker']['status']=='unavailable'
    s,e=new_session(c);result,_=send(c,s,e,model_key=row['key'])
    assert result.status_code==409 and '不会自动' in result.text
    assert c.get('/api/chat/sessions/'+s['id']).json()['runs']==[]


@pytest.mark.parametrize('patch',[{'baseUrl':'https://example.com/v1'},{'baseUrl':'http://localhost:10100/v1'},
    {'id':'google-antigravity/gemini-3.8-flash-high'},{'provider':'google'},{'api':'google-generative-ai'},
    {'auth_type':'local'},{'thinking_levels':['low','medium','high']},{'thinking_level_map':{'low':'high'}}])
def test_banker_route_is_fixed_and_unknown_ids_or_efforts_rejected(setup,patch):
    c,runtime,_=setup;runtime.settings.gemini.model_ids=lambda:list(MODEL_IDS);connect(c)
    state=snapshot(c);next(r for r in state['models'] if r['provider']==PROVIDER).update(patch)
    assert put(c,state).status_code==422


def test_connect_keeps_browser_and_revision_guards(setup):
    c,runtime,_=setup;calls=[];runtime.settings.gemini.model_ids=lambda:(calls.append(1) or list(MODEL_IDS))
    assert c.post('/api/model-settings/gemini/connect',json={'expected_revision':False}).status_code==422
    assert c.post('/api/model-settings/gemini/connect',json={'expected_revision':-1}).status_code==409
    csrf=c.headers.pop('X-CSRF-Token');assert connect(c).status_code==403;c.headers['X-CSRF-Token']=csrf
    token='retired-external-credential'
    assert c.post('/api/model-settings/gemini/connect',json={'expected_revision':0},headers={'Authorization':'Bearer '+token}).status_code==403
    assert calls==[] and snapshot(c)['revision']==0


def test_metadata_reader_uses_fixed_loopback_and_filters_models(monkeypatch):
    requests=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return json.dumps({'data':[{'id':MODEL_IDS[0]},{'id':'unrelated'},None,{'id':False}]}).encode()
    class Opener:
        def open(self,request,timeout):requests.append((request,timeout));return Response()
    monkeypatch.setattr('backend.gemini_broker.urllib.request.build_opener',lambda *args:Opener())
    broker=GeminiBroker();assert broker.status()['model_ids']==[MODEL_IDS[0]]
    assert requests[0][0].full_url==BASE_URL+'/models' and not requests[0][0].has_header('Authorization')
    assert requests[0][1]==5
