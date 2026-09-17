"""Stage-level gate checks: law and timing, plan requirements, draft text, Word file.

gates.evaluate owns the gate contract (input fingerprint, upstream receipts, dedupe,
action selection and the report shape). This module owns the checks that read one
stage's frozen inputs and return issues, warnings or semantic-review items.
"""
import copy
import hashlib
import json
from datetime import date
from fastapi import HTTPException
from . import library
from .disclosure_contract import draft_checks
from . import disclosure_contract as contract
from .domain import evaluate as rule_check

LEGAL_KINDS = {'official_rule','regulation','statute'}


def issue(code, detail, source_id=None):
    return {'code':code,'detail':detail,**({'source_id':source_id} if source_id else {})}


def source_issues(event, catalog, source_ids, legal_only=False):
    errors=[];sources={s['id']:s for s in catalog['sources']}
    try: event_date=date.fromisoformat(event['facts']['event_date'])
    except (KeyError,TypeError,ValueError):return [issue('event_date_invalid','请补充有效的事项发生日期')]
    for sid in dict.fromkeys(source_ids):
        source=sources.get(sid)
        if source is None:
            errors.append(issue('law_missing','法律库缺少引用法源，须检索官方来源并收录适用版本',sid));continue
        if legal_only and source.get('source_kind') not in LEGAL_KINDS:
            errors.append(issue('not_a_law','案例或格式规则不能代替法律依据',sid))
        if not source.get('text','').strip():errors.append(issue('law_text_missing','法源正文缺失',sid))
        try:
            start=date.fromisoformat(source['effective_from'])
            end=date.fromisoformat(source['effective_to']) if source.get('effective_to') else None
            if event_date < start or (end and event_date > end):
                errors.append(issue('law_out_of_period','事项日期不在法源适用期间，请回法律库确认对应版本',sid))
        except (KeyError,TypeError,ValueError):errors.append(issue('law_dates_invalid','法源时效资料缺失或无效',sid))
        if source.get('text_sha256') and hashlib.sha256(source['text'].encode()).hexdigest()!=source['text_sha256']:
            errors.append(issue('law_integrity','法源文本哈希不符',sid))
        for path_key, hash_key in (('original_path','sha256'),('document_path','document_sha256')):
            path=source.get(path_key)
            if path and catalog.get('asset_state',{}).get(path)!=source.get(hash_key):
                errors.append(issue('law_integrity','法源原件或提取正文哈希不符',sid))
    return errors


def review_notes(event, catalog, source_ids):
    """月检到期或缺少核验记录只提示，不阻断制稿；由法规生命周期页维护。"""
    notes=[];sources={s['id']:s for s in catalog['sources']}
    try: event_date=date.fromisoformat(event['facts']['event_date'])
    except (KeyError,TypeError,ValueError):return notes
    for sid in dict.fromkeys(source_ids):
        source=sources.get(sid)
        if source is None:continue
        try:
            as_of=source.get('as_of') or catalog.get('as_of')
            if not as_of or event_date>date.fromisoformat(as_of):
                notes.append(issue('law_review_due','法源核验记录早于事项日期；请在法规生命周期页更新核验，不阻断当前制稿',sid))
        except (TypeError,ValueError):
            notes.append(issue('law_review_due','法源缺少有效核验记录；请在法规生命周期页处理',sid))
    return notes


def law_basis(event, catalog):
    rules=[r for r in catalog.get('rules',[]) if r['event_kind']==event['kind'] and event['layer'] in r.get('layers',[])]
    ids=(list((event.get('law_bindings') or {}).values()) if event.get('intake_mode')=='open' else
         [(event.get('law_bindings') or {}).get(sid,sid) for r in rules for sid in r.get('source_ids',[])])
    errors=source_issues(event,catalog,ids,legal_only=True)
    if event.get('intake_mode')!='open' and (not rules or not ids):errors.append(issue('law_missing','本事项尚无完整的适用法源绑定'))
    candidate=event.get('assessment') or {}
    cited=[s['id'] for s in candidate.get('citations',[])]
    # All cited sources must be authentic/current. Only sources used to establish
    # duties or deadlines must be law; format requirements have a distinct role.
    errors += source_issues(event,catalog,cited)
    paths={sid for matter in candidate.get('matters',[]) for sid in
           [*[p['source_id'] for p in matter.get('reasoning_items',[])],*matter.get('deadline_basis',[]),
            *[c['basis_source_id'] for c in matter.get('calculations',[]) if c.get('basis_source_id')!='facts']]}
    errors += source_issues(event,catalog,paths,legal_only=True)
    if candidate and not cited:errors.append(issue('law_missing','判断候选没有法律依据'))
    return errors, review_notes(event,catalog,[*ids,*cited,*paths])


