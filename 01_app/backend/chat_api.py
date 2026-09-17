"""Browser-only conversation control; confirmation remains in the workflow API."""
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import Field
from .models import Strict
from .boards import require_board
from .chat_store import LIVE


class SessionCreate(Strict):
    company_code:str=Field(default='',pattern=r'^\d{6}$|^$')
    event_id:str=Field(default='',max_length=100)
    title:str=Field(default='新会话',min_length=1,max_length=100)
    board:Literal['base','innovation','chinext']
    request_id:str=Field(min_length=8,max_length=128)


class SessionEdit(Strict):
    title:str|None=Field(default=None,min_length=1,max_length=100)
    archived:bool|None=None


class Send(Strict):
    company_code:str=Field(default='',max_length=6,pattern=r'^\d{6}$|^$')
    text:str=Field(min_length=1,max_length=20000)
    model_key:str=Field(min_length=1,max_length=80)
    stage:Literal['auto','chat','assessment','plan','template','draft','word']='auto'
    expected_revision:int=Field(default=0,ge=0)
    request_id:str=Field(min_length=8,max_length=128)
    attachment_ids:list[str]=Field(default_factory=list,max_length=8)


class ContinueMessage(Strict):
    text:str=Field(min_length=1,max_length=20000)
    mode:Literal['steer','follow_up']='steer'
    request_id:str=Field(min_length=8,max_length=128)


