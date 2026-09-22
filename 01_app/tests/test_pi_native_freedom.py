"""User-requested Pi freedom, with object/scope and cancellation still enforced."""
import json
import queue
import threading
import time
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from backend.pi_runtime import PiRuntime
from backend.pi_tool_dispatch import ToolDispatch,READ_TOOLS
from backend import semantic_review,document_runtime,pi_subprocess
from test_pi_runtime import client,settled
from test_document_runtime import request,draft,readiness,reviewed


def test_domain_tools_do_not_change_with_stage_or_preflight(client):
    _,runtime,_=client
    stages=('chat','assessment','plan','template','draft','word','document','announcement')
    surfaces=[{t['name'] for t in runtime.tools(stage,{'production_allowed':False})} for stage in stages]
    assert all(surface==surfaces[0] for surface in surfaces)
    assert {'make_word','save_announcement','submit_candidate','submit_consultation','read_document_template'}<=surfaces[0]
    from backend.knowledge_ops import tools
    assert {t['name'] for t in tools('query')}=={t['name'] for t in tools('delete')}=={t['name'] for t in tools('template')}
    assert all(name.startswith('knowledge_') for name in {t['name'] for t in tools()})


def test_real_python_transport_dispatches_two_reads_before_waiting(monkeypatch):
    barrier=threading.Barrier(2);returned=[];events=[]
    class Session:
        returncode=0
        def __init__(self,*a,**kw):
            self.process=SimpleNamespace(pid=123);self.lines=queue.Queue();self.first=True;self.results=[]
        def send(self,value):
            if self.first:
                self.first=False
                for identity in ('a','b'):self.lines.put(json.dumps({'type':'tool_call','id':identity,'name':'read_library','args':{'item_id':identity}}))
            else:
                self.results.append(value)
                if len(self.results)==2:self.lines.put(json.dumps({'type':'done'}))
        def read(self):return self.lines.get(timeout=.01)
        def wait(self):pass
        def close(self):pass
    monkeypatch.setattr(pi_subprocess,'Session',Session)
    runtime=PiRuntime.__new__(PiRuntime)
    from pathlib import Path
    runtime.code_root=Path(__file__).resolve().parents[1]
    runtime.lock=threading.RLock();runtime.active={'r':{}}
    runtime.trace=lambda *args:events.append(args)
    runtime.store=SimpleNamespace(update=lambda *a,**kw:None)
    runtime.finish_interrupted_call=lambda rid:None
    runtime.add_timing=lambda *a:None
    def bridge(name,args):
        barrier.wait(timeout=2);returned.append(args['item_id']);return {'data':args}
    runtime.process('r',{'apiKey':'fake'},lambda item:None,bridge,threading.Event())
    assert set(returned)=={'a','b'}
    assert len([row for row in events if row[1]=='tool_returned'])==2


def test_parallel_mutations_are_atomic_and_queued_work_respects_cancel():
    stop=threading.Event();entered=threading.Event();release=threading.Event();calls=[]
    def bridge(name,args):
        calls.append(name);entered.set();release.wait(timeout=2);return {'data':{}}
    dispatch=ToolDispatch(bridge,stop)
    try:
        dispatch.submit({'id':'first','name':'save_announcement','args':{}})
        assert entered.wait(1)
        dispatch.submit({'id':'second','name':'make_word','args':{}})
        stop.set();release.set()
    finally:dispatch.close()
    assert calls==['save_announcement']


def test_reviewer_accepts_more_than_40_and_uses_selected_budget_and_research(client,monkeypatch):
    _,runtime,_=client;observed=[];lookups=[]
    items=[{'item_id':str(i),'value':'fixture','quote':'fixture'} for i in range(81)]
    model=runtime.settings.resolve_model('fixture-a')
    model={**model,'reasoning_effort':'high','maxTokens':16000}
    monkeypatch.setattr(runtime.settings,'resolve_model',lambda key:model)
    monkeypatch.setattr(runtime,'bridge',lambda rid,name,args,stop:lookups.append(name) or {'data':{'text':'fixture'}})
    def runner(packet,emit,bridge,stop):
        observed.append(packet)
        bridge('knowledge_web_search',{'query':'fixture public source'})
        with pytest.raises(HTTPException):bridge('make_word',{})
        values=[{'item_id':r['item_id'],'verdict':'supported','reason':'fixture'} for r in items]
        emit({'type':'assistant','stopReason':'stop','text':json.dumps({'verdicts':values})})
    runtime.runner=runner
    result,source=runtime.semantic_review('fixture-review',{'stage':'chat','model':{'key':'fixture-a'}},items,threading.Event())
    assert len(result)==81 and source=='reviewed' and len(observed)==1
    assert observed[0]['maxTokens']==16000 and observed[0]['reasoning_effort']=='high'
    assert lookups==['knowledge_web_search']
    assert all(t['name'] in READ_TOOLS|{'knowledge_download'} for t in observed[0]['tools'])


