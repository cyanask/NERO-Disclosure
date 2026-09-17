"""Event endpoints: list, create, read, edit, rule check and the retired tombstones."""
from fastapi import HTTPException, Request
from sqlalchemy import text
from . import models as m, agent_tasks as tasks, gates, library
from .boards import require_board
from .workflow import audit, edit_facts, new_event


class Surface:
    """Route helpers the in-process router and the scenario importer still call."""

    def __init__(self,create,events,event_create,event_get,event_edit,assess):
        self.create=create
        self.events=events
        self.event_create=event_create
        self.event_get=event_get
        self.event_edit=event_edit
        self.assess=assess


def mount(app,ctx,load,read_event):
    def create(body, request):
        if not ctx.legacy_test_mode:body={**body,'workflow_policy':'continuous-v1'}
        actor = ctx.security.actor(request)
        with ctx.store.transaction() as conn:
            key = f"{actor['channel']}:{actor['actor_id']}:{body['request_id']}"
            digest, cached = ctx.store.cached(conn, key, {'action':'create',**body})
            if cached:
                return tasks.project_event(cached)
            event = new_event(body, actor)
            library.selected(ctx.seeds.for_event(event),event)
            ctx.store.save(conn, event)
            ctx.store.cache(conn, key, digest, event)
            return tasks.project_event(event)

    @app.get('/api/events')
    def events(request: Request, board: str | None = None, company: str | None = None):
        if board is not None: require_board(board)
        ctx.security.actor(request)
        with ctx.store.read() as conn:
            ids = conn.execute(text('SELECT id FROM events ORDER BY rowid DESC')).scalars().all()
            scopes = {event_id: (ctx.store.get(conn,event_id) or {}) for event_id in ids}
        return [tasks.project_event(read_event(event_id)) for event_id in ids
                if (board is None or scopes[event_id].get('layer')==board)
                and (company is None or scopes[event_id].get('stock_code')==company)]

    @app.post('/api/events')
    def event_create(payload: m.Create, request: Request):
        if not ctx.legacy_test_mode and 'workflow_policy' in payload.model_fields_set and payload.workflow_policy!='continuous-v1':
            raise HTTPException(422,'新事项必须使用当前连续流程策略，不能关闭正文确认')
        return create(payload.model_dump(), request)

    @app.get('/api/events/{event_id}')
    def event_get(event_id: str, request: Request, company: str | None = None):
        ctx.security.actor(request)
        event=read_event(event_id)
        if company is not None and event.get('stock_code')!=company:raise HTTPException(403,'事项不属于当前公司')
        return tasks.project_event(event)

    @app.patch('/api/events/{event_id}')
    def event_edit(event_id: str, payload: m.Edit, request: Request):
        actor = ctx.security.actor(request)
        body = payload.model_dump(exclude_none=True)
        with ctx.store.transaction() as conn:
            event = load(conn, event_id)
            if event['revision'] != body['expected_revision']:
                raise HTTPException(409, '事项版本已变化，请重新读取')
            edit_facts(event, body, ctx.seeds)
            tasks.refresh(event, ctx.seeds)
            event['revision'] += 1
            audit(event, actor, 'edit')
            ctx.store.save(conn, event)
            return tasks.project_event(event)

    @app.post('/api/events/{event_id}/assess')
    def assess(event_id: str, payload: m.Generate, request: Request):
        ctx.security.actor(request)
        event=read_event(event_id)
        return {'rule_check':__import__('backend.domain',fromlist=['evaluate']).evaluate(event,ctx.seeds),'gate':gates.evaluate(event,ctx.seeds,'assessment',require_result=False)}

    # A small tombstone keeps old clients from mistaking retired writes for success.
    @app.post('/api/events/{event_id}/approve')
    @app.post('/api/events/{event_id}/plan')
    @app.patch('/api/events/{event_id}/plan')
    @app.post('/api/events/{event_id}/draft')
    @app.patch('/api/events/{event_id}/draft')
    @app.post('/api/events/{event_id}/word/prepare')
    @app.post('/api/events/{event_id}/word/review')
    def retired_production(event_id: str):
        raise HTTPException(410, '旧审批和后台生产已移除；请由外部 Agent 提交候选，经 Verify/Gate 流转')

    return Surface(create,events,event_create,event_get,event_edit,assess)
