"""法规生命周期核验：前端手动触发一次 Pi 运行，结论经后端固定路径登记。"""
import hashlib
import json
import shutil
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import law_lifecycle, public_sources
from backend.app import create_app

ROOT=Path(__file__).resolve().parents[1]
BOARD='chinext'
LAW='szse-chinext-listing-2026-verified'
OFFICIAL='https://www.szse.cn/mock-official'
CONFIG={'models':[{'key':'fixture-a','label':'离线模型 A','provider':'fixture','api':'openai-completions',
 'id':'offline-a','baseUrl':'http://127.0.0.1:1','api_key_env':'DISCLOSURE_TEST_KEY','enabled':True,
 'contextWindow':200000,'maxTokens':1024}]}


def page(payload=b'<html><body>mock official rule text v1</body></html>'):
    return payload,'text/html',OFFICIAL


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('DISCLOSURE_TEST_KEY','fixture-not-real-123456')
    monkeypatch.setattr(public_sources,'fetch',lambda url,search=False:page())
    # 隔离副本：核验会写入 life_lifecycle.json 与原件事务目录，绝不触及真实工作区。
    from conftest import KNOWLEDGE, seed_tree
    seed_tree(KNOWLEDGE/'data/public/boards',tmp_path/'data/public/boards')
    # 每次从空的核验记录开始，避免真实工作区里已有的核验基线影响断言。
    baseline=tmp_path/'data/public/boards'/BOARD/law_lifecycle.STORE
    if baseline.exists():baseline.unlink()
    app=create_app(tmp_path/'var',tmp_path,{'allowed_hosts':['testserver']},pi_config=CONFIG,pi_runner=lambda *a:None)
    with TestClient(app) as c:
        session=c.get('/api/session').json();c.headers.update({'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']})
        yield c,app.state.pi_runtime,tmp_path


def trigger(c,instrument=LAW,**over):
    body={'board':BOARD,'instrument_id':instrument,'model_key':'fixture-a',**over}
    return c.post('/api/law-lifecycle/run',json=body)


def wait(c,runtime,rid,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        out=c.get('/api/chat/runs/'+rid).json()
        if out['run']['status'] not in ('accepted','running','cancelling'):return out
        time.sleep(.05)
    pytest.fail('lifecycle run did not settle')


def runner_submit(download=True,outcome='unchanged',detail='官方原文与登记正文一致，未检出修订。',extra=None,expect_error=None):
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'})
        assert packet.get('stage')=='lifecycle'
        names=[row['name'] for row in packet['tools']]
        assert 'lifecycle_submit' in names and 'knowledge_download' in names and 'knowledge_propose' not in names
        assert packet['history']==[]
        payload={'instrument_id':LAW,'outcome':outcome,'detail':detail,'official_url':OFFICIAL}
        if download:
            receipt=bridge('knowledge_download',{'url':OFFICIAL})['data']
            payload['download_id']=receipt['download_id']
        payload.update(extra or {})
        try:reply=bridge('lifecycle_submit',payload)
        except Exception as exc:
            if expect_error:
                emit({'type':'assistant','message':0,'phase':'answer','stopReason':'stop','text':str(getattr(exc,'detail',exc))})
                emit({'type':'done'});return
            raise
        assert reply['terminate'] is True
        emit({'type':'done'})
    return runner


def test_page_trigger_reuses_one_session_and_registers_unchanged(client):
    c,runtime,root=client
    runtime.runner=runner_submit()
    first=trigger(c)
    assert first.status_code==200,first.text
    info=first.json()
    out=wait(c,runtime,info['run_id'])
    assert out['run']['status']=='completed',out['run']
    saved=runtime.store.run(info['run_id'])
    assert saved['lifecycle_result']['status']=='current' and saved['lifecycle_result']['method']=='pi-runtime'
    record=law_lifecycle.load(root,BOARD)['records'][LAW]
    assert record['status']=='current' and record['method']=='pi-runtime'
    assert record['evidence']['download_id'] and record['evidence']['sha256']==hashlib.sha256(page()[0]).hexdigest()
    assert record['next_check_at']==(date.today()+timedelta(days=law_lifecycle.CHECK_INTERVAL_DAYS)).isoformat()
    assert not record.get('pending_change')
    # 第二次触发复用同一个“法规生命周期”会话，不新建
    second=trigger(c)
    assert second.status_code==200
    assert second.json()['session_id']==info['session_id']
    assert len([s for s in runtime.store.sessions(BOARD,'',False) if s['title']==law_lifecycle.SESSION_TITLE])==1


def test_law_text_is_never_rewritten_and_baseline_mismatch_is_rejected(client,monkeypatch):
    c,runtime,root=client
    runtime.runner=runner_submit()
    wait(c,runtime,trigger(c).json()['run_id'])
    catalog_path=root/'data/public/boards'/BOARD/'catalog.json'
    before=json.loads(catalog_path.read_text())
    monkeypatch.setattr(public_sources,'fetch',lambda url,search=False:page(b'<html>official rule text v2 revised</html>'))
    runtime.runner=runner_submit(outcome='unchanged',expect_error='baseline')
    out=wait(c,runtime,trigger(c).json()['run_id'])
    assert out['run']['status']=='incomplete'          # 模型收到拒绝后本轮未登记
    assert json.loads(catalog_path.read_text())==before  # 法规正文未被改写
    assert law_lifecycle.load(root,BOARD)['records'][LAW]['status']=='current'
    runtime.runner=runner_submit(outcome='changed',detail='官方原文条款编号与表述发生变化，需核对修订安排。')
    out=wait(c,runtime,trigger(c).json()['run_id'])
    assert out['run']['status']=='completed'
    record=law_lifecycle.load(root,BOARD)['records'][LAW]
    assert record['status']=='changed' and record['pending_change']['new_sha256']
    assert record['next_check_at'] is None and record['pending_change']['snapshot']
    assert json.loads(catalog_path.read_text())==before


def test_unavailable_is_recorded_without_evidence(client):
    c,runtime,root=client
    runtime.runner=runner_submit(download=False,outcome='unavailable',detail='官方来源暂时无法连接，本轮未取得原文。',extra={'official_url':None})
    out=wait(c,runtime,trigger(c).json()['run_id'])
    assert out['run']['status']=='completed'
    record=law_lifecycle.load(root,BOARD)['records'][LAW]
    assert record['status']=='failed' and '暂时无法连接' in record['last_result']
    assert record['next_check_at']==(date.today()+timedelta(days=1)).isoformat()


def test_submission_must_match_bound_law_and_schema(client):
    c,runtime,_=client
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'})
        for payload,expect in [({'instrument_id':'other-law','outcome':'unchanged','detail':'x'*20},403),
                               ({'instrument_id':LAW,'outcome':'unchanged'},422)]:
            try:
                bridge('lifecycle_submit',payload);raise AssertionError('应该被拒绝')
            except Exception as exc:
                assert getattr(exc,'status_code',None)==expect,getattr(exc,'detail',exc)
        emit({'type':'done'})
    runtime.runner=runner
    out=wait(c,runtime,trigger(c).json()['run_id'])
    assert out['run']['status']=='incomplete'
    assert law_lifecycle.load(client[2],BOARD)['records']=={}


def test_trigger_rejects_unknown_law(client):
    c,_,_=client
    assert trigger(c,instrument='no-such-law').status_code==404
