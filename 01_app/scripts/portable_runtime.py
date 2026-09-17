"""Project-local environment preparation shared by the existing launchers.

No global installation, model login, database migration or project compression.
Copied virtual environments are never selected by their old absolute paths.
"""
import argparse
import csv
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import webbrowser
import zipfile
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
PYTHON_VERSION='3.13.12'


def cache_root(root,key):
    return workspace_paths.local_of(root)/'cache/portable'/key


def history_root(root,component):
    if workspace_paths.local_of(root)==Path(root).resolve():
        return Path(root)/'runtime'/component
    target=workspace_paths.resolve(root,'var/backups/runtime/'+component)
    target.mkdir(parents=True,exist_ok=True)
    return target


@contextmanager
def installation_lock(root):
    """Use the same file lock as the live Pi runtime while replacing dependencies."""
    directory=workspace_paths.var(root);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'pi-runtime.lock').open('a+b') as handle:
        try:
            if os.name=='nt':
                import msvcrt
                handle.seek(0)
                if not handle.read(1):handle.write(b'0');handle.flush()
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise RuntimeError('本项目有运行中的服务或配置程序；未修改环境，请先关闭原窗口') from None
        try:yield
        finally:
            if os.name=='nt':handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


def sha(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def platform_key():
    machine=platform.machine().lower()
    if sys.platform=='darwin' and tuple(int(v) for v in platform.mac_ver()[0].split('.')[:2])<(13,5):
        raise RuntimeError('本运行包要求 macOS 13.5 或更新版本')
    if sys.platform=='win32' and machine in ('amd64','x86_64'):return 'windows-x64'
    if sys.platform=='darwin' and machine in ('arm64','aarch64'):return 'macos-arm64'
    if sys.platform=='darwin' and machine in ('x86_64','amd64'):return 'macos-x64'
    raise RuntimeError('一键入口支持 Windows x64、macOS Apple Silicon / Intel；当前系统不在支持范围')


def record(root,key):
    with (root/'runtime/portable-runtime.lock.tsv').open(encoding='utf-8') as file:
        rows=[row for row in csv.DictReader(file,delimiter='\t') if row['resource']==key]
    if len(rows)!=1 or len(rows[0]['sha256'])!=64:raise RuntimeError('运行组件锁文件不完整')
    return rows[0]


def atomic_json(path,value):
    if path.is_symlink():raise RuntimeError('运行状态文件不能是符号链接')
    temporary=path.with_name(path.name+'.'+uuid4().hex[:8]+'.next')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,path)


def download(row,cache):
    cache.mkdir(parents=True,exist_ok=True);target=cache/row['url'].rsplit('/',1)[1]
    if target.exists():
        if target.is_symlink() or sha(target)!=row['sha256']:raise RuntimeError('已下载组件校验失败；已保留原件，请联系维护者')
        return target
    temporary=target.with_name(target.name+'.'+uuid4().hex[:8]+'.part')
    with urllib.request.urlopen(row['url'],timeout=60) as response,temporary.open('xb') as output:
        shutil.copyfileobj(response,output,1024*1024)
    if sha(temporary)!=row['sha256']:raise RuntimeError('组件下载校验失败；未安装下载内容')
    os.replace(temporary,target)
    return target


def environment(node=None,base=None):
    env=dict(base if base is not None else os.environ)
    for name in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'):env.pop(name,None)
    if node:env['PATH']=str(Path(node).parent)+os.pathsep+env.get('PATH','')
    env['PYTHONUTF8']='1'
    env['PYTHONNOUSERSITE']='1'
    return env


def node_path(root,key):
    row=record(root,'node-'+key)
    folder=row['url'].rsplit('/',1)[1].removesuffix('.tar.gz').removesuffix('.zip')
    return root/'runtime/portable'/key/folder/('node.exe' if key.startswith('windows') else 'bin/node')


