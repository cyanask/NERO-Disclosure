import json,sqlite3,zipfile,threading,time,shutil
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from backend.app import create_app
from test_pi_runtime import CONFIG,settled
from test_agent_tasks import candidate,event
ROOT=Path(__file__).resolve().parents[1]
from conftest import isolated_root

@pytest.fixture
def control(tmp_path,monkeypatch):
    monkeypatch.setenv('DISCLOSURE_TEST_KEY','offline-autonomous')
    app=create_app(tmp_path/'var',isolated_root(tmp_path),{'allowed_hosts':['testserver']},legacy_test_mode=True,pi_config=CONFIG,pi_runner=lambda *a:None)
    with TestClient(app) as c:
        session=c.get('/api/session').json();c.headers.update({'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']})
        yield c,app.state.pi_runtime,tmp_path


def session(c,e=None):
    r=c.post('/api/chat/sessions',json={'board':'chinext','title':'控制层隔离测试','event_id':e['id'] if e else '', 'request_id':str(uuid4())});assert r.status_code==200,r.text;return r.json()


def send_auto(c,s,text='信披咨询',**kw):
    return c.post(f"/api/chat/sessions/{s['id']}/runs",json={'text':text,'model_key':'fixture-a','request_id':str(uuid4()),**kw})


def test_general_consultation_has_no_fake_company_and_requires_routing(control):
    c,r,_=control;s=session(c)
    def model(p,emit,bridge,stop):
        assert p['tools'][0]['name']=='route_request'
        with pytest.raises(HTTPException):bridge('read_event',{})
        reply=bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'一般信披规则问题'})
        assert 'next_context' in reply
        assert bridge('read_event',{})['data']['bound'] is False
        emit({'type':'assistant','phase':'answer','message':1,'text':'信披咨询答复','stopReason':'stop'});emit({'type':'done'})
    r.runner=model;out=settled(c,send_auto(c,s))
    assert out['run']['status']=='completed' and out['run']['stage']=='chat'
    assert c.get('/api/chat/sessions/'+s['id']).json()['event'] is None
    assert c.get('/api/events').json()==[]


def test_unrelated_request_refuses_even_if_client_posts_a_stage(control):
    c,r,_=control;s=session(c)
    def model(p,emit,bridge,stop):
        answer=bridge('route_request',{'domain':'unrelated','intent':'consult','reason':'无关任务'})
        assert answer['terminate']
        with pytest.raises(HTTPException):bridge('read_event',{})
        emit({'type':'done'})
    r.runner=model;out=settled(c,send_auto(c,s,'写旅游攻略',stage='assessment'))
    assert out['run']['stage']=='scope' and out['run']['status']=='completed'
    assert any('无法回答' in x['body'].get('text','') for x in out['events'])
    assert c.get('/api/events').json()==[]


def test_workflow_auto_route_preserves_human_gate(control):
    c,r,_=control;e=event(c);s=session(c,e)
    def model(p,emit,bridge,stop):
        reply=bridge('route_request',{'domain':'disclosure','intent':'workflow','reason':'用户要求判断披露义务'})
        assert any(x['name']=='submit_candidate' for x in reply['next_context']['tools'])
        bridge('submit_candidate',{'result':candidate()});emit({'type':'done'})
    r.runner=model;out=settled(c,send_auto(c,s,expected_revision=e['revision']))
    assert out['run']['status']=='waiting_approval'
    assert not c.get('/api/events/'+e['id']).json().get('approval_records')


def test_knowledge_query_cannot_write_or_execute_workflow(control):
    c,r,_=control;s=session(c)
    def model(p,emit,bridge,stop):
        reply=bridge('route_request',{'domain':'knowledge','intent':'query','reason':'查询知识库'})
        assert {x['name'] for x in reply['next_context']['tools']}=={'knowledge_search','knowledge_read','knowledge_web_search','knowledge_download','knowledge_download_read','knowledge_imports','knowledge_history','knowledge_import_read'}
        with pytest.raises(HTTPException):bridge('knowledge_propose',{'operation':'delete'})
        with pytest.raises(HTTPException):bridge('submit_candidate',{'result':candidate()})
        assert bridge('knowledge_search',{'collection':'laws','query':'董事会'})['data']['items']
        emit({'type':'done'})
    r.runner=model;out=settled(c,send_auto(c,s,'查询董事会规则'));assert out['run']['status']=='completed'


