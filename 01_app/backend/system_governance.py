"""Project-scoped inventories and explicit, fingerprint-bound cleanup.

Never classify canonical databases, WAL/SHM, sources, deliverables or dependencies
as disposable. Preview is advisory; confirmation rechecks eligibility and bytes.
Removing a historical database copy moves it into ``governance/trash`` first, so
every cleanup stays recoverable until the operator releases the space explicitly;
``governance/executions/<preview>.jsonl`` records each step before it happens, so
an interrupted run is still auditable.
"""
import hashlib
import errno
import json
import os
import re
import shutil
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .library_admin import atomic
from . import paths as workspace_paths

LOCK=threading.RLock()
RETENTION=1
CACHE_ROOTS=('.pytest_cache','cache/pytest_cache','backend/__pycache__','backend/vendor/nero_word/__pycache__',
             'scripts/__pycache__','tests/__pycache__','frontend/node_modules/.vite')
# Runtime package caches: rebuildable by reinstall/re-download, never project data.
RUNTIME_CACHE_GLOBS=('runtime/portable/*/uv-cache','runtime/portable/*/npm-cache',
                     'runtime/pi/node_modules.previous-*')
PUBLIC_NOTE='仅扫描本项目；当前数据库、WAL/SHM、证据原件、交付文件和依赖环境不进入清理清单。'
QUARANTINE_NOTE='已确认清理的数据库副本先移入隔离区，可原样恢复；确认不再需要后可释放空间。'


def now():return datetime.now(timezone.utc).isoformat()


