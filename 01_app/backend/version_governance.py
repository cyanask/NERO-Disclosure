"""Build identity, consistency evidence and rollback points for one copy.

The record compares the published manifest, the served Web assets, the installed
Pi engine and the local data schema, then lists the rollback points already kept
in this copy. It changes no build file, rebuilds no asset and deletes nothing:
the quick scan reads file metadata, and the optional full check only hashes.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from . import announcement_index, public_library_index
from .public_store import atomic
from .system_governance import databases as database_groups
from . import paths as workspace_paths

LOCK=threading.RLock()
JOBS={}
ASSET=re.compile(r'(?:src|href)="(/[^"]+)"')
VERIFY_CHUNK=64*1024
BOUNDARY=('版本记录只做只读核对：读取发布清单与运行服务信息，不重新构建、不覆盖文件、不删除任何回退点。'
          '清单指纹证明“与本副本的发布清单一致”，不等于法律效力或内容正确。')


def now():return datetime.now(timezone.utc).isoformat()
def relative(root,path):
    try:return workspace_paths.store_path(root,path)
    except (ValueError,OSError):return str(path)


def backend_fingerprint(root):
    value=hashlib.sha256()
    for path in sorted((Path(root)/'backend').rglob('*.py')):
        if path.is_symlink():continue
        value.update(path.relative_to(root).as_posix().encode());value.update(path.read_bytes())
    return value.hexdigest()


def bind_runtime(runtime):
    # Capture once when this service constructs its routes, never at scan time.
    runtime.governance_boot={'started_at':now(),'pid':os.getpid(),
                             'backend_sha256':backend_fingerprint(runtime.code_root)}


def running_backend(runtime):
    boot=getattr(runtime,'governance_boot',None)
    current=backend_fingerprint(runtime.code_root)
    return {**(boot or {}),'disk_sha256':current,
            'status':'current' if boot and boot['backend_sha256']==current else 'restart_required' if boot else 'unknown'}
def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(VERIFY_CHUNK):value.update(chunk)
    return value.hexdigest()


def scoped_path(root,relative_path):
    root=Path(root).resolve();relative_path=Path(relative_path)
    if relative_path.is_absolute() or '..' in relative_path.parts:
        raise ValueError('清单包含项目范围外的路径')
    path=root/relative_path
    # Portable Python/Node bundles contain internal links; read their targets only
    # when they remain inside this project. External targets remain forbidden.
    resolved=path.resolve()
    if not resolved.is_relative_to(root):raise ValueError('清单包含项目范围外的链接或路径')
    return resolved
def folder_size(path):
    total=count=0
    for parent,dirs,names in os.walk(path):
        dirs[:]=[d for d in dirs if not (Path(parent)/d).is_symlink()]
        for name in names:
            item=Path(parent)/name
            try:total+=item.stat().st_size;count+=1
            except OSError:continue
    return total,count


def build(root):
    path=Path(root)/'BUILD_MANIFEST.json'
    row={'file':relative(root,path),'present':path.is_file(),'version':'','product':'','schema_version':'',
         'description':'','files_count':None,'producer':{},'manifest_sha256':'','recorded_at':None,'error':None,'files':[]}
    if not row['present']:
        row['error']='缺少 BUILD_MANIFEST.json，无法核对本副本与发布清单'
        return row
    try:
        manifest=json.loads(path.read_text('utf-8'))
        if not isinstance(manifest,dict) or not isinstance(manifest.get('files'),list):raise ValueError('缺少文件清单')
        seen=set()
        for item in manifest['files']:
            if not isinstance(item,dict) or not isinstance(item.get('path'),str) or not item['path']:raise ValueError('文件路径缺失')
            scoped_path(manifest_base(root,manifest),item['path'])
            if item['path'] in seen:raise ValueError('文件路径重复')
            seen.add(item['path'])
            if not isinstance(item.get('bytes'),int) or item['bytes']<0 or not re.fullmatch('[a-fA-F0-9]{64}',str(item.get('sha256',''))):raise ValueError('文件大小或哈希无效')
        if manifest.get('files_count',len(seen))!=len(seen):raise ValueError('清单文件数与内容不一致')
    except (OSError,ValueError) as exc:
        row['error']=f'发布清单无法读取：{exc}'
        return row
    row.update(version=manifest.get('version',''),product=manifest.get('product',''),schema_version=manifest.get('schema_version',''),
               path_base=manifest.get('path_base','app'),
               description=manifest.get('description',''),files_count=manifest.get('files_count',len(manifest['files'])),producer=manifest.get('producer') or {},
               manifest_sha256=digest(path),recorded_at=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).astimezone().isoformat(),
               files=manifest.get('files') or [])
    return row


def manifest_base(root,manifest):
    root=Path(root).resolve()
    if manifest.get('path_base')=='workspace' and root.name=='01_app':return root.parent
    return root


def manifest_check(root,manifest):
    """Existence and size comparison over the recorded list; hashing stays optional."""
    missing=[];changed=[];checked=0
    for row in manifest.get('files',[]):
        try:path=scoped_path(manifest_base(root,manifest),row['path'])
        except ValueError:missing.append(row['path']);continue
        if not path.is_file():missing.append(row['path']);continue
        checked+=1
        try:current=path.stat().st_size
        except OSError:missing.append(row['path']);continue
        if current!=row['bytes']:changed.append({'path':row['path'],'recorded':row['bytes'],'current':current})
    return {'mode':'metadata','status':'unavailable' if manifest.get('error') else 'different' if missing or changed else 'metadata_match','checked':checked,'recorded':len(manifest.get('files',[])),
            'missing_count':len(missing),'changed_count':len(changed),
            'missing':missing[:50],'changed':changed[:50],
            'notice':'按清单记录的文件存在性与大小比对，不校验内容哈希；完整校验另在后台执行。'}


def web(root,manifest):
    dist=Path(root)/'frontend/dist';index=dist/'index.html'
    row={'root':relative(root,dist),'index':relative(root,index),'present':index.is_file(),'bundle':'','assets':[],
         'stale':None,'notice':'','newest_source':None,'built_at':None}
    if not row['present']:
        row['notice']='本副本没有已构建的前端资源，WebUI 无法启动。'
        return row
    html=index.read_text('utf-8',errors='replace')
    references=[value for value in ASSET.findall(html) if not value.startswith('/api')]
    recorded={item['path']:item for item in (manifest.get('files') or [])}
    for reference in references:
        target=(dist/reference.lstrip('/')).resolve()
        if not target.is_relative_to(dist.resolve()) or not target.is_file():
            row['assets'].append({'reference':reference,'path':'','present':False,'bytes':0,'sha256':'','recorded_sha256':'','matches':False})
            continue
        current=digest(target);key=relative(manifest_base(root,manifest),target)
        entry={'reference':reference,'path':key,'present':True,'bytes':target.stat().st_size,'sha256':current,
               'mtime':datetime.fromtimestamp(target.stat().st_mtime,timezone.utc).astimezone().isoformat(),
               'recorded_sha256':(recorded.get(key) or {}).get('sha256',''),'matches':None}
        entry['matches']=entry['recorded_sha256']==current if entry['recorded_sha256'] else None
        row['assets'].append(entry)
        if reference.endswith('.js'):row['bundle']=reference
    bundles=[item for item in row['assets'] if item['present'] and item['reference'].endswith(('.js','.css'))]
    if bundles:
        built=max(item['mtime'] for item in bundles)
        row['built_at']=built
        newest=0.0;newest_path=''
        source=Path(root)/'frontend/src'
        if source.is_dir():
            for parent,dirs,names in os.walk(source):
                for name in names:
                    item=Path(parent)/name
                    try:stamp=item.stat().st_mtime
                    except OSError:continue
                    if stamp>newest:newest,newest_path=stamp,relative(root,item)
        if newest:
            row['newest_source']={'path':newest_path,'mtime':datetime.fromtimestamp(newest,timezone.utc).astimezone().isoformat()}
            row['stale']=newest>max(datetime.fromisoformat(item['mtime']).timestamp() for item in bundles)
            if row['stale']:
                row['notice']=f"前端源码（{newest_path}）比已构建资源更新，页面可能仍是旧版本；需要重新构建并更新前端包。"
    if not row['notice']:
        missing=[item['reference'] for item in row['assets'] if not item['present']]
        row['notice']='已构建资源与入口引用一致。' if not missing else f"入口引用缺失：{'、'.join(missing)}"
    return row


def source(root):
    row={'available':False,'commit':'','commit_date':'','subject':'','local_changes':None,'error':None}
    if not (Path(root)/'.git').exists():
        row['error']='本副本没有本地 Git 记录（拷贝安装属正常情况），以发布清单为准'
        return row
    if not shutil.which('git'):
        row['error']='本机未安装 Git，无法读取源码提交'
        return row
    def run(args):
        return subprocess.run(['git',*args],cwd=root,capture_output=True,text=True,timeout=20).stdout.strip()
    try:
        row['commit']=run(['rev-parse','--short','HEAD'])
        row['commit_date']=run(['log','-1','--format=%cI'])
        row['subject']=run(['log','-1','--format=%s'])[:200]
        dirty=run(['status','--porcelain'])
        row['local_changes']=len([line for line in dirty.splitlines() if line.strip()])
        row['available']=bool(row['commit'])
    except (OSError,subprocess.SubprocessError) as exc:
        row['error']=f'读取源码提交失败：{exc}'
    return row


def engine(runtime):
    node=shutil.which('node') or ''
    worker=(runtime.code_root/'runtime/pi/worker.mjs').is_file()
    core=(runtime.code_root/'runtime/pi/node_modules/@earendil-works/pi-agent-core/dist/index.js').is_file()
    package=runtime.code_root/'runtime/pi/node_modules/@earendil-works/pi-agent-core/package.json'
    row={'name':'pi-agent-core','version':'','installed':bool(node and worker and core),'node':node,
         'configuration_path':'','settings_revision':0,'models':{'total':0,'enabled':0},'error':None}
    try:row['version']=json.loads(package.read_text('utf-8')).get('version','')
    except (OSError,ValueError):pass
    try:
        capabilities=runtime.capabilities()
        models=capabilities.get('models') or []
        row.update(name=capabilities.get('engine') or row['name'],version=row['version'] or capabilities.get('version',''),
                   configuration_path=capabilities.get('configuration_path'),settings_revision=capabilities.get('settings_revision'),
                   models={'total':len(models),'enabled':sum(1 for m in models if m.get('configured') and m.get('enabled'))})
    except HTTPException as exc:
        row['error']=str(exc.detail)
    return row


def data(root,directory):
    databases=[];indexes=[]
    for path in (Path(directory)/'disclosure.sqlite3',Path(directory)/'conversations.sqlite3'):
        databases.append({'path':relative(root,path),'bytes':path.stat().st_size if path.is_file() else 0,'present':path.is_file()})
    for group in database_groups(root)['groups']:
        parts=Path(group['current_path']).parts
        if '/disclosure_library.sqlite3' in group['current_path']:
            board=parts[-2]
            state=public_library_index.status(root,board)
            indexes.append({'kind':'法规案例索引','board':board,'path':group['current_path'],'status':state.get('status'),
                            'schema':state.get('schema',''),'expected':public_library_index.SCHEMA,
                            'detail':state.get('message') or state.get('generated_at') or '',
                            'changed_assets':len(state.get('changed_assets') or [])})
        elif '/announcement_history.sqlite3' in group['current_path']:
            board,code=parts[-3],parts[-2]
            state=announcement_index.status(root,board,code)
            indexes.append({'kind':'公司公告索引','board':f'{board} · {code}','path':group['current_path'],'status':state.get('status'),
                            'schema':state.get('schema',''),'expected':announcement_index.SCHEMA,
                            'detail':state.get('classification_version',''),'changed_assets':len(state.get('changed_assets') or [])})
    return {'databases':databases,'indexes':indexes}


def rollback(root,directory):
    rows=[]
    for folder in sorted((Path(directory)/'backups').glob('*'),key=lambda p:p.stat().st_mtime,reverse=True):
        if not folder.is_dir() or folder.is_symlink():continue
        total,count=folder_size(folder)
        rows.append({'kind':'源码／配置变更前备份','path':relative(root,folder),'bytes':total,'files':count,
                     'at':datetime.fromtimestamp(folder.stat().st_mtime,timezone.utc).astimezone().isoformat()})
    for path in sorted((Path(directory)/'archives').glob('*'),key=lambda p:p.stat().st_mtime,reverse=True):
        if path.is_symlink():continue
        total,count=folder_size(path) if path.is_dir() else (path.stat().st_size,1)
        rows.append({'kind':'历史归档','path':relative(root,path),'bytes':total,'files':count,
                     'at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).astimezone().isoformat()})
    for path in sorted((Path(directory)/'model-config-history').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        rows.append({'kind':'模型设置历史版本','path':relative(root,path),'bytes':path.stat().st_size,'files':1,
                     'at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).astimezone().isoformat()})
    for group in database_groups(root)['groups']:
        newest=(group.get('backups') or [None])[0]
        if not newest:continue
        rows.append({'kind':f"数据库历史副本 · {group['label']}",'path':newest['path'],'bytes':newest['bytes'],'files':1,
                     'at':datetime.fromtimestamp(newest['mtime_ns']/1e9,timezone.utc).astimezone().isoformat()})
    for row in rows:
        row['readiness']='unverified' if row['files'] and row['bytes'] else 'unavailable'
        row['notice']='历史备份，恢复完整性与版本兼容性尚未核验' if row['readiness']=='unverified' else '空目录，不能用于恢复'
    return rows


def identity(record):
    return {'version':record['build'].get('version'),'manifest':record['build'].get('manifest_sha256'),
            'files':record['build'].get('files_count'),'bundle':record['web'].get('bundle'),
            'engine':record['engine'].get('version'),'settings_revision':record['engine'].get('settings_revision'),
            'schemas':sorted(f"{(item['kind'])}:{item.get('schema')}" for item in record['data']['indexes']),
            'local_changes':record['source'].get('local_changes'),'commit':record['source'].get('commit')}


def differences(before,after):
    labels={'version':'发布版本','manifest':'发布清单','files':'清单记录文件数','bundle':'前端入口资源','engine':'Pi 引擎版本',
            'settings_revision':'模型设置版本','schemas':'数据库结构标记','local_changes':'本地未提交改动','commit':'源码提交'}
    return [f"{labels.get(key,key)}：{before.get(key)} → {after.get(key)}" for key in after if before.get(key)!=after.get(key)]


def log(directory,limit=20):
    path=Path(directory)/'governance/version-log.jsonl'
    if not path.is_file():return []
    rows=[]
    for line in path.read_text('utf-8').splitlines()[-limit:]:
        try:rows.append(json.loads(line))
        except ValueError:continue
    return rows[::-1]


def release_notes(root):
    """Curated iteration records shipped as content, not inferred from file state.

    The page needs what each version changed, which no scan can derive. The file
    is optional: a missing or malformed record degrades to an empty list instead
    of failing the whole version scan.
    """
    path=Path(root)/'config/release-notes.json'
    try:
        value=json.loads(path.read_text('utf-8'))
    except (OSError,ValueError):
        return {'current':'','releases':[]}
    if not isinstance(value,dict):return {'current':'','releases':[]}
    releases=[]
    for row in value.get('releases') or []:
        if not isinstance(row,dict) or not isinstance(row.get('version'),str) or not row['version'].strip():continue
        items=[str(item).strip() for item in row.get('items') or [] if isinstance(item,str) and item.strip()]
        releases.append({'version':row['version'].strip(),'released_at':str(row.get('released_at') or ''),
                         'kind':str(row.get('kind') or ''),'summary':str(row.get('summary') or ''),'items':items})
    current=str(value.get('current') or '').strip() or (releases[0]['version'] if releases else '')
    return {'current':current,'releases':releases}


def scan(root,directory,runtime):
    started=time.monotonic()
    app=workspace_paths.app_of(root);repository=workspace_paths.repository_root(app)
    manifest=build(app)
    record={'scanned_at':now(),'boundary':BOUNDARY,'source':source(repository),'engine':engine(runtime),
            'build':{key:value for key,value in manifest.items() if key!='files'},
            'web':web(app,manifest),'runtime':running_backend(runtime),
            'data':data(root,directory),'rollback':rollback(root,directory)}
    record['check']=manifest_check(app,manifest)
    record['changes']=log(directory)
    record['releases']=release_notes(app)
    record['elapsed_ms']=round((time.monotonic()-started)*1000)
    with LOCK:
        folder=Path(directory)/'governance';folder.mkdir(parents=True,exist_ok=True)
        previous=saved(directory)
        if previous:
            moved=differences(identity(previous),identity(record))
            if moved:
                with (folder/'version-log.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps({'at':record['scanned_at'],'from':identity(previous),'to':identity(record),'differences':moved},ensure_ascii=False)+'\n')
                record['changes']=log(directory)
        atomic(folder/'last-version.json',(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode())
    return record


def saved(directory, root=None):
    """The last scan record; with a root, the iteration records stay current.

    The scan snapshot carries the content of its own moment. The version page must
    also show records added after the last scan, so a read attaches the current
    file instead of the stale copy inside the record.
    """
    path=Path(directory)/'governance/last-version.json'
    if not path.is_file():return None
    try:record=json.loads(path.read_text('utf-8'))
    except (OSError,ValueError):return None
    if root is not None and isinstance(record,dict):record['releases']=release_notes(root)
    return record


def verify_state(directory):
    with LOCK:
        path=Path(directory)/'governance/version-verify.json'
        if not path.is_file():return None
        try:job=json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):return None
        handle=JOBS.get(str(Path(directory).resolve()))
        if job.get('state') in ('running','cancelling') and not (handle and handle['id']==job['request_id'] and handle['thread'].is_alive()):
            job.update(state='interrupted',error='服务已重启或检查进程已结束，请重新发起完整校验')
        return job


def verify_start(root,directory,request_id):
    """One background hash check per copy; the page polls the saved progress."""
    key=str(Path(directory).resolve());app=workspace_paths.app_of(root)
    with LOCK:
        current=verify_state(directory)
        if current and current.get('state') in ('running','cancelling'):
            return current
        if current and current.get('request_id')==request_id and current.get('state')=='completed':
            return current
        manifest=build(app)
        if manifest.get('error'):raise HTTPException(409,manifest['error'])
        folder=Path(directory)/'governance';folder.mkdir(parents=True,exist_ok=True)
        stop=threading.Event()
        job={'request_id':request_id,'state':'running','started_at':now(),'finished_at':None,'total':len(manifest['files']),
             'manifest_sha256':manifest['manifest_sha256'],'processed':0,'checked':0,'bytes':0,
             'missing_count':0,'mismatch_count':0,'missing':[],'mismatched':[],'elapsed_ms':0,'error':None}
        def save():atomic(folder/'version-verify.json',(json.dumps(job,ensure_ascii=False)+'\n').encode())
        save()

        def work():
            started=time.monotonic();last_save=started
            try:
                for row in manifest['files']:
                    if stop.is_set():break
                    path=scoped_path(manifest_base(app,manifest),row['path'])
                    try:
                        before=path.stat();current_hash=digest(path);after=path.stat()
                    except OSError:
                        job['missing_count']+=1
                        if len(job['missing'])<50:job['missing'].append(row['path'])
                    else:
                        job['checked']+=1;job['bytes']+=after.st_size
                        if (before.st_mtime_ns,before.st_size,before.st_ino)!=(after.st_mtime_ns,after.st_size,after.st_ino):
                            raise ValueError('检查期间文件发生变化，请重新检查：'+row['path'])
                        if current_hash.lower()!=row['sha256'].lower():
                            job['mismatch_count']+=1
                            if len(job['mismatched'])<50:job['mismatched'].append({'path':row['path'],'recorded':row['sha256'][:16],'current':current_hash[:16]})
                    job['processed']+=1
                    if time.monotonic()-last_save>.5:
                        with LOCK:
                            job['elapsed_ms']=round((time.monotonic()-started)*1000);save()
                        last_save=time.monotonic()
                if not stop.is_set() and digest(Path(app)/'BUILD_MANIFEST.json')!=job['manifest_sha256']:
                    raise ValueError('检查期间发布清单已变化，请重新检查')
                job['state']='cancelled' if stop.is_set() else 'completed'
            except Exception as exc:
                job.update(state='failed',error=str(exc)[:300])
            finally:
                with LOCK:
                    job.update(finished_at=now(),elapsed_ms=round((time.monotonic()-started)*1000))
                    try:save()
                    finally:JOBS.pop(key,None)
        thread=threading.Thread(target=work,name='version-verify',daemon=True)
        JOBS[key]={'id':request_id,'stop':stop,'thread':thread}
        accepted=deepcopy(job)
        thread.start()
        return accepted


def verify_cancel(directory,request_id):
    with LOCK:
        job=verify_state(directory)
        if not job or job['request_id']!=request_id:raise HTTPException(409,'检查任务已变化，请刷新进度')
        handle=JOBS.get(str(Path(directory).resolve()))
        if handle and job['state']=='running':
            handle['stop'].set();job['state']='cancelling'
            atomic(Path(directory)/'governance/version-verify.json',(json.dumps(job,ensure_ascii=False)+'\n').encode())
        return job