def test_purge_cleans_session_runs_files_and_backup_without_touching_other_session(control):
    c,r,tmp=control;a=session(c);b=session(c)
    # Session ids are request-specific even when titles match.
    def model(p,emit,bridge,stop):bridge('route_request',{'domain':'unrelated','intent':'consult','reason':'测试拒绝'})
    r.runner=model;out=settled(c,send_auto(c,a));rid=out['run']['id']
    assert c.get('/api/chat/sessions/'+a['id']+'/deletion-preview').status_code==409
    assert c.patch('/api/chat/sessions/'+a['id'],json={'archived':True}).status_code==200
    backup=r.directory/'backups/test';backup.mkdir(parents=True)
    source=sqlite3.connect(r.store.path);dest=sqlite3.connect(backup/'conversations.sqlite3');source.backup(dest);dest.close();source.close()
    folder=r.directory/'pi-runs'/rid;folder.mkdir(parents=True);(folder/'result.txt').write_text('private session output')
    archive=backup/'snapshot.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.write(backup/'conversations.sqlite3','var/conversations.sqlite3')
        z.write(folder/'result.txt','var/pi-runs/'+rid+'/result.txt')
        z.writestr('unrelated.txt','keep me')
    preview=c.get('/api/chat/sessions/'+a['id']+'/deletion-preview').json();assert preview['backups'] and preview['files']
    assert c.request('DELETE','/api/chat/sessions/'+a['id'],json={'fingerprint':'wrong'}).status_code==409
    result=c.request('DELETE','/api/chat/sessions/'+a['id'],json={'fingerprint':preview['fingerprint']});assert result.status_code==200,result.text
    assert c.get('/api/chat/sessions/'+a['id']).status_code==404 and c.get('/api/chat/runs/'+rid).status_code==404
    assert c.get('/api/chat/sessions/'+b['id']).status_code==200 and not (folder/'result.txt').exists()
    with zipfile.ZipFile(archive) as z:
        assert 'var/pi-runs/'+rid+'/result.txt' not in z.namelist() and z.read('unrelated.txt')==b'keep me'
    copied=sqlite3.connect(backup/'conversations.sqlite3');assert copied.execute('select 1 from sessions where id=?',(a['id'],)).fetchone() is None;assert copied.execute('select 1 from sessions where id=?',(b['id'],)).fetchone();copied.close()


def test_auto_intake_owns_only_new_event_and_purge_removes_it(control):
    c,r,tmp=control;s=session(c)
    def model(p,emit,bridge,stop):
        reply=bridge('route_request',{'domain':'disclosure','intent':'workflow','reason':'准备判断真实事项','event':{'company_name':'隔离测试公司','title':'新事项','summary':'仅为工程测试的董事会事项','facts':{'event_date':'2026-09-08','assessment_as_of':'2026-09-08'},'output_mode':'text'}})
        assert reply['data']['stage']=='assessment';emit({'type':'done'})
    r.runner=model;out=settled(c,send_auto(c,s,'请判断隔离测试公司的事项'))
    assert out['run']['owns_event'];eid=out['run']['event_id'];assert not eid.startswith('conversation:')
    assert c.get('/api/chat/sessions/'+s['id']).json()['event']['id']==eid
    c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    preview=c.get('/api/chat/sessions/'+s['id']+'/deletion-preview').json();assert preview['delete_owned_event']
    result=c.request('DELETE','/api/chat/sessions/'+s['id'],json={'fingerprint':preview['fingerprint']});assert result.status_code==200,result.text
    assert result.json()['deleted_event_id']==eid and c.get('/api/events/'+eid).status_code==404


