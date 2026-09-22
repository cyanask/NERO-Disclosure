"""Real dispatch function with stub I/O; never a claim of rendering/LLM acceptance."""
import copy
from types import SimpleNamespace
import threading
import pytest
from fastapi import HTTPException
from backend import document_runtime as dispatch, document_preflight as preflight


class Store:
    def __init__(self, **values):
        self.value={'id':'fixture-run','stage':'document','intent_domain':'disclosure',**values}
    def run(self, rid):
        return copy.deepcopy(self.value)
    def update(self, rid, **values):
        self.value.update(values)
        return self.run(rid)
    def journal(self, rid):
        # 制文工具按本轮用户原话确定输出目标，不按阶段标签放行。
        return [{'kind':'user','body':{'text':'请把当前分析制作成Word。'}}]


def runtime(**values):
    return SimpleNamespace(store=Store(**values),trace=lambda *args:None)


def test_deferred_preflight_does_not_consume_production_attempts(monkeypatch):
    engine=runtime()
    held={'data':{'status':'preflight_required'},'next_context':{'stage':'document_preflight'}}
    monkeypatch.setattr(preflight,'enforce',lambda *args:held)
    monkeypatch.setattr(dispatch,'make_word',lambda *args,**kwargs:pytest.fail('must not generate'))
    for _ in range(5):
        assert dispatch.execute(engine,'fixture-run','make_word',{'documents':[]},threading.Event())==held
    assert 'document_attempts' not in engine.store.value
    assert 'outcome' not in engine.store.value


def test_ready_dispatch_preserves_existing_generation_attempt_control(monkeypatch):
    engine=runtime()
    monkeypatch.setattr(preflight,'enforce',lambda *args:None)
    monkeypatch.setattr(dispatch,'make_word',lambda *args,**kwargs:{'data':{'fixture':True}})
    assert dispatch.execute(engine,'fixture-run','make_word',{},threading.Event())['data']['fixture']
    assert engine.store.value['document_attempts']==1


def test_actual_generation_failure_is_not_silently_retried_or_count_reset(monkeypatch):
    engine=runtime(document_attempts=2)
    monkeypatch.setattr(preflight,'enforce',lambda *args:None)
    traced=[];engine.trace=lambda *args:traced.append(args)
    def fail(*args,**kwargs):
        raise HTTPException(409,'fixture renderer failure')
    monkeypatch.setattr(dispatch,'make_word',fail)
    with pytest.raises(HTTPException) as error:
        dispatch.execute(engine,'fixture-run','make_word',{},threading.Event())
    assert error.value.status_code==409 and error.value.detail=='fixture renderer failure'
    assert engine.store.value['document_attempts']==3
    assert 'outcome' not in engine.store.value and 'documents' not in engine.store.value
    assert [row[:2] for row in traced]==[('fixture-run','document_check_failed')]


def test_changed_inputs_resync_tool_surface_once(monkeypatch):
    engine=runtime(document_context_sha256='old',document_preflight={'status':'ready','input_fingerprint':'old'})
    monkeypatch.setattr(dispatch,'context',lambda *args:{'production_allowed':False,'templates':[]})
    invoked=[]
    def next_context(*args):
        invoked.append(True)
        return {'data':{},'next_context':{'stage':'document_preflight','tools':[]}}
    monkeypatch.setattr(preflight,'next_context',next_context)
    result=dispatch.execute(engine,'fixture-run','read_document_context',{},threading.Event())
    assert result['next_context']['stage']=='document_preflight'
    assert result['data']['templates']==[] and invoked==[True]


def test_unchanged_read_does_not_add_context_transition(monkeypatch):
    engine=runtime(document_context_sha256='current',document_preflight={'status':'ready','input_fingerprint':'current'})
    monkeypatch.setattr(dispatch,'context',lambda *args:{'production_allowed':True,'templates':[]})
    monkeypatch.setattr(preflight,'next_context',lambda *args:pytest.fail('no transition needed'))
    assert 'next_context' not in dispatch.execute(engine,'fixture-run','read_document_context',{},threading.Event())


def test_read_in_chat_never_switches_into_production(monkeypatch):
    engine=runtime(stage='chat')
    monkeypatch.setattr(dispatch,'context',lambda *args:{'production_allowed':True})
    monkeypatch.setattr(preflight,'next_context',lambda *args:pytest.fail('do not escalate'))
    assert 'next_context' not in dispatch.execute(engine,'fixture-run','read_document_context',{},threading.Event())


def test_non_disclosure_domain_cannot_call_document_writer(monkeypatch):
    """制文工具按业务域开放；域外调用不得读取用户原话或触达制文门禁。"""
    monkeypatch.setattr(preflight,'enforce',lambda *args:pytest.fail('domain must reject before the write gate'))
    monkeypatch.setattr(preflight,'current_user',lambda *args:pytest.fail('domain must reject before reading the user message'))
    with pytest.raises(HTTPException) as exc:
        dispatch.execute(runtime(intent_domain='knowledge',stage='chat'),'fixture-run','make_word',{},threading.Event())
    assert exc.value.status_code==403


def test_disclosure_tool_call_binds_the_output_mode_from_the_user_message(monkeypatch):
    """咨询阶段也可调用制文工具；阶段标签不授权，输出目标按本轮要求登记并保留门禁。"""
    engine=runtime(stage='chat')
    monkeypatch.setattr(preflight,'enforce',lambda *args:None)
    monkeypatch.setattr(dispatch,'make_word',lambda *args,**kwargs:{'data':{'fixture':True}})
    assert dispatch.execute(engine,'fixture-run','make_word',{},threading.Event())['data']['fixture']
    assert engine.store.value['stage']=='document' and engine.store.value['intent']=='document'
    assert engine.store.value['document_attempts']==1
