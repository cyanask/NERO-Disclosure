"""Explicit archived-session purge with preview binding and shared-asset preservation."""
import hashlib,json,sqlite3,zipfile,tempfile,os,shutil
from pathlib import Path, PureWindowsPath
from fastapi import HTTPException
from .intent_control import bound
from .library_admin import atomic


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def _raw_roots(runtime):
    """Return the caller-selected roots without following path aliases."""
    return {name:Path(value).absolute() for name,value in {
        'root':runtime.root,'local':runtime.local_root,'directory':runtime.directory}.items()}


def _check_root(path):
    path=Path(path).absolute()
    if path.is_symlink():raise HTTPException(409,'工作区根目录含路径别名')
    return path


def _roots(runtime):
    """Named roots used by a plan; plans never persist absolute file paths."""
    values={name:_check_root(path) for name,path in _raw_roots(runtime).items()}
    return {name:path.resolve() for name,path in values.items()}


def _workspace_id(runtime):
    return digest({name:str(path) for name,path in sorted(_roots(runtime).items())})


def _no_symlink(path,base):
    """Reject links in every component, including a link replacing a deleted file."""
    base=Path(base).absolute()
    path=Path(path).absolute()
    if base.is_symlink():raise HTTPException(409,'工作区根目录含路径别名')
    try:relative=path.relative_to(base)
    except ValueError:raise HTTPException(409,'删除范围超出当前工作区') from None
    current=base
    for part in relative.parts:
        current=current/part
        if current.is_symlink():raise HTTPException(409,'删除范围含路径别名，未继续删除')
    return relative


def _entry(runtime,path,sha256=None):
    """Encode an existing path relative to the narrowest current workspace root."""
    path=Path(path).absolute()
    if path.is_symlink():raise HTTPException(409,'删除范围含路径别名，未开始删除')
    raw_roots=_raw_roots(runtime)
    roots=_roots(runtime)
    candidates=[]
    for name in ('local','directory'):
        raw_base=raw_roots[name]
        try:
            # Check the lexical path before normalising either root or entry;
            # otherwise a root/parent alias can disappear behind resolve().
            relative=_no_symlink(path,raw_base)
            base=roots[name]
            canonical=path.resolve(strict=False)
            if not canonical.is_relative_to(base):raise HTTPException(409,'删除范围超出当前工作区')
            candidates.append((len(base.parts),name,relative.as_posix()))
        except HTTPException:
            continue
    if not candidates:raise HTTPException(409,'删除范围不属于当前工作区')
    _,scope,relative=max(candidates)
    return {'scope':scope,'path':relative,'sha256':sha256 or hashlib.sha256(path.read_bytes()).hexdigest()}


def _resolve_entry(runtime,value):
    """Resolve and validate a plan entry without accepting absolute/legacy paths."""
    if not isinstance(value,dict) or not isinstance(value.get('scope'),str) or not isinstance(value.get('path'),str):
        raise HTTPException(409,'删除记录格式过旧，请重新预览并确认')
    raw=value['path'].replace('\\','/')
    path=Path(raw)
    if not raw or path.is_absolute() or PureWindowsPath(raw).drive or '..' in path.parts or '\x00' in raw:
        raise HTTPException(409,'删除记录路径不是当前工作区的相对路径')
    raw_base=_raw_roots(runtime).get(value['scope']) if value['scope'] in ('local','directory') else None
    if raw_base is None:raise HTTPException(409,'删除记录所属工作区不一致')
    _check_root(raw_base)
    candidate=raw_base/path
    _no_symlink(candidate,raw_base)
    if candidate.exists() and not candidate.is_file():raise HTTPException(409,'删除范围不是普通文件')
    return candidate


def _verify_entry(runtime,value,missing_ok=True):
    path=_resolve_entry(runtime,value)
    if not path.exists():
        if missing_ok:return path
        raise HTTPException(409,'待清理文件不存在')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=value.get('sha256'):
        raise HTTPException(409,'待清理文件已经变化，未继续删除')
    return path


