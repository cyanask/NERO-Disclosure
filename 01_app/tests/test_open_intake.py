from internal_workflow import route as internal_route
from internal_workflow import context as read_context
"""Open intake and source-led text flow at the existing HTTP boundary."""
from uuid import uuid4
from test_agent_tasks import SCENARIO_DATE, env, post, claimed, submit, latest, candidate, confirm_stage


def real_event(c, *, board='chinext', required=True, output_mode='text'):
    response=c.post('/api/events',json={'company_name':'样例科技（上海）互联网科技股份有限公司',
        'stock_code':'300001','board':board,'kind':'strategic_placement_reduction',
        'title':'战略配售股东拟减持','summary':'测试输入：战略配售股东准备减持；不是现实披露结论。',
        'facts':{'assessment_as_of':SCENARIO_DATE,'requires_shareholder_approval':required},
        'output_mode':output_mode,'request_id':str(uuid4())})
    assert response.status_code==200,response.text
    return response.json()


def assess(c,current,token,value):
    task,lease=claimed(c,current,token)
    assert submit(c,current,task,lease,token,value).status_code==200
    return post(c,current,f"agent-tasks/{task['id']}/adopt")


def source_plan():
    documents=[];requirements=[]
    for key,title in [('notice','模拟公告一'),('explanation','模拟说明二')]:
        documents.append({'document_id':key,'title':title,'purpose':'public','necessity':'required',
            'applicability':'测试中已确认的事项范围','stage':'current','producer':'公司',
            'production':'company_draft','timing':'测试节点','source_ids':['szse-chinext-2026-4.1.7']})
        requirements.append({'requirement_id':key+'-fact','document_id':key,'section_id':'facts',
            'topic':'事项说明','granularity':'说明本次事项的已知事实与所涉程序',
            'necessity':'required','applicability':'本次测试事项','source_ids':['szse-chinext-2026-4.1.7'],
            'fact_keys':['requires_shareholder_approval'],'historical_relation':'unknown','verify_method':'逐项核对本次输入与条文'})
    return {'documents':documents,'requirements':requirements}


def test_real_issuer_and_unlisted_matter_can_enter_a_without_template(env):
    c,tokens,_,_=env;current=real_event(c,board='chinext')
    task,lease=claimed(c,current,tokens[0])
    packet=read_context(c,current,task,tokens[0]).json()
    assert packet['event']['company_name']==current['company_name']
    assert packet['event']['stock_code']=='300001' and packet['board']=='chinext'
    assert packet['stage_skill']['id']=='disclosure-duty-assessment'
    assert packet['templates']==[]
    assert 'law_missing' not in {i['code'] for i in packet['verification_gate']['issues']}
    response=internal_route(c,tokens[0],{'operation':'task.library.search',
        'args':{'event_id':current['id'],'task_id':task['id'],'collection':'laws','query':'减持'}})
    assert response.status_code==200,response.text
    assert response.json()['data']['board']=='chinext'
    assert c.get('/api/library/search',params={'board':'chinext','collection':'laws','kind':'strategic_placement_reduction'}).status_code==200


def test_unknown_reasoning_cannot_be_declared_no_disclosure(env):
    c,tokens,_,_=env;current=real_event(c);value=candidate()
    value['status']='no_disclosure';matter=value['matters'][0]
    matter.update(duty_status='no_mandatory_identified',timing_status='unknown',reassessment_conditions=['核实股东身份后复判'])
    matter['reasoning_items'][0]['outcome']='unknown'
    response=assess(c,current,tokens[0],value)
    assert response.status_code==409,response.text
    assert 'unknown_duty_as_no_disclosure' in {i['code'] for i in response.json()['detail']['gate']['issues']}
    assert post(c,current,'agent-tasks',stage='plan').status_code==409


def test_no_disclosure_decision_stops_ordinary_downstream(env):
    c,tokens,_,_=env;current=real_event(c,required=False);value=candidate()
    value['facts'][0]['value']=False;value['status']='no_disclosure'
    value['matters'][0].update(duty_status='no_mandatory_identified',timing_status='not_triggered',reassessment_conditions=['出现新的事实或独立触发条件'])
    value['matters'][0]['reasoning_items'][0]['outcome']='not_met'
    response=assess(c,current,tokens[0],value);assert response.status_code==200,response.text
    response=confirm_stage(c,current,'assessment','no_disclosure');assert response.status_code==200,response.text
    assert response.json()['stage']=='no_disclosure_manual_tracking'
    assert post(c,current,'agent-tasks',stage='plan').status_code==409


def test_valid_unknown_assessment_is_saved_for_input_not_misreported_pass(env):
    c,tokens,_,_=env;current=real_event(c);value=candidate()
    value['status']='needs_info';value['missing']=['请核实股东控制关系']
    value['facts'][0].update(status='unknown',value=None)
    value['matters'][0].update(duty_status='undetermined',timing_status='unknown',
        decisive_questions=['请核实股东控制关系'],reassessment_conditions=['事实补齐后复判'])
    value['matters'][0]['reasoning_items'][0]['outcome']='unknown'
    response=assess(c,current,tokens[0],value)
    assert response.status_code==200,response.text
    saved=response.json()
    assert saved['stage']=='awaiting_assessment_information'
    assert saved['assessment']['status']=='needs_info' and not saved['assessment']['verified']
    assert saved['verification']['status']=='BLOCKED'
    assert not saved.get('approval_records')
    assert post(c,current,'agent-tasks',stage='plan').status_code==409


