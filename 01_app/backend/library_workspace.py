"""File-based knowledge actions; the UI and Pi share these same operations."""
import base64
import json
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from . import announcement_history as history, file_ingestion, library_admin, paths as workspace_paths, public_sources, template_authoring


def deletion_preview(root, runtime, board, collection, ids, company=''):
    if not isinstance(ids,list) or not 1<=len(ids)<=200 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise HTTPException(422,'请选择具体资料')
    state=history.state(root,board,company) if collection=='history' else library_admin.state(root,collection,board)
    rows=history.visible(state) if collection=='history' else state['items'];byid={r['id']:r for r in rows}
    if set(ids)-byid.keys():raise HTTPException(404,'部分资料不存在于当前范围')
    if any(byid[i].get('company_scope') not in (None,'',company) for i in ids):raise HTTPException(403,'所选模板不属于当前公司')
    from .knowledge_references import references
    refs=references(runtime,board,ids)
    result={'board':board,'company':company,'collection':collection,'ids':ids,'expected_fingerprint':state['fingerprint'],
        'objects':[{'id':i,'title':byid[i]['title']} for i in ids],'references':refs,
        'notice':'删除当前库条目及检索结果；保留原件和必要历史引用以便恢复。本地删除不代表市场公告撤回。'}
    result['fingerprint']=library_admin.sha(history.encoded(result));return result


def delete(root,runtime,preview,fingerprint):
    current=deletion_preview(root,runtime,preview['board'],preview['collection'],preview['ids'],preview.get('company',''))
    if current['fingerprint']!=fingerprint:raise HTTPException(409,'删除范围或引用已变化，请重新预览')
    if current['collection']=='history':
        def change(value):
            for row in value['items']:
                if row['id'] in current['ids']:row['deleted_at']=history.now()
            value['coverage'].update(complete=False,note='存在删除记录，历史覆盖待重新核对')
        result=history.save(root,current['board'],current['company'],current['expected_fingerprint'],change,'用户删除')
        return {'status':'deleted','deleted_ids':current['ids'],'fingerprint':result['fingerprint']}
    return library_admin.remove(root,current['collection'],current['ids'],current['expected_fingerprint'],current['board'])


