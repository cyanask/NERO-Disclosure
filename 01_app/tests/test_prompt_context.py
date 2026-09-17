"""Prompt projection reduces duplicate data without changing the business source."""
import copy,json
from backend.agent_tasks import prompt_context
from backend.agent_models import PlanCandidate
from test_autonomous_control import control,send_auto
from test_continuous_runtime import setup,runner_for
from test_pi_runtime import settled


def test_projection_keeps_source_text_conditions_versions_and_user_decisions():
    source={'id':'law','text':'第一条 原句、定义与例外均保留。','effective_from':'2025-01-01',
            'effective_to':None,'as_of':'2026-09-14','url':'https://official.invalid/law',
            'board_applicability':{'note':'仅在该条件成立时适用'},'import_provenance':{'unused':'metadata'*100}}
    context={'stage':'plan','claim_id':'private-lease','scope_ref':{'company_name':'测试'},
             'sources':[source],'event':{'company_name':'测试','facts':{'amount':123},
                'assessment':{'summary':'需要披露','citations':[source],'producer':{'run':'historical-run'}},
                'approval_records':[{'node':'assessment','state':'current','decision':'prepare_voluntary','reason':'保留审阅决定'}],
                'verified_stages':{'assessment':{'status':'PASS','checks':[{'huge':'diagnostic'*100}]}},
                'agent_tasks':[{'huge':'old history'}],'audit':[{'huge':'old audit'}]},
             'result_schema':PlanCandidate.model_json_schema()}
    original=copy.deepcopy(context);result=prompt_context(context)
    assert context==original
    assert result['sources'][0]['text']==source['text']
    for key in ('effective_from','effective_to','as_of','board_applicability','url'):
        assert result['sources'][0][key]==source[key]
    assert result['event']['assessment']['citations'][0]['text_ref']
    assert result['event']['approval_records'][0]['reason']=='保留审阅决定'
    assert result['event']['facts']=={'amount':123}
    assert 'claim_id' not in result and 'agent_tasks' not in result['event']
    # A business field named title must survive stripping JSON Schema annotations.
    assert result['result_schema']['$defs']['PlannedDocument']['properties']['title']['type']=='string'
    assert len(json.dumps(result,ensure_ascii=False))<len(json.dumps(context,ensure_ascii=False))


def test_different_source_versions_are_never_deduplicated():
    current={'id':'law','text':'现行原文','effective_from':'2026-01-01'}
    old={'id':'law','text':'历史原文','effective_from':'2025-01-01'}
    result=prompt_context({'sources':[current],'event':{'assessment':{'citations':[old]}}})
    assert result['event']['assessment']['citations'][0]['text']=='历史原文'
    assert result['sources'][0]['text']=='现行原文'


def test_per_document_text_is_kept_once_and_templates_refer_to_identical_sections():
    sections=[{'id':'s','fields':[{'prompt':'真实字段'}]}]
    result=prompt_context({'event':{'draft':{'text':'仅供显示的重复汇总','documents':[{'text':'完整正文'}]}},
        'profiles':[{'id':'p','sections':sections}], 'templates':[{'id':'t','profile_id':'p','sections':sections}]})
    assert result['event']['draft']['documents'][0]['text']=='完整正文'
    assert 'text' not in result['event']['draft']
    assert result['templates'][0]['sections_ref'] and result['profiles'][0]['sections']==sections
    context={'profiles':[{'id':'p','sections':sections}],
             'templates':[{'id':'t','profile_id':'p','sections':[dict(sections[0],official_blocks=[1,9])]}]}
    result=prompt_context(context)
    assert result['templates'][0]['sections'][0]['official_blocks']==[1,9]
    assert result['templates'][0]['sections'][0]['fields_ref']
    assert result['profiles'][0]['sections'][0]['fields']==sections[0]['fields']


def test_real_node_context_projection_preserves_continuous_handoff(control):
    client,runtime,_=control;session,event=setup(client,runtime,'word')
    original=runtime.system_for;measurements=[]
    def measure(context):
        if context.get('stage') in ('assessment','plan','template','draft'):
            before={k:v for k,v in context.items() if k not in ('verification_gate','case_candidates')}
            after=prompt_context(context)
            measurements.append({'stage':context['stage'],'before_chars':len(json.dumps(before,ensure_ascii=False)),
                                 'after_chars':len(json.dumps(after,ensure_ascii=False))})
            assert after['event']['facts']==context['event']['facts']
        result=original(context)
        assert 'A应完整给出条件性文件和内容要求' not in result
        return result
    runtime.system_for=measure;runtime.runner=runner_for(runtime,True)
    # The real Node context projection covers four continuous stages; allow the
    # bounded fixture up to one minute without weakening any state assertions.
    output=settled(client,send_auto(client,session,'完成隔离工作稿并在全文确认前停止',expected_revision=event['revision']),timeout=60)
    assert output['run']['status']=='waiting_approval',output['run']
    assert [row['stage'] for row in measurements]==['assessment','plan','template','draft']
    assert all(row['after_chars']<row['before_chars'] for row in measurements)
    assert not client.get('/api/events/'+event['id']).json().get('approval_records')
    print('PROMPT_PROJECTION '+json.dumps(measurements,ensure_ascii=False))
