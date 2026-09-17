"""Private workflow service boundaries with synthetic internal callers, not real model acceptance."""
import copy
import json
from pathlib import Path
import shutil
import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.domain import Seeds
from internal_workflow import CALLERS,install_callers,invoke,context as read_context,route as internal_route

from conftest import KNOWLEDGE,ROOT,seed_project,seed_tree

# 事项发生日期来自当前 chinext-board-01 模拟样本；候选的基准日必须与其一致。
SCENARIO_DATE='2026-06-18'


@pytest.fixture
def env(tmp_path,monkeypatch):
    install_callers(monkeypatch)
    seed_project(tmp_path)
    config={'allowed_hosts':['testserver']}
    app=create_app(tmp_path/'var',tmp_path,config,legacy_test_mode=True)
    with TestClient(app) as client:
        def login():
            r=client.get('/api/session')
            client.headers.update({'Origin':'http://testserver','X-CSRF-Token':r.json()['csrf_token']})
        login()
        tokens=CALLERS
        yield client,tokens,tmp_path,config


def event(client, sample='chinext-board-01'):
    r=client.post('/api/scenarios/'+sample+'/import',json={'request_id':str(uuid4())})
    assert r.status_code==200,r.text
    return r.json()


def latest(client,e):
    return client.get('/api/events/'+e['id']).json()


def post(client,e,action,headers=None,**body):
    current=latest(client,e)
    payload={'expected_revision':current['revision'],'request_id':str(uuid4()),**body}
    if action=='agent-tasks':
        return invoke(client,headers,'task.request',{'event_id':e['id'],**payload})
    if headers and action.startswith('agent-tasks/'):
        _,task_id,verb=action.split('/')
        operation='task.open' if verb=='claim' else 'task.'+verb
        return invoke(client,headers,operation,{'event_id':e['id'],'task_id':task_id,**payload})
    return client.post('/api/events/'+e['id']+'/'+action,headers=headers or {},json=payload)


def request_task(client,e,stage='assessment'):
    r=post(client,e,'agent-tasks',stage=stage,instruction='仅使用公开模拟资料提出候选，不批准')
    assert r.status_code==200,r.text
    return r.json()['agent_tasks'][-1]


def claimed(client,e,token,stage='assessment'):
    task=request_task(client,e,stage)
    r=post(client,e,f"agent-tasks/{task['id']}/claim",token,host_family='pi',host_run_ref='synthetic-fixture')
    assert r.status_code==200,r.text
    return task,r.json()


def candidate(as_of=SCENARIO_DATE):
    return {'status':'disclose','summary':'模拟董事会议案须股东会表决，建议披露。',
            'reasons':['4.1.7 对应已给模拟事实。'],'missing':[],
            'source_ids':['szse-chinext-2026-4.1.7'],'limitations':['仅为测试候选，待专业审核'],
            'assessment_as_of':as_of,
            'facts':[{'key':'requires_shareholder_approval','value':True,'status':'user_statement',
                      'source_ref':'facts.requires_shareholder_approval','observed_at':as_of}],
            'matters':[{'matter_id':'simulated-matter','event_types':['board_resolution'],'subject':'模拟公司董事会',
                'stage':'会议结束','duty_status':'mandatory','timing_status':'triggered',
                'trigger_events':['会议结束，决议涉及股东会事项'],'deadline_basis':['szse-chinext-2026-4.1.7'],
                'reasoning_items':[{'source_id':'szse-chinext-2026-4.1.7','locator':'4.1.7',
                    'quote':'董事会决议涉及须经股东会审议的事项','condition':'模拟议案须股东会表决',
                    'fact_keys':['requires_shareholder_approval'],'application':'模拟事实与该条件对应；不作为现实法律验收',
                    'outcome':'established'}]}]}


def confirm_stage(client,e,stage,decision='accept',**extra):
    gate=client.get('/api/events/'+e['id']+'/verify',params={'stage':stage}).json()
    return post(client,e,'confirmations',stage=stage,input_fingerprint=gate['input_fingerprint'],
                decision=decision,reviewer='模拟测试人员',reason='模拟产品确认，非真实人工验收',**extra)


