"""Company delivery projection reads existing conversation files without re-registering them."""
from uuid import uuid4
from backend import announcement_history, document_store
from test_pi_runtime import client, settled
from test_document_runtime import request, provider, draft, listing, content_gap, readiness


def session(runtime,code='300101',title='制文会话'):
    announcement_history.register_company(runtime.root,'chinext',code,'示例股份有限公司')
    return runtime.store.create_session('chinext',None,title,str(uuid4()),code)


def test_existing_word_appears_without_event_and_updates_to_latest_version(client):
    c,runtime,_=client;s=session(runtime)
    gap=content_gap('审议日期','董事会审议日期尚未提供')
    body='# 分析材料\n\n一、当前结论\n审议日期为【待补：审议日期】。\n\n二、后续安排\n请核对实施状态。'
    def notice(packet,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'document','reason':'用户要求制作Word'})
        bridge('read_document_context',{})
        result=bridge('assess_document_readiness',{'documents':[readiness(draft(text=body),[gap])],
                                                   'request_quote':packet['prompt'],'decision':'assess'})
        assert result['terminate'] and result['data']['status']=='waiting_user',result
        emit({'type':'done'})
    runtime.runner=notice
    first=settled(c,request(c,s))
    assert first['run']['status']=='waiting_user' and listing(c,s)['items']==[]
    provider(runtime,lambda *_:[draft(text=body)],gaps={'分析材料':[gap]},
             consent=first['run']['document_preflight']['notice_id'])
    assert settled(c,request(c,s,'先按现有资料制作Word，缺项标注待补。'))['run']['status']=='completed'
    row=listing(c,s)['items'][0]
    index=document_store.folder(runtime,s['id'])/'index.json';before=index.read_bytes()
    response=c.get('/api/documents?board=chinext&company=300101')
    assert response.status_code==200,response.text
    files=response.json()['items']
    assert len(files)==1 and files[0]['sha256']==row['sha256']
    assert files[0]['session_title']=='制文会话' and files[0]['pending']==['审议日期']
    assert files[0]['download']==row['download']
    assert c.get(files[0]['download']).content==c.get(row['download']).content
    assert index.read_bytes()==before
    provider(runtime,lambda *_:[draft(document_id=row['document_id'],base_version=1,text='修订后的文稿。')])
    assert settled(c,request(c,s,'请修改当前Word'))['run']['status']=='completed'
    files=c.get('/api/documents?board=chinext&company=300101').json()['items']
    assert len(files)==1 and files[0]['version']==2
    assert c.get(row['download']).status_code==200


def test_listing_preserves_scope_archived_files_and_unavailable_state(client):
    c,runtime,_=client;own=session(runtime);other=session(runtime,'300102','其他公司')
    provider(runtime,lambda *_:[draft()])
    for s in (own,other):assert settled(c,request(c,s))['run']['status']=='completed'
    own_row=listing(c,own)['items'][0]
    runtime.store.edit_session(own['id'],archived=True)
    files=c.get('/api/documents?board=chinext&company=300101').json()['items']
    assert len(files)==1 and files[0]['session_id']==own['id'] and files[0]['session_archived'] is True
    (document_store.folder(runtime,own['id'])/(own_row['sha256']+'.docx')).write_bytes(b'corrupt test-only file')
    files=c.get('/api/documents?board=chinext&company=300101').json()['items']
    assert len(files)==1 and files[0]['available'] is False
    assert c.get(files[0]['download']).status_code==409
    assert c.get('/api/documents?board=chinext').status_code==422
    assert c.get('/api/documents?board=innovation&company=300101').status_code==409


def test_text_draft_is_not_a_delivered_word_and_bad_index_is_reported(client):
    c,runtime,_=client;s=session(runtime)
    document_store.publish(runtime,s['id'],[{'title':'仅正文','kind':'announcement','raw':None,
        'snapshot':{'text':'正文尚未制成文件。'},'source_type':'runtime_text'}],0)
    assert c.get('/api/documents?board=chinext&company=300101').json()['items']==[]
    (document_store.folder(runtime,s['id'])/'index.json').write_text('broken test index')
    response=c.get('/api/documents?board=chinext&company=300101').json()
    assert response['items']==[] and '制文会话' in response['warnings'][0]
