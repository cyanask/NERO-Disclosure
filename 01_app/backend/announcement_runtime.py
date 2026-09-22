"""Announcement context and user-message-bound text confirmation; no legal approval."""
import re
from fastapi import HTTPException
from . import document_store as store


def conversation_documents(runtime,run):
    index=store.load(runtime,run['session_id'])
    current=[d['versions'][-1] for d in index['documents']]
    previous=next((r for r in runtime.store.runs(run['session_id']) if r['id']!=run['id']),None)
    presented=[{k:d[k] for k in ('document_id','version','sha256')} for d in (previous or {}).get('documents',[]) if d.get('format')=='text']
    runtime.store.update(run['id'],confirmation_targets=presented)
    return {'current':[{k:r.get(k) for k in ('document_id','version','title','kind','format','review_status')} for r in current],
            'last_task':(previous or {}).get('stage'),'last_presented_drafts':presented}


def existing_word(runtime,run,identity=None):
    candidates=[d['versions'][-1] for d in store.load(runtime,run['session_id'])['documents']]
    candidates=[d for d in candidates if d['kind']=='announcement' and d.get('format','docx')=='docx' and (identity is None or d['document_id']==identity)]
    return candidates[0] if len(candidates)==1 else None


def confirm_text(runtime,run,args):
    user=next((r for r in runtime.store.journal(run['id']) if r['kind']=='user'),None)
    text=str((user or {}).get('body',{}).get('text',''))
    confirmation=text.strip().rstrip('。！! ')
    confirmation=re.sub(r'[,，。；;\s]*(?:并|然后|再)?(?:请)?(?:生成|制作|导出)(?:为|成)?(?:Word|docx)(?:文档|文件)?$', '', confirmation,flags=re.I)
    normalized=re.sub(r'[\s，,。.!！；;]', '', confirmation)
    affirmations={'确认','确认正文','确认当前正文','确认这个版本','确认当前版本','确认本版','确认这版','正文确认','这版确认','认可正文','同意正文','确认全部正文','全部确认'}
    if normalized not in affirmations:
        raise HTTPException(409,'该回复包含其他含义或修改要求，未自动记录正文确认；请针对当前正文明确确认')
    fresh=runtime.store.run(run['id'])
    targets=fresh.get('confirmation_targets') or []
    if args.get('target_document_id'):targets=[t for t in targets if t['document_id']==args['target_document_id']]
    if not targets or len(targets)>1 and '全部' not in normalized:
        raise HTTPException(409,'当前确认对象不唯一，请指明文稿或回复“全部确认”')
    with runtime.lock:
        for target in targets:
            row=store.version(runtime,run['session_id'],target['document_id'])
            if row.get('format')!='text' or row['version']!=target['version'] or row['sha256']!=target['sha256']:
                raise HTTPException(409,'公告正文版本已变化，未确认旧稿')
        confirmed=[store.review(runtime,run['session_id'],t['document_id'],{
            'version':t['version'],'sha256':t['sha256'],'decision':'accepted','content_reviewed':True,'visual_reviewed':False,
            'source_run_id':run['id'],'source_message_seq':user['seq']}) for t in targets]
        runtime.trace(run['id'],'text_confirmed',{'documents':confirmed,'user_message_seq':user['seq'],'business_state_changed':False})
        runtime.store.update(run['id'],stage='confirmation',outcome='completed',documents=confirmed,skill_status='not_applicable')
        runtime.trace(run['id'],'assistant',{'phase':'final','stopReason':'stop','text':'已记录当前公告正文版本的确认，后续修改将另存版本。'})
    return {'data':{'status':'text_confirmed','documents':confirmed,'business_state_changed':False},'terminate':True}
