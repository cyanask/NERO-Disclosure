"""Read and review saved output. Word generation is exclusively a Pi tool."""
import json
from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from . import document_store as store, document_files
from .boards import require_board


def mount(app, runtime, browser):
    async def body(request, allowed, maximum=10000):
        raw = await request.body()
        if len(raw) > maximum:
            raise HTTPException(413, '请求超过文档大小限制')
        try:
            value = json.loads(raw)
        except ValueError:
            raise HTTPException(422, '文档请求格式无效') from None
        if not isinstance(value, dict) or set(value) - allowed:
            raise HTTPException(422, '文档请求字段无效')
        return value

    @app.post('/api/chat/sessions/{sid}/attachments')
    async def upload_attachment(sid:str,request:Request):
        browser(request)
        value=await body(request,{'filename','content_base64'},30000000)
        from .conversation_attachments import upload
        return await run_in_threadpool(upload,runtime,sid,value.get('filename'),value.get('content_base64'))

    @app.get('/api/documents')
    def company_documents(request: Request, board: str, company: str = Query(pattern=r'^\d{6}$')):
        browser(request)
        require_board(board)
        from .company_workspace import company as registered_company
        registered_company(runtime.root, board, company)
        items, warnings = [], []
        # Archived conversations retain their delivered files. This is only a
        # projection of existing versions, never a second registration or copy.
        for archived in (False, True):
            for session in runtime.store.sessions(board, archived=archived):
                if runtime.session_company(session) != company:
                    continue
                try:
                    documents = store.listing(runtime, session['id'])['items']
                except HTTPException:
                    warnings.append('会话《'+session['title']+'》的文件记录暂时无法读取，请在会话中核对。')
                    continue
                for row in documents:
                    if row.get('format', 'docx') != 'docx':
                        continue
                    items.append({**{k:v for k,v in row.items() if k not in ('history', 'text')},
                                  'session_id':session['id'], 'session_title':session['title'],
                                  'session_archived':bool(session['archived'])})
        return {'items':sorted(items, key=lambda row:row['created'], reverse=True), 'warnings':warnings}

    @app.get('/api/chat/sessions/{sid}/documents')
    def documents(sid: str, request: Request):
        browser(request)
        return store.listing(runtime, sid)

    @app.get('/api/chat/sessions/{sid}/documents/{document_id}/versions/{number}/file')
    def download(sid: str, document_id: str, number: int, request: Request):
        browser(request)
        path, row = store.file(runtime, sid, document_id, number)
        return FileResponse(path, filename=row['filename'])

    @app.get('/api/chat/sessions/{sid}/documents/{document_id}/versions/{number}/preview')
    def preview(sid: str, document_id: str, number: int, request: Request):
        browser(request)
        row=store.version(runtime,sid,document_id,number)
        if row.get('format','docx')=='text':parsed={'text':store.snapshot(runtime,sid,document_id,number)['text']}
        else:
            path, row = store.file(runtime, sid, document_id, number)
            parsed = document_files.inspect(path.read_bytes())
        return {'document': store.public_version(sid, row), 'text': parsed['text'],
                'preview_kind': 'text_only', 'notice': '文字预览；实际分页和版式请打开 Word 核对。'}

    @app.post('/api/chat/sessions/{sid}/documents/{document_id}/open')
    def open_working_copy(sid:str,document_id:str,request:Request):
        browser(request)
        raise HTTPException(410, '请下载 Word 后在本机使用；系统外修改不再接回会话。')

    @app.post('/api/chat/sessions/{sid}/documents/{document_id}/review')
    async def review(sid: str, document_id: str, request: Request):
        browser(request)
        value = await body(request, {'version', 'sha256', 'decision', 'content_reviewed', 'visual_reviewed'}, 10000)
        return store.review(runtime, sid, document_id, value)

    @app.post('/api/chat/sessions/{sid}/documents/import')
    async def import_source(sid: str, request: Request):
        browser(request)
        raise HTTPException(410, '会话仅输出 Word，不再接回系统外修改稿；请在会话中提出修改要求。')
