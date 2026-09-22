"""Governance checks use tiny isolated stores, never copied project databases."""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from backend import system_governance as gov
from backend.app import create_app


def database(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as c:c.execute('CREATE TABLE sample (id INTEGER)')
    return path


def backups(root,count=3):
    database(root/'var/disclosure.sqlite3')
    paths=[database(root/f'var/backups/r{i}/disclosure.sqlite3') for i in range(count)]
    for i,p in enumerate(paths):os.utime(p,ns=(1000000000+i,1000000000+i))
    return paths


def test_retains_current_and_newest_backup(tmp_path):
    paths=backups(tmp_path)
    state=gov.scan(tmp_path,tmp_path/'var');group=state['databases']['groups'][0]
    assert group['backup_count']==3 and group['needs_attention']
    preview=gov.prepare(tmp_path,tmp_path/'var','databases',[group['id']])
    assert len(preview['entries'])==2 and paths[-1].exists()
    result=gov.execute(tmp_path,tmp_path/'var',preview['id'])
    assert result['count']==2 and result['status']=='completed'
    assert paths[-1].exists() and (tmp_path/'var/disclosure.sqlite3').exists()
    assert not paths[0].exists() and not paths[1].exists()
    assert gov.execute(tmp_path,tmp_path/'var',preview['id'])==result
    assert len(gov.history(tmp_path/'var'))==1


def test_one_backup_does_not_offer_cleanup(tmp_path):
    backups(tmp_path,1)
    group=gov.databases(tmp_path)['groups'][0]
    assert not group['needs_attention'] and group['reclaimable_bytes']==0
    with pytest.raises(HTTPException):gov.prepare(tmp_path,tmp_path/'var','databases',[group['id']])


def test_changed_preview_does_not_delete_any_file(tmp_path):
    paths=backups(tmp_path)
    preview=gov.prepare(tmp_path,tmp_path/'var','databases',['var/disclosure.sqlite3'])
    paths[0].write_bytes(paths[0].read_bytes()+b'changed')
    with pytest.raises(HTTPException):gov.execute(tmp_path,tmp_path/'var',preview['id'])
    assert all(p.exists() for p in paths)


def test_live_sqlite_sidecars_and_linked_files_are_protected(tmp_path):
    paths=backups(tmp_path)
    (tmp_path/'var/disclosure.sqlite3-wal').write_bytes(b'live WAL')
    Path(str(paths[0])+'-wal').write_bytes(b'backup WAL')
    (tmp_path/'var/backups/external.sqlite3').symlink_to(tmp_path/'var/disclosure.sqlite3')
    group=gov.databases(tmp_path)['groups'][0]
    assert not next(r for r in group['backups'] if r['path']==str(paths[0].relative_to(tmp_path)))['eligible']
    preview=gov.prepare(tmp_path,tmp_path/'var','databases',[group['id']])
    gov.execute(tmp_path,tmp_path/'var',preview['id'])
    assert paths[0].exists() and (tmp_path/'var/disclosure.sqlite3-wal').exists()


def test_cache_allowlist_does_not_touch_evidence_or_dependencies(tmp_path):
    for rel in ('tests/__pycache__/a.pyc','tests/__pycache__/source.docx','data/public/originals/a.pdf','frontend/node_modules/lib/index.js'):
        p=tmp_path/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'content')
    preview=gov.prepare(tmp_path,tmp_path/'var','caches',['tests/__pycache__'])
    assert [r['path'] for r in preview['entries']]==['tests/__pycache__/a.pyc']
    gov.execute(tmp_path,tmp_path/'var',preview['id'])
    for rel in ('tests/__pycache__/source.docx','data/public/originals/a.pdf','frontend/node_modules/lib/index.js'):assert (tmp_path/rel).exists()


def test_tampered_preview_cannot_delete_current_database(tmp_path):
    backups(tmp_path)
    preview=gov.prepare(tmp_path,tmp_path/'var','databases',['var/disclosure.sqlite3'])
    current=tmp_path/'var/disclosure.sqlite3'
    preview['entries']=[{'path':'var/disclosure.sqlite3',**gov.identity(current),'sha256':gov.digest(current)}]
    (tmp_path/'var/governance/previews'/f"{preview['id']}.json").write_text(json.dumps(preview))
    with pytest.raises(HTTPException):gov.execute(tmp_path,tmp_path/'var',preview['id'])
    assert current.exists()


def test_recognizes_sibling_rebuild_backups_and_keeps_one(tmp_path):
    database(tmp_path/'data/public/boards/chinext/disclosure_library.sqlite3')
    a=database(tmp_path/'data/public/boards/chinext/disclosure_library.sqlite3.old')
    b=database(tmp_path/'data/public/boards/chinext/disclosure_library.sqlite3.bak')
    os.utime(a,ns=(1,1));os.utime(b,ns=(2,2))
    group=gov.databases(tmp_path)['groups'][0]
    assert group['backup_count']==2 and group['reclaimable_bytes']==a.stat().st_size


