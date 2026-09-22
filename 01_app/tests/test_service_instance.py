"""Real process contention: no project data, model providers or installed apps."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys

import pytest

from scripts import service_instance as instance

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS process contract')
APP = Path(__file__).resolve().parents[1]

OWNER = '''
import json,sys,threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from scripts.service_instance import service_instance
with service_instance(sys.argv[1]) as lease:
    assert lease.owner
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'configuration_path':str(lease.directory/'pi-models.json')}).encode())
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    lease.publish(server.server_port)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    print(server.server_port,flush=True)
    sys.stdin.readline()
    server.shutdown();server.server_close()
'''


def start(script, home, *args):
    env=dict(os.environ, HOME=str(home), PYTHONPATH=str(APP))
    env.pop('NERO_SERVICE_LOCK_FD', None)
    return subprocess.Popen([sys.executable,'-u','-c',script,*map(str,args)],env=env,
                            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)


def line(child):
    assert select.select([child.stdout],[],[],10)[0], 'child did not signal readiness'
    value=child.stdout.readline().strip()
    assert value, child.stderr.read()
    return value


def stop(child):
    if child.poll() is None:
        child.stdin.write('\n');child.stdin.flush()
    try:child.communicate(timeout=10)
    except subprocess.TimeoutExpired:child.kill();child.communicate();raise


def test_shared_backend_reuses_owner_and_blocks_other_data(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    data=tmp_path/'data';child=start(OWNER,tmp_path,data)
    try:
        port=int(line(child))
        with instance.service_instance(data,timeout=1) as lease:
            assert not lease.owner and lease.url==f'http://127.0.0.1:{port}/'
        with pytest.raises(RuntimeError,match='另一资料目录'):
            with instance.service_instance(tmp_path/'other',timeout=1):pytest.fail('second backend')
        assert child.poll() is None
    finally:stop(child)
    assert not (instance.runtime_directory()/'service.json').exists()
    with instance.service_instance(data,timeout=1) as lease:assert lease.owner


def test_startup_race_and_crashed_owner_recovery(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    child=start("from scripts.service_instance import service_instance\nimport sys\nwith service_instance(sys.argv[1]) as lease:\n print('locked',flush=True)\n sys.stdin.readline()",tmp_path,tmp_path/'data')
    try:
        assert line(child)=='locked'
        with pytest.raises(RuntimeError,match='启动或退出中'):
            with instance.service_instance(tmp_path/'data',timeout=.2):pytest.fail('racing owner')
        # A stale receipt never grants ownership while a kernel lock is held.
        state=instance.runtime_directory()/'service.json'
        state.write_text(json.dumps({'directory':str(tmp_path/'data'),'port':1024,'pid':child.pid}))
        child.kill();child.communicate(timeout=10)
        with instance.service_instance(tmp_path/'data',timeout=.2) as lease:
            assert lease.owner and not state.exists()
    finally:stop(child)


def test_lock_survives_exec_restart(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    script='''
import os,sys
from scripts.service_instance import service_instance,exec_restart
with service_instance(sys.argv[1]):
    print('before',flush=True)
    sys.stdin.readline()
    exec_restart(sys.executable,[sys.executable,'-u','-c',sys.argv[2],sys.argv[1]],dict(os.environ))
'''
    child=start(script,tmp_path,tmp_path/'data',OWNER)
    try:
        assert line(child)=='before'
        child.stdin.write('\n');child.stdin.flush()
        port=int(line(child))
        with instance.service_instance(tmp_path/'data',timeout=1) as lease:
            assert lease.url==f'http://127.0.0.1:{port}/' and not lease.owner
    finally:stop(child)


@pytest.mark.parametrize('entry',['desktop','console','portable'])
def test_both_entrypoints_attach_before_initializing_backend(tmp_path,monkeypatch,entry):
    from scripts import macos_desktop, run, portable_runtime
    monkeypatch.setenv('HOME',str(tmp_path))
    home=tmp_path/'workspace';data=home/'03_local/var'
    child=start(OWNER,tmp_path,data)
    try:
        port=int(line(child))
        if entry=='desktop':
            monkeypatch.setattr(macos_desktop,'workspace_home',lambda value:home)
            monkeypatch.setattr(macos_desktop,'_serve',lambda *a:pytest.fail('duplicate backend'))
            events=[];monkeypatch.setattr(macos_desktop,'event',lambda kind,**kw:events.append((kind,kw)))
            macos_desktop.serve(home,None,port+1,workspace=True)
            assert events==[('attached',{'url':f'http://127.0.0.1:{port}/','home':str(home)})]
        elif entry=='portable':
            monkeypatch.setattr(portable_runtime.workspace_paths,'var',lambda root:data)
            monkeypatch.setattr(portable_runtime.subprocess,'Popen',lambda *a,**k:pytest.fail('duplicate backend'))
            monkeypatch.setattr(portable_runtime.webbrowser,'open',lambda *a:pytest.fail('duplicate page'))
            assert portable_runtime.launch(home,Path(sys.executable),None,port+1)==0
        else:
            monkeypatch.setattr(run,'serve',lambda *a:pytest.fail('duplicate backend'))
            monkeypatch.setattr(sys,'argv',['run.py','--data-dir',str(data),'--port',str(port+1)])
            run.main()
    finally:stop(child)
