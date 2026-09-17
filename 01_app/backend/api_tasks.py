"""Task endpoints: lease/claim/submit/evaluate/adopt plus the unified agent routes."""
import copy
import hashlib
from fastapi import HTTPException, Request
from sqlalchemy import text
from . import models as m, agent_models as am, agent_tasks as tasks, gates, library
from . import disclosure_contract as contract
from .boards import require_board
from .workflow import audit, failed_attempt


class Surface:
    """Route functions the in-process router still dispatches by name."""

    def __init__(self,task_list,task_create,task_context,task_submit,task_evaluate,task_heartbeat,task_finish,
                 task_adopt,open_agent_task,task_library):
        self.task_list=task_list
        self.task_create=task_create
        self.task_context=task_context
        self.task_submit=task_submit
        self.task_evaluate=task_evaluate
        self.task_heartbeat=task_heartbeat
        self.task_finish=task_finish
        self.task_adopt=task_adopt
        self.open_agent_task=open_agent_task
        self.task_library=task_library


def mount(app,ctx,load,read_event):
    def snapshot_template(event):
        template = next((t for t in library.applicable_templates(ctx.seeds.for_event(event),event) if t['id'] == event['draft']['template_id']),None)
        if template is None:raise HTTPException(409,'已绑定模板不在当前规划适用范围内')
        template_root = (ctx.root / 'templates').resolve()
        source = (template_root / template['file']).resolve()
        if not source.is_relative_to(template_root) or source.suffix.lower() != '.docx' or not source.is_file():
            raise HTTPException(409, '模板路径无效')
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        snapshot_root = ctx.directory / 'templates'
        snapshot_root.mkdir(exist_ok=True)
        snapshot = snapshot_root / (digest + '.docx')
        try:
            with snapshot.open('xb') as target:
                target.write(content)
        except FileExistsError:
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
                raise HTTPException(409, '模板快照校验失败')
        event['draft']['template_version'] = template.get('version', '')
        event['draft']['template_sha256'] = digest

    def task_write(event_id, task_id, action, payload, request):
        actor=ctx.security.actor(request)
        body=payload.model_dump(exclude_none=True)
        with ctx.store.transaction() as conn:
            key=f"task:{actor['channel']}:{actor['actor_id']}:{body['request_id']}"
            stamp,cached=ctx.store.cached(conn,key,{'event_id':event_id,'task_id':task_id,'action':action,**body})
            if cached:
                if cached.get('_gate_error'):raise HTTPException(409,cached['_gate_error'])
                return cached
            event=load(conn,event_id)
            if event['revision']!=body['expected_revision']:
                raise HTTPException(409,'事项版本已变化，请重新读取任务和事项')
            blocked=None
            try:
                # A failed adoption must retain the submitted candidate and the failure receipt.
                candidate=copy.deepcopy(event)
                tasks.apply(candidate,action,body,actor,ctx.seeds,task_id)
                event=candidate
            except HTTPException as exc:
                if action!='adopt' or exc.status_code!=409 or not isinstance(exc.detail,dict) or 'gate' not in exc.detail:raise
                blocked=exc.detail
                event['verification']=blocked['gate']
                failed_attempt(event,tasks.get_task(event,task_id)['stage'],blocked['gate'])
            if action in ('adopt','evaluate') and not blocked and tasks.get_task(event,task_id)['status']=='adopted' and tasks.get_task(event,task_id)['stage']=='draft' and event.get('output_mode')!='text':
                snapshot_template(event)
                from . import continuous_workflow as continuous
                if continuous.enabled(event) and action=='evaluate':
                    # The template snapshot is part of the frozen draft. Verify only its final shape.
                    receipt=gates.advance(event,ctx.seeds,'draft');event['verification']=receipt
                    task=tasks.get_task(event,task_id);task['evaluation']['gate']=receipt
                    task['candidate_history'][-1]['gate']=receipt
            tasks.refresh(event,ctx.seeds)
            event['revision']+=1
            audit(event,actor,'agent_task_'+action+('_blocked' if blocked else ''),blocked or body.get('reason',body.get('instruction',task_id or '')))
            ctx.store.save(conn,event)
            if action in ('claim','heartbeat'):
                task=tasks.get_task(event,task_id)
                result={'event_id':event_id,'task_id':task_id,'expected_revision':event['revision'],
                        'claim_id':task['claim_id'],'input_fingerprint':task['input_fingerprint'],
                        'lease_until':task['lease_until'],'status':task['status']}
            elif action=='evaluate':
                result=tasks.evaluation_response(event,tasks.get_task(event,task_id))
            else:
                result={'_gate_error':blocked} if blocked else tasks.project_event(event)
            ctx.store.cache(conn,key,stamp,result)
        if blocked:raise HTTPException(409,blocked)
        return result

    def task_list(request: Request, board: str | None = None):
        if board is not None: require_board(board)
        ctx.security.actor(request)
        with ctx.store.read() as conn:
            ids=conn.execute(text('SELECT id FROM events ORDER BY rowid DESC')).scalars().all()
            layers={i:(ctx.store.get(conn,i) or {}).get('layer') for i in ids}
        return [{'event_id':event['id'],'event_title':event['title'],'event_revision':event['revision'],**task}
                for event in [tasks.project_event(read_event(i)) for i in ids if board is None or layers[i]==board]
                for task in reversed(event.get('agent_tasks',[]))]

    def task_create(event_id: str,payload: am.TaskCreate,request: Request):
        return task_write(event_id,None,'create',payload,request)

    def task_context(event_id: str,task_id: str,request: Request):
        actor=ctx.security.actor(request)
        event=read_event(event_id)
        return tasks.context(event,tasks.get_task(event,task_id),actor,ctx.seeds)

    def task_claim(event_id: str,task_id: str,payload: am.Claim,request: Request):
        return task_write(event_id,task_id,'claim',payload,request)

    def task_heartbeat(event_id: str,task_id: str,payload: am.Lease,request: Request):
        return task_write(event_id,task_id,'heartbeat',payload,request)

    def task_submit(event_id: str,task_id: str,payload: am.Submit,request: Request):
        return task_write(event_id,task_id,'submit',payload,request)

    def task_evaluate(event_id: str,task_id: str,payload: am.Submit,request: Request):
        return task_write(event_id,task_id,'evaluate',payload,request)

    @app.post('/api/events/{event_id}/agent-tasks/{task_id}/finish')
    def task_finish(event_id: str,task_id: str,payload: am.Finish,request: Request):
        return task_write(event_id,task_id,'finish',payload,request)

    @app.post('/api/events/{event_id}/agent-tasks/{task_id}/adopt')
    def task_adopt(event_id: str,task_id: str,payload: m.Generate,request: Request):
        return task_write(event_id,task_id,'adopt',payload,request)

    def open_agent_task(args,request):
        actor=ctx.security.actor(request);tasks.require_agent(actor)
        body=args.model_dump()
        with ctx.store.transaction() as conn:
            key=f"route-open:{actor['actor_id']}:{args.request_id}"
            stamp,cached=ctx.store.cached(conn,key,body)
            event=load(conn,args.event_id);task=tasks.get_task(event,args.task_id)
            if cached:
                tasks.require_owner(task,actor,cached['claim_id'])
                return tasks.context(event,task,actor,ctx.seeds)
            if event['revision']!=args.expected_revision:raise HTTPException(409,'事项版本已变化，请重新读取')
            tasks.claim(task,body,actor)
            event['revision']+=1;audit(event,actor,'agent_task_open','统一路由领取并读取任务')
            ctx.store.save(conn,event);ctx.store.cache(conn,key,stamp,{'claim_id':task['claim_id']})
            return tasks.context(event,task,actor,ctx.seeds)

    def task_library(args, request, read=False):
        actor=ctx.security.actor(request)
        with ctx.store.transaction() as conn:
            event=load(conn,args.event_id);task=tasks.get_task(event,args.task_id)
            tasks.require_owner(task,actor,task.get('claim_id'))
            bound=ctx.seeds.for_event(event)
            if read and args.item_id.startswith('announcement-'):
                from .announcement_history import read as read_history
                return read_history(ctx.root,event['layer'],event.get('stock_code',''),args.item_id,args.page)
            if read:return library.item(bound,args.item_id,args.page,args.view)
            if args.collection=='client_history':
                from .announcement_history import search as history_search
                return history_search(ctx.root,event,args.query,args.offset,args.limit)
            if args.collection in ('client_history','client_materials'):
                return {'scope_ref':contract.scope(event),**contract.capabilities()[args.collection], 'items':[], 'not_found_is_absence':False}
            snapshot=task['snapshot']['event']
            as_of=snapshot['facts'].get('assessment_as_of') or snapshot['facts'].get('event_date') or snapshot['created_at'][:10]
            return library.search(bound,args.collection,q=args.query,offset=args.offset,limit=args.limit,as_of=as_of,view=args.view)

    return Surface(task_list,task_create,task_context,task_submit,task_evaluate,task_heartbeat,task_finish,
                   task_adopt,open_agent_task,task_library)