def test_shared_event_is_retained_and_zip_backup_is_scrubbed(control):
    c,r,tmp=control;e=event(c);s=session(c,e);other=session(c,e)
    c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    folder=r.directory/'backups/zip-fixture';folder.mkdir(parents=True)
    for name in ['conversations.sqlite3','disclosure.sqlite3']:
        source=sqlite3.connect(r.directory/name);target=sqlite3.connect(folder/name);source.backup(target);source.close();target.close()
    archive=folder/'historical.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('keep-unrelated.txt','unrelated content')
        for name in ['conversations.sqlite3','disclosure.sqlite3']:z.write(folder/name,'var/'+name)
    preview=c.get('/api/chat/sessions/'+s['id']+'/deletion-preview').json();assert not preview['delete_owned_event'] and any(x['kind']=='zip' for x in preview['backups'])
    result=c.request('DELETE','/api/chat/sessions/'+s['id'],json={'fingerprint':preview['fingerprint']});assert result.status_code==200,result.text
    assert c.get('/api/events/'+e['id']).status_code==200 and c.get('/api/chat/sessions/'+other['id']).status_code==200
    with zipfile.ZipFile(archive) as z:(tmp/'scrubbed.sqlite3').write_bytes(z.read('var/conversations.sqlite3'))
    db=sqlite3.connect(tmp/'scrubbed.sqlite3');assert db.execute('select 1 from sessions where id=?',(s['id'],)).fetchone() is None;assert db.execute('select 1 from sessions where id=?',(other['id'],)).fetchone();db.close()


def test_interrupted_purge_retries_the_same_confirmed_scope(control,monkeypatch):
    from backend import session_deletion
    c,r,_=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    preview=session_deletion.preview(r,s['id']);real=session_deletion.scrub;failed=False
    def stop_after_business(path,plan):
        nonlocal failed
        if Path(path)==r.store.path and not failed:failed=True;raise OSError('injected interruption')
        return real(path,plan)
    monkeypatch.setattr(session_deletion,'scrub',stop_after_business)
    with pytest.raises(OSError):session_deletion.delete(r,s['id'],preview['fingerprint'])
    assert session_deletion.preview(r,s['id'])['fingerprint']==preview['fingerprint']
    result=session_deletion.delete(r,s['id'],preview['fingerprint']);assert result['status']=='deleted'
    assert c.get('/api/chat/sessions/'+s['id']).status_code==404


def test_pending_delete_cannot_resume_against_a_copied_workspace(control):
    from backend import session_deletion
    c,r,tmp=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    document=r.local_root/'work/documents'/s['id'];document.mkdir(parents=True);source_file=document/'synthetic.txt';source_file.write_text('keep in original')
    plan=session_deletion.preview(r,s['id'])
    marker=r.directory/'deletions'/f'session-{s["id"]}.json';marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({'status':'deleting','workspace_id':session_deletion._workspace_id(r),'plan':plan}))

    copied=tmp/'copied-project';copied_var=tmp/'copied-var'
    shutil.copytree(r.root,copied);shutil.copytree(r.directory,copied_var)
    app=create_app(copied_var,copied,{'allowed_hosts':['testserver']},legacy_test_mode=True,pi_config=CONFIG,pi_runner=lambda *a:None)
    new_runtime=app.state.pi_runtime
    try:
        new_runtime.own()
        marker=copied_var/'deletions'/f'session-{s["id"]}.json'
        assert json.loads(marker.read_text())['status']=='blocked'
        assert source_file.exists()
        copied_file=copied/'work/documents'/s['id']/'synthetic.txt'
        assert copied_file.exists()
        fresh=session_deletion.preview(new_runtime,s['id'])
        assert fresh['fingerprint']!=plan['fingerprint']
        assert session_deletion.delete(new_runtime,s['id'],fresh['fingerprint'])['status']=='deleted'
        assert source_file.exists()
        assert not copied_file.exists()
    finally:
        new_runtime.close()


def test_pending_delete_corrupt_markers_are_blocked_without_startup_failure(control):
    from backend import session_deletion
    c,r,_=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    marker=r.directory/'deletions'/f'session-{s["id"]}.json';marker.parent.mkdir(parents=True)
    values=(None,[],{'status':'deleting','plan':None},
            {'status':'deleting','plan':[]},
            {'status':'deleting','plan':{'session_id':'other'}})
    for value in values:
        marker.write_text(json.dumps(value))
        session_deletion.resume_pending(r)
        assert json.loads(marker.read_text())['status']=='blocked'
    marker.write_text('{bad-json')
    session_deletion.resume_pending(r)
    assert json.loads(marker.read_text())['status']=='blocked'
    wrong=r.directory/'deletions'/'session-other.json'
    wrong.write_text(json.dumps({'status':'deleting','workspace_id':session_deletion._workspace_id(r),
                                 'plan':session_deletion.preview(r,s['id'])}))
    session_deletion.resume_pending(r)
    assert json.loads(wrong.read_text())['status']=='blocked'