def draft_prologue(event, seeds, catalog):
    """Hand-checked template text and sibling-announcement conflicts; draft and word both run it."""
    from .announcement_history import check as history_check
    errors=[];warnings=[]
    siblings=seeds.draft_provider(event['layer'],event.get('stock_code')) if seeds.draft_provider else []
    conflicts,notes=history_check(event,catalog.get('client_history',{}),siblings)
    errors.extend(conflicts);warnings.extend(notes)
    template=next((t for t in seeds.templates() if t['id']==(event.get('draft') or {}).get('template_id')),None)
    if template and template.get('authority')=='user_uploaded':
        from docx import Document
        from .artifact_checks import normalized
        text=(event.get('draft') or {}).get('text','')
        source=Document(seeds.root/'templates'/template['file'])
        for para in source.paragraphs:
            if para.text.strip() and '{{' not in para.text and normalized(para.text) not in normalized(text):
                errors.append(issue('template_text_not_confirmed','手工模板固定内容须纳入最终正文后再确认：'+para.text[:100]))
    return errors,warnings


def assessment_stage(dated, event, catalog, result, review, seeds):
    from .announcement_history import read as read_history
    errors=[];warnings=[];review_items=[]
    extra, notes, pending=contract.assessment_checks(event,catalog,result,
        history_reader=lambda identity:read_history(seeds.root,event['layer'],event.get('stock_code',''),identity),review=review)
    errors+=extra;warnings+=notes;review_items+=pending
    deterministic=rule_check(dated,seeds=seeds,catalog=catalog)
    if deterministic['status']=='disclose' and result.get('status') in ('no_disclosure','needs_info'):
        errors.append(issue('conclusion_conflict','现有确定性规则已识别义务，候选不能直接降为无义务或整体待判断'))
    return errors,warnings,review_items


def plan_stage(dated, event, catalog, result):
    errors=[];warnings=[]
    extra, notes=contract.plan_checks(event,catalog,result);errors+=extra;warnings+=notes
    refs={sid for group in ('documents','requirements','drafting_gaps') for row in result.get(group,[]) for sid in row.get('source_ids',[])}
    legal={s['id'] for s in catalog['sources']}
    errors+=source_issues(dated,catalog,list(refs & legal))
    for doc in result['documents']:
        profile=next((p for p in catalog.get('profiles',[]) if p['id']==doc['profile_id']),{})
        errors+=source_issues(dated,catalog,[(event.get('law_bindings') or {}).get(sid,sid) for sid in profile.get('normative_source_ids',[])])
    return errors,warnings


def template_stage(event, catalog, result, seeds):
    errors=[]
    template=next((t for t in library.applicable_templates(seeds,event) if t['id']==result['template_id']),None)
    if not template:errors.append(issue('template_invalid','模板不适用于当前规划'))
    current=catalog.get('template_asset_state',{}).get(result['template_id'],'')
    if len(current)!=64:errors.append(issue('template_integrity','模板文件缺失或不可读取'))
    requirements=contract.body_requirements(event)
    required={r['requirement_id'] for r in requirements}
    mapping=result.get('requirement_map',{})
    if set(mapping)!=required:errors.append(issue('template_requirement_missing','模板未逐项承载已认可的内容要求'))
    sections={s['id'] for s in (template or {}).get('sections',[])}
    if any(v not in sections for v in mapping.values()):errors.append(issue('template_section_missing','映射章节不在真实模板结构中，请适配或换模板'))
    return errors


