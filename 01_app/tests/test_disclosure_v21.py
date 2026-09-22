from internal_workflow import context as read_context
"""v2.1 business acceptance at private workflow and browser gates; all data are simulated."""
import copy
import hashlib
import json
from uuid import uuid4
import pytest
from test_agent_tasks import (env as copied_env, event, claimed, candidate, post, submit, latest,
                             confirm_stage, plan_candidate, approve_template)
from internal_workflow import invoke

@pytest.fixture
def env(copied_env):
    from conftest import ready_layout
    ready_layout(copied_env[2])
    return copied_env


def route(client,caller,operation,args=None):
    return invoke(client,caller,operation,args or {},wrapped=True)



def context(client, current, task, token):
    return read_context(client,current,task,token).json()


def adopt(client, current, token, value=None, stage='assessment'):
    task, lease = claimed(client, current, token, stage)
    response = submit(client, current, task, lease, token, value or candidate())
    assert response.status_code == 200, response.text
    return post(client, current, f"agent-tasks/{task['id']}/adopt")


def accepted_a(client, token):
    current=event(client)
    result=adopt(client,current,token)
    assert result.status_code==200,result.text
    result=confirm_stage(client,current,'assessment','prepare_mandatory')
    assert result.status_code==200,result.text
    return current


def prepared_plan(client,current,token):
    task,lease=claimed(client,current,token,'plan')
    ctx=context(client,current,task,token)
    return task,lease,ctx,plan_candidate(ctx)


def test_v21_method_loaded_by_bound_node(env):
    client, tokens, _, _ = env
    current = event(client)
    task, _ = claimed(client, current, tokens[0])
    context = read_context(client,current,task,tokens[0]).json()
    assert context['stage_skill']['id'] == 'disclosure-duty-assessment'
    assert context['scope_ref']['client_ref'] == current['company_id']
    assert 'board' not in context['result_schema']['properties']
    assert context['capabilities']['client_history']['status'] == 'not_connected'


def test_natural_language_intake_does_not_need_fact_approval(env):
    """自然语言事项凭摘要原句登记事实；判定性事实先经独立语义复核，但不需要用户事实确认。"""
    c,tokens,_,_=env
    current=c.post('/api/events',json={'company_id':'demo-chinext','kind':'board_resolution','title':'模拟自然语言事项',
        'summary':'模拟议案须经股东会表决。','facts':{'event_date':'2026-09-08'},'request_id':str(uuid4())}).json()
    value=candidate('2026-09-08');value['facts']=[{'key':'requires_shareholder_approval','value':'须经股东会表决',
        'status':'user_statement','source_ref':'summary','quote':'模拟议案须经股东会表决。','observed_at':'2026-09-08'}]
    task,lease=claimed(c,current,tokens[0])
    def evaluate(**extra):
        return post(c,current,f"agent-tasks/{task['id']}/evaluate",tokens[0],claim_id=lease['claim_id'],
                    input_fingerprint=lease['input_fingerprint'],result=value,**extra)
    first=evaluate();assert first.status_code==200,first.text
    assert first.json()['outcome']=='review_pending',first.text
    items=first.json()['gate']['semantic_review']
    assert [i['item_id'] for i in items]==['fact:requires_shareholder_approval']
    verdicts=[{'item_id':i['item_id'],'verdict':'supported','reason':'模拟复核：事实值与事项说明原句一致'} for i in items]
    second=evaluate(semantic_review=verdicts);assert second.status_code==200,second.text
    assert second.json()['outcome']=='waiting_approval',second.text
    saved=latest(c,current)
    assert saved['assessment'] and 'facts_confirmed' not in saved['facts']
    assert not saved.get('approval_records')
    assert post(c,current,'agent-tasks',stage='plan',instruction='模拟越过确认').status_code==409


