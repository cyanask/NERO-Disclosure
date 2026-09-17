"""Read-only runtime health inventory for the system governance page.

The scan reads current service, Pi engine, execution, node-task and database
state. It starts no model round and repairs no business result: a Gate that
blocked a candidate stays blocked here. Recovery reuses the existing audited
entries (execution cancel, node-task finish), so the action trail stays in the
conversation and event records instead of a second control channel.
"""
import json
import os
import platform
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from .agent_tasks import ACTIVE
from .chat_store import LIVE
from .public_store import atomic
from .system_governance import databases as database_groups
from . import paths as workspace_paths

LOCK=threading.RLock()
STARTED=time.time()
PENDING_NOTICE_HOURS=6
LOW_DISK=2*1024**3
TIGHT_DISK=10*1024**3
BOUNDARY=('健康检查只读取当前状态：不启动模型、不重放工具动作、不改变业务结论。'
          '系统故障可以按下方原入口恢复；业务核验未通过仍须补资料或修订，治理页不放行门禁。')
STAGE_NAMES={'assessment':'披露判断','plan':'文件清单','draft':'正文','template':'模板','word':'Word 制作',
             'lifecycle':'法规核验','classification':'公告分类','scope':'需求分流','chat':'咨询','knowledge':'知识库','company_lookup':'公司核实'}
RUN_STATES={'accepted':'已接收，等待启动','running':'执行中','cancelling':'正在停止','completed':'已完成',
            'incomplete':'未形成可验证结果','failed':'执行失败','interrupted':'服务重启中断','cancelled':'已停止',
            'blocked':'业务门禁阻断','waiting_user':'等待你补充事实','waiting_approval':'等待人工确认','review_pending':'等待语义复核'}
RUN_NEXT={'accepted':'等待 Pi 启动；若长期停留此状态，可停止后在同一会话重新提问。',
          'running':'仍在执行；可在执行记录查看过程，或按需停止。',
          'cancelling':'正在停止，已发生的动作保留记录。',
          'completed':'本轮已完成；是否生成 Word 以事项门禁和人工确认为准。',
          'incomplete':'模型已结束但未提交可验证的节点结果；在同一会话重新提问即可继续，不需要解锁。',
          'failed':'本轮执行失败；先按说明确认模型或资料问题，再在同一会话重新提问。',
          'interrupted':'服务重启打断本轮；在同一会话重新提问即可继续。',
          'cancelled':'本轮已停止；需要时在同一会话重新提问。',
          'blocked':'业务核验未通过：按阻断项补资料、维护法规库或修订后重提；治理页不放行业务结论。',
          'waiting_user':'需要你补充事实或确认后再继续；请打开会话回答待补问题。',
          'review_pending':'候选已保存，等待独立语义复核后形成结论。'}
ATTENTION=('blocked','incomplete','failed','interrupted','waiting_user','review_pending')
TABLES={'disclosure.sqlite3':('events','requests','versions'),
        'conversations.sqlite3':('sessions','runs','journal'),
        'disclosure_library.sqlite3':('meta_info','sources','cases','blacklist_cases'),
        'announcement_history.sqlite3':('meta','announcements','units','document_pages')}
COUNTS={'disclosure.sqlite3':('events',),'conversations.sqlite3':('sessions','runs'),
        'announcement_history.sqlite3':('announcements',)}
STATUS_ORDER={'running':0,'cancelling':1,'accepted':2,'incomplete':3,'failed':4,'interrupted':5,'cancelled':6,'completed':7}


def now():return datetime.now(timezone.utc).isoformat()
def iso(value):return datetime.fromtimestamp(value,timezone.utc).astimezone().isoformat() if isinstance(value,(int,float)) else None
def relative(root,path):
    try:return workspace_paths.store_path(root,path)
    except (ValueError,OSError):return str(path)
def age(value):return round(time.time()-value) if isinstance(value,(int,float)) else None


