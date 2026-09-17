import copy,json,hashlib
from pathlib import Path
from uuid import uuid4
import pytest
from backend import public_sources,knowledge_ops,library_admin
from test_gates import gate_env
from test_pi_runtime import CONFIG,settled
from test_autonomous_control import session,send_auto
from test_library_admin import law


def configure(c,monkeypatch):
    monkeypatch.setenv('DISCLOSURE_TEST_KEY','offline-knowledge')
    r=c.app.state.pi_runtime;r.config_override=CONFIG
    return r


def test_download_read_admit_requires_original_and_browser_confirmation(gate_env,monkeypatch):
    c,_,root=gate_env;r=configure(c,monkeypatch);s=session(c)
    body='第一条 这是隔离测试法条，不是实际法律依据。'
    monkeypatch.setattr(public_sources,'fetch',lambda url,search=False:(('<html><p>'+body+'</p></html>').encode(),'text/html',url))
    received={}
    def model(p,emit,bridge,stop):
        bridge('route_request',{'domain':'knowledge','intent':'refresh','reason':'用户要求入库新法规'})
        source=bridge('knowledge_download',{'url':'https://www.neeq.com.cn/test-law'})['data'];received.update(source)
        page=bridge('knowledge_download_read',{'download_id':source['download_id'],'page':1})['data'];assert body in page['text']
        value={**law(),'id':'new-original-bound-test','article':'第一条','text':body,'effective_to':None,'replaces_source_ids':[]}
        bridge('knowledge_propose',{'operation':'admit','collection':'laws','items':[value],'download_id':source['download_id'],'summary':'入库隔离测试法条'})
    r.runner=model;result=settled(c,send_auto(c,s,'更新法规'))
    assert result['run']['status']=='waiting_knowledge_confirmation',result
    assert all(x['id']!='new-original-bound-test' for x in library_admin.state(root,'laws','chinext')['items'])
    change=result['run']['knowledge_change']
    raw=c.get('/api/chat/runs/'+result['run']['id']+'/source-candidate');assert raw.status_code==200 and hashlib.sha256(raw.content).hexdigest()==received['sha256']
    applied=c.post('/api/chat/runs/'+result['run']['id']+'/knowledge-confirmation',json={'accept':True,'fingerprint':change['fingerprint']});assert applied.status_code==200,applied.text
    row=next(x for x in library_admin.state(root,'laws','chinext')['items'] if x['id']=='new-original-bound-test')
    assert row['sha256']==received['sha256'] and row['review_status']=='pending_professional_review'
    assert (root/row['original_path']).is_file()
    assert not list((root/'work/downloads'/result['run']['id']).glob('*.html'))


def test_knowledge_edit_delete_and_stale_preview(gate_env,monkeypatch):
    c,_,root=gate_env;r=configure(c,monkeypatch);s=session(c)
    # Only copied fixture data is changed.
    added={**law(),'replaces_source_ids':[]};state=library_admin.state(root,'laws','chinext');library_admin.update(root,'laws',[added],state['fingerprint'],'chinext')
    def model(p,emit,bridge,stop):
        bridge('route_request',{'domain':'knowledge','intent':'delete','reason':'用户要求删除指定测试条目'})
        bridge('knowledge_propose',{'operation':'delete','collection':'laws','ids':[added['id']],'summary':'删除单条测试法源'})
    r.runner=model;out=settled(c,send_auto(c,s,'删除指定测试条目'));change=out['run']['knowledge_change']
    endpoint='/api/chat/runs/'+out['run']['id']+'/knowledge-confirmation'
    assert c.post(endpoint,json={'accept':True,'fingerprint':'bad'}).status_code==409
    assert c.post(endpoint,json={'accept':True,'fingerprint':change['fingerprint']}).status_code==200
    assert added['id'] not in {v['id'] for v in library_admin.state(root,'laws','chinext')['items']}
    assert c.post(endpoint,json={'accept':True,'fingerprint':change['fingerprint']}).status_code==200


