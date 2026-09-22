"""Publish consultation text with evidence reminders; findings never withhold the answer."""
from fastapi import HTTPException
from .document_schema import obj
from .document_context import context
from .grounded_text import validate
from .document_store import sha

GUIDE = '''咨询答复调用 submit_consultation 提交 text 和 basis；核验结论只作提醒随答复展示，任何理由都不阻断答复。
basis 的 statement 须逐字复制自本次提交正文中的原句，quote 须是被引来源中的原句；两者定位不到时只生成提醒，不扣留正文。
每项事实、规则、时点、期限、条件和适用性判断都应绑定实际读取的原文；模型记忆、搜索摘要及历史助手回复不是依据。
basis 使用 read_document_context 返回的 user/event 来源编号、library:条款id、download:下载id:页码或 attachment 来源。
用户陈述须明确归属于用户提供的事实，不能把用户问题或操作指令当作法规依据。
外网结果只作线索，须读取原文并核对主体、版本及适用条件。找不到依据时继续查证，并在正文中明确列出未核实部分。
不得用“假设”“建议”等措辞包装无来源的具体义务、期限或肯定结论。依据不足不要求用户重复授权。
正文应标明关键结论的出处、条件及未核实部分；收到提醒时优先在下一轮补齐依据。'''


def tool():
    string={'type':'string','minLength':1}
    return {'name':'submit_consultation','description':'提交咨询回复并附带依据绑定；核验结果作为提醒随答复展示，不阻断发布。',
        'parameters':obj({'text':{'type':'string','minLength':1,'maxLength':100000},
            'basis':{'type':'array','maxItems':100,'items':obj({'statement':string,'source_id':string,'quote':string},['statement','source_id','quote'])}},['text','basis'])}


def submit(runtime,rid,args,stop):
    run=runtime.store.run(rid)
    if run.get('outcome'):raise HTTPException(409,'本轮已结束，不能再次提交答复')
    if not isinstance(args,dict) or set(args)!={'text','basis'}:raise HTTPException(422,'请提交咨询正文和依据绑定')
    try:
        evidence,receipt,warnings=validate(runtime,rid,run,args['text'],args['basis'],context(runtime,run),stop)
    except HTTPException as exc:
        evidence=[];receipt={'source':'unavailable','verdicts':[]}
        warnings=[{'statement':'','source_id':'review:unavailable','quote':'','reason':'依据复核未完成，仅提示不阻断：'+str(exc.detail)}]
    if not args['basis']:
        warnings=[{'statement':'','source_id':'basis:empty','quote':'','reason':'未提供依据绑定，正文结论未完成核验'},*warnings]
    if stop.is_set():raise HTTPException(409,'已取消，未发布正文')
    value={'text':args['text'],'sha256':sha(args['text'].encode()),'basis':evidence,'warnings':warnings,'semantic_review':receipt}
    with runtime.lock:
        if warnings:runtime.trace(rid,'consultation_evidence_warnings',{'issues':warnings,'published':True})
        runtime.store.update(rid,consultation_result=value,outcome='completed')
        runtime.trace(rid,'consultation_verified' if not warnings else 'consultation_published_unverified',
            {'sha256':value['sha256'],'basis_count':len(evidence),'warnings':len(warnings)})
        runtime.trace(rid,'assistant',{'message':-1,'phase':'final','text':value['text'],'stopReason':'stop',
            'evidence_status':'reviewed' if not warnings else 'unverified',
            'warnings':[{**w,'statement':w['statement'][:200],'quote':w['quote'][:200]} for w in warnings[:20]]})
    return {'data':{'status':'completed','sha256':value['sha256'],'warnings':warnings},'terminate':True}
