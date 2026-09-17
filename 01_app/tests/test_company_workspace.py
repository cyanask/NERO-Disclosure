"""Company registration and scope through the real HTTP/runtime/storage seams; offline provider."""
import json
import sqlite3
import threading
from uuid import uuid4
import pytest
from fastapi import HTTPException
from backend import announcement_history as history, public_sources
from backend.chat_store import ChatStore
from test_pi_runtime import client, settled

NAME = '甲示例科技股份有限公司'
CODE = '300101'
QUOTE = f'公司全称：{NAME}；证券代码：{CODE}；所属市场：深圳证券交易所创业板；当前状态：上市。'


def request(c, **extra):
    return c.post('/api/company-workspace/lookup', json={
        'company_name': NAME, 'stock_code': CODE, 'model_key': 'fixture-a', 'request_id': str(uuid4()), **extra})


def provider(runtime, monkeypatch, *, quote=QUOTE, board='chinext', submit=True):
    monkeypatch.setattr(public_sources, 'search', lambda q,b: {'items': [{'url': 'https://www.szse.cn/company-test.html'}], 'query': q})
    monkeypatch.setattr(public_sources, 'fetch', lambda url, **kw: (
        ('<html><body><p>' + quote + '</p></body></html>').encode(), 'text/html', url))
    def run(packet, emit, bridge, stop):
        assert packet['stage'] == 'company_lookup' and packet['history'] == []
        assert {t['name'] for t in packet['tools']} == {'company_search', 'company_read', 'submit_candidate'}
        assert NAME in packet['system'] and CODE in packet['system']
        emit({'type': 'started'})
        bridge('company_search', {'query': '所属板块 最新公司资料'})
        doc = bridge('company_read', {'url': 'https://www.szse.cn/company-test.html'})['data']
        if submit:
            bridge('submit_candidate', {'status': 'verified', 'board': board, 'reason': '核对本轮官方公司资料。',
                'sources': [{'download_id': doc['download_id'], 'page': 1, 'quote': quote}]})
        emit({'type': 'done'})
    runtime.runner = run


def test_lookup_register_and_restore_company(client, monkeypatch):
    c, runtime, _ = client
    provider(runtime, monkeypatch)
    response = request(c)
    run = settled(c, response)['run']
    assert run['status'] == 'completed'
    assert run['company_result']['board'] == 'chinext'
    assert run['company_result']['sources'][0]['url'] == 'https://www.szse.cn/company-test.html'
    assert not history.state(runtime.root, 'chinext', CODE)['company_name']
    registration = c.post('/api/company-workspace/register', json={'run_id': run['id']})
    assert registration.status_code == 200, registration.text
    assert registration.json()['company_name'] == NAME
    assert c.get('/api/company-workspace').json()['company']['stock_code'] == CODE
    assert history.state(runtime.root, 'chinext', CODE)['identity_verification']['run_id'] == run['id']
    assert c.post('/api/company-workspace/register', json={'run_id': run['id']}).json() == registration.json()
    assert c.post('/api/companies', json={'board': 'chinext', 'stock_code': '300999', 'company_name': '手填跳过'}).status_code == 404


def test_wrong_code_and_missing_result_cannot_register(client, monkeypatch):
    c, runtime, _ = client
    provider(runtime, monkeypatch, quote=QUOTE.replace(CODE, '300102'))
    run = settled(c, request(c))['run']
    assert run['status'] == 'failed' and '证券代码' in run['reason']
    assert c.post('/api/company-workspace/register', json={'run_id': run['id']}).status_code == 409
    provider(runtime, monkeypatch, submit=False)
    missing = settled(c, request(c))['run']
    assert missing['status'] == 'incomplete' and 'company_result' not in missing
    assert c.post('/api/company-workspace/register', json={'run_id': missing['id']}).status_code == 409


def test_recognizes_unsupported_board_without_enabling_or_registering(client, monkeypatch):
    c, runtime, _ = client
    provider(runtime, monkeypatch, quote=QUOTE.replace('深圳证券交易所创业板', '全国股转系统创新层'), board='innovation')
    run = settled(c, request(c))['run']
    assert run['status'] == 'completed'
    assert run['company_result']['available'] is False
    assert c.post('/api/company-workspace/register', json={'run_id': run['id']}).status_code == 409
    assert not (runtime.root/'data/client_announcements/innovation'/CODE/'catalog.json').exists()


def test_altered_evidence_rejected_at_registration(client, monkeypatch):
    c, runtime, _ = client
    provider(runtime, monkeypatch)
    run = settled(c, request(c))['run']
    source = run['company_result']['sources'][0]
    receipt, _ = public_sources.receipt(runtime.root, run['id'], source['download_id'])
    (runtime.root/receipt['document_path']).write_text('{}')
    assert c.post('/api/company-workspace/register', json={'run_id': run['id']}).status_code == 409
    assert not history.state(runtime.root, 'chinext', CODE)['company_name']