def ensure_node(root,key):
    row=record(root,'node-'+key);node=node_path(root,key)
    if not node.is_file():
        parent=root/'runtime/portable'/key;parent.mkdir(parents=True,exist_ok=True)
        archive=download(row,parent/'downloads')
        with tempfile.TemporaryDirectory(prefix='node-stage-',dir=parent) as temporary:
            stage=Path(temporary)
            if archive.suffix=='.zip':
                with zipfile.ZipFile(archive) as bundle:
                    for item in bundle.infolist():
                        if not (stage/item.filename).resolve().is_relative_to(stage.resolve()):raise RuntimeError('组件包路径无效')
                    bundle.extractall(stage)
            else:
                with tarfile.open(archive) as bundle:bundle.extractall(stage,filter='data')
            folders=list(stage.iterdir())
            if len(folders)!=1 or not folders[0].is_dir():raise RuntimeError('Node.js 发行目录无效')
            target=parent/folders[0].name
            if target.exists():raise RuntimeError('Node.js 目录不完整，已保留原目录，请联系维护者')
            folders[0].rename(target)
    result=subprocess.run([str(node),'--version'],capture_output=True,text=True,timeout=15,env=environment(node))
    if result.returncode or result.stdout.strip()!='v'+row['version']:raise RuntimeError('项目 Node.js 版本或执行检查未通过')
    return node


def pi_ready(root,node,key):
    package=root/'runtime/pi';modules=package/'node_modules'
    if modules.is_symlink() or getattr(modules,'is_junction',lambda:False)():return False
    try:
        marker=json.loads((package/'.portable-install.json').read_text())
        expected={'platform':key,'lock_sha256':sha(package/'package-lock.json'),'node_version':record(root,'node-'+key)['version']}
        if marker!=expected:return False
        for name,version in json.loads((package/'package.json').read_text())['dependencies'].items():
            if json.loads((modules/name/'package.json').read_text())['version']!=version:return False
        code="await import('./worker.mjs'); for (const api of ['openai-responses','openai-completions','anthropic-messages','google-generative-ai','openai-codex-responses']) await import('@earendil-works/pi-ai/api/'+api);"
        return subprocess.run([str(node),'--input-type=module','-e',code],cwd=package,env=environment(node),capture_output=True,timeout=30).returncode==0
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):return False


def ensure_pi(root,node,key):
    if pi_ready(root,node,key):return
    package=root/'runtime/pi';modules=package/'node_modules'
    if modules.is_symlink() or getattr(modules,'is_junction',lambda:False)():raise RuntimeError('Pi 依赖目录为外部链接，未自动覆盖')
    marker=package/'.portable-install.json'
    if marker.is_symlink():raise RuntimeError('Pi 安装记录不能是符号链接')
    prior_marker=marker.read_bytes() if marker.exists() else None
    history=history_root(root,'pi')
    previous=history/('node_modules.previous-'+uuid4().hex[:8])
    if modules.exists():modules.rename(previous)
    npm=node.parent/'node_modules/npm/bin/npm-cli.js' if key.startswith('windows') else node.parent.parent/'lib/node_modules/npm/bin/npm-cli.js'
    try:
        subprocess.run([str(node),str(npm),'ci','--ignore-scripts','--no-audit','--no-fund','--cache',str(cache_root(root,key)/'npm-cache')],
            cwd=package,env=environment(node),check=True,timeout=600)
        atomic_json(package/'.portable-install.json',{'platform':key,'lock_sha256':sha(package/'package-lock.json'),'node_version':record(root,'node-'+key)['version']})
        if not pi_ready(root,node,key):raise RuntimeError('Pi 依赖导入检查未通过')
    except Exception:
        # Retain the failed attempt and put the original dependency directory back.
        if modules.exists():modules.rename(history/('node_modules.failed-'+uuid4().hex[:8]))
        if previous.exists():previous.rename(modules)
        if prior_marker is not None:marker.write_bytes(prior_marker)
        elif marker.exists():marker.unlink()
        raise


