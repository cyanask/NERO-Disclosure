"""Migration contracts exercised with three physical directories and isolated data."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import paths, stage_skills, system_governance as governance
from backend import announcement_history, file_ingestion, library_admin, knowledge_packages
from backend.app import create_app
from backend.domain import Seeds
from backend.model_credentials import ModelCredentialVault
from backend.public_library_index import status
from scripts.sync_sqlite_library import sync_library_db
from scripts.refresh_knowledge_packages import refresh
from test_public_library_index import setup as seed_public
from test_announcement_workspace import docx_bytes, upload, commit
from test_system_governance import backups
from conftest import ROOT, seed_tree


@pytest.fixture
def layout(tmp_path):
    app=tmp_path/'01_app';app.mkdir()
    knowledge=tmp_path/'02_knowledge';knowledge.mkdir()
    seed_public(knowledge)
    (knowledge/'data/public/boards/chinext/scenarios.json').write_text('[]')
    seed_tree(ROOT/'skills',app/'skills')
    local=tmp_path/'03_local'
    return app,knowledge,local


def test_first_start_creates_only_local_business_state_and_finds_software_methods(layout):
    app,knowledge,local=layout
    service=create_app(seed_root=app,auth_config={'allowed_hosts':['testserver']},pi_config={'models':[]})
    with TestClient(service) as client:
        meta=client.get('/api/meta')
        assert meta.status_code==200 and len(meta.json()['workflow']['stage_skills'])==4
        assert service.state.pi_runtime.root==knowledge
        assert service.state.pi_runtime.directory==local/'var'
    assert (local/'var/disclosure.sqlite3').is_file()
    assert (local/'var/conversations.sqlite3').is_file()
    assert not (app/'var').exists() and not (knowledge/'var').exists()
    assert stage_skills.get(knowledge,'assessment')['id']=='disclosure-duty-assessment'
    (app/'skills/registry.json').unlink()
    with pytest.raises(HTTPException):stage_skills.get(knowledge,'assessment')


@pytest.mark.parametrize('relative',[
    '../var/private.json','work/../../private.json','/tmp/private.json',
    r'C:\private.json',r'work\..\..\private.json','//host/share/file'])
def test_registered_paths_reject_traversal_and_absolute_paths(layout,relative):
    with pytest.raises(ValueError):paths.resolve(layout[1],relative)


def test_registered_paths_reject_links_outside_the_selected_category(layout,tmp_path):
    app,knowledge,local=layout
    local.mkdir()
    (knowledge/'data/escape').symlink_to(local,target_is_directory=True)
    with pytest.raises(ValueError):paths.resolve(knowledge,'data/escape/private.json')


def test_named_category_roots_cannot_redirect_to_another_workspace(layout,tmp_path):
    app,knowledge,local=layout
    outside=tmp_path/'another-workspace';outside.mkdir()
    local.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):paths.local_of(app)
    with pytest.raises(ValueError):paths.local_of(local)


def test_same_workspace_keeps_credential_namespace_but_a_copy_does_not(tmp_path):
    before=ModelCredentialVault(tmp_path/'old-home/var').service
    after=ModelCredentialVault(tmp_path/'old-home/03_local/var').service
    copied=ModelCredentialVault(tmp_path/'other-home/03_local/var').service
    assert before==after and copied!=before


def test_old_work_references_and_new_imports_remain_local(layout):
    app,knowledge,local=layout
    service=create_app(seed_root=knowledge,auth_config={'allowed_hosts':['testserver']},pi_config={'models':[]})
    with TestClient(service) as client:
        token=client.get('/api/session').json()['csrf_token']
        client.headers.update({'Origin':'http://testserver','X-CSRF-Token':token})
        announcement_history.register_company(knowledge,'chinext','300001','测试公司')
        raw=docx_bytes();prepared=upload(client,raw)
        assert prepared['original_path'].startswith('work/library-imports/')
        original=paths.resolve(knowledge,prepared['original_path'])
        assert original.is_relative_to(local) and original.read_bytes()==raw
        fetched=client.get('/api/library/imports/'+prepared['id']+'/original?board=chinext&company=300001')
        assert fetched.status_code==200 and fetched.content==raw
        applied=commit(client,prepared)
        assert applied.status_code==200,applied.text
        detail=client.get('/api/announcements/'+applied.json()['id']+'?board=chinext&company=300001').json()
        assert paths.resolve(knowledge,detail['original_path']).read_bytes()==raw
        assert not (knowledge/'work').exists()
        assert '文末正文不可丢失' in detail['pages'][0]['text']


def test_three_directory_edit_and_index_rebuild_keep_source_hashes(layout):
    app,knowledge,local=layout
    state=library_admin.state(knowledge,'laws','chinext')
    changed=copy.deepcopy(state['items'][0]);changed['title']='测试规则维护名称'
    result=library_admin.update(knowledge,'laws',[changed],state['fingerprint'],'chinext')
    assert result['status']=='updated'
    counts=sync_library_db(root=knowledge,board='chinext')
    assert counts['sources']==1 and status(knowledge,'chinext')['status']=='current'
    from backend.library import search
    found=search(Seeds(knowledge,'chinext'),'cases','供应链中断风险')
    assert found['retrieval_backend']=='sqlite_fts5+canonical_json' and found['passages'][0]['page']==2


def test_cleanup_restore_uses_local_backup_paths_and_preserves_live_databases(layout):
    app,knowledge,local=layout
    old=backups(local)
    # A separate rebuildable index stays in the knowledge category.
    from test_system_governance import database
    database(knowledge/'data/public/boards/chinext/disclosure_library.sqlite3')
    groups=governance.databases(knowledge)['groups']
    assert len(groups)==2 and any(g['id']=='var/disclosure.sqlite3' for g in groups)
    preview=governance.prepare(knowledge,local/'var','databases',['var/disclosure.sqlite3'])
    result=governance.execute(knowledge,local/'var',preview['id'])
    assert result['count']==2 and (local/'var/disclosure.sqlite3').exists()
    restored=governance.restore(knowledge,local/'var',preview['id'])
    assert restored['count']==2 and all(p.is_file() for p in old)
    assert not (knowledge/'var').exists()


def test_package_checks_dependencies_and_every_content_hash(layout):
    app,knowledge,local=layout
    for members in knowledge_packages.CAPABILITIES.values():
        for relative in members:
            target=app/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('fixture')
    company=knowledge/'data/client_announcements/chinext/300001'
    company.mkdir(parents=True);(company/'catalog.json').write_text('{"items":[]}')
    refresh(knowledge,knowledge/'packages')
    report=knowledge_packages.load(knowledge,app,full=True)
    assert len(report['packages'])==2 and report['files_checked']>10
    original=knowledge/'data/public/test/case.json'
    original.write_text(original.read_text().replace('首页摘要','首页改变'))
    with pytest.raises(ValueError,match='快照不符'):
        knowledge_packages.load(knowledge,app,full=True)
    index=knowledge/'packages/index.json';data=json.loads(index.read_text())
    data['packages']=[e for e in data['packages'] if e['id']=='chinext-announcements-300001']
    index.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='缺少依赖'):
        knowledge_packages.load(knowledge,app)


def test_workspace_manifest_uses_its_declared_path_base(layout):
    from backend import version_governance as version
    app,knowledge,local=layout
    sample=app/'sample.txt';sample.write_text('software')
    doc={'version':'test','path_base':'workspace','files_count':1,
         'files':[{'path':'01_app/sample.txt','bytes':sample.stat().st_size,
                   'sha256':version.digest(sample)}]}
    (app/'BUILD_MANIFEST.json').write_text(json.dumps(doc))
    parsed=version.build(app)
    assert parsed['error'] is None
    assert version.manifest_check(app,parsed)['status']=='metadata_match'
