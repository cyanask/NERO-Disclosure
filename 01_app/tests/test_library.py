"""Public-seam tests for scope, evidence preservation and profile handoff."""
import json
import hashlib
from pathlib import Path
from uuid import uuid4
import pytest
from test_agent_tasks import env,event,post,latest,advance,claimed,submit,candidate
from conftest import KNOWLEDGE, ROOT
BOARD=KNOWLEDGE/'data/public/boards/chinext'
PROFILES=json.loads((BOARD/'profiles.json').read_text())


def test_source_index_is_complete_and_unique():
    catalog=json.loads((BOARD/'catalog.json').read_text())
    rows=catalog['sources'];assert len({r['id'] for r in rows})==len(rows)
    instruments=[i['id'] for i in json.loads((BOARD/'instruments.json').read_text())]
    registered={r.get('instrument_id') for r in rows}
    assert set(instruments) <= registered
    for row in rows:
        for key in ('id','title','article','text','url','effective_from','as_of'):
            assert row.get(key),f'{row.get("id")} 缺少 {key}'
    for row in rows+catalog['cases']:
        for key,hash_key in [('original_path','sha256'),('document_path','document_sha256')]:
            if row.get(key):assert hashlib.sha256((KNOWLEDGE/row[key]).read_bytes()).hexdigest()==row[hash_key]


def test_all_fifteen_profiles_have_primary_format_and_real_case_evidence():
    c=json.loads((BOARD/'catalog.json').read_text());cases={x['id']:x for x in c['cases']}
    numbers={p['official_format_number'] for p in PROFILES}
    assert {'szse-01','szse-03','szse-17','szse-61','szse-63'} <= numbers
    assert all(n.startswith('szse-') for n in numbers)
    for p in PROFILES:
        assert p['format_evidence']['source_id'] in p['normative_source_ids']
        # 与 library_admin.validate 同一条件：没有案例依据时必须显式标记待补，
        # 其余情况必须至少有一条可定位的案例证据。
        if not p['case_evidence']:
            assert p['scope_review_status']=='format_and_case_evidence_pending',p['id']
        assert p['sections'] and not p['review']['human_acceptance']
        assert all(any(e['observed_sections']) for e in p['case_evidence'])
        missing=[e['case_id'] for e in p['case_evidence'] if e['case_id'] not in cases]
        assert not missing,f"{p['id']} 仍引用已删除的案例：{missing}；需重新挑选案例并核对 observed_sections"
        for ev in p['case_evidence']:
            row=cases[ev['case_id']]
            pages=json.loads((KNOWLEDGE/row['document_path']).read_text())['pages']
            for excerpt in ev['observed_sections']:
                assert excerpt['quote'] in next(pg['text'] for pg in pages if pg['page']==excerpt['page'])


@pytest.mark.knowledge_pack
def test_dedicated_search_and_page_read(env):
    c,tokens,_,_=env
    r=c.get('/api/library/search',params={'board':'chinext','collection':'laws','q':'关联交易','limit':2})
    assert r.status_code==200 and r.json()['total']>2 and len(r.json()['items'])==2
    assert c.get('/api/library/search',params={'board':'chinext','collection':'laws','limit':101}).status_code==422
    r=c.get('/api/library/search',params={'board':'chinext','collection':'cases','kind':'shareholder_notice','view':'candidates'})
    row=next(x for x in r.json()['items'] if x.get('document_path'))
    doc=c.get('/api/library/items/'+row['id'],params={'board':'chinext','page':1}).json()
    assert len(doc['pages'])==1 and doc['pages'][0]['page']==1
    assert c.get('/api/library/items/'+row['id'],params={'board':'chinext','page':999}).status_code==404
    admitted=c.get('/api/library/search',params={'board':'chinext','collection':'cases','q':'董事会决议'}).json()
    with_original=next(x for x in admitted['items'] if x.get('original_path'))
    a=c.get('/api/library/assets/'+with_original['id'],params={'board':'chinext'});assert a.content.startswith(b'%PDF')
    assert c.get('/api/library/search',params={'board':'chinext','collection':'models'}).status_code==422