def test_official_docx_download_can_be_extracted(tmp_path):
    from docx import Document
    from backend.public_sources import extract
    document=Document();document.add_paragraph('公告格式指引：生效条款。')
    original=tmp_path/'official.docx';document.save(original)
    output=tmp_path/'parsed.json';extract(original,output)
    assert '生效条款' in json.loads(output.read_text())['pages'][0]['text']


def test_validity_claim_requires_locatable_official_evidence(tmp_path,monkeypatch):
    from backend import law_lifecycle,public_sources
    folder=tmp_path/'data/public/boards/chinext';folder.mkdir(parents=True)
    (folder/'catalog.json').write_text(json.dumps({'board':'chinext','sources':[{'id':'law','instrument_id':'law','title':'隔离法规','text':'原文'}]}))
    source={'board':'chinext','sha256':'a'*64,'download_id':'a'*64,'final_url':'https://www.szse.cn/test','original_path':'fixture'}
    monkeypatch.setattr(public_sources,'receipt',lambda *a:(source,{'pages':[{'text':'本通知明确废止隔离法规。'}]}))
    payload={'instrument_id':'law','outcome':'changed','detail':'测试废止通知','validity':'repealed','download_id':'a'*64,'validity_download_id':'a'*64,'validity_quote':'不存在的效力声明'}
    with pytest.raises(HTTPException):law_lifecycle.record_result(tmp_path,'chinext',payload,run_id='fixture')
    payload['validity_quote']='本通知明确废止隔离法规。'
    result=law_lifecycle.record_result(tmp_path,'chinext',payload,run_id='fixture')
    assert result['validity']=='repealed' and result['validity_evidence']['quote']==payload['validity_quote']


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('DISCLOSURE_GOV_TEST','test-credential')
    folder=tmp_path/'data/public/boards/chinext';folder.mkdir(parents=True)
    sources=[{'id':f'source-{i}','instrument_id':f'law-{i}','title':f'测试法规{i}','library_board':'chinext','text':'测试原文'} for i in range(3)]
    (folder/'catalog.json').write_text(json.dumps({'board':'chinext','sources':sources}))
    config={'models':[{'key':'test-model','label':'隔离模型','provider':'fixture','api':'openai-completions','id':'offline',
        'baseUrl':'http://127.0.0.1:1','api_key_env':'DISCLOSURE_GOV_TEST','enabled':True,'maxTokens':1024,'contextWindow':200000}]}
    app=create_app(tmp_path/'var',tmp_path,{'allowed_hosts':['testserver']},pi_config=config,pi_runner=lambda *a:None)
    with TestClient(app) as c:
        c.headers.update({'Origin':'http://testserver','X-CSRF-Token':c.get('/api/session').json()['csrf_token']})
        yield c,app.state.pi_runtime,tmp_path


def settle_batch(c,identity):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        result=c.get('/api/governance/laws/runs/'+identity).json()
        if result['status'] not in ('running','cancelling'):return result
        time.sleep(.02)
    pytest.fail('batch did not settle')


def settle_verify(c):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        result=c.get('/api/governance/version/verify').json()
        if not result or result['state']!='running':return result
        time.sleep(.05)
    pytest.fail('verification did not settle')


def conversation(root,run,title='创业板对外担保公告要求'):
    """One stored session and run, inserted the way the runtime would persist them."""
    path=root/'var/conversations.sqlite3'
    with sqlite3.connect(path) as c:
        c.execute('INSERT OR REPLACE INTO sessions(id,board,event_id,title,archived,created,updated) VALUES (?,?,?,?,0,?,?)',(run['session_id'],'chinext','event-1',title,1.0,1.0))
        c.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',(run['id'],run['session_id'],'event-1',run['status'],run['id'],'{}',json.dumps(run,ensure_ascii=False)))


def test_full_library_runs_every_instrument_once_and_get_does_not_start(client):
    c,runtime,root=client;calls=[]
    assert c.get('/api/governance/laws/current?board=chinext').json() is None
    assert not runtime.store.runs()
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'})
        assert packet['history']==[]
        run=next(r for r in runtime.store.runs() if r['status']=='running')
        identity=run['lifecycle']['instrument_id'];calls.append(identity)
        bridge('lifecycle_submit',{'instrument_id':identity,'outcome':'unavailable','detail':'隔离测试，未访问外网','validity':'uncertain'})
        emit({'type':'done'})
    runtime.runner=runner
    body={'board':'chinext','model_key':'test-model','request_id':str(uuid4())}
    r=c.post('/api/governance/laws/runs',json=body);assert r.status_code==200,r.text
    result=settle_batch(c,r.json()['batch_id'])
    assert result['completed']==result['total']==3 and result['status']=='partial'
    assert calls==['law-0','law-1','law-2']
    assert c.post('/api/governance/laws/runs',json=body).status_code==200
    assert len(runtime.store.runs())==3


