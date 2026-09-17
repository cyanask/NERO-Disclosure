from internal_workflow import context as read_context
import hashlib
import json
from pathlib import Path
from uuid import uuid4
import pytest
from test_agent_tasks import env,event,claimed,latest,post,advance,submit,candidate


def update_skill(root,stage):
    registry=root/'skills/registry.json';data=json.loads(registry.read_text());row=data['stages'][stage]
    p=root/row['path'];p.write_text(p.read_text()+'\n本次方法补充。\n');row['version']='1.0.1';row['sha256']=hashlib.sha256(p.read_bytes()).hexdigest();registry.write_text(json.dumps(data,ensure_ascii=False))


def test_project_skills_discovery_and_stage_context(env):
    c,tokens,root,_=env
    meta=c.get('/api/meta').json();assert len(meta['workflow']['stage_skills'])==4
    e=event(c);task,lease=claimed(c,e,tokens[0])
    ctx=read_context(c,e,task,tokens[0]).json()
    assert ctx['stage_skill']['id']=='disclosure-duty-assessment'
    assert ctx['stage_skill']['scope']=='project_only'
    assert ctx['stage_skill']['sha256']==hashlib.sha256(ctx['stage_skill']['instructions'].encode()).hexdigest()
    assert 'status' in ctx['result_schema']['properties'] and 'approved' not in ctx['result_schema']['properties']
    assert ctx['next_action']['claim_id']==lease['claim_id']
    assert 'instructions' not in str(latest(c,e)['agent_tasks'])
    update_skill(root,'plan')
    assert latest(c,e)['agent_tasks'][-1]['status']=='claimed'
    update_skill(root,'assessment')
    assert latest(c,e)['agent_tasks'][-1]['status']=='stale'
    assert submit(c,e,task,lease,tokens[0]).status_code==409


@pytest.mark.parametrize('bad', ['../README.md', '/tmp/foreign/SKILL.md'])
def test_skill_paths_cannot_escape_project(env,bad):
    c,tokens,root,_=env;e=event(c)
    p=root/'skills/registry.json';d=json.loads(p.read_text());d['stages']['assessment']['path']=bad;p.write_text(json.dumps(d))
    assert post(c,e,'agent-tasks',stage='assessment',instruction='test').status_code==409


def test_missing_or_changed_skill_fails_closed(env):
    c,tokens,root,_=env;e=event(c)
    p=root/'skills/disclosure-duty-assessment/SKILL.md';p.write_text('Changed without registry acceptance')
    assert post(c,e,'agent-tasks',stage='assessment',instruction='test').status_code==409


def test_whole_skill_directory_cannot_redirect_outside_project(tmp_path):
    from backend.stage_skills import get
    from fastapi import HTTPException
    foreign=tmp_path/'outside';foreign.mkdir();root=tmp_path/'project';root.mkdir()
    try:(root/'skills').symlink_to(foreign,target_is_directory=True)
    except OSError:pytest.skip('symlinks unavailable on this test host')
    with pytest.raises(HTTPException) as error:get(root,'assessment')
    assert error.value.status_code==409


def test_adopted_candidate_keeps_bound_method_provenance(env):
    c,tokens,root,_=env;e=event(c);task,lease=claimed(c,e,tokens[0])
    assert submit(c,e,task,lease,tokens[0]).status_code==200
    r=post(c,e,f"agent-tasks/{task['id']}/adopt");assert r.status_code==200
    producer=r.json()['assessment']['producer']
    assert producer['skill_id']=='disclosure-duty-assessment'
    assert producer['skill_version']==json.loads((root/'skills/registry.json').read_text())['stages']['assessment']['version']
    assert producer['skill_sha256']==json.loads((root/'skills/registry.json').read_text())['stages']['assessment']['sha256']
