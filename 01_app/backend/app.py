from . import library, paths as workspace_paths, stage_skills, workflow_operations
"""Local-only API. Run with uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8765."""
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from . import models as m
from . import agent_models as am, agent_tasks as tasks, gates
from .domain import COMPANIES, NOTICE, Seeds, event_types, read_json
from .security import Security
from .storage import Store
from .workflow import audit, invalidate
from . import disclosure_contract as contract


from .document_content import WordDeliveryError
from .boards import BOARDS


def create_app(data_dir=None, seed_root=None, auth_config=None, pi_config=None, pi_runner=None, *, legacy_test_mode=False):
    app = workspace_paths.app_root()
    explicit = Path(seed_root).resolve() if seed_root is not None else None
    root = workspace_paths.knowledge_of(explicit or app)
    # 旧式单根实例（含隔离测试根）以传入根自洽；三类布局中技能、发布清单随软件根。
    skills_root = workspace_paths.app_of(root)
    manifest_root = workspace_paths.app_of(root)
    directory = Path(data_dir or workspace_paths.local_of(root) / 'var')
    directory.mkdir(parents=True, exist_ok=True)
    seeds, store = Seeds(root), Store(directory / 'disclosure.sqlite3')
    seeds.draft_provider=store.company_drafts
    security = Security(auth_config or {}, store)
    app = FastAPI(title='信息披露-AI辅助系统', docs_url=None, redoc_url=None)

    app.state.store, app.state.security = store, security

    @app.exception_handler(WordDeliveryError)
    async def word_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={'detail':exc.detail})

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={'detail':'输入字段缺失、类型错误或超出范围'})

    @app.middleware('http')
    async def guard(request, call_next):
        try:
            security.origin(request)
            length = request.headers.get('content-length')
            attachment_upload=request.url.path.startswith('/api/chat/sessions/') and request.url.path.endswith('/attachments')
            body_limit=30000000 if attachment_upload else 42000000 if request.url.path=='/api/library/imports' else 9000000 if request.url.path.endswith('/artifacts') else 1000000
            if length and (not length.isdigit() or int(length) > body_limit):
                return JSONResponse(status_code=413, content={'detail':'请求过大'})
            if request.method not in ('GET','HEAD'):
                limit = body_limit
                chunks=[];received=0
                async for chunk in request.stream():
                    received+=len(chunk)
                    if received>limit:return JSONResponse(status_code=413,content={'detail':'请求过大'})
                    chunks.append(chunk)
                request._body=b''.join(chunks)
            return await call_next(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={'detail':exc.detail})

    @app.middleware('http')
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path.endswith('.html') or request.url.path.endswith('.js') or request.url.path == '/':
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    def stale_stage(event):
        """只读检查：返回需要重新核对的起始阶段，None 表示当前状态仍有效。"""
        if not event.get('assessment'):
            return None
        catalog=seeds.for_event(event).catalog()
        from . import continuous_workflow as continuous
        for stage in gates.STAGES:
            record=gates.current_approval(event,stage)
            producer=(event.get(stage) or {}).get('producer') or {}
            method_changed=producer and stage!='word' and producer.get('skill_bundle_sha256')!=stage_skills.get(skills_root,stage)['bundle_sha256']
            automatic_stale=continuous.enabled(event) and event.get('verified_stages',{}).get(stage) and not continuous.verified(event,catalog,stage)
            if automatic_stale or (record and not gates.approval_valid(event,catalog,stage)) or (method_changed and (record or event.get('verified_stages',{}).get(stage))):
                return 'draft' if stage=='word' else stage
        return None

    def load(conn, event_id):
        """读取并按需修复：发现状态过期时在调用方的写事务内修复并留痕。"""
        event = store.get(conn, event_id)
        if not event:
            raise HTTPException(404, '事项不存在')
        changed = False
        start = stale_stage(event)
        if start:
            invalidate(event, start, '当前资料或方法版本变化')
            changed = True
        if tasks.refresh(event, seeds):
            changed = True
        if changed:
            event['revision'] += 1
            audit(event, {'actor':'Harness状态检查','channel':'system'}, 'inputs_changed', '依据、业务输入或领取期限变化，重新核对任务和确认状态')
            store.save(conn, event)
        return event

    def read_event(event_id):
        """GET 读路径：状态有效时只读返回；只有确实过期才进入写事务修复。"""
        with store.read() as conn:
            event = store.get(conn, event_id)
            if not event:
                raise HTTPException(404, '事项不存在')
            if not stale_stage(event) and not tasks.refresh(event, seeds):
                return event
        with store.transaction() as conn:
            return load(conn, event_id)

    @app.get('/api/meta')
    def meta(board: str | None = None):
        scoped = seeds.for_board(board) if board is not None else None
        release=read_json(manifest_root/'BUILD_MANIFEST.json', {})
        producer={'name':release.get('producer',{}).get('name','NERO'),'label':release.get('producer',{}).get('label','NERO 出品'),'product':'信息披露-AI辅助系统','version':release.get('version','0.5.0')}
        return {'title':'信息披露-AI辅助系统','boards':BOARDS,'board':board,'mode':'pi_agent_harness','mode_label':'Pi 对话操作台 · 三库管理 · Verify/Gate','producer':producer,'access':{'mode':'local_no_login','identity_assurance':'none','approval_authority':'local_product_confirmation_only'},'ai_execution':{'word_production':'registered_agent_script','location':'project_pi','backend_model':False,'backend_agent_runtime':True,'dispatch':'explicit_browser_model_selection','model_fallback':False},'workflow':{'transport':'in_process','capabilities':contract.capabilities(),'stage_skills':stage_skills.catalog(skills_root) if (skills_root/'skills/registry.json').exists() else []},'scope_notice':NOTICE,'companies':[c for c in COMPANIES if board is None or c['layer']==board],'event_types':event_types(library.profiles(scoped) if scoped else None),'intake':{'real_issuers':True,'arbitrary_matters':True,'classification_stage':'assessment','document_planning_stage':'plan','output_modes':['text','word']}}

    @app.get('/api/session')
    def session(request: Request):
        token, result = security.default_session(request)
        response = JSONResponse(result)
        response.set_cookie('disclosure_session', token, httponly=True, samesite='lax', secure=request.url.scheme == 'https', max_age=86400*30, path='/')
        return response

    @app.post('/api/session')
    @app.delete('/api/session')
    def removed_login():
        raise HTTPException(410, '用户登录与密码权限已移除；流程由 Verify/Gate 控制')

    def workflow_operation(payload: workflow_operations.Envelope,request: Request):
        actor=security.actor(request);tasks.require_agent(actor)
        cast=workflow_operations.payload
        handlers={
            'task.library.search':lambda a:tasks_api.task_library(a,request),
            'task.library.read':lambda a:tasks_api.task_library(a,request,read=True),
            'drafting.supplement':lambda a:gates_api.drafting_supplement(a.event_id,cast(a,m.DraftingSupplement),request),
            'workflow.reopen':lambda a:gates_api.reopen_event(a.event_id,cast(a,m.Reopen),request),
            'workflow.continuous':lambda a:gates_api.gated_write(a.event_id,a,request,'continuous'),
            'event.list':lambda a:events_api.events(request,a.board),
            'event.create':lambda a:events_api.event_create(a,request),
            'event.get':lambda a:events_api.event_get(a.event_id,request),
            'event.update':lambda a:events_api.event_edit(a.event_id,cast(a,m.Edit),request),
            'rules.check':lambda a:events_api.assess(a.event_id,cast(a,m.Generate),request),
            'task.list':lambda a:tasks_api.task_list(request,a.board),
            'task.request':lambda a:tasks_api.task_create(a.event_id,cast(a,am.TaskCreate),request),
            'task.open':lambda a:tasks_api.open_agent_task(a,request),
            'task.context':lambda a:tasks_api.task_context(a.event_id,a.task_id,request),
            'task.submit':lambda a:tasks_api.task_submit(a.event_id,a.task_id,cast(a,am.Submit),request),
            'task.evaluate':lambda a:tasks_api.task_evaluate(a.event_id,a.task_id,cast(a,am.Submit),request),
            'task.heartbeat':lambda a:tasks_api.task_heartbeat(a.event_id,a.task_id,cast(a,am.Lease),request),
            'task.finish':lambda a:tasks_api.task_finish(a.event_id,a.task_id,cast(a,am.Finish),request),
            'library.search':lambda a:library_api.search(request,collection=a.collection,q=a.query,kind=a.kind,board=a.board,offset=a.offset,limit=a.limit,view=a.view,company=a.company),
            'library.read':lambda a:library_api.item(a.item_id,request,a.page,a.board,a.view,a.company),
            'library.manage':lambda a:library_admin_api.library_manage(a.collection,request,a.board),
            'library.update':lambda a:library_admin_api.library_update(a.collection,cast(a,m.LibraryUpdate),request,a.board),
            'templates.list':lambda a:library_api.templates(request,a.kind,a.board),
            'word.context':lambda a:gates_api.word_context(a.event_id,request),
            'artifact.register':lambda a:gates_api.artifact_upload(a.event_id,cast(a,m.ArtifactUpload),request),
            'verify.run':lambda a:gates_api.verify_event(a.event_id,request,a.stage),
            'gate.advance':lambda a:gates_api.advance(a.event_id,cast(a,m.Verify),request),
            'law.bind':lambda a:gates_api.law_bindings(a.event_id,cast(a,m.LawBindings),request),
            'source.search_report':lambda a:gates_api.source_search(a.event_id,cast(a,m.SourceSearch),request),
            'task.adopt':lambda a:tasks_api.task_adopt(a.event_id,a.task_id,cast(a,m.Generate),request),
            'scenario.list':lambda a:library_admin_api.scenarios(request,a.board),
            'scenario.import':lambda a:library_admin_api.import_scenario(a.scenario_id,cast(a,m.Import),request),
        }
        return workflow_operations.dispatch(payload,handlers)

    from .pi_runtime import PiRuntime
    from .chat_api import mount as mount_chat
    def pi_route(operation,args):
        return workflow_operation(workflow_operations.Envelope(operation=operation,args=args),security.internal_agent_request())['data']
    runtime=PiRuntime(root,directory,pi_route,config=pi_config,runner=pi_runner)
    app.state.pi_runtime=runtime
    mount_chat(app,runtime,security)
    from .company_workspace import mount as mount_company_workspace
    mount_company_workspace(app,runtime,security)
    from .library_workspace import mount as mount_library_workspace
    mount_library_workspace(app,root,runtime,security)
    from .governance_api import mount as mount_governance
    mount_governance(app,root,directory,runtime,security)
    from .api_library import mount as mount_library_api
    library_api=mount_library_api(app,root,seeds,security)
    from .api_context import WorkflowContext
    from .api_gates import mount as mount_gates_api
    context=WorkflowContext(root,directory,seeds,store,security,runtime,legacy_test_mode)
    gates_api=mount_gates_api(app,context,load,read_event)
    from .api_tasks import mount as mount_tasks_api
    tasks_api=mount_tasks_api(app,context,load,read_event)
    from .api_events import mount as mount_events_api
    events_api=mount_events_api(app,context,load,read_event)
    from .api_library_admin import mount as mount_library_admin
    library_admin_api=mount_library_admin(app,context,events_api.create)
    from .api_law_lifecycle import mount as mount_law_lifecycle
    mount_law_lifecycle(app,context)
    return app