def test_pending_delete_rejects_parent_symlink(control):
    from backend import session_deletion
    c,r,_=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    documents=r.local_root/'work/documents';documents.parent.mkdir(parents=True,exist_ok=True)
    external=r.local_root/'outside-documents';external.mkdir(parents=True)
    documents.symlink_to(external,target_is_directory=True)
    (external/s['id']).mkdir(parents=True)
    (external/s['id']/'outside.txt').write_text('external')
    with pytest.raises(HTTPException):session_deletion.preview(r,s['id'])


def test_pending_delete_control_symlinks_never_write_outside(control):
    from backend import session_deletion
    c,r,tmp=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    outside=tmp/'outside-control';outside.mkdir()
    control_dir=r.directory/'deletions';control_dir.symlink_to(outside,target_is_directory=True)
    session_deletion.resume_pending(r)
    assert list(outside.iterdir())==[]
    with pytest.raises(HTTPException):session_deletion.preview(r,s['id'])


def test_pending_delete_marker_symlink_never_overwrites_target(control):
    from backend import session_deletion
    c,r,tmp=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    folder=r.directory/'deletions';folder.mkdir(parents=True)
    outside=tmp/'outside-marker.json';outside.write_text('{"status":"deleting"}')
    marker=folder/f'session-{s["id"]}.json';marker.symlink_to(outside)
    session_deletion.resume_pending(r)
    assert outside.read_text()=='{"status":"deleting"}'
    with pytest.raises(HTTPException):session_deletion.preview(r,s['id'])


def test_pending_delete_root_alias_is_rejected_without_following_alias(control):
    from backend import session_deletion
    c,r,tmp=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    alias=tmp/'project-alias';alias.symlink_to(r.root,target_is_directory=True)
    r.root=alias
    session_deletion.resume_pending(r)
    with pytest.raises(HTTPException):session_deletion.preview(r,s['id'])


def test_backup_adjacent_scrub_interruption_requires_same_scope_reconfirmation(control,monkeypatch):
    from backend import session_deletion
    c,r,_=control;e=event(c);s=session(c,e)
    run,_=r.store.accept(r.store.session(s['id']),{'session_id':s['id'],'stage':'chat','text':'fixture','request_id':str(uuid4())},CONFIG['models'][0])
    r.store.update(run['id'],status='completed',owns_event=True)
    c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    folder=r.directory/'backups'/'partial';folder.mkdir(parents=True)
    for source_path,name in ((r.store.path,'conversations.sqlite3'),(r.directory/'disclosure.sqlite3','disclosure.sqlite3')):
        source=sqlite3.connect(source_path);target=sqlite3.connect(folder/name);source.backup(target);target.close();source.close()
    preview=session_deletion.preview(r,s['id'])
    primary=folder/'conversations.sqlite3';adjacent=folder/'disclosure.sqlite3'
    real_build=session_deletion._build_backup_candidate
    def fail_primary(runtime,path,item,plan):
        if Path(path)==primary:raise OSError('injected backup interruption')
        return real_build(runtime,path,item,plan)
    monkeypatch.setattr(session_deletion,'_build_backup_candidate',fail_primary)
    with pytest.raises(OSError):session_deletion.delete(r,s['id'],preview['fingerprint'])
    assert not session_deletion._db_presence(adjacent,'events','id',e['id']) and session_deletion.db_has(primary,s['id'])
    session_deletion.resume_pending(r)
    assert json.loads((r.directory/'deletions'/f'session-{s["id"]}.json').read_text())['status']=='blocked'
    monkeypatch.setattr(session_deletion,'_build_backup_candidate',real_build)
    fresh=session_deletion.preview(r,s['id'])
    assert fresh['fingerprint']==preview['fingerprint']
    assert session_deletion.delete(r,s['id'],fresh['fingerprint'])['status']=='deleted'
    assert not session_deletion.db_has(primary,s['id'])