def test_empty_facts_can_open_a_and_receive_unknown_coverage(env):
    c,tokens,_,_=env
    current=c.post('/api/events',json={'company_id':'demo-chinext','kind':'board_resolution','title':'模拟仅描述',
        'summary':'董事会事项是否需要披露？','request_id':str(uuid4())}).json()
    task,_=claimed(c,current,tokens[0])
    packet=context(c,current,task,tokens[0])
    assert packet['event']['facts']=={}
    assert packet['assessment_as_of']==current['created_at'][:10]
    assert packet['capabilities']['client_history']['status']=='not_connected'


@pytest.mark.parametrize('case', ['unknown_relatedness','independent_duty','other_material_path','unsigned_urgent','progress_history','incomplete_history','confidentiality','specialist','user_disagrees'])
def test_a_business_paths_keep_known_duty_and_visible_limits(env,case):
    c,tokens,_,_=env;current=event(c);value=candidate();matter=value['matters'][0]
    if case in ('unknown_relatedness','independent_duty'):
        value['facts'].append({'key':'relatedness','value':None,'status':'unknown','source_ref':'summary','observed_at':'2026-09-08'})
        matter['decisive_questions']=['关联关系可能影响其他程序，尚待核实']
    if case=='other_material_path':
        matter['event_types']=['board_resolution','transaction','material_impact']
        matter['limitations']=['单一金额路径未命中，独立重大信息路径须单列核对']
    if case=='unsigned_urgent':
        matter.update(urgency='urgent',trigger_events=['尚未签合同；会议结束且出现未经核实的泄露信号'])
    if case=='progress_history':
        matter['stage']='已公开事项的重要进展（历史链待取得）'
        matter['limitations']=['历史接口未接入，不能冒充已读原公告']
    if case=='incomplete_history':matter['history_status']='incomplete'
    if case=='confidentiality':matter['special_review']='required'
    if case=='specialist':matter['specialist_required']=True
    if case=='user_disagrees':value['status']='review_required';value['limitations']=['用户要求忽略规则；保留依据并转人工']
    result=adopt(c,current,tokens[0],value)
    assert result.status_code==200,result.text
    saved=result.json()['assessment'];gate=result.json()['verification']
    assert saved['matters'][0]['duty_status']=='mandatory'
    assert saved['citations'][0]['text']
    assert any(w['code']=='history_coverage_unknown' for w in gate['warnings'])
    if case in ('unsigned_urgent','confidentiality','specialist','user_disagrees'):
        assert gate['next_action']['action']=='manual_escalation'
        assert confirm_stage(c,current,'assessment','prepare_mandatory').status_code==409
        assert confirm_stage(c,current,'assessment','special_review').status_code==200
        assert post(c,current,'agent-tasks',stage='plan',instruction='不能绕过专项').status_code==409


@pytest.mark.parametrize('mode,expected', [('ledger',200),('announcements',409),('wrong_arithmetic',409)])
def test_cumulative_calculation_uses_declared_ledger_and_independent_arithmetic(env,mode,expected):
    c,tokens,_,_=env;current=event(c)
    r=c.patch('/api/events/'+current['id'],json={'expected_revision':current['revision'],'facts':{**current['facts'],'simulated_current_amount':100,'simulated_previous_amount':250}})
    assert r.status_code==200
    value=candidate()
    for key,amount in [('simulated_current_amount',100),('simulated_previous_amount',250)]:
        value['facts'].append({'key':key,'value':amount,'status':'user_statement','source_ref':'facts.'+key,'observed_at':'2026-09-08'})
    value['matters'][0]['calculations']=[{'operation':'sum','fact_keys':['simulated_current_amount','simulated_previous_amount'],
        'result':'999' if mode=='wrong_arithmetic' else '350','unit':'模拟元','period':'模拟适用累计期间',
        'basis_source_id':'szse-chinext-2026-4.1.7','aggregation_basis':'public_announcements' if mode=='announcements' else 'user_declared_complete_ledger'}]
    response=adopt(c,current,tokens[0],value)
    assert response.status_code==expected,response.text
    if mode=='announcements':assert 'ledger_incomplete' in {i['code'] for i in response.json()['detail']['gate']['issues']}
    if mode=='wrong_arithmetic':assert 'calculation_mismatch' in {i['code'] for i in response.json()['detail']['gate']['issues']}