def draft_stage(event, catalog, result, require_result):
    errors=[]
    ready=contract.drafting_readiness(event)
    if ready['status']!='ready' and not (continuous_enabled(event) and not require_result):errors += [issue('drafting_not_ready',b) for b in ready['blockers']]
    if result:
        if result['template_id']!=(event.get('template') or {}).get('template_id'):
            errors.append(issue('template_not_confirmed','正文必须使用当前已确认模板'))
        required={r['requirement_id'] for r in contract.body_requirements(event)}
        mapping=result.get('requirement_map',{})
        if set(mapping)!=required or any(not contract.mapped_in_text(excerpt,result['text']) for excerpt in mapping.values()):
            errors.append(issue('draft_mapping_missing','正文要求映射不完整或无法定位'))
        current=catalog.get('template_asset_state',{}).get(result.get('template_id'),'')
        if len(current)!=64 or result.get('template_sha256',current)!=current:errors.append(issue('template_integrity','Word 模板缺失或当前文件版本不符'))
        for check in draft_checks(result['text'],event.get('plan') or {'items':[]}):
            if check['status']=='fail':errors.append(issue('draft_incomplete',check['detail']))
    return errors


def text_draft_stage(event, result, require_result):
    errors=[]
    ready=contract.drafting_readiness(event)
    if ready['status']!='ready' and not (continuous_enabled(event) and not require_result):errors += [issue('drafting_not_ready',b) for b in ready['blockers']]
    if result:errors+=contract.text_draft_checks(event,result)
    return errors


def continuous_enabled(event):
    from .continuous_policy import enabled
    return enabled(event)


def word_stage(event, seeds, catalog, artifact_directory, draft_report, draft_fingerprint):
    errors=[];warnings=[]
    errors+=draft_report['issues']
    artifact=next((a for a in event.get('artifacts',[]) if a['id']==event.get('current_artifact_id')),None)
    if not artifact or artifact.get('verification',{}).get('status')!='PASS':
        errors.append(issue('word_missing','当前版本尚无通过实际文件检查的 Word'))
    elif artifact.get('input_fingerprint')!=draft_fingerprint():
        errors.append(issue('word_stale','Word 对应的正文或上游版本已变化'))
    elif artifact_directory is None:
        errors.append(issue('word_file_not_checked','尚未检查当前实际 Word 文件'))
    else:
        from . import artifact_checks as artifacts, word_delivery
        try:
            actual=artifacts.path(artifact_directory,artifact).read_bytes()
            layout=word_delivery.layout(seeds,event)
            if not layout:raise HTTPException(409,'文种尚未绑定版式规则')
            original=artifacts.template_bytes(seeds,event) if layout and layout.get('template_authority')=='user_uploaded' else None
            file_report=artifacts.check(actual,event,layout,original)
            errors += [issue('word_file_invalid',message) for message in file_report['errors']]
        except (HTTPException,word_delivery.WordDeliveryError):
            errors.append(issue('word_file_invalid','当前 Word 缺失、哈希不符或结构无效'))
    warnings.append(issue('word_manual_review','分页视觉、语义及法律适用仍须人工审阅当前文件；host_qa 为自报'))
    return errors,warnings


def layout_issues(event, catalog):
    """Imported layout profiles need a professional applicability review before production."""
    errors=[]
    template_id=(event.get('template') or event.get('draft') or {}).get('template_id')
    layout_id=next((t.get('layout_profile_id') for t in catalog.get('templates',[]) if t['id']==template_id),None)
    for layout in catalog.get('layout_profiles',[]):
        if layout['id']!=layout_id:continue
        if layout.get('scope_review_status')=='layout_scope_review_required':errors.append(issue('layout_scope_review_required','导入版式适用性尚未复核'))
        path=layout.get('source_observations_path')
        if path and catalog.get('asset_state',{}).get(path)!=layout.get('source_observations_sha256'):errors.append(issue('layout_integrity','版式依据缺失或哈希不符'))
    return errors
