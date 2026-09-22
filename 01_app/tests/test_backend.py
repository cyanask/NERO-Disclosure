"""V1 HTTP transport/edit regressions after removal of the old approval workflow."""
from uuid import uuid4
from fastapi.staticfiles import StaticFiles
from test_agent_tasks import env,event,latest,post


def assert_response_headers(response, web=False):
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
    if web:
        assert response.headers['pragma'] == 'no-cache'
        assert response.headers['expires'] == '0'


def test_csrf_origin_and_host_remain_required(env):
    c,_,_,_=env;e=event(c)
    assert c.post('/api/events',json={'company_id':e['company_id'],'kind':e['kind'],'title':'test','request_id':str(uuid4())},headers={'X-CSRF-Token':'bad'}).status_code==403
    assert c.post('/api/events',json={'company_id':e['company_id'],'kind':e['kind'],'title':'test','request_id':str(uuid4())},headers={'Origin':'https://elsewhere.example'}).status_code==403
    assert c.get('/api/meta',headers={'Host':'elsewhere.example'}).status_code==403


def test_request_replay_and_revision_conflict(env):
    c,_,_,_=env
    body={'request_id':str(uuid4())};a=c.post('/api/scenarios/chinext-board-01/import',json=body);b=c.post('/api/scenarios/chinext-board-01/import',json=body)
    assert a.json()==b.json()
    e=a.json();url='/api/events/'+e['id'];edit={'expected_revision':e['revision'],'summary':'修改后的模拟事实'}
    assert c.patch(url,json=edit).status_code==200
    assert c.patch(url,json=edit).status_code==409


def test_rule_check_never_rewrites_candidate_or_revision(env):
    c,_,_,_=env;e=event(c);before=latest(c,e)
    result=post(c,e,'assess');assert result.status_code==200
    assert result.json()['rule_check']['status']=='disclose'
    assert latest(c,e)==before


def test_facts_reject_nested_data_and_wrong_profile(env):
    c,_,_,_=env;e=event(c)
    assert c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':{'nested':{}}}).status_code==422
    assert c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':{'disclosure_profile_id':'missing-profile'}}).status_code==422


def test_old_generation_and_review_routes_cannot_mutate(env):
    c,_,_,_=env;e=event(c);before=latest(c,e)
    for op,args in [('plan',{}),('draft',{'template_id':'x'}),('word/prepare',{}),('word/review',{}),('approve',{})]:
        assert post(c,e,op,**args).status_code==410
    for op in ('plan','draft'):
        assert c.patch('/api/events/'+e['id']+'/'+op,json={}).status_code==410
    assert latest(c,e)==before


def test_streamed_large_request_cannot_bypass_size_limit(env):
    c,_,_,_=env
    def body():
        yield b'{"name":"'
        yield b'x'*1000001
        yield b'"}'
    response=c.post('/api/events',content=body(),headers={'Content-Type':'application/json'})
    assert response.status_code==413
    assert_response_headers(response)


def test_response_headers_cover_success_static_and_handled_errors(env):
    c,_,root,_=env
    web_root=root/'frontend-test';web_root.mkdir()
    (web_root/'bundle.js').write_text('window.synthetic = true;')
    c.app.mount('/test-assets',StaticFiles(directory=web_root),name='test-assets')

    api_response=c.get('/api/meta')
    assert api_response.status_code==200
    assert_response_headers(api_response)
    js_response=c.get('/test-assets/bundle.js')
    assert js_response.status_code==200 and 'window.synthetic = true;' in js_response.text
    assert_response_headers(js_response, web=True)

    host_error=c.get('/api/meta',headers={'Host':'elsewhere.example'})
    assert host_error.status_code==403
    assert_response_headers(host_error)
    origin_error=c.get('/api/meta',headers={'Origin':'https://elsewhere.example'})
    assert origin_error.status_code==403
    assert_response_headers(origin_error)

    length_error=c.post('/api/events',content=b'{}',headers={'Content-Type':'application/json','Content-Length':'1000001'})
    assert length_error.status_code==413
    assert_response_headers(length_error)

    validation_error=c.get('/api/chat/sessions',params={'board':'chinext','limit':'invalid'})
    assert validation_error.status_code==422
    assert_response_headers(validation_error)

    retired_error=c.post('/api/events/synthetic/plan',json={})
    assert retired_error.status_code==410
    assert_response_headers(retired_error)

    not_found=c.get('/route-that-does-not-exist')
    assert not_found.status_code==404
    assert_response_headers(not_found)
