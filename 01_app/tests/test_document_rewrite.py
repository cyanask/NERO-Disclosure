"""Regenerating an unconfirmed memo must not be confined to its old short draft."""
import json
import pytest
from backend import document_files, document_store
from test_pi_runtime import client, new_session, settled
from test_document_runtime import draft, listing, provider, readiness, request


@pytest.mark.parametrize('source_type',['runtime','anchored_revision','reply_render'])
def test_reorganize_memo_can_replace_short_body_and_retains_old_version(client,source_type):
    c,runtime,_=client;s,_=new_session(c)
    provider(runtime,lambda *_:[draft('备忘录',text='旧短稿，只剩结论。')])
    assert settled(c,request(c,s))['run']['status']=='completed'
    previous=listing(c,s)['items'][0]
    old_bytes=c.get(previous['download']).content
    index=document_store.load(runtime,s['id'])
    index['documents'][0]['versions'][0]['source_type']=source_type
    (document_store.folder(runtime,s['id'])/'index.json').write_text(json.dumps(index))
    text='\n'.join(f'第{i}项：完整保留原会话中的问题、条件、程序说明和待核事项。' for i in range(100))[:2422]
    def runner(packet,emit,bridge,stop):
        # Reproduce the real route: the model chose revise for "重新整理".
        routed=bridge('route_request',{'domain':'disclosure','intent':'document','document_kind':'analysis',
            'document_action':'revise','target_document_id':previous['document_id'],'reason':'重新整理备忘录'})
        assert '不把已有短稿当作内容范围' in routed['next_context']['system']
        bridge('read_document',{'document_id':previous['document_id']})
        doc=draft('备忘录',document_id=previous['document_id'],base_version=1,text=text)
        bridge('assess_document_readiness',{'documents':[readiness(doc)],'request_quote':packet['prompt'],'decision':'assess'})
        assert bridge('make_word',{'documents':[doc]})['data']['documents']
        emit({'type':'done'})
    runtime.runner=runner
    out=settled(c,request(c,s,'请重新整理成备忘录word'))
    assert out['run']['status']=='completed',out
    current=listing(c,s)['items'][0]
    assert current['version']==2 and current['document_id']==previous['document_id']
    assert document_store.snapshot(runtime,s['id'],current['document_id'])['text']==text
    assert text in document_files.inspect(c.get(current['download']).content)['text']
    assert c.get(previous['download']).content==old_bytes
    assert current['review_status']=='pending' and out['run']['document_attempts']==1