def identity(path):
    s=path.lstat()
    return {'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'inode':s.st_ino,'device':s.st_dev}


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def safe_file(root,relative):
    if not isinstance(relative,str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise HTTPException(409,'清理路径无效，请重新扫描')
    root=workspace_paths.base_for(root,relative);p=root/relative
    for item in [p,*p.parents]:
        if item==root:break
        if item.is_symlink():raise HTTPException(409,'清理对象包含链接，已停止')
    if not p.resolve().is_relative_to(root) or not p.is_file() or not stat.S_ISREG(p.lstat().st_mode):
        raise HTTPException(409,'文件已变化，请重新扫描')
    if p.lstat().st_nlink>1:raise HTTPException(409,'文件包含硬链接，保留不清理')
    return p


def files(root,relative):
    base=workspace_paths.base_for(root,relative);start=base/relative
    if not start.is_dir() or start.is_symlink():return
    for parent in start.parents:
        if parent==base:break
        if parent.is_symlink():return
    for folder,dirs,names in os.walk(start,followlinks=False):
        dirs[:]=[d for d in dirs if not (Path(folder)/d).is_symlink()]
        for name in names:
            p=Path(folder)/name
            try:
                rel=p.relative_to(base).as_posix();safe_file(base,rel)
                yield rel,p
            except (OSError,HTTPException):continue


def databases(root):
    root=Path(root).resolve()
    live={'var/disclosure.sqlite3':('事项与版本','业务主库'),
          'var/conversations.sqlite3':('会话与执行记录','业务主库')}
    for rel,p in files(root,'data'):
        if len(Path(rel).parts)==5 and rel.startswith('data/public/boards/') and p.name=='disclosure_library.sqlite3':
            live[rel]=(f'法规案例索引 · {p.parent.name}','可重建索引')
        elif len(Path(rel).parts)==5 and rel.startswith('data/client_announcements/') and p.name=='announcement_history.sqlite3':
            live[rel]=(f'公司公告索引 · {p.parent.name}','可重建索引')
    groups=[];byname={}
    for rel,(label,kind) in live.items():
        p=workspace_paths.resolve(root,rel)
        if not p.is_file():continue
        group={'id':rel,'label':label,'kind':kind,'current_path':rel,'current_bytes':p.stat().st_size,
               'sidecar_bytes':sum(s.stat().st_size for s in (Path(str(p)+'-wal'),Path(str(p)+'-shm')) if s.is_file()),
               'backups':[],'retention':RETENTION}
        groups.append(group);byname.setdefault(p.stem,[]).append(group)
    # Historical database files under the existing rollback area only. Unknown
    # origins remain visible but protected, rather than guessed from extension.
    unknown=[];candidates_by_path=dict(files(root,'var/backups'))
    for rel in live:
        current=workspace_paths.resolve(root,rel)
        if not current.parent.is_dir():continue
        for p in current.parent.iterdir():
            if p!=current and p.name.startswith(current.stem) and re.search(r'backup|before|\.bak|\.old|\.previous',p.name,re.I):
                try:
                    relative=workspace_paths.store_path(root,p);safe_file(root,relative)
                    candidates_by_path[relative]=p
                except (OSError,HTTPException):continue
    for rel,p in candidates_by_path.items():
        if '.sqlite' not in p.name and not p.name.endswith(('.db','.db.bak')):continue
        if p.name.endswith(('-wal','-shm','-journal')):continue
        stems=[stem for stem in byname if p.name.startswith(stem)]
        candidates=byname[max(stems,key=len)] if stems else []
        matches=[g for g in candidates if g['current_path'].removesuffix(p.name) in rel] if len(candidates)>1 else candidates
        row={'path':rel,**identity(p),'eligible':False,'reason':'来源无法唯一确定，保留'}
        if len(matches)!=1:unknown.append(row);continue
        with p.open('rb') as f:sqlite=f.read(16)==b'SQLite format 3\x00'
        row.update(reason='待保留策略检查' if sqlite else '不是可识别的 SQLite 副本，保留',sqlite=sqlite)
        row['busy_sidecar']=any(Path(str(p)+suffix).exists() for suffix in ('-wal','-shm','-journal'))
        matches[0]['backups'].append(row)
    for group in groups:
        rows=sorted(group['backups'],key=lambda r:(r['mtime_ns'],r['path']),reverse=True)
        for i,row in enumerate(rows):
            eligible=i>=RETENTION and row['sqlite'] and not row['busy_sidecar']
            row.update(eligible=eligible,reason='超过保留数量的历史副本' if eligible else '保留最新副本' if i<RETENTION else '副本不可安全清理')
        group.update(backups=rows,backup_count=len(rows),needs_attention=len(rows)>RETENTION,
                     reclaimable_bytes=sum(r['bytes'] for r in rows if r['eligible']))
    return {'groups':groups,'unclassified':unknown,'retention':RETENTION,
            'excess_groups':sum(g['needs_attention'] for g in groups)}


def cache_roots(root):
    """Whitelist of rebuildable caches; runtime entries appear only when installed."""
    found=list(CACHE_ROOTS)
    for pattern in RUNTIME_CACHE_GLOBS:
        for p in sorted(workspace_paths.app_of(root).glob(pattern)):
            if p.is_dir() and not p.is_symlink():
                relative=p.relative_to(workspace_paths.app_of(root)).as_posix()
                if relative not in found:found.append(relative)
    for pattern in ('cache/portable/*/uv-cache','cache/portable/*/npm-cache'):
        for p in sorted(workspace_paths.local_of(root).glob(pattern)):
            if p.is_dir() and not p.is_symlink():
                found.append(p.relative_to(workspace_paths.local_of(root)).as_posix())
    return found


def cache_label(relative):
    if '__pycache__' in relative:return 'Python 编译缓存'
    if relative.endswith('pytest_cache'):return '测试缓存'
    if relative.endswith('node_modules/.vite'):return '前端预构建缓存'
    if 'node_modules.previous-' in relative:return '上一个版本的运行依赖副本'
    return '运行包下载与包管理缓存'


def quarantine_root(directory):
    return Path(directory)/'governance/trash'


def journal_path(directory,preview_id):
    return Path(directory)/'governance/executions'/(preview_id+'.jsonl')


def note(directory,preview_id,event):
    """Append-only step record; written before the step takes effect."""
    path=journal_path(directory,preview_id);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'at':now(),**event},ensure_ascii=False)+'\n')
        stream.flush();os.fsync(stream.fileno())


def move_file(source,target,expected):
    """Move a verified file; falls back to copy+verify+unlink for a cross-device path."""
    if target.exists() or target.is_symlink():raise OSError('目标位置已有同名文件，未覆盖')
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        os.replace(source,target)
    except OSError as exc:
        if exc.errno!=errno.EXDEV:raise
        shutil.copy2(source,target)
        if digest(target)!=expected:
            target.unlink(missing_ok=True);raise OSError('移动后校验失败')
        source.unlink()
    return target


def quarantine(directory,preview_id,path,relative,expected):
    folder=contained_path(directory,'governance/trash/'+preview_id)
    return move_file(path,contained_path(folder,relative),expected)


