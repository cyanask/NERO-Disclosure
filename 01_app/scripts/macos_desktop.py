"""Installed Mac lifecycle; the native window owns this process via a private pipe."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from scripts.macos_bundle import app_from_code, checked_home, install, prepare_knowledge


def event(kind, **values):
    print('NERO_EVENT ' + json.dumps({'event':kind, **values}, ensure_ascii=False), flush=True)


def progress(message):
    event('progress', message=message)


def configure(home, workspace=False):
    os.environ['NERO_DISCLOSURE_HOME'] = str(home)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTHONNOUSERSITE'] = '1'
    if workspace:
        from scripts.portable_runtime import node_path, platform_key
        node_bin = node_path(APP, platform_key()).parent
    else:node_bin = APP/'runtime/macos/node/bin'
    os.environ['PATH'] = str(node_bin) + ':/usr/bin:/bin:/usr/sbin:/sbin'
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):os.environ.pop(key, None)


def self_check(home, workspace=False):
    import importlib
    import importlib.metadata
    lock = APP/('requirements.lock.txt' if workspace else 'native/macos/requirements.lock.txt')
    for line in lock.read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            name, version = line.split('==')
            if importlib.metadata.version(name) != version:raise ValueError('依赖版本不符：' + name)
    for name in ('backend.app','docxtpl','pypdf','lxml.etree','openpyxl','et_xmlfile','backend.vendor.nero_office.reader'):
        importlib.import_module(name)
    if workspace:
        from scripts.portable_runtime import node_path, platform_key
        node = node_path(APP, platform_key())
    else:node = APP/'runtime/macos/node/bin/node'
    probe = subprocess.run([str(node), '--input-type=module', '-e',
        "await import('./worker.mjs'); for (const api of ['openai-responses','openai-completions','anthropic-messages','google-generative-ai','openai-codex-responses']) await import('@earendil-works/pi-ai/api/'+api);"],
        cwd=APP/'runtime/pi', capture_output=True, text=True, timeout=45)
    if probe.returncode:raise ValueError('AI 运行组件无法加载：' + probe.stderr[-2000:])
    from backend import paths, knowledge_packages, stage_skills
    report = knowledge_packages.load(home/'02_knowledge', APP)
    stage_skills.catalog(APP)
    helper = APP/'runtime/macos/bin/disclosure-ocr'
    if not workspace:subprocess.run([str(helper), '--version'], capture_output=True, check=True, timeout=10)
    if paths.app_of(home/'02_knowledge') != APP or paths.local_of(APP) != home/'03_local':
        raise ValueError('安装版数据根绑定不一致')
    return {'app_root':str(APP), 'knowledge_root':str(home/'02_knowledge'),
            'local_root':str(home/'03_local'), 'packages':report['packages'],
            'python':sys.version.split()[0], 'node':subprocess.check_output([str(node),'--version'],text=True).strip()}


def read_live(home):
    path = home/'03_local/var/desktop-service.json'
    try:
        value = json.loads(path.read_text())
        if value.get('home') != str(home):return None
        port = int(value['port'])
        if not 1024 <= port <= 65535:return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/chat/models',timeout=2) as response:
            metadata = json.loads(response.read(500000))
        if metadata.get('configuration_path') != str(home/'03_local/var/pi-models.json'):return None
        return f'http://127.0.0.1:{port}/'
    except (OSError, ValueError, KeyError, TypeError):return None


def listen(preferred,exact=False):
    ports=(preferred,) if exact else range(preferred, min(preferred+30, 65536))
    for port in ports:
        channel = socket.socket()
        try:channel.bind(('127.0.0.1', port))
        except OSError as exc:
            channel.close()
            if exc.errno == errno.EADDRINUSE:
                if exact:raise RuntimeError('重启目标端口已被其他服务占用，未接管') from exc
                continue
            raise RuntimeError('本机端口无法绑定：' + str(exc)) from exc
        channel.listen(128)
        return channel, port
    raise RuntimeError('未找到可用的本机端口，请关闭占用端口的软件后重试')


def _restart_args(port):
    args=list(sys.argv[1:]);result=[];found=False;index=0
    while index<len(args):
        value=args[index]
        if value=='--port' and index+1<len(args):
            result.extend(('--port',str(port)));found=True;index+=2;continue
        if value.startswith('--port='):
            result.append('--port='+str(port));found=True;index+=1;continue
        result.append(value);index+=1
    if not found:result.extend(('--port',str(port)))
    return result


def _exec_restart(port):
    env=dict(os.environ);env['NERO_DESKTOP_RESTART']='1'
    command=[sys.executable,'-B','-s','-u','-X','utf8',str(Path(__file__).resolve()),*_restart_args(port)]
    os.execve(sys.executable,command,env)


def workspace_home(home):
    home = checked_home(home, APP)
    if APP.name != '01_app' or home != APP.parent:
        raise ValueError('本机应用只能连接当前软件所在的试运行工作区')
    return home


def serve(home, seed, preferred, check=False, workspace=False):
    home = workspace_home(home) if workspace else checked_home(home, app_from_code(APP))
    restart_handoff=os.environ.get('NERO_DESKTOP_RESTART')=='1'
    if restart_handoff:os.environ.pop('NERO_DESKTOP_RESTART',None)
    if workspace and not check:
        # Reuse an existing source launcher without taking ownership of it.
        from scripts.portable_runtime import service_state
        state = service_state(APP, preferred)
        if state == 'ours' and not restart_handoff:
            event('attached', url=f'http://127.0.0.1:{preferred}/', home=str(home)); return
        if state != 'free':raise RuntimeError('本机端口由其他工作区占用，未启动或停止任何服务')
    home.mkdir(parents=True, exist_ok=True)
    with (home/'.desktop.lock').open('a+b') as lock:
        try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            url = read_live(home)
            if url:event('attached', url=url, home=str(home)); return
            raise RuntimeError('本数据目录已有启动任务，请回到原启动器查看进度')
        if restart_handoff:
            from scripts.portable_runtime import service_state
            if service_state(APP,preferred)!='free':raise RuntimeError('重启目标端口已被其他服务占用，未接管或启动其他工作区')
        configure(home, workspace)
        progress('正在加载个人知识库')
        if workspace:
            from backend.knowledge_packages import load
            load(home/'02_knowledge', APP)
        else:prepare_knowledge(home, seed, APP, progress)
        local = home/'03_local/var'
        local.mkdir(parents=True, exist_ok=True)
        progress('正在检查内置运行环境')
        report = self_check(home, workspace)
        if check:event('checked', **report); return
        stopped = threading.Event();parent_stopped=threading.Event();restart_requested=False;restart_succeeded=False;port=None
        def watch():
            try:sys.stdin.buffer.read(1)
            finally:parent_stopped.set();stopped.set()
        watch_thread=threading.Thread(target=watch, daemon=True);watch_thread.start()
        from backend.app import create_app
        from fastapi.staticfiles import StaticFiles
        import uvicorn
        progress('正在启动工作台')
        app = create_app(data_dir=local, seed_root=home/'02_knowledge')
        def request_restart():
            nonlocal restart_requested
            restart_requested=True
            server.should_exit=True
        app.state.service_control.restart=request_restart
        app.mount('/', StaticFiles(directory=APP/'frontend/dist', html=True), name='workbench')
        channel, port = listen(preferred,exact=restart_handoff)
        state_path = local/'desktop-service.json'
        state_path.write_text(json.dumps({'home':str(home),'pid':os.getpid(),'port':port}),encoding='utf-8')
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False))
        def status():
            deadline = time.monotonic()+45
            while not server.started and not stopped.is_set() and time.monotonic()<deadline:time.sleep(.1)
            if server.started and not stopped.is_set():
                # Binding alone is not ready: the application must identify the selected data root.
                if read_live(home):event('ready', url=f'http://127.0.0.1:{port}/', home=str(home), pid=os.getpid())
                else:event('error', message='服务身份检查未通过'); stopped.set()
            elif not stopped.is_set():event('error',message='启动超时，请查看日志'); stopped.set()
            stopped.wait(); server.should_exit=True
        threading.Thread(target=status,daemon=True).start()
        try:
            server.run(sockets=[channel]);restart_succeeded=True
        finally:
            stopped.set(); channel.close()
            if state_path.exists():state_path.unlink()
            event('stopped', message='工作台已停止，资料已保留')
        watch_thread.join(timeout=.2)
    if restart_succeeded and restart_requested and not parent_stopped.is_set():_exec_restart(port)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-home',type=Path,default=Path.home()/'Library/Application Support/NERO Disclosure')
    parser.add_argument('--seed',type=Path)
    parser.add_argument('--install-to',type=Path)
    parser.add_argument('--snapshot',type=Path)
    parser.add_argument('--replace',action='store_true')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--workspace',action='store_true')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:raise ValueError('端口范围无效')
    if args.workspace:
        if args.install_to:raise ValueError('本机工作区入口不执行安装或数据复制')
        from scripts.portable_runtime import reexec_workspace, service_state
        if not args.check and service_state(APP,args.port)!='free':
            serve(args.data_home, None, args.port, False, workspace=True)
            return
        if reexec_workspace(APP,sys.argv[1:],script=__file__):return
        serve(args.data_home, None, args.port, args.check, workspace=True)
        return
    bundle=app_from_code(APP)
    seed=args.seed or bundle.parent/'02_knowledge'
    if args.snapshot:
        if not args.install_to:raise ValueError('完整迁移快照只用于安装，不用于普通启动')
        import signal
        def cancel_install(signum,frame):raise KeyboardInterrupt('安装已取消')
        signal.signal(signal.SIGTERM,cancel_install)
        from scripts.migration_install import restore
        result=restore(bundle,args.install_to,args.data_home,args.snapshot,
                       replace=args.replace,progress=progress)
        event('installed',**result)
        return
    if args.install_to:
        home=checked_home(args.data_home,bundle);home.mkdir(parents=True,exist_ok=True)
        with (home/'.desktop.lock').open('a+b') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('请先退出正在运行的信披系统再安装或更新') from None
            result=install(bundle,args.install_to,home,seed,replace=args.replace,progress=progress)
            event('installed',**result)
    else:serve(args.data_home,seed,args.port,args.check)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        event('error',message=str(exc))
        raise SystemExit(1)
