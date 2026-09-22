"""Leaf context and preflight projections for document workflows."""
import json
import time
from . import document_store as store
from .domain import Seeds
from .intent_control import bound


def seeds_for(runtime, run):
    scope = {'layer': run['board'], 'stock_code': run.get('company_code', '')}
    return Seeds(runtime.root).for_event(scope)


def with_announcement_method(runtime, run, value):
    """Use the same drafting guidance for announcement text, Word and revisions."""
    target=next((d for d in value['documents'] if d['document_id']==run.get('target_document_id')),None)
    planned=(run.get('document_preflight') or {}).get('documents',[])
    announcement=(run['stage']=='announcement' or run.get('document_kind') in ('announcement','mixed') or
                  (not run.get('document_kind') and ((target and target['kind']=='announcement') or
                   any(d['kind']=='announcement' for d in planned))))
    if announcement and run.get('document_action')!='render':
        value={**value,'method':runtime.load_method(run,'announcement')}
    return value


def context(runtime, run):
    from .agent_tasks import model_event
    event = runtime.event(run['event_id']) if bound(run['event_id']) else None
    sources = []
    for prior in reversed(runtime.store.runs(run['session_id'])[:30]):
        for row in runtime.store.journal(prior['id']):
            if row['kind'] == 'user' and row['body'].get('text'):
                sources.append({'id': 'user:' + str(row['seq']), 'text': row['body']['text'], 'status': '用户陈述'})
    if event:
        sources += [{'id': 'event:summary', 'text': event['summary'], 'status': '事项登记，后续用户修订优先'},
                    {'id': 'event:facts', 'text': json.dumps(event['facts'], ensure_ascii=False), 'status': '事项登记'}]
    documents = store.listing(runtime, run['session_id'])
    templates = seeds_for(runtime, run).templates()
    consultations=[r for r in runtime.store.runs(run['session_id']) if r['id']!=run['id'] and r['stage']=='chat' and r['status']=='completed']
    latest_consult=None
    if consultations:
        prior=consultations[0]
        answers=[r['body']['text'] for r in runtime.store.journal(prior['id']) if r['kind']=='assistant' and r['body'].get('text') and r['body'].get('stopReason')=='stop']
        if answers:latest_consult={'run_id':prior['id'],'text':answers[-1],'status':'咨询分析候选，须核对最新事实和规则'}
    from .conversation_attachments import manifest
    value = {'stage': run['stage'], 'scope': runtime.company_scope(run),'attachments':manifest(runtime,run),
             'event': model_event(event) if event else None,
             'event_revision': event['revision'] if event else None,
             'document_revision': documents['revision'],
             'documents': [{k: row.get(k) for k in ('document_id', 'version', 'title', 'kind', 'format','template_id', 'source_type', 'sha256', 'pending', 'review_status', 'available')} for row in documents['items']],
             'document_action':run.get('document_action','create'),'reply_source':run.get('reply_source'),
             'document_kind':run.get('document_kind'),'latest_consultation':latest_consult,
             'sources': sources,
             'templates': [{'id': 'builtin:analysis', 'name': '分析材料通用版式', 'kind': 'analysis'}] +
                          [{k: row.get(k) for k in ('id', 'name', 'kind', 'scope_review_status', 'authority')} for row in templates],
             'current_date': time.strftime('%Y-%m-%d')}
    # The assessment/consent projection is not itself an input fact. Excluding
    # it prevents reading the context from invalidating its own authorization.
    fingerprint=store.digest({k:v for k,v in value.items() if k!='stage'})
    value['document_preflight']=run.get('document_preflight') or previous(runtime,run)
    value['production_allowed']=allowed({**run,'document_context_sha256':fingerprint})
    from .completion_receipts import document_capability
    value['production_capability']=document_capability({**run,'document_context_sha256':fingerprint})
    if run.get('document_action')=='render':
        # This reflects the existing bound-reply route; render() still verifies
        # the source belongs to this session and has the registered content hash.
        value['production_allowed']=value['production_capability']['production_allowed']
    if event and event.get('plan'):
        value['planning_baseline']={k:event['plan'].get(k) for k in ('requirements','drafting_gaps','documents')}
    runtime.store.update(run['id'], document_context=value, document_context_sha256=fingerprint)
    return value


def previous(runtime, run):
    # An unrelated intervening turn does not carry an implicit yes across tasks.
    prior = next((r for r in runtime.store.runs(run['session_id']) if r['id'] != run['id']), None)
    if not prior or prior.get('status') not in ('waiting_user', 'completed', 'incomplete', 'failed', 'interrupted'):
        return None
    value = prior.get('document_preflight')
    if not value or value.get('company_code') != run.get('company_code', '') or value.get('board') != run['board']:
        return None
    return value


def allowed(run):
    value = run.get('document_preflight') or {}
    return value.get('status') in ('ready','authorized') and value.get('input_fingerprint') == run.get('document_context_sha256')
