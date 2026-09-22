"""Synthetic inputs only: capability projection and completion."""
import copy
import pytest
from backend.completion_receipts import document_capability, current_answer, settle_without_outcome


def run(**over):
    return {'id':'fixture-run','stage':'document','document_context_sha256':'current-fingerprint', **over}


def receipt(text='已给出测试答复', stop='stop', phase='answer', **over):
    return {'run_id':'fixture-run','kind':'assistant',
            'body':{'text':text,'stopReason':stop,'phase':phase}, **over}


def test_hidden_word_tool_is_preflight_not_renderer_unavailable():
    value=document_capability(run())
    assert value['state']=='preflight_required' and value['next_tool']=='assess_document_readiness'
    assert value['production_tool']=='make_word' and value['renderer_health']=='not_probed'
    assert value['production_allowed'] is False


@pytest.mark.parametrize('status',['ready','authorized'])
def test_matching_preflight_projects_current_production_tool(status):
    value=document_capability(run(document_preflight={'status':status,'input_fingerprint':'current-fingerprint'}))
    assert value['state']=='ready' and value['next_tool']=='make_word'
    assert value['production_allowed'] is True


@pytest.mark.parametrize('fingerprint',['stale-fingerprint',None,''])
def test_stale_or_missing_fingerprint_never_projects_permission(fingerprint):
    value=document_capability(run(document_preflight={'status':'authorized','input_fingerprint':fingerprint}))
    assert value['production_allowed'] is False and value['next_tool']=='assess_document_readiness'


def test_text_target_never_advertises_word_permission():
    value=document_capability(run(stage='announcement'))
    assert value['production_tool']=='save_announcement' and value['expected_result']=='registered_text'


@pytest.mark.parametrize('outcome',['waiting_user','failed','cancelled','completed'])
def test_registered_outcome_does_not_reopen_write(outcome):
    value=document_capability(run(outcome=outcome,document_preflight={'status':'ready','input_fingerprint':'current-fingerprint'}))
    assert value['next_tool'] is None and value['production_allowed'] is False


def test_evidence_repair_is_not_a_new_user_fact_gap():
    value=document_capability(run(document_preflight={'status':'repair_evidence','input_fingerprint':'current-fingerprint'}))
    assert value['state']=='evidence_repair' and '依据定位' in value['detail']


def test_projection_never_mutates_authorization():
    value=run(document_preflight={'status':'authorized','input_fingerprint':'current-fingerprint'})
    before=copy.deepcopy(value)
    document_capability(value)
    assert value==before


@pytest.mark.parametrize('stage',['chat','knowledge'])
def test_empty_or_search_only_read_round_is_incomplete(stage):
    value=run(stage=stage)
    rows=[{'run_id':value['id'],'kind':'knowledge_returned','body':{'items':['模拟资料']}}]
    status,_=settle_without_outcome(value,rows)
    assert status=='incomplete'


def test_finished_answer_can_complete_knowledge_round():
    assert settle_without_outcome(run(stage='knowledge'),[receipt()])[0]=='completed'


def test_consultation_answer_is_never_withheld_by_evidence_gaps():
    # Evidence findings are reminders: a delivered answer always registers.
    status,reason=settle_without_outcome(run(stage='chat'),[receipt()])
    assert status=='completed' and '答复已返回' in reason


def test_bound_reply_render_does_not_request_drafting_preflight():
    value=document_capability(run(document_action='render',reply_source={'run_id':'prior','sha256':'bound'}))
    assert value['state']=='ready' and value['next_tool']=='make_word'
    assert document_capability(run(document_action='render'))['production_allowed'] is False


@pytest.mark.parametrize('message',[
    receipt(text=''),receipt(text='  '),receipt(stop='toolUse',phase='progress'),
    receipt(stop='length'),receipt(stop='error'),receipt(stop=None),receipt(phase='progress'),
    receipt(run_id='old-run'),{'run_id':'fixture-run','kind':'text_delta','body':{'delta':'正在查询'}},
])
def test_partial_or_foreign_message_is_not_an_answer(message):
    assert not current_answer(run(stage='chat'),[message])


def test_last_empty_answer_does_not_reuse_earlier_answer():
    assert settle_without_outcome(run(stage='chat'),[receipt(),receipt(text='')])[0]=='incomplete'


@pytest.mark.parametrize('marker',[
    {'run_id':'fixture-run','kind':'completion_incomplete','body':{}},
    {'run_id':'fixture-run','kind':'done','body':{'completion_complete':False}},
])
def test_worker_incomplete_receipt_does_not_withhold_a_delivered_answer(marker):
    assert settle_without_outcome(run(stage='chat'),[receipt(),marker])[0]=='completed'


def test_persisted_incomplete_flag_wins():
    assert settle_without_outcome(run(stage='knowledge',completion_complete=False),[receipt()])[0]=='incomplete'


def test_provider_failure_does_not_become_success():
    assert settle_without_outcome(run(stage='chat',provider_error='fixture'),[receipt()])[0]=='failed'


def test_document_prose_without_receipt_never_completes():
    value=run(document_preflight={'status':'ready','input_fingerprint':'current-fingerprint'})
    status,reason=settle_without_outcome(value,[receipt(text='Word已完成')])
    assert status=='incomplete' and '未取得生产工具' in reason


def test_preflight_failure_diagnostic_does_not_claim_engine_failure():
    status,reason=settle_without_outcome(run(),[receipt(text='make_word工具不可用')])
    assert status=='incomplete' and '核对' in reason and '不可用' not in reason


def test_real_tool_error_is_reported_before_generic_missing_step():
    rows=[{'run_id':'fixture-run','kind':'document_check_failed','body':{'detail':'fixture'}}]
    status,reason=settle_without_outcome(run(),rows)
    assert status=='incomplete' and '最后一次错误' in reason
