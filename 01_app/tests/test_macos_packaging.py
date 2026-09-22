"""Installed read-only software, independent writable knowledge and lifecycle checks."""
import errno
import fcntl
import hashlib
import json
from pathlib import Path
import plistlib
import threading
from types import SimpleNamespace

import pytest

from backend import paths, pi_subprocess
from scripts import macos_bundle as bundle
from scripts import build_macos_release as release
from scripts import macos_desktop as desktop
from scripts.refresh_knowledge_packages import refresh
from test_public_library_index import setup as seed_public


@pytest.fixture(autouse=True)
def isolate_service_instance(tmp_path, monkeypatch):
    from scripts import service_instance
    monkeypatch.setattr(service_instance, 'runtime_directory', lambda: tmp_path/'runtime-lock')


@pytest.fixture
def installed(tmp_path, monkeypatch):
    package = tmp_path/'安装 位置/NERO 信披系统.app'
    app = package/'Contents/Resources/01_app'
    app.mkdir(parents=True)
    home = tmp_path/'个人 资料'
    monkeypatch.setenv('NERO_DISCLOSURE_HOME', str(home))
    monkeypatch.setattr(paths, 'app_root', lambda start=None: Path(start).resolve() if start is not None else app)
    return package, app, home


def test_installed_paths_preserve_historical_prefixes_and_other_workspaces(installed,tmp_path):
    package, app, home = installed
    knowledge, local = home/'02_knowledge', home/'03_local'
    assert paths.knowledge_of(app) == knowledge
    assert paths.local_of(app) == local
    assert paths.app_of(knowledge) == app
    assert paths.resolve(knowledge,'work/documents/old.docx') == local/'work/documents/old.docx'
    assert paths.resolve(local,'data/public/originals/old.pdf') == knowledge/'data/public/originals/old.pdf'
    other = tmp_path/'another/01_app'
    assert paths.knowledge_of(other) == other.parent/'02_knowledge'
    assert paths.local_of(other) == other.parent/'03_local'
    assert paths.app_of(tmp_path/'legacy') == tmp_path/'legacy'


def test_installed_paths_reject_redirected_root(installed,tmp_path):
    _,app,home=installed
    home.mkdir(); (home/'03_local').symlink_to(tmp_path/'other',target_is_directory=True)
    with pytest.raises(ValueError,match='符号链接'):paths.local_of(app)


def make_seed(folder,app):
    from backend.knowledge_packages import CAPABILITIES
    seed_public(folder)
    for members in CAPABILITIES.values():
        for name in members:
            p=app/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
    p=folder/'data/public/boards/chinext/scenarios.json';p.write_text('[]')
    refresh(folder,folder/'packages')


def test_initial_knowledge_is_copied_once_and_user_edits_are_not_overwritten(installed,tmp_path):
    _,app,home=installed
    seed=tmp_path/'source';make_seed(seed,app)
    assert bundle.prepare_knowledge(home,seed,app)=='initialized'
    target=home/'02_knowledge/data/public/boards/chinext/catalog.json'
    value=json.loads(target.read_text());value['sources'][0]['text']='用户维护后的正文'
    target.write_text(json.dumps(value))
    before=target.read_bytes()
    assert bundle.prepare_knowledge(home,seed,app)=='existing_preserved'
    assert target.read_bytes()==before


def test_corrupt_seed_is_rejected_before_initialization(installed,tmp_path):
    _,app,home=installed
    seed=tmp_path/'source';make_seed(seed,app)
    (seed/'data/public/boards/chinext/catalog.json').write_text('{}')
    with pytest.raises(ValueError,match='快照不符'):bundle.prepare_knowledge(home,seed,app)
    assert not (home/'02_knowledge').exists()


def test_failed_copy_leaves_no_promoted_knowledge(installed,tmp_path,monkeypatch):
    _,app,home=installed
    seed=tmp_path/'source';make_seed(seed,app)
    monkeypatch.setattr(bundle.shutil,'copy2',lambda *a,**kw:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError,match='disk full'):bundle.prepare_knowledge(home,seed,app)
    assert not (home/'02_knowledge').exists()
    assert not list(home.glob('.knowledge-install-*'))


def test_no_data_inside_application(installed):
    package,app,home=installed
    with pytest.raises(ValueError,match='软件包外'):bundle.checked_home(app/'data',package)
    assert bundle.checked_home(home,package)==home


def test_worker_inherits_only_the_selected_data_scope(monkeypatch):
    monkeypatch.setenv('NERO_DISCLOSURE_HOME','/user/data home')
    monkeypatch.setenv('PROVIDER_API_KEY','must-not-pass')
    result=pi_subprocess.child_env()
    assert result['NERO_DISCLOSURE_HOME']=='/user/data home'
    assert 'PROVIDER_API_KEY' not in result