def test_batch_cancel_stops_remaining_instruments(client):
    c,runtime,_=client;started=threading.Event()
    def runner(packet,emit,bridge,stop):started.set();stop.wait(3);emit({'type':'done'})
    runtime.runner=runner
    r=c.post('/api/governance/laws/runs',json={'board':'chinext','model_key':'test-model','request_id':str(uuid4())})
    assert started.wait(2)
    result=c.post('/api/governance/laws/runs/'+r.json()['batch_id']+'/cancel',json={});assert result.status_code==200
    state=settle_batch(c,r.json()['batch_id'])
    assert state['status']=='cancelled' and len(runtime.store.runs())==1
    assert len([r for r in state['items'] if r['status']=='pending'])==2


def test_cleanup_requires_csrf_and_explicit_confirmation(client):
    c,runtime,root=client;paths=backups(root)
    r=c.post('/api/governance/cleanup-preview',json={'category':'databases','ids':['var/disclosure.sqlite3']})
    assert r.status_code==200,r.text
    assert c.post('/api/governance/cleanup',json={'preview_id':r.json()['id'],'confirmed':False}).status_code==422
    assert all(p.exists() for p in paths)
    c.headers.pop('X-CSRF-Token')
    assert c.post('/api/governance/cleanup',json={'preview_id':r.json()['id'],'confirmed':True}).status_code==403


def test_health_scan_reads_state_without_starting_a_round(client):
    c,runtime,_=client
    body=c.post('/api/governance/health/scan').json()
    assert body['service']['pid']>0 and body['runs']['total']==0 and body['tasks']['hanging']==[]
    assert body['storage']['databases'] and all(row['readable'] and row['quick_check']=='ok' for row in body['storage']['databases'])
    assert not runtime.store.runs()
    assert c.get('/api/governance/health').json()['scanned_at']==body['scanned_at']
    assert '不放行门禁' in body['boundary']


def test_health_scan_flags_interrupted_round_and_blocked_task(client):
    c,runtime,root=client
    conversation(root,{'id':'run-1','session_id':'session-1','event_id':'event-1','board':'chinext','status':'interrupted','stage':'draft',
                       'model':{'label':'DeepSeek V4 Flash'},'reason':'服务重启，上一轮未完整结束；需人工重新发起','updated':time.time()})
    with c.app.state.store.engine.begin() as conn:
        conn.execute(text('INSERT INTO events VALUES (:id,:body)'),{'id':'event-1','body':json.dumps({'id':'event-1','revision':4,'title':'创业板对外担保公告要求','company_name':'样例公司','stage':'manual_escalation','escalation':{'node':'assessment','reason':'反复失败已转人工'},'agent_tasks':[{'id':'task-1','stage':'assessment','status':'submitted','status_reason':'候选已返回；等待 Verify/Gate','created_at':time.time()-90000,'evaluation':{'outcome':'blocked','attempt':3,'gate':{'status':'BLOCKED'}}}]},ensure_ascii=False)})
    body=c.post('/api/governance/health/scan').json()
    codes={row['code'] for row in body['findings']}
    assert {'rounds_interrupted','tasks_hanging','escalation'}<=codes
    run=next(row for row in body['runs']['attention'] if row['run_id']=='run-1')
    assert run['session_title']=='创业板对外担保公告要求' and '重新提问' in run['next_step']
    task=next(row for row in body['tasks']['hanging'] if row['task_id']=='task-1')
    assert task['gate_status']=='BLOCKED' and task['outcome']=='blocked' and task['event_revision']==4
    finding=next(row for row in body['findings'] if row['code']=='tasks_hanging')
    assert finding['action']=='open_runs' and finding['ids']==['event-1']


def test_health_scan_explains_business_block_without_unlocking(client):
    c,runtime,root=client
    conversation(root,{'id':'run-2','session_id':'session-2','event_id':'event-2','board':'chinext','status':'blocked','stage':'assessment',
                       'model':{'label':'DeepSeek V4 Flash'},'reason':'以已登记结果和当前 Gate 为准','updated':time.time()})
    event={'id':'event-2','revision':9,'title':'创业板对外担保公告要求','verification':{'status':'BLOCKED','issues':[{'code':'law_stale','detail':'三条法源核验记录过旧，尚未核验其后是否有变化'}]}}
    with c.app.state.store.engine.begin() as conn:
        conn.execute(text('INSERT INTO events VALUES (:id,:body)'),{'id':'event-2','body':json.dumps(event,ensure_ascii=False)})
    body=c.post('/api/governance/health/scan').json()
    run=next(row for row in body['runs']['rows'] if row['run_id']=='run-2')
    assert run['status_name']=='业务门禁阻断' and run['blockers']==['三条法源核验记录过旧，尚未核验其后是否有变化'] and run['gate_status']=='BLOCKED'
    finding=next(row for row in body['findings'] if row['code']=='rounds_blocked')
    assert '不放行' in finding['message'] and finding['detail'].startswith('三条法源核验记录过旧')
    assert not [row for row in body['findings'] if row['code'] in ('rounds_failed','rounds_incomplete')]