def test_source_led_multiple_texts_require_a_b_but_not_word_template(env):
    c,tokens,root,_=env;current=real_event(c)
    response=assess(c,current,tokens[0],candidate());assert response.status_code==200,response.text
    assert post(c,current,'agent-tasks',stage='plan').status_code==409
    assert confirm_stage(c,current,'assessment','prepare_mandatory').status_code==200
    task,lease=claimed(c,current,tokens[0],'plan');plan=source_plan()
    assert submit(c,current,task,lease,tokens[0],plan).status_code==200
    response=post(c,current,f"agent-tasks/{task['id']}/adopt");assert response.status_code==200,response.text
    assert 'format_not_bound' in {w['code'] for w in response.json()['verification']['warnings']}
    assert post(c,current,'agent-tasks',stage='draft').status_code==409
    assert confirm_stage(c,current,'plan').status_code==200
    task,lease=claimed(c,current,tokens[0],'draft')
    packet=read_context(c,current,task,tokens[0]).json()
    assert 'template_id' not in packet['result_schema'].get('required',[])
    texts={'documents':[{'document_id':key,'text':title+'\n本次事项涉及已列明的股东会程序。',
        'requirement_map':{key+'-fact':'本次事项涉及已列明的股东会程序。'}}
        for key,title in [('notice','模拟公告一'),('explanation','模拟说明二')]]}
    assert submit(c,current,task,lease,tokens[0],texts).status_code==200
    response=post(c,current,f"agent-tasks/{task['id']}/adopt");assert response.status_code==200,response.text
    assert [d['document_id'] for d in response.json()['draft']['documents']]==['notice','explanation']
    assert not (root/'var/templates').exists()
    assert c.get(f"/api/events/{current['id']}/word/context").status_code==409


def test_issuer_identity_cannot_override_an_existing_company_binding(env):
    c,_,_,_=env
    response=c.post('/api/events',json={'company_id':'demo-base','company_name':'另一家公司',
        'board':'chinext','title':'不得覆盖已绑定身份','request_id':str(uuid4())})
    assert response.status_code==422


def test_registered_content_profile_can_use_a_new_matter_label(env):
    c,_,_,_=env
    snapshot=c.get('/api/library/profiles/manage',params={'board':'chinext'}).json()
    row={**snapshot['items'][0],'id':'profile-open-intake-example','kind':'strategic_placement_reduction'}
    response=c.post('/api/library/profiles/update',params={'board':'chinext'},json={'expected_fingerprint':snapshot['fingerprint'],'items':[row]})
    assert response.status_code==200,response.text
    result=c.get('/api/library/search',params={'board':'chinext','collection':'profiles','kind':'strategic_placement_reduction'}).json()
    assert [r['id'] for r in result['items']]==[row['id']]


def test_unknown_fact_cannot_be_used_as_negative_duty_path(env):
    c,tokens,_,_=env;current=real_event(c);value=candidate()
    value['status']='no_disclosure';value['facts'][0].update(status='unknown',value=None)
    value['matters'][0].update(duty_status='no_mandatory_identified',timing_status='unknown',
        reassessment_conditions=['核实未知事实后复判'])
    value['matters'][0]['reasoning_items'][0]['outcome']='not_met'
    response=assess(c,current,tokens[0],value)
    assert response.status_code==409
    assert 'unknown_fact_as_negative' in {i['code'] for i in response.json()['detail']['gate']['issues']}


def test_open_intake_preserves_explicit_event_date(env):
    c,_,_,_=env
    response=c.post('/api/events',json={'company_name':'真实主体','board':'chinext','title':'历史事项',
        'facts':{'event_date':'2025-09-30'},'request_id':str(uuid4())})
    assert response.status_code==200
    assert response.json()['facts']['assessment_as_of']=='2025-09-30'


def test_quoted_numbers_accept_grouping_without_scale_or_substring_errors():
    from backend.disclosure_contract import quoted_value_matches
    assert quoted_value_matches(1559259, '获配1,559,259股')
    assert quoted_value_matches(-1234.5, '变动-1,234.50元')
    assert not quoted_value_matches(559259, '获配1,559,259股')
    assert not quoted_value_matches(12, '共112股')
    assert not quoted_value_matches(1559259, '获配155.9259万股')
    assert not quoted_value_matches(12345, '错误分组1,23,45股')


def test_legal_anchor_tolerates_layout_and_sublocator_not_changed_words():
    from backend.disclosure_contract import excerpt_in_source, locator_matches
    assert excerpt_in_source('应当按照本所规定', '应当按照\n\n本所规定')
    assert not excerpt_in_source('可以按照本所规定', '应当按照\n本所规定')
    assert locator_matches('第二章第三节第2.3.14条第二款', '2.3.14', '')
    assert not locator_matches('第12.3.14条', '2.3.14', '')
    assert locator_matches('第十一条第一款', '第十一条', '')
    assert not locator_matches('第二十一条', '第十一条', '')
