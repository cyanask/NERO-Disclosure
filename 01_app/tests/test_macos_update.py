import json
from pathlib import Path
import plistlib
import pytest
from scripts import macos_bundle as bundle, macos_desktop as desktop, build_macos_update as builder


@pytest.fixture
def update(tmp_path,monkeypatch):
    source=tmp_path/'media/New.app';target=tmp_path/'Applications/Old.app';home=tmp_path/'custom-data'
    for app,version in ((source,'1.0.1'),(target,'1.0.0')):
        (app/'Contents/Resources/01_app').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':bundle.BUNDLE_ID,'CFBundleShortVersionString':version}))
        (app/'Contents/Resources/01_app/code.py').write_text(version)
    for name in ('02_knowledge','03_local'):(home/name).mkdir(parents=True)
    for name in ('02_knowledge/edited-law.json','03_local/conversations.sqlite3','03_local/pi-models.json','03_local/report.docx'):
        (home/name).write_bytes(('user-owned:'+name).encode())
    monkeypatch.setattr(bundle,'verify_payload',lambda path:{'version':'1.0.1'})
    def existing_only(selected,seed,app,progress):
        assert selected==home and seed is None
        assert (selected/'02_knowledge/edited-law.json').read_bytes().startswith(b'user-owned:')
        return 'existing_preserved'
    monkeypatch.setattr(bundle,'prepare_knowledge',existing_only)
    return source,target,home


def files(root):return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_update_preserves_all_user_files_and_keeps_old_app(update):
    source,target,home=update;before=files(home)
    result=bundle.install(source,target,home,None,replace=True,update_only=True)
    assert files(home)==before and result['knowledge']=='existing_preserved'
    assert (target/'Contents/Resources/01_app/code.py').read_text()=='1.0.1'
    assert Path(result['previous_app']).suffix=='.backup'
    assert (Path(result['previous_app'])/'Contents/Resources/01_app/code.py').read_text()=='1.0.0'


def test_updater_never_bootstraps_a_new_home(update,tmp_path):
    source,target,_=update;home=tmp_path/'not-existing'
    with pytest.raises(ValueError,match='原有资料'):bundle.install(source,target,home,None,replace=True,update_only=True)
    assert not home.exists()


def test_update_requires_original_app_and_replace(update,tmp_path):
    source,target,home=update
    with pytest.raises(ValueError,match='已安装'):bundle.install(source,target,home,None,update_only=True)
    with pytest.raises(ValueError,match='已安装'):bundle.install(source,tmp_path/'Absent.app',home,None,replace=True,update_only=True)


@pytest.mark.parametrize('version',['1.0.2','2.0.0','unrecognized'])
def test_update_rejects_newer_or_unknown_versions(update,version):
    source,target,home=update
    info=target/'Contents/Info.plist';value=plistlib.loads(info.read_bytes());value['CFBundleShortVersionString']=version
    info.write_bytes(plistlib.dumps(value));before=files(target)
    with pytest.raises(ValueError):bundle.install(source,target,home,None,replace=True,update_only=True)
    assert files(target)==before


def test_update_rejects_corrupt_payload_before_replacing(update,monkeypatch):
    source,target,home=update;before=files(target)
    monkeypatch.setattr(bundle,'verify_payload',lambda *_:(_ for _ in ()).throw(ValueError('invalid payload')))
    with pytest.raises(ValueError,match='invalid payload'):bundle.install(source,target,home,None,replace=True,update_only=True)
    assert files(target)==before and not list(target.parent.glob('*.previous-*'))


def test_update_failure_restores_original_app(update,monkeypatch):
    source,target,home=update;before=files(target);data=files(home);rename=Path.rename
    def fail_staging(path,destination):
        if path.name.startswith('.nero-install-'):raise OSError('injected replace failure')
        return rename(path,destination)
    monkeypatch.setattr(Path,'rename',fail_staging)
    with pytest.raises(OSError):bundle.install(source,target,home,None,replace=True,update_only=True)
    assert files(target)==before and files(home)==data
    assert not list(target.parent.glob('.nero-install-*'))


@pytest.mark.parametrize('extra',[['--snapshot','snapshot'],['--workspace'],[]])
def test_update_cli_cannot_be_used_as_migration_or_workspace(monkeypatch,extra):
    args=['macos_desktop.py','--update-only',*extra]
    if extra:args+=['--install-to','old.app']
    monkeypatch.setattr(desktop.sys,'argv',args)
    with pytest.raises(ValueError,match='程序更新'):desktop.main()


@pytest.mark.parametrize('invalid',['data','commit','arch','version','personal'])
def test_universal_builder_rejects_inconsistent_or_data_payload(tmp_path,monkeypatch,invalid):
    payloads={arch:tmp_path/arch for arch in ('arm64','x86_64')}
    for path in payloads.values():path.mkdir()
    def metadata(path):
        result={'version':'1.0.1','architecture':path.name,'software_only':True,'personal_data_included':False,'source_commit':'same'}
        if path.name=='arm64':
            if invalid=='commit':result['source_commit']='different'
            if invalid=='arch':result['architecture']='x86_64'
            if invalid=='version':result['version']='1.0.0'
            if invalid=='personal':result['personal_data_included']=True
        return result
    monkeypatch.setattr(builder,'verify_payload',metadata)
    if invalid=='data':(payloads['arm64']/'03_local').mkdir()
    with pytest.raises(ValueError):builder.validate_inputs(payloads,'1.0.1')
