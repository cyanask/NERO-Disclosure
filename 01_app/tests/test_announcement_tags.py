import json
import pytest
from fastapi import HTTPException
from backend import announcement_tags as tags, announcement_schedule as schedule, announcement_index as index
from backend.file_ingestion import classify


@pytest.mark.parametrize('title,expected,absent',[
    ('关于召开2025年第一次临时股东大会的通知','shareholder','board'),
    ('2025年年度股东会决议公告','shareholder','annual'),
    ('律师事务所关于公司2025年年度股东会的法律意见书','shareholder','annual'),
    ('股东会议事规则','governance','shareholder'),
    ('董事会秘书工作细则','governance','board'),
    ('2025年度董事会工作报告','governance','board'),
    ('2025年年度报告','annual','board'),
    ('2026年半年度报告摘要','half_year','annual'),
    ('2025年三季度报告','quarter','annual'),
    ('首次公开发行股票并在创业板上市招股说明书','ipo','refinancing'),
    ('第四届董事会第三次会议决议公告','board','shareholder'),
    ('2025年年度审计报告','audit','annual'),
    ('关于2026年度对外担保额度预计的公告','guarantee','related'),
])
def test_purpose_not_mentions(title,expected,absent):
    result=tags.classify({'title':title}, {'pages':[{'page':1,'text':'本公司及董事会保证。股东大会召开，讨论年报、担保、关联交易及减持。'}]})
    assert expected in result['tags'] and absent not in result['tags']


def test_multi_labels_forms_and_no_body_pollution():
    assert set(tags.classify_title('保荐机构关于使用闲置募集资金进行现金管理的核查意见')[0])=={'proceeds','treasury','audit'}
    assert tags.classify_title('2025年年度报告更正公告')[1]==['full','correction']
    assert tags.classify_title('2025年年度报告摘要')[1]==['summary']
    assert tags.classify({'title':'未知资料'},{'pages':[{'page':1,'text':'本公司及董事会保证。股东会决议公告'},{'page':2,'text':'首次公开发行股票'}]})['tags']==['unclassified']
    fallback=tags.classify({'title':'资料附件'},{'pages':[{'page':1,'text':'2025年年度报告\n本公司及董事会保证'}]})
    assert fallback['tags']==['annual'] and fallback['evidence']['page']==1
    assert classify('首次公开发行股票并在创业板上市发行公告')=='ipo'
    assert classify('股东会议事规则')=='corporate_governance'


def test_manual_correction_version_binding():
    row={'title':'未知资料','document_sha256':'v1'}
    manual=schedule.correction(row,{'tags':['annual'],'forms':['full']})
    row['classification_override']=manual
    assert tags.classify(row)['status']=='manual'
    assert tags.classify({**row,'document_sha256':'v2'})['status']=='pending_pi'
    with pytest.raises(HTTPException):schedule.correction(row,{'tags':['unclassified','annual'],'forms':['full']})
    with pytest.raises(HTTPException):schedule.correction(row,{'tags':['not-known'],'forms':['full']})


def make_catalog(root,company,titles):
    from backend.library_admin import sha
    base=root/'data/client_announcements/chinext'/company;base.mkdir(parents=True)
    rows=[]
    for n,title in enumerate(titles):
        original=base/f'{n}.original';original.write_bytes(b'original')
        doc=base/f'{n}.json';doc.write_text(json.dumps({'pages':[{'page':1,'text':title+'\n本公司及董事会保证。\n检索专用证据在这里。'}]},ensure_ascii=False))
        rows.append({'id':f'{company}-{n}','title':title,'published_at':'2025-06-04','kind':'unclassified','page_count':1,
            'original_path':str(original.relative_to(root)),'sha256':sha(original.read_bytes()),
            'document_path':str(doc.relative_to(root)),'document_sha256':sha(doc.read_bytes())})
    (base/'catalog.json').write_text(json.dumps({'items':rows,'company_name':'测试','revision':0,'coverage':{'complete':False}},ensure_ascii=False))
    index.sync(root,'chinext',company)


def test_index_facets_fulltext_scope_and_rebuild(tmp_path):
    make_catalog(tmp_path,'300001',['2025年年度报告','股东会议事规则','2025年年度股东会决议公告'])
    make_catalog(tmp_path,'300002',['2025年年度股东会决议公告'])
    result=schedule.listing(tmp_path,'chinext','300001',tag='shareholder')
    assert [r['id'] for r in result['items']]==['300001-2']
    assert result['matched_total']==3 and result['total']==1
    assert next(t['count'] for t in result['tag_options'] if t['id']=='shareholder')==1
    assert schedule.listing(tmp_path,'chinext','300001',tag='shareholder',form='notice')['total']==0
    fulltext=schedule.listing(tmp_path,'chinext','300001',q='检索专用证据',tag='annual')
    assert fulltext['total']==1 and fulltext['retrieval_backend']=='company_sqlite_fts5'
    assert schedule.listing(tmp_path,'chinext','300001',q='专用',tag='annual')['total']==1
    catalog=index.paths(tmp_path,'chinext','300001')[1];value=json.loads(catalog.read_text())
    row=value['items'][0];row['classification_override']=schedule.correction(row,{'tags':['half_year'],'forms':['summary']})
    catalog.write_text(json.dumps(value,ensure_ascii=False));index.sync(tmp_path,'chinext','300001')
    assert schedule.listing(tmp_path,'chinext','300001',tag='annual')['total']==0
    assert schedule.listing(tmp_path,'chinext','300001',tag='half_year')['items'][0]['classification']['status']=='manual'
    row['deleted_at']='2025-06-05';catalog.write_text(json.dumps(value));index.sync(tmp_path,'chinext','300001')
    assert schedule.listing(tmp_path,'chinext','300001',tag='half_year')['total']==0
    assert schedule.listing(tmp_path,'chinext','300001',deleted=True,tag='half_year')['total']==1
