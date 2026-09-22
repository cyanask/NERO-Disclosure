from internal_workflow import context as read_context
"""Caller-visible full analysis, source-size and bounded repair regressions."""
import copy
import json
from uuid import uuid4
from internal_workflow import invoke
import pytest
from test_agent_tasks import env, claimed, candidate, post, latest
from test_open_intake import real_event, source_plan
from test_pi_runtime import client, new_session, send, settled


def evaluate(c,e,task,lease,token,value):
    return post(c,e,f"agent-tasks/{task['id']}/evaluate",token,claim_id=lease['claim_id'],
                input_fingerprint=lease['input_fingerprint'],result=value)


def test_full_conditional_analysis_survives_unknown_a_without_promoting_b(env):
    c,tokens,_,_=env;e=real_event(c);task,lease=claimed(c,e,tokens[0]);v=candidate()
    v.update(status='needs_info',missing=['减持方式待确认'])
    v['facts'][0].update(status='unknown',value=None)
    v['matters'][0].update(duty_status='undetermined',timing_status='unknown',decisive_questions=['减持方式待确认'],reassessment_conditions=['方式确定后复判'])
    v['matters'][0]['reasoning_items'][0]['outcome']='unknown'
    v['preliminary_plan']=source_plan()
    for d in v['preliminary_plan']['documents']:d['stage']='preliminary'
    v['preliminary_plan']['blocking_questions']=['实际数量待补']
    r=evaluate(c,e,task,lease,tokens[0],v);assert r.status_code==200,r.text
    assert r.json()['outcome']=='waiting_user'
    saved=latest(c,e);assert saved['stage']=='awaiting_assessment_information'
    assert len(saved['assessment']['preliminary_plan']['documents'])==2
    assert saved['plan'] is None and not saved.get('approval_records')
    assert post(c,e,'agent-tasks',stage='plan').status_code==409


def test_missing_metadata_bound_but_wrong_explicit_values_not_overwritten(env):
    c,tokens,_,_=env;e=real_event(c);task,lease=claimed(c,e,tokens[0]);v=candidate()
    del v['assessment_as_of'];del v['source_ids'];del v['facts'][0]['observed_at'];del v['facts'][0]['source_ref']
    del v['matters'][0]['reasoning_items'][0]['locator']
    r=evaluate(c,e,task,lease,tokens[0],v);assert r.status_code==200,r.text
    assert r.json()['outcome']=='waiting_approval'
    saved=latest(c,e);f=saved['assessment']['facts'][0]
    assert f['source_ref']=='facts.requires_shareholder_approval'
    assert len(saved['agent_tasks'][0]['field_bindings'])==5
    assert not saved.get('approval_records')


def test_same_task_repair_retains_candidate_and_stops_at_human_gate(env):
    c,tokens,_,_=env;e=real_event(c);task,lease=claimed(c,e,tokens[0]);bad=candidate()
    bad['matters'][0]['reasoning_items'][0]['quote']='不存在的法条原句'
    r=evaluate(c,e,task,lease,tokens[0],bad);assert r.status_code==200,r.text
    assert r.json()['outcome']=='revise'
    assert evaluate(c,e,task,lease,tokens[1],candidate()).status_code==403
    good=evaluate(c,e,task,lease,tokens[0],candidate());assert good.json()['outcome']=='waiting_approval',good.text
    saved=latest(c,e);assert len(saved['agent_tasks'])==1
    history=saved['agent_tasks'][0]['candidate_history'];assert len(history)==2
    assert history[0]['result']['matters'][0]['reasoning_items'][0]['quote']=='不存在的法条原句'
    assert saved['stage']=='awaiting_assessment_confirmation'
    assert not saved.get('approval_records')


def test_repeated_repairs_keep_the_gate_and_stale_input_stays_rejected(env):
    """同一无效候选可反复退回修订，没有数值上限或人工升级节点；输入变化仍拒绝旧候选。"""
    c,tokens,_,_=env;e=real_event(c);task,lease=claimed(c,e,tokens[0]);v=candidate()
    v['assessment_as_of']='2000-01-01'
    for _ in range(3):
        r=evaluate(c,e,task,lease,tokens[0],v);assert r.status_code==200,r.text
        assert r.json()['outcome']=='revise',r.text
    saved=latest(c,e)
    assert saved['stage']!='manual_escalation' and not saved.get('escalation')
    assert post(c,e,'agent-tasks',stage='assessment').status_code==409
    other=real_event(c);t,l=claimed(c,other,tokens[0]);current=latest(c,other)
    assert c.patch('/api/events/'+other['id'],json={'expected_revision':current['revision'],'summary':'事实变化'}).status_code==200
    assert evaluate(c,other,t,l,tokens[0],candidate()).status_code==409