def plan_candidate(ctx):
    profile=next(p for p in ctx['profiles'] if p['id']==ctx['templates'][0]['profile_id'])
    items=[{'id':s['id'],'title':s['title'],'detail':'明确的模拟内容，供接口验收。',
            'evidence_status':'模拟事实','source_ids':['szse-chinext-2026-4.1.7']} for s in profile['sections']]
    requirements=[]
    for section in profile['sections']:
        fields=section.get('fields') or [None]
        for index,field in enumerate(fields):
            requirements.append({'requirement_id':section['id']+'-'+str(index),'document_id':'simulated-doc',
                'section_id':section['id'],'format_field_refs':[section['id']+':'+str(field['block'])] if field else [],
                'topic':field['prompt'] if field else section['title'],'granularity':'列明具体主体、日期、表决及适用条件；模拟接口数据',
                'necessity':'conditional' if field and field.get('conditional') else 'required','applicability':'本次模拟公告适用，条件项保留说明',
                'source_ids':['szse-chinext-2026-4.1.7'],'fact_keys':['requires_shareholder_approval'],
                'historical_relation':'unknown','verify_method':'原文对照及语义人工复核'})
    return {'items':items,'documents':[{'document_id':'simulated-doc','title':'模拟董事会决议公告','profile_id':profile['id'],
        'purpose':'public','necessity':'required','applicability':'模拟股东会事项','stage':'current','producer':'模拟公司',
        'production':'company_draft','timing':'会议结束后及时','source_ids':['szse-chinext-2026-4.1.7']}], 'requirements':requirements}


def approve_template(client,e,token,ctx,plan):
    task,lease=claimed(client,e,token,'template')
    value={'template_id':ctx['templates'][0]['id'],'requirement_map':{r['requirement_id']:r['section_id'] for r in plan['requirements']}}
    assert submit(client,e,task,lease,token,value).status_code==200
    adopted=post(client,e,f"agent-tasks/{task['id']}/adopt")
    assert adopted.status_code==200,adopted.text
    confirmed=confirm_stage(client,e,'template')
    assert confirmed.status_code==200,confirmed.text


def submit(client,e,task,lease,token,result=None):
    return post(client,e,f"agent-tasks/{task['id']}/submit",token,
        claim_id=lease['claim_id'],input_fingerprint=lease['input_fingerprint'],result=result or candidate())


def advance(client,e,stage,**extra):
    return post(client,e,'advance',stage=stage)


def test_candidate_inbox_and_verified_adoption(env):
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    public=latest(c,e)['agent_tasks'][0]
    assert 'snapshot' not in public and 'claim_id' not in public and 'owner_id' not in public
    ctx=read_context(c,e,task,tokens[0]).json()
    scenario=next(s for s in Seeds(KNOWLEDGE).scenarios() if s['id']=='chinext-board-01')
    assert ctx['event']['facts']['resolution_subject']==scenario['facts']['resolution_subject']
    assert ctx['rule_check']['status']=='disclose'
    assert ctx['templates']==[]
    assert all('text' not in row for row in ctx['rule_check']['citations'])
    assert len(json.dumps(ctx,ensure_ascii=False))<60000
    assert 'preliminary_plan' not in ctx['result_schema']['properties']
    assert 'PlanCandidate' not in ctx['result_schema'].get('$defs',{})
    assert submit(c,e,task,lease,tokens[0]).status_code==200
    assert latest(c,e)['assessment'] is None  # candidate cannot overwrite current artifact
    r=post(c,e,f"agent-tasks/{task['id']}/adopt",tokens[0])
    assert r.status_code==200,r.text
    a=r.json()['assessment'];assert a['mode']=='external_agent' and not a['approved']
    assert a['producer']['task_id']==task['id'] and a['citations'][0]['article']=='4.1.7'
    assert advance(c,e,'assessment').status_code==200


@pytest.mark.parametrize('result',[{**candidate(),'approved':True},{**candidate(),'source_ids':['invented-law']}])
def test_forged_candidate_fields_and_sources_rejected(env,result):
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    assert submit(c,e,task,lease,tokens[0],result).status_code==422
    assert latest(c,e)['agent_tasks'][0]['status']=='claimed'