def _valid_plan(runtime,plan,check_hash=True,sid=None,progress=None):
    try:workspace_id=_workspace_id(runtime)
    except (HTTPException,OSError):return False
    if not isinstance(plan,dict) or plan.get('workspace_id')!=workspace_id:return False
    if sid is not None and plan.get('session_id')!=sid:return False
    if (not isinstance(plan.get('files'),list) or not isinstance(plan.get('backups'),list)
            or not isinstance(plan.get('stores'),list)):return False
    fingerprint=plan.get('fingerprint')
    unsigned={k:v for k,v in plan.items() if k!='fingerprint'}
    if not isinstance(fingerprint,str) or digest(unsigned)!=fingerprint:return False
    progress=_progress_valid(progress,plan)
    if progress is None:return False
    try:
        for index,value in enumerate(plan['files']):
            state=_progress_state(progress,'files',index)
            if state and not _state_for(state,value,('processing','done')):return False
            path=_resolve_entry(runtime,value)
            if state and state.get('status')=='done':
                if not _state_matches(path,state):return False
            elif state and not _unfinished_target_valid(path,value,state):return False
            elif check_hash and not state:_verify_entry(runtime,value,missing_ok=True)
        for index,value in enumerate(plan['backups']):
            for key,item in ((index,value),(str(index)+'.adjacent',value.get('adjacent') if isinstance(value,dict) else None)):
                if item is None:continue
                state=_progress_state(progress,'backups',key)
                if state and not _state_for(state,item):return False
                path=_resolve_entry(runtime,item)
                if state and state.get('status')=='done':
                    if not _state_matches(path,state):return False
                elif state and not _unfinished_target_valid(path,item,state):return False
                elif check_hash and not state:_verify_entry(runtime,item,missing_ok=True)
        for item in plan['stores']:
            if not isinstance(item,dict):return False
            state=_progress_state(progress,'stores',item.get('name'))
            if state and (not isinstance(state,dict) or state.get('status') not in ('processing','done')):return False
            path=_resolve_entry(runtime,item)
            fixed={'disclosure':Path(runtime.directory)/'disclosure.sqlite3',
                   'conversations':Path(runtime.store.path)}.get(item.get('name'))
            if (item.get('kind')!='sqlite' or fixed is None
                    or _entry(runtime,fixed)['scope']!=item.get('scope')
                    or _entry(runtime,fixed)['path']!=item.get('path')):return False
            if state and state.get('status')=='done':
                if not path.is_file():return False
            elif not path.is_file():return False
    except (HTTPException,OSError):return False
    return True


def _read_marker(path):
    try:return json.loads(path.read_text())
    except (OSError,UnicodeDecodeError,json.JSONDecodeError):return None


def _deletion_folder(runtime,create=False):
    """Return the control directory only when it is rooted in this workspace."""
    directory=_raw_roots(runtime)['directory']
    _check_root(directory)
    folder=directory/'deletions'
    _no_symlink(folder,directory)
    if folder.exists() and not folder.is_dir():raise HTTPException(409,'删除控制目录不是目录')
    if create and not folder.exists():folder.mkdir()
    return folder


def _marker_path(runtime,sid,create=False):
    if (not isinstance(sid,str) or not sid or Path(sid).name!=sid or sid in ('.','..')
            or '/' in sid or '\\' in sid or '\x00' in sid):
        raise HTTPException(409,'会话编号无效')
    folder=_deletion_folder(runtime,create=create)
    marker=folder/('session-'+sid+'.json')
    _no_symlink(marker,folder)
    return marker


