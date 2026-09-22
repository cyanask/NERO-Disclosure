from . import library
from datetime import datetime, timezone, timedelta
import hashlib
from uuid import uuid4
from fastapi import HTTPException
from .domain import COMPANIES, KINDS
from .event_state import invalidate, now
from .disclosure_contract import draft_checks, unresolved



def audit(event, actor, action, detail=''):
    event['updated_at'] = now()
    event['audit'].append({'at':now(), 'actor':actor['actor'], 'channel':actor['channel'], 'action':action, 'revision':event['revision'], 'detail':detail})


def new_event(payload, actor):
    from .boards import require_board
    supplied_name=(payload.get('company_name') or '').strip()
    if supplied_name:
        if payload.get('company_id'):raise HTTPException(422,'已有主体编号与新主体名称不能同时提交')
        board=require_board(payload.get('board'))
        identity=board+':'+(payload.get('stock_code') or supplied_name)
        company={'id':'issuer-'+hashlib.sha256(identity.encode()).hexdigest()[:24],'name':supplied_name,'layer':board}
    else:
        company=next((c for c in COMPANIES if c['id']==payload.get('company_id')),None)
        if not company:raise HTTPException(422,'请提供真实主体名称和所属板块，或选择已有主体')
        if payload.get('board') and payload['board']!=company['layer']:raise HTTPException(422,'板块与已有主体绑定不一致')
    kind=payload.get('kind') or 'unclassified'
    intake_mode='open' if supplied_name or kind not in KINDS else 'legacy'
    facts=dict(payload.get('facts') or {})
    if intake_mode=='open':facts.setdefault('assessment_as_of',facts.get('event_date') or datetime.now(timezone(timedelta(hours=8))).date().isoformat())
    event = {'id':str(uuid4()), 'title':payload['title'], 'company_id':company['id'], 'company_name':company['name'], 'stock_code':payload.get('stock_code'), 'layer':company['layer'], 'kind':kind, 'intake_mode':intake_mode, 'output_mode':payload.get('output_mode','word'), 'summary':payload.get('summary',''), 'facts':facts, 'revision':1, 'stage':'intake', 'created_at':now(), 'updated_at':now(), 'assessment':None, 'plan':None, 'draft':None, 'audit':[]}
    event['workflow_policy']=payload.get('workflow_policy','legacy-v1')
    audit(event, actor, 'create')
    return event




def edit_facts(event, payload, seeds):
    for key in ('title','summary','facts','output_mode'):
        if key in payload:
            event[key] = payload[key]
    invalidate(event)
    library.selected(seeds,event)  # reject mismatched profile before saving facts


