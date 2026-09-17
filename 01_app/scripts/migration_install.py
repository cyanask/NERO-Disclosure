"""Restore a verified whole-data snapshot only into a new, independent home."""
import fcntl
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from scripts.macos_bundle import checked_home, verify_payload

MANIFEST = 'MIGRATION_MANIFEST.json'


def snapshot_manifest(folder):
    from backend.knowledge_packages import contained, digest
    folder = Path(folder).resolve()
    value = json.loads((folder/MANIFEST).read_text())
    if value.get('schema') != 'nero.disclosure.full-migration.v1' or value.get('version') != '1.0.0':
        raise ValueError('迁移快照格式或版本不兼容')
    seen = set()
    for row in value['files']:
        relative = row['path']
        if relative in seen or relative.split('/')[0] not in ('02_knowledge','03_local'):
            raise ValueError('迁移快照包含重复或越界路径')
        seen.add(relative)
        path = contained(folder, relative)
        if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise ValueError('迁移资料校验失败：'+relative)
    mandatory = {'02_knowledge/packages/index.json','03_local/var/conversations.sqlite3',
                 '03_local/var/disclosure.sqlite3'}
    if not mandatory.issubset(seen):raise ValueError('完整迁移快照缺少知识库或历史数据库')
    # Reject unlisted additions, not only changed files.
    actual = set()
    for name in ('02_knowledge','03_local'):
        for path in (folder/name).rglob('*'):
            if path.is_symlink():raise ValueError('迁移快照不能包含链接')
            if path.is_file():actual.add(path.relative_to(folder).as_posix())
    if actual != seen:raise ValueError('迁移快照文件集合与清单不一致')
    return value


def restore(source, target, home, snapshot, *, replace=False, progress=lambda _: None):
    from scripts.macos_bundle import BUNDLE_ID
    import plistlib
    source=Path(source).resolve();target=Path(target).expanduser().absolute()
    home=checked_home(home,source)
    if target.is_symlink() or target.suffix!='.app':raise ValueError('应用安装位置无效')
    target=target.resolve()
    if target==source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('安装位置不能包含安装介质')
    if home==target or home.is_relative_to(target) or target.is_relative_to(home):
        raise ValueError('应用和数据目录不能互相包含')
    if home.exists():
        raise ValueError('目标资料目录已存在；完整迁移不覆盖已有资料，请选择一个新的目录')
    if target.exists():
        info=plistlib.loads((target/'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier')!=BUNDLE_ID:raise ValueError('安装目标属于其他应用')
        if not replace:raise ValueError('已存在应用，请确认替换软件后重试')
    progress('正在核对软件和完整迁移快照')
    verify_payload(source)
    value=snapshot_manifest(snapshot)
    target.parent.mkdir(parents=True,exist_ok=True);home.parent.mkdir(parents=True,exist_ok=True)
    needed=sum(r['bytes'] for r in value['files'])+sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
    # Both locations are checked conservatively, including when they share a disk.
    if any(shutil.disk_usage(p).free < needed+128*1024*1024 for p in (home.parent,target.parent)):
        raise ValueError('磁盘空间不足，尚未写入迁移资料')
    stage_app=target.parent/('.nero-app-'+uuid4().hex+'.app')
    stage_home=home.parent/('.nero-data-'+uuid4().hex)
    backup=None;promoted_home=False;promoted_app=False
    with (target.parent/'.nero-full-install.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('另一个安装任务正在运行') from None
        if home.exists():raise ValueError('资料目录已被其他任务创建，未覆盖')
        try:
            progress('正在复制软件与离线运行环境')
            shutil.copytree(source,stage_app,symlinks=True)
            verify_payload(stage_app)
            stage_home.mkdir(mode=0o700)
            progress('正在恢复知识库、会话、执行记录和附件')
            for name in ('02_knowledge','03_local'):
                shutil.copytree(Path(snapshot)/name,stage_home/name)
            shutil.copy2(Path(snapshot)/MANIFEST,stage_home/MANIFEST)
            snapshot_manifest(stage_home)
            from backend.knowledge_packages import load
            load(stage_home/'02_knowledge',stage_app/'Contents/Resources/01_app',full=True)
            if home.exists():raise ValueError('资料目录已存在，未覆盖')
            if target.exists():
                if not replace:raise ValueError('应用已由其他任务安装，未覆盖')
                backup=target.with_name(target.stem+'.previous-'+uuid4().hex[:8]+'.app')
                target.rename(backup)
            stage_app.rename(target);promoted_app=True
            stage_home.rename(home);promoted_home=True
            return {'app':str(target),'home':str(home),'knowledge':'full_snapshot_restored',
                    'previous_app':str(backup) if backup else None,'migration_id':value['migration_id']}
        except BaseException:
            if promoted_home:home.rename(stage_home)
            if promoted_app:target.rename(stage_app)
            if backup is not None:backup.rename(target)
            raise
        finally:
            for path in (stage_app,stage_home):
                if path.exists():shutil.rmtree(path)  # only this transaction's temporary copies
