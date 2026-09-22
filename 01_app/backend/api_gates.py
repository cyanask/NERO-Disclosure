"""Verify/Gate endpoints: advance, human confirmation, supplements, law rebinding,
search feedback, Word executor context and artifact registration."""
import hashlib
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from . import models as m, agent_tasks as tasks, artifacts, gates, library, word_delivery
from .workflow import audit, confirm, failed_attempt, invalidate, reopen, supplement


class Surface:
    """Route functions the in-process router still dispatches by name."""

    def __init__(self,advance,human_confirmation,drafting_supplement,reopen_event,law_bindings,source_search,
                 word_context,artifact_upload,verify_event,gated_write):
        self.advance=advance
        self.human_confirmation=human_confirmation
        self.drafting_supplement=drafting_supplement
        self.reopen_event=reopen_event
        self.law_bindings=law_bindings
        self.source_search=source_search
        self.word_context=word_context
        self.artifact_upload=artifact_upload
        self.verify_event=verify_event
        self.gated_write=gated_write


def mount(app,ctx,load,read_event):
    @app.get('/api/events/{event_id}/verify')
    def verify_event(event_id: str, request: Request, stage: str = 'assessment'):
        ctx.security.actor(request)
        event=read_event(event_id)
        return gates.evaluate(event,ctx.seeds,stage,artifact_directory=ctx.directory)

    def gated_write(event_id,payload,request,action):
        actor=ctx.security.actor(request);body=payload.model_dump()
        if action=='human_confirmation' and actor['channel']!='web':raise HTTPException(403,'Agent 不能代签产品内人工确认')
        with ctx.store.transaction() as conn:
            key=f"gate:{actor['actor_id']}:{body['request_id']}"
            stamp,cached=ctx.store.cached(conn,key,{'event_id':event_id,'action':action,**body})
            if cached:
                if cached.get('_gate_error'):raise HTTPException(409,cached['_gate_error'])
                return cached
            event=load(conn,event_id)
            if event['revision']!=body['expected_revision']:raise HTTPException(409,'事项版本已变化，请重新读取')
            blocked=None
            if action=='advance':
                try:
                    receipt=gates.advance(event,ctx.seeds,body['stage'],artifact_directory=ctx.directory)
                    event['verification']=receipt
                except HTTPException as exc:
                    if exc.status_code!=409 or not isinstance(exc.detail,dict) or 'gate' not in exc.detail:raise
                    blocked=exc.detail
                    receipt=blocked['gate']
                    event['verification']=receipt
                    failed_attempt(event,body['stage'],receipt)
            elif action=='human_confirmation':
                if body['stage']=='word':
                    artifact=next((a for a in event.get('artifacts',[]) if a['id']==body.get('artifact_id')),None)
                    if not artifact:raise HTTPException(409,'当前 Word 不存在')
                    artifacts.path(ctx.directory,artifact)
                confirm(event,body,actor,ctx.seeds,artifact_directory=ctx.directory)
            elif action=='drafting_supplement':
                supplement(event,body)
            elif action=='reopen':
                reopen(event,body,actor)
            elif action=='continuous':
                from .continuous_workflow import enable
                enable(event,body,actor)
            elif action=='artifact_upload':
                if not ctx.legacy_test_mode and event.get('workflow_policy')!='continuous-v1':raise HTTPException(409,'旧事项须按当前流程重新核验正文后再制作文件')
                artifacts.upload(event,ctx.seeds,ctx.directory,body,actor)
            elif action=='law_bindings':
                catalog=ctx.seeds.for_event(event).catalog();known={row['id']:row for row in catalog['sources']}
                old_ids={sid for r in catalog.get('rules',[]) if r['event_kind']==event['kind'] for sid in r.get('source_ids',[])}
                if event.get('intake_mode')=='open':old_ids.update(known)
                profile=library.selected(ctx.seeds,event) or {}
                old_ids.update(profile.get('normative_source_ids',[]))
                for original,replacement in body['bindings'].items():
                    if original not in old_ids or replacement not in known:raise HTTPException(422,'只能绑定本事项依赖与已收录的法源')
                    if original!=replacement and original not in known[replacement].get('replaces_source_ids',[]):raise HTTPException(422,'替代法源须在法律库登记 replaces_source_ids，禁止无依据替换')
                candidate={**event,'law_bindings':body['bindings']}
                dated={**candidate,'facts':{**candidate['facts'],'event_date':candidate['facts'].get('assessment_as_of') or candidate['facts'].get('event_date') or candidate['created_at'][:10]}}
                errors=gates.source_issues(dated,catalog,list(body['bindings'].values()),legal_only=True)
                if errors:raise HTTPException(409,{'message':'替代法源尚未通过时效与完整性检查','issues':errors})
                invalidate(event);event['law_bindings']=body['bindings']
            elif action=='source_search':
                current=gates.evaluate(event,ctx.seeds,body['stage'],require_result=False)
                if current['input_fingerprint']!=body['input_fingerprint']:raise HTTPException(409,'检索反馈已不是当前输入版本')
                if current['status']!='BLOCKED':raise HTTPException(409,'当前事项没有待处理的法源阻断')
                if body['status']=='found' and not body['urls']:raise HTTPException(422,'检索到来源须记录原文地址')
                event['source_search']={**body,'channel':actor['channel'],'message':body['message']}
                event['verification']=gates.evaluate(event,ctx.seeds,body['stage'],require_result=False)
            event['revision']+=1;audit(event,actor,action+'_blocked' if blocked else action,event.get('verification') if blocked else body.get('message',''))
            tasks.refresh(event,ctx.seeds);ctx.store.save(conn,event)
            result={'_gate_error':blocked} if blocked else tasks.project_event(event)
            ctx.store.cache(conn,key,stamp,result)
        if blocked:raise HTTPException(409,blocked)
        return result

    @app.post('/api/events/{event_id}/advance')
    def advance_event(event_id: str,payload: m.Verify,request: Request):
        return gated_write(event_id,payload,request,'advance')

    @app.post('/api/events/{event_id}/confirmations')
    def human_confirmation(event_id: str,payload: m.HumanConfirmation,request: Request):
        result=gated_write(event_id,payload,request,'human_confirmation')
        if payload.decision!='reject':
            result={**result,'continuation':ctx.runtime.resume_after_confirmation(result)}
        return result

    @app.post('/api/events/{event_id}/drafting-supplements')
    def drafting_supplement(event_id: str,payload: m.DraftingSupplement,request: Request):
        return gated_write(event_id,payload,request,'drafting_supplement')

    @app.post('/api/events/{event_id}/reopen')
    def reopen_event(event_id: str,payload: m.Reopen,request: Request):
        return gated_write(event_id,payload,request,'reopen')

    @app.post('/api/events/{event_id}/law-bindings')
    def law_bindings(event_id: str,payload: m.LawBindings,request: Request):
        return gated_write(event_id,payload,request,'law_bindings')

    @app.post('/api/events/{event_id}/source-search')
    def source_search(event_id: str,payload: m.SourceSearch,request: Request):
        return gated_write(event_id,payload,request,'source_search')

    @app.get('/api/events/{event_id}/word/context')
    def word_context(event_id: str,request: Request):
        import base64
        ctx.security.actor(request)
        event=read_event(event_id)
        if not ctx.legacy_test_mode and event.get('workflow_policy')!='continuous-v1':raise HTTPException(409,'旧事项须按当前流程重新核验正文后再制作文件')
        if event.get('output_mode')=='text':raise HTTPException(409,'本轮只形成正文，未请求 Word 生产')
        from .continuous_workflow import require_content_confirmation
        require_content_confirmation(event,ctx.seeds)
        gate=gates.require(event,ctx.seeds,'draft');draft=event['draft']
        template_sha=draft.get('template_sha256','')
        if len(template_sha)!=64 or any(c not in '0123456789abcdef' for c in template_sha):raise HTTPException(409,'模板快照缺失')
        template_root=(ctx.directory/'templates').resolve();template=template_root/(template_sha+'.docx')
        if template.is_symlink() or not template.is_file() or hashlib.sha256(template.read_bytes()).hexdigest()!=template_sha:raise HTTPException(409,'模板快照校验失败')
        return {'event':tasks.project_event(event),'expected_revision':event['revision'],'input_fingerprint':gate['input_fingerprint'],
            'layout':word_delivery.layout(ctx.seeds,event),'template_sha256':template_sha,'template_base64':base64.b64encode(template.read_bytes()).decode(),
            'executor':'external_agent','upload_operation':'artifact.register'}

    @app.post('/api/events/{event_id}/artifacts')
    def artifact_upload(event_id: str,payload: m.ArtifactUpload,request: Request):
        return gated_write(event_id,payload,request,'artifact_upload')

    @app.get('/api/events/{event_id}/artifacts/{artifact_id}/preview')
    def artifact_preview(event_id: str,artifact_id: str,request: Request):
        ctx.security.actor(request)
        event=read_event(event_id)
        artifact=next((a for a in event.get('artifacts',[]) if a['id']==artifact_id),None)
        if not artifact:raise HTTPException(404,'交付物不存在')
        from .document_files import inspect
        raw=artifacts.path(ctx.directory,artifact).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=artifact['sha256']:raise HTTPException(409,'交付文件已变化，不能预览该登记版本')
        return {'text':inspect(raw)['text'],'notice':'这是该版本 Word 的正文预览；文件仍须按实际内容审阅。'}

    @app.get('/api/events/{event_id}/artifacts/{artifact_id}/file')
    def artifact_file(event_id: str,artifact_id: str,request: Request):
        ctx.security.actor(request)
        event=read_event(event_id)
        artifact=next((a for a in event.get('artifacts',[]) if a['id']==artifact_id),None)
        if not artifact:raise HTTPException(404,'交付物不存在')
        return FileResponse(artifacts.path(ctx.directory,artifact),filename=artifact['filename'])

    return Surface(advance_event,human_confirmation,drafting_supplement,reopen_event,law_bindings,source_search,
                   word_context,artifact_upload,verify_event,gated_write)
