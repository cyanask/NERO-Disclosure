"""Candidate contract: citations, stage schema limits and the evaluation receipt."""
import pytest
from fastapi import HTTPException
from backend import candidate_contract


def task(stage='assessment', output_mode='text'):
    return {'id':'t1','stage':stage,
            'snapshot':{'event':{'id':'e1','revision':3,'output_mode':output_mode,'layer':'chinext'},
                        'catalog':{'sources':[{'id':'s1','title':'法律一'},{'id':'s2','title':'法律二'}],
                                   'cases':[{'id':'case-1','title':'案例一'}],'profiles':[{'id':'fmt1','normative_source_ids':['s1']}]},
                        'templates':[{'id':'tpl1'}]}}


def plan_payload(source_id='s1',**overrides):
    payload={'items':[{'id':'i1','title':'章节','source_ids':[source_id]}],
             'documents':[{'document_id':'d1','title':'公告','purpose':'public','necessity':'required','applicability':'适用',
                           'stage':'current','producer':'公司','production':'company_draft','timing':'董事会后','source_ids':[source_id]}],
             'requirements':[{'requirement_id':'r1','document_id':'d1','section_id':'s1','topic':'主题','granularity':'粒度',
                              'necessity':'required','applicability':'适用','source_ids':[source_id],
                              'historical_relation':'new','verify_method':'核对原文'}],
             'drafting_gaps':[]}
    payload.update(overrides)
    return payload


def test_plan_candidate_citing_a_registered_source_is_accepted():
    assert candidate_contract.validate(task('plan'),plan_payload())['items'][0]['source_ids']==['s1']


def test_citation_outside_the_bound_snapshot_is_rejected():
    with pytest.raises(HTTPException) as exc:
        candidate_contract.validate(task('plan'),plan_payload(source_id='s9'))
    assert exc.value.status_code==422 and 's9' in exc.value.detail


def test_plan_candidate_rejects_duplicate_item_ids():
    payload=plan_payload(items=[{'id':'i1','title':'章节','source_ids':['s1']},{'id':'i1','title':'章节二','source_ids':['s1']}])
    with pytest.raises(HTTPException) as exc:
        candidate_contract.validate(task('plan'),payload)
    assert exc.value.status_code==422 and '重复' in exc.value.detail


def test_plan_cites_cases_only_when_the_case_is_admitted_evidence():
    # library.admitted_case requires an indexed official original published on the same board.
    bound=task('plan')
    record=bound['snapshot']['catalog']['cases'][0]
    with pytest.raises(HTTPException) as exc:
        candidate_contract.validate(bound,plan_payload(source_id='case-1'))
    assert exc.value.status_code==422 and 'case-1' in exc.value.detail
    record.update(eligible_as_case_evidence=True,verification_status='official_original_indexed',
                  original_path='data/case-1.json',layer_at_publication='chinext',case_scope={'verified_board_at_publication':'chinext'})
    assert candidate_contract.validate(bound,plan_payload(source_id='case-1'))['requirements'][0]['source_ids']==['case-1']


def test_template_candidate_must_match_the_bound_templates():
    assert candidate_contract.validate(task('template'),{'template_id':'tpl1','requirement_map':{'r1':'原文'}})['template_id']=='tpl1'
    with pytest.raises(HTTPException) as exc:
        candidate_contract.validate(task('template'),{'template_id':'tpl9','requirement_map':{'r1':'原文'}})
    assert exc.value.status_code==422 and '模板' in exc.value.detail


def test_missing_required_field_is_reported_as_a_contract_error():
    with pytest.raises(HTTPException) as exc:
        candidate_contract.validate(task(),{'summary':'只有摘要'})
    assert exc.value.status_code==422 and '候选字段不符合当前阶段合同' in exc.value.detail


def test_event_view_reads_top_level_and_item_citations_only():
    catalog={'sources':[{'id':'s1'},{'id':'s2'}],'cases':[{'id':'case-1'}]}
    nested={'source_ids':['s1'],'items':[{'id':'i','source_ids':['case-1']}],
            'matters':[{'reasoning_items':[{'source_id':'s2'}]}]}
    assert [s['id'] for s in candidate_contract.source_view(catalog,candidate_contract.candidate_ids(nested))]==['s1','case-1']


def test_evaluation_receipt_walks_nested_verdicts():
    nested={'source_ids':['s1'],'matters':[{'reasoning_items':[{'source_id':'s2'}]}]}
    assert candidate_contract.candidate_ids(nested,deep=True)=={'s1','s2'}


def test_response_lists_the_candidate_with_its_citations():
    record=task()
    record.update(result={'summary':'候选摘要'},
                  evaluation={'outcome':'waiting_approval','gate':{'semantic_review':[{'verdict':'clear'}]}},
                  candidate_history=[{'attempt':1,'result':{'source_ids':['s2'],'summary':'s'},'outcome':'waiting_approval'}],
                  field_bindings=[{'field':'summary','section_id':'sec1'}])
    body=candidate_contract.response({'id':'e1','revision':3},record)
    assert body['outcome']=='waiting_approval' and body['task_id']=='t1' and body['summary']=='候选摘要'
    assert [s['id'] for s in body['result_snapshot']['sources']]==['s2']
    assert body['semantic_review']==[{'verdict':'clear'}] and body['field_bindings']==[{'field':'summary','section_id':'sec1'}]
