"""Guidance reaches Pi without adding a completion gate or another tool."""
import pytest
from backend.intent_control import PRESENTATION
from test_autonomous_control import control, session, send_auto
from test_pi_runtime import settled


@pytest.mark.parametrize('domain,intent,stage',[
    ('disclosure','consult','chat'), ('knowledge','query','knowledge'),
])
def test_guidance_survives_routing_without_requiring_a_followup(control,domain,intent,stage):
    client,runtime,_=control
    current=session(client)
    seen=[]
    def runner(packet,emit,bridge,stop):
        seen.append(packet['system'])
        reply=bridge('route_request',{'domain':domain,'intent':intent,'reason':'隔离测试当前用户需求'})
        next_context=reply['next_context']
        seen.append(next_context['system'])
        assert next_context['requires_result'] is False
        assert not any('guidance' in tool['name'] for tool in next_context['tools'])
        emit({'type':'assistant','phase':'answer','message':1,'text':'本次查询已完成。','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=runner
    output=settled(client,send_auto(client,current,'只查询相关规则，暂时不写公告或制作文件。'))
    assert len(seen)==2 and all(PRESENTATION in text for text in seen)
    assert output['run']['stage']==stage and output['run']['status']=='completed'
    assert not output['run'].get('questions')
    assert client.get('/api/events').json()==[]
