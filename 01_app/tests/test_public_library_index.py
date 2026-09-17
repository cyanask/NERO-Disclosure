"""Law canonical-row FTS and case page/section FTS remain source-bound."""
import hashlib,json
import os
from pathlib import Path
from backend.domain import Seeds
from backend.library import search
from backend.public_library_index import status
from backend import announcement_history,announcement_index
from scripts.sync_sqlite_library import sync_library_db

def setup(tmp_path):
    public=tmp_path/'data/public/boards/chinext';public.mkdir(parents=True)
    assets=tmp_path/'data/public/test';assets.mkdir(parents=True)
    original=assets/'case.pdf';original.write_bytes(b'%PDF- synthetic fixture')
    document=assets/'case.json';document.write_text(json.dumps({'pages':[{'page':1,'text':'第一部分 交易概况\n首页摘要。'},{'page':2,'text':'第二章 风险因素\n后页独有供应链中断风险。'}]},ensure_ascii=False))
    pending=assets/'pending.json';pending.write_text(json.dumps({'pages':[{'page':1,'text':'待核资料独有汽车渠道事项。'}]},ensure_ascii=False))
    decision=assets/'decision.json';decision.write_text(json.dumps({'pages':[{'page':1,'text':'行政处罚决定书\n年度报告存在虚假记载，责令改正并处以罚款。'}]},ensure_ascii=False))
    law={'id':'law-a5','title':'测试信息披露规则','article':'第五条','text':'第五条 信息披露义务人应当及时披露。','instrument_id':'law','source_kind':'official_rule','library_board':'chinext','layers':['chinext'],'effective_from':'2025-01-01','as_of':'2026-09-01','url':'https://www.neeq.com.cn/law'}
    case={'id':'case-admitted','title':'重大事项公告','company':'测试公司','stock_code':'800001','kind':'related_transaction','published_at':'2026-01-01','library_board':'chinext','layers':['chinext'],'verification_status':'official_original_indexed','eligible_as_case_evidence':True,'layer_at_publication':'chinext','case_scope':{'verified_board_at_publication':'chinext'},'case_admission_status':'admitted_as_official_case','original_path':str(original.relative_to(tmp_path)),'document_path':str(document.relative_to(tmp_path)),'sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'document_sha256':hashlib.sha256(document.read_bytes()).hexdigest(),'page_count':2,'text':'首页摘要。'}
    candidate={'id':'case-pending','title':'待核案例','company':'待核公司','kind':'related_transaction','library_board':'chinext','layers':['chinext'],'verification_status':'imported_source_unverified','eligible_as_case_evidence':False,'case_admission_status':'pending_official_original','document_path':str(pending.relative_to(tmp_path)),'document_sha256':hashlib.sha256(pending.read_bytes()).hexdigest(),'page_count':1,'text':'待核资料。'}
    blacklist={'id':'blacklist-admitted','title':'测试公司年报虚假记载案','company':'测试公司','stock_code':'800001','library_board':'chinext','layers':['chinext'],'source_kind':'blacklist_case','layer_at_misconduct':'chinext','case_scope':{'verified_board_at_misconduct':'chinext'},'admission_status':'admitted','verification_status':'official_decision_verified','disposition_type':'administrative_penalty','authority':'测试监管机关','decision_date':'2026-02-01','decision_number':'测试〔2026〕1号','announcement_kinds':['annual_report'],'violation_types':['false_record'],'wrongdoing_summary':'年报数据不实。','regulator_finding':'构成信息披露违法。','drafting_checks':['核对收入真实性'],'evidence_complete':False,'evidence_documents':[{'id':'decision-1','role':'regulatory_decision','title':'行政处罚决定书','url':'https://www.gov.cn/test','original_path':str(original.relative_to(tmp_path)),'document_path':str(decision.relative_to(tmp_path)),'sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'document_sha256':hashlib.sha256(decision.read_bytes()).hexdigest(),'page_count':1}]}
    (public/'catalog.json').write_text(json.dumps({'board':'chinext','sources':[law],'cases':[case,candidate],'blacklist_cases':[blacklist]},ensure_ascii=False))
    for name,value in [('profiles.json',[]),('instruments.json',[{'id':'law','title':'测试信息披露规则','library_board':'chinext','layers':['chinext']}]),('rules.json',[])]: (public/name).write_text(json.dumps(value,ensure_ascii=False))
    templates=tmp_path/'templates/boards/chinext';templates.mkdir(parents=True);(templates/'manifest.json').write_text('[]');(templates/'layout_profiles.json').write_text('[]')
    return Seeds(tmp_path,'chinext'),document

def test_law_and_case_fts_use_current_rebuildable_index(tmp_path):
    seeds,document=setup(tmp_path);counts=sync_library_db(root=tmp_path,board='chinext')
    assert counts['law_fts_rows']==1 and counts['case_pages']==3 and counts['case_units']>=5
    current=status(tmp_path,'chinext');assert current['status']=='current' and current['coverage']['admitted_cases']==1
    laws=search(seeds,'laws','信息披露义务人');assert laws['retrieval_backend']=='sqlite_fts5+canonical_json' and laws['items'][0]['id']=='law-a5'
    cases=search(seeds,'cases','供应链中断风险');assert cases['items'][0]['id']=='case-admitted'
    assert cases['passages'][0]['page']==2 and cases['passages'][0]['anchor']=='page:2:line:2'
    assert search(seeds,'cases','汽车渠道',view='items')['total']==0
    pending=search(seeds,'cases','汽车渠道',view='candidates');assert pending['items'][0]['id']=='case-pending' and not pending['items'][0]['eligible_as_case_evidence']
    blacklist=search(seeds,'blacklist_cases','责令改正');assert blacklist['items'][0]['id']=='blacklist-admitted'
    assert blacklist['passages'][0]['page']==1 and blacklist['retrieval_backend']=='sqlite_fts5+canonical_json'
    assert search(seeds,'blacklist_cases','责令改正',kind='annual_report')['total']==1
    assert search(seeds,'blacklist_cases','责令改正',violation='material_omission')['total']==0
    document.write_text(document.read_text()+' ')
    assert status(tmp_path,'chinext')['status']=='stale'
    fallback=search(seeds,'cases','供应链中断风险');assert fallback['retrieval_backend']=='canonical_json' and not fallback['catalog_indexed'] and fallback['total']==0


def test_indexes_survive_timestamp_only_migration_but_reject_same_size_changes_and_deletes(tmp_path):
    seeds,document=setup(tmp_path);sync_library_db(root=tmp_path,board='chinext')
    original=document.read_bytes();stamp=document.stat();os.utime(document,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1_000_000))
    assert status(tmp_path,'chinext')['status']=='current'
    assert search(seeds,'cases','供应链中断风险')['total']==1
    document.write_bytes(original[:-1]+(b'X' if original[-1:]!=b'X' else b'Y'))
    assert status(tmp_path,'chinext')['status']=='stale'
    document.unlink()
    assert status(tmp_path,'chinext')['status']=='stale'

    base=tmp_path/'data/client_announcements/chinext/300001';base.mkdir(parents=True)
    original_path=base/'original.pdf';original_path.write_bytes(b'%PDF- migration')
    parsed=base/'parsed.json';parsed.write_text(json.dumps({'pages':[{'page':1,'text':'迁移后正文专属词。'}]},ensure_ascii=False),encoding='utf-8')
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    row={'id':'announcement-migration','title':'迁移公告','published_at':'2026-09-01','page_count':1,
         'original_path':original_path.relative_to(tmp_path).as_posix(),'document_path':parsed.relative_to(tmp_path).as_posix(),
         'sha256':digest(original_path),'document_sha256':digest(parsed)}
    (base/'catalog.json').write_text(json.dumps({'board':'chinext','stock_code':'300001','company_name':'迁移公司','items':[row],
        'coverage':{'complete':False},'revision':1},ensure_ascii=False),encoding='utf-8')
    announcement_index.sync(tmp_path,'chinext','300001')
    stamp=original_path.stat();os.utime(original_path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1_000_000))
    assert announcement_index.status(tmp_path,'chinext','300001')['status']=='current'
    assert announcement_history.search(tmp_path,{'layer':'chinext','stock_code':'300001'},'正文专属词')['total']==1
    original_path.write_bytes(b'%PDF- changed!!')
    assert announcement_index.status(tmp_path,'chinext','300001')['status']=='stale'
    original_path.unlink()
    assert announcement_index.status(tmp_path,'chinext','300001')['status']=='stale'
