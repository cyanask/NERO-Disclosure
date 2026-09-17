"""V1 library maintenance uses copied public fixtures and injects write failures."""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import pytest
from backend import library_admin as admin
from test_gates import gate_env,sample,command


def law():
    return {'id':'test-law-2024-a30','title':'隔离测试法源','instrument_id':'test-law-2024','article':'第三十条','source_kind':'official_rule','text':'仅为测试的条款，不是法律意见。','effective_from':'2024-01-01','effective_to':'2024-12-31','as_of':'2026-09-08','url':'https://www.neeq.com.cn/test-law','replaces_source_ids':['szse-chinext-2026-4.1.7']}


def update(c,collection,items,fp=None):
    fp=fp or c.get('/api/library/'+collection+'/manage',params={'board':'chinext'}).json()['fingerprint']
    return c.post('/api/library/'+collection+'/update',params={'board':'chinext'},json={'expected_fingerprint':fp,'items':items})


def test_batch_validation_precedes_any_canonical_write(gate_env):
    c,_,root=gate_env;p=root/'data/public/boards/chinext/catalog.json';before=p.read_bytes();history_before={x.name:x.read_bytes() for x in (p.parent/'history').glob('*') if x.is_file()}
    r=update(c,'laws',[law(),{**law(),'id':'bad','effective_from':'invalid'}]);assert r.status_code==422
    assert p.read_bytes()==before
    assert {x.name:x.read_bytes() for x in (p.parent/'history').glob('*') if x.is_file()}==history_before
    for invalid in ({'id':[]},{'id':'x','title':'bad','url':{}},{**law(),'replaces_source_ids':{}}, {**law(),'effective_to':[]}):
        assert update(c,'laws',[invalid]).status_code==422
    assert p.read_bytes()==before


def test_original_hash_preserved_and_stale_version_rejected(gate_env):
    c,_,root=gate_env
    state=c.get('/api/library/laws/manage',params={'board':'chinext'}).json();original=next(r for r in state['items'] if r.get('original_path'))
    r=update(c,'laws',[{'id':original['id'],'text':original['text']+'\n隔离测试说明','as_of':'2026-09-08'}],state['fingerprint'])
    assert r.status_code==200,r.text
    row=next(x for x in c.get('/api/library/laws/manage',params={'board':'chinext'}).json()['items'] if x['id']==original['id'])
    assert row['sha256']==original['sha256']
    assert row['text_sha256']==hashlib.sha256(row['text'].encode()).hexdigest()
    assert (root/r.json()['history']).is_file()
    assert update(c,'laws',[law()],state['fingerprint']).status_code==409
    assert update(c,'laws',[{'id':original['id'],'effective_from':'2000-01-01'}]).status_code==422


def test_atomic_replace_failure_preserves_old_catalog(gate_env,monkeypatch):
    c,_,root=gate_env;p=root/'data/public/boards/chinext/catalog.json';before=p.read_bytes();real=admin.atomic
    def fail(path,raw):
        if Path(path)==p:raise OSError('injected write failure')
        return real(path,raw)
    monkeypatch.setattr(admin,'atomic',fail)
    with pytest.raises(OSError):update(c,'laws',[law()])
    assert p.read_bytes()==before


def test_browser_blank_end_date_preserves_open_ended_law(gate_env):
    c,_,_=gate_env
    original=next(x for x in c.get('/api/library/laws/manage',params={'board':'chinext'}).json()['items'] if not x.get('effective_to'))
    r=update(c,'laws',[{**original,'title':original['title']+'（隔离维护）','effective_to':''}])
    assert r.status_code==200,r.text
    row=next(x for x in c.get('/api/library/laws/manage',params={'board':'chinext'}).json()['items'] if x['id']==original['id'])
    assert row['effective_to'] is None and row['effective_from']==original['effective_from']
    assert update(c,'laws',[{'id':original['id'],'effective_to':'2026-09-08'}]).status_code==422


def test_projection_failure_reports_committed_canonical_truth(gate_env,monkeypatch):
    c,_,root=gate_env
    def fail(*args,**kwargs):raise OSError('index unavailable')
    monkeypatch.setattr('scripts.sync_sqlite_library.sync_library_db',fail)
    r=update(c,'laws',[law()]);assert r.status_code==200 and r.json()['projection_warnings']
    assert c.get('/api/library/items/'+law()['id'],params={'board':'chinext'}).json()['text']==law()['text']


