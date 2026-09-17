"""R5: deterministic, current-input Verify/Gate. No caller can approve a failure."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from . import library, stage_skills, disclosure_contract as contract
from .continuous_policy import assessment_exception, enabled, requires_human
from .gate_checks import (LEGAL_KINDS, assessment_stage, draft_prologue, draft_stage, issue, law_basis, layout_issues,
                          plan_stage, review_notes, source_issues, template_stage, text_draft_stage, word_stage)

STAGES = ('assessment','plan','template','draft','word')
HUMAN_STAGES = ('assessment','plan','template','word')
# 月检与核验记录不属于业务版本：刷新核验日期不得使已确认文稿失效。
LIFECYCLE_FIELDS = ('as_of','reviewed_at','next_review_at','review_status','review_note')
def human_stages(event):return ('assessment','draft','word') if enabled(event) else HUMAN_STAGES

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def verified_receipt(event,catalog,stage):
    """A stage receipt counts only while it matches the current input fingerprint."""
    row=event.get('verified_stages',{}).get(stage) or {}
    return row.get('status')=='PASS' and row.get('input_fingerprint')==fingerprint(event,catalog,stage)


def catalog_binding(catalog, stage):
    # Template/layout changes must not discard an unchanged legal judgment.
    excluded = {'templates','template_asset_state','layout_profiles'} if stage in ('assessment','plan') else set()
    if stage == 'assessment':excluded |= {'profiles'}
    bound = {k:v for k,v in catalog.items() if k not in excluded and k != 'asset_state'}
    if stage == 'assessment':bound['cases']=[c for c in catalog.get('cases',[]) if library.admitted_case(c,catalog['board'])]
    paths = {row[key] for group in ('sources', 'cases')
             for row in bound.get(group, []) for key in ('original_path','document_path') if row.get(key)}
    if stage not in ('assessment','plan'):
        paths.update(row['source_observations_path'] for row in catalog.get('layout_profiles',[]) if row.get('source_observations_path'))
    bound['asset_state'] = {p:catalog.get('asset_state',{}).get(p) for p in paths}
    if 'sources' in bound:
        bound['sources']=[{k:v for k,v in row.items() if k not in LIFECYCLE_FIELDS} for row in bound['sources']]
    return bound


def fingerprint(event, catalog, stage):
    text_draft=event.get('output_mode')=='text' and stage=='draft'
    sections = {}
    for name in STAGES[:STAGES.index(stage)+1]:
        if text_draft and name=='template':continue
        section = copy.deepcopy(event.get(name))
        if section:
            for key in ('approved','verified','checks','word','review_readiness','drafting_readiness','review_warnings'):
                section.pop(key,None)
        sections[name] = section
    upstream = {name: (current_approval(event,name) or {}).get('id')
                for name in human_stages(event) if STAGES.index(name) < STAGES.index(stage) and not (text_draft and name=='template')}
    return digest({'facts':event['facts'],'company_id':event['company_id'],'kind':event['kind'],
        'company_name':event['company_name'],'stock_code':event.get('stock_code'),'intake_mode':event.get('intake_mode'), 'output_mode':event.get('output_mode','word'),
        'law_bindings':(event.get('law_bindings') or {}),'title':event['title'],'summary':event.get('summary',''),
        'sections':sections,'catalog':catalog_binding(catalog,'plan' if text_draft else stage),'upstream_confirmations':upstream,
        'drafting_supplements':event.get('drafting_supplements',{}) if stage in ('draft','word') else None,
        'artifact':event.get('current_artifact_id') if stage=='word' else None})


def current_approval(event, stage):
    return next((r for r in reversed(event.get('approval_records') or [])
                 if r['node']==stage and r.get('state')=='current'),None)


def approval_valid(event, catalog, stage):
    record=current_approval(event,stage)
    return bool(record and record['decision']!='reject' and record['input_fingerprint']==fingerprint(event,catalog,stage))


def upstream_issues(event, catalog, stage):
    errors=[]
    if enabled(event):
        for upstream in STAGES[:STAGES.index(stage)]:
            if upstream=='template' and event.get('output_mode')=='text':continue
            if not verified_receipt(event,catalog,upstream):errors.append(issue('upstream_not_verified','缺少当前版本自动核验：'+upstream))
        if stage!='assessment' and assessment_exception(event):
            record=current_approval(event,'assessment') or {}
            if not approval_valid(event,catalog,'assessment') or record.get('decision') not in ('prepare_mandatory','prepare_voluntary'):
                errors.append(issue('preparation_decision_missing','当前处理方向需要人工决定'))
        if stage=='word' and not approval_valid(event,catalog,'draft'):
            errors.append(issue('content_not_confirmed','Word 制作前缺少当前完整正文的人工确认'))
        return errors
    for upstream in HUMAN_STAGES:
        if STAGES.index(upstream)>=STAGES.index(stage):continue
        if event.get('output_mode')=='text' and stage=='draft' and upstream=='template':continue
        if not approval_valid(event,catalog,upstream):
            errors.append(issue('upstream_not_confirmed','缺少当前版本人工确认：'+upstream))
    if stage!='assessment':
        decision=(current_approval(event,'assessment') or {}).get('decision')
        if decision not in ('prepare_mandatory','prepare_voluntary'):
            errors.append(issue('preparation_decision_missing','尚未有效确认准备本次披露的处理决定'))
    return errors


def evaluate(event, seeds, stage, *, catalog=None, require_result=True, artifact_directory=None, review=None):
    seeds = seeds.for_event(event)
    if stage not in STAGES:raise HTTPException(422,'业务节点无效')
    if catalog is not None and catalog.get('board') != seeds.board:
        raise HTTPException(422,'校验快照与事项板块不一致')
    catalog=catalog if catalog is not None else seeds.catalog()
    # Verdicts recorded on the live task apply only to the candidate they were bound to.
    # A changed candidate or changed input silently falls back to a fresh review.
    if review is None:
        for task in reversed(event.get('agent_tasks',[]) or []):
            stored=task.get('semantic_review')
            if task.get('stage')!=stage or not stored or task.get('status')=='stale':continue
            if stored.get('candidate_sha256')==digest(task.get('result')) and isinstance(stored.get('verdicts'),list):
                review={v['item_id']:v for v in stored['verdicts'] if isinstance(v,dict) and isinstance(v.get('item_id'),str)}
            break
    dated=copy.deepcopy(event)
    assessment=event.get('assessment') or {}
    as_of=event['facts'].get('assessment_as_of') or event['facts'].get('event_date') or event['created_at'][:10]
    dated['facts']['event_date']=as_of
    errors,law_notes=law_basis(dated,catalog)
    if event.get('output_mode')=='text' and stage in ('template','word'):
        errors.append(issue('output_scope_mismatch','本轮只形成正文，不进入 Word 模板或文件生产节点'))
    if assessment and str(assessment.get('assessment_as_of'))!=as_of:
        errors.append(issue('assessment_date_mismatch','判断基准日与任务绑定日期不一致；不能由模型改日期绕过时效检查'))
    errors+=upstream_issues(event,catalog,stage)
    warnings=list(law_notes);review_items=[]
    if stage in ('draft','word'):
        conflicts,notes=draft_prologue(event,seeds,catalog)
        errors.extend(conflicts);warnings.extend(notes)
    if stage in ('draft','word'):
        plan_warnings=(event.get('plan') or {}).get('review_warnings',[]) or (event.get('verified_stages',{}).get('plan') or {}).get('warnings',[])
        warnings.extend(copy.deepcopy(w) for w in plan_warnings
                        if w.get('code') in ('format_coverage_review','format_field_coverage_review','requirement_basis_review'))
        for row in (event.get('plan') or {}).get('requirements',[]):
            if row.get('applicability_status')=='not_applicable':warnings.append(issue('requirement_exclusion_review','终稿时核对不适用项：'+row['topic']+'；'+row['applicability']))
        for gap in (event.get('plan') or {}).get('drafting_gaps',[]):
            if gap.get('impact')=='content_review':warnings.append(issue('human_content_review','终稿确认时核对：'+gap['description']))
            if gap.get('impact')=='publication':warnings.append(issue('publication_action_pending','公司发布前另行完成：'+gap['description']))
    if event.get('intake_mode')=='open':
        warnings.append(issue('source_led_assessment','事项已接纳；类别与义务由法源和事实判断，未命中预置规则不表示无需披露'))
    result=event.get(stage)
    cited={x.get('id') for x in (event.get('assessment') or {}).get('citations',[])}
    cited.update(x for row in (event.get('plan') or {}).get('items',[]) for x in row.get('source_ids',[]))
    warnings.extend(issue('source_review_pending','新入库来源的专业适用性仍待人工核对',s['id']) for s in catalog.get('sources',[]) if s['id'] in cited and s.get('review_status')=='pending_professional_review')
    for name in STAGES[:STAGES.index(stage)+1]:
        producer=(event.get(name) or {}).get('producer') or {}
        if producer and name!='word' and producer.get('skill_bundle_sha256')!=stage_skills.get(seeds.root,name)['bundle_sha256']:
            errors.append(issue('method_changed','节点方法版本已变化：'+name))
    if require_result and not result and stage!='word':errors.append(issue('candidate_missing','本节点尚未载入候选'))
    if result and stage in ('assessment','plan') and result.get('contract_version')!=contract.CONTRACT_VERSION:
        errors.append(issue('contract_version_missing','历史候选须按当前 v2.1 合同重新提交，不能复用旧 Gate'))
        result=None
    if stage=='assessment' and result:
        extra, notes, pending=assessment_stage(dated,event,catalog,result,review,seeds)
        errors+=extra;warnings+=notes;review_items+=pending
    elif stage=='plan' and result:
        extra, notes=plan_stage(dated,event,catalog,result);errors+=extra;warnings+=notes
    elif stage=='template' and result:
        errors+=template_stage(event,catalog,result,seeds)
    elif stage=='draft' and event.get('output_mode')=='text':
        errors+=text_draft_stage(event,result,require_result)
        warnings.append(issue('text_review_boundary','只核验当前公司正文及内容映射，不证明外部报告已出具、逐页排版或正式披露完成'))
    elif stage=='draft':
        errors+=draft_stage(event,catalog,result,require_result)
    elif stage=='word':
        draft_report=evaluate(event,seeds,'draft',catalog=catalog)
        extra, notes=word_stage(event,seeds,catalog,artifact_directory,draft_report,lambda:fingerprint(event,catalog,'draft'))
        errors+=extra;warnings+=notes
    if stage in ('template','draft','word') and event.get('output_mode')!='text':
        errors+=layout_issues(event,catalog)
    errors=list({json.dumps(i,sort_keys=True,ensure_ascii=False):i for i in errors}.values())
    warnings=list({json.dumps(i,sort_keys=True,ensure_ascii=False):i for i in warnings}.values())
    review_items=list({i['item_id']:i for i in review_items}.values())
    codes={i['code'] for i in errors};fp=fingerprint(event,catalog,stage)
    if codes & {'law_missing','law_text_missing'}:action='search_official_web'
    elif any(code.startswith('law_') for code in codes):action='review_law_library'
    elif errors:action='notify_user_stop'
    elif review_items:action='semantic_review'
    elif any(w['code']=='manual_escalation' for w in warnings):action='manual_escalation'
    else:action='human_review' if requires_human(event,stage) else 'advance'
    search=event.get('source_search') or {}
    if search.get('input_fingerprint')==fp and search.get('status')=='not_found':action='notify_user_stop'
    queries=[(i.get('source_id') or event['kind'])+' 适用版本 官方原文' for i in errors if i['code'].startswith('law_')]
    history_receipt=None
    if stage in ('draft','word'):
        from .announcement_history import field_check_receipt
        history_receipt=field_check_receipt(event,catalog.get('client_history',{}))
    return {'status':'BLOCKED' if errors else 'PENDING_REVIEW' if review_items else 'PASS','stage':stage,'input_fingerprint':fp,
        'history_check':history_receipt,
        'checked_at':datetime.now(timezone.utc).isoformat(),'issues':errors,'warnings':warnings,'semantic_review':review_items,
        'checks':[{'check_id':i['code'],'result':'fail','severity':'blocker','message':i['detail']} for i in errors]
            +[{'check_id':i['code'],'result':'unknown','severity':'semantic_review','message':i['detail']} for i in review_items]
            +[{'check_id':w['code'],'result':'unknown','severity':'manual_review','message':w['detail']} for w in warnings]
            +[{'check_id':'deterministic_contract','result':'fail' if errors else 'pass','severity':'blocker','message':'本报告仅覆盖实际执行的范围、版本、引用及相应节点检查'}],
        'manual_review_items':['规则适用与例外、程序、时点、事实语义、覆盖边界'] + (['当前 Word 的逐页视觉与内容'] if stage=='word' else []),
        'review_readiness':'blocked' if errors else 'pending_review' if review_items else 'ready',
        'drafting_readiness':contract.drafting_readiness(event) if stage!='assessment' else None,
        'next_action':{'action':action,'executor':'external_agent' if action=='search_official_web' else 'local_workbench',
            'queries':list(dict.fromkeys(queries)),'board':seeds.board,
            'official_domains':['gov.cn','csrc.gov.cn','szse.cn' if seeds.board=='chinext' else 'neeq.com.cn'],
            'instruction':('对标记为 semantic_review 的事实逐项做独立语义复核，返回逐项结论、原文定位和理由。' if review_items
                           else '使用当前任务绑定的工具；缺失接口不得编造结果。法源不足时记录真实检索及覆盖限制。')},
        'boundary':'PASS 仅为已执行确定性检查通过；未知项和人工复核单列。本机确认不替代法定审批或公开披露。'}

def require(event,seeds,stage,*,require_result=True,artifact_directory=None):
    result=evaluate(event,seeds,stage,require_result=require_result,artifact_directory=artifact_directory)
    if result['status']!='PASS':raise HTTPException(409,{'message':'Gate 已阻断后续步骤','gate':result})
    return result

def advance(event,seeds,stage,*,artifact_directory=None):
    receipt=require(event,seeds,stage,artifact_directory=artifact_directory)
    event.setdefault('verified_stages',{})[stage]=receipt
    if approval_valid(event,seeds.for_event(event).catalog(),stage):return receipt
    if event.get(stage):
        event[stage]['approved']=False
        event[stage]['verified']=True
    if enabled(event):
        event.setdefault('automation_records',[]).append({'stage':stage,'input_fingerprint':receipt['input_fingerprint'],'checked_at':receipt['checked_at'],'status':'verified_work_draft','human_approved':False})
        event['stage']='awaiting_'+stage+'_confirmation' if requires_human(event,stage) else {'assessment':'planning','plan':'drafting' if event.get('output_mode')=='text' else 'selecting_template','template':'drafting'}[stage]
    else:event['stage']='awaiting_'+stage+'_confirmation' if stage in HUMAN_STAGES else ('text_draft_ready' if event.get('output_mode')=='text' else 'draft_verified')
    if receipt['next_action']['action']=='manual_escalation':event['stage']='manual_escalation'
    return receipt
