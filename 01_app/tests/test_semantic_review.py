"""独立语义复核：待复核不等于失败，复核意见绑定候选，未复核不得静默通过。"""
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import disclosure_contract as contract
from backend import gates
from backend.app import create_app
from conftest import KNOWLEDGE, isolated_root
from backend.domain import Seeds

ROOT=Path(__file__).resolve().parents[1]
SUMMARY='模拟事项说明：本次金额为 100.00 元，需要判断披露义务。'
QUOTE='本次金额为 100.00 元'
VALUE='折算后为 90.00 元'
RELATED='szse-chinext-2026-8.7.2'
CONFIG={'models':[{'key':'fixture-a','label':'离线模型 A','provider':'fixture','api':'openai-completions',
 'id':'offline-a','baseUrl':'http://127.0.0.1:1','api_key_env':'DISCLOSURE_TEST_KEY','enabled':True,
 'contextWindow':200000,'maxTokens':1024}]}


def history_catalog(text='公告原文：本次金额为 100.00 元（含税）。'):
    return {'sources':[],'cases':[],'client_history':{'items':[{'id':'announcement-300001-test',
            'sha256':hashlib.sha256(text.encode()).hexdigest()}],'coverage':{'complete':False}}}


def history_reader(text='公告原文：本次金额为 100.00 元（含税）。'):
    def read(identity):return {'sha256':hashlib.sha256(text.encode()).hexdigest(),'pages':[{'page':1,'text':text}]}
    return read


def fact(**over):
    row={'key':'amount','value':VALUE,'status':'user_statement','source_ref':'summary','quote':QUOTE,
         'observed_at':'2026-09-15'}
    row.update(over);return row


def result_with(facts):
    return result_with_matter(facts,default_matter())


def default_matter():
    return {'matter_id':'m1','event_types':['模拟'],'subject':'模拟事项','stage':'模拟阶段',
            'duty_status':'mandatory','timing_status':'not_triggered','trigger_events':[],
            'deadline_basis':[],'reasoning_items':[],'calculations':[],'procedural_requirements':[],
            'historical_links':[],'comparable_cases':[],'history_status':'not_connected',
            'special_review':'none','decisive_questions':[],'downstream_gaps':[],'limitations':[],
            'reassessment_conditions':[],'urgency':'normal','specialist_required':False}


def established_matter(text,article):
    return {'matter_id':'m1','event_types':['模拟'],'subject':'模拟事项','stage':'模拟阶段',
            'duty_status':'mandatory','timing_status':'triggered','trigger_events':['模拟触发'],'deadline_basis':[RELATED],
            'reasoning_items':[{'source_id':RELATED,'locator':article,'quote':text,'condition':'模拟条件',
                                'fact_keys':['scope.company_name'],'application':'模拟应用','outcome':'established'}],
            'calculations':[],'procedural_requirements':[],'historical_links':[],'comparable_cases':[],
            'history_status':'not_connected','special_review':'none','decisive_questions':[],'downstream_gaps':[],
            'limitations':[],'reassessment_conditions':[],'urgency':'normal','specialist_required':False}


def result_with_matter(facts,matter):
    return {'status':'disclose','summary':SUMMARY,'reasons':['模拟理由'],'missing':[],'source_ids':[],
            'limitations':['模拟'],'assessment_as_of':'2026-09-15','facts':facts,'matters':[matter]}


def event(**over):
    row={'company_name':'复核测试公司','summary':SUMMARY,'layer':'chinext','facts':{'event_date':'2026-09-15'}}
    row.update(over);return row


def test_value_rewrite_becomes_pending_review_not_a_failure():
    errors,warnings,pending=contract.assessment_checks(event(),history_catalog(),result_with([fact()]))
    codes={row['code'] for row in errors}
    assert 'fact_source_mismatch' not in codes and 'fact_value_conflict' not in codes
    assert [row['item_id'] for row in pending]==['fact:amount']
    assert pending[0]['quote']==QUOTE and pending[0]['value']==VALUE


def test_supported_verdict_resolves_and_conflict_blocks():
    supported={'fact:amount':{'item_id':'fact:amount','verdict':'supported','reason':'仅括注位置不同'}}
    errors,_,pending=contract.assessment_checks(event(),history_catalog(),result_with([fact()]),review=supported)
    assert pending==[] and not any(row['code'].startswith(('fact_value','semantic_review','fact_source')) for row in errors)
    conflict={'fact:amount':{'item_id':'fact:amount','verdict':'conflict','reason':'金额与原文不一致'}}
    errors,_,pending=contract.assessment_checks(event(),history_catalog(),result_with([fact()]),review=conflict)
    hits=[row for row in errors if row['code']=='fact_value_conflict']
    assert pending==[] and hits and '不一致' in hits[0]['reason']