def test_pending_delete_keeps_prepared_backup_candidate_after_replace_retry(control,monkeypatch):
    from backend import session_deletion
    c,r,_=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    folder=r.directory/'backups'/'replace-retry';folder.mkdir(parents=True)
    source=sqlite3.connect(r.store.path);target=sqlite3.connect(folder/'conversations.sqlite3');source.backup(target);target.close();source.close()
    plan=session_deletion.preview(r,s['id']);backup=folder/'conversations.sqlite3';real_replace=session_deletion.os.replace;failed=False
    def fail_once(source_path,target_path):
        nonlocal failed
        if Path(target_path)==backup and not failed:
            failed=True;raise PermissionError('injected target lock')
        return real_replace(source_path,target_path)
    monkeypatch.setattr(session_deletion.os,'replace',fail_once)
    with pytest.raises(PermissionError):session_deletion.delete(r,s['id'],plan['fingerprint'])
    marker=r.directory/'deletions'/f'session-{s["id"]}.json';saved=json.loads(marker.read_text())
    candidate=saved['progress']['backups']['0']['candidate']
    candidate_path=r.directory/candidate['path'] if candidate['scope']=='directory' else r.local_root/candidate['path']
    assert saved['progress']['backups']['0']['status']=='prepared' and candidate_path.is_file()
    monkeypatch.setattr(session_deletion.os,'replace',real_replace)
    session_deletion.resume_pending(r)
    assert json.loads(marker.read_text())['status']=='deleted'
    assert not session_deletion.db_has(backup,s['id'])


def test_pending_delete_does_not_replace_backup_changed_after_candidate_build(control,monkeypatch):
    from backend import session_deletion
    c,r,_=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    folder=r.directory/'backups'/'candidate-source-change';folder.mkdir(parents=True)
    source=sqlite3.connect(r.store.path);backup=folder/'conversations.sqlite3';target=sqlite3.connect(backup);source.backup(target);target.close();source.close()
    plan=session_deletion.preview(r,s['id']);real_build=session_deletion._build_backup_candidate;changed=backup.read_bytes()
    def build_then_change(runtime,path,item,value):
        candidate=real_build(runtime,path,item,value)
        Path(path).write_bytes(Path(path).read_bytes()+b'changed-after-candidate')
        return candidate
    monkeypatch.setattr(session_deletion,'_build_backup_candidate',build_then_change)
    with pytest.raises(HTTPException):session_deletion.delete(r,s['id'],plan['fingerprint'])
    marker=r.directory/'deletions'/f'session-{s["id"]}.json';saved=json.loads(marker.read_text())
    assert backup.read_bytes()==changed+b'changed-after-candidate'
    assert saved['progress']['backups']['0']['status']=='prepared'


def test_pending_delete_rejects_prepared_candidate_outside_control_dir(control,monkeypatch):
    from backend import session_deletion
    c,r,_=control;s=session(c);c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    folder=r.directory/'backups'/'candidate-boundary';folder.mkdir(parents=True)
    source=sqlite3.connect(r.store.path);backup=folder/'conversations.sqlite3';target=sqlite3.connect(backup);source.backup(target);target.close();source.close()
    plan=session_deletion.preview(r,s['id']);real_replace=session_deletion.os.replace;failed=False
    def fail_once(source_path,target_path):
        nonlocal failed
        if Path(target_path)==backup and not failed:
            failed=True;raise PermissionError('injected target lock')
        return real_replace(source_path,target_path)
    monkeypatch.setattr(session_deletion.os,'replace',fail_once)
    with pytest.raises(PermissionError):session_deletion.delete(r,s['id'],plan['fingerprint'])
    monkeypatch.setattr(session_deletion.os,'replace',real_replace)
    marker=r.directory/'deletions'/f'session-{s["id"]}.json';saved=json.loads(marker.read_text())
    outside=r.local_root/'outside-prepared-candidate.sqlite';outside.write_bytes(b'preserve me')
    state=saved['progress']['backups']['0'];state['candidate']={'scope':'local','path':'outside-prepared-candidate.sqlite','kind':'sqlite','sha256':state['after_sha256']}
    marker.write_text(json.dumps(saved))
    session_deletion.resume_pending(r)
    blocked=json.loads(marker.read_text())
    assert blocked['status']=='blocked' and outside.read_bytes()==b'preserve me' and session_deletion.db_has(backup,s['id'])


