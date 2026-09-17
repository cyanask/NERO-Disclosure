"""Caller-visible regressions found during the technical-refactor acceptance."""
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from backend.chat_store import ChatStore
from backend import gates, document_extract, public_sources
from backend.storage import Store
from test_agent_tasks import env


def test_internal_event_create_uses_the_same_policy_and_replay_as_http(env):
    client,_,_,_=env
    payload={'company_name':'隔离测试公司','board':'chinext','kind':'unclassified',
             'title':'路由测试','summary':'只验证内部与HTTP同一合同','facts':{},'request_id':str(uuid4())}
    created=client.app.state.pi_runtime.route('event.create',payload)
    replay=client.post('/api/events',json={**payload,'request_id':str(uuid4())})
    assert replay.status_code==200,replay.text
    assert created['title']==replay.json()['title']
    assert client.app.state.pi_runtime.route('event.create',payload)==created


def test_continuous_gate_reads_receipts_without_undefined_module():
    value={'workflow_policy':'continuous-v1','verified_stages':{},'assessment':{'status':'disclose'}}
    assert {i['code'] for i in gates.upstream_issues(value,{},'plan')}=={'upstream_not_verified'}


def test_official_html_parser_shared_by_local_and_web_intake(tmp_path):
    path=tmp_path/'official.html';path.write_text('<html><p>法条正文</p><script>不能作为正文</script><a href="https://www.gov.cn/example">来源</a></html>')
    parsed=document_extract.extract(path)
    assert '法条正文' in parsed['pages'][0]['text']
    assert '不能作为正文' not in parsed['pages'][0]['text']
    output=tmp_path/'parsed.json';public_sources.extract(path,output)
    assert '法条正文' in json.loads(output.read_text())['pages'][0]['text']


def test_paginated_search_matches_legacy_display_title_and_unicode(tmp_path):
    store=ChatStore(tmp_path/'chat.sqlite3')
    for i,title in enumerate(('普通会话','Ärger','新会话')):
        session=store.create_session('chinext','',title,f's-{i}')
        run,_=store.accept(session,{'stage':'chat','text':'董事会安排','request_id':f'r-{i}'},{})
        store.append(run['id'],'user',{'text':'董事会安排'})
        store.update(run['id'],status='completed')
        if i==2:
            with store.connect() as c:c.execute("UPDATE sessions SET title='新会话' WHERE id=?",(session['id'],))
    for query in ('','董事会','ärger'):
        full=store.sessions('chinext',query)
        pages=[row for offset in range(len(full)) for row in store.sessions('chinext',query,limit=1,offset=offset)]
        assert pages==full
    assert store.sessions('chinext','董事会',limit=1)[0]['title']=='董事会安排'
    assert len(store.sessions('chinext','ärger',limit=1))==1
    assert store.runs(board='chinext',offset=1)==store.runs(board='chinext')[1:]
    with pytest.raises(HTTPException):store.runs(offset=-1)


def test_api_pagination_rejects_negative_offsets(env):
    client,_,_,_=env
    session=client.post('/api/chat/sessions',json={'board':'chinext','title':'分页','request_id':str(uuid4())}).json()
    for path in ('/api/chat/sessions?board=chinext&offset=-1','/api/chat/runs?board=chinext&offset=-1',
                 '/api/chat/sessions/'+session['id']+'?offset=-1'):
        assert client.get(path).status_code==422


def test_finished_stream_replays_every_page_before_terminal_state(env):
    client,_,_,_=env;store=client.app.state.pi_runtime.store
    session=store.create_session('chinext','','长记录',str(uuid4()))
    run,_=store.accept(session,{'stage':'chat','text':'测试','request_id':str(uuid4())},{})
    with store.connect() as c:
        c.executemany('INSERT INTO journal(run_id,at,kind,body) VALUES (?,0,?,?)',[(run['id'],'text_delta',json.dumps({'delta':str(i)})) for i in range(1005)])
    store.update(run['id'],status='completed')
    stream=client.get('/api/chat/runs/'+run['id']+'/stream').text
    assert stream.count('event: receipt')==1005
    assert stream.count('event: state')==1
    assert stream.rfind('event: receipt')<stream.index('event: state')


def test_store_read_is_enforced_and_does_not_contend_for_writer_lock(tmp_path):
    path=tmp_path/'events.sqlite3';store=Store(path)
    with store.transaction() as conn:conn.exec_driver_sql("INSERT INTO events VALUES ('e','{}')")
    with sqlite3.connect(path) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with store.read() as conn:
            assert conn.exec_driver_sql('SELECT count(*) FROM events').scalar()==1
            from sqlalchemy.exc import OperationalError
            with pytest.raises(OperationalError):conn.exec_driver_sql('DELETE FROM events')
    with store.transaction() as conn:conn.exec_driver_sql('DELETE FROM events')
    store.engine.dispose()