def test_voluntary_preparation_keeps_original_duty_conclusion(env):
    c,tokens,_,_=env;current=event(c);value=candidate()
    assert c.patch('/api/events/'+current['id'],json={'expected_revision':current['revision'],
        'facts':{**current['facts'],'requires_shareholder_approval':False,'contains_disclosable_information':False}}).status_code==200
    value['facts'][0]['value']=False
    value['status']='no_disclosure';matter=value['matters'][0]
    matter.update(duty_status='no_mandatory_identified',timing_status='not_triggered',reassessment_conditions=['模拟新事实或独立披露路径成立时复判'])
    matter['reasoning_items'][0]['outcome']='not_met'
    result=adopt(c,current,tokens[0],value);assert result.status_code==200,result.text
    assert confirm_stage(c,current,'assessment','prepare_mandatory').status_code==409
    response=confirm_stage(c,current,'assessment','prepare_voluntary');assert response.status_code==200,response.text
    assert response.json()['assessment']['status']=='no_disclosure'
    assert post(c,current,'agent-tasks',stage='plan',instruction='模拟自愿披露').status_code==200


def test_planning_can_be_ready_while_payment_details_block_drafting(env):
    c,tokens,_,_=env;current=accepted_a(c,tokens[0]);task,lease,ctx,plan=prepared_plan(c,current,tokens[0])
    plan['drafting_gaps']=[{'key':'payment_detail','description':'本次付款明细待提供','impact':'draft','owner':'模拟财务人员','treatment':'supply'}]
    plan['requirements'][0]['gap_key']='payment_detail'
    assert submit(c,current,task,lease,tokens[0],plan).status_code==200
    result=post(c,current,f"agent-tasks/{task['id']}/adopt");assert result.status_code==200,result.text
    assert result.json()['plan']['review_readiness']=='ready'
    assert result.json()['plan']['drafting_readiness']['status']=='blocked'
    assert confirm_stage(c,current,'plan').status_code==200
    approve_template(c,current,tokens[0],ctx,plan)
    assert post(c,current,'agent-tasks',stage='draft',instruction='资料未齐').status_code==409
    before=latest(c,current)['approval_records']
    result=post(c,current,'drafting-supplements',values={'payment_detail':'模拟付款明细：到期支付'},source_note='模拟使用者本次补充，未经材料核验')
    assert result.status_code==200,result.text
    assert [r for r in result.json()['approval_records'] if r['state']=='current']==[r for r in before if r['state']=='current']
    saved=result.json();previous=saved['drafting_supplements']['payment_detail']
    reopened=post(c,current,'reopen',stage='template',reason='仅调整模板章节承载').json()
    assert reopened['plan']['id']==saved['plan']['id']
    assert reopened['plan']['drafting_readiness']['status']=='ready'
    assert reopened['drafting_supplements']['payment_detail']==previous
    approve_template(c,current,tokens[0],ctx,plan)
    assert post(c,current,'agent-tasks',stage='draft',instruction='资料已补齐').status_code==200
    assert post(c,current,'drafting-supplements',values={'requires_shareholder_approval':'False'},source_note='试图覆盖关键条件').status_code==409