def test_port_permission_error_is_not_treated_as_occupied(monkeypatch):
    class Blocked:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def settimeout(self,*args):pass
        def setsockopt(self,*args):pass
        def connect(self,address):raise ConnectionRefusedError(errno.ECONNREFUSED,'refused')
        def bind(self,addr):raise PermissionError(errno.EACCES,'permission denied')
        def close(self):pass
    monkeypatch.setattr(desktop.socket,'socket',Blocked)
    with pytest.raises(RuntimeError,match='无法绑定'):desktop.listen(18765)


def test_packaged_ocr_keeps_review_state(tmp_path,monkeypatch):
    from backend import document_extract as extract
    import subprocess
    monkeypatch.setattr(extract,'packaged_ocr',lambda:Path('/bundled/ocr'))
    calls=[]
    def run(args,**kwargs):
        calls.append(args);return subprocess.CompletedProcess(args,0,json.dumps([{'text':'扫描文字','confidence':.9}]),'')
    monkeypatch.setattr(extract.subprocess,'run',run)
    result=extract.ocr(tmp_path/'image.png')
    assert result['text']=='扫描文字' and result['review_required'] is True
    assert calls==[['/bundled/ocr',str(tmp_path/'image.png')]]


def test_workspace_entry_cannot_redirect_existing_data(tmp_path,monkeypatch):
    app=tmp_path/'trial/01_app';app.mkdir(parents=True)
    monkeypatch.setattr(desktop,'APP',app)
    assert desktop.workspace_home(app.parent)==app.parent
    with pytest.raises(ValueError,match='试运行工作区'):
        desktop.workspace_home(tmp_path/'other')


def test_workspace_attaches_without_initializing_or_importing_backend(tmp_path,monkeypatch):
    from scripts import portable_runtime
    app=tmp_path/'trial/01_app';app.mkdir(parents=True)
    monkeypatch.setattr(desktop,'APP',app)
    monkeypatch.setattr(portable_runtime,'service_state',lambda *_:'ours')
    monkeypatch.setattr(desktop,'self_check',lambda *_:pytest.fail('existing service must not be reinitialized'))
    events=[];monkeypatch.setattr(desktop,'event',lambda kind,**kw:events.append((kind,kw)))
    desktop.serve(app.parent,None,8765,workspace=True)
    assert events==[('attached',{'url':'http://127.0.0.1:8765/','home':str(app.parent)})]
    assert not (app.parent/'.desktop.lock').exists()


def test_workspace_rejects_foreign_listener(tmp_path,monkeypatch):
    from scripts import portable_runtime
    app=tmp_path/'trial/01_app';app.mkdir(parents=True)
    monkeypatch.setattr(desktop,'APP',app)
    monkeypatch.setattr(portable_runtime,'service_state',lambda *_:'occupied')
    with pytest.raises(RuntimeError,match='其他工作区'):
        desktop.serve(app.parent,None,8765,workspace=True)


def test_workspace_main_reexecs_before_startup_imports(tmp_path,monkeypatch):
    app=tmp_path/'trial/01_app';app.mkdir(parents=True)
    monkeypatch.setattr(desktop,'APP',app)
    from scripts import portable_runtime
    calls=[]
    monkeypatch.setattr(portable_runtime,'reexec_workspace',lambda *args,**kwargs:calls.append((args,kwargs)) or True)
    monkeypatch.setattr(desktop,'serve',lambda *args,**kwargs:pytest.fail('old interpreter must not start workspace'))
    monkeypatch.setattr(desktop.sys,'argv',['macos_desktop.py','--workspace','--check','--port','18888'])
    desktop.main()
    assert calls and calls[0][0][0]==app and calls[0][0][1]==['--workspace','--check','--port','18888']


def test_workspace_help_stays_available_without_environment_bootstrap(tmp_path,monkeypatch):
    app=tmp_path/'trial/01_app';app.mkdir(parents=True)
    monkeypatch.setattr(desktop,'APP',app)
    from scripts import portable_runtime
    monkeypatch.setattr(portable_runtime,'reexec_workspace',lambda *args,**kwargs:pytest.fail('normal help must not require workspace bootstrap'))
    monkeypatch.setattr(desktop.sys,'argv',['macos_desktop.py','--workspace','--help'])
    with pytest.raises(SystemExit) as exc:desktop.main()
    assert exc.value.code==0


def test_workspace_main_reuses_existing_service_before_pointer_validation(tmp_path,monkeypatch):
    app=tmp_path/'trial/01_app';app.mkdir(parents=True)
    monkeypatch.setattr(desktop,'APP',app)
    from scripts import portable_runtime
    monkeypatch.setattr(portable_runtime,'service_state',lambda *args:'ours')
    monkeypatch.setattr(portable_runtime,'reexec_workspace',lambda *args:pytest.fail('existing service must attach first'))
    attached=[];monkeypatch.setattr(desktop,'serve',lambda *args,**kwargs:attached.append((args,kwargs)))
    monkeypatch.setattr(desktop.sys,'argv',['macos_desktop.py','--workspace','--port','18888'])
    desktop.main()
    assert attached and attached[0][1]['workspace'] is True


