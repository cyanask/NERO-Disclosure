"""Project-local Windows setup/diagnostics. Does not configure an Agent's model."""
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import urllib.request
import zipfile
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import portable_runtime
from backend import paths as workspace_paths
RUNTIME=ROOT/'runtime/windows-x64'
MODULES=('pypdf','fastapi','uvicorn','sqlalchemy','docxtpl','lxml.etree','pydantic_core','cryptography.hazmat.bindings._rust','openpyxl','et_xmlfile','backend.vendor.nero_office.reader','win32api','pythoncom')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def required_versions(path):
    result={}
    for line in path.read_text('utf-8').splitlines():
        if line.strip() and not line.startswith('#'):
            name,version=line.strip().split('==');result[re.sub(r'[-_.]+','-',name).casefold()]=version
    return result


def ensure_utf8(argv=None):
    """Re-exec the same Windows entry once before reading project files."""
    if sys.platform!='win32' or getattr(sys.flags,'utf8_mode',False):return False
    if os.environ.get('NERO_WINDOWS_UTF8_REEXEC')=='1':raise RuntimeError('Windows UTF-8 重执行未生效，已阻止循环')
    env=dict(os.environ);env['PYTHONUTF8']='1';env['NERO_WINDOWS_UTF8_REEXEC']='1'
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),*(list(sys.argv[1:] if argv is None else argv))]
    os.execve(sys.executable,command,env)
    return True


def diagnose(root=ROOT, windows=None):
    root=Path(root);base=root/'runtime/windows-x64';issues=[]
    is_windows=sys.platform=='win32' if windows is None else windows
    if not is_windows:issues.append('此运行入口仅支持Windows x64')
    if is_windows and Path(sys.executable).resolve()!=(base/'python/python.exe').resolve():issues.append('工程诊断请使用项目内置 Python；日常使用对应平台的正式 App')
    if is_windows and platform.machine().lower() not in ('amd64','x86_64'):issues.append('当前包要求Windows x64')
    if not (root/'frontend/dist/index.html').is_file():issues.append('缺少已构建的Web页面，请重新取得完整MVP目录')
    for name in ('data/public/boards/chinext/catalog.json',
                 'data/public/boards/chinext/profiles.json',
                 'data/public/boards/chinext/instruments.json',
                 'data/public/boards/chinext/rules.json',
                 'templates/boards/chinext/manifest.json',
                 'skills/registry.json'):
        if not workspace_paths.resolve(root,name).is_file():issues.append('缺少项目文件：'+name)
    if is_windows:
        try:
            for name,version in required_versions(base/'requirements.windows.lock.txt').items():
                if importlib.metadata.version(name)!=version:issues.append('依赖版本不匹配：'+name)
        except (OSError,ValueError,importlib.metadata.PackageNotFoundError):issues.append('本地依赖不完整')
        for name in MODULES:
            try:importlib.import_module(name)
            except Exception:issues.append('模块不能加载：'+name)
    if is_windows and not issues:
        try:
            from backend.stage_skills import catalog
            catalog(root)
        except Exception:
            issues.append('项目节点Skill缺失或哈希不符')
    return {'status':'passed' if not issues else 'failed','issues':issues,'platform':sys.platform,'python':platform.python_version(),'windows_execution_verified':sys.platform=='win32' and not issues}