@pytest.mark.parametrize('change', ['gap_description', 'requirement'])
def test_replanned_gap_cannot_reuse_previous_supplement(env,change):
    c,tokens,_,_=env;current=accepted_a(c,tokens[0]);task,lease,ctx,plan=prepared_plan(c,current,tokens[0])
    plan['drafting_gaps']=[{'key':'payment_detail','description':'9月付款明细待提供','impact':'draft','owner':'模拟财务人员','treatment':'supply'}]
    plan['requirements'][0]['gap_key']='payment_detail'
    assert submit(c,current,task,lease,tokens[0],plan).status_code==200
    assert post(c,current,f"agent-tasks/{task['id']}/adopt").status_code==200
    assert confirm_stage(c,current,'plan').status_code==200
    approve_template(c,current,tokens[0],ctx,plan)
    supplied=post(c,current,'drafting-supplements',values={'payment_detail':'仅模拟9月付款明细'},source_note='模拟9月资料').json()
    previous=supplied['drafting_supplements']['payment_detail']
    assert supplied['plan']['drafting_readiness']['status']=='ready'

    reopened=post(c,current,'reopen',stage='plan',reason='本次规划新增10月付款要求')
    assert reopened.status_code==200,reopened.text
    assert reopened.json()['plan']['id']==supplied['plan']['id']
    assert reopened.json()['plan']['drafting_readiness']['status']=='blocked'
    task,lease,ctx,_=prepared_plan(c,current,tokens[0])
    revised=copy.deepcopy(plan)
    if change=='gap_description':
        revised['drafting_gaps'][0]['description']='10月付款明细待提供，9月明细不适用'
    else:
        revised['requirements'][0]['granularity']='须列明10月新增付款，原9月明细不适用'
    assert submit(c,current,task,lease,tokens[0],revised).status_code==200
    response=post(c,current,f"agent-tasks/{task['id']}/adopt")
    assert response.status_code==200,response.text
    saved=response.json()
    assert saved['plan']['id']!=supplied['plan']['id']
    retained=saved['drafting_supplements']['payment_detail']
    assert retained['value']==previous['value'] and retained['plan_id']==previous['plan_id']
    assert retained['state']=='invalidated'
    assert saved['plan']['review_readiness']=='ready'
    assert saved['plan']['drafting_readiness']['status']=='blocked'
    assert confirm_stage(c,current,'plan').status_code==200
    approve_template(c,current,tokens[0],ctx,revised)
    assert post(c,current,'agent-tasks',stage='draft',instruction='旧资料不能满足新规划').status_code==409

    before=latest(c,current)['approval_records']
    response=post(c,current,'drafting-supplements',values={'payment_detail':'已核对本次模拟10月付款明细'},source_note='模拟使用者重新核对新规划')
    assert response.status_code==200,response.text
    saved=response.json()
    assert saved['plan']['drafting_readiness']['status']=='ready'
    assert [r for r in saved['approval_records'] if r['state']=='current']==[r for r in before if r['state']=='current']
    assert post(c,current,'agent-tasks',stage='draft',instruction='使用重新核对的补充资料').status_code==200


@pytest.mark.parametrize('supplements', [None,
    {'payment_detail':{'value':'历史付款明细','source_note':'旧版本记录','status':'user_statement'}},
    {'payment_detail':{'value':'历史付款明细','plan_id':'old-plan','state':'current'}},
    {'payment_detail':{'value':'历史付款明细','plan_id':'current-plan','state':'invalidated'}}])
def test_legacy_unbound_supplement_remains_visible_but_cannot_clear_gap(supplements):
    from backend.disclosure_contract import drafting_readiness
    current={'plan':{'id':'current-plan','drafting_gaps':[{'key':'payment_detail','description':'本次付款明细','treatment':'supply'}],
        'documents':[{'title':'模拟公告','stage':'current','production':'company_draft'}]},
        'drafting_supplements':supplements}
    original=copy.deepcopy(current)
    assert drafting_readiness(current)=={'status':'blocked','blockers':['本次付款明细']}
    assert current==original