def confirm(event, payload, actor, seeds, artifact_directory=None):
    """Only the existing browser session can record a local product confirmation."""
    from . import gates, continuous_workflow as continuous
    if actor['channel']!='web':raise HTTPException(403,'Agent 不能代签产品内人工确认')
    stage=payload['stage'];catalog=seeds.for_event(event).catalog()
    if payload['input_fingerprint']!=gates.fingerprint(event,catalog,stage):
        raise HTTPException(409,'待确认内容或依赖版本已变化，请重新审阅')
    decision=payload['decision']
    if stage=='draft' and not continuous.enabled(event):raise HTTPException(409,'旧流程没有正文确认节点，请先按新流程重新核验')
    if continuous.enabled(event) and stage in ('plan','template'):raise HTTPException(409,'本流程规划与模板由自动核验推进，不记录人工批准')
    if decision=='reject':
        invalidate(event,'draft' if stage=='word' else stage,payload['reason'])
    else:
        report=gates.require(event,seeds,stage,artifact_directory=artifact_directory)
        if stage=='assessment':
            assessment=event['assessment'];matters=assessment['matters']
            if decision not in ('prepare_mandatory','prepare_voluntary','no_disclosure','special_review'):
                raise HTTPException(422,'判断确认须同时记录处理决定')
            if decision=='prepare_mandatory' and assessment['status']!='disclose':
                raise HTTPException(409,'未识别强制义务，不能记录依法准备披露')
            if decision=='prepare_voluntary' and assessment['status']!='no_disclosure':
                raise HTTPException(409,'自愿披露不能掩盖已识别义务或待判断事项')
            if decision=='no_disclosure' and (assessment['status']!='no_disclosure' or not all(m['reassessment_conditions'] for m in matters)):
                raise HTTPException(409,'当前不披露须有相应判断及复判条件')
            if report['next_action']['action']=='manual_escalation' and decision!='special_review':
                raise HTTPException(409,'当前存在紧急、专项或重大分歧；须先处理并重新提交判断')
        elif decision!='accept':raise HTTPException(422,'本节点须确认或退回')
        if stage=='draft' and payload.get('content_review')!='reviewed':
            raise HTTPException(409,'请完整审阅文件清单及全部正文后确认')
        if stage=='word':
            if payload.get('artifact_id')!=event.get('current_artifact_id'):
                raise HTTPException(409,'须确认当前实际 Word 文件')
            if payload.get('visual_review')!='reviewed' or payload.get('content_review')!='reviewed':
                raise HTTPException(409,'当前 Word 尚未完成人工内容和逐页视觉审阅')
        gates.advance(event,seeds,stage,artifact_directory=artifact_directory)
    # Preserve prior decisions even when repeating a confirmation of the same node.
    for record in event.get('approval_records',[]):
        if record['node']==stage and record.get('state')=='current':record.update(state='superseded',superseded_at=now())
    record={'id':str(uuid4()),'case_id':event['id'],'node':stage,
            'artifact_version':(event.get(stage) or {}).get('id',event.get('current_artifact_id')),
            'input_fingerprint':payload['input_fingerprint'],'dependencies':{
                'facts':gates.digest({'facts':event['facts'],'summary':event.get('summary','')}),
                **{name:(gates.current_approval(event,name) or {}).get('id') for name in gates.human_stages(event) if gates.STAGES.index(name)<gates.STAGES.index(stage)}},
            'reviewer':payload['reviewer'].strip(),'actor':actor['actor'],'channel':'web',
            'identity_assurance':'local_self_reported','at':now(),'decision':decision,'reason':payload['reason'],
            'state':'current' if decision!='reject' else 'rejected','legal_approval':False}
    event.setdefault('approval_records',[]).append(record)
    if decision=='reject':return
    # A new upstream decision invalidates only its dependants.
    next_stage={'assessment':'plan','plan':'template','template':'draft'}.get(stage)
    if next_stage:invalidate(event,next_stage,'上游确认或处理决定更新')
    if stage=='assessment':
        event['stage']={'prepare_mandatory':'planning','prepare_voluntary':'planning','no_disclosure':'no_disclosure_manual_tracking','special_review':'specialist_handling'}[decision]
    elif stage=='plan':event['stage']='drafting' if event.get('output_mode')=='text' else 'selecting_template'
    elif stage=='template':event['stage']='drafting'
    elif stage=='draft':
        invalidate(event,'word','正文已人工确认，旧 Word 需按本次正文重新生成')
        event['stage']='text_confirmed' if event.get('output_mode')=='text' else 'draft_verified'
        record['content_sha256']=gates.digest(event['draft'])
    elif stage=='word':
        event['stage']='confirmed_draft_archived'
        artifact=next(a for a in event['artifacts'] if a['id']==payload['artifact_id'])
        artifact.update(status='human_confirmed_unpublished',approval_record_id=record['id'],published=False)
        record.update(artifact_sha256=artifact['sha256'],visual_review='human_self_reported',content_review='human_self_reported')


def supplement(event, payload):
    plan=event.get('plan') or {}
    if not plan.get('id'):raise HTTPException(409,'当前缺少可绑定的规划版本，请先重新载入规划')
    gaps={g['key']:g for g in plan.get('drafting_gaps',[])}
    upstream={f['key'] for f in (event.get('assessment') or {}).get('facts',[])} | event['facts'].keys()
    for key,value in payload['values'].items():
        if key in upstream or key not in gaps or gaps[key]['impact']!='draft' or gaps[key]['treatment']!='supply':
            raise HTTPException(409,'该资料可能改变上游或不在已规划的制稿待补项中，请回 A/B 更新')
        if not value.strip():raise HTTPException(422,'补充资料不能为空')
    invalidate(event,'draft','仅补充规划中已列明的制稿资料')
    event.setdefault('drafting_supplements',{}).update({key:{'value':value,'source_note':payload['source_note'],'at':now(),
        'status':'user_statement','plan_id':plan['id'],'state':'current'} for key,value in payload['values'].items()})


def failed_attempt(event, stage, report):
    from .gates import digest
    # Count distinct repair issues for diagnostics only; never stop at a fixed count.
    issues=[{'code':i['code'],**({'detail':i.get('detail','')} if i['code']=='candidate_schema_invalid' else {})}
            for i in report.get('issues',[])]
    issue_keys=sorted(digest(i) for i in issues) if any(i['code']=='candidate_schema_invalid' for i in issues) else sorted(i['code'] for i in issues)
    signature=digest({'stage':stage,'issues':issue_keys,
                      'facts':event['facts'],'summary':event.get('summary','')})
    attempts=event.setdefault('repair_attempts',{})
    attempts[signature]=attempts.get(signature,0)+1


def reopen(event, payload, actor):
    if event.get('escalation') and actor['channel']!='web':
        raise HTTPException(403,'达到修复上限后须由人工明确恢复；Agent 不能重置计数')
    invalidate(event,payload['stage'],payload['reason'])
    if actor['channel']=='web':
        event.pop('escalation',None)
        event['repair_attempts']={}