def _plan_record_safe(plan):
    if not isinstance(plan,dict) or not all(isinstance(plan.get(name),list) for name in ('files','backups','stores')):return False
    values=list(plan['files'])+list(plan['stores'])
    for item in plan['backups']:
        values.append(item)
        if isinstance(item,dict) and item.get('adjacent') is not None:values.append(item['adjacent'])
    for item in values:
        if not isinstance(item,dict) or not isinstance(item.get('scope'),str) or not isinstance(item.get('path'),str):return False
        raw=item['path'].replace('\\','/')
        parsed=Path(raw)
        if not raw or parsed.is_absolute() or PureWindowsPath(raw).drive or '..' in parsed.parts or '\x00' in raw:return False
    return True


def _progress_record_safe(progress):
    if not isinstance(progress,dict):return False
    for name in ('backups','files','stores'):
        if not isinstance(progress.get(name),dict):return False
    for state in progress['backups'].values():
        if not isinstance(state,dict):return False
        candidate=state.get('candidate')
        if candidate is not None and not _plan_record_safe({'files':[candidate],'backups':[],'stores':[]}):return False
    return True


def _mark_blocked(path,runtime,reason,value=None):
    try:
        folder=_deletion_folder(runtime)
        _no_symlink(path,folder)
    except (HTTPException,OSError):
        return False
    body={'status':'blocked','workspace_id':_workspace_id(runtime),'reason':reason}
    if isinstance(value,dict):
        if _plan_record_safe(value.get('plan')):
            body['plan']=value['plan'];body['session_id']=value['plan'].get('session_id')
        if _progress_record_safe(value.get('progress')):body['progress']=value['progress']
    try:atomic(path,(json.dumps(body,ensure_ascii=False)+'\n').encode())
    except (OSError,HTTPException):return False
    return True


def _progress_blank(plan):
    return {'plan_fingerprint':plan.get('fingerprint'),'backups':{},'files':{},'stores':{}}


def _progress_valid(progress,plan):
    if progress is None:return _progress_blank(plan)
    if not isinstance(progress,dict) or progress.get('plan_fingerprint')!=plan.get('fingerprint'):return None
    if any(not isinstance(progress.get(name),dict) for name in ('backups','files','stores')):return None
    return progress


def _progress_write(marker,runtime,plan,progress,status='deleting'):
    """Atomically persist recovery state; marker and parent are already checked."""
    _no_symlink(marker,_deletion_folder(runtime))
    body={'status':status,'workspace_id':_workspace_id(runtime),'session_id':plan.get('session_id'),'plan':plan,'progress':progress}
    atomic(marker,(json.dumps(body,ensure_ascii=False)+'\n').encode())


def _progress_state(progress,group,key):
    value=progress.get(group,{}).get(str(key))
    return value if isinstance(value,dict) else None


def _progress_set(progress,group,key,state):
    progress.setdefault(group,{})[str(key)]=state


def _state_for(state,item,allowed=('processing','prepared','done')):
    return (isinstance(state,dict) and state.get('status') in allowed
            and state.get('before_sha256')==item.get('sha256'))


def _entry_hash(path):
    path=Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _state_matches(path,state):
    if not isinstance(state,dict) or state.get('status')!='done':return False
    expected=state.get('after_sha256')
    if expected is None:return not Path(path).exists()
    return Path(path).is_file() and _entry_hash(path)==expected


def _prepared_candidate(runtime,info,item,after):
    if (not isinstance(info,dict) or info.get('kind')!=item.get('kind')
            or info.get('sha256')!=after):
        raise HTTPException(409,'删除候选记录不属于当前任务，未继续删除')
    candidate=_resolve_entry(runtime,info)
    folder=_deletion_folder(runtime)
    if candidate.parent!=folder or not candidate.name.startswith('.purge-') or not candidate.name.endswith('.'+str(item.get('kind'))):
        raise HTTPException(409,'删除候选不在当前控制目录，未继续删除')
    if candidate.exists() and (not candidate.is_file() or _entry_hash(candidate)!=after):
        raise HTTPException(409,'删除候选校验失败，未继续删除')
    return candidate