@pytest.mark.parametrize('mutation,code', [('omit_field',None),('case_over_rule','case_as_requirement'),('outline_only','granularity_missing'),('external_report',None)])
def test_b_independent_format_coverage_and_document_dependencies(env,mutation,code):
    c,tokens,_,_=env;current=accepted_a(c,tokens[0]);task,lease,ctx,plan=prepared_plan(c,current,tokens[0])
    if mutation=='omit_field':plan['requirements']=plan['requirements'][1:]
    if mutation=='outline_only':plan['requirements'][0]['granularity']=plan['requirements'][0]['topic']
    if mutation=='case_over_rule':
        # No cases are currently admitted: an invented citation is rejected before adoption.
        plan['requirements'][0]['source_ids']=['simulated-unadmitted-case']
    if mutation=='external_report':
        plan['documents'].append({'document_id':'third-party','title':'模拟专项报告','profile_id':'external',
            'purpose':'filing','necessity':'conditional','applicability':'模拟条件成立时','stage':'current',
            'producer':'模拟会计师事务所','production':'external_dependency','timing':'依本次程序要求',
            'dependencies':['尚未出具的真实报告'],'source_ids':['szse-chinext-2026-4.1.7']})
    response=submit(c,current,task,lease,tokens[0],plan)
    if mutation=='case_over_rule':
        assert response.status_code==422
        return
    assert response.status_code==200,response.text
    result=post(c,current,f"agent-tasks/{task['id']}/adopt")
    if code:
        assert result.status_code==409,result.text
        assert code in {i['code'] for i in result.json()['detail']['gate']['issues']}
    else:
        assert result.status_code==200,result.text
        if mutation=='omit_field':
            codes={w['code'] for w in result.json()['verification']['warnings']}
            assert {'format_coverage_review','format_field_coverage_review'} & codes
            final_gate=c.get('/api/events/'+current['id']+'/verify?stage=draft').json()
            assert {'format_coverage_review','format_field_coverage_review'} & {w['code'] for w in final_gate['warnings']}
        else:
            assert result.json()['plan']['documents'][-1]['producer']=='模拟会计师事务所'
            assert result.json()['plan']['drafting_readiness']['status']=='blocked'


def test_changed_critical_fact_invalidates_a_and_downstream(env):
    c,tokens,_,_=env;current=accepted_a(c,tokens[0]);before=latest(c,current)
    response=c.patch('/api/events/'+current['id'],json={'expected_revision':before['revision'],'facts':{**before['facts'],'amount':999}})
    assert response.status_code==200
    assert response.json()['approval_records'][0]['state']=='invalidated'
    assert post(c,current,'agent-tasks',stage='plan',instruction='不得沿用旧判断').status_code==409


def test_template_omission_blocks_t_and_format_only_reopen_preserves_a_b(env):
    c,tokens,_,_=env;current=accepted_a(c,tokens[0]);task,lease,ctx,plan=prepared_plan(c,current,tokens[0])
    assert submit(c,current,task,lease,tokens[0],plan).status_code==200
    assert post(c,current,f"agent-tasks/{task['id']}/adopt").status_code==200
    assert confirm_stage(c,current,'plan').status_code==200
    task,lease=claimed(c,current,tokens[0],'template')
    value={'template_id':ctx['templates'][0]['id'],'requirement_map':{plan['requirements'][0]['requirement_id']:plan['requirements'][0]['section_id']}}
    assert submit(c,current,task,lease,tokens[0],value).status_code==200
    response=post(c,current,f"agent-tasks/{task['id']}/adopt")
    assert response.status_code==409
    assert 'template_requirement_missing' in {i['code'] for i in response.json()['detail']['gate']['issues']}
    response=post(c,current,'reopen',stage='template',reason='模拟仅调整模板结构')
    assert [r['node'] for r in response.json()['approval_records'] if r['state']=='current']==['assessment','plan']


def test_scope_and_approval_injection_are_rejected_on_server(env):
    c,tokens,_,_=env;current=event(c);other=event(c);task,lease=claimed(c,current,tokens[0])
    args={'event_id':current['id'],'task_id':task['id'],'collection':'laws'}
    assert route(c,tokens[0],'task.library.search',{**args,'board':'chinext'}).status_code==422
    assert route(c,tokens[0],'task.library.search',{**args,'client_ref':'another-client'}).status_code==422
    assert route(c,tokens[0],'task.library.search',{**args,'event_id':other['id']}).status_code==404
    assert route(c,tokens[1],'task.library.search',args).status_code==403
    missing=route(c,tokens[0],'task.library.search',{**args,'collection':'client_history'}).json()['data']
    assert missing['status']=='not_connected' and not missing['not_found_is_absence']
    assert submit(c,current,task,lease,tokens[0],{**candidate(),'approved':True}).status_code==422
    nested=candidate();nested['matters'][0]['approved']=True
    assert submit(c,current,task,lease,tokens[0],nested).status_code==422
    assert route(c,tokens[0],'human.confirm',{}).status_code==403
    forged=post(c,current,'confirmations',tokens[0],stage='assessment',input_fingerprint='0'*64,
        decision='prepare_mandatory',reviewer='伪造人员',reason='不应写入')
    assert forged.status_code==403 and not latest(c,current).get('approval_records')


