"""Failure-oriented acceptance checks, using tiny isolated stores only."""
import json
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from backend import runtime_health as health, version_governance as version
from test_system_governance import client, conversation, settle_verify


def manifest(root):
    (root/'sample.txt').write_text('source')
    doc={'version':'test','files_count':1,'files':[{'path':'sample.txt','bytes':6,'sha256':version.digest(root/'sample.txt')}]}
    (root/'BUILD_MANIFEST.json').write_text(json.dumps(doc))
    return doc


def test_same_request_does_not_start_two_hash_workers(client,monkeypatch):
    c,_,root=client;manifest(root);entered=threading.Event();release=threading.Event();calls=[]
    original=version.digest
    def slow(path):
        if Path(path).name=='sample.txt':
            calls.append(str(path));entered.set();release.wait(3)
        return original(path)
    monkeypatch.setattr(version,'digest',slow)
    request={'request_id':str(uuid4())}
    try:
        assert c.post('/api/governance/version/verify',json=request).status_code==200
        assert entered.wait(2)
        assert c.post('/api/governance/version/verify',json=request).status_code==200
        assert len(calls)==1
    finally:release.set();settle_verify(c)


def test_fresh_job_without_worker_is_immediately_interrupted(client):
    c,_,root=client;folder=root/'var/governance';folder.mkdir(parents=True)
    (folder/'version-verify.json').write_text(json.dumps({'state':'running','request_id':'old-process','started_at':version.now()}))
    assert c.get('/api/governance/version/verify').json()['state']=='interrupted'


@pytest.mark.parametrize('value',[{}, {'files':[{'path':'../outside','bytes':1,'sha256':'a'*64}]}, {'files':[{'path':'sample.txt'}]}])
def test_invalid_manifest_never_claims_consistency(client,value):
    c,_,root=client;(root/'BUILD_MANIFEST.json').write_text(json.dumps(value))
    result=c.post('/api/governance/version/scan').json()
    assert result['build']['error'] and result['check']['status']=='unavailable'
    assert c.post('/api/governance/version/verify',json={'request_id':str(uuid4())}).status_code==409


def test_old_failure_resolved_by_new_round_is_not_current_alert(client):
    c,runtime,root=client
    conversation(root,{'id':'old','event_id':'event-1','session_id':'s1','status':'failed','updated':1})
    conversation(root,{'id':'new','event_id':'event-1','session_id':'s1','status':'completed','updated':2})
    result=c.post('/api/governance/health/scan').json()
    assert not result['runs']['attention']
    assert not any(f['code']=='rounds_failed' for f in result['findings'])
    assert result['runs']['total']==2


def test_gate_receipt_stays_bound_to_its_own_run(client):
    c,runtime,root=client
    conversation(root,{'id':'run-old','event_id':'event-1','session_id':'s1','task_id':'t-old','status':'blocked','updated':1})
    event={'id':'event-1','verification':{'status':'PASS','issues':[]},'agent_tasks':[
        {'id':'t-old','evaluation':{'gate':{'status':'BLOCKED','issues':[{'detail':'old evidence missing'}]}}}]}
    row=health.runs_state(runtime,[event])['rows'][0]
    assert row['blockers']==['old evidence missing'] and row['gate_status']=='BLOCKED'


def test_normal_active_task_is_not_an_orphan(client):
    c,runtime,root=client
    conversation(root,{'id':'live','event_id':'event-1','session_id':'s1','task_id':'t1','status':'running','updated':time.time()})
    event={'id':'event-1','agent_tasks':[{'id':'t1','stage':'assessment','status':'claimed'}]}
    result=health.tasks_state([event],runtime.store.runs())
    assert result['hanging']==[] and result['active_count']==1


def test_empty_backup_is_not_a_verified_rollback_point(client):
    c,_,root=client;(root/'var/backups/empty').mkdir(parents=True)
    rows=version.rollback(root,root/'var')
    assert rows and rows[0]['readiness']=='unavailable'