def test_consult_route_can_make_requested_word_after_more_than_three_failures(client,monkeypatch):
    c,runtime,_=client;s=runtime.store.create_session('chinext','','tool-domain',str(uuid4()))
    real=document_runtime.make_word;attempts=[]
    def transient(*a,**kw):
        attempts.append(1)
        if len(attempts)<=5:raise HTTPException(422,'模拟可修正的制文失败')
        return real(*a,**kw)
    monkeypatch.setattr(document_runtime,'make_word',transient)
    def provider(packet,emit,bridge,stop):
        bridge('load_business_skill',{'skill_id':'disclosure-consultation'})
        bridge('read_document_context',{})
        doc=draft('跨阶段制文')
        opened=bridge('assess_document_readiness',{'output':'word','documents':[readiness(doc)],'request_quote':packet['prompt'],'decision':'assess'})
        assert opened.get('next_context')
        for _ in range(5):
            with pytest.raises(HTTPException):bridge('make_word',{'documents':[doc]})
        assert bridge('make_word',{'documents':[doc]})['data']['documents']
        emit({'type':'assistant','phase':'answer','stopReason':'stop','text':'本轮测试操作已结束，以登记回执为准。'});emit({'type':'done'})
    runtime.runner=reviewed(provider)
    result=settled(c,request(c,s,'请把分析制作成 Word'),timeout=45)
    assert result['run']['status']=='completed',result['run'].get('reason')
    assert result['run']['document_attempts']==6 and len(attempts)==6


def test_parallel_research_cannot_cache_old_result_under_new_version():
    from backend.research_session import ResearchSession
    research=ResearchSession();started=threading.Event();release=threading.Event()
    def old():
        started.set();assert release.wait(2);return {'items':[{'id':'old'}]}
    worker=threading.Thread(target=lambda:research.read('search',{},'old-version',old))
    worker.start();assert started.wait(1)
    fresh=research.read('search',{},'new-version',lambda:{'items':[{'id':'new'}]})
    release.set();worker.join(2);assert not worker.is_alive()
    cached=research.read('search',{},'new-version',lambda:pytest.fail('new result was lost'))
    assert cached['items']==fresh['items'] and cached['cache_hit']


def test_word_tool_availability_does_not_turn_text_consent_into_word_consent(client):
    c,runtime,_=client;s=runtime.store.create_session('chinext','','output-object',str(uuid4()))
    def provider(packet,emit,bridge,stop):
        bridge('load_business_skill',{'skill_id':'disclosure-announcement-drafting'})
        bridge('read_document_context',{})
        doc=draft('模拟公告',kind='announcement')
        opened=bridge('assess_document_readiness',{'output':'text','documents':[readiness(doc)],'request_quote':packet['prompt'],'decision':'assess'})
        assert opened.get('next_context')
        held=bridge('make_word',{'documents':[doc]})
        assert 'next_context' in held
        rid=runtime.store.runs(s['id'])[0]['id']
        assert runtime.store.run(rid)['document_preflight']['status']=='output_changed'
        assert not runtime.store.run(rid).get('documents')
        emit({'type':'assistant','phase':'answer','stopReason':'stop','text':'本轮测试操作已结束，以登记回执为准。'});emit({'type':'done'})
    runtime.runner=reviewed(provider)
    result=settled(c,request(c,s,'请起草一份模拟公告正文'),timeout=45)
    assert result['run']['status']=='incomplete',result['run'].get('reason')