def quarantine_state(directory):
    folder=quarantine_root(directory);items=[]
    if folder.is_dir():
        for p in sorted(folder.iterdir()):
            if not p.is_dir() or p.is_symlink():continue
            entries=[f for f in p.rglob('*') if f.is_file() and not f.is_symlink()]
            items.append({'id':p.name,'count':len(entries),'bytes':sum(f.stat().st_size for f in entries),
                          'entries':[{'path':f.relative_to(p).as_posix(),'bytes':f.stat().st_size} for f in entries]})
    return {'items':items,'count':len(items),'bytes':sum(i['bytes'] for i in items),'notice':QUARANTINE_NOTE}


def preview_file(directory,preview_id):
    if not isinstance(preview_id,str) or len(preview_id)!=32 or any(c not in '0123456789abcdef' for c in preview_id):
        raise HTTPException(422,'清理预览编号无效')
    return Path(directory)/'governance/previews'/(preview_id+'.json')


def actions(directory):
    return Path(directory)/'governance/actions.jsonl'


def record(directory,entry):
    target=actions(directory);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('a',encoding='utf-8') as stream:stream.write(json.dumps(entry,ensure_ascii=False)+'\n')


def caches(root):
    rows=[]
    for relative in cache_roots(root):
        entries=[]
        for rel,p in files(root,relative):
            if '__pycache__' in relative and p.suffix!='.pyc':continue
            entries.append({'path':rel,**identity(p),'eligible':True})
        rows.append({'id':relative,'label':cache_label(relative),'count':len(entries),
                     'bytes':sum(r['bytes'] for r in entries),'files':entries,
                     'rebuild':'需要联网重新下载' if relative.startswith('runtime/') else '本机可重新生成'})
    return {'groups':rows,'count':sum(r['count'] for r in rows),'bytes':sum(r['bytes'] for r in rows),
            'notice':'清理后按需重新生成，首次加载可能稍慢；模型复核记录、下载原件及运行历史不属于此处缓存。'}


def inventory(root,directory):
    root=Path(root).resolve();usage=shutil.disk_usage(root)
    return {'scanned_at':now(),'scope':str(root),'notice':PUBLIC_NOTE,'databases':databases(root),'caches':caches(root),
            'quarantine':quarantine_state(directory),'disk':{'total':usage.total,'free':usage.free},'review_interval_days':7}


def clean_view(value):
    result=json.loads(json.dumps(value))
    for row in result['caches']['groups']:row.pop('files',None)
    return result


def scan(root,directory):
    with LOCK:
        data=inventory(root,directory);folder=Path(directory)/'governance';folder.mkdir(parents=True,exist_ok=True)
        atomic(folder/'last-scan.json',(json.dumps(clean_view(data),ensure_ascii=False,indent=2)+'\n').encode())
        return clean_view(data)


def history(directory):
    path=Path(directory)/'governance/actions.jsonl'
    if not path.exists():return []
    return [json.loads(line) for line in path.read_text().splitlines()[-20:] if line.strip()][::-1]


def prepare(root,directory,category,ids):
    if category not in ('databases','caches') or not isinstance(ids,list) or not ids or len(ids)>200:
        raise HTTPException(422,'请选择需要清理的类别与对象')
    with LOCK:
        state=inventory(root,directory)
        groups={g['id']:g for g in state[category]['groups']}
        if len(set(ids))!=len(ids) or set(ids)-groups.keys():raise HTTPException(409,'对象已变化，请重新扫描')
        entries=[]
        for key in ids:
            rows=groups[key]['backups'] if category=='databases' else groups[key]['files']
            for row in rows:
                if row['eligible']:
                    p=safe_file(root,row['path'])
                    entries.append({**row,'group_id':key,'sha256':digest(p)})
        if not entries:raise HTTPException(409,'当前没有符合清理条件的文件')
        plan={'id':uuid4().hex,'created_at':now(),'category':category,'ids':ids,'entries':entries,
              'bytes':sum(r['bytes'] for r in entries),'count':len(entries),'retention':RETENTION,
              'notice':'确认后移入隔离区（可恢复）；保留当前数据库和每组最新一份历史副本。' if category=='databases' else '确认后永久删除以下可重建缓存文件。'}
        folder=Path(directory)/'governance/previews';folder.mkdir(parents=True,exist_ok=True)
        atomic(folder/(plan['id']+'.json'),(json.dumps(plan,ensure_ascii=False)+'\n').encode())
        return plan


