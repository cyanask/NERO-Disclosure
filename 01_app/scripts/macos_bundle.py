"""Install a release app and a separately shipped knowledge folder, without overwrites."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
from uuid import uuid4

BUNDLE_ID = 'cn.nero.disclosure.desktop'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def app_from_code(code):
    code = Path(code).resolve()
    bundle = code.parents[2]
    if code.name != '01_app' or code.parent.name != 'Resources' or not bundle.name.endswith('.app'):
        raise ValueError('此入口须由完整的 Mac 安装版打开')
    return bundle


def checked_home(home, bundle):
    home = Path(home).expanduser().absolute()
    if not home.is_absolute() or home.is_symlink():raise ValueError('数据目录不能是符号链接')
    home = home.resolve()
    if home.is_relative_to(Path(bundle).resolve()):raise ValueError('知识库和工作数据须保存在软件包外')
    for name in ('02_knowledge', '03_local'):
        if (home/name).is_symlink():raise ValueError('数据根不能是符号链接')
    return home


def verify_payload(bundle):
    bundle = Path(bundle).resolve()
    # Signing a bundle changes the main executable's signature and seals the
    # resource manifest. Avoid a self-referential hash; codesign owns that check.
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(bundle)],
                   check=True,capture_output=True,text=True,timeout=60)
    info = plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != BUNDLE_ID:raise ValueError('软件包身份不符')
    manifest = json.loads((bundle/'Contents/Resources/PAYLOAD_MANIFEST.json').read_text())
    for row in manifest['files']:
        path = bundle / row['path']
        if Path(row['path']).is_absolute() or '..' in Path(row['path']).parts or not path.resolve().is_relative_to(bundle):
            raise ValueError('软件包清单路径越界')
        if 'link' in row:
            if not path.is_symlink() or os.readlink(path) != row['link']:raise ValueError('运行组件链接不符')
        elif not path.is_file() or digest(path) != row['sha256']:
            raise ValueError('软件文件校验失败：' + row['path'])
    return manifest


def prepare_knowledge(home, seed, app, progress=lambda _: None):
    from backend.knowledge_packages import load, contained
    home, app = Path(home), Path(app)
    target = home/'02_knowledge'
    if target.exists():
        # A user's edited knowledge belongs to them. Startup verifies the
        # compatibility contract, not the original distribution's old hashes.
        load(target, app)
        return 'existing_preserved'
    if seed is None or not (Path(seed)/'packages/index.json').is_file():
        raise ValueError('请在启动器选择随安装包提供的 02_knowledge 文件夹')
    seed = Path(seed).resolve()
    load(seed, app, full=True)
    staging = home/('.knowledge-install-' + uuid4().hex)
    home.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        index = json.loads((seed/'packages/index.json').read_text())
        names = {'packages/index.json'}
        for entry in index['packages']:
            manifest = contained(seed/'packages', entry['file'])
            names.add('packages/' + entry['file'])
            doc = json.loads(manifest.read_text())
            names.update(row['path'] for row in doc['files'])
        for n, name in enumerate(sorted(names), 1):
            source = contained(seed, name)
            destination = contained(staging, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if n % 50 == 0:progress(f'正在初始化知识库（{n}/{len(names)}）')
        load(staging, app, full=True)
        if target.exists():raise ValueError('知识库目录已由其他进程创建，未覆盖')
        staging.rename(target)
        return 'initialized'
    finally:
        if staging.exists():shutil.rmtree(staging)  # this call's disposable staging only


def install(source, target, home, seed, *, replace=False, update_only=False, progress=lambda _: None):
    source, target = Path(source).resolve(), Path(target).expanduser().absolute()
    home = checked_home(home, source)
    if target.is_symlink() or target.suffix != '.app':raise ValueError('安装目标须为普通 .app 目录')
    if target == source:raise ValueError('请从安装介质安装到另一个位置')
    if target.is_relative_to(source) or source.is_relative_to(target):raise ValueError('安装位置不能包含源软件包')
    if update_only:
        if not replace or not target.is_dir():raise ValueError('更新包只用于已安装的信披系统，请选择原应用')
        if not all((home/name).is_dir() for name in ('02_knowledge','03_local')):
            raise ValueError('请选择原有资料目录，更新包不会创建或迁移资料')
    if target.exists():
        info = plistlib.loads((target/'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != BUNDLE_ID:raise ValueError('目标位置属于其他软件')
        if not replace:raise ValueError('目标已有信披系统，请确认更新软件后重试')
    progress('正在核对安装文件')
    verified=verify_payload(source)
    if update_only:
        import re
        current=info.get('CFBundleShortVersionString','')
        incoming=verified.get('version','')
        if not all(re.fullmatch(r'\d+\.\d+\.\d+',v) for v in (current,incoming)):
            raise ValueError('应用版本无法识别，未替换程序')
        if tuple(map(int,current.split('.'))) > tuple(map(int,incoming.split('.'))):
            raise ValueError('已安装的版本较新，拒绝降级')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent/('.nero-install-' + uuid4().hex + '.app')
    backup = None
    try:
        progress('正在安装软件和离线运行环境')
        shutil.copytree(source, staging, symlinks=True)
        verify_payload(staging)
        progress('正在核对原有资料兼容性' if update_only else '正在初始化独立知识库')
        knowledge = prepare_knowledge(home, None if update_only else seed, staging/'Contents/Resources/01_app', progress)
        if target.exists():
            # Keep rollback bytes without exposing another launchable application.
            backup = target.with_name(target.stem + '.previous-' + uuid4().hex[:8] + '.app.backup')
            target.rename(backup)
        try:staging.rename(target)
        except OSError:
            if backup is not None:backup.rename(target)
            raise
        return {'app':str(target), 'home':str(home), 'knowledge':knowledge,
                'previous_app':str(backup) if backup else None}
    finally:
        if staging.exists():shutil.rmtree(staging)