def test_release_source_copy_includes_vite_entry_and_public_config(tmp_path):
    destination=tmp_path/'source-copy';rows=release.copy_source(destination);by_path={row['path']:row for row in rows}
    required=('frontend/index.html','frontend/src/main.tsx','frontend/package.json','frontend/package-lock.json',
              'frontend/tsconfig.json','frontend/vite.config.ts','config/pi-models.example.json',
              'config/model-contract.json','config/workspace-layout.json')
    for relative in required:
        source=release.APP/relative;copied=destination/relative
        assert copied.is_file() and copied.read_bytes()==source.read_bytes()
        assert by_path[relative]['bytes']==source.stat().st_size and by_path[relative]['sha256']==release.digest(source)
    assert not list(destination.rglob('node_modules'))
    assert not list(destination.rglob('.venv'))
    assert not list(destination.rglob('03_local'))
    assert not list(destination.rglob('pi-models.json'))


def _serve_fixture(tmp_path,monkeypatch,parent_bytes,invoke_restart):
    app_root=tmp_path/'trial/01_app';app_root.mkdir(parents=True);home=app_root.parent
    (home/'02_knowledge').mkdir();monkeypatch.setattr(desktop,'APP',app_root)
    monkeypatch.setattr(desktop,'workspace_home',lambda value:home)
    from scripts import portable_runtime
    monkeypatch.setattr(portable_runtime,'service_state',lambda *args:'free')
    monkeypatch.setattr(desktop,'configure',lambda *args:None)
    monkeypatch.setattr(desktop,'self_check',lambda *args:{'status':'ok'})
    from backend import app as backend_app,knowledge_packages
    service=SimpleNamespace(restart=None);fake_app=SimpleNamespace(state=SimpleNamespace(service_control=service),mount=lambda *args,**kwargs:None)
    monkeypatch.setattr(backend_app,'create_app',lambda **kwargs:fake_app)
    monkeypatch.setattr(knowledge_packages,'load',lambda *args,**kwargs:None)
    monkeypatch.setattr(desktop,'read_live',lambda *args:'http://127.0.0.1:8877/')
    monkeypatch.setattr(desktop,'listen',lambda preferred,exact=False:(SimpleNamespace(close=lambda:None),8877))
    import fastapi.staticfiles
    monkeypatch.setattr(fastapi.staticfiles,'StaticFiles',lambda *args,**kwargs:object())
    import uvicorn
    monkeypatch.setattr(uvicorn,'Config',lambda *args,**kwargs:SimpleNamespace())
    class Server:
        started=True
        should_exit=False
        def __init__(self,config):pass
        def run(self,sockets):
            if invoke_restart:service.restart()
    monkeypatch.setattr(uvicorn,'Server',Server)
    monkeypatch.setattr(desktop,'event',lambda *args,**kwargs:None)
    release=threading.Event()
    class Input:
        def __init__(self,value):self.buffer=self;self.value=value
        def read(self,size):
            if self.value is None:
                release.wait()
                return b''
            return self.value
    monkeypatch.setattr(desktop.sys,'stdin',Input(parent_bytes))
    restarted=[]
    def restart(port):
        with (home/'.desktop.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(lock,fcntl.LOCK_UN)
        assert not (home/'03_local/var/desktop-service.json').exists()
        restarted.append(port)
    monkeypatch.setattr(desktop,'_exec_restart',restart)
    desktop.serve(home,None,8765,workspace=True)
    release.set()
    return restarted,service


def test_workspace_serve_binds_idle_restart_after_drain_and_keeps_actual_port(tmp_path,monkeypatch):
    restarted,service=_serve_fixture(tmp_path,monkeypatch,None,True)
    assert service.restart is not None and restarted==[8877]


def test_workspace_serve_does_not_restart_after_parent_pipe_eof(tmp_path,monkeypatch):
    restarted,service=_serve_fixture(tmp_path,monkeypatch,b'',True)
    assert service.restart is not None and restarted==[]


def test_restart_listener_refuses_port_fallback(monkeypatch):
    class Busy:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def settimeout(self,*args):pass
        def setsockopt(self,*args):pass
        def connect(self,address):raise ConnectionRefusedError(errno.ECONNREFUSED,'refused')
        def bind(self,address):raise OSError(errno.EADDRINUSE,'busy')
        def close(self):pass
    monkeypatch.setattr(desktop.socket,'socket',lambda:Busy())
    with pytest.raises(RuntimeError,match='重启目标端口'):
        desktop.listen(18876,exact=True)


def test_restart_handover_never_takes_a_live_listener(monkeypatch):
    class Serving:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def settimeout(self,*args):pass
        def connect(self,address):pass
        def bind(self,address):raise AssertionError('a live listener must not be rebound')
        def close(self):pass
    monkeypatch.setattr(desktop.socket,'socket',lambda:Serving())
    with pytest.raises(RuntimeError,match='重启目标端口'):desktop.listen(18877,exact=True)