def database_state(root,path):
    """Read-only integrity read; a locked or unreadable database is reported, never repaired."""
    path=Path(path);started=time.monotonic()
    row={'path':relative(root,path),'name':path.name,'exists':path.is_file(),'bytes':0,'wal_bytes':0,
         'readable':False,'quick_check':None,'missing_tables':[],'counts':{},'error':None,'elapsed_ms':0}
    if not row['exists']:
        row.update(error='文件不存在',elapsed_ms=round((time.monotonic()-started)*1000))
        return row
    row['bytes']=path.stat().st_size
    row['wal_bytes']=sum(s.stat().st_size for s in (Path(str(path)+suffix) for suffix in ('-wal','-shm')) if s.is_file())
    connection=None
    try:
        connection=sqlite3.connect(f'file:{path}?mode=ro',uri=True,timeout=10)
        row['quick_check']=connection.execute('PRAGMA quick_check').fetchone()[0]
        names={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        expected=TABLES.get(path.name,())
        row['missing_tables']=[name for name in expected if name not in names]
        for name in COUNTS.get(path.name,()):
            if name in names:row['counts'][name]=connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        row['readable']=True
    except sqlite3.Error as exc:
        row['error']=f'只读打开失败：{exc}'
    finally:
        if connection is not None:connection.close()
    row['elapsed_ms']=round((time.monotonic()-started)*1000)
    return row


def storage_state(root,directory):
    paths=[Path(directory)/'disclosure.sqlite3',Path(directory)/'conversations.sqlite3']
    paths+= [workspace_paths.resolve(root,g['current_path']) for g in database_groups(root)['groups']
             if '/disclosure_library.sqlite3' in g['current_path'] or '/announcement_history.sqlite3' in g['current_path']]
    seen=[];rows=[]
    for path in paths:
        key=str(path)
        if key in seen:continue
        seen.append(key);rows.append(database_state(root,path))
    usage=shutil.disk_usage(root)
    return {'databases':rows,'disk':{'free':usage.free,'total':usage.total}}


def service(root,directory,port=None):
    return {'pid':os.getpid(),'ppid':os.getppid(),'started_at':iso(STARTED),'uptime_seconds':round(time.time()-STARTED),
            'python':platform.python_version(),'platform':platform.platform(),'directory':str(directory),
            'project_root':str(workspace_paths.app_of(root)),'port':port,'entry':'scripts/run.py 本机 WebUI（127.0.0.1）'}


def engine(runtime):
    worker=runtime.code_root/'runtime/pi/worker.mjs'
    core=runtime.code_root/'runtime/pi/node_modules/@earendil-works/pi-agent-core/dist/index.js'
    package=runtime.code_root/'runtime/pi/node_modules/@earendil-works/pi-agent-core/package.json'
    node=shutil.which('node') or ''
    row={'closed':bool(getattr(runtime,'closed',False)),'active_rounds':len(getattr(runtime,'active',{}) or {}),
         'lock_file':relative(runtime.code_root,runtime.directory/'pi-runtime.lock'),
         'node':node,
         'worker':relative(runtime.code_root,runtime.code_root/'runtime/pi/worker.mjs'),
         'name':'pi-agent-core','version':'','installed':False,'configuration_path':'','settings_revision':0,
         'default_route':'','models':{'total':0,'configured':0,'enabled':0},'error':None}
    row['worker_present']=worker.is_file()
    row['core_present']=core.is_file()
    # The installed engine is a filesystem fact; credentials only affect model listing.
    row['installed']=bool(node and row['worker_present'] and row['core_present'])
    try:row['version']=json.loads(package.read_text('utf-8')).get('version','')
    except (OSError,ValueError):pass
    try:
        capabilities=runtime.capabilities()
        models=capabilities.get('models') or []
        row.update(name=capabilities.get('engine') or row['name'],version=row['version'] or capabilities.get('version',''),
                   configuration_path=capabilities.get('configuration_path'),settings_revision=capabilities.get('settings_revision'),
                   default_route=(capabilities.get('routes') or {}).get('default') or '',
                   models={'total':len(models),'configured':sum(1 for m in models if m.get('configured')),
                           'enabled':sum(1 for m in models if m.get('configured') and m.get('enabled'))})
    except HTTPException as exc:
        row['error']=str(exc.detail)
    return row


def conversation_titles(path):
    if not Path(path).is_file():return {}
    connection=None
    try:
        connection=sqlite3.connect(f'file:{path}?mode=ro',uri=True,timeout=10)
        return {row[0]:{'title':row[1],'board':row[2],'archived':bool(row[3])}
                for row in connection.execute('SELECT id,title,board,archived FROM sessions')}
    except sqlite3.Error:
        return {}
    finally:
        if connection is not None:connection.close()


def runs_state(runtime,event_rows=()):
    conversations=conversation_titles(runtime.store.path)
    by_event={row.get('id'):row for row in event_rows if isinstance(row,dict)}
    rows=[]
    runs=runtime.store.runs();latest={}
    for run in sorted(runs,key=lambda r:r.get('created',r.get('updated',0)),reverse=True):
        latest.setdefault(run.get('session_id'),run.get('id'))
    for run in runs:
        if not run.get('id'):continue
        session=conversations.get(run.get('session_id',''),{})
        model=run.get('model') or {}
        status=run.get('status','')
        event=by_event.get(run.get('event_id')) or {}
        task=next((t for t in event.get('agent_tasks',[]) if t.get('id')==run.get('task_id')),None)
        gate=(task.get('evaluation') or {}).get('gate',{}) if task else {}
        gate_scope='run' if gate else ''
        is_current=latest.get(run.get('session_id'))==run['id'] and not session.get('archived')
        if not gate and is_current and status=='blocked':
            gate=event.get('verification') or {};gate_scope='current_event'
        blockers=[issue.get('detail') or issue.get('code','') for issue in gate.get('issues',[])[:3]] if status in ('blocked','waiting_user','review_pending') else []
        rows.append({'run_id':run['id'],'session_id':run.get('session_id',''),'session_title':session.get('title') or '会话',
                     'event_id':run.get('event_id',''),'board':run.get('board',''),'stage':run.get('stage',''),
                     'stage_name':STAGE_NAMES.get(run.get('stage',''),run.get('stage','')),'status':status,
                     'status_name':RUN_STATES.get(status,status),'outcome':run.get('outcome') or '',
                     'reason':run.get('reason',''),'provider_error':run.get('provider_error',''),
                     'model':model.get('label') or model.get('key') or model.get('id') or '',
                     'updated_at':run.get('updated'),'updated_iso':iso(run.get('updated')),
                     'age_seconds':age(run.get('updated')),'live':status in LIVE,'is_current':is_current,
                     'gate_status':gate.get('status',''),'gate_scope':gate_scope,
                     'blockers':[str(value)[:200] for value in blockers if value],
                     'next_step':RUN_NEXT.get(status,'')})
    rows.sort(key=lambda r:(0 if r['live'] else 1,-(r['updated_at'] or 0)))
    counts={}
    for row in rows:counts[row['status']]=counts.get(row['status'],0)+1
    return {'rows':rows,'counts':counts,'total':len(rows),
            'live':[r for r in rows if r['live']],
            'attention':[r for r in rows if r['is_current'] and r['status'] in ATTENTION]}


def events(directory):
    """Read-only event inventory; an unreadable store is reported, never repaired."""
    path=Path(directory)/'disclosure.sqlite3'
    if not path.is_file():return [],'未找到事项库 var/disclosure.sqlite3'
    connection=None
    try:
        connection=sqlite3.connect(f'file:{path}?mode=ro',uri=True,timeout=10)
        rows=connection.execute('SELECT body FROM events ORDER BY rowid DESC').fetchall()
        return [json.loads(row[0]) for row in rows],None
    except (sqlite3.Error,ValueError) as exc:
        return [],f'事项库无法只读读取：{exc}'
    finally:
        if connection is not None:connection.close()


def task_row(event,task):
    evaluation=task.get('evaluation') or {}
    gate=(evaluation.get('gate') or event.get('verification') or {})
    return {'event_id':event['id'],'event_title':event.get('title',''),'company_name':event.get('company_name',''),
            'event_revision':event.get('revision'),'event_stage':event.get('stage',''),'task_id':task['id'],
            'stage':task.get('stage',''),'stage_name':STAGE_NAMES.get(task.get('stage',''),task.get('stage','')),
            'status':task.get('status',''),'status_reason':task.get('status_reason',''),
            'created_at':task.get('created_at'),'age_seconds':age(task.get('created_at')),
            'outcome':evaluation.get('outcome',''),'attempt':evaluation.get('attempt'),
            'gate_status':gate.get('status',''),'escalation':bool(event.get('escalation')),
            'instruction':(task.get('instruction') or '')[:200]}


def tasks_state(event_rows,runs=()):
    hanging=[];escalated=[];active_count=0
    active={(r.get('event_id'),r.get('task_id')) for r in runs if r.get('status') in LIVE}
    for event in event_rows:
        if event.get('escalation'):
            escalated.append({'event_id':event['id'],'event_title':event.get('title',''),'company_name':event.get('company_name',''),
                              'event_stage':event.get('stage',''),'node':event['escalation'].get('node',''),
                              'reason':event['escalation'].get('reason',''),'event_revision':event.get('revision')})
        for task in event.get('agent_tasks',[]):
            if task.get('status') in ACTIVE:
                if (event['id'],task['id']) in active:active_count+=1
                else:hanging.append(task_row(event,task))
    return {'hanging':hanging,'active_count':active_count,'escalated':escalated}


def findings(record):
    items=[]
    engine_state=record['engine']
    if not engine_state.get('installed') or not engine_state.get('worker_present') or not engine_state.get('core_present'):
        items.append({'level':'attention','code':'engine_unavailable','action':'none',
                      'message':'Pi 引擎未就绪，模型无法运行；请核对 Node 与依赖安装。',
                      'detail':f"node={engine_state.get('node') or '未找到'}；worker={engine_state.get('worker_present')}；核心依赖={engine_state.get('core_present')}"})
    if not engine_state.get('models',{}).get('enabled'):
        items.append({'level':'attention','code':'model_missing','action':'none',
                      'message':('当前无法确认已启用且已配置的模型：'+str(engine_state['error'])) if engine_state.get('error')
                                else '当前没有已启用且已配置的模型，新一轮无法开始；请先在“模型设置”页确认模型已配置并启用。'})
    live=record['runs']['live']
    if live:
        items.append({'level':'info','code':'rounds_running','action':'none','ids':[r['run_id'] for r in live],
                      'message':f"当前有 {len(live)} 轮执行中；需要时可在下方停止。"})
    for status,code,label in (('blocked','rounds_blocked','以业务门禁阻断结束；按阻断项补资料、维护法规库或修订后重提，治理页不放行业务结论。'),
                              ('waiting_user','rounds_waiting_user','等待你补充事实或确认；请打开会话回答待补问题。'),
                              ('incomplete','rounds_incomplete','模型已结束但未形成可验证结果；在同一会话重新提问即可继续，不需要解锁。'),
                              ('failed','rounds_failed','执行失败；先按说明确认模型或资料问题，再在同一会话重新提问。'),
                              ('interrupted','rounds_interrupted','因服务重启中断；在同一会话重新提问即可继续。')):
        rows=[r for r in record['runs']['attention'] if r['status']==status]
        if rows:
            items.append({'level':'attention','code':code,'action':'open_session','ids':[r['run_id'] for r in rows],
                          'message':f"{len(rows)} 个会话的最新一轮{label}",'detail':'；'.join(rows[0]['blockers']) or None})
    hanging=record['tasks']['hanging']
    if hanging:
        blocked=[t for t in hanging if t['outcome']=='blocked' or t['gate_status']=='BLOCKED']
        items.append({'level':'attention','code':'tasks_hanging','action':'open_runs','ids':[t['event_id'] for t in hanging],
                      'message':f"{len(hanging)} 个节点任务仍占位"+(f"，其中 {len(blocked)} 个已按门禁阻断、模型无法自行修复" if blocked else '')+'；'+
                                '请先打开对应事项核对，再处理占位任务。'})
    pending=[t for t in hanging if t['status']=='pending' and (t['age_seconds'] or 0)>PENDING_NOTICE_HOURS*3600]
    if pending:
        items.append({'level':'info','code':'tasks_waiting_claim','action':'cancel_task','ids':[t['task_id'] for t in pending],
                      'message':f"{len(pending)} 个节点任务等待领取超过 {PENDING_NOTICE_HOURS} 小时。"})
    if record['tasks']['escalated']:
        items.append({'level':'attention','code':'escalation','action':'open_runs','ids':[e['event_id'] for e in record['tasks']['escalated']],
                      'message':f"{len(record['tasks']['escalated'])} 个事项已转人工处理；请在事项中核对后恢复当前节点。"})
    for row in record['storage']['databases']:
        if not row['readable']:
            items.append({'level':'attention','code':'database_unreadable','action':'databases','ids':[row['path']],
                          'message':f"{row['path']} 无法只读打开：{row['error']}"})
        elif row['quick_check']!='ok':
            items.append({'level':'attention','code':'database_integrity','action':'databases','ids':[row['path']],
                          'message':f"{row['path']} 完整性检查返回：{row['quick_check']}"})
        elif row['missing_tables']:
            items.append({'level':'attention','code':'database_schema','action':'version','ids':[row['path']],
                          'message':f"{row['path']} 缺少当前代码需要的表：{'、'.join(row['missing_tables'])}"})
    free=record['storage']['disk']['free']
    if free<LOW_DISK:
        items.append({'level':'attention','code':'disk_low','action':'caches','message':f'磁盘剩余空间不足 2 GB；请先释放缓存或历史副本。'})
    elif free<TIGHT_DISK:
        items.append({'level':'info','code':'disk_tight','action':'caches','message':'磁盘剩余空间低于 10 GB，建议按需释放缓存。'})
    return items


def scan(root,directory,runtime,port=None):
    started=time.monotonic()
    event_rows,event_error=events(directory)
    record={'scanned_at':now(),'boundary':BOUNDARY}
    record['service']=service(root,directory,port)
    record['engine']=engine(runtime)
    record['storage']=storage_state(root,directory)
    record['runs']=runs_state(runtime,event_rows)
    record['tasks']=tasks_state(event_rows,runtime.store.runs())
    record['findings']=findings(record)
    if event_error:
        record['findings'].insert(0,{'level':'attention','code':'events_unreadable','action':'databases','message':event_error,
                                     'detail':'节点任务与门禁结论无法核对；上一轮执行状态仍可在执行记录查看。'})
    record['elapsed_ms']=round((time.monotonic()-started)*1000)
    with LOCK:
        folder=Path(directory)/'governance';folder.mkdir(parents=True,exist_ok=True)
        atomic(folder/'last-health.json',(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode())
    return record


def saved(directory):
    path=Path(directory)/'governance/last-health.json'
    if not path.is_file():return None
    try:return json.loads(path.read_text('utf-8'))
    except (OSError,ValueError):return None