def check_python(python,lock):
    code="""import importlib,importlib.metadata,json,sys
from pathlib import Path
if sys.version_info[:3]!=(3,13,12):raise RuntimeError('Python version mismatch')
for line in Path(sys.argv[1]).read_text().splitlines():
 if line.strip() and not line.startswith('#'):
  name,version=line.strip().split('==')
  if importlib.metadata.version(name)!=version:raise RuntimeError('Dependency version mismatch: '+name)
for name in ('fastapi','uvicorn','sqlalchemy','docxtpl','lxml.etree','pydantic_core','cryptography.hazmat.bindings._rust','openpyxl','et_xmlfile','backend.vendor.nero_office.reader'):importlib.import_module(name)
print(json.dumps({'python':sys.version.split()[0],'prefix':sys.prefix}))
"""
    return subprocess.run([str(python),'-X','utf8','-c',code,str(lock)],cwd=Path(lock).parent,env=environment(),capture_output=True,text=True,timeout=30)


def _lexical_child(base,path,allow_final_link=False):
    """Check a selected root and its children without accepting redirects."""
    base=Path(base).absolute();path=Path(path).absolute()
    if base.is_symlink():raise RuntimeError('运行环境根目录不能是符号链接')
    try:relative=path.relative_to(base)
    except ValueError:raise RuntimeError('运行环境路径超出当前工作区') from None
    current=base
    for index,part in enumerate(relative.parts):
        current=current/part
        if not current.is_symlink():continue
        if not allow_final_link or index!=len(relative.parts)-1:
            raise RuntimeError('运行环境路径含外部链接')
        try:
            if not current.resolve(strict=True).is_relative_to(base.resolve()):raise RuntimeError('运行环境链接指向工作区外部')
        except OSError as exc:raise RuntimeError('运行环境链接无法验证') from exc
    return path


def workspace_python(root,key=None):
    """Validate the prepared workspace venv and its real Office reader imports."""
    root=Path(root).absolute()
    if root.is_symlink():raise RuntimeError('workspace 根目录不能是符号链接')
    key=key or platform_key();base=_lexical_child(root,root/'runtime/portable'/key)
    pointer=base/'current-python.json'
    if pointer.is_symlink() or not pointer.is_file():raise RuntimeError('workspace Python 指针缺失或为符号链接')
    try:saved=json.loads(pointer.read_text(encoding='utf-8'))
    except (OSError,ValueError,UnicodeError) as exc:raise RuntimeError('workspace Python 指针无法读取') from exc
    lock=root/'requirements.lock.txt'
    if lock.is_symlink() or not lock.is_file():raise RuntimeError('workspace Python 锁文件缺失或为符号链接')
    if not isinstance(saved,dict):raise RuntimeError('workspace Python 指针结构无效')
    expected={'root':str(root.resolve()),'platform':key,'python_version':PYTHON_VERSION,'lock_sha256':sha(lock)}
    if saved.get('identity')!=expected:raise RuntimeError('workspace Python 指针与当前锁文件或工作区不一致')
    directory=saved.get('directory')
    if not isinstance(directory,str) or not directory or Path(directory).is_absolute() or PureWindowsPath(directory).drive or '..' in Path(directory).parts:
        raise RuntimeError('workspace Python 目录不是受控相对路径')
    target=_lexical_child(base,base/Path(directory));python=_lexical_child(base,target/'bin/python',allow_final_link=True)
    if not python.is_file():raise RuntimeError('workspace Python 尚未准备完成')
    try:result=check_python(python,lock)
    except (OSError,subprocess.SubprocessError) as exc:raise RuntimeError('workspace Python 依赖检查无法执行') from exc
    if result.returncode!=0:raise RuntimeError('workspace Python 依赖或 Office reader 未就绪：'+(result.stderr or result.stdout)[-1200:])
    return python


def reexec_workspace(root,argv=None,key=None,script=None):
    """Re-exec once into the validated workspace venv, preserving CLI scope."""
    python=workspace_python(root,key);target_prefix=Path(python).parent.parent.absolute()
    if Path(sys.prefix).absolute()==target_prefix:return False
    marker=os.environ.get('NERO_WORKSPACE_REEXEC')
    if marker and Path(marker).absolute()==target_prefix:raise RuntimeError('workspace Python 重执行未生效，已阻止循环')
    env=environment();env['NERO_WORKSPACE_REEXEC']=str(target_prefix)
    flags=['-B','-s','-u','-X','utf8']
    entry=_lexical_child(Path(root).absolute(),Path(script or sys.argv[0]).absolute())
    if not entry.is_file():raise RuntimeError('workspace 启动脚本不存在')
    command=[str(python),*flags,str(entry),*(list(sys.argv[1:] if argv is None else argv))]
    os.execve(str(python),command,env)
    return True