def _unfinished_target_valid(path,item,state):
    if not state or state.get('status') not in ('processing','prepared'):return True
    if not Path(path).exists():return state.get('status')=='processing'
    current=_entry_hash(path)
    if state.get('status')=='processing':return current==item.get('sha256')
    return current in (item.get('sha256'),state.get('after_sha256'))


def db_has(path,sid):
    try:
        c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
        try:return c.execute('select 1 from sessions where id=?',(sid,)).fetchone() is not None
        finally:c.close()
    except sqlite3.Error:return False


def preview(runtime,sid):
    marker=_marker_path(runtime,sid)
    if marker.is_file():
        saved=_read_marker(marker)
        if (isinstance(saved,dict) and saved.get('status') in ('deleting','blocked')
                and saved.get('session_id',sid)==sid
                and _valid_plan(runtime,saved.get('plan'),check_hash=True,sid=sid,progress=saved.get('progress'))):
            return saved['plan']
    session=runtime.store.session(sid)
    if not session['archived']:raise HTTPException(409,'请先归档会话，再删除')
    runs=runtime.store.runs(sid)
    if any(r['status'] in ('accepted','running','cancelling') for r in runs):raise HTTPException(409,'运行中的会话不能删除')
    eid=session['event_id'];linked=[s for archived in (False,True) for s in runtime.store.sessions(session['board'],archived=archived) if s['event_id']==eid]
    own=bound(eid) and len(linked)==1 and any(r.get('owns_event') for r in runs)
    runids=[r['id'] for r in runs];request_ids=[];message_count=0
    for r in runs:
        cursor=0
        while True:
            rows=runtime.store.journal(r['id'],cursor);message_count+=len(rows)
            request_ids += [x['body'].get('args',{}).get('request_id') for x in rows if x['kind']=='tool_requested']
            if len(rows)<1000:break
            cursor=rows[-1]['seq']
    files=[];retained=[]
    if bound(eid) and not own:retained.append('该事项独立保存或被其他会话共用：事项本体、正式结果及其历史版本保留。')
    for rid in runids:
        for base in (runtime.directory/'pi-runs'/rid,runtime.local_root/'work/template-candidates'/rid,runtime.local_root/'work/downloads'/rid):
            if not base.exists():continue
            if base.is_symlink():raise HTTPException(409,'会话专属目录含路径别名，未开始删除')
            for p in base.rglob('*'):
                if p.is_symlink():raise HTTPException(409,'会话目录含链接，未开始删除')
                if p.is_file():files.append(_entry(runtime,p))
    exports=runtime.local_root/'work/consult-exports'/sid
    if exports.exists():
        if exports.is_symlink():raise HTTPException(409,'会话专属目录含路径别名，未开始删除')
        for p in exports.rglob('*'):
            if p.is_symlink():raise HTTPException(409,'会话目录含链接，未开始删除')
            if p.is_file():files.append(_entry(runtime,p))
        retained.append('咨询工作稿仅在本会话内保存，随会话删除；需要保留请先下载。')
    documents=runtime.local_root/'work/documents'/sid
    if documents.exists():
        if documents.is_symlink():raise HTTPException(409,'文档目录含路径别名，未开始删除')
        for p in documents.rglob('*'):
            if p.is_symlink():raise HTTPException(409,'文档目录含链接，未开始删除')
            if p.is_file():files.append(_entry(runtime,p))
        retained.append('本会话文档和人工导入副本随会话删除，用户原始文件不受影响。')
    if own:
        event=runtime.event(eid)
        others=runtime.route('event.list',{'board':None})
        history=sqlite3.connect('file:'+str(runtime.directory/'disclosure.sqlite3')+'?mode=ro',uri=True)
        try:historical_hashes={a.get('sha256') for (body,) in history.execute('select body from versions where event_id<>?',(eid,)) for a in json.loads(body).get('artifacts',[])}
        finally:history.close()
        for a in event.get('artifacts',[]):
            if a['sha256'] in historical_hashes or any(e['id']!=eid and any(x.get('sha256')==a['sha256'] for x in e.get('artifacts',[])) for e in others):retained.append('共用交付文件保留：'+a['filename']);continue
            p=runtime.directory/'artifacts'/a['file']
            if p.is_file() and not p.is_symlink():files.append(_entry(runtime,p))
    backups=[]
    for base in (runtime.directory/'backups',runtime.directory/'archives'):
        if not base.exists():continue
        for p in base.rglob('*.sqlite3'):
            if p.is_symlink():continue
            if p.name=='conversations.sqlite3' and db_has(p,sid):
                item={'path':_entry(runtime,p)['path'],'scope':_entry(runtime,p)['scope'],'kind':'sqlite','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                adjacent=p.with_name('disclosure.sqlite3')
                if adjacent.is_symlink():raise HTTPException(409,'备份旁邻数据库含路径别名，未开始删除')
                if adjacent.is_file():
                    item['adjacent']={**_entry(runtime,adjacent),'kind':'sqlite'}
                backups.append(item)
        for p in base.rglob('*.zip'):
            if p.is_symlink():continue
            try:
                with zipfile.ZipFile(p) as z:
                    names=[i for i in z.infolist() if i.filename.endswith('conversations.sqlite3')]
                    if not names:continue
                    if any(i.file_size>100*1024*1024 for i in names):raise HTTPException(409,'历史压缩备份过大，需先单独清理该会话副本')
                    found=False
                    for info in names:
                        with tempfile.TemporaryDirectory() as td:
                            tmp=Path(td)/'check.sqlite3';tmp.write_bytes(z.read(info));found=found or db_has(tmp,sid)
                    if found:
                        item=_entry(runtime,p)
                        backups.append({'path':item['path'],'scope':item['scope'],'kind':'zip','sha256':item['sha256']})
            except zipfile.BadZipFile:raise HTTPException(409,'历史备份无法读取，无法确认会话副本已完整清理')
    stores=[]
    for name,path in (('disclosure',runtime.directory/'disclosure.sqlite3'),('conversations',runtime.store.path)):
        path=Path(path)
        if path.is_symlink() or not path.is_file():raise HTTPException(409,'实时删除数据库含路径别名或无法读取')
        item=_entry(runtime,path);stores.append({'name':name,'kind':'sqlite','path':item['path'],'scope':item['scope']})
    value={'session_id':sid,'title':session['title'],'event_id':eid,'delete_owned_event':own,'run_ids':runids,
           'request_ids':sorted(set(x for x in request_ids if x)),'runs':len(runs),'records':message_count,'files':files,'backups':backups,
           'retained':retained+['知识库原件、已入库资料与注册模板属于共享资产，不随会话删除。'],
           'workspace_id':_workspace_id(runtime),'stores':stores}
    value['fingerprint']=digest(value);return value


def scrub(path,plan):
    """Target exact identities, never clear an unrelated session or request cache."""
    c=sqlite3.connect(path)
    try:
        tables={r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        c.execute('PRAGMA secure_delete=ON')
        c.execute('BEGIN IMMEDIATE')
        if 'sessions' in tables:
            ids=[r[0] for r in c.execute('select id from runs where session_id=?',(plan['session_id'],))]
            c.executemany('delete from journal where run_id=?',[(x,) for x in ids]);c.execute('delete from runs where session_id=?',(plan['session_id'],));c.execute('delete from sessions where id=?',(plan['session_id'],))
        if 'events' in tables:
            if plan['delete_owned_event']:
                
                if 'versions' in tables:c.execute('delete from versions where event_id=?',(plan['event_id'],))
                c.execute('delete from events where id=?',(plan['event_id'],))
            for key,response in c.execute('select key,response from requests').fetchall():
                if any(key.endswith(':'+x) for x in plan['request_ids']) or plan['delete_owned_event'] and plan['event_id'] in response:c.execute('delete from requests where key=?',(key,))
        c.commit()
        try:c.execute('VACUUM')
        except sqlite3.OperationalError:pass  # logical deletion and secure_delete are already committed
    finally:c.close()


def _db_presence(path,table,column,value):
    try:
        c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
        try:
            return c.execute(f'select 1 from {table} where {column}=?',(value,)).fetchone() is not None
        finally:c.close()
    except sqlite3.Error:return None


def _candidate(runtime,suffix):
    folder=_deletion_folder(runtime,create=True)
    fd,name=tempfile.mkstemp(prefix='.purge-',suffix=suffix,dir=folder);os.close(fd)
    return Path(name)


def _build_backup_candidate(runtime,path,item,plan):
    candidate=_candidate(runtime,'.'+item['kind'])
    try:
        if item['kind']=='sqlite':
            shutil.copyfile(path,candidate);scrub(candidate,plan)
        else:
            with zipfile.ZipFile(path) as source,zipfile.ZipFile(candidate,'w',zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    parts=Path(info.filename).parts
                    owned=any(parts[i] in ('pi-runs','template-candidates','downloads') and i+1<len(parts) and parts[i+1] in plan['run_ids'] for i in range(max(0,len(parts)-1)))
                    owned_artifacts={Path(f['path']).name for f in plan['files'] if Path(f['path']).parent.name=='artifacts'}
                    owned_documents=any(parts[i] in ('documents','consult-exports') and i+1<len(parts) and parts[i+1]==plan['session_id'] for i in range(max(0,len(parts)-1)))
                    if owned or owned_documents or len(parts)>1 and parts[-2]=='artifacts' and parts[-1] in owned_artifacts:continue
                    raw=source.read(info)
                    if info.filename.endswith(('conversations.sqlite3','disclosure.sqlite3')):
                        with tempfile.TemporaryDirectory() as td:
                            db=Path(td)/'copy.sqlite3';db.write_bytes(raw);scrub(db,plan);raw=db.read_bytes()
                    target.writestr(info,raw)
        return candidate
    except Exception:
        if candidate.exists():candidate.unlink()
        raise


def _done(progress,group,key,entry,after):
    _progress_set(progress,group,key,{'status':'done','before_sha256':entry.get('sha256'),'after_sha256':after})


def _resume_prepared(runtime,path,item,plan,progress,marker,group,key,role='primary'):
    state=_progress_state(progress,group,key)
    if not state:return False
    if not _state_for(state,item):raise HTTPException(409,'删除进度与确认范围不一致，未继续删除')
    if state.get('status')=='done':
        if not _state_matches(path,state):raise HTTPException(409,'已完成的删除目标状态异常，未继续删除')
        return True
    if state.get('status')=='prepared':
        after=state.get('after_sha256');candidate_info=state.get('candidate')
        candidate=_prepared_candidate(runtime,candidate_info,item,after)
        current=_entry_hash(path)
        if current==after:
            if candidate.exists():candidate.unlink()
            _done(progress,group,key,item,current);_progress_write(marker,runtime,plan,progress);return True
        if current!=item.get('sha256') or not candidate.is_file() or _entry_hash(candidate)!=after:
            raise HTTPException(409,'备份在删除恢复前已发生未登记变化')
        os.replace(candidate,path);_done(progress,group,key,item,after);_progress_write(marker,runtime,plan,progress);return True
    if state.get('status')=='processing':
        current=_entry_hash(path)
        if current!=item.get('sha256'):
            raise HTTPException(409,'备份在删除恢复前已发生未登记变化')
    return False


def _purge_backup_entry(runtime,item,plan,progress,marker,key,role='primary'):
    path=_resolve_entry(runtime,item)
    if _resume_prepared(runtime,path,item,plan,progress,marker,'backups',key,role):return
    if _entry_hash(path)!=item.get('sha256'):raise HTTPException(409,'备份版本已变化，未继续删除')
    _progress_set(progress,'backups',key,{'status':'processing','before_sha256':item.get('sha256')})
    _progress_write(marker,runtime,plan,progress)
    candidate=None;registered=False
    try:
        candidate=_build_backup_candidate(runtime,path,item,plan)
        after=_entry_hash(candidate)
        candidate_ref=_entry(runtime,candidate)
        state={'status':'prepared','before_sha256':item.get('sha256'),'after_sha256':after,
               'candidate':{**candidate_ref,'kind':item.get('kind')}}
        _progress_set(progress,'backups',key,state);_progress_write(marker,runtime,plan,progress)
        registered=True
        if _entry_hash(path)!=item.get('sha256'):
            raise HTTPException(409,'备份在候选生成期间已变化，未继续删除')
        os.replace(candidate,path);candidate=None
        _done(progress,'backups',key,item,after);_progress_write(marker,runtime,plan,progress)
    except Exception:
        # Once prepared is on the marker, keep the candidate for retry. Before
        # that point it is disposable and cannot be referenced by recovery.
        if candidate is not None and candidate.exists() and not registered:candidate.unlink()
        raise


def purge_backup(runtime,item,plan,progress,marker,index):
    if item.get('adjacent'):
        _purge_backup_entry(runtime,item['adjacent'],plan,progress,marker,str(index)+'.adjacent','adjacent')
    _purge_backup_entry(runtime,item,plan,progress,marker,str(index),'primary')


def _store_postcondition(path,item,plan,state):
    if item.get('name')=='disclosure':
        present=_db_presence(path,'events','id',plan['event_id'])
        return plan['delete_owned_event'] and present is False
    return _db_presence(path,'sessions','id',plan['session_id']) is False


def _purge_store(runtime,item,plan,progress,marker):
    name=item.get('name');path=_resolve_entry(runtime,item);state=_progress_state(progress,'stores',name)
    if state and (not isinstance(state,dict) or state.get('status') not in ('processing','done')):raise HTTPException(409,'实时数据库删除进度不一致，未继续删除')
    if state and state.get('status')=='done':
        if not path.is_file():raise HTTPException(409,'已完成的实时数据库不在受控位置')
        return
    if state and state.get('status')=='processing' and _store_postcondition(path,item,plan,state):
        _done(progress,'stores',name,item,None);_progress_write(marker,runtime,plan,progress);return
    state={'status':'processing'}
    _progress_set(progress,'stores',name,state);_progress_write(marker,runtime,plan,progress)
    try:scrub(path,plan)
    except Exception:
        if _store_postcondition(path,item,plan,state):
            _done(progress,'stores',name,item,None);_progress_write(marker,runtime,plan,progress)
        raise
    _done(progress,'stores',name,item,None);_progress_write(marker,runtime,plan,progress)


def _purge_file(runtime,item,plan,progress,marker,index):
    path=_resolve_entry(runtime,item);state=_progress_state(progress,'files',index)
    if state and not _state_for(state,item,('processing','done')):raise HTTPException(409,'文件删除进度不一致，未继续删除')
    if state and state.get('status')=='done':
        if _state_matches(path,state):return
        raise HTTPException(409,'已完成的文件删除状态异常，未继续删除')
    if state and state.get('status')=='processing' and not path.exists():
        _done(progress,'files',index,item,None);_progress_write(marker,runtime,plan,progress);return
    if path.exists() and _entry_hash(path)!=item.get('sha256'):
        raise HTTPException(409,'待清理文件已经变化，未继续删除')
    if not path.exists():
        _done(progress,'files',index,item,None);_progress_write(marker,runtime,plan,progress);return
    _progress_set(progress,'files',index,{'status':'processing','before_sha256':item.get('sha256')})
    _progress_write(marker,runtime,plan,progress)
    path.unlink();_done(progress,'files',index,item,None);_progress_write(marker,runtime,plan,progress)


def delete(runtime,sid,fingerprint):
    with runtime.lock:
        marker=_marker_path(runtime,sid)
        saved=_read_marker(marker) if marker.is_file() else None
        if (isinstance(saved,dict) and saved.get('status')=='deleted'
                and saved.get('workspace_id')==_workspace_id(runtime)
                and saved.get('session_id',sid)==sid):return saved
        saved_progress=_progress_valid(saved.get('progress'),saved.get('plan')) if isinstance(saved,dict) and isinstance(saved.get('plan'),dict) else None
        pending=(saved if isinstance(saved,dict) and saved.get('status') in ('deleting','blocked')
                 and saved.get('workspace_id')==_workspace_id(runtime)
                 and saved.get('session_id',sid)==sid
                 and _valid_plan(runtime,saved.get('plan'),check_hash=True,sid=sid,progress=saved_progress) else None)
        plan=pending['plan'] if pending else preview(runtime,sid)
        progress=saved_progress if pending else _progress_blank(plan)
        if plan['fingerprint']!=fingerprint:raise HTTPException(409,'删除范围已变化，请重新预览并确认')
        if not pending:
            if not _valid_plan(runtime,plan,check_hash=True,sid=sid,progress=progress):
                raise HTTPException(409,'删除范围在确认后已变化，请重新预览')
            marker=_marker_path(runtime,sid,create=True)
            _progress_write(marker,runtime,plan,progress)
        for index,item in enumerate(plan['backups']):purge_backup(runtime,item,plan,progress,marker,index)
        for index,item in enumerate(plan['files']):_purge_file(runtime,item,plan,progress,marker,index)
        for item in plan['stores']:_purge_store(runtime,item,plan,progress,marker)
        result={'session_id':sid,'status':'deleted','workspace_id':_workspace_id(runtime),'deleted_event_id':plan['event_id'] if plan['delete_owned_event'] else None,'runs':plan['runs'],'records':plan['records'],'files':len(plan['files']),'backups':len(plan['backups'])}
        atomic(marker,(json.dumps(result,ensure_ascii=False)+'\n').encode())
        return {**result,'retained':plan['retained']}


def resume_pending(runtime):
    try:folder=_deletion_folder(runtime)
    except (HTTPException,OSError):return
    if not folder.exists():return
    try:workspace_id=_workspace_id(runtime)
    except (HTTPException,OSError):return
    for path in folder.glob('session-*.json'):
        if path.is_symlink():continue
        value=_read_marker(path)
        if not isinstance(value,dict):
            _mark_blocked(path,runtime,'待删除记录损坏，需重新预览并确认',value);continue
        if value.get('status')!='deleting':continue
        plan=value.get('plan')
        marker_sid=path.stem.removeprefix('session-')
        plan_sid=plan.get('session_id') if isinstance(plan,dict) else None
        progress=_progress_valid(value.get('progress'),plan) if isinstance(plan,dict) else None
        if (value.get('workspace_id')!=workspace_id
                or value.get('session_id',marker_sid)!=marker_sid
                or marker_sid!=str(plan_sid or '')
                or progress is None
                or not _valid_plan(runtime,plan,check_hash=True,sid=marker_sid,progress=progress)):
            _mark_blocked(path,runtime,'待删除记录属于其他工作区、旧格式或文件校验失败；请在当前归档会话重新预览并确认',value)
            continue
        try:delete(runtime,plan['session_id'],plan['fingerprint'])
        except (HTTPException,OSError,sqlite3.Error) as exc:
            latest=_read_marker(path)
            if isinstance(latest,dict) and latest.get('status')=='deleted':continue
            if not isinstance(latest,dict) or latest.get('status') not in ('deleting','blocked'):
                latest=value
            _mark_blocked(path,runtime,'删除恢复未完成：'+str(getattr(exc,'detail',exc)),latest)
