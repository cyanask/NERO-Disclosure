import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend import conversation_history


def test_legacy_replay_keeps_roles_and_all_rounds(tmp_path):
    model={'api':'openai-completions','provider':'fixture','id':'m'}
    runs=[{'id':str(i),'session_id':'s','stage':'chat','model':model} for i in range(14)]
    def journal(rid,after=0):
        return [{'kind':'user','body':{'text':'question '+rid},'at':1,'seq':1},{'kind':'assistant','body':{'text':'answer '+rid},'at':2,'seq':2}]
    runtime=SimpleNamespace(directory=tmp_path,store=SimpleNamespace(runs=lambda sid:list(reversed(runs)),journal=journal))
    messages=conversation_history.load(runtime,runs[-1])
    assert len(messages)==26
    assert messages[0]['role']=='user' and messages[0]['content']=='question 0'
    assert messages[1]['role']=='assistant' and messages[1]['content'][0]['text']=='answer 0'
    assert conversation_history.load(runtime,{**runs[-1],'stage':'lifecycle'})==[]


def test_private_replay_is_bound_to_its_session_and_run_and_keeps_tool_pairs(tmp_path):
    old={'id':'r1','session_id':'s','stage':'chat','model':{}}
    current={'id':'r2','session_id':'s','stage':'auto','model':{}}
    runtime=SimpleNamespace(directory=tmp_path,store=SimpleNamespace(runs=lambda sid:[current,old],journal=lambda *args:[]))
    path=conversation_history.state_path(runtime,old);path.parent.mkdir(parents=True)
    value={'schema':1,'session_id':'s','run_id':'r1','messages':[{'role':'toolResult','toolCallId':'saved-call','content':[]}]}
    path.write_text(json.dumps(value))
    assert conversation_history.load(runtime,current)==value['messages']
    value['session_id']='another-session';path.write_text(json.dumps(value))
    with pytest.raises(HTTPException):conversation_history.load(runtime,current)


def test_replay_removes_internal_retries_without_rewriting_source_or_losing_draft(tmp_path):
    old={'id':'r1','session_id':'s','stage':'document','status':'incomplete','model':{}}
    current={**old,'id':'r2'}
    retry='当前业务节点尚未通过工具登记结果，文字答复不代表已完成。请调用 submit_candidate'
    rows=[{'kind':'user','body':{'text':'先出Word，资料缺失留空'}},
          {'kind':'assistant','body':{'text':'待补草稿正文'}}]
    runtime=SimpleNamespace(directory=tmp_path,store=SimpleNamespace(runs=lambda sid:[current,old],journal=lambda *args:rows))
    messages=[{'role':'user','content':rows[0]['body']['text']},
              {'role':'assistant','content':[{'type':'text','text':'待补草稿正文'}]},
              {'role':'user','content':retry},
              {'role':'assistant','content':[{'type':'text','text':'没有工具，重复指令不会改变事实'}]},
              {'role':'user','content':'new retry','runtime_control':'completion_repair'},
              {'role':'assistant','content':[{'type':'toolCall','name':'assess_document_readiness','id':'t','arguments':{}}]},
              {'role':'toolResult','toolCallId':'t','content':[]}]
    path=conversation_history.state_path(runtime,old);path.parent.mkdir(parents=True)
    original=json.dumps({'schema':1,'session_id':'s','run_id':'r1','messages':messages});path.write_text(original)
    result=conversation_history.load(runtime,current)
    assert [m['content'] for m in result if m['role']=='user']==[rows[0]['body']['text']]
    assert '待补草稿正文' in json.dumps(result,ensure_ascii=False)
    assert '重复指令不会改变事实' not in json.dumps(result,ensure_ascii=False)
    assert result[-1]['toolCallId']=='t' and result[-2]['content'][0]['id']=='t'
    assert path.read_text()==original


def test_real_user_quoting_internal_text_is_not_removed():
    text=conversation_history.CONTROL_PREFIXES[0]+'，请解释这个错误。'
    runtime=SimpleNamespace(store=SimpleNamespace(journal=lambda *args:[{'kind':'user','body':{'text':text}}]))
    messages=[{'role':'user','content':text}]
    assert conversation_history.replay_projection(runtime,[{'id':'r'}],messages)==messages