def test_law_directory_then_articles(env):
    c,tokens,path,_=env
    directory=c.get('/api/library/search',params={'board':'chinext','collection':'laws','view':'groups'}).json()
    assert directory['view']=='groups' and directory['items']
    law=directory['items'][0]
    assert law['article_count']>0 and 'article' not in law
    detail=c.get('/api/library/items/'+law['id'],params={'board':'chinext','view':'document'}).json()
    assert detail['id']==law['id'] and len(detail['articles'])==law['article_count']
    assert all(article.get('article') for article in detail['articles'][:5])
    flat=c.get('/api/library/search',params={'board':'chinext','collection':'laws','view':'items','limit':2}).json()
    assert flat['items'] and flat['items'][0].get('article')


@pytest.mark.knowledge_pack
def test_chinext_blacklist_cases_are_matter_based_filterable_and_source_bound(env):
    c,_,_,_=env
    base={'board':'chinext','collection':'blacklist_cases'}
    result=c.get('/api/library/search',params=base).json()
    assert result['total']==5 and result['blacklist_scope_summary']=={
        'admitted':5,'candidates':0,'boundary':'只有官方处理决定和违规时点板块均已核实的事项进入已核实视图。'}
    assert c.get('/api/library/search',params={**base,'kind':'annual_report'}).json()['total']==5
    assert c.get('/api/library/search',params={**base,'violation':'material_omission'}).json()['total']==1
    assert c.get('/api/library/search',params={**base,'disposition':'administrative_penalty','year':2025}).json()['total']==1
    found=c.get('/api/library/search',params={**base,'q':'销售返利'}).json()
    assert found['items'][0]['id']=='blacklist-chinext-300301-2025-6'
    assert found['retrieval_backend']=='sqlite_fts5+canonical_json' and found['passages'][0]['page']==1
    detail=c.get('/api/library/items/'+found['items'][0]['id'],params={'board':'chinext'}).json()
    assert len(detail['evidence_documents'])==2 and not detail['evidence_complete']
    decision=next(x for x in detail['evidence_documents'] if x['role']=='regulatory_decision')
    asset=c.get(f"/api/library/items/{detail['id']}/evidence/{decision['id']}",params={'board':'chinext'})
    assert asset.status_code==200 and b'csrc.gov.cn' in asset.content


@pytest.mark.parametrize('profile',PROFILES,ids=lambda p:p['id'])
def test_profile_selects_matching_template(profile):
    from backend.domain import Seeds
    from backend.library import applicable_templates
    e={'kind':profile['kind'],'layer':profile['layers'][0],'facts':{'disclosure_profile_id':profile['id']}}
    templates=applicable_templates(Seeds(KNOWLEDGE),e)
    assert templates and all(t['profile_id']==profile['id'] for t in templates)
    assert templates[0]['sections']==profile['sections']


def test_cases_cannot_substitute_for_law_and_a_changed_original_is_rejected(env):
    c,tokens,path,_=env;e=event(c);task,lease=claimed(c,e,tokens[0]);v=candidate()
    data=json.loads((path/'data/public/boards/chinext/catalog.json').read_text());case=next(r for r in data['cases'] if r.get('original_path'))
    v['source_ids']=[case['id']]
    assert submit(c,e,task,lease,tokens[0],v).status_code==422
    original=path/case['original_path'];original.write_bytes(original.read_bytes()+b'\nchanged')
    # An admitted case participates in the assessment fingerprint, so changing
    # its registered original invalidates the open task and the asset read.
    assert latest(c,e)['agent_tasks'][-1]['status']=='stale'
    assert c.get('/api/library/assets/'+case['id'],params={'board':'chinext'}).status_code==409