def install_dependencies():
    lock=json.loads((RUNTIME/'runtime.lock.json').read_text('utf-8'));cache=RUNTIME/'downloads';cache.mkdir(exist_ok=True)
    archive=cache/'uv.zip'
    if not archive.exists():
        with urllib.request.urlopen(lock['uv_url'],timeout=60) as response:raw=response.read()
        if hashlib.sha256(raw).hexdigest()!=lock['uv_sha256']:raise RuntimeError('uv下载校验失败')
        archive.write_bytes(raw)
    if digest(archive)!=lock['uv_sha256']:raise RuntimeError('uv原件校验失败，请重新取得完整包')
    tools=RUNTIME/'tools';tools.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if not (tools/info.filename).resolve().is_relative_to(tools.resolve()):raise RuntimeError('工具包路径无效')
        z.extractall(tools)
    matches=list(tools.rglob('uv.exe'))
    if len(matches)!=1:raise RuntimeError('uv工具包不完整')
    # Install into a new versioned directory; never delete or overwrite an existing environment.
    lockpath=RUNTIME/'requirements.windows.lock.txt';target=RUNTIME/('packages-'+digest(lockpath)[:12]+'-'+uuid4().hex[:8])
    env={**os.environ,'UV_CACHE_DIR':str(portable_runtime.cache_root(ROOT,'windows-x64')/'uv-cache'),'UV_PYTHON_DOWNLOADS':'never'}
    subprocess.run([str(matches[0]),'pip','install','--python',sys.executable,'--target',str(target),
                    '--only-binary',':all:','-r',str(lockpath)],env=env,check=True)
    # The next fresh Python process loads this directory via sitecustomize.
    pointer=RUNTIME/'active-packages.json'
    if pointer.exists():
        (RUNTIME/('active-packages-previous-'+uuid4().hex[:8]+'.json')).write_bytes(pointer.read_bytes())
    staged=RUNTIME/('active-packages-'+uuid4().hex[:8]+'.next')
    staged.write_text(json.dumps({'directory':target.name},ensure_ascii=False),encoding='utf-8')
    os.replace(staged,pointer)
    return target


def main():
    parser=argparse.ArgumentParser(description='NERO信披工作台首次使用与诊断')
    parser.add_argument('--doctor',action='store_true');parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--install-dependencies',action='store_true',help='联网准备缺少的项目内依赖')
    parser.add_argument('--after-install',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('端口应在1024至65535之间')
    if sys.platform!='win32':print('仅支持Windows x64；本机不能证明Windows已运行。');return 2
    if ensure_utf8(sys.argv[1:]):return 0
    try:portable_runtime.project_files(ROOT)
    except RuntimeError as exc:print(str(exc));return 2
    if args.install_dependencies:
        try:install_dependencies();print('依赖已准备，请重新运行首次使用入口。');return 0
        except Exception as exc:print('依赖准备未完成：'+type(exc).__name__+'。未修改原有依赖，请保留现场供维护者检查。');return 2
    report=diagnose();print(json.dumps(report,ensure_ascii=False,indent=2))
    if report['status']!='passed':
        dependency_only=all(i.startswith(('依赖','本地依赖','模块')) for i in report['issues'])
        if dependency_only and not args.doctor and not args.after_install:
            print('首次使用：正在联网准备项目内依赖，不修改系统Python或全局配置。')
            try:install_dependencies()
            except Exception as exc:
                print('依赖准备失败：'+type(exc).__name__+'。保留现有文件，请检查网络或联系维护者。');return 2
            return subprocess.call([sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--after-install'],cwd=ROOT)
        print('环境未通过检查。企业网络或权限限制须由本机IT处理；未启动工作台。');return 2
    key='windows-x64';node=portable_runtime.node_path(ROOT,key)
    if args.doctor:
        ready=node.is_file() and portable_runtime.pi_ready(ROOT,node,key)
        print(json.dumps({'pi_runtime':'ready' if ready else 'needs_setup','global_installation':False},ensure_ascii=False))
        return 0 if ready else 2
    state=portable_runtime.service_state(ROOT,args.port)
    if state=='ours' and not args.prepare_only:return portable_runtime.launch(ROOT,sys.executable,node,args.port,args.no_browser)
    if state!='free':print('原服务或端口正在使用，请关闭原服务或使用 --port 后配置。');return 2
    try:
        with portable_runtime.installation_lock(ROOT):
            node=portable_runtime.ensure_node(ROOT,key)
            portable_runtime.ensure_pi(ROOT,node,key)
    except Exception as exc:
        print('Pi 环境准备未完成：'+str(exc)+'。原有事项和模型配置已保留。');return 2
    # Prepare local storage without a user or password configuration.
    from scripts.setup import initialize
    initialize(workspace_paths.var(ROOT))
    print('请在网页“模型设置”中完成授权，再从对话操作台执行任务。')
    print('本入口不会迁移密钥、替用户登录或修改全局配置。')
    if args.prepare_only:return 0
    return portable_runtime.launch(ROOT,sys.executable,node,args.port,args.no_browser)

if __name__=='__main__':raise SystemExit(main())