def test_owner_fencing_even_with_same_name(env):
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    assert submit(c,e,task,lease,tokens[1]).status_code==403
    assert read_context(c,e,task,tokens[1]).status_code==403


def test_fact_change_rejects_old_candidate(env):
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0]);cur=latest(c,e)
    r=c.patch('/api/events/'+e['id'],json={'expected_revision':cur['revision'],'summary':'模拟事实变更'})
    assert r.status_code==200
    assert latest(c,e)['agent_tasks'][0]['status']=='stale'
    assert submit(c,e,task,lease,tokens[0]).status_code==409


def test_missing_facts_cannot_be_hidden_by_host(env):
    c,tokens,_,_=env;e=event(c,'chinext-related-01');task,lease=claimed(c,e,tokens[0])
    assert submit(c,e,task,lease,tokens[0]).status_code==200
    r=post(c,e,f"agent-tasks/{task['id']}/adopt")
    assert r.status_code==409,r.text
    assert latest(c,e)['assessment'] is None
    assert 'fact_source_mismatch' in {i['code'] for i in r.json()['detail']['gate']['issues']}
    assert advance(c,e,'assessment').status_code==409


def test_conflict_is_visible_and_requires_review(env):
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    assert submit(c,e,task,lease,tokens[0],{**candidate(),'status':'no_disclosure'}).status_code==200
    r=post(c,e,f"agent-tasks/{task['id']}/adopt")
    assert r.status_code==409,r.text
    assert latest(c,e)['assessment'] is None
    assert latest(c,e)['agent_tasks'][-1]['result']['status']=='no_disclosure'
    assert advance(c,e,'assessment').status_code==409


def test_cancel_and_late_submit(env):
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    r=post(c,e,f"agent-tasks/{task['id']}/finish",status='cancelled',reason='模拟用户取消')
    assert r.status_code==200
    assert submit(c,e,task,lease,tokens[0]).status_code==409


def test_expired_claim_reassigned_old_owner_cannot_write(env,monkeypatch):
    c,tokens,_,_=env;e=event(c);task,old=claimed(c,e,tokens[0]);clock=time.time()
    monkeypatch.setattr('backend.agent_tasks.time.time',lambda:clock+1000)
    assert latest(c,e)['agent_tasks'][0]['status']=='expired'
    r=post(c,e,f"agent-tasks/{task['id']}/claim",tokens[1],host_family='workbuddy',host_run_ref='synthetic-second-host')
    assert r.status_code==200 and r.json()['claim_id']!=old['claim_id']
    assert submit(c,e,task,old,tokens[0]).status_code==403


def test_request_retry_and_duplicate_active_task(env):
    c,tokens,_,_=env;e=event(c)
    body={'expected_revision':e['revision'],'request_id':str(uuid4()),'stage':'assessment','instruction':'测试'}
    path=f"/api/events/{e['id']}/agent-tasks"
    first=invoke(c,tokens[0],'task.request',{'event_id':e['id'],**body});second=invoke(c,tokens[0],'task.request',{'event_id':e['id'],**body})
    assert first.json()==second.json()
    assert len(latest(c,e)['agent_tasks'])==1
    assert post(c,e,'agent-tasks',stage='assessment',instruction='重复任务').status_code==409


def test_cross_event_and_template_change(env):
    c,tokens,root,_=env;e=event(c);other=event(c);task,lease=claimed(c,e,tokens[0])
    assert read_context(c,other,task,tokens[0]).status_code==404
    path=root/'templates/boards/chinext/manifest.json';v=json.loads(path.read_text());v[0]['version']='changed';path.write_text(json.dumps(v))
    assert latest(c,e)['agent_tasks'][0]['status']=='claimed'
    assert submit(c,e,task,lease,tokens[0]).status_code==200