def prepare_macos_python(root,key,uv):
    base=root/'runtime/portable'/key;base.mkdir(parents=True,exist_ok=True)
    lock=root/'requirements.lock.txt';pointer=base/'current-python.json'
    identity={'root':str(root.resolve()),'platform':key,'python_version':PYTHON_VERSION,'lock_sha256':sha(lock)}
    if pointer.exists():
        saved=json.loads(pointer.read_text());folder=(base/saved.get('directory','')).resolve()
        if folder.is_relative_to(base.resolve()) and saved.get('identity')==identity:
            python=folder/'bin/python'
            if python.is_file() and check_python(python,lock).returncode==0:return python
    target=base/'envs'/uuid4().hex[:12];target.parent.mkdir(exist_ok=True)
    env=environment();env.update(UV_CACHE_DIR=str(cache_root(root,key)/'uv-cache'),UV_PYTHON_INSTALL_DIR=str(base/'python'),UV_PYTHON_INSTALL_BIN='0',UV_NO_MODIFY_PATH='1')
    subprocess.run([str(uv),'--no-config','venv','--python',sys.executable,str(target)],env=env,cwd=root,check=True,timeout=60)
    python=target/'bin/python'
    # Current uv accepts the lockfile as the positional sync source; the old
    # pip-compatible ``-r`` flag is rejected by uv 0.11.x.
    subprocess.run([str(uv),'--no-config','pip','sync','--python',str(python),'--only-binary',':all:',str(lock)],env=env,cwd=root,check=True,timeout=600)
    if check_python(python,lock).returncode:raise RuntimeError('Python 依赖检查未通过；未切换原运行环境')
    if pointer.exists():shutil.copy2(pointer,history_root(root,'portable/'+key)/('current-python.previous-'+uuid4().hex[:8]+'.json'))
    atomic_json(pointer,{'identity':identity,'directory':str(target.relative_to(base))})
    return python


def project_files(root):
    for name in ('backend','scripts','frontend/dist','data','templates','skills','runtime','var'):
        base=workspace_paths.base_for(root,name);path=base/name
        if path.exists() and not path.resolve().is_relative_to(base.resolve()):raise RuntimeError('必要目录指向项目外部，无法保证整目录迁移：'+name)
    required=('frontend/dist/index.html','runtime/pi/package-lock.json',
              'data/public/boards/chinext/catalog.json',
              'data/public/boards/chinext/profiles.json',
              'data/public/boards/chinext/instruments.json',
              'data/public/boards/chinext/rules.json',
              'templates/boards/chinext/manifest.json',
              'skills/registry.json')
    missing=[name for name in required if not workspace_paths.resolve(root,name).is_file() or not workspace_paths.resolve(root,name).resolve().is_relative_to(workspace_paths.base_for(root,name).resolve())]
    index=root/'frontend/dist/index.html'
    if index.exists():
        for reference in re.findall(r'(?:src|href)="(/assets/[^\"]+)"',index.read_text(encoding='utf-8')):
            target=(root/'frontend/dist'/reference.lstrip('/')).resolve()
            if not target.is_relative_to((root/'frontend/dist').resolve()) or not target.is_file():missing.append(reference)
    if missing:raise RuntimeError('项目文件不完整：'+', '.join(missing))


def service_state(root,port):
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',port));return 'free'
        except OSError:pass
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(f'http://127.0.0.1:{port}/api/chat/models',timeout=2) as response:data=json.loads(response.read(500000))
        if isinstance(data,dict) and isinstance(data.get('configuration_path'),str) and Path(data['configuration_path']).resolve()==(workspace_paths.var(root)/'pi-models.json').resolve():return 'ours'
    except (OSError,ValueError,TypeError):pass
    return 'occupied'


