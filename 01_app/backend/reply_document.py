"""A displayed reply is immutable rendering input, not a request to redraft it."""
import time
from fastapi import HTTPException
from . import document_store as store
from .document_schema import obj


def replies(runtime,run):
    result=[]
    for prior in runtime.store.runs(run['session_id']):
        if prior['id']==run['id'] or prior['status']!='completed':continue
        if prior['stage']!='chat' and prior.get('controller_mode')!='native':continue
        cursor=0
        while True:
            rows=runtime.store.journal(prior['id'],after=cursor)
            for row in rows:
                body=row['body']
                if row['kind']=='assistant' and body.get('text') and body.get('stopReason')=='stop' and body.get('phase')!='progress':
                    text=body['text']
                    outcome=prior.get('consultation_result') or {}
                    checksum=store.sha(text.encode())
                    # Verification state is inherited, never re-derived from a hash match.
                    result.append({'run_id':prior['id'],'message_seq':row['seq'],'text':text,'sha256':checksum,
                                   'reviewed':outcome.get('sha256')==checksum and not outcome.get('warnings')})
            if len(rows)<1000:break
            cursor=rows[-1]['seq']
    return result


def bind(runtime,run,run_id,seq):
    # Identifiers must come from the current conversation projection, never another session.
    reply=next((r for r in replies(runtime,run) if r['run_id']==run_id and r['message_seq']==seq),None)
    if not reply:raise HTTPException(422,'请绑定当前会话已完整展示的指定咨询回复')
    return reply


def tool():
    return {'name':'make_word','description':'将本轮绑定的已展示回复原文制作成Word；只排版，不接受模型重写正文。','parameters':obj()}


def render(runtime,rid,args,stop):
    run=runtime.store.run(rid)
    if run['stage']!='document' or run.get('document_action')!='render' or args!={}:raise HTTPException(422,'原回复制文仅接受已绑定的正文，不接受重写内容')
    source=run['reply_source'];current=bind(runtime,run,source['run_id'],source['message_seq'])
    if current['sha256']!=source['sha256'] or store.sha(source['text'].encode())!=source['sha256']:
        raise HTTPException(409,'源回复已变化，文件未生成')
    from .document_runtime import run_script
    from .document_rendering import layout, title_of
    text=source['text'];title=title_of(text,runtime.store.session(run['session_id'])['title'])[:120]
    document={'title':title,'kind':'analysis','template_id':'builtin:analysis','text':text,'pending':[],'basis':[]}
    packet={'kind':'runtime_document','document':document,'layout':layout(runtime.root,run['board']),
            'company_name':runtime.company_scope(run).get('company_name',''),'board':run['board'],
            'generated_at':time.strftime('%Y-%m-%d %H:%M'),'input_fingerprint':store.digest(source),
            'notice':'原回复排版副本，未重新研究或改写；历史回复的事实与规则未完成当前依据核验。' if not source['reviewed'] else '咨询回复排版副本；内容依据复核记录随源回复保留，文件待审阅，未发布。'}
    revision=store.listing(runtime,run['session_id'])['revision']
    raw=run_script(runtime,rid,packet,stop)
    checks={'structure':'passed','body_readback':'passed','source_reply_preserved':True,
            'fact_source_coverage':'inherited_review' if source['reviewed'] else 'historical_unverified','visual_review':'pending_user'}
    snapshot={'document':document,'text':text,'basis':[],'source_reply':source,'checks':checks}
    with runtime.lock:
        current=bind(runtime,run,source['run_id'],source['message_seq'])
        if current['sha256']!=source['sha256']:raise HTTPException(409,'制作期间源回复已变化，未登记文件')
        documents=store.publish(runtime,run['session_id'],[{**document,'raw':raw,'snapshot':snapshot,'checks':checks,
            'warnings':[] if source['reviewed'] else ['仅保留历史回复原文，不代表其中事实和规则已核实。'],
            'source_type':'reply_render','run_id':rid,'template_name':'咨询回复通用版式'}],revision,stop)
        runtime.store.update(rid,documents=documents,outcome='completed')
    runtime.trace(rid,'documents_created',{'documents':documents,'business_state_changed':False})
    return {'data':{'documents':documents,'business_state_changed':False},'terminate':True,'finalize':True}
