from internal_workflow import route as internal_route
from internal_workflow import context as read_context
"""V1: board boundaries through copied fixtures and the existing public API."""
import copy
import hashlib
import json
from collections import Counter
from uuid import uuid4
import pytest

from backend.domain import Seeds
from test_agent_tasks import env, event, claimed, submit, candidate, post, latest, advance, confirm_stage, plan_candidate


def test_all_library_entrypoints_require_an_available_board(env):
    client,tokens,_,_=env
    for path in ('/library/search','/library/items/szse-chinext-2026-4.1.7',
                 '/library/assets/szse-chinext-2026-4.1.7','/library/laws/manage','/knowledge','/templates'):
        assert client.get('/api'+path).status_code==422
        assert client.get('/api'+path,params={'board':'sse-main'}).status_code==409
        assert client.get('/api'+path,params={'board':'../base'}).status_code==422
    for operation,args in (('library.search',{}),('library.read',{'item_id':'szse-chinext-2026-4.1.7'}),
                           ('library.manage',{'collection':'laws'}),('templates.list',{})):
        assert internal_route(client,tokens[0],{'operation':operation,'args':args}).status_code==422
    assert client.post('/api/library/laws/update',json={'expected_fingerprint':'0'*64,'items':[{'id':'x'}]}).status_code==422
    boards=client.get('/api/meta').json()['boards']
    assert len(boards)==7 and {b['id'] for b in boards if b['available']}=={'chinext'}


def test_catalog_membership_and_profile_selection_are_board_specific(env):
    client,_,root,_=env
    catalog=Seeds(root,'chinext').catalog()
    assert catalog['sources'] and catalog['profiles'] and catalog['instruments'] and catalog['rules']
    assert all(row['library_board']=='chinext' for key in ('sources','cases','profiles','rules','templates') for row in catalog[key])
    assert all(p['layers']==['chinext'] for p in catalog['profiles'])
    for archived in ('base','innovation'):
        assert client.get('/api/meta',params={'board':archived}).status_code==409
        assert client.get('/api/library/search',params={'board':archived}).status_code==409
    e=event(client)
    wrong={**e['facts'],'disclosure_profile_id':'profile-neeq-board_resolution-1'}
    assert client.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'facts':wrong}).status_code==422
    assert latest(client,e)['facts']==e['facts']
    assert client.post('/api/events',json={'company_id':'demo-base','kind':e['kind'],'title':'隔离测试',
        'summary':'模拟输入','facts':e['facts'],'request_id':str(uuid4())}).status_code==422


@pytest.mark.knowledge_pack
def test_production_pack_registers_the_reviewed_board_library(env):
    """正式知识包的登记规模；默认运行只使用虚构样例，不承担数量断言。"""
    _,_,root,_=env
    catalog=Seeds(root,'chinext').catalog()
    assert len(catalog['sources'])==1033
    assert len(catalog['profiles'])==14


def test_archived_board_write_cannot_change_current_tasks(env):
    client,tokens,root,_=env;e=event(client)
    task,_=claimed(client,e,tokens[0]);before=latest(client,e)
    snapshot=client.get('/api/library/laws/manage',params={'board':'chinext'}).json()
    body={'expected_fingerprint':snapshot['fingerprint'],'items':[{'id':'foreign','title':'不能写入'}]}
    for board in ('base','innovation'):
        assert client.post('/api/library/laws/update',params={'board':board},json=body).status_code==409
        assert not (root/'data/public/boards'/board).exists()
    assert latest(client,e)==before
    assert latest(client,e)['agent_tasks'][-1]['status']=='claimed'


def test_foreign_board_record_is_rejected_before_write(env):
    client,_,root,_=env
    snapshot=client.get('/api/library/profiles/manage',params={'board':'chinext'}).json()
    foreign={**snapshot['items'][0],'library_board':'innovation','layers':['innovation']}
    p=root/'data/public/boards/chinext/profiles.json';before=p.read_bytes()
    response=client.post('/api/library/profiles/update',params={'board':'chinext'},json={
        'expected_fingerprint':snapshot['fingerprint'],'items':[foreign]})
    assert response.status_code==422
    assert p.read_bytes()==before


def test_misfiled_board_manifest_is_not_silently_read(env):
    client,_,root,_=env
    path=root/'data/public/boards/chinext/profiles.json'
    rows=json.loads(path.read_text());rows[0]['library_board']='innovation';path.write_text(json.dumps(rows))
    for endpoint in ('/api/meta','/api/library/search','/api/templates','/api/library/profiles/manage'):
        assert client.get(endpoint,params={'board':'chinext'}).status_code==409
    assert client.post('/api/library/profiles/update',params={'board':'chinext'},json={
        'expected_fingerprint':hashlib.sha256(path.read_bytes()).hexdigest(),
        'items':[{**rows[0],'library_board':'chinext','layers':['chinext']}]}).status_code==409