def test_law_rebind_resumes_only_after_new_candidate(gate_env):
    from test_agent_tasks import claimed,submit,candidate
    c,token,root=gate_env;e=sample(c)
    e=c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':{**e['facts'],'event_date':'2024-06-01'}}).json()
    assert command(c,e,'advance',stage='assessment').status_code==409
    rules=json.loads((root/'data/public/boards/chinext/rules.json').read_text())
    ids=next(r['source_ids'] for r in rules if r['event_kind']==e['kind'] and e['layer'] in r['layers'])
    replacements=[{**law(),'id':'test-2024-'+sid,'replaces_source_ids':[sid]} for sid in ids]
    assert update(c,'laws',replacements).status_code==200
    r=command(c,e,'law-bindings',bindings={sid:'test-2024-'+sid for sid in ids});assert r.status_code==200,r.text
    assert command(c,e,'advance',stage='assessment').status_code==409
    task,lease=claimed(c,e,token)
    value={**candidate(),'source_ids':['test-2024-'+ids[0]],
           'assessment_as_of':'2024-06-01'}
    value['facts'][0]['observed_at']='2024-06-01'
    # A replacement requires a genuinely reassessed candidate, including nested citations.
    value['matters'][0]['deadline_basis']=value['source_ids']
    value['matters'][0]['reasoning_items'][0].update(
        source_id=value['source_ids'][0],quote=law()['text'],locator='第三十条')
    assert submit(c,e,task,lease,token,value).status_code==200
    r=command(c,e,f"agent-tasks/{task['id']}/adopt");assert r.status_code==200,r.text
    assert command(c,e,'advance',stage='assessment').status_code==200
    # Official format still only applies from 2025; an assessment fix cannot bypass its plan Gate.
    assert command(c,e,'agent-tasks',stage='plan',instruction='test').status_code==409


def test_cli_invocation_is_import_safe_and_preserves_original(gate_env):
    c,_,root=gate_env;batch=root/'batch.json';batch.write_text(json.dumps([law()]))
    script=Path(__file__).resolve().parents[1]/'scripts/update_laws.py'
    result=subprocess.run([sys.executable,str(script),'--root',str(root),'--board','chinext','import',str(batch)],capture_output=True,text=True,cwd=root)
    assert result.returncode==0,result.stderr+result.stdout
    assert c.get('/api/library/items/'+law()['id'],params={'board':'chinext'}).status_code==200


def _profile_delete_fixture(tmp_path):
    board=tmp_path/'data/public/boards/chinext';board.mkdir(parents=True)
    profiles=board/'profiles.json';profiles.write_text(json.dumps([{'id':'audit-profile','library_board':'chinext','layers':['chinext']}]))
    profile=board/'profiles/audit-profile.json';profile.parent.mkdir();profile.write_text('{}')
    templates=tmp_path/'templates/boards/chinext/manifest.json';templates.parent.mkdir(parents=True);templates.write_text(json.dumps([{'id':'audit-template','profile_id':'audit-profile'}]))
    return profiles,profile,templates


def test_profile_delete_commits_with_projection_warning_and_preserves_history(tmp_path,monkeypatch):
    profiles,projection,templates=_profile_delete_fixture(tmp_path);real_unlink=Path.unlink
    monkeypatch.setattr(admin,'rebuild_index',lambda *args:None)
    def fail(path,*args,**kwargs):
        if Path(path)==projection:raise PermissionError('synthetic projection file lock')
        return real_unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',fail)
    result=admin.remove(tmp_path,'profiles',['audit-profile'],admin.sha(profiles.read_bytes()),'chinext')
    assert result['status']=='deleted' and result['projection_warnings']
    assert json.loads(profiles.read_text())==[] and json.loads(templates.read_text())==[]
    assert projection.is_file() and list((profiles.parent/'history').glob('profiles-*.json'))


def test_profile_delete_normal_projection_cleanup_has_no_warning(tmp_path,monkeypatch):
    profiles,projection,templates=_profile_delete_fixture(tmp_path)
    monkeypatch.setattr(admin,'rebuild_index',lambda *args:None)
    result=admin.remove(tmp_path,'profiles',['audit-profile'],admin.sha(profiles.read_bytes()),'chinext')
    assert result['status']=='deleted' and result['projection_warnings']==[]
    assert json.loads(profiles.read_text())==[] and json.loads(templates.read_text())==[] and not projection.exists()