def test_version_scan_compares_manifest_and_does_not_rebuild(client):
    c,runtime,root=client
    (root/'backend').mkdir(exist_ok=True);(root/'backend/app.py').write_text('current source')
    recorded=[{'path':'backend/app.py','bytes':999,'sha256':'a'*64},{'path':'docs/PACKAGE_BOUNDARY.md','bytes':10,'sha256':'b'*64}]
    (root/'BUILD_MANIFEST.json').write_text(json.dumps({'version':'0.6.0','product':'NERO_Disclosure','schema_version':'nero.disclosure.manifest.v1',
        'files_count':2,'producer':{'name':'NERO','label':'NERO 出品','fingerprint':'f'*16},'files':recorded},ensure_ascii=False))
    state=c.post('/api/governance/version/scan').json()
    assert state['build']['version']=='0.6.0' and state['build']['files_count']==2
    assert state['check']['missing_count']==1 and state['check']['changed_count']==1
    assert state['check']['changed'][0]['path']=='backend/app.py' and state['web']['present'] is False
    assert state['changes']==[] and (root/'backend/app.py').read_text()=='current source'
    assert c.get('/api/governance/version').json()['scanned_at']==state['scanned_at']
    job=c.post('/api/governance/version/verify',json={'request_id':str(uuid4())}).json()
    assert job['state']=='running' and job['total']==2
    result=settle_verify(c)
    assert result['state']=='completed' and result['checked']==1 and result['mismatch_count']==1 and result['missing_count']==1


def test_version_scan_records_identity_change(client):
    c,runtime,root=client
    manifest={'version':'0.6.0','product':'NERO_Disclosure','files_count':0,'producer':{},'files':[]}
    (root/'BUILD_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False))
    c.post('/api/governance/version/scan')
    manifest['version']='0.6.1';(root/'BUILD_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False))
    state=c.post('/api/governance/version/scan').json()
    assert len(state['changes'])==1 and any('发布版本' in row for row in state['changes'][0]['differences'])
    assert c.post('/api/governance/version/scan').json()['changes']==state['changes']


def test_verify_job_without_live_worker_reports_interrupted(client):
    c,runtime,root=client
    folder=root/'var/governance';folder.mkdir(parents=True,exist_ok=True)
    folder.joinpath('version-verify.json').write_text(json.dumps({'request_id':'stale-job','state':'running','started_at':'2020-01-01T00:00:00+00:00','total':2,'checked':1}))
    assert c.get('/api/governance/version/verify').json()['state']=='interrupted'


def test_version_scan_carries_iteration_records_and_survives_broken_file(client):
    c,runtime,root=client
    (root/'config').mkdir(exist_ok=True)
    notes={'schema':'nero.disclosure.release-notes.v1','current':'1.0.1','releases':[
        {'version':'1.0.1','released_at':'2026-09-18','kind':'程序更新','summary':'直接更新程序。','items':['第一条改动','第二条改动']},
        {'version':'1.0.0','items':['旧版改动',7,'  ']}]}
    (root/'config/release-notes.json').write_text(json.dumps(notes,ensure_ascii=False))
    state=c.post('/api/governance/version/scan').json()
    assert state['releases']['current']=='1.0.1'
    assert [row['version'] for row in state['releases']['releases']]==['1.0.1','1.0.0']
    assert state['releases']['releases'][0]['items']==['第一条改动','第二条改动']
    assert state['releases']['releases'][0]['kind']=='程序更新'
    assert state['releases']['releases'][1]['items']==['旧版改动']
    # A record saved before these notes existed must still show the current file.
    log=root/'var/governance/last-version.json';record=json.loads(log.read_text('utf-8'));record.pop('releases')
    log.write_text(json.dumps(record,ensure_ascii=False))
    assert c.get('/api/governance/version').json()['releases']['current']=='1.0.1'
    assert c.get('/api/governance/version').json()['scanned_at']==state['scanned_at']
    (root/'config/release-notes.json').write_text('{ broken')
    broken=c.post('/api/governance/version/scan').json()
    assert broken['releases']=={'current':'','releases':[]}
