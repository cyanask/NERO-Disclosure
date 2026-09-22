"""One runtime: consultation Skill -> announcement text -> human confirmation -> Word."""
import pytest
from backend import document_store
from test_pi_runtime import client, new_session, settled
from test_document_runtime import request, draft, listing, provider, readiness, content_gap

ANNOUNCEMENT_TEXT='# 财务资助公告\n一、事项概述\n拟资助1000万元。\n二、审议情况\n经董事会审议通过。'
ANNOUNCEMENT_GAP=content_gap('审议情况','董事会审议情况尚未提供')
ANNOUNCEMENT_PENDING='# 财务资助公告\n一、事项概述\n拟资助1000万元。\n二、审议情况\n【待补：审议情况】'
ANNOUNCEMENT_ACCEPT='先按现有资料拟公告，缺项标注待补。'


def announcement_draft(template_id,text):
    return draft('财务资助公告',kind='announcement',template_id=template_id,text=text,
                 pending=['审议情况'] if '【待补：审议情况】' in text else [])


def consult(runtime, answer='该事项需先核对披露范围，然后拟写公告。'):
    def run(packet,emit,bridge,stop):
        routed=bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'信披问题'})
        assert 'disclosure-consultation' in routed['next_context']['system']
        assert '不为每个问题执行同一套固定步骤' in routed['next_context']['system']
        emit({'type':'assistant','text':answer,'phase':'final','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=run


def write_announcement(runtime, *,expected_consult=None, text=ANNOUNCEMENT_TEXT):
    def run(packet,emit,bridge,stop):
        routed=bridge('route_request',{'domain':'disclosure','intent':'announcement','reason':'用户开始拟公告'})
        assert routed['next_context']['stage']=='document_preflight'
        names=[t['name'] for t in routed['next_context']['tools']]
        assert 'assess_document_readiness' in names and 'save_announcement' in names
        assert 'name: disclosure-announcement-drafting' in routed['next_context']['system']
        ctx=bridge('read_document_context',{})['data']
        if expected_consult:assert ctx['latest_consultation']['run_id']==expected_consult
        selected=next(t for t in ctx['templates'] if t.get('kind')=='related_transaction')
        bridge('read_document_template',{'template_id':selected['id']})
        document=announcement_draft(selected['id'],text)
        opened=bridge('assess_document_readiness',{'documents':[readiness(document)],'request_quote':packet['prompt'],'decision':'assess'})
        assert 'save_announcement' in [t['name'] for t in opened['next_context']['tools']],opened
        assessment={'disclosure_needed':'yes','disclosure_scope':'事项、金额、审议及风险','reason':'根据当前用户条件拟写'}
        if expected_consult:assessment['consultation_run_id']=expected_consult
        result=bridge('save_announcement',{'assessment':assessment,'documents':[document]})
        assert result['data']['text_saved'] is True
        emit({'type':'assistant','text':'公告正文已保存，可确认版本或要求制作Word。','phase':'final','stopReason':'stop'})
        emit({'type':'done'})
    runtime.runner=run


def test_consultation_loads_versioned_project_skill_without_business_nodes(client):
    c,runtime,_=client;s,e=new_session(c);before=c.get('/api/events/'+e['id']).json()
    consult(runtime)
    out=settled(c,request(c,s,'这件事要不要披露？'))
    assert out['run']['status']=='completed'
    assert out['run']['skill']['id']=='disclosure-consultation'
    assert out['run']['skill_status']=='loaded'
    assert any(r['kind']=='skill_loaded' for r in out['events'])
    assert not any(r['kind']=='tool_requested' and r['body'].get('name')=='task.request' for r in out['events'])
    assert c.get('/api/events/'+e['id']).json()==before


def test_consultation_skill_hash_drift_is_not_silently_ignored(client):
    c,runtime,_=client;s,_=new_session(c)
    path=runtime.root/'skills/disclosure-consultation/SKILL.md'
    path.write_text(path.read_text()+'\n未登记修改。')
    consult(runtime)
    out=settled(c,request(c,s,'请咨询'))
    assert out['run']['status']=='failed'
    assert 'Skill' in out['run']['reason']


@pytest.mark.parametrize('with_consult',[False,True])
def test_drafting_saves_text_after_reusing_or_doing_assessment(client,with_consult):
    c,runtime,_=client;s,e=new_session(c);before=c.get('/api/events/'+e['id']).json()
    prior=None
    if with_consult:
        consult(runtime);prior=settled(c,request(c,s,'拟资助1000万元，是否披露？'))['run']['id']
    write_announcement(runtime,expected_consult=prior)
    out=settled(c,request(c,s,'开始拟公告，拟资助1000万元。'))
    assert out['run']['status']=='completed',out
    row=listing(c,s)['items'][0]
    assert row['format']=='text' and row['download'] is None
    assert row['text'].startswith('# 财务资助公告')
    assert not list(document_store.folder(runtime,s['id']).glob('*.docx'))
    assert out['run']['announcement_assessment']['disclosure_scope']
    assert out['run']['skill']['id']=='disclosure-announcement-drafting'
    assert c.get('/api/events/'+e['id']).json()==before


def test_plain_user_confirmation_binds_text_then_word_can_reuse_it(client):
    c,runtime,_=client;s,e=new_session(c)
    write_announcement(runtime);settled(c,request(c,s,'拟资助1000万元，请拟公告。'))
    row=listing(c,s)['items'][0]
    def confirm(packet,emit,bridge,stop):
        result=bridge('route_request',{'domain':'disclosure','intent':'confirm_text','reason':'用户确认当前公告正文'})
        assert result['terminate'];emit({'type':'done'})
    runtime.runner=confirm
    out=settled(c,request(c,s,'确认'))
    assert out['run']['status']=='completed',out
    confirmed=listing(c,s)['items'][0]
    assert confirmed['review_status']=='accepted' and confirmed['sha256']==row['sha256']
    assert confirmed['reviews'][-1]['source_run_id']==out['run']['id']
    assert not confirmed['reviews'][-1]['visual_reviewed']
    provider(runtime,lambda *_:[{'document_id':row['document_id'],'base_version':1,'title':row['title'],
                                 'kind':'announcement','template_id':row['template_id'],'pending':row['pending'],'basis':[]}])
    result=settled(c,request(c,s,'请制作成公告Word'))
    assert result['run']['status']=='completed',result
    current=listing(c,s)['items'][0]
    assert current['format']=='docx' and current['version']==2 and current['review_status']=='pending'
    assert current['history'][1]['format']=='text' and current['history'][1]['review_status']=='accepted'
    assert c.get(current['download']).status_code==200


def test_approval_of_a_plan_does_not_confirm_unseen_or_changed_text(client):
    c,runtime,_=client;s,_=new_session(c)
    write_announcement(runtime);settled(c,request(c,s,'拟资助1000万元，请拟公告。'))
    def wrong(packet,emit,bridge,stop):bridge('route_request',{'domain':'disclosure','intent':'confirm_text','reason':'错误地把认可方案当全文确认'})
    runtime.runner=wrong
    assert settled(c,request(c,s,'认可方案，请继续修改第二部分'))['run']['status']=='failed'
    assert listing(c,s)['items'][0]['review_status']=='pending'


def test_announcement_modification_routes_to_existing_word(client):
    c,runtime,_=client;s,_=new_session(c)
    write_announcement(runtime);settled(c,request(c,s,'拟资助1000万元，请拟公告。'));row=listing(c,s)['items'][0]
    provider(runtime,lambda *_:[{'document_id':row['document_id'],'base_version':1,'title':row['title'],
                                 'kind':'announcement','template_id':row['template_id'],'pending':row['pending'],'basis':[]}])
    settled(c,request(c,s,'生成公告Word'));row=listing(c,s)['items'][0]
    def route(packet,emit,bridge,stop):
        result=bridge('route_request',{'domain':'disclosure','intent':'announcement','document_action':'revise',
                                      'target_document_id':row['document_id'],'reason':'修改已有公告'})
        assert result['data']['intent']=='document'
        assert result['next_context']['stage']=='document_preflight'
        assert 'assess_document_readiness' in [t['name'] for t in result['next_context']['tools']]
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            bridge('assess_document_readiness',{'documents':[readiness({'title':'另一份公告','kind':'announcement'})],
                                               'request_quote':packet['prompt'],'decision':'assess'})
        assert error.value.status_code==409
        opened=bridge('assess_document_readiness',{'documents':[readiness({'document_id':row['document_id'],'title':row['title'],'kind':'announcement'})],
                                                   'request_quote':packet['prompt'],'decision':'assess'})
        assert 'make_word' in [t['name'] for t in opened['next_context']['tools']],opened
        emit({'type':'done'})
    runtime.runner=route
    assert settled(c,request(c,s,'修改这份公告'))['run']['status']=='incomplete'
    assert listing(c,s)['items'][0]['version']==2


def test_confirmation_and_word_in_one_message_records_only_current_text(client):
    c,runtime,_=client;s,_=new_session(c)
    write_announcement(runtime);settled(c,request(c,s,'拟资助1000万元，请拟公告。'));row=listing(c,s)['items'][0]
    def run(packet,emit,bridge,stop):
        routed=bridge('route_request',{'domain':'disclosure','intent':'document','document_kind':'announcement',
                                      'confirm_current_text':True,'reason':'用户确认当前正文并要求Word'})
        assert routed['next_context']['stage']=='document_preflight'
        assert document_store.version(runtime,s['id'],row['document_id'])['review_status']=='accepted'
        document={'document_id':row['document_id'],'base_version':1,'title':row['title'],
            'kind':'announcement','template_id':row['template_id'],'pending':row['pending'],'basis':[]}
        bridge('read_document_context',{})
        opened=bridge('assess_document_readiness',{'documents':[readiness(document)],'request_quote':packet['prompt'],'decision':'assess'})
        assert 'make_word' in [t['name'] for t in opened['next_context']['tools']],opened
        bridge('make_word',{'documents':[document]})
        emit({'type':'done'})
    runtime.runner=run
    out=settled(c,request(c,s,'确认，请制作成Word'))
    assert out['run']['status']=='completed',out
    current=listing(c,s)['items'][0]
    assert current['format']=='docx' and current['review_status']=='pending'
    assert current['history'][1]['reviews'][-1]['source_run_id']==out['run']['id']


def test_word_kind_cannot_silently_switch_announcement_to_consultation(client):
    c,runtime,_=client;s,_=new_session(c)
    def run(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'document','document_kind':'announcement','reason':'公告Word'})
        bridge('read_document_context',{})
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            bridge('assess_document_readiness',{'documents':[readiness(draft())],'request_quote':packet['prompt'],'decision':'assess'})
        assert error.value.status_code==422
        emit({'type':'done'})
    runtime.runner=run
    assert settled(c,request(c,s,'制作公告Word'))['run']['status']=='incomplete'
    assert listing(c,s)['items']==[]


def test_announcement_gap_notice_precedes_text_draft(client):
    """The controller tells the user what is missing before any text version exists."""
    c,runtime,_=client;s,e=new_session(c);before=c.get('/api/events/'+e['id']).json()
    def notice(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'announcement','reason':'用户开始拟公告'})
        ctx=bridge('read_document_context',{})['data']
        selected=next(t for t in ctx['templates'] if t.get('kind')=='related_transaction')
        result=bridge('assess_document_readiness',{'documents':[readiness(announcement_draft(selected['id'],ANNOUNCEMENT_PENDING),[ANNOUNCEMENT_GAP])],
                                                   'request_quote':packet['prompt'],'decision':'assess'})
        assert result['terminate'] and result['data']['status']=='waiting_user',result
        assert any('审议情况' in question for question in result['data']['questions'])
        emit({'type':'done'})
    runtime.runner=notice
    first=settled(c,request(c,s,'开始拟公告，拟资助1000万元。'))
    assert first['run']['status']=='waiting_user',first
    assert listing(c,s)['items']==[]
    notice_id=first['run']['document_preflight']['notice_id']
    def accept(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'announcement','drafting_notice_id':notice_id,'reason':'用户接受已告知缺口'})
        ctx=bridge('read_document_context',{})['data']
        selected=next(t for t in ctx['templates'] if t.get('kind')=='related_transaction')
        document=announcement_draft(selected['id'],ANNOUNCEMENT_PENDING)
        opened=bridge('assess_document_readiness',{'documents':[readiness(document,[ANNOUNCEMENT_GAP])],'request_quote':packet['prompt'],
                                                   'decision':'proceed_with_gaps','notice_id':notice_id,'choice_quote':packet['prompt']})
        assert 'save_announcement' in [t['name'] for t in opened['next_context']['tools']],opened
        result=bridge('save_announcement',{'assessment':{'disclosure_needed':'yes','disclosure_scope':'事项、金额、审议及风险',
            'reason':'用户接受已告知缺口后保存待补正文'},'documents':[document]})
        assert result['data']['text_saved'] is True
        emit({'type':'done'})
    runtime.runner=accept
    second=settled(c,request(c,s,ANNOUNCEMENT_ACCEPT))
    assert second['run']['status']=='completed',second
    row=listing(c,s)['items'][0]
    assert row['format']=='text' and row['pending']==['审议情况'] and '【待补：审议情况】' in row['text']
    assert not list(document_store.folder(runtime,s['id']).glob('*.docx'))
    assert c.get('/api/events/'+e['id']).json()==before
