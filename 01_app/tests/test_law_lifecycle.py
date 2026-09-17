"""法规生命周期：月检记录、真实变更与业务版本指纹的契约。

月检到期、失败或仅刷新核验日期都不能阻断或失效制稿；法规正文只由知识库
既有接纳流程改写。
"""
import copy
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from backend import gates, law_lifecycle
from backend.domain import Seeds
from conftest import KNOWLEDGE

ROOT=Path(__file__).resolve().parents[1]
BOARD='chinext'


def board_root(tmp_path,sources):
    board=tmp_path/'data/public/boards'/BOARD
    board.mkdir(parents=True)
    (board/'catalog.json').write_text(json.dumps({'board':BOARD,'sources':sources},ensure_ascii=False))
    return tmp_path


def source(**over):
    row={'id':'src-x-1','instrument_id':'inst-x','title':'测试规则','article':'第一条',
         'text':'第一条规定了测试义务。','source_kind':'official_rule','layers':[BOARD],'library_board':BOARD,
         'effective_from':'2026-01-01','as_of':'2026-09-08','url':'https://www.szse.cn/test'}
    row.update(over);return row


def fake_fetch(payload=b'<html>rule text v1</html>'):
    calls=[]
    def fetch(url):calls.append(url);return payload,'text/html','https://www.szse.cn/test'
    return fetch,calls


def test_state_derives_instrument_and_marks_unscheduled(tmp_path):
    root=board_root(tmp_path,[source(),source(id='src-x-2',article='第二条')])
    state=law_lifecycle.state(root,BOARD,today=date(2026,9,16))
    assert state['summary']=={'total':1,'current':0,'unscheduled':1,'changed':0,'failed':0,'due':1,'pending_changes':0}
    row=state['records'][0]
    assert row['instrument_id']=='inst-x' and row['article_count']==2
    assert row['status']=='unscheduled' and row['due'] is True


def test_monthly_check_records_baseline_without_touching_law_text(tmp_path):
    root=board_root(tmp_path,[source()])
    fetch,calls=fake_fetch()
    first=law_lifecycle.run(root,BOARD,fetch=fetch,today=date(2026,9,16))
    assert first['current']==['inst-x'] and first['changed']==[] and first['failed']==[]
    assert calls==['https://www.szse.cn/test']
    record=law_lifecycle.state(root,BOARD,today=date(2026,9,16))['records'][0]
    assert record['status']=='current' and record['next_check_at']=='2026-10-16' and record['due'] is False
    assert '首次核验' in record['last_result']
    confirmed=law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],force=True,today=date(2026,9,17))['results'][0]
    assert '基线一致' in confirmed['detail']
    # 月检只登记核验记录，不改写法规正文
    assert json.loads((root/'data/public/boards'/BOARD/'catalog.json').read_text())['sources'][0]['text']=='第一条规定了测试义务。'


def test_not_due_is_skipped_until_forced(tmp_path):
    root=board_root(tmp_path,[source()])
    law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],today=date(2026,9,16))
    assert law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],today=date(2026,9,20))['count']==0
    forced=law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],force=True,today=date(2026,9,20))
    assert forced['count']==1 and forced['current']==['inst-x']


def test_dry_run_previews_without_writing(tmp_path):
    root=board_root(tmp_path,[source()])
    preview=law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],force=True,dry_run=True,today=date(2026,9,16))
    assert preview['count']==1 and preview['current']==['inst-x']
    assert not (root/'data/public/boards'/BOARD/law_lifecycle.STORE).exists()


def test_changed_bytes_raise_pending_change_without_accepting_new_version(tmp_path):
    root=board_root(tmp_path,[source()])
    law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],today=date(2026,9,16))
    changed=law_lifecycle.run(root,BOARD,fetch=fake_fetch(b'<html>rule text v2 revised</html>')[0],
                              force=True,today=date(2026,10,16))
    assert changed['changed']==['inst-x']
    record=law_lifecycle.state(root,BOARD,today=date(2026,10,17))['records'][0]
    assert record['status']=='changed' and record['due'] is False and record['next_check_at'] is None
    assert 'v2' in record['pending_change']['snapshot']
    assert record['pending_change']['previous_sha256']!=record['pending_change']['new_sha256']
    # 变化的官方原件不会自动成为法规正文；仍待在知识库核验后接纳
    assert json.loads((root/'data/public/boards'/BOARD/'catalog.json').read_text())['sources'][0]['text']=='第一条规定了测试义务。'


