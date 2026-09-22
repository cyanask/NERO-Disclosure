"""V1 setup contracts: no downloads, package installation or real model calls."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from scripts import portable_runtime as setup


@pytest.fixture(autouse=True)
def isolate_service_instance(tmp_path, monkeypatch):
    from scripts import service_instance
    monkeypatch.setattr(service_instance, 'runtime_directory', lambda: tmp_path/'runtime-lock')


@pytest.fixture
def project(tmp_path):
    root=tmp_path/'新电脑 项目';(root/'runtime/pi').mkdir(parents=True);(root/'var').mkdir()
    (root/'var/keep.json').write_text('{"original": true}')
    (root/'requirements.lock.txt').write_text('example==1.0\n')
    shutil.copy2(setup.ROOT/'runtime/portable-runtime.lock.tsv',root/'runtime/portable-runtime.lock.tsv')
    (root/'runtime/pi/package.json').write_text('{"dependencies": {}}')
    (root/'runtime/pi/package-lock.json').write_text('{}')
    return root


def test_checksum_mismatch_never_installs_or_replaces_existing_file(project,monkeypatch):
    cache=project/'cache';cache.mkdir();existing=cache/'runtime.bin';existing.write_bytes(b'old preserved')
    row={'url':'https://example.invalid/runtime.bin','sha256':hashlib.sha256(b'expected').hexdigest()}
    monkeypatch.setattr(setup.urllib.request,'urlopen',lambda *a,**kw:pytest.fail('Existing invalid file must not be silently replaced'))
    with pytest.raises(RuntimeError,match='校验失败'):setup.download(row,cache)
    assert existing.read_bytes()==b'old preserved'


def test_moved_macos_environment_rebuilds_without_touching_old_or_data(project,monkeypatch):
    key='macos-arm64';base=project/'runtime/portable'/key;base.mkdir(parents=True)
    pointer=base/'current-python.json';old=base/'envs/old';(old/'bin').mkdir(parents=True);(old/'bin/python').write_text('old interpreter')
    pointer.write_text(json.dumps({'identity':{'root':'/old computer/project'},'directory':'envs/old'}))
    calls=[]
    def run(command,**kw):
        calls.append(command)
        if 'venv' in command:
            target=Path(command[-1]);(target/'bin').mkdir(parents=True);(target/'bin/python').write_text('fixture interpreter')
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(setup.subprocess,'run',run)
    monkeypatch.setattr(setup,'check_python',lambda *a:subprocess.CompletedProcess([],0))
    python=setup.prepare_macos_python(project,key,project/'uv')
    assert python!=old/'bin/python' and python.is_relative_to(base)
    assert (old/'bin/python').read_text()=='old interpreter'
    assert (project/'var/keep.json').read_text()=='{"original": true}'
    assert json.loads(pointer.read_text())['identity']['root']==str(project.resolve())
    assert len(calls)==2
    assert str(project/'requirements.lock.txt') in calls[1] and '-r' not in calls[1]
    assert setup.prepare_macos_python(project,key,project/'uv')==python and len(calls)==2


def test_failed_python_check_does_not_activate_new_environment(project,monkeypatch):
    key='macos-arm64';base=project/'runtime/portable'/key;base.mkdir(parents=True)
    pointer=base/'current-python.json';pointer.write_text('{"directory":"old","identity":{"root":"elsewhere"}}')
    original=pointer.read_bytes()
    monkeypatch.setattr(setup.subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess([],0))
    monkeypatch.setattr(setup,'check_python',lambda *a:subprocess.CompletedProcess([],1))
    with pytest.raises(RuntimeError,match='依赖检查未通过'):setup.prepare_macos_python(project,key,project/'uv')
    assert pointer.read_bytes()==original


def test_failed_npm_restores_original_modules_and_marker(project,monkeypatch):
    package=project/'runtime/pi';modules=package/'node_modules';modules.mkdir()
    (modules/'original.txt').write_text('old dependencies')
    marker=package/'.portable-install.json';marker.write_text('{"old":true}')
    def fail(command,**kw):
        assert 'ci' in command and '--ignore-scripts' in command
        modules.mkdir();(modules/'new.txt').write_text('partial install')
        raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(setup.subprocess,'run',fail)
    with pytest.raises(subprocess.CalledProcessError):setup.ensure_pi(project,project/'node/bin/node','macos-arm64')
    assert (modules/'original.txt').read_text()=='old dependencies'
    assert marker.read_text()=='{"old":true}'
    assert any((p/'new.txt').is_file() for p in package.glob('node_modules.failed-*'))


def test_existing_dependency_link_is_not_followed_or_replaced(project,tmp_path):
    target=tmp_path/'external';target.mkdir();(target/'keep').write_text('outside')
    modules=project/'runtime/pi/node_modules';modules.symlink_to(target,target_is_directory=True)
    with pytest.raises(RuntimeError,match='外部链接'):setup.ensure_pi(project,project/'node','macos-arm64')
    assert modules.is_symlink() and (target/'keep').read_text()=='outside'


def test_running_runtime_lock_prevents_dependency_change(project):
    with setup.installation_lock(project):
        with pytest.raises(RuntimeError,match='运行中的服务'):
            with setup.installation_lock(project):pytest.fail('second lock acquired')


def test_unknown_port_owner_is_not_launched_or_opened(project,monkeypatch):
    monkeypatch.setattr(setup,'service_state',lambda *a:'occupied')
    monkeypatch.setattr(setup.subprocess,'Popen',lambda *a,**kw:pytest.fail('Must not start or stop another service'))
    monkeypatch.setattr(setup.webbrowser,'open',lambda *a:pytest.fail('Must not open the other service'))
    with pytest.raises(RuntimeError,match='其他服务占用'):setup.launch(project,Path('python'),Path('node'),8765)


def test_existing_project_service_reuses_page_without_install_or_spawn(project,monkeypatch):
    opened=[];monkeypatch.setattr(setup,'service_state',lambda *a:'ours')
    monkeypatch.setattr(setup.webbrowser,'open',opened.append)
    monkeypatch.setattr(setup.subprocess,'Popen',lambda *a,**kw:pytest.fail('Existing service must be reused'))
    assert setup.launch(project,Path('python'),None,8878)==0
    assert opened==([] if setup.sys.platform=='darwin' else ['http://127.0.0.1:8878/'])


def test_missing_built_asset_blocks_setup_before_model_or_data_work(project):
    for name in ('frontend/dist/index.html','data/public/boards/chinext/catalog.json',
                 'data/public/boards/chinext/profiles.json','data/public/boards/chinext/instruments.json',
                 'data/public/boards/chinext/rules.json','skills/registry.json',
                 'templates/boards/chinext/manifest.json'):
        p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    (project/'frontend/dist/index.html').write_text('<script src="/assets/missing.js"></script>')
    with pytest.raises(RuntimeError,match='missing.js'):setup.project_files(project)
    assert (project/'var/keep.json').read_text()=='{"original": true}'


def test_child_environment_does_not_reuse_old_python_paths():
    original={'PATH':'existing','HOME':'unchanged-home','PYTHONHOME':'old machine','PYTHONPATH':'old modules','VIRTUAL_ENV':'old venv'}
    env=setup.environment(Path('/new location/node'),original)
    assert env['HOME']=='unchanged-home' and env['PATH'].startswith('/new location')
    assert not {'PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'}&env.keys()
    assert original['PYTHONHOME']=='old machine'


def test_external_business_directory_blocks_portable_setup(project,tmp_path):
    external=tmp_path/'external data';external.mkdir()
    (project/'data').symlink_to(external,target_is_directory=True)
    with pytest.raises(RuntimeError,match='项目外部'):setup.project_files(project)
    assert list(external.iterdir())==[]


def test_project_files_reads_utf8_dist_index_explicitly(project,monkeypatch):
    required=('frontend/dist/index.html','runtime/pi/package-lock.json','data/public/boards/chinext/catalog.json',
              'data/public/boards/chinext/profiles.json','data/public/boards/chinext/instruments.json',
              'data/public/boards/chinext/rules.json','templates/boards/chinext/manifest.json','skills/registry.json')
    for relative in required:
        path=project/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('<html>中文</html>',encoding='utf-8')
    index=project/'frontend/dist/index.html';original=Path.read_text
    def guarded(path,*args,**kwargs):
        if path==index:assert kwargs.get('encoding')=='utf-8'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    setup.project_files(project)


def test_workspace_python_reexecs_only_into_validated_pointer(project,monkeypatch):
    key='macos-arm64';base=project/'runtime/portable'/key;target=base/'envs/new';(target/'bin').mkdir(parents=True)
    python=target/'bin/python';python.write_text('prepared')
    identity={'root':str(project.resolve()),'platform':key,'python_version':setup.PYTHON_VERSION,
              'lock_sha256':setup.sha(project/'requirements.lock.txt')}
    base.mkdir(parents=True,exist_ok=True);(base/'current-python.json').write_text(json.dumps({'identity':identity,'directory':'envs/new'}))
    script=project/'scripts/macos_desktop.py';script.parent.mkdir(parents=True);script.write_text('')
    monkeypatch.setattr(setup,'check_python',lambda *args:subprocess.CompletedProcess([],0))
    monkeypatch.setattr(setup.sys,'prefix',str(project/'old-env'))
    calls=[];monkeypatch.setattr(setup.os,'execve',lambda *args:calls.append(args))
    assert setup.reexec_workspace(project,['--workspace','--check'],key,script=script)
    assert calls
    command=calls[0][1]
    assert command[0]==str(python) and str(script) in command
    script_index=command.index(str(script))
    assert command[script_index+1:]==['--workspace','--check']
    assert calls[0][2]['PYTHONUTF8']=='1' and not {'PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'}&calls[0][2].keys()


def test_workspace_python_rejects_pointer_redirect_and_reader_probe_is_explicit(project,monkeypatch,tmp_path):
    key='macos-arm64';base=project/'runtime/portable'/key;base.mkdir(parents=True)
    target=tmp_path/'outside';target.mkdir();(base/'current-python.json').symlink_to(target/'pointer')
    with pytest.raises(RuntimeError,match='指针缺失或为符号链接'):setup.workspace_python(project,key)
    (base/'current-python.json').unlink();(base/'current-python.json').write_text('[]')
    with pytest.raises(RuntimeError,match='指针结构无效'):setup.workspace_python(project,key)
    command=[]
    monkeypatch.setattr(setup.subprocess,'run',lambda args,**kwargs:(command.append(args) or subprocess.CompletedProcess(args,1,stderr='missing')))
    setup.check_python(Path('python'),project/'requirements.lock.txt')
    script=command[0][4]
    assert 'openpyxl' in script and 'et_xmlfile' in script and 'backend.vendor.nero_office.reader' in script
