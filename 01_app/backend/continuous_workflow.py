"""Work-draft progression policy; never manufactures human approval records."""
from fastapi import HTTPException
from .continuous_policy import POLICY, assessment_exception, enabled, next_stage, requires_human

def verified(event,catalog,stage):
    from . import gates
    row=event.get('verified_stages',{}).get(stage) or {}
    return row.get('status')=='PASS' and row.get('input_fingerprint')==gates.fingerprint(event,catalog,stage)

def require_content_confirmation(event,seeds):
    from . import gates
    if enabled(event) and not gates.approval_valid(event,seeds.for_event(event).catalog(),'draft'):
        raise HTTPException(409,'制作 Word 前必须人工确认当前完整正文；内容或依赖变化后须重新确认')

def enable(event,body,actor):
    from .event_state import invalidate
    if actor['channel']!='agent':raise HTTPException(403,'连续执行上下文只接受当前 Pi 内部运行身份')
    if not enabled(event):
        if any(t['status'] in ('pending','claimed','submitted','expired') for t in event.get('agent_tasks',[])):
            raise HTTPException(409,'旧事项仍有未结任务，请先停止或处理')
        invalidate(event,'assessment','已授权切换连续工作稿流程，旧记录保留并重新核验')
        event['workflow_policy']=POLICY
    event['continuation_context']={k:body[k] for k in ('session_id','model_key','run_id')}