def test_verification_can_be_cancelled_and_restarted(client,monkeypatch):
    c,_,root=client;manifest(root);entered=threading.Event();release=threading.Event();original=version.digest
    def slow(path):
        if Path(path).name=='sample.txt':entered.set();release.wait(3)
        return original(path)
    monkeypatch.setattr(version,'digest',slow);request={'request_id':str(uuid4())}
    try:
        c.post('/api/governance/version/verify',json=request);assert entered.wait(2)
        assert c.post('/api/governance/version/verify/cancel',json={'request_id':'wrong-run'}).status_code==409
        assert c.post('/api/governance/version/verify/cancel',json=request).json()['state']=='cancelling'
    finally:release.set()
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        state=c.get('/api/governance/version/verify').json()
        if state['state']=='cancelled':break
        time.sleep(.01)
    assert state['state']=='cancelled'
    assert c.post('/api/governance/version/verify',json={'request_id':str(uuid4())}).status_code==200
    assert settle_verify(c)['state']=='completed'


def test_worker_exception_reaches_failed_terminal(client,monkeypatch):
    c,_,root=client;manifest(root);original=version.digest
    def broken(path):
        if Path(path).name=='sample.txt':raise RuntimeError('fixture failure')
        return original(path)
    monkeypatch.setattr(version,'digest',broken)
    c.post('/api/governance/version/verify',json={'request_id':str(uuid4())})
    state=settle_verify(c)
    assert state['state']=='failed' and 'fixture failure' in state['error']


def test_manifest_link_outside_project_is_rejected(client,tmp_path):
    c,_,root=client;doc=manifest(root)
    (root/'sample.txt').unlink();(root/'sample.txt').symlink_to('/etc/hosts')
    assert version.build(root)['error']
    assert c.post('/api/governance/version/verify',json={'request_id':str(uuid4())}).status_code==409


def test_portable_runtime_internal_links_remain_verifiable(client):
    c,_,root=client;manifest(root)
    (root/'sample.txt').rename(root/'target.txt');(root/'sample.txt').symlink_to('target.txt')
    assert version.build(root)['error'] is None
    c.post('/api/governance/version/verify',json={'request_id':str(uuid4())})
    result=settle_verify(c)
    assert result['state']=='completed' and result['mismatch_count']==result['missing_count']==0


def test_backend_source_change_is_reported_as_restart_required(client,tmp_path):
    _,runtime,_=client;runtime.code_root=tmp_path/'code';(runtime.code_root/'backend').mkdir(parents=True)
    source=runtime.code_root/'backend/example.py';source.write_text('value=1')
    version.bind_runtime(runtime)
    assert version.running_backend(runtime)['status']=='current'
    source.write_text('value=2')
    assert version.running_backend(runtime)['status']=='restart_required'


def test_database_quarantine_restore_and_release_are_wired(client):
    from test_system_governance import backups
    c,_,root=client;paths=backups(root)
    prepared=c.post('/api/governance/cleanup-preview',json={'category':'databases','ids':['var/disclosure.sqlite3']}).json()
    body={'preview_id':prepared['id'],'confirmed':True}
    result=c.post('/api/governance/cleanup',json=body).json()
    assert result['released_bytes']==0 and result['quarantined_bytes']>0
    state=c.post('/api/governance/scan').json();item=state['quarantine']['items'][0]
    assert len(item['entries'])==2 and paths[-1].exists()
    assert c.post('/api/governance/cleanup/restore',json={**body,'confirmed':False}).status_code==422
    assert c.post('/api/governance/cleanup/restore',json=body).json()['count']==2
    assert all(p.exists() for p in paths)
    prepared=c.post('/api/governance/cleanup-preview',json={'category':'databases','ids':['var/disclosure.sqlite3']}).json()
    body={'preview_id':prepared['id'],'confirmed':True};c.post('/api/governance/cleanup',json=body)
    assert c.post('/api/governance/cleanup/purge',json=body).json()['released_bytes']>0
    assert paths[-1].exists() and (root/'var/disclosure.sqlite3').exists()
