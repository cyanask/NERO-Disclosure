"""Persisted drafting choices survive execution failure, not scope changes."""
import pytest
from uuid import uuid4
from test_pi_runtime import client, settled
from test_document_runtime import request, readiness, content_gap, draft, listing


@pytest.mark.parametrize('text', [
    '只讨论生成Word的方法，缺失信息先标注待补。',
    '先讨论如何起草，缺失资料留空，不开始执行。',
])
def test_discussion_of_placeholder_mode_is_not_production_consent(text):
    from backend.document_preflight import explicit_placeholders
    assert not explicit_placeholders(text)


@pytest.mark.parametrize('status,new_title,should_continue', [
    ('failed', '分析工作稿', True),
    ('incomplete', '分析工作稿', True),
    ('interrupted', '分析工作稿', True),
    ('cancelled', '分析工作稿', False),
    ('failed', '另一份工作稿', False),
])
def test_recorded_choice_recovers_only_for_same_uncancelled_document(client, status, new_title, should_continue):
    c, runtime, _ = client
    session = runtime.store.create_session('chinext', '', '恢复回归', str(uuid4()))
    gap = content_gap('实施日期')

    def prepared_then_failed(packet, emit, bridge, stop):
        bridge('route_request', {'domain': 'disclosure', 'intent': 'document', 'document_kind': 'analysis', 'reason': '制作工作稿'})
        value = bridge('assess_document_readiness', {
            'documents': [readiness(draft('分析工作稿'), [gap])], 'request_quote': packet['prompt'],
            'decision': 'draft_with_placeholders', 'choice_quote': packet['prompt'],
        })
        assert any(t['name'] == 'make_word' for t in value['next_context']['tools'])
        raise RuntimeError('Isolated failure after consent, before production')

    runtime.runner = prepared_then_failed
    first = settled(c, request(c, session, '先生成Word，缺失资料留空。'))
    assert first['run']['status'] == 'failed'
    assert first['run']['document_preflight']['status'] == 'authorized'
    assert listing(c, session)['items'] == []
    # Exercise persisted terminal states without touching any real session.
    runtime.store.update(first['run']['id'], status=status)

    def resume(packet, emit, bridge, stop):
        bridge('route_request', {'domain': 'disclosure', 'intent': 'document', 'document_kind': 'analysis', 'reason': '继续制作工作稿'})
        document = draft(new_title, text='# '+new_title+'\n\n实施日期：【待补：实施日期】', pending=['实施日期'])
        value = bridge('assess_document_readiness', {
            'documents': [readiness(document, [gap])], 'request_quote': packet['prompt'], 'decision': 'assess',
        })
        if should_continue:
            assert 'next_context' in value
            bridge('make_word', {'documents': [document]})
        else:
            assert value['terminate'] and value['data']['status'] == 'waiting_user'
        emit({'type': 'done'})

    runtime.runner = resume
    second = settled(c, request(c, session, '继续生成Word。'))
    assert second['run']['status'] == ('completed' if should_continue else 'waiting_user'), second
    assert len(listing(c, session)['items']) == int(should_continue)
    assert any(row['kind'] == 'document_gap_notice' for row in second['events']) != should_continue
