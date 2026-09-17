"""Candidate contract checks and projections over one stored candidate.

The task lifecycle module owns leases, state transitions and adoption. This module
owns what can be decided from a frozen task snapshot alone: whether a candidate
satisfies the stage contract, which registered sources it cites, and the response
shapes built from a stored candidate.
"""
import copy
import json
from fastapi import HTTPException
from pydantic import ValidationError
from . import library
from .agent_models import AssessmentCandidate, PlanCandidate, DraftCandidate, TextDraftCandidate, TemplateCandidate

MAX_CANDIDATE_BYTES = 250000


def validate(task, result):
    """Stage contract check: model schema, size and citations against the frozen snapshot."""
    model = {'assessment':AssessmentCandidate,'plan':PlanCandidate,'template':TemplateCandidate,
             'draft':TextDraftCandidate if task['snapshot']['event'].get('output_mode')=='text' else DraftCandidate}[task['stage']]
    try:
        value = model.model_validate(result).model_dump(mode='json')
    except ValidationError as exc:
        fields='；'.join('.'.join(str(k) for k in error['loc'])+': '+error['type']
                        for error in exc.errors(include_input=False)[:10])
        raise HTTPException(422, '候选字段不符合当前阶段合同：'+fields)
    if len(json.dumps(value, ensure_ascii=False)) > MAX_CANDIDATE_BYTES:
        raise HTTPException(422, '候选内容过大')
    snap = task['snapshot']; source_ids = {s['id'] for s in snap['catalog']['sources']}
    if task['stage']=='plan':
        source_ids.update(c['id'] for c in snap['catalog'].get('cases',[]) if library.admitted_case(c, snap['event']['layer']))
    if task['stage'] == 'assessment':
        ids = value['source_ids']
    elif task['stage'] == 'plan':
        ids = [sid for item in value['items'] for sid in item['source_ids']]
        ids += [sid for group in ('documents','requirements','drafting_gaps') for row in value[group] for sid in row.get('source_ids',[])]
        incoming = [item['id'] for item in value['items']]
        if len(set(incoming)) != len(incoming):raise HTTPException(422,'清单编号不能重复')
    else:
        ids = []
        if not (task['stage']=='draft' and snap['event'].get('output_mode')=='text') and value['template_id'] not in {t['id'] for t in snap['templates']}:
            raise HTTPException(422, '候选模板不适用于该任务')
    if not set(ids) <= source_ids:
        missing=sorted(set(ids)-source_ids)
        profiles={p['id']:p for p in snap['catalog'].get('profiles',[])}
        hints=['格式编号 '+sid+' 的规范来源为 '+','.join(profiles[sid].get('normative_source_ids',[])) for sid in missing if sid in profiles]
        raise HTTPException(422, '候选引用不存在于任务绑定的法源包：'+','.join(missing[:10])+('；'+'；'.join(hints) if hints else ''))
    return value


def candidate_ids(candidate, deep=False):
    """Registered source ids the candidate cites.

    deep=False covers the top level and plan items, which is what event views show.
    deep=True also walks nested payloads, which is what an evaluation receipt lists.
    """
    ids=set()
    if not deep:
        ids.update(candidate.get('source_ids',[]))
        ids.update(sid for item in candidate.get('items',[]) for sid in item.get('source_ids',[]))
        return ids
    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'source_ids' and isinstance(child, list):
                    ids.update(x for x in child if isinstance(x, str))
                elif key == 'source_id' and isinstance(child, str):
                    ids.add(child)
                else: collect(child)
        elif isinstance(value, list):
            for child in value: collect(child)
    collect(candidate)
    return ids


def source_view(catalog, ids):
    """The registered sources and cases a candidate cites, in catalog order."""
    return [copy.deepcopy(s) for key in ('sources','cases') for s in (catalog or {}).get(key,[]) if s['id'] in ids]


def response(event, task):
    """Evaluation receipt for one task: the candidate, its citations and its verdict."""
    result = (task.get('candidate_history') or [{}])[-1].get('result')
    # Preserve the submitted candidate in audit history, but display the facts
    # actually admitted by verification (ordinary gaps may have become unknown).
    admitted = event.get('assessment') or {}
    if task['stage'] == 'assessment' and task.get('status') == 'adopted' and admitted.get('producer', {}).get('task_id') == task['id']:
        result = {**(result or {}), 'facts':copy.deepcopy(admitted.get('facts', [])),
                  'missing':copy.deepcopy(admitted.get('missing', []))}
    source_ids = candidate_ids(result or {}, deep=True)
    catalog = task.get('snapshot', {}).get('catalog', {})
    snapshot = {'event_id':event['id'], 'revision':event['revision'], 'stage':task['stage'],
                'task_id':task['id'], 'outcome':task['evaluation']['outcome'], 'result':copy.deepcopy(result),
                'sources':source_view(catalog, source_ids)}
    return {'event_id':event['id'], 'task_id':task['id'], 'expected_revision':event['revision'],
            **task['evaluation'], 'field_bindings':task.get('field_bindings', []),
            'semantic_review':copy.deepcopy((task['evaluation'].get('gate') or {}).get('semantic_review',[])),
            'summary':(task.get('result') or {}).get('summary', ''), 'result_snapshot':snapshot}