def test_failed_fetch_is_recorded_and_retried_next_day(tmp_path):
    root=board_root(tmp_path,[source()])
    def broken(url):raise RuntimeError('官方来源暂时无法连接')
    result=law_lifecycle.run(root,BOARD,fetch=broken,today=date(2026,9,16))
    assert result['failed']==['inst-x'] and result['current']==[]
    record=law_lifecycle.state(root,BOARD,today=date(2026,9,16))['records'][0]
    assert record['status']=='failed' and record['next_check_at']=='2026-09-17'
    assert record['due'] is True and record['needs_attention'] is True
    retry=law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],failed_only=True,today=date(2026,9,17))
    assert retry['current']==['inst-x']


def test_missing_official_url_is_a_recorded_failure_not_a_crash(tmp_path):
    root=board_root(tmp_path,[source(url=None)])
    result=law_lifecycle.run(root,BOARD,fetch=fake_fetch()[0],today=date(2026,9,16))
    assert result['failed']==['inst-x']
    assert '官方原文地址' in law_lifecycle.state(root,BOARD,today=date(2026,9,16))['records'][0]['last_result']


def test_gate_fingerprint_ignores_review_records_but_real_period_changes_still_block():
    catalog=Seeds(KNOWLEDGE).for_board(BOARD).catalog()
    event={'id':'e1','title':'模拟事项','company_id':'c1','company_name':'测试公司','layer':BOARD,
           'kind':'unclassified','intake_mode':'open','output_mode':'text','created_at':'2026-09-15T00:00:00+00:00',
           'facts':{'event_date':'2026-09-15','assessment_as_of':'2026-09-15'},
           'law_bindings':{'szse-chinext-2026-8.7.2':'szse-chinext-2026-8.7.2'}}
    before=gates.fingerprint(event,catalog,'assessment')
    refreshed=copy.deepcopy(catalog)
    for row in refreshed['sources']:row['as_of']='2026-12-31'
    assert gates.fingerprint(event,refreshed,'assessment')==before
    stale=copy.deepcopy(catalog)
    for row in stale['sources']:row['as_of']='2026-09-08'
    receipt=gates.evaluate(event,Seeds(KNOWLEDGE),'assessment',catalog=stale,require_result=False)
    assert 'law_freshness_unconfirmed' not in {i['code'] for i in receipt['issues']}
    assert any(w['code']=='law_review_due' for w in receipt['warnings'])
    assert receipt['status']!='BLOCKED'
    past=copy.deepcopy(event);past['facts']={'event_date':'2024-01-01','assessment_as_of':'2024-01-01'}
    blocked=gates.evaluate(past,Seeds(KNOWLEDGE),'assessment',catalog=stale,require_result=False)
    codes={i['code'] for i in blocked['issues']}
    assert blocked['status']=='BLOCKED' and 'law_out_of_period' in codes


def test_fixed_monthly_entry_is_callable_standalone(tmp_path):
    root=board_root(tmp_path,[source()])
    env={**os.environ,'PYTHONPATH':str(ROOT)}
    status=subprocess.run([sys.executable,str(ROOT/'scripts/law_lifecycle_check.py'),'--root',str(root),
                           '--board',BOARD,'--status'],capture_output=True,text=True,env=env,timeout=60)
    assert status.returncode==0,status.stderr
    data=json.loads(status.stdout)
    assert data['summary']['total']==1 and data['records'][0]['status']=='unscheduled'
    bad=subprocess.run([sys.executable,str(ROOT/'scripts/law_lifecycle_check.py'),'--root',str(root),
                        '--board','base','--status'],capture_output=True,text=True,env=env,timeout=60)
    assert bad.returncode==2 and json.loads(bad.stderr)['status']=='failed'
