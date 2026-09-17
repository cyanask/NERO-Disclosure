"""Register verified Word artifacts with the existing Gate and event lifecycle."""
import base64
import hashlib
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from . import gates, word_delivery
from .artifact_checks import check, check_user_template, normalized, path, template_bytes


def upload(event,seeds,directory,payload,actor):
    from .continuous_workflow import require_content_confirmation
    require_content_confirmation(event,seeds)
    gate=gates.require(event,seeds,'draft')
    if payload['input_fingerprint']!=gate['input_fingerprint']:raise HTTPException(409,'交付物对应的输入版本已变化')
    try:raw=base64.b64decode(payload['content_base64'],validate=True)
    except (ValueError,TypeError):raise HTTPException(422,'文件编码无效')
    if not 1<=len(raw)<=6000000 or not payload['filename'].lower().endswith('.docx'):raise HTTPException(422,'仅接收不超过6MB的Word交付文件')
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=payload['sha256']:raise HTTPException(422,'交付物文件哈希不符')
    layout=word_delivery.layout(seeds,event)
    if not layout:raise HTTPException(409,'文种尚未绑定版式规则')
    template_raw=None
    if layout.get('template_authority')=='user_uploaded':
        template_raw=template_bytes(seeds,event)
    verification=check(raw,event,layout,template_raw)
    if verification['status']!='PASS':raise HTTPException(422,{'message':'交付物 Verify 未通过','verification':verification})
    folder=Path(directory)/'artifacts'
    if folder.is_symlink():raise HTTPException(409,'交付物目录无效')
    folder.mkdir(exist_ok=True)
    filename=digest+'.docx';target=folder/filename
    if target.exists():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise HTTPException(409,'已有文件哈希或路径异常')
    else:
        with target.open('xb') as stream:stream.write(raw)
    prior=next((a for a in event.get('artifacts',[]) if a['sha256']==digest and a['input_fingerprint']==gate['input_fingerprint']),None)
    if not prior:
        event.setdefault('artifacts',[]).append({'id':uuid4().hex,'file':filename,'filename':payload['filename'],
            'sha256':digest,'bytes':len(raw),'input_fingerprint':gate['input_fingerprint'],
            'status':'registered','verification':verification,'producer':actor['actor'],
            'host_qa':payload.get('host_qa',''),'host_qa_assurance':'self_reported'})
    from .workflow import invalidate
    current=prior or event['artifacts'][-1]
    if event.get('current_artifact_id')!=current['id']:
        invalidate(event,'word','当前 Word 文件更新')
    event['current_artifact_id']=current['id']
    event['stage']='awaiting_word_confirmation'