def execute(root,directory,preview_id):
    if not isinstance(preview_id,str) or len(preview_id)!=32 or any(c not in '0123456789abcdef' for c in preview_id):
        raise HTTPException(422,'清理预览编号无效')
    with LOCK:
        path=Path(directory)/'governance/previews'/(preview_id+'.json')
        if not path.is_file() or path.is_symlink():raise HTTPException(409,'预览不存在或已处理，请重新扫描')
        plan=json.loads(path.read_text())
        if plan.get('result'):return plan['result']
        if (datetime.now(timezone.utc)-datetime.fromisoformat(plan['created_at'])).total_seconds()>1800:
            raise HTTPException(409,'清理预览已过期，请重新扫描')
        state=inventory(root,directory);category=plan['category'];eligible={}
        for g in state[category]['groups']:
            for row in (g['backups'] if category=='databases' else g['files']):
                if row['eligible']:eligible[row['path']]=row
        for row in plan['entries']:
            current=eligible.get(row['path']);p=safe_file(root,row['path'])
            if current is None or any(current[k]!=row[k] for k in ('bytes','mtime_ns','inode','device')) or digest(p)!=row['sha256']:
                raise HTTPException(409,'文件或保留范围发生变化，未执行清理；请重新扫描')
        deleted=[];errors=[]
        note(directory,preview_id,{'event':'start','category':category,'count':len(plan['entries']),
                                   'paths':[row['path'] for row in plan['entries']]})
        # Persist intent before moving any bytes. Recovery also reads verified
        # quarantine entries if the process stopped before its final receipt.
        plan['started_at']=now();atomic(path,(json.dumps(plan,ensure_ascii=False)+'\n').encode())
        for row in plan['entries']:
            try:
                p=safe_file(root,row['path'])
                if identity(p)!={k:row[k] for k in ('bytes','mtime_ns','inode','device')}:raise OSError('文件已变化')
                if category=='databases':
                    note(directory,preview_id,{'event':'moving','path':row['path'],'sha256':row['sha256']})
                    quarantine(directory,preview_id,p,row['path'],row['sha256'])
                else:
                    p.unlink()
                item={'path':row['path'],'bytes':row['bytes'],'sha256':row['sha256'],'quarantined':category=='databases'}
                deleted.append(item);note(directory,preview_id,{'event':'removed',**item})
            except (OSError,HTTPException) as exc:
                reason=str(getattr(exc,'detail',exc))
                errors.append({'path':row['path'],'reason':reason})
                note(directory,preview_id,{'event':'error','path':row['path'],'reason':reason});break
        result={'id':preview_id,'at':now(),'status':'partial' if errors else 'completed','category':category,
                'deleted':deleted,'errors':errors,'released_bytes':sum(r['bytes'] for r in deleted if not r['quarantined']),
                'quarantined_bytes':sum(r['bytes'] for r in deleted if r['quarantined']),'count':len(deleted),
                'recoverable':category=='databases','quarantine':f'governance/trash/{preview_id}' if category=='databases' and deleted else None,
                'notice':QUARANTINE_NOTE if category=='databases' else '缓存为可重建内容，按确认永久删除。'}
        plan['result']=result;atomic(path,(json.dumps(plan,ensure_ascii=False)+'\n').encode())
        note(directory,preview_id,{'event':'finished','status':result['status'],'count':result['count'],'errors':len(errors)})
        record(directory,result)
        return result


