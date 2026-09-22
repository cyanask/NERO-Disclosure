"""Business-facing source list: factual access, version/scope isolation and no false coverage."""
import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
from backend.evidence_access import access
from backend.evidence_summary import build, journal
from backend.announcement_history import field_check_receipt
from backend.chat_store import ChatStore


LAW={'id':'law-a','title':'测试规则','article':'第十条','source_kind':'official_rule','sha256':'old','text':'条款全文'}
CASE={'id':'case-a','title':'甲公司交易公告案例','source_kind':'official_case','sha256':'case-version'}
RUN={'id':'r1','session_id':'s1','stage':'chat','status':'completed'}
def row(kind, body, rid='r1'): return {'run_id':rid,'kind':kind,'body':body}
def group(value, key): return next(g for g in value['groups'] if g['key']==key)


def test_search_and_context_are_not_read_or_cited_and_same_title_cases_stay_distinct():
    rows=[row('context_loaded',{'context':{'sources':[LAW]}}),
          row('tool_requested',{'id':'c','name':'library.search','args':{'collection':'cases'}}),
          row('tool_returned',{'id':'c','name':'library.search','result':{'collection':'cases','total':50,'items':[CASE,{**CASE,'id':'case-b'}]}})]
    result=build([RUN],rows)
    assert group(result,'laws')['items'][0]['states']==['provided']
    cases=group(result,'cases')['items']
    assert len(cases)==2 and all(r['states']==['searched'] for r in cases)
    assert not group(result,'history')['checks']


def test_success_dedup_citations_versions_and_round_scope():
    receipts=[row('evidence_access',access('read_library',{'item_id':'law-a'},LAW)),
              row('evidence_access',access('read_library',{'item_id':'law-a'},LAW)),
              row('result_snapshot',{'sources':[LAW],'result':{}}),
              row('evidence_access',access('read_library',{'item_id':'law-a'},{**LAW,'sha256':'new'}),'r2')]
    second={**RUN,'id':'r2'}
    result=build([second,RUN],receipts)
    sources=group(result,'laws')['items']
    assert len(sources)==2
    assert next(s for s in sources if s['sha256']=='old')['states']==['read','cited']
    assert next(s for s in sources if s['sha256']=='new')['states']==['read']
    one=build([second],receipts)
    assert len(group(one,'laws')['items'])==1
    assert group(one,'laws')['items'][0]['sha256']=='new'


def test_failures_empty_search_and_unconnected_remain_distinct():
    result=build([RUN],[row('evidence_access',access('search_library',{'collection':'cases'},{'items':[],'total':0})),
        row('evidence_access',access('search_library',{'collection':'laws'},failed=True)),
        row('evidence_access',access('search_library',{'collection':'client_history'},{'status':'not_connected','items':[]}))])
    assert group(result,'cases')['empty_search'] and not group(result,'cases')['failed']
    assert group(result,'laws')['failed'] and not group(result,'laws')['empty_search']
    assert group(result,'history')['unavailable'] and not group(result,'history')['searched']


def test_old_history_request_is_not_a_success_and_metadata_never_means_all_checked():
    rows=[row('model_tool_call',{'name':'read_library','args':{'item_id':'announcement-one'}}),
          row('context_loaded',{'context':{'announcement_schedule':{'items':[{'id':'announcement-one','title':'会议通知'}]}}})]
    result=build([RUN],rows)
    assert group(result,'history')['incomplete']
    assert not group(result,'history')['items'] and not group(result,'history')['checks']


def test_pending_requests_describe_specific_actions_across_libraries():
    rows=[row('knowledge_requested',{'name':'knowledge_history','args':{'query':'查询本公司历史公告库当前可检索范围、公告数量、时间表和目录索引'}}),
          row('model_tool_call',{'name':'search_library','args':{'collection':'laws','query':'关联交易'}}),
          row('tool_requested',{'id':'call','name':'library.search','args':{'collection':'laws','query':'关联交易'}})]
    result=build([RUN],rows)
    assert group(result,'history')['initiated_actions']==['已发起查询历史公告库的可检索范围、数量及目录']
    assert group(result,'laws')['initiated_actions']==['已发起查询法规库：关联交易']
    rows.append(row('tool_returned',{'id':'call','name':'library.search','result':{'collection':'laws','items':[],'total':0}}))
    assert not group(build([RUN],rows),'laws')['initiated_actions']
    rows.append(row('knowledge_returned',{'name':'knowledge_history','result':{'items':[],'total':0}}))
    assert not group(build([RUN],rows),'history')['incomplete']


def test_failed_request_is_not_pending_and_modern_receipt_closes_request():
    args={'collection':'cases','query':'担保'}
    rows=[row('model_tool_call',{'name':'search_library','args':args}),
          row('model_tool_failed',{'name':'search_library','error':'读取失败'})]
    result=build([RUN],rows)
    assert group(result,'cases')['failed'] and not group(result,'cases')['initiated_actions']
    history={'query':'年度报告'}
    rows=[row('knowledge_requested',{'name':'knowledge_history','args':history}),
          row('evidence_access',{**access('knowledge_history',history,{'items':[],'total':0}),'tool':'knowledge_history','request':history})]
    assert not group(build([RUN],rows),'history')['initiated_actions']