def test_chinext_task_flow_keeps_pending_evidence_and_blocks_unreviewed_layout(env):
    client,tokens,root,_=env;e=event(client,'chinext-board-01')
    task,lease=claimed(client,e,tokens[0])
    context=read_context(client,e,task,tokens[0]).json()
    assert context['board']=='chinext' and context['sources'] and context['case_candidates'] and not context['cases']
    assert all(s['library_board']=='chinext' for s in context['sources'])
    assert all(c['verification_status']=='imported_source_unverified' for c in context['case_candidates'])
    assert all(t['profile_id'].startswith('profile-chinext-') for t in context['templates'])
    assert 'szse.cn' in context['verification_gate']['next_action']['official_domains']
    foreign=candidate();foreign['source_ids']=['neeq-general-2025-a30']
    assert submit(client,e,task,lease,tokens[0],foreign).status_code==422
    # Replacing only source_ids left the NEEQ quote, locator and September date
    # in this June Chinext scenario. Build a board-bound synthetic chain instead.
    source=next(row for row in context['sources'] if row['id']=='szse-chinext-2026-5.1.1')
    value={'status':'disclose','summary':'模拟董事会通过重大融资事项，按已给事实建议披露。',
           'reasons':['上市规则5.1.1与模拟重大事项输入对应。'],'missing':[],
           'source_ids':[source['id']],'limitations':['隔离接口测试，不是现实法律验收。'],
           'assessment_as_of':e['facts']['event_date'],
           'facts':[{'key':'contains_disclosable_information','value':True,'status':'user_statement',
                     'source_ref':'facts.contains_disclosable_information','observed_at':e['facts']['event_date']}],
           'matters':[{'matter_id':'chinext-simulated-matter','event_types':['board_resolution'],
               'subject':'创业板模拟公司董事会','stage':'会议结束','duty_status':'mandatory',
               'timing_status':'triggered','trigger_events':['董事会通过模拟重大融资事项'],
               'deadline_basis':[source['id']],
               'reasoning_items':[{'source_id':source['id'],'locator':'5.1.1',
                   'quote':'及时、公平地披露所有可能对公司股票及其衍生品种交易价格或者投资决策产生较大影响的信息或事项',
                   'condition':'输入已声明含需披露的重大信息','fact_keys':['contains_disclosable_information'],
                   'application':'仅验证本板块条款和模拟已给事实的依据链，不代替专业判断。','outcome':'established'}]}]}
    submitted=submit(client,e,task,lease,tokens[0],value)
    assert submitted.status_code==200,submitted.text
    adopted=post(client,e,f"agent-tasks/{task['id']}/adopt",tokens[0]);assert adopted.status_code==200,adopted.text
    assert advance(client,e,'assessment').status_code==200
    assert confirm_stage(client,e,'assessment','prepare_mandatory').status_code==200
    task,lease=claimed(client,e,tokens[0],'plan')
    context=read_context(client,e,task,tokens[0]).json()
    plan=plan_candidate(context)
    for row in plan['items']+plan['documents']+plan['requirements']:
        row['source_ids']=[source['id']]
        if 'fact_keys' in row:row['fact_keys']=['contains_disclosable_information']
    invalid=copy.deepcopy(plan);invalid['items'][0]['source_ids']=[context['case_candidates'][0]['id']]
    assert submit(client,e,task,lease,tokens[0],invalid).status_code==422
    assert submit(client,e,task,lease,tokens[0],plan).status_code==200
    assert post(client,e,f"agent-tasks/{task['id']}/adopt",tokens[0]).status_code==200
    assert advance(client,e,'plan').status_code==200
    assert confirm_stage(client,e,'plan').status_code==200
    # The current workflow checks imported layout at template adoption, before
    # drafting. Keep that earlier barrier rather than fabricate an approved layout.
    task,lease=claimed(client,e,tokens[0],'template')
    template={'template_id':context['templates'][0]['id'],
              'requirement_map':{r['requirement_id']:r['section_id'] for r in plan['requirements']}}
    assert submit(client,e,task,lease,tokens[0],template).status_code==200
    blocked=post(client,e,f"agent-tasks/{task['id']}/adopt",tokens[0])
    assert blocked.status_code==409
    assert 'layout_scope_review_required' in {i['code'] for i in blocked.json()['detail']['gate']['issues']}
    assert latest(client,e).get('template') is None
    assert latest(client,e)['draft'] is None


def test_imported_candidate_has_readable_text_without_fabricated_original(env):
    client,_,root,_=env
    case=Seeds(root,'chinext').catalog()['cases'][0]
    response=client.get('/api/library/items/'+case['id'],params={'board':'chinext','page':1})
    assert response.status_code==200 and response.json()['pages']
    assert response.json()['source_kind']=='imported_case_candidate'
    assert response.json()['text_completeness']=='imported_text_unverified'
    assert client.get('/api/library/assets/'+case['id'],params={'board':'chinext'}).status_code==404
    assert client.get('/api/library/items/'+case['id'],params={'board':'innovation'}).status_code==409
    assert client.get('/api/library/items/'+case['id'],params={'board':'chinext','page':999}).status_code==404


def test_templates_have_independent_manifests_and_imported_asset_bytes(env):
    _,_,root,_=env
    receipt=json.loads((root/'data/public/boards/import_receipt.json').read_text())
    for asset in receipt['assets']:
        assert hashlib.sha256((root/asset['target']).read_bytes()).hexdigest()==asset['sha256']
    path=root/'templates/boards/chinext/manifest.json';before=Seeds(root,'chinext').fingerprint()
    rows=json.loads(path.read_text());rows[0]['version']='isolated-test';path.write_text(json.dumps(rows))
    assert Seeds(root,'chinext').fingerprint()!=before
    assert all('/imports/chinext/' in str(root/'templates'/t['file']) for t in Seeds(root,'chinext').templates())
    assert not (root/'templates/boards/innovation').exists()