def mount(app,runtime,security):
    def browser(request):
        actor=security.actor(request)
        if actor['channel']!='web':raise HTTPException(403,'会话控制只接受本机网页操作，Agent 无权自行选择其他模型')
        runtime.own()

    @app.get('/api/chat/models')
    def models(request:Request):
        browser(request);return runtime.capabilities()

    async def settings_body(request, allowed):
        # Avoid Pydantic echoing a mistyped API key in a validation-error body.
        try:
            raw=await request.body()
            if len(raw)>10000000:raise ValueError()
            value=json.loads(raw)
            if not isinstance(value,dict) or set(value)-allowed:raise ValueError()
            return value
        except (ValueError,UnicodeError):raise HTTPException(422,'模型设置请求格式无效') from None

    @app.get('/api/model-settings')
    def model_settings(request:Request):
        browser(request);return runtime.settings.snapshot()

    @app.put('/api/model-settings')
    async def save_model_settings(request:Request):
        browser(request);body=await settings_body(request,{'expected_revision','models','routes'})
        if type(body.get('expected_revision')) is not int:raise HTTPException(422,'缺少模型设置版本')
        return runtime.settings.save(body['expected_revision'],body.get('models'),body.get('routes',{}))

    @app.get('/api/model-settings/catalog')
    def model_catalog(request:Request):
        browser(request);return runtime.settings.catalog()

    @app.post('/api/model-settings/catalog/refresh')
    def refresh_model_catalog(request:Request):
        browser(request);return runtime.settings.catalog(reload=True)

    @app.post('/api/model-settings/gemini/connect')
    async def connect_gemini(request:Request):
        browser(request);body=await settings_body(request,{'expected_revision'})
        if type(body.get('expected_revision')) is not int:raise HTTPException(422,'缺少模型设置版本')
        return runtime.settings.connect_gemini(body.get('expected_revision'))

    @app.post('/api/model-settings/{key}/credential')
    async def save_model_credential(key:str,request:Request):
        browser(request);body=await settings_body(request,{'api_key','provider_env'})
        return await run_in_threadpool(runtime.settings.save_key,key,body.get('api_key'),body.get('provider_env'))

    @app.delete('/api/model-settings/{key}/credential')
    def remove_model_credential(key:str,request:Request):
        browser(request);return runtime.settings.remove_credential(key)

    @app.post('/api/model-settings/providers/{provider}/sync')
    async def sync_provider_models(provider:str,request:Request):
        browser(request);body=await settings_body(request,{'expected_revision','cached'})
        expected=body.get('expected_revision')
        if expected is not None and type(expected) is not int:raise HTTPException(422,'缺少模型设置版本')
        if 'cached' in body and type(body['cached']) is not bool:raise HTTPException(422,'目录刷新参数无效')
        sync=await run_in_threadpool(runtime.settings.sync_provider,provider,expected,body.get('cached',False))
        return {'sync':sync,'settings':await run_in_threadpool(runtime.settings.snapshot)}

    @app.post('/api/model-settings/{key}/login')
    def model_login(key:str,request:Request):
        browser(request);return runtime.settings.begin_login(key)

    @app.post('/api/model-settings/providers/{provider}/login')
    def provider_login(provider:str,request:Request):
        browser(request);return runtime.settings.logins.begin(provider=provider)

    @app.get('/api/model-settings/login/{identity}')
    def model_login_status(identity:str,request:Request):
        browser(request);return runtime.settings.login_status(identity)

    @app.delete('/api/model-settings/login/{identity}')
    def model_login_cancel(identity:str,request:Request):
        browser(request);return runtime.settings.cancel_login(identity)

    @app.post('/api/model-settings/login/{identity}/answer')
    async def answer_model_login(identity:str,request:Request):
        browser(request);body=await settings_body(request,{'prompt_id','value'})
        return runtime.settings.logins.answer(identity,body.get('prompt_id'),body.get('value'))

    @app.post('/api/model-settings/{key}/test')
    def test_model(key:str,request:Request):
        browser(request);return runtime.settings.probe(key)

    @app.get('/api/chat/sessions')
    def sessions(request:Request,board:str,q:str='',archived:bool=False,limit:int|None=None,offset:int=0,company:str=''):
        browser(request);require_board(board)
        if offset<0 or (limit is not None and not 1<=limit<=200):raise HTTPException(422,'分页大小超出范围')
        if not company:return runtime.store.sessions(board,q,archived,limit,offset)
        from .company_workspace import company as registered_company
        registered_company(runtime.root,board,company)
        rows=[s for s in runtime.store.sessions(board,q,archived) if runtime.session_company(s)==company]
        return rows[offset:offset+limit if limit else None]

    @app.post('/api/chat/sessions')
    def create(payload:SessionCreate,request:Request):
        browser(request);require_board(payload.board)
        event=runtime.event(payload.event_id) if payload.event_id else None
        if event and event['layer']!=payload.board:raise HTTPException(409,'不能将其他板块事项加入当前会话')
        code=payload.company_code or (event or {}).get('stock_code') or ''
        if payload.company_code:
            from .company_workspace import company as registered_company
            registered_company(runtime.root,payload.board,code)
            if event and event.get('stock_code')!=code:raise HTTPException(409,'不能将其他公司的事项加入当前会话')
        return runtime.store.create_session(payload.board,payload.event_id,payload.title,payload.request_id,code)

    @app.patch('/api/chat/sessions/{sid}')
    def edit(sid:str,payload:SessionEdit,request:Request):
        browser(request);return runtime.store.edit_session(sid,**payload.model_dump())

    @app.get('/api/chat/sessions/{sid}')
    def detail(sid:str,request:Request,limit:int|None=None,offset:int=0,company:str=''):
        browser(request);session=runtime.store.session(sid)
        if company and runtime.session_company(session)!=company:raise HTTPException(403,'会话不属于当前公司')
        if offset<0 or (limit is not None and not 1<=limit<=500):raise HTTPException(422,'分页大小超出范围')
        return {'session':session,'runs':runtime.store.runs(sid,limit=limit,offset=offset),'event':runtime.event(session['event_id']) if not session['event_id'].startswith('conversation:') else None}

    @app.post('/api/chat/sessions/{sid}/runs')
    def send(sid:str,payload:Send,request:Request):
        browser(request)
        if not payload.text.strip():raise HTTPException(422,'消息不能为空')
        return runtime.accept(sid,{**payload.model_dump(),'stage':'auto'})

    @app.get('/api/chat/runs')
    def runs(request:Request,board:str,limit:int|None=None,offset:int=0,company:str=''):
        browser(request);require_board(board)
        if offset<0 or (limit is not None and not 1<=limit<=500):raise HTTPException(422,'分页大小超出范围')
        if not company:return runtime.store.runs(board=board,limit=limit,offset=offset)
        from .company_workspace import company as registered_company
        registered_company(runtime.root,board,company)
        rows=[r for r in runtime.store.runs(board=board) if (r.get('company_code') or runtime.session_company(runtime.store.session(r['session_id'])))==company]
        return rows[offset:offset+limit if limit else None]

    @app.get('/api/chat/runs/{rid}')
    def run(rid:str,request:Request,after:int=0):
        browser(request);return {'run':runtime.store.run(rid),'events':runtime.store.journal(rid,max(after,0))}

    @app.post('/api/chat/runs/{rid}/cancel')
    def cancel(rid:str,request:Request):
        browser(request);return runtime.cancel(rid)

    @app.post('/api/chat/runs/{rid}/messages')
    def continue_message(rid:str,payload:ContinueMessage,request:Request):
        browser(request)
        if not payload.text.strip():raise HTTPException(422,'消息不能为空')
        return runtime.enqueue_message(rid,payload.text,payload.mode,payload.request_id)

    @app.get('/api/chat/runs/{rid}/stream')
    async def stream(rid:str,request:Request,after:int=0):
        browser(request);runtime.store.run(rid)
        try:cursor=max(after,int(request.headers.get('last-event-id','0')))
        except ValueError:raise HTTPException(422,'无效的事件游标')
        async def produce():
            nonlocal cursor
            while not await request.is_disconnected():
                rows=runtime.store.journal(rid,cursor)
                for row in rows:
                    cursor=row['seq']
                    yield f"id: {cursor}\nevent: receipt\ndata: {json.dumps(row,ensure_ascii=False)}\n\n"
                run=runtime.store.run(rid)
                if run['status'] in LIVE or len(rows)<1000:
                    yield f"event: state\ndata: {json.dumps(run,ensure_ascii=False)}\n\n"
                if run['status'] not in LIVE and len(rows)<1000:break
                await asyncio.sleep(.5)
        return StreamingResponse(produce(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

    @app.get('/api/chat/sessions/{sid}/deletion-preview')
    def deletion_preview(sid:str,request:Request):
        browser(request)
        from .session_deletion import preview
        return preview(runtime,sid)

    @app.delete('/api/chat/sessions/{sid}')
    async def delete_session(sid:str,request:Request):
        browser(request);body=await settings_body(request,{'fingerprint'})
        if not isinstance(body.get('fingerprint'),str):raise HTTPException(422,'删除需要对应范围预览')
        from .session_deletion import delete
        return delete(runtime,sid,body['fingerprint'])

    @app.post('/api/chat/runs/{rid}/knowledge-confirmation')
    async def knowledge_confirmation(rid:str,request:Request):
        browser(request);body=await settings_body(request,{'fingerprint','accept','declarations'})
        if type(body.get('accept')) is not bool or not isinstance(body.get('fingerprint'),str):raise HTTPException(422,'知识变更确认无效')
        from .knowledge_ops import confirm
        return confirm(runtime,rid,body['fingerprint'],body['accept'],body.get('declarations'))

    @app.get('/api/chat/runs/{rid}/source-candidate')
    def source_candidate(rid:str,request:Request):
        browser(request)
        from fastapi.responses import FileResponse
        import hashlib
        value=(runtime.store.run(rid).get('knowledge_change') or {}).get('source')
        if not value:raise HTTPException(404,'本轮没有下载原件')
        path=(runtime.root/value['original_path']).resolve()
        if not path.is_relative_to((runtime.root/'data/public/originals').resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=value['sha256']:raise HTTPException(409,'原件路径或哈希不符')
        return FileResponse(path,filename=path.name)

    @app.get('/api/chat/runs/{rid}/template-candidate')
    def template_candidate(rid:str,request:Request):
        browser(request)
        from fastapi.responses import FileResponse
        from pathlib import Path
        import hashlib
        value=(runtime.store.run(rid).get('knowledge_change') or {}).get('template')
        if not value:raise HTTPException(404,'本轮没有模板候选')
        from .paths import resolve
        path=resolve(runtime.root,value['candidate_path']).resolve()
        if not path.is_relative_to((runtime.local_root/'work/template-candidates').resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=value['sha256']:raise HTTPException(409,'模板候选路径或版本不符')
        return FileResponse(path,filename=path.name)

    @app.get('/api/chat/sessions/{sid}/exports')
    def session_exports(sid:str,request:Request):
        browser(request)
        from . import consult_export
        return consult_export.listing(runtime,sid)

    @app.post('/api/chat/sessions/{sid}/exports')
    async def create_session_export(sid:str,request:Request):
        browser(request)
        runtime.store.session(sid)
        raise HTTPException(410,'单条回复导出已停用。请在会话中提出 Word 需求，由 runtime 整理文稿并调用制作工具。')

    @app.get('/api/chat/sessions/{sid}/exports/{export_id}/file')
    def session_export_file(sid:str,export_id:str,request:Request):
        browser(request)
        from fastapi.responses import FileResponse
        from . import consult_export
        path,filename=consult_export.file_path(runtime,sid,export_id)
        return FileResponse(path,filename=filename)

    from .evidence_api import mount as mount_evidence
    mount_evidence(app,runtime,browser)

    from .document_api import mount as mount_documents
    mount_documents(app,runtime,browser)

    previous_lifespan=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with previous_lifespan(application):
            try:yield
            finally:runtime.close()
    app.router.lifespan_context=lifespan
