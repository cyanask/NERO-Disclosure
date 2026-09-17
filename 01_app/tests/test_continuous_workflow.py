"""Continuous policy gates exercised in copied, isolated fixture stores.

Synthetic internal candidate callers verify authorization contracts only. These
checks do not run a model, alter production data, or establish human acceptance.
"""
import io
import json
from uuid import uuid4

import pytest
from docx import Document
from internal_workflow import context as read_context
from test_agent_tasks import (env as copied_env, event, latest, post, claimed, candidate,
                              plan_candidate, confirm_stage)
from test_open_intake import source_plan
from test_word_delivery import word_bytes, register


@pytest.fixture
def env(copied_env):
    # This suite tests continuation/approval versions, not real layout acceptance.
    # A synthetic ready layout belongs only to the copied test workspace.
    client, tokens, root, config = copied_env
    path = root / 'templates/boards/chinext/layout_profiles.json'
    rows = json.loads(path.read_text())
    for row in rows:
        row['scope_review_status'] = 'synthetic_fixture_only_not_human_acceptance'
    path.write_text(json.dumps(rows, ensure_ascii=False))
    yield client, tokens, root, config


def create_case(client, mode='word', policy='continuous-v1', required=True):
    sample = event(client)
    payload = {key: sample[key] for key in ('company_id', 'kind', 'title', 'summary', 'facts')}
    payload.update(output_mode=mode, workflow_policy=policy, request_id=str(uuid4()))
    payload['facts'] = {**payload['facts'], 'requires_shareholder_approval': required}
    if mode == 'text':
        # Source-led text uses the existing open-intake contract, without a template.
        payload.pop('company_id')
        payload['facts'].pop('disclosure_profile_id', None)
        payload.update(company_name='连续流程隔离测试公司', board='chinext', kind='synthetic_disclosure')
    response = client.post('/api/events', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['workflow_policy'] == policy
    return response.json()


def evaluate(client, case, token, stage, value):
    task, lease = claimed(client, case, token, stage)
    packet = read_context(client, case, task, token)
    assert packet.status_code == 200, packet.text
    result = value(packet.json()) if callable(value) else value
    response = post(client, case, f"agent-tasks/{task['id']}/evaluate", token,
                    claim_id=lease['claim_id'], input_fingerprint=lease['input_fingerprint'],
                    result=result)
    assert response.status_code == 200, response.text
    saved = latest(client, case)
    assert saved['agent_tasks'][-1]['status'] == 'adopted', response.text
    return saved, packet.json(), result


def assert_automatically_advanced(case, stage, expected):
    assert case['stage'] == expected
    assert case['verified_stages'][stage]['status'] == 'PASS'
    assert not case.get('approval_records')
    assert not case[stage]['approved']
    assert any(row['stage'] == stage and row['human_approved'] is False
               for row in case['automation_records'])


def ready_draft(client, token, mode='word', policy='continuous-v1'):
    case = create_case(client, mode, policy)
    case, _, _ = evaluate(client, case, token, 'assessment', candidate())
    if policy == 'continuous-v1':
        assert_automatically_advanced(case, 'assessment', 'planning')
    else:
        assert case['stage'] == 'awaiting_assessment_confirmation'
        assert post(client, case, 'agent-tasks', stage='plan').status_code == 409
        response = confirm_stage(client, case, 'assessment', 'prepare_mandatory')
        assert response.status_code == 200, response.text
    case, packet, plan = evaluate(client, case, token, 'plan',
                                 (lambda _: source_plan()) if mode == 'text' else plan_candidate)
    if policy == 'continuous-v1':
        assert_automatically_advanced(case, 'plan', 'drafting' if mode == 'text' else 'selecting_template')
    else:
        assert case['stage'] == 'awaiting_plan_confirmation'
        assert post(client, case, 'agent-tasks', stage='template').status_code == 409
        response = confirm_stage(client, case, 'plan')
        assert response.status_code == 200, response.text
    if mode == 'text':
        draft = {'documents': [
            {'document_id': doc['document_id'], 'text': doc['title'] + '\n本次事项涉及已列明的股东会程序。',
             'requirement_map': {doc['document_id'] + '-fact': '本次事项涉及已列明的股东会程序。'}}
            for doc in plan['documents']]}
    else:
        template = {'template_id': packet['templates'][0]['id'],
                    'requirement_map': {r['requirement_id']: r['section_id'] for r in plan['requirements']}}
        case, _, _ = evaluate(client, case, token, 'template', template)
        if policy == 'continuous-v1':
            assert_automatically_advanced(case, 'template', 'drafting')
        else:
            assert case['stage'] == 'awaiting_template_confirmation'
            assert post(client, case, 'agent-tasks', stage='draft').status_code == 409
            response = confirm_stage(client, case, 'template')
            assert response.status_code == 200, response.text
        body = '证券代码：000000 证券简称：模拟公司 主办券商：模拟券商 公告编号：模拟001\n# 董事会决议公告\n'
        body += '\n'.join('## ' + item['title'] + '\n模拟金额 100.00 元。' for item in plan['items'])
        body += '\n| 项目 | 金额（元） |\n| --- | --- |\n| 本次 | 100.00 |'
        draft = {'template_id': template['template_id'], 'text': body,
                 'requirement_map': {r['requirement_id']: '模拟金额 100.00 元。' for r in plan['requirements']}}
    case, _, _ = evaluate(client, case, token, 'draft', draft)
    return case, draft


def confirm_draft(client, case):
    response = confirm_stage(client, case, 'draft', content_review='reviewed')
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('mode', ['text', 'word'])
def test_automatic_candidates_stop_at_complete_draft_without_human_signatures(env, mode):
    client, tokens, _, _ = env
    case, _ = ready_draft(client, tokens[0], mode)
    assert case['stage'] == 'awaiting_draft_confirmation'
    assert not case.get('approval_records')
    assert case['verified_stages']['draft']['status'] == 'PASS'
    assert confirm_stage(client, case, 'plan').status_code == 409
    if mode == 'word':
        assert confirm_stage(client, case, 'template').status_code == 409
    assert not latest(client, case).get('approval_records')


def test_text_content_checkbox_and_fingerprint_are_required_before_finalization(env):
    client, tokens, _, _ = env
    case, _ = ready_draft(client, tokens[0], 'text')
    assert confirm_stage(client, case, 'draft').status_code == 409
    bad = post(client, case, 'confirmations', stage='draft', input_fingerprint='0' * 64,
               decision='accept', reviewer='隔离测试', reason='检查旧指纹拒绝', content_review='reviewed')
    assert bad.status_code == 409
    assert not latest(client, case).get('approval_records')
    saved = confirm_draft(client, case)
    assert saved['stage'] == 'text_confirmed'
    assert [r['node'] for r in saved['approval_records'] if r['state'] == 'current'] == ['draft']
    assert client.get(f"/api/events/{case['id']}/word/context").status_code == 409
    assert not saved.get('artifacts')


def test_word_context_and_upload_require_current_complete_content_confirmation(env):
    client, tokens, root, _ = env
    case, _ = ready_draft(client, tokens[0])
    packet = client.get(f"/api/events/{case['id']}/word/context")
    assert packet.status_code == 409
    assert '完整正文' in packet.text
    raw = io.BytesIO()
    Document().save(raw)
    gate = client.get(f"/api/events/{case['id']}/verify", params={'stage': 'draft'}).json()
    rejected = register(client, case, gate, raw.getvalue())
    assert rejected.status_code == 409
    assert '完整正文' in rejected.text
    assert not latest(client, case).get('artifacts')
    assert confirm_stage(client, case, 'draft').status_code == 409
    saved = confirm_draft(client, case)
    assert saved['stage'] == 'draft_verified'
    packet = client.get(f"/api/events/{case['id']}/word/context")
    assert packet.status_code == 200, packet.text
    packet = packet.json()
    registered = register(client, case, packet, word_bytes(root, packet))
    assert registered.status_code == 200, registered.text
    assert registered.json()['stage'] == 'awaiting_word_confirmation'
    artifact = registered.json()['artifacts'][-1]
    assert confirm_stage(client, case, 'word', artifact_id=artifact['id'], content_review='reviewed').status_code == 409
    accepted = confirm_stage(client, case, 'word', artifact_id=artifact['id'],
                             content_review='reviewed', visual_review='reviewed')
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['stage'] == 'confirmed_draft_archived'
    assert [r['node'] for r in accepted.json()['approval_records'] if r['state'] == 'current'] == ['draft', 'word']


@pytest.mark.parametrize('change', ['draft', 'facts', 'law'])
def test_prior_content_confirmation_is_invalidated_by_dependency_changes(env, change):
    client, tokens, root, _ = env
    case, draft = ready_draft(client, tokens[0])
    case = confirm_draft(client, case)
    approval = next(r for r in case['approval_records'] if r['node'] == 'draft' and r['state'] == 'current')
    if change == 'draft':
        revised = {**draft, 'text': draft['text'] + '\n补充模拟披露说明。'}
        case, _, _ = evaluate(client, case, tokens[0], 'draft', revised)
        assert case['stage'] == 'awaiting_draft_confirmation'
    elif change == 'facts':
        response = client.patch(f"/api/events/{case['id']}", json={
            'expected_revision': latest(client, case)['revision'],
            'facts': {**case['facts'], 'resolution_subject': '模拟事实修订后的议案'}})
        assert response.status_code == 200, response.text
    else:
        path = root / 'data/public/boards/chinext/catalog.json'
        catalog = json.loads(path.read_text())
        source = next(row for row in catalog['sources'] if row['id'] == 'szse-chinext-2026-4.1.7')
        source['text'] += '\n仅用于隔离测试的法源版本变化。'
        path.write_text(json.dumps(catalog, ensure_ascii=False))
    saved = latest(client, case)
    assert next(r for r in saved['approval_records'] if r['id'] == approval['id'])['state'] == 'invalidated'
    assert client.get(f"/api/events/{case['id']}/word/context").status_code == 409
    old_confirmation = post(client, case, 'confirmations', stage='draft',
                            input_fingerprint=approval['input_fingerprint'], decision='accept',
                            reviewer='隔离测试', reason='旧确认不得复用', content_review='reviewed')
    assert old_confirmation.status_code == 409


def test_legacy_word_flow_retains_four_human_gates(env):
    client, tokens, root, _ = env
    case, _ = ready_draft(client, tokens[0], policy='legacy-v1')
    assert case['stage'] == 'draft_verified'
    assert [r['node'] for r in case['approval_records'] if r['state'] == 'current'] == ['assessment', 'plan', 'template']
    assert confirm_stage(client, case, 'draft', content_review='reviewed').status_code == 409
    packet = client.get(f"/api/events/{case['id']}/word/context")
    assert packet.status_code == 200, packet.text
    packet = packet.json()
    registered = register(client, case, packet, word_bytes(root, packet))
    assert registered.status_code == 200, registered.text
    artifact = registered.json()['artifacts'][-1]
    accepted = confirm_stage(client, case, 'word', artifact_id=artifact['id'],
                             content_review='reviewed', visual_review='reviewed')
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['stage'] == 'confirmed_draft_archived'
    assert [r['node'] for r in accepted.json()['approval_records'] if r['state'] == 'current'] == ['assessment', 'plan', 'template', 'word']


def test_no_disclosure_exception_waits_for_a_real_human_decision(env):
    client, tokens, _, _ = env
    case = create_case(client, 'text', required=False)
    value = candidate()
    value['status'] = 'no_disclosure'
    value['facts'][0]['value'] = False
    value['matters'][0].update(duty_status='no_mandatory_identified', timing_status='not_triggered',
                               reassessment_conditions=['出现新的事实或独立触发条件'])
    value['matters'][0]['reasoning_items'][0]['outcome'] = 'not_met'
    case, _, _ = evaluate(client, case, tokens[0], 'assessment', value)
    assert case['stage'] == 'awaiting_assessment_confirmation'
    assert not case.get('approval_records')
    assert post(client, case, 'agent-tasks', stage='plan').status_code == 409
    accepted = confirm_stage(client, case, 'assessment', 'no_disclosure')
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['stage'] == 'no_disclosure_manual_tracking'
    assert [r['node'] for r in accepted.json()['approval_records'] if r['state'] == 'current'] == ['assessment']
    assert post(client, case, 'agent-tasks', stage='plan').status_code == 409