def mount(app,root,runtime,security):
    def user(request):
        actor=security.actor(request)
        if actor['channel']!='web':raise HTTPException(403,'此入口仅接受用户操作；Pi 使用登记工具')
        return actor

    @app.get('/api/announcement-schedule')
    def schedule(request:Request,board:str,company:str,q:str='',deleted:bool=False,tag:str='',form:str=''):
        from .announcement_schedule import listing
        user(request);result=listing(root,board,company,q,deleted,tag,form)
        run=next((r for r in runtime.store.runs(board=board) if r['stage']=='classification' and r.get('company_code')==company),None)
        result['classification_run']={k:run.get(k) for k in ('id','session_id','status','reason')} if run else None
        return result

    @app.post('/api/announcement-schedule/review')
    async def review_announcements(request:Request):
        user(request);body=await request.json()
        from .announcement_review import enqueue
        if body.get('expected_sources') is not None:
            from .announcement_tags import source_key
            current=history.state(root,body['board'],body['company'])
            actual={r['id']:source_key(r) for r in history.visible(current) if r['id'] in body.get('ids',[])}
            if actual!=body['expected_sources']:raise HTTPException(409,'本机公告范围或版本与下载批次不一致')
        return await run_in_threadpool(enqueue,runtime,body['board'],body['company'],body.get('ids'),body.get('model_key'))

    @app.get('/api/announcements/{identity}')
    def announcement(request:Request,identity:str,board:str,company:str,page:int|None=None):
        user(request);return history.read(root,board,company,identity,page)

    @app.get('/api/announcements/{identity}/original')
    def announcement_original(request:Request,identity:str,board:str,company:str):
        user(request);row=history.read(root,board,company,identity)
        path=Path(root)/row['original_path'];return FileResponse(path,filename=row['title']+path.suffix)

    @app.patch('/api/announcement-schedule')
    async def correct_schedule(request:Request):
        user(request);body=await request.json();board=body['board'];company=body['company'];changes=body.get('changes',{})
        allowed={'announcement_number','meeting_date','meeting','related_ids','relation','classification_override'}
        if set(changes)-allowed or not body.get('reason','').strip():raise HTTPException(422,'请提供字段修正及原因')
        if changes.get('meeting') and (not isinstance(changes['meeting'],dict) or set(changes['meeting'])-{'organ','term','year','sequence','basis','meeting_type'}):raise HTTPException(422,'会议字段无效')
        if changes.get('meeting_date'):
            try:__import__('datetime').date.fromisoformat(changes['meeting_date'])
            except (TypeError,ValueError):raise HTTPException(422,'会议日期无效')
        def update(value):
            row=next((r for r in history.visible(value) if r['id']==body['id']),None)
            if not row:raise HTTPException(404,'公告不存在')
            if 'classification_override' in changes:
                from .announcement_schedule import correction
                changes['classification_override']=correction(row,changes['classification_override'])
            if set(changes.get('related_ids',[]))-{r['id'] for r in history.visible(value)}:raise HTTPException(422,'关联公告不属于当前公司')
            row.setdefault('corrections',[]).append({'before':{k:row.get(k) for k in changes},'reason':body['reason'],'at':history.now(),'actor':'用户修正'})
            row.update(changes)
        return history.save(root,board,company,body['fingerprint'],update,'用户修正')

    @app.post('/api/announcement-schedule/coverage')
    async def coverage(request:Request):
        user(request);body=await request.json();coverage=body['coverage']
        from datetime import date
        try:
            if date.fromisoformat(coverage['from'])>date.fromisoformat(coverage['through']) or date.fromisoformat(coverage['through'])>date.today():raise ValueError()
            if type(coverage['complete']) is not bool:raise ValueError()
        except (TypeError,ValueError,KeyError):raise HTTPException(422,'请填写有效的覆盖期间')
        return history.save(root,body['board'],body['company'],body['fingerprint'],lambda v:v.update(coverage={**coverage,'confirmed_by':'用户','at':history.now()}),'用户确认覆盖范围')

    @app.post('/api/announcement-schedule/restore')
    async def restore(request:Request):
        user(request);body=await request.json()
        def change(value):
            row=next((r for r in value['items'] if r['id']==body['id'] and r.get('deleted_at')),None)
            if not row:raise HTTPException(404,'没有这条已删除记录')
            row.pop('deleted_at');value['coverage'].update(complete=False,note='已恢复公告，覆盖范围待重新核对')
        return history.save(root,body['board'],body['company'],body['fingerprint'],change,'用户恢复')

    @app.post('/api/library/imports')
    async def upload(request:Request):
        user(request);body=await request.json();url=body.get('url','')
        if url:
            raw,_,url=await run_in_threadpool(public_sources.fetch,url);filename=url.rsplit('/',1)[-1]
        else:
            try:raw=base64.b64decode(body.get('file_base64',''),validate=True)
            except (ValueError,TypeError):raise HTTPException(422,'上传文件编码无效')
            filename=body.get('filename','uploaded.docx')
        return await run_in_threadpool(file_ingestion.prepare,root,body['board'],body['collection'],raw,filename,body.get('company',''),url)

    @app.get('/api/library/imports/{identity}')
    def import_detail(request:Request,identity:str,board:str,company:str='',collection:str|None=None):
        user(request);return file_ingestion.get(root,identity,board,collection,company)

    @app.get('/api/library/imports/{identity}/original')
    def import_original(request:Request,identity:str,board:str,company:str=''):
        user(request);value=file_ingestion.get(root,identity,board,company=company)
        path=workspace_paths.resolve(root,value['original_path']);return FileResponse(path,filename=value['filename'])

    @app.post('/api/library/imports/{identity}/commit')
    async def commit(request:Request,identity:str):
        user(request);body=await request.json()
        result=await run_in_threadpool(file_ingestion.commit,root,identity,body['board'],body['collection'],body.get('company',''),body['metadata'],'用户入库',body.get('fingerprint'))
        if body['collection']=='history':
            from .announcement_review import enqueue
            result['classification_run']=await run_in_threadpool(enqueue,runtime,body['board'],body['company'],[result['id']])
        return result

    @app.post('/api/library/deletion-preview')
    async def preview_delete(request:Request):
        user(request);body=await request.json()
        return deletion_preview(root,runtime,body['board'],body['collection'],body['ids'],body.get('company',''))

    @app.post('/api/library/delete')
    async def delete_library(request:Request):
        user(request);body=await request.json();return delete(root,runtime,body['preview'],body['fingerprint'])

    @app.post('/api/library/template-replacement')
    async def replace(request:Request):
        user(request);body=await request.json()
        return template_authoring.replacement(root,body['board'],body['import_id'],body['profile_id'],body.get('company',''),body.get('fingerprint'),body.get('apply') is True)

    @app.post('/api/library/template-upload')
    async def add_template(request:Request):
        user(request);body=await request.json()
        return template_authoring.add_uploaded(root,body['board'],body['import_id'],body['base_profile_id'],body['title'],body.get('company',''))

    @app.get('/api/library/template-file/{profile_id}')
    def template_file(request:Request,profile_id:str,board:str,company:str=''):
        user(request)
        from .domain import Seeds
        seeds=Seeds(root,board,{'stock_code':company})
        entry=next((x for x in seeds.templates() if x.get('profile_id')==profile_id),None)
        if not entry:raise HTTPException(404,'没有可下载的模板')
        path=(Path(root)/'templates'/entry['file']).resolve()
        if not path.is_relative_to((Path(root)/'templates').resolve()):raise HTTPException(403,'模板路径越界')
        return FileResponse(path,filename=entry['name']+'.docx')