def test_insufficient_and_uncovered_reviews_can_never_pass_silently():
    insufficient={'fact:amount':{'item_id':'fact:amount','verdict':'insufficient','reason':'原文不足以判断'}}
    errors,_,pending=contract.assessment_checks(event(),history_catalog(),result_with([fact()]),review=insufficient)
    assert any(row['code']=='semantic_review_insufficient' for row in errors) and pending==[]
    errors,_,pending=contract.assessment_checks(event(),history_catalog(),result_with([fact()]),review={})
    assert any(row['code']=='semantic_review_incomplete' for row in errors) and pending==[]


def test_unlocatable_quote_still_fails_closed():
    errors,_,pending=contract.assessment_checks(event(),history_catalog(),result_with([fact(quote='原文中不存在的句子')]))
    assert any(row['code']=='fact_source_mismatch' for row in errors) and pending==[]
    text='公告原文：本次金额为 100.00 元（含税）。'
    errors,_,pending=contract.assessment_checks(event(),history_catalog(text),
        result_with([fact(status='material_supported',source_ref='announcement-300001-test',quote='原文中不存在的句子')]),
        history_reader=history_reader(text))
    assert any(row['code']=='history_fact_unlocatable' for row in errors) and pending==[]


def test_history_rewrite_is_reviewed_with_bounded_original_context():
    text='公告原文：本次金额为 100.00 元（含税）。'
    errors,_,pending=contract.assessment_checks(event(),history_catalog(text),
        result_with([fact(status='material_supported',source_ref='announcement-300001-test',value='本次金额为90元')]),
        history_reader=history_reader(text))
    assert not any(row['code']=='history_fact_unlocatable' for row in errors)
    assert pending and pending[0]['evidence_sha']==hashlib.sha256(text.encode()).hexdigest()
    assert '含税' in pending[0]['context']


def test_gate_marks_pending_review_without_prejudging():
    catalog=Seeds(KNOWLEDGE).for_board('chinext').catalog()
    row=next(r for r in catalog['sources'] if r['id']==RELATED)
    facts=[{'key':'scope.company_name','value':'复核测试公司','status':'user_statement',
            'source_ref':'scope.company_name','observed_at':'2026-09-15'},fact()]
    assessment={**result_with_matter(facts,established_matter(row['text'],row['article'])),
                'contract_version':contract.CONTRACT_VERSION,'source_ids':[RELATED],
                'citations':[row for row in catalog['sources'] if row['id']==RELATED]}
    state={'id':'e1','title':'模拟事项','company_id':'c1','company_name':'复核测试公司','layer':'chinext',
           'kind':'unclassified','intake_mode':'open','output_mode':'text','created_at':'2026-09-15T00:00:00+00:00',
           'facts':{'event_date':'2026-09-15','assessment_as_of':'2026-09-15'},'summary':SUMMARY,
           'assessment':assessment}
    receipt=gates.evaluate(state,Seeds(KNOWLEDGE),'assessment',catalog=catalog,require_result=True)
    assert receipt['status']=='PENDING_REVIEW'
    assert receipt['next_action']['action']=='semantic_review'
    assert [row['item_id'] for row in receipt['semantic_review']]==['fact:amount']
    assert '检查未通过' not in json.dumps(receipt,ensure_ascii=False)


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('DISCLOSURE_TEST_KEY','fixture-not-real-123456')
    app=create_app(tmp_path/'var',isolated_root(tmp_path),{'allowed_hosts':['testserver']},pi_config=CONFIG,pi_runner=lambda *a:None)
    with TestClient(app) as c:
        session=c.get('/api/session').json();c.headers.update({'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']})
        yield c,app.state.pi_runtime,tmp_path


def make_event(c):
    r=c.post('/api/events',json={'board':'chinext','kind':'unclassified','title':'语义复核隔离测试',
        'company_name':'复核测试公司','summary':SUMMARY,
        'facts':{'event_date':'2026-09-15','assessment_as_of':'2026-09-15'},'output_mode':'text','request_id':str(uuid4())})
    assert r.status_code==200,r.text
    return r.json()


def candidate(company='复核测试公司'):
    return {'status':'disclose','summary':SUMMARY,'reasons':['模拟理由'],'missing':[],'limitations':['模拟'],
            'facts':[{'key':'scope.company_name','value':company,'status':'user_statement','source_ref':'scope.company_name','observed_at':'2026-09-15'},fact()],
            'matters':[{'matter_id':'m1','event_types':['模拟'],'subject':'模拟事项','stage':'模拟阶段',
                        'duty_status':'mandatory','timing_status':'triggered','trigger_events':['模拟触发'],
                        'deadline_basis':[RELATED],
                        'reasoning_items':[{'source_id':RELATED,'condition':'模拟条件','fact_keys':['scope.company_name'],
                                            'application':'模拟应用','outcome':'established'}],
                        'reassessment_conditions':[],'history_status':'incomplete'}]}