def contained_path(root,relative):
    """No traversal or links, including missing destinations used by restore."""
    root=Path(root).resolve()
    if not isinstance(relative,str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise HTTPException(409,'隔离区路径无效')
    target=root/relative
    for node in [target,*target.parents]:
        if node==root:break
        if node.is_symlink():raise HTTPException(409,'隔离区对象包含链接，已停止')
    if not target.resolve().is_relative_to(root):raise HTTPException(409,'隔离区路径超出范围')
    return target


def recovery_plan(directory,preview_id):
    path=preview_file(directory,preview_id)
    contained_path(directory,path.relative_to(directory).as_posix())
    if not path.is_file():raise HTTPException(409,'清理记录不存在，请重新扫描')
    plan=json.loads(path.read_text())
    if plan.get('id')!=preview_id or plan.get('category')!='databases':raise HTTPException(409,'该清理没有可恢复的数据库副本')
    if not plan.get('started_at') and not plan.get('result'):raise HTTPException(409,'该清理尚未执行')
    folder=contained_path(directory,'governance/trash/'+preview_id)
    entries=plan.get('entries',[])
    if len({row['path'] for row in entries})!=len(entries):raise HTTPException(409,'隔离区清单重复')
    for row in entries:
        source=contained_path(folder,row['path'])
        if source.exists() and (not source.is_file() or digest(source)!=row['sha256']):
            raise HTTPException(409,'隔离区文件内容已变化，未执行操作')
    return path,plan,folder,entries


def restore(root,directory,preview_id):
    """Restore only recorded files, including interrupted moves; never overwrite."""
    with LOCK:
        path,plan,folder,rows=recovery_plan(directory,preview_id)
        restored=[];errors=[];already=plan.get('restored_paths',[])
        # Validate all destinations before restoring the first file.
        for row in rows:
            contained_path(workspace_paths.base_for(root,row['path']),row['path'])
        note(directory,preview_id,{'event':'restore_start','count':len(rows)})
        for row in rows:
            source=contained_path(folder,row['path']);target=contained_path(workspace_paths.base_for(root,row['path']),row['path'])
            if not source.exists():continue
            try:
                move_file(source,target,row['sha256'])
                restored.append({'path':row['path'],'bytes':row['bytes']})
                already=list(dict.fromkeys([*already,row['path']]))
                plan['restored_paths']=already;atomic(path,(json.dumps(plan,ensure_ascii=False)+'\n').encode())
                note(directory,preview_id,{'event':'restored','path':row['path']})
            except (OSError,HTTPException) as exc:
                errors.append({'path':row['path'],'reason':str(getattr(exc,'detail',exc))})
                note(directory,preview_id,{'event':'restore_error',**errors[-1]})
        outcome={'id':preview_id,'at':now(),'status':'partial' if errors else 'restored','category':'databases',
                 'restored':restored,'errors':errors,'count':len(restored),'released_bytes':0}
        result=plan.get('result') or {'id':preview_id,'category':'databases','status':'interrupted'}
        result.update(restored=restored,restore_errors=errors,restored_at=outcome['at'])
        plan['result']=result;atomic(path,(json.dumps(plan,ensure_ascii=False)+'\n').encode())
        note(directory,preview_id,{'event':'restore_finished','status':outcome['status'],'count':outcome['count']})
        record(directory,outcome)
        return outcome


def purge(directory,preview_id):
    """Release only hash-verified recorded quarantine files; preserve unknown files."""
    with LOCK:
        path,plan,folder,entries=recovery_plan(directory,preview_id)
        expected={row['path'] for row in entries};present=[]
        if folder.is_dir():
            for parent,dirs,names in os.walk(folder,followlinks=False):
                for name in [*dirs,*names]:
                    item=Path(parent)/name
                    if item.is_symlink():raise HTTPException(409,'隔离区对象包含链接，未释放空间')
                for name in names:
                    item=Path(parent)/name;relative=item.relative_to(folder).as_posix()
                    if relative not in expected:raise HTTPException(409,'隔离区存在清单外文件，未释放空间')
                    present.append(item)
        removed=[];errors=[]
        for item in present:
            relative=item.relative_to(folder).as_posix()
            note(directory,preview_id,{'event':'purging','path':relative})
            try:
                size=item.stat().st_size;item.unlink();removed.append({'path':relative,'bytes':size})
                note(directory,preview_id,{'event':'purged_file','path':relative,'bytes':size})
            except OSError as exc:
                errors.append({'path':relative,'reason':str(exc)});break
        if folder.is_dir():
            for parent,_,_ in os.walk(folder,topdown=False):
                try:Path(parent).rmdir()
                except OSError:pass
        outcome={'id':preview_id,'at':now(),'status':'partial' if errors else 'purged','category':'databases',
                 'count':len(removed),'released_bytes':sum(row['bytes'] for row in removed),
                 'paths':[row['path'] for row in removed],'errors':errors}
        result=plan.get('result') or {'id':preview_id,'category':'databases','status':'interrupted'}
        result.update(purged_at=outcome['at'],purged_bytes=outcome['released_bytes'])
        plan['result']=result;atomic(path,(json.dumps(plan,ensure_ascii=False)+'\n').encode())
        note(directory,preview_id,{'event':'purged','status':outcome['status'],'count':outcome['count'],'released_bytes':outcome['released_bytes']})
        record(directory,outcome)
        return outcome