def launch(root,python,node,port,no_browser=False):
    state=service_state(root,port);url=f'http://127.0.0.1:{port}/'
    if state=='occupied':raise RuntimeError(f'端口 {port} 被其他服务占用；使用 --port 指定另一端口，不会关闭其他服务')
    if state=='ours':
        print('本项目已在运行：'+url)
        if not no_browser:webbrowser.open(url)
        return 0
    app=workspace_paths.app_of(root)
    command=[str(python),str(app/'scripts/run.py'),'--port',str(port),
             '--data-dir',str(workspace_paths.var(root)),'--seed-root',str(workspace_paths.knowledge_of(root)),
             '--web-root',str(app/'frontend/dist')]
    process=subprocess.Popen(command,cwd=app,env=environment(node))
    try:
        for _ in range(80):
            if process.poll() is not None:raise RuntimeError('工作台未启动，请查看本窗口错误信息')
            if service_state(root,port)=='ours':break
            time.sleep(.25)
        else:raise RuntimeError('工作台启动超时，未将其他页面标为成功')
        print('配置完成，工作台已就绪：'+url,flush=True)
        print('模型账号须在“模型设置”中完成授权；此脚本不迁移密钥，也不启动 OpenCodex。',flush=True)
        if not no_browser:webbrowser.open(url)
        return process.wait()
    except KeyboardInterrupt:
        # Ctrl+C also reaches the child console; give its shutdown hook time to
        # settle the current run and close database connections before forcing it.
        try:process.wait(timeout=30)
        except subprocess.TimeoutExpired:pass
        return 0
    finally:
        if process.poll() is None:process.terminate()
        try:process.wait(timeout=30)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)


def mac_main():
    parser=argparse.ArgumentParser(description='macOS 信披系统一键配置与启动')
    parser.add_argument('--uv',type=Path,required=True);parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--doctor',action='store_true');parser.add_argument('--no-browser',action='store_true');parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('端口应在1024至65535之间')
    root=ROOT.resolve();key=platform_key();project_files(root)
    if not key.startswith('macos'):raise RuntimeError('此入口只用于 macOS')
    state=service_state(root,args.port)
    if state=='ours' and not args.prepare_only and not args.doctor:return launch(root,sys.executable,None,args.port,args.no_browser)
    if state!='free' and not args.doctor:raise RuntimeError('端口或原服务正在使用；先关闭原服务或换用 --port 后配置')
    if args.doctor:
        base=root/'runtime/portable'/key;pointer=base/'current-python.json'
        saved=json.loads(pointer.read_text()) if pointer.exists() else {};folder=(base/saved.get('directory','')).resolve()
        python=folder/'bin/python';valid=folder.is_relative_to(base.resolve()) and saved.get('identity',{}).get('root')==str(root)
        node=node_path(root,key);ready=valid and python.is_file() and check_python(python,root/'requirements.lock.txt').returncode==0 and node.is_file() and pi_ready(root,node,key)
        print(json.dumps({'status':'passed' if ready else 'needs_setup','platform':key,'model_login':'separate_user_action','data_changes':False},ensure_ascii=False))
        return 0 if ready else 2
    with installation_lock(root):
        node=ensure_node(root,key);python=prepare_macos_python(root,key,args.uv);ensure_pi(root,node,key)
        subprocess.run([str(python),'-c','from pathlib import Path; from backend.stage_skills import catalog; catalog(Path.cwd())'],cwd=root,env=environment(node),check=True,timeout=30)
    workspace_paths.var(root).mkdir(parents=True,exist_ok=True)
    if args.prepare_only:print('环境已准备。请从正式 App 打开工作台。');return 0
    return launch(root,python,node,args.port,args.no_browser)


if __name__=='__main__':
    try:raise SystemExit(mac_main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print('配置未完成：'+str(error)+'\n原有事项、文稿和模型配置未删除。',file=sys.stderr);raise SystemExit(2)
