import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from backend import announcement_history, announcement_index
from backend.pi_runtime import PiRuntime


def _company(root, code, count, title_prefix='审查公告'):
    base=root/'data/client_announcements/chinext'/code;base.mkdir(parents=True)
    items=[]
    for number in range(count):
        original=base/f'original-{number}.pdf';original.write_bytes(f'PDF-{code}-{number}'.encode())
        pages=[{'page':page,'text':f'正文专属检索词 样本 {number} 页 {page}。'} for page in range(1,31 if number==0 else 2)]
        document=base/f'parsed-{number}.json';document.write_text(json.dumps({'pages':pages},ensure_ascii=False),encoding='utf-8')
        items.append({'id':f'announcement-{code}-{number}','title':f'{title_prefix} {number}',
                      'published_at':'2026-09-01','page_count':len(pages),
                      'original_path':original.relative_to(root).as_posix(),'document_path':document.relative_to(root).as_posix(),
                      'sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
                      'document_sha256':hashlib.sha256(document.read_bytes()).hexdigest()})
    (base/'catalog.json').write_text(json.dumps({'board':'chinext','stock_code':code,'company_name':'模拟公司'+code,
        'items':items,'coverage':{'complete':False},'revision':1},ensure_ascii=False),encoding='utf-8')
    announcement_index.sync(root,'chinext',code)


def test_history_search_bridge_pages_documents_and_scopes_company(tmp_path):
    root=tmp_path;_company(root,'300001',25);_company(root,'300002',1,'另一公司公告')
    run={'id':'run','stage':'chat','event_id':'conversation:run','board':'chinext','company_code':'300001'}
    runtime=object.__new__(PiRuntime);runtime.root=root
    runtime.store=SimpleNamespace(run=lambda _:run)
    runtime.research_read=lambda rid,name,args,call:call()
    runtime.trace=lambda *args:None
    stop=threading.Event()

    def bridge(query,offset=0):
        return runtime._bridge('run','search_library',{'collection':'client_history','query':query,'offset':offset},stop)['data']

    for query in ('正文专属检索词','审查公告','正文'):
        first=bridge(query);second=bridge(query,20)
        assert first['total']==25 and len(first['items'])==20 and len(second['items'])==5
        assert not {row['id'] for row in first['items']} & {row['id'] for row in second['items']}
    empty=bridge('',20)
    assert empty['total']==25 and len(empty['items'])==5
    body=bridge('正文专属检索词')
    assert len(body['passages'])==20 and len({row['announcement_id'] for row in body['passages']})==20
    other=announcement_history.search(root,{'layer':'chinext','stock_code':'300002'},'正文专属检索词')
    assert other['total']==1 and all(row['id'].startswith('announcement-300002-') for row in other['items'])