def test_article_expansion_and_page_reads_keep_actual_scope():
    law=access('read_library',{'item_id':'instrument'},{'id':'instrument','articles':[LAW]})
    assert law['category']=='laws' and law['items'][0]['article']=='第十条'
    item={'id':'announcement-one','title':'甲公司年度报告','page_count':300,'pages':[{'page':2,'text':'局部'}]}
    value=build([RUN],[row('evidence_access',access('read_library',{'item_id':item['id'],'page':2},item))])
    history=group(value,'history')
    assert history['items'][0]['pages']==[2] and not history['checks']


def test_actual_field_check_scope_not_full_text_or_all_public_history():
    history={'stock_code':'300001','fingerprint':'frozen','coverage':{'complete':False},'items':[{'id':'announcement-one','title':'甲公告'}]}
    assert not field_check_receipt({'draft':{'text':'未识别编号或会议'}},history)['performed']
    event={'draft':{'text':'公告编号：2026-001'}}
    check=field_check_receipt(event,history)
    assert check['performed'] and check['count']==1 and check['method']=='announcement_fields'
    result=build([RUN],[row('verification',{'history_check':check})])
    assert group(result,'history')['checks'][0]['coverage']['complete'] is False


def test_template_options_and_candidate_are_not_used():
    template={'id':'t1','name':'股东会公告模板','sha256':'v1'}
    base=[row('context_loaded',{'context':{'templates':[template]}}),
          row('result_snapshot',{'stage':'template','result':{'template_id':'t1'},'sources':[]})]
    assert group(build([RUN],base),'templates')['items'][0]['states']==['matched']
    saved=base+[row('documents_created',{'documents':[{'template_id':'t1','template_name':'股东会公告模板'}]})]
    assert 'used' in group(build([RUN],saved),'templates')['items'][0]['states']


def test_journal_filter_reads_all_pages_without_messages(tmp_path):
    store=ChatStore(tmp_path/'chat.db')
    for n in range(1005):store.append('r1','user',{'text':'不得进入依据汇总'})
    store.append('r1','evidence_access',access('read_library',{'item_id':'law-a'},LAW))
    store.append('r2','evidence_access',access('read_library',{'item_id':'law-a'},{**LAW,'title':'其他会话'}))
    rows=journal(store,['r1'])
    assert len(rows)==1 and rows[0]['kind']=='evidence_access'
    assert group(build([RUN],rows),'laws')['items'][0]['title']=='测试规则'


def test_evidence_api_company_board_run_scope_and_archives(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.evidence_api import mount
    store=ChatStore(tmp_path/'chat.db')
    a=store.create_session('chinext','','甲会话',str(uuid4()),'300001')
    b=store.create_session('chinext','','乙会话',str(uuid4()),'300002')
    def accept(s):
        r,_=store.accept(s,{'request_id':str(uuid4()),'stage':'chat','company_code':s['company_code']},{})
        store.update(r['id'],status='completed');return r
    ra,rb=accept(a),accept(b)
    store.append(ra['id'],'evidence_access',access('read_library',{'item_id':'law-a'},LAW))
    store.append(rb['id'],'evidence_access',access('read_library',{'item_id':'law-a'},{**LAW,'title':'乙独有'}))
    runtime=SimpleNamespace(store=store,session_company=lambda s:s['company_code'])
    app=FastAPI();mount(app,runtime,lambda r:None)
    with TestClient(app) as c:
        url=f"/api/chat/sessions/{a['id']}/evidence"
        query={'board':'chinext','company':'300001'}
        assert c.get(url,params=query).status_code==200
        assert c.get(url,params={**query,'company':'300002'}).status_code==403
        assert c.get(url,params={**query,'board':'innovation'}).status_code==409
        assert c.get(url,params={**query,'run_id':rb['id']}).status_code==404
        assert c.get(url,params={'board':'chinext'}).status_code==422
        data=c.get('/api/chat/evidence-sessions',params=query).json()
        assert [r['title'] for r in data['items']]==['甲会话']
        store.edit_session(a['id'],archived=True)
        assert not c.get('/api/chat/evidence-sessions',params=query).json()['items']
        assert c.get('/api/chat/evidence-sessions',params={**query,'archived':'true'}).json()['total']==1


def test_runtime_records_success_failure_and_cache_without_changing_tool_response():
    from backend.pi_runtime import PiRuntime
    saved=[]
    runtime=object.__new__(PiRuntime)
    runtime.store=SimpleNamespace(run=lambda rid:{})
    runtime.trace=lambda rid,kind,body:saved.append((kind,body))
    response={'data':{'collection':'laws','items':[LAW],'total':1,'cache_hit':True}}
    runtime._bridge=lambda *args:response
    assert runtime.bridge('r','search_library',{'collection':'laws'},None) is response
    assert saved[-1][1]['cache_hit'] is True
    def fail(*args):raise ValueError('failed')
    runtime._bridge=fail
    with pytest.raises(ValueError):runtime.bridge('r','search_library',{'collection':'laws'},None)
    assert saved[-1][1]['action']=='failed'
    with pytest.raises(ValueError,match='failed'):runtime.bridge('r','search_library',None,None)