def test_profile_delete_rejects_external_projection_directory_link(tmp_path,monkeypatch):
    profiles,projection,templates=_profile_delete_fixture(tmp_path)
    external=tmp_path/'external-profiles';external.mkdir();outside=external/'audit-profile.json';outside.write_bytes(b'keep outside')
    projection.unlink();(profiles.parent/'profiles').rmdir();(profiles.parent/'profiles').symlink_to(external,target_is_directory=True)
    monkeypatch.setattr(admin,'rebuild_index',lambda *args:None)
    result=admin.remove(tmp_path,'profiles',['audit-profile'],admin.sha(profiles.read_bytes()),'chinext')
    assert result['status']=='deleted' and result['projection_warnings']
    assert outside.read_bytes()==b'keep outside' and json.loads(profiles.read_text())==[] and json.loads(templates.read_text())==[]


def test_profile_delete_rejects_known_parent_traversal_projection_id(tmp_path,monkeypatch):
    profiles,projection,templates=_profile_delete_fixture(tmp_path)
    outside=profiles.parent/'outside.json';outside.write_bytes(b'keep outside')
    profiles.write_text(json.dumps([{'id':'../outside','library_board':'chinext','layers':['chinext']}]))
    monkeypatch.setattr(admin,'rebuild_index',lambda *args:None)
    result=admin.remove(tmp_path,'profiles',['../outside'],admin.sha(profiles.read_bytes()),'chinext')
    assert result['status']=='deleted' and result['projection_warnings']
    assert outside.read_bytes()==b'keep outside' and json.loads(profiles.read_text())==[] and json.loads(templates.read_text())==[{'id':'audit-template','profile_id':'audit-profile'}]


def test_profile_delete_canonical_write_failure_does_not_report_success(tmp_path,monkeypatch):
    profiles,projection,templates=_profile_delete_fixture(tmp_path);before_profiles=profiles.read_bytes();before_templates=templates.read_bytes()
    real_atomic=admin.atomic
    def fail(path,raw):
        if Path(path)==profiles:raise OSError('synthetic canonical write failure')
        return real_atomic(path,raw)
    monkeypatch.setattr(admin,'atomic',fail)
    with pytest.raises(OSError):admin.remove(tmp_path,'profiles',['audit-profile'],admin.sha(before_profiles),'chinext')
    assert profiles.read_bytes()==before_profiles and templates.read_bytes()==before_templates and projection.is_file()


def test_profile_invalid_fields_do_not_commit(gate_env):
    c,_,root=gate_env;state=c.get('/api/library/profiles/manage',params={'board':'chinext'}).json();p=state['items'][0]
    for fields in ({'sections':[{}]}, {'normative_source_ids':[{}]}, {'case_evidence':[{}]}, {'id':'../escape'}):
        assert update(c,'profiles',[{**p,**fields}]).status_code==422
    assert c.get('/api/library/profiles/manage',params={'board':'chinext'}).json()['fingerprint']==state['fingerprint']


def test_case_and_new_profile_are_manageable_and_project_into_templates(gate_env):
    c,_,root=gate_env
    state=c.get('/api/library/cases/manage',params={'board':'chinext'}).json()
    case=next(x for x in state['items'] if x.get('source_kind')=='official_case' and x.get('document_path') and admin.official_url(x.get('url')))
    r=update(c,'cases',[{'id':case['id'],'title':case['title']+'（隔离测试）'}]);assert r.status_code==200,r.text
    original=c.get('/api/library/profiles/manage',params={'board':'chinext'}).json()['items'][0]
    clone={**original,'id':'test-profile','title':'隔离测试文种','case_evidence':[],'scope_review_status':'format_and_case_evidence_pending'}
    r=update(c,'profiles',[clone]);assert r.status_code==200,r.text
    from backend.domain import Seeds
    from backend.library import applicable_templates
    templates=applicable_templates(Seeds(root),{'kind':clone['kind'],'layer':'chinext','facts':{'disclosure_profile_id':clone['id']}})
    assert len(templates)==1 and templates[0]['sections']==clone['sections']
    assert c.get('/api/library/items/test-profile',params={'board':'chinext'}).json()['normative_sources']