def test_word_round_reads_the_single_child_reader_queue(tmp_path):
    from backend.pi_runtime import PiRuntime
    import threading
    script=tmp_path/'scripts/agent_word.py';script.parent.mkdir()
    script.write_text("import sys,json,hashlib,pathlib\np=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);p.write_bytes(b'isolated-word')\nprint(json.dumps({'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}),flush=True)\n")
    runtime=PiRuntime.__new__(PiRuntime);runtime.code_root=tmp_path;runtime.directory=tmp_path/'var';runtime.directory.mkdir()
    recorded=[];runtime.trace=lambda *a:recorded.append(a)
    runtime.store=SimpleNamespace(run=lambda _: {'event_id':'e','word_input_fingerprint':'fp'},update=lambda *a,**k:None)
    runtime.operation=lambda rid,op,args: {'input_fingerprint':'fp'} if op=='word.context' else {'status':'PASS'}
    writes=[]
    def write(rid,op,**kw):
        writes.append(op)
        if op=='artifact.register':assert kw['sha256']==hashlib.sha256(b'isolated-word').hexdigest()
        return {'current_artifact_id':'a'}
    runtime.write=write
    result=runtime.word('round',threading.Event())
    assert result['data']['artifact_id']=='a' and writes==['artifact.register','gate.advance']
    assert any(row[1]=='script_returned' for row in recorded)


def quarantined(tmp_path):
    from backend import system_governance as gov
    from test_system_governance import backups
    paths=backups(tmp_path)
    plan=gov.prepare(tmp_path,tmp_path/'var','databases',['var/disclosure.sqlite3'])
    return gov,paths,plan


def test_interrupted_quarantine_can_restore_without_final_receipt(tmp_path,monkeypatch):
    gov,paths,plan=quarantined(tmp_path)
    real=gov.note
    def interrupted(directory,identity,event):
        if event['event']=='removed':raise RuntimeError('simulated power loss after move')
        return real(directory,identity,event)
    with monkeypatch.context() as m:
        m.setattr(gov,'note',interrupted)
        with pytest.raises(RuntimeError):gov.execute(tmp_path,tmp_path/'var',plan['id'])
    result=gov.restore(tmp_path,tmp_path/'var',plan['id'])
    assert result['status']=='restored' and result['count']==1
    assert all(path.exists() for path in paths)
    assert gov.restore(tmp_path,tmp_path/'var',plan['id'])['count']==0


def test_purge_preserves_unplanned_files_and_restore_rejects_links(tmp_path):
    gov,paths,plan=quarantined(tmp_path)
    gov.execute(tmp_path,tmp_path/'var',plan['id'])
    folder=gov.quarantine_root(tmp_path/'var')/plan['id'];unknown=folder/'important.txt';unknown.write_text('keep')
    with pytest.raises(HTTPException):gov.purge(tmp_path/'var',plan['id'])
    assert unknown.read_text()=='keep'
    moved=tmp_path/'var/backups';relocated=tmp_path/'original-parent';moved.rename(relocated);moved.symlink_to(relocated,target_is_directory=True)
    with pytest.raises(HTTPException):gov.restore(tmp_path,tmp_path/'var',plan['id'])
    assert not (relocated/'r0/disclosure.sqlite3').exists()


def test_backend_dependency_graph_has_no_cycles_including_lazy_imports():
    import ast
    root=Path(__file__).resolve().parents[1]/'backend'
    modules={p.stem:p for p in root.glob('*.py')};edges={key:set() for key in modules}
    for name,path in modules.items():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom) and node.level==1:
                targets=[node.module.split('.')[0]] if node.module else [a.name for a in node.names]
                edges[name].update(t for t in targets if t in modules)
    visited=set();stack=[]
    def visit(node):
        assert node not in stack,' -> '.join([*stack,node])
        if node in visited:return
        stack.append(node)
        for target in edges[node]:visit(target)
        stack.pop();visited.add(node)
    for module in modules:visit(module)


def test_release_verifier_rejects_empty_or_wrong_size_manifest(tmp_path):
    import subprocess,sys
    root=Path(__file__).resolve().parents[1]
    source=tmp_path/'source.txt';source.write_text('approved source')
    manifest=tmp_path/'manifest.json'
    def check(value):
        manifest.write_text(json.dumps(value))
        r=subprocess.run([sys.executable,str(root/'scripts/verify_release.py'),'--root',str(tmp_path),'--manifest',str(manifest)],capture_output=True,text=True)
        return r.returncode,json.loads(r.stdout)
    assert check({'files':[],'files_count':0})[0]==2
    row={'path':'source.txt','bytes':source.stat().st_size,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    assert check({'files':[row],'files_count':1,'scope':'source'})[1]['verified']
    row['bytes']+=1
    assert check({'files':[row],'files_count':1})[1]['verified'] is False


def test_nested_gate_query_reads_its_own_transaction_without_locking(tmp_path):
    store=Store(tmp_path/'events.sqlite3')
    value={'id':'new','revision':1,'layer':'chinext','stock_code':'300001','draft':{'text':'x'*100000}}
    with store.transaction() as conn:
        conn.exec_driver_sql('PRAGMA cache_size=2')
        store.save(conn,value)
        assert store.company_drafts('chinext','300001')==[value]
    assert store.company_drafts('chinext','300001')==[value]
    store.engine.dispose()