def test_template_is_created_before_confirmation_and_registered_after(gate_env,monkeypatch):
    c,_,root=gate_env;r=configure(c,monkeypatch);s=session(c)
    original=copy.deepcopy(library_admin.state(root,'profiles','chinext')['items'][0]);original['id']='profile-generated-fixture-'+str(uuid4());original['title']='隔离内容格式模板';original['case_evidence']=[];original['review_status']='untrusted-model-claim'
    def model(p,emit,bridge,stop):
        bridge('route_request',{'domain':'knowledge','intent':'template','reason':'用户要求制作模板'})
        bridge('knowledge_propose',{'operation':'template','collection':'profiles','items':[original],'summary':'依据既有法源和案例制作候选模板'})
    r.runner=model;out=settled(c,send_auto(c,s,'制作模板'));assert out['run']['status']=='waiting_knowledge_confirmation',out
    change=out['run']['knowledge_change'];tpl=change['template'];assert (root/tpl['candidate_path']).is_file()
    file=c.get('/api/chat/runs/'+out['run']['id']+'/template-candidate');assert file.status_code==200 and hashlib.sha256(file.content).hexdigest()==tpl['sha256']
    applied=c.post('/api/chat/runs/'+out['run']['id']+'/knowledge-confirmation',json={'accept':True,'fingerprint':change['fingerprint']});assert applied.status_code==200,applied.text
    assert applied.json()['status']=='applied',applied.text
    registered=next(x for x in library_admin.state(root,'profiles','chinext')['items'] if x['id']==original['id']);assert registered['review_status']=='pending_human_review'
    specs=json.loads((root/'templates/boards/chinext/manifest.json').read_text());created=next(x for x in specs if x['id']=='tpl-'+original['id'])
    assert created['review_status']=='pending_human_review' and (root/'templates'/created['file']).is_file()


def test_fetch_blocks_private_destinations(monkeypatch):
    monkeypatch.setattr(public_sources.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(Exception) as error:public_sources.fetch('https://www.neeq.com.cn/test')
    assert getattr(error.value,'status_code',None)==403
    with pytest.raises(Exception):public_sources.fetch('https://127.0.0.1/secret')


def test_pdf_text_layer_and_empty_scans_keep_page_boundaries(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    w=PdfWriter();p=w.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 700 Td (Test Rule) Tj ET');p[NameObject('/Contents')]=w._add_object(stream)
    w.add_blank_page(width=612,height=792);original=tmp_path/'fixture.pdf';w.write(original)
    output=tmp_path/'extracted.json';public_sources.extract(original,output);data=json.loads(output.read_text())
    assert [p['page'] for p in data['pages']]==[1,2] and 'Test Rule' in data['pages'][0]['text']
    assert data['empty_pages']==[2] and data['text_completeness']=='text_layer_with_unread_or_blank_pages'
    blank=PdfWriter();blank.add_blank_page(width=612,height=792);blank.write(tmp_path/'scan.pdf')
    public_sources.extract(tmp_path/'scan.pdf',output);assert json.loads(output.read_text())['requires_ocr']


def test_empty_or_mismatched_edit_cannot_reach_confirmation(gate_env,monkeypatch):
    from fastapi import HTTPException
    c,_,root=gate_env;r=configure(c,monkeypatch);s=session(c)
    record=library_admin.state(root,'laws','chinext')['items'][0]
    def model(p,emit,bridge,stop):
        bridge('route_request',{'domain':'knowledge','intent':'edit','reason':'编辑指定条目'})
        for payload in [
            {'ids':[record['id']],'items':[]},
            {'ids':['a-different-id'],'items':[{'id':record['id'],'title':'changed'}]},
        ]:
            with pytest.raises(HTTPException) as error:
                bridge('knowledge_propose',{'operation':'edit','collection':'laws','summary':'范围测试',**payload})
            assert error.value.status_code==422
        emit({'type':'done'})
    r.runner=model;out=settled(c,send_auto(c,s,'编辑条目'))
    assert 'knowledge_change' not in out['run']
    assert next(x for x in library_admin.state(root,'laws','chinext')['items'] if x['id']==record['id'])['title']==record['title']