def test_snapshot_arithmetic_uses_known_inputs_not_a_fictitious_legal_basis(env):
    c,tokens,_,_=env;e=real_event(c);e=c.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':{**e['facts'],'initial':1559259,'addition':467777}}).json()
    t,l=claimed(c,e,tokens[0]);v=candidate()
    v['facts'] += [{'key':k,'value':v,'status':'user_statement'} for k,v in [('initial',1559259),('addition',467777)]]
    v['matters'][0]['calculations']=[{'operation':'sum','fact_keys':['initial','addition'],'scope':'snapshot','unit':'股','period':'报告期末','aggregation_basis':'public_announcements'}]
    r=evaluate(c,e,t,l,tokens[0],v);assert r.json()['outcome']=='waiting_approval',r.text
    calc=latest(c,e)['assessment']['matters'][0]['calculations'][0]
    assert calc['result']=='2027036' and calc['basis_source_id']=='facts'


def test_article_read_is_small_but_explicit_document_and_page_still_available(env):
    c,_,root,_=env;p=root/'data/public/boards/chinext/catalog.json';cat=json.loads(p.read_text())
    row=next(r for r in cat['sources'] if r['id']=='szse-chinext-2026-4.1.7')
    # A deterministic multi-page original fixture independent of production PDF size.
    doc=root/'data/public/documents/slim-read.json';doc.parent.mkdir(parents=True,exist_ok=True)
    doc.write_text(json.dumps({'pages':[{'page':n,'text':'无关正文'*1000} for n in range(1,160)]}))
    import hashlib
    row.update(document_path=str(doc.relative_to(root)),document_sha256=hashlib.sha256(doc.read_bytes()).hexdigest());p.write_text(json.dumps(cat))
    url='/api/library/items/'+row['id'];small=c.get(url,params={'board':'chinext'}).json();full=c.get(url,params={'board':'chinext','view':'document'}).json()
    assert small['text']==row['text'] and small['pages']==[]
    assert small['text_completeness']=='registered_article_text'
    assert len(json.dumps(small)) < len(json.dumps(full))/20
    assert len(full['pages'])==159
    one=c.get(url,params={'board':'chinext','page':20}).json();assert len(one['pages'])==1 and one['pages'][0]['page']==20
    assert c.get(url,params={'board':'chinext','view':'guess'}).status_code==422


def test_pi_uses_shared_evaluator_and_repairs_in_one_run(client):
    c,runtime,_=client;s,e=new_session(c)
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'});bad=candidate();bad['matters'][0]['reasoning_items'][0]['quote']='不存在的原句'
        r=bridge('submit_candidate',{'result':bad});assert r['terminate'] is False and r['data']['outcome']=='revise'
        r=bridge('submit_candidate',{'result':candidate()});assert r['terminate'] is True
        emit({'type':'done'})
    runtime.runner=runner;r,_=send(c,s,e,'assessment');out=settled(c,r)
    assert out['run']['status']=='waiting_approval',out['run']
    names=[x['body']['name'] for x in out['events'] if x['kind']=='tool_requested']
    assert names.count('task.evaluate')==2 and 'task.adopt' not in names and 'gate.advance' not in names
    assert len(latest(c,e)['agent_tasks'])==1


def test_evaluation_schema_failure_and_idempotent_replay_keep_truth(env):
    c,tokens,_,_=env;e=real_event(c);task,lease=claimed(c,e,tokens[0])
    current=latest(c,e);body={'expected_revision':current['revision'],'request_id':str(uuid4()),'claim_id':lease['claim_id'],'input_fingerprint':lease['input_fingerprint'],'result':{'approved':True}}
    url=f"/api/events/{e['id']}/agent-tasks/{task['id']}/evaluate"
    assert c.post(url,json=body).status_code==404
    first=invoke(c,tokens[0],'task.evaluate',{'event_id':e['id'],'task_id':task['id'],**body});replay=invoke(c,tokens[0],'task.evaluate',{'event_id':e['id'],'task_id':task['id'],**body})
    assert first.status_code==200 and first.json()==replay.json()
    saved=latest(c,e);history=saved['agent_tasks'][0]['candidate_history']
    assert len(history)==1 and history[0]['result'] is None
    assert len(first.json()['gate']['input_fingerprint'])==64
    assert saved['assessment'] is None and not saved.get('approval_records')


