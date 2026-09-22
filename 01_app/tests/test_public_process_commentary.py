from uuid import uuid4
from test_pi_runtime import client,settled
from test_document_runtime import request


def test_public_commentary_is_recorded_but_never_completes_a_consultation(client):
    c,runtime,_=client
    session=runtime.store.create_session('chinext','','过程说明回归',str(uuid4()))
    def runner(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'测试过程消息'})
        emit({'type':'assistant','text':'我会先说明适用条件，再整理办理步骤。','phase':'progress','stopReason':'toolUse','message':1})
        emit({'type':'done'})
    runtime.runner=runner
    result=settled(c,request(c,session,'请分析办理步骤'))
    assert result['run']['status']=='incomplete'
    public=[r for r in result['events'] if r['kind']=='assistant']
    assert len(public)==1 and public[0]['body']['phase']=='progress'
    assert public[0]['body']['text'].startswith('我会先说明')


def test_process_does_not_replace_final_answer_or_expose_reasoning(client):
    c,runtime,_=client
    session=runtime.store.create_session('chinext','','过程与结果分离',str(uuid4()))
    def runner(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'测试完成'})
        emit({'type':'assistant','text':'我会先核对适用范围。','phase':'progress','stopReason':'toolUse','message':1})
        emit({'type':'thinking','text':'PRIVATE_REASONING_SENTINEL'})
        emit({'type':'assistant','text':'当前资料不足，无法确定具体办理期限。','phase':'answer','stopReason':'stop','message':2})
        emit({'type':'done'})
    runtime.runner=runner
    result=settled(c,request(c,session,'请说明当前结论'))
    assert result['run']['status']=='completed'
    assert [r['body']['phase'] for r in result['events'] if r['kind']=='assistant']==['progress','answer']
    assert not any('PRIVATE_REASONING_SENTINEL' in str(r) for r in result['events'])