def test_cancel_after_lookup_before_registration_is_honored(client, monkeypatch):
    c,runtime,_=client
    provider(runtime,monkeypatch)
    run=settled(c,request(c))['run']
    assert run['status']=='completed'
    stopped=c.post('/api/chat/runs/'+run['id']+'/cancel').json()
    assert stopped['status']=='cancelled'
    assert c.post('/api/company-workspace/register',json={'run_id':run['id']}).status_code==409
    assert not history.state(runtime.root,'chinext',CODE)['company_name']


def test_duplicate_stop_and_request_identity(client):
    c, runtime, _ = client
    started = threading.Event()
    def waiting(packet, emit, bridge, stop):
        emit({'type': 'started'});started.set();stop.wait(5)
    runtime.runner = waiting
    request_id = str(uuid4())
    first = request(c, request_id=request_id)
    assert started.wait(2)
    assert request(c).json()['id'] == first.json()['id']
    assert request(c, request_id=request_id, stock_code='300102').status_code == 409
    assert c.post('/api/chat/runs/'+first.json()['id']+'/cancel').status_code == 200
    assert settled(c, first)['run']['status'] == 'cancelled'
    assert c.post('/api/company-workspace/register', json={'run_id': first.json()['id']}).status_code == 409


def test_lookup_tool_scope_and_no_memory_only_registration(client):
    c, runtime, _ = client
    def restricted(packet, emit, bridge, stop):
        emit({'type': 'started'})
        with pytest.raises(HTTPException) as denied:
            bridge('knowledge_delete_prepare', {'ids': ['anything']})
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException):
            bridge('submit_candidate', {'status': 'verified', 'board': 'chinext', 'reason': '只凭记忆', 'sources': []})
        bridge('submit_candidate', {'status': 'needs_review', 'reason': '未取得匹配的官方原文，请核对公司全称。'})
    runtime.runner = restricted
    run = settled(c, request(c))['run']
    assert run['status'] == 'waiting_user' and run['company_result']['status'] == 'needs_review'


def test_company_sessions_runs_events_and_deliveries_stay_scoped(client):
    c, runtime, _ = client
    for code in (CODE, '300102'):
        history.register_company(runtime.root, 'chinext', code, NAME if code == CODE else '乙示例科技股份有限公司')
    def session(code):
        result = c.post('/api/chat/sessions', json={'board': 'chinext', 'company_code': code,
            'request_id': str(uuid4()), 'title': '本公司会话'})
        assert result.status_code == 200, result.text
        return result.json()
    own, other = session(CODE), session('300102')
    assert [s['id'] for s in c.get('/api/chat/sessions', params={'board': 'chinext', 'company': CODE}).json()] == [own['id']]
    assert c.get('/api/chat/sessions/'+other['id'], params={'company': CODE}).status_code == 403
    assert c.post('/api/chat/sessions/'+own['id']+'/runs', json={'company_code': '300102', 'text': '咨询',
        'model_key': 'fixture-a', 'request_id': str(uuid4())}).status_code == 409
    for code, sid in ((CODE, own['id']), ('300102', other['id'])):
        response = c.post('/api/events', json={'company_name': NAME if code == CODE else '乙示例科技股份有限公司',
            'stock_code': code, 'board': 'chinext', 'kind': 'unclassified', 'title': '测试事项',
            'summary': '正在讨论事项。', 'facts': {}, 'request_id': str(uuid4())})
        assert response.status_code == 200, response.text
        runtime.store.bind_event(sid, response.json()['id'])
        r, _ = runtime.store.accept(runtime.store.session(sid), {'text': 'offline', 'stage': 'chat',
            'company_code': code, 'request_id': str(uuid4())}, {'key': 'fixture-a'})
        runtime.store.update(r['id'], status='completed')
    events = c.get('/api/events', params={'board': 'chinext', 'company': CODE}).json()
    assert len(events) == 1 and events[0]['stock_code'] == CODE
    runs = c.get('/api/chat/runs', params={'board': 'chinext', 'company': CODE}).json()
    assert len(runs) == 1 and runs[0]['company_code'] == CODE
    assert c.get('/api/events/'+events[0]['id'], params={'company': '300102'}).status_code == 403
    assert c.post('/api/company-workspace/select', json={'board': 'chinext', 'stock_code': CODE}).status_code == 200
    assert c.get('/api/company-workspace').json()['company']['stock_code'] == CODE


def test_existing_session_schema_is_extended_without_rewriting_rows(tmp_path):
    path = tmp_path/'conversations.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY,board TEXT NOT NULL,event_id TEXT NOT NULL,title TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL)')
        connection.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)', ('legacy', 'chinext', 'conversation:legacy', '原会话', 0, 1, 2))
    store = ChatStore(path)
    assert store.session('legacy') == {'id': 'legacy', 'board': 'chinext', 'event_id': 'conversation:legacy',
        'title': '原会话', 'archived': 0, 'created': 1, 'updated': 2, 'company_code': ''}
    assert ChatStore(path).session('legacy') == store.session('legacy')