def test_pending_delete_recovers_backup_and_live_business_interruption(control,monkeypatch):
    from backend import session_deletion
    c,r,_=control;e=event(c);s=session(c,e)
    run,_=r.store.accept(r.store.session(s['id']),{'session_id':s['id'],'stage':'chat','text':'fixture','request_id':str(uuid4())},CONFIG['models'][0])
    r.store.update(run['id'],status='completed',owns_event=True)
    c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    folder=r.directory/'backups'/'recoverable';folder.mkdir(parents=True)
    for source_path,name in ((r.store.path,'conversations.sqlite3'),(r.directory/'disclosure.sqlite3','disclosure.sqlite3')):
        source=sqlite3.connect(source_path);target=sqlite3.connect(folder/name);source.backup(target);target.close();source.close()
    plan=session_deletion.preview(r,s['id']);real=session_deletion.scrub
    live_business=r.directory/'disclosure.sqlite3'
    def interrupt_after_business(path,value):
        real(path,value)
        if Path(path)==live_business:raise OSError('injected live business interruption')
    monkeypatch.setattr(session_deletion,'scrub',interrupt_after_business)
    with pytest.raises(OSError):session_deletion.delete(r,s['id'],plan['fingerprint'])
    session_deletion.resume_pending(r)
    marker=r.directory/'deletions'/f'session-{s["id"]}.json'
    assert json.loads(marker.read_text())['status']=='deleted'
    assert c.get('/api/chat/sessions/'+s['id']).status_code==404
    assert c.get('/api/events/'+e['id']).status_code==404


def test_resume_blocked_marker_keeps_progress_written_before_second_interrupt(control,monkeypatch):
    from backend import session_deletion
    c,r,_=control;e=event(c);s=session(c,e)
    run,_=r.store.accept(r.store.session(s['id']),{'session_id':s['id'],'stage':'chat','text':'fixture','request_id':str(uuid4())},CONFIG['models'][0])
    r.store.update(run['id'],status='completed',owns_event=True)
    c.patch('/api/chat/sessions/'+s['id'],json={'archived':True})
    plan=session_deletion.preview(r,s['id']);real=session_deletion.scrub
    live_chat=Path(r.store.path)
    def interrupt_live_chat(path,value):
        if Path(path)==live_chat:raise OSError('injected repeated live chat interruption')
        return real(path,value)
    monkeypatch.setattr(session_deletion,'scrub',interrupt_live_chat)
    with pytest.raises(OSError):session_deletion.delete(r,s['id'],plan['fingerprint'])
    session_deletion.resume_pending(r)
    marker=r.directory/'deletions'/f'session-{s["id"]}.json';saved=json.loads(marker.read_text())
    assert saved['status']=='blocked'
    assert saved['progress']['stores']['conversations']['status']=='processing'
    monkeypatch.setattr(session_deletion,'scrub',real)
    assert session_deletion.delete(r,s['id'],plan['fingerprint'])['status']=='deleted'


def test_backend_does_not_display_unadmitted_model_text(control):
    c,r,_=control;s=session(c)
    legal_question='请补充当前需求涉及的具体事项。'
    def model(p,emit,bridge,stop):
        emit({'type':'assistant','text':'UNADMITTED_SENTINEL','phase':'answer','message':0})
        bridge('route_request',{'domain':'unclear','intent':'consult','reason':'需求不明','question':legal_question})
        emit({'type':'assistant','text':'UNADMITTED_SENTINEL','phase':'answer','message':1})
    r.runner=model;out=settled(c,send_auto(c,s,'帮我处理一下'))
    assert 'UNADMITTED_SENTINEL' not in json.dumps(out,ensure_ascii=False)
    assert legal_question in json.dumps(out,ensure_ascii=False) and out['run']['status']=='waiting_user'