def test_plan_and_draft_tasks_preserve_current_until_adopted(env):
    from conftest import ready_layout
    ready_layout(env[2])
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    assert submit(c,e,task,lease,tokens[0]).status_code==200
    post(c,e,f"agent-tasks/{task['id']}/adopt");advance(c,e,'assessment')
    assert confirm_stage(c,e,'assessment','prepare_mandatory').status_code==200
    task,lease=claimed(c,e,tokens[0],'plan')
    ctx=read_context(c,e,task,tokens[0]).json()
    plan=plan_candidate(ctx);items=plan['items']
    assert submit(c,e,task,lease,tokens[0],{'items':items[:1]}).status_code==422
    assert submit(c,e,task,lease,tokens[0],plan).status_code==200
    assert latest(c,e)['plan'] is None
    assert post(c,e,f"agent-tasks/{task['id']}/adopt").status_code==200
    assert advance(c,e,'plan').status_code==200
    assert confirm_stage(c,e,'plan').status_code==200
    approve_template(c,e,tokens[0],ctx,plan)
    task,lease=claimed(c,e,tokens[0],'draft')
    result={'template_id':ctx['templates'][0]['id'],'text':'证券代码：000000 证券简称：模拟公司 主办券商：模拟券商 公告编号：模拟001\n'+'\n'.join(i['title']+'\n模拟段落。' for i in items)}
    result['requirement_map']={r['requirement_id']:'模拟段落。' for r in plan['requirements']}
    assert submit(c,e,task,lease,tokens[0],result).status_code==200
    assert latest(c,e)['draft'] is None
    r=post(c,e,f"agent-tasks/{task['id']}/adopt");assert r.status_code==200,r.text
    assert r.json()['draft']['template_sha256']
    assert advance(c,e,'draft').status_code==200
    assert latest(c,e)['stage']=='draft_verified'


def test_restart_preserves_handoff_and_no_backend_model(env):
    c,tokens,root,config=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    app=create_app(root/'var',root,config,legacy_test_mode=True)
    with TestClient(app) as restarted:
        r=invoke(restarted,tokens[0],'task.list',{})
        assert r.status_code==200 and r.json()[0]['id']==task['id']
        meta=restarted.get('/api/meta').json()
        assert meta['mode']=='pi_agent_harness'
        assert meta['ai_execution']['backend_model'] is False
        assert meta['ai_execution']['backend_agent_runtime'] is True


def test_heartbeat_and_explicit_failure(env,monkeypatch):
    c,tokens,_,_=env;e=event(c);task,lease=claimed(c,e,tokens[0]);clock=time.time()
    monkeypatch.setattr('backend.agent_tasks.time.time',lambda:clock+100)
    r=post(c,e,f"agent-tasks/{task['id']}/heartbeat",tokens[0],claim_id=lease['claim_id'])
    assert r.status_code==200 and r.json()['lease_until']>lease['lease_until']
    r=post(c,e,f"agent-tasks/{task['id']}/finish",tokens[0],claim_id=lease['claim_id'],status='failed',reason='模拟宿主中断')
    assert r.status_code==200 and r.json()['agent_tasks'][0]['status']=='failed'
    assert submit(c,e,task,lease,tokens[0]).status_code==409


def test_candidate_citations_remain_frozen_after_source_change(env):
    c,tokens,root,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    assert submit(c,e,task,lease,tokens[0]).status_code==200
    old=latest(c,e)['agent_tasks'][0]['candidate_sources'][0]['text']
    p=root/'data/public/boards/chinext/catalog.json';catalog=json.loads(p.read_text())
    next(s for s in catalog['sources'] if s['id']=='szse-chinext-2026-4.1.7')['text']='测试修改后的条文'
    p.write_text(json.dumps(catalog))
    task_view=latest(c,e)['agent_tasks'][0]
    assert task_view['status']=='stale'
    assert task_view['candidate_sources'][0]['text']==old


def test_agent_cannot_bypass_candidate_inbox_or_web_claim(env):
    c,tokens,_,_=env;e=event(c);task=request_task(c,e)
    assert post(c,e,f"agent-tasks/{task['id']}/claim",host_family='codex',host_run_ref='fake-web-host').status_code==404
    assert c.get(f"/api/events/{e['id']}/agent-tasks/{task['id']}/context").status_code==404
    r=c.patch('/api/events/'+e['id']+'/draft',headers=tokens[0],json={'expected_revision':latest(c,e)['revision'],'text':'绕过候选'})
    assert r.status_code==410