def test_scoped_search_gives_exact_snippet_and_prioritizes_date_coverage(monkeypatch,tmp_path):
    from backend.library import search
    monkeypatch.setattr('backend.library.profiles',lambda seeds:[])
    class Sources:
        root=tmp_path
        board='chinext'
        def catalog(self):
            return {'sources':[{'id':'stale','title':'规则','text':'有关战略配售和减持的旧核验记录','effective_from':'2025-01-01','as_of':None},
                               {'id':'current','title':'规则','text':'有关战略配售和减持的当前条文','effective_from':'2025-01-01','as_of':'2026-09-12','original_path':'official.pdf'}]}
    result=search(Sources(),'laws','战略配售',as_of='2026-09-12')
    assert [r['id'] for r in result['items']]==['current','stale']
    assert result['items'][0]['text_preview']=='有关战略配售和减持的当前条文'
    assert result['total']==2  # Older entries remain visible, not silently removed.


def test_retry_context_keeps_issue_summary_without_replaying_full_candidate(env):
    c,tokens,_,_=env;e=real_event(c);t,l=claimed(c,e,tokens[0]);bad=candidate()
    bad['matters'][0]['reasoning_items'][0]['quote']='需要修订的原句'
    assert evaluate(c,e,t,l,tokens[0],bad).json()['outcome']=='revise'
    assert post(c,e,f"agent-tasks/{t['id']}/finish",tokens[0],claim_id=l['claim_id'],status='failed',reason='模型运行中断').status_code==200
    t2,l2=claimed(c,e,tokens[0]);ctx=read_context(c,e,t2,tokens[0]).json()
    assert 'candidate' not in ctx['repair_context']
    assert ctx['repair_context']['summary']==bad['summary']
    assert 'citation_unlocatable' in {row['code'] for row in ctx['repair_context']['issues']}
    assert ctx['repair_context']['status']=='unadopted_candidate_same_bound_input'
    now=latest(c,e);c.patch('/api/events/'+e['id'],json={'expected_revision':now['revision'],'summary':'新的事实'})
    t3,l3=claimed(c,e,tokens[0]);changed=read_context(c,e,t3,tokens[0]).json()
    assert changed['repair_context'] is None


def test_preliminary_analysis_cannot_invent_template_field_bindings(env):
    c,tokens,_,_=env;e=real_event(c);t,l=claimed(c,e,tokens[0]);v=candidate();v['preliminary_plan']=source_plan()
    for d in v['preliminary_plan']['documents']:d['stage']='preliminary'
    v['preliminary_plan']['requirements'][0]['format_field_refs']=['fabricated-section:42']
    result=evaluate(c,e,t,l,tokens[0],v)
    assert result.status_code==200 and result.json()['outcome']=='revise'
    assert 'format_field_invalid' in {i['code'] for i in result.json()['gate']['issues']}
    assert latest(c,e)['assessment'] is None


def test_preliminary_external_dependencies_are_review_items_not_intake_blocks(env):
    from backend.disclosure_contract import plan_checks
    from backend.domain import Seeds
    c,tokens,root,_=env;e=real_event(c);t,l=claimed(c,e,tokens[0]);v=candidate();v['preliminary_plan']=source_plan()
    for d in v['preliminary_plan']['documents']:d['stage']='preliminary'
    v['preliminary_plan']['documents'].append({'document_id':'outside','title':'第三方核查文件','purpose':'filing','necessity':'conditional','applicability':'实际办理相关程序时','stage':'preliminary','producer':'独立第三方','production':'external_dependency','timing':'正式制作前核实','source_ids':['szse-chinext-2026-4.1.7']})
    r=evaluate(c,e,t,l,tokens[0],v);assert r.json()['outcome']=='waiting_approval',r.text
    saved=latest(c,e);plan=saved['assessment']['preliminary_plan']
    errors,_=plan_checks(saved,Seeds(root,'chinext').catalog(),plan)
    assert 'external_dependency_missing' in {i['code'] for i in errors}


def test_model_event_read_keeps_business_facts_without_replaying_history(client):
    c,runtime,_=client;s,e=new_session(c)
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'});value=bridge('read_event',{})['data']
        assert value['id']==e['id'] and value['facts']==e['facts']
        assert 'audit' not in value and 'agent_tasks' not in value
        emit({'type':'assistant','message':0,'text':'已按当前事项事实回答。','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=runner;r,_=send(c,s,e);out=settled(c,r)
    assert out['run']['status']=='completed'
    assert any(row['kind']=='model_projection' for row in out['events'])
