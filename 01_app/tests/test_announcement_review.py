import json
import threading
import time
from pathlib import Path
import pytest
from fastapi import HTTPException
from backend import announcement_review as review, announcement_history as history, announcement_tags as tags
from backend.pi_runtime import PiRuntime
from test_announcement_tags import make_catalog


def runtime(tmp_path,monkeypatch,runner):
    monkeypatch.setenv('DISCLOSURE_CLASSIFICATION_TEST','not-real-key')
    config={'models':[{'key':'test','label':'Test','id':'test-model','provider':'fixture','api':'openai-completions','enabled':True,
        'baseUrl':'http://127.0.0.1:1','api_key_env':'DISCLOSURE_CLASSIFICATION_TEST','contextWindow':200000,'maxTokens':4096}], 'routes':{'default':'test'}}
    folder=tmp_path/'var';folder.mkdir(exist_ok=True)
    (tmp_path/'data/public/boards/chinext').mkdir(parents=True,exist_ok=True)
    return PiRuntime(tmp_path,folder,lambda *a:None,config=config,runner=runner)


def wait(rt,rid):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        result=rt.store.run(rid)
        if result['status'] not in ('accepted','running','cancelling') and rid not in rt.active:return result
        time.sleep(.01)
    pytest.fail('Pi did not settle')


def valid_runner(packet,emit,bridge,stop):
    context=json.loads(packet['system'].split('\n',1)[1]);items=[]
    emit({'type':'started'})
    assert set(t['name'] for t in packet['tools'])=={'read_announcement_page','submit_candidate'}
    for d in context['documents']:
        items.append({'id':d['id'],'status':'classified','tags':['annual'],'forms':['full'],'page':1,'quote':d['title'],'reason':'文件标题明确为年度报告'})
    bridge('submit_candidate',{'result':{'items':items}});emit({'type':'done'})


def test_rule_unmeasured_must_use_pi_and_cache(tmp_path,monkeypatch):
    make_catalog(tmp_path,'300001',['2025年年度报告'])
    assert tags.classify(history.state(tmp_path,'chinext','300001')['items'][0])['rule_confidence'] is None
    rt=runtime(tmp_path,monkeypatch,valid_runner)
    result=review.enqueue(rt,'chinext','300001');done=wait(rt,result['run_id'])
    assert done['status']=='completed' and done['model']['key']=='test'
    row=history.state(tmp_path,'chinext','300001')['items'][0]
    assert tags.classify(row)['status']=='pi_reviewed'
    assert review.enqueue(rt,'chinext','300001')['status']=='not_required'
    assert tags.classify({**row,'document_sha256':'new'})['requires_pi']
    assert list((tmp_path/'data/client_announcements/chinext/300001/history').glob('*.json'))
    rt.close()


def test_no_result_not_success_and_cancel_dedup(tmp_path,monkeypatch):
    make_catalog(tmp_path,'300001',['2025年年度报告'])
    rt=runtime(tmp_path,monkeypatch,lambda p,e,b,s:e({'type':'done'}))
    first=review.enqueue(rt,'chinext','300001');assert wait(rt,first['run_id'])['status']=='incomplete'
    assert tags.classify(history.state(tmp_path,'chinext','300001')['items'][0])['requires_pi']
    entered=threading.Event()
    def block(p,e,b,s):entered.set();s.wait(5)
    rt.runner=block;again=review.enqueue(rt,'chinext','300001');assert entered.wait(3)
    assert review.enqueue(rt,'chinext','300001')['run_id']==again['run_id']
    rt.cancel(again['run_id']);assert wait(rt,again['run_id'])['status']=='cancelled'
    rt.close()


def test_cross_company_forged_quote_and_manual_protected(tmp_path,monkeypatch):
    make_catalog(tmp_path,'300001',['2025年年度报告']);make_catalog(tmp_path,'300002',['2025年年度报告'])
    def attempt(packet,emit,bridge,stop):
        context=json.loads(packet['system'].split('\n',1)[1]);d=context['documents'][0]
        with pytest.raises(HTTPException):bridge('read_announcement_page',{'id':'300002-0','page':1})
        with pytest.raises(HTTPException):bridge('submit_candidate',{'result':{'items':[{'id':d['id'],'status':'classified','tags':['annual'],'forms':['full'],'page':1,'quote':'伪造的依据','reason':'测试'}]}})
        valid_runner(packet,emit,bridge,stop)
    rt=runtime(tmp_path,monkeypatch,attempt);r=review.enqueue(rt,'chinext','300001');assert wait(rt,r['run_id'])['status']=='completed'
    assert 'classification_review' not in history.state(tmp_path,'chinext','300002')['items'][0]
    from backend.announcement_schedule import correction
    value=history.state(tmp_path,'chinext','300001')
    history.save(tmp_path,'chinext','300001',value['fingerprint'],lambda v:v['items'][0].update(classification_override=correction(v['items'][0],{'tags':['half_year'],'forms':['summary']})),'用户校正')
    assert review.enqueue(rt,'chinext','300001')['status']=='not_required'
    assert tags.classify(history.state(tmp_path,'chinext','300001')['items'][0])['status']=='manual'
    rt.close()


def test_batch_continues_and_reuses_session(tmp_path,monkeypatch):
    make_catalog(tmp_path,'300001',[f'{2020+n}年年度报告' for n in range(8)])
    rt=runtime(tmp_path,monkeypatch,valid_runner);r=review.enqueue(rt,'chinext','300001')
    wait(rt,r['run_id'])
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        rows=history.visible(history.state(tmp_path,'chinext','300001'))
        if all(tags.classify(row).get('status')=='pi_reviewed' for row in rows):break
        time.sleep(.02)
    assert all(tags.classify(row)['status']=='pi_reviewed' for row in rows)
    assert len({run['session_id'] for run in rt.store.runs()})==1
    rt.close()


def test_restart_marks_orphan_interrupted(tmp_path,monkeypatch):
    from uuid import uuid4
    make_catalog(tmp_path,'300001',['2025年年度报告'])
    rt=runtime(tmp_path,monkeypatch,valid_runner);rt.own()
    s=rt.store.create_session('chinext',None,'中断测试',str(uuid4()))
    run,_=rt.store.accept(s,{'stage':'classification','company_code':'300001','text':'测试','request_id':str(uuid4())},{'key':'test'})
    rt.close();restarted=runtime(tmp_path,monkeypatch,valid_runner);restarted.own()
    assert restarted.store.run(run['id'])['status']=='interrupted'
    assert tags.classify(history.state(tmp_path,'chinext','300001')['items'][0])['requires_pi']
    restarted.close()