def run_flow(c,runtime,verdict_text):
    e=make_event(c)
    s=c.post('/api/chat/sessions',json={'event_id':e['id'],'board':'chinext','title':'语义复核','request_id':str(uuid4())}).json()
    seen=[];submitted={'done':False}
    def runner(packet,emit,bridge,stop):
        if packet.get('stage')=='semantic_review':
            seen.append(('review',packet))
            emit({'type':'assistant','message':0,'phase':'answer','stopReason':'stop','text':verdict_text})
            emit({'type':'done'});return
        emit({'type':'started'})
        bridge('prepare_disclosure_workflow',{'request_quote':packet['prompt']})
        if not submitted['done']:
            submitted['done']=True
            reply=bridge('submit_candidate',{'result':candidate()})
            seen.append(('reply',reply))
        emit({'type':'done'})
    runtime.runner=runner
    response=c.post(f"/api/chat/sessions/{s['id']}/runs",json={'text':'复核本节点事实','model_key':'fixture-a',
        'stage':'assessment','expected_revision':e['revision'],'request_id':str(uuid4())})
    assert response.status_code==200,response.text
    rid=response.json()['id'];deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        out=c.get('/api/chat/runs/'+rid).json()
        if out['run']['status'] not in ('accepted','running','cancelling'):break
        time.sleep(.05)
    return e,rid,seen


def test_runtime_reviews_in_fresh_context_then_adopts_supported_candidate(client):
    c,runtime,_=client
    verdicts={'verdicts':[{'item_id':'fact:amount','verdict':'supported','reason':'括注与写法差异不影响金额'}]}
    e,rid,seen=run_flow(c,runtime,json.dumps(verdicts))
    reply=next(body for kind,body in seen if kind=='reply')
    assert reply['data']['outcome'] in ('continue','waiting_approval'),reply
    packets=[packet for kind,packet in seen if kind=='review']
    assert len(packets)==1
    assert packets[0]['history']==[] and 'knowledge_web_search' in {t['name'] for t in packets[0]['tools']}
    assert '独立的事实一致性复核员' in packets[0]['system']
    saved=c.get('/api/events/'+e['id']).json()
    assert saved['verified_stages']['assessment']['status']=='PASS'
    assert saved['assessment']['facts'][1]['key']=='amount'
    event_fp=saved['verified_stages']['assessment']['input_fingerprint']
    task=next(t for t in saved['agent_tasks'] if t['stage']=='assessment')
    assert task['semantic_review']['candidate_sha256'] and task['semantic_review']['verdicts'][0]['verdict']=='supported'
    assert event_fp


def test_conflict_verdict_blocks_and_keeps_no_adopted_assessment(client):
    c,runtime,_=client
    verdicts={'verdicts':[{'item_id':'fact:amount','verdict':'conflict','reason':'金额与原文不一致，原文为100元'}]}
    e,rid,seen=run_flow(c,runtime,json.dumps(verdicts))
    reply=next(body for kind,body in seen if kind=='reply')
    assert reply['data']['outcome'] in ('blocked','revise'),reply
    assert any(row['code']=='fact_value_conflict' for row in reply['data']['gate']['issues'])
    saved=c.get('/api/events/'+e['id']).json()
    assert saved['assessment'] is None and not saved.get('verified_stages')


def test_unusable_reviewer_output_blocks_with_explicit_reason(client):
    c,runtime,_=client
    e,rid,seen=run_flow(c,runtime,'这不是结构化结论')
    reply=next(body for kind,body in seen if kind=='reply')
    assert reply['data']['outcome']=='blocked',reply
    assert any(row['code']=='semantic_review_incomplete' for row in reply['data']['gate']['issues'])
    journal=[row['body'] for row in runtime.store.journal(rid) if row['kind']=='semantic_review_result']
    assert journal and journal[-1]['source']=='invalid_result'
    assert c.get('/api/events/'+e['id']).json()['assessment'] is None


def test_review_uses_selected_model_instead_of_separate_override(client):
    c,runtime,_=client
    runtime.config_override={**CONFIG,'semantic_review':{'model_key':'not-configured-model'}}
    e,rid,seen=run_flow(c,runtime,json.dumps({'verdicts':[]}))
    reply=next(body for kind,body in seen if kind=='reply')
    assert reply['data']['outcome']=='blocked'
    journal=[row['body'] for row in runtime.store.journal(rid) if row['kind']=='semantic_review_result']
    assert journal and journal[-1]['source']=='invalid_result'
    assert [packet['model']['id'] for kind,packet in seen if kind=='review']==['offline-a']


def test_identical_candidate_reuses_review_record_across_events(client):
    c,runtime,_=client
    verdicts=json.dumps({'verdicts':[{'item_id':'fact:amount','verdict':'supported','reason':'差异不影响金额'}]})
    _,first_rid,first_seen=run_flow(c,runtime,verdicts)
    _,second_rid,second_seen=run_flow(c,runtime,verdicts)
    assert [packet for kind,packet in first_seen if kind=='review']
    assert [packet for kind,packet in second_seen if kind=='review']==[]
    reused=[row['kind'] for row in runtime.store.journal(second_rid)]
    assert 'semantic_review_reused' in reused
