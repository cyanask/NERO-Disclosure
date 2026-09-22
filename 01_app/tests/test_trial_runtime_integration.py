"""Full-repository tests: real local APIs, routing and Word writer; fake provider.

Run these in the complete repository. They are not part of the standalone
fragment-only validation shipped with the patch.
"""
from uuid import uuid4
from test_pi_runtime import client, settled
from test_document_runtime import request, readiness, content_gap, draft, listing
from test_grounded_consultation import review_only


def session(runtime):
    return runtime.store.create_session('chinext','','试运行接口回归',str(uuid4()))


def test_real_routing_keeps_the_model_decision_and_loads_consultation_skill(client):
    c,runtime,_=client
    s=session(runtime)
    answer='以下为虚构测试的办理说明。'
    review_only(runtime,{answer})
    def provider(packet,emit,bridge,stop):
        emit({'type':'started'})
        routed=bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'业务程序咨询'})
        assert routed['data']['domain']=='disclosure' and routed['data']['intent']=='consult'
        assert routed['next_context']['requires_result'] is False
        assert bridge('submit_consultation',{'text':answer,'basis':[]})['terminate']
        emit({'type':'done'})
    runtime.runner=provider
    result=settled(c,request(c,s,'那办理分红的程序性要求是什么，比如和中登系统提交申请'))
    assert result['run']['status']=='completed' and result['run']['stage']=='chat'
    assert result['run']['skill']['id']=='disclosure-consultation'
    assert not any(row['kind']=='routing_correction' for row in result['events'])


def test_real_runtime_does_not_complete_a_blank_consultation(client):
    c,runtime,_=client
    s=session(runtime)
    def provider(packet,emit,bridge,stop):
        emit({'type':'started'})
        bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'咨询'})
        emit({'type':'assistant','text':'','message':0,'phase':'answer','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=provider
    result=settled(c,request(c,s,'分红办理的程序是什么'))
    assert result['run']['status']=='incomplete'
    assert '尚未返回可展示的答复' in result['run']['reason']


def test_explicit_placeholders_open_writer_and_create_registered_word(client):
    c,runtime,_=client
    s=session(runtime)
    review_only(runtime,{'# 模拟业务分析','实施日期为【待补：实施日期】。'})
    def provider(packet,emit,bridge,stop):
        emit({'type':'started'})
        routed=bridge('route_request',{'domain':'disclosure','intent':'document','document_kind':'analysis','reason':'用户要待补Word'})
        assert 'make_word' in [t['name'] for t in routed['next_context']['tools']]
        ctx=bridge('read_document_context',{})['data']
        assert ctx['production_capability']['state']=='preflight_required'
        doc=draft('模拟业务分析',text='# 模拟业务分析\n\n实施日期为【待补：实施日期】。',pending=['实施日期'])
        opened=bridge('assess_document_readiness',{'documents':[readiness(doc,[content_gap('实施日期')])],
            'request_quote':packet['prompt'],'decision':'draft_with_placeholders','choice_quote':packet['prompt']})
        assert opened['data']['production_capability']['state']=='ready'
        assert opened['data']['production_capability']['next_tool']=='make_word'
        assert 'make_word' in [t['name'] for t in opened['next_context']['tools']]
        saved=bridge('make_word',{'documents':[doc]})
        assert saved['data']['documents']
        emit({'type':'assistant','text':'测试Word已登记，仍有待补项。','message':0,'phase':'final','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=provider
    result=settled(c,request(c,s,'缺项留空标注【待补】，先制作Word'))
    assert result['run']['status']=='completed',result['run']
    docs=listing(c,s)['items']
    assert len(docs)==1 and docs[0]['format']=='docx' and '实施日期' in docs[0]['pending']
    assert c.get(docs[0]['download']).status_code==200


def test_saved_word_is_not_lost_when_closing_reply_is_empty(client):
    c,runtime,_=client
    s=session(runtime)
    review_only(runtime,{'# 模拟材料','一、当前结论','以当前资料为准。','二、后续安排','请核对实施状态。'})
    def provider(packet,emit,bridge,stop):
        emit({'type':'started'})
        bridge('route_request',{'domain':'disclosure','intent':'document','document_kind':'analysis','reason':'用户要Word'})
        bridge('read_document_context',{})
        doc=draft('模拟材料')
        bridge('assess_document_readiness',{'documents':[readiness(doc)],'request_quote':packet['prompt'],'decision':'assess'})
        bridge('make_word',{'documents':[doc]})
        emit({'type':'finalization_failed','message':'模拟空收尾'})
        emit({'type':'assistant','text':'','message':0,'phase':'final','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=provider
    result=settled(c,request(c,s,'请制作分析Word'))
    assert result['run']['status']=='completed' and result['run']['finalization_status']=='failed',result['run']
    assert listing(c,s)['items']


def test_explicit_original_query_stays_knowledge_and_reads_late_answer(client):
    c,runtime,_=client;s=session(runtime)
    def provider(packet,emit,bridge,stop):
        routed=bridge('route_request',{'domain':'knowledge','intent':'query','reason':'用户索取原文'})
        assert routed['data']['domain']=='knowledge' and routed['data']['intent']=='query'
        assert routed['next_context']['requires_result'] is False
        for _ in range(1001):runtime.trace(packet['run_id'],'knowledge_returned',{'items':[]})
        emit({'type':'assistant','text':'这是隔离用例的原文读取结果。','message':0,'phase':'answer','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=provider
    result=settled(c,request(c,s,'查看《上市公司股份减持管理暂行办法》中关于应当披露的原文'))
    assert result['run']['status']=='completed' and result['run']['stage']=='knowledge'


def test_blank_knowledge_answer_is_not_completed(client):
    c,runtime,_=client;s=session(runtime)
    def provider(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'knowledge','intent':'query','reason':'查看原文'})
        emit({'type':'assistant','text':'','message':0,'phase':'answer','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=provider
    result=settled(c,request(c,s,'查看法规库原文'))
    assert result['run']['status']=='incomplete'


def test_changed_document_inputs_resync_tools_without_spending_attempts(client):
    c,runtime,_=client;s=session(runtime)
    def provider(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'document','reason':'制文'})
        bridge('read_document_context',{})
        doc=draft('核对测试')
        bridge('assess_document_readiness',{'documents':[readiness(doc)],'request_quote':packet['prompt'],'decision':'assess'})
        runtime.store.append(packet['run_id'],'user',{'text':'补充：实施日期仍待确认。'})
        changed=bridge('read_document_context',{})
        assert changed['data']['production_capability']['state']=='input_changed'
        assert changed['next_context']['stage']=='document_preflight'
        assert 'make_word' in [t['name'] for t in changed['next_context']['tools']]
        assert 'next_context' not in bridge('read_document_context',{})
        for _ in range(2):
            held=bridge('make_word',{'documents':[doc]})
            assert held['data']['status']=='preflight_required'
        assert runtime.store.run(packet['run_id']).get('document_attempts',0)==0
        emit({'type':'done'})
    runtime.runner=provider
    result=settled(c,request(c,s,'请制作核对测试Word'))
    assert result['run']['status']=='incomplete',result['run']
    assert listing(c,s)['items']==[]