def test_exact_four_confirmations_archive_only_current_unpublished_word(env):
    from test_word_delivery import ready,word_bytes,register
    c,tokens,root,_=env;current,packet=ready(c,tokens[0]);raw=word_bytes(root,packet)
    registered=register(c,current,packet,raw);assert registered.status_code==200,registered.text
    artifact=registered.json()['artifacts'][-1]
    assert len([r for r in registered.json()['approval_records'] if r['state']=='current'])==3
    assert confirm_stage(c,current,'word',artifact_id=artifact['id']).status_code==409
    response=confirm_stage(c,current,'word',artifact_id=artifact['id'],visual_review='reviewed',content_review='reviewed')
    assert response.status_code==200,response.text
    saved=response.json()
    assert [r['node'] for r in saved['approval_records'] if r['state']=='current']==['assessment','plan','template','word']
    assert saved['stage']=='confirmed_draft_archived'
    assert saved['artifacts'][-1]['published'] is False
    assert not (root/'data/client_history').exists()
    assert saved['approval_records'][-1]['artifact_sha256']==hashlib.sha256(raw).hexdigest()
    reopened=post(c,current,'reopen',stage='draft',reason='模拟仅修字体和页眉').json()
    assert [r['node'] for r in reopened['approval_records'] if r['state']=='current']==['assessment','plan','template']


def test_word_gate_rereads_real_file_before_confirmation(env):
    from test_word_delivery import ready,word_bytes,register
    c,tokens,root,_=env;current,packet=ready(c,tokens[0]);raw=word_bytes(root,packet)
    response=register(c,current,packet,raw);assert response.status_code==200
    artifact=response.json()['artifacts'][-1]
    path=root/'var/artifacts'/artifact['file'];path.write_bytes(b'simulated corruption')
    gate=c.get('/api/events/'+current['id']+'/verify',params={'stage':'word'}).json()
    assert gate['status']=='BLOCKED'
    assert 'word_file_invalid' in {i['code'] for i in gate['issues']}
    assert confirm_stage(c,current,'word',artifact_id=artifact['id'],visual_review='reviewed',content_review='reviewed').status_code==409


def test_repeated_repairs_keep_evidence_gates_without_a_numerical_stop(env):
    c,tokens,_,_=env;current=event(c);task,lease=claimed(c,current,tokens[0]);value=candidate()
    value['matters'][0]['reasoning_items'][0]['quote']='模拟不存在的条文原句'
    assert submit(c,current,task,lease,tokens[0],value).status_code==200
    for _ in range(6):assert post(c,current,f"agent-tasks/{task['id']}/adopt").status_code==409
    saved=latest(c,current)
    assert saved['stage']!='manual_escalation' and not saved.get('escalation')
    assert saved['agent_tasks'][-1]['result']['summary']==value['summary']
    assert post(c,current,'reopen',tokens[0],stage='assessment',reason='试图重置').status_code==403


def test_shared_contract_change_invalidates_confirmed_method(env):
    c,tokens,root,_=env;current=accepted_a(c,tokens[0])
    ref=root/'skills/disclosure-contract.md';ref.write_text(ref.read_text()+'\n模拟合同版本更新。\n')
    registry=root/'skills/registry.json';data=json.loads(registry.read_text())
    for row in data['stages'].values():row['references'][0]['sha256']=hashlib.sha256(ref.read_bytes()).hexdigest()
    registry.write_text(json.dumps(data))
    result=latest(c,current)
    assert result['approval_records'][0]['state']=='invalidated'
    assert post(c,current,'agent-tasks',stage='plan',instruction='不得复用旧方法确认').status_code==409
