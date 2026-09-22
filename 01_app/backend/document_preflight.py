"""Drafting contract on the existing Pi run/journal; no second workflow store.

The controller judges applicability and interprets the current user message.
This module binds that judgment, the visible gap notice and the later consent
to the same documents, company and input version before saving.
A document is named by title before its first save and by document id after it,
so every comparison here resolves both forms to one identity.
"""
import json
import re
from fastapi import HTTPException
from . import document_store as store
from .document_schema import obj
from .document_context import context, previous, allowed

VERSION = '1.0.3'
GUIDE = '''起草行为合同：先核对，再决定是否起草。先阅读业务能力目录，按用户目标选择正文或Word；保存时核对具体文稿、用户要求和当前输入。
先读取当前资料、适用规则及模板，复用已有内容要求，按本次文种检查主体、事项、时间、金额、程序、条件和必要附件；未适用的主题说明理由，不把模板案例当事实。
调用 assess_document_readiness 登记本轮核对结果和output（text或word）：每份文稿有稳定的title/kind/document_id、checked_topics和结构化gaps。已有系统内文稿时沿用其document_id；未提供编号时系统按标题和类型对齐同一文稿，同一缺口不重复询问。不得通过空列缺口宣称资料齐全。
gaps分类：content=正文事实缺失或冲突；evidence=系统检索/依据定位问题；review=内容或版式复核；publication=签发、报送或发布待办。不要把后两类当成正文缺失。每个缺口用不带【待补】前缀的简洁label，说明reason，后续沿用相同label；同一缺口只登记一次。
首次发现content缺口，通常由工具提示并等待用户选择；仅要求Word不代表接受缺口。如果本轮用户明确要求缺失资料留空或标注待补并先制作，提交decision=draft_with_placeholders和choice_quote（完整本轮用户消息），完成核对登记后直接制作待补稿，不要求重复选择。不知道的事实和任职合规声明均须待核实，不能写成肯定事实。
前轮document_preflight有缺口提醒时，结合本轮完整用户消息判断是否同意继续。仅在用户明确接受已告知缺口并要求继续该文稿时，提交decision=proceed_with_gaps、notice_id和choice_quote（完整本轮用户消息）；含否定、提问、换事项或只补充部分事实，不能当同意。不要求固定确认口令。
这项选择只允许带已告知缺口继续制作，不确认正文正确、文件定稿或公司审批。无新缺口且文稿范围未变时，已记录的选择可以沿用。新发现、性质加重或涉及另一文稿的缺口须再提醒。
首次只说拟公告，目标是text。只有明确要Word、修改已有Word，或承接前轮已明确的Word目标时，才进入word。不要把“确认缺口处理”分流成confirm_text。
evidence问题应先自行核对来源、修正引用或改为真实条件表述，不得机械转成用户资料缺口。body中的【待补：label】须与本轮content缺口对应；review/publication事项只登记在清单，不要追加进正文。
登记本身不等于文件已生成；保存正文或生成文件以本轮真实登记回执为准。用户明确表示暂不制作时按其要求停在该步。'''


def label(value):
    value = str(value).strip()
    if value.startswith('【') and value.endswith('】'):
        value = value[1:-1].strip()
    return re.sub(r'^(?:待补\s*[：:]?\s*)+', '', value).strip()


def labels(values):
    return list(dict.fromkeys(v for raw in values if (v := label(raw))))


def normalize_markers(text):
    return re.sub(r'【待补[：:]?([^】]+)】',lambda m:'【待补：'+label(m[1])+'】',text)


def covers(values,candidate):
    parts={p.strip() for value in values for p in value.split('、')}
    return candidate in values or all(p.strip() in parts for p in candidate.split('、'))


def current_user(runtime, run):
    return next(r for r in runtime.store.journal(run['id']) if r['kind'] == 'user')


def tool():
    string = {'type':'string', 'minLength':1, 'maxLength':2000}
    gap = obj({'label':string, 'reason':string,
               'category':{'type':'string','enum':['content','evidence','review','publication']},
               'state':{'type':'string','enum':['missing','conflict','pending']}},
              ['label','reason','category','state'])
    document = obj({'title':{'type':'string','minLength':1,'maxLength':120},
                    'kind':{'type':'string','enum':['announcement','analysis']},
                    'document_id':{'type':'string'},
                    'checked_topics':{'type':'array','items':string,'minItems':1,'maxItems':50},
                    'gaps':{'type':'array','items':gap,'maxItems':50}},
                   ['title','kind','checked_topics','gaps'])
    resolution=obj({'gap_label':string,'status':{'type':'string','enum':['resolved','still_missing','conflict']},
                    'source_ids':{'type':'array','items':{'type':'string'},'maxItems':20},'note':string},
                   ['gap_label','status','source_ids','note'])
    return {'name':'assess_document_readiness', 'description':'主控登记起草前核对、分类缺口和用户对已告知缺口的选择。新内容缺口先提示并等待用户；已接受或缺项留空的处理按本轮用户要求登记。',
            'parameters':obj({'documents':{'type':'array','items':document,'minItems':1,'maxItems':10},
                              'request_quote':{'type':'string','minLength':1,'maxLength':20000},
                              'output':{'type':'string','enum':['text','word'],'description':'按本轮用户要求或同一文稿已登记目标选择；该字段仅绑定这次文稿输出，不切换工具权限。'},
                              'decision':{'type':'string','enum':['assess','proceed_with_gaps','draft_with_placeholders']},
                              'notice_id':{'type':'string'}, 'choice_quote':{'type':'string','maxLength':20000},
                              'attachment_resolution':{'type':'array','items':resolution,'maxItems':100}},
                             ['documents','request_quote','decision','output'])}


def identity(document):
    return (document.get('document_id') or document['title'], document['kind'])


def same_document(left, right):
    """One document seen before and after its first save is still the same one."""
    if left['kind'] != right['kind']:
        return False
    if left.get('document_id') and right.get('document_id'):
        return left['document_id'] == right['document_id']
    return left['title'] == right['title']


def same_scope(left, right):
    return len(left) == len(right) and all(any(same_document(a, b) for a in left) for b in right) \
        and all(any(same_document(b, a) for b in right) for a in left)


def resolved(rows, document):
    """Bind a title-only plan entry to the session document that already carries it."""
    if document.get('document_id'):
        return document
    match = next((row for row in rows if row['title'] == document['title'] and row['kind'] == document['kind']), None)
    return {**document, 'document_id': match['document_id']} if match else document


def accepted_records(value):
    """Accept both the current record shape and the earlier tuple-key shape."""
    rows = []
    for entry in value.get('accepted_content') or []:
        if isinstance(entry, dict):
            rows.append(entry)
        else:
            identity_key, label_text, state = entry
            key, kind = identity_key
            rows.append({'key': key, 'kind': kind, 'label': label(label_text), 'state': state})
    return rows


def accepted_for(value, document):
    return {(row['label'], row['state']) for row in accepted_records(value)
            if row.get('kind') == document['kind'] and row.get('key') in (document.get('document_id'), document['title'])}


def content_pairs(document):
    return {(gap['label'], gap['state']) for gap in document['gaps'] if gap['category'] == 'content'}


def accepted_rows(documents):
    return [{'key': d.get('document_id') or d['title'], 'kind': d['kind'],
             'label': gap['label'], 'state': gap['state']}
            for d in documents for gap in d['gaps'] if gap['category'] == 'content']


def next_context(runtime, rid, message):
    run = runtime.store.run(rid)
    from .document_context import with_announcement_method
    value = with_announcement_method(runtime,run,context(runtime, run))
    system = runtime.system_for(value) + '\n' + message
    stamp = store.sha(system.encode())
    # The worker reports this stamp with phase_started, so the run record must
    # hold it too; otherwise the live runtime rejects the switch as inconsistent.
    runtime.store.update(rid, system_sha256=stamp)
    runtime.trace(rid,'context_loaded',{'context':value,'sha256':store.sha(json.dumps(value,ensure_ascii=False,sort_keys=True).encode())})
    return {'data':{'status':'ready' if allowed(runtime.store.run(rid)) else 'preflight_required','message':message,
                    'production_capability':value['production_capability']},
            'next_context':{'system':system,'system_sha256':stamp,
                            'tools':runtime.tools(run['stage'],value),
                            'stage':run['stage'] if value['production_allowed'] else 'document_preflight','requires_result':True}}


def wait(runtime, rid, value, message=None):
    value = {**value, 'status':'waiting_choice', 'notice_id':rid, 'accepted_content':[]}
    details = [d['title']+'：'+g['label']+'（'+g['reason']+'）' for d in value['documents'] for g in d['gaps'] if g['category']=='content']
    target = 'Word草稿' if value['output']=='word' else '公告正文草稿'
    questions = [message or '起草前还有内容缺口，请先选择处理方式。', *details,
                 '建议先补充上述资料；也可以回复“先按现有资料制作'+target+'，缺项标注待补”。确认只针对缺口处理，不代表正文或文件已经定稿。']
    runtime.store.update(rid, document_preflight=value, outcome='waiting_user', questions=questions, reason='已提示内容缺口，等待用户选择处理方式')
    runtime.trace(rid,'document_gap_notice',{'notice_id':rid,'documents':value['documents'],'output':value['output'],'questions':questions})
    runtime.trace(rid,'questions',{'questions':questions})
    return {'data':{'status':'waiting_user','questions':questions,'notice_id':rid,'documents_saved':False},'terminate':True,'finalize':True}


def assess(runtime, rid, args):
    run = runtime.store.run(rid)
    if run['stage'] not in ('document','announcement'):
        raise HTTPException(403,'当前任务没有起草核对权限')
    if not isinstance(args,dict) or set(args)-{'documents','request_quote','decision','output','notice_id','choice_quote','attachment_resolution'} or args.get('decision') not in ('assess','proceed_with_gaps','draft_with_placeholders'):
        raise HTTPException(422,'起草核对字段无效')
    resolutions=args.get('attachment_resolution',[])
    if not isinstance(resolutions,list) or len(resolutions)>100:raise HTTPException(422,'附件补充核对记录无效')
    if run.get('attachment_ids') and not resolutions:
        raise HTTPException(422,'本轮含补充附件，请读取相关内容并登记attachment_resolution，说明已补齐、仍缺或冲突；不能仅凭文件名称认定已补齐')
    for row in resolutions:
        if not isinstance(row,dict) or set(row)!={'gap_label','status','source_ids','note'} or row['status'] not in ('resolved','still_missing','conflict') or not all(isinstance(row[k],str) and 0<len(row[k])<=2000 for k in ('gap_label','note')) or not isinstance(row['source_ids'],list) or len(row['source_ids'])>20:
            raise HTTPException(422,'附件补充核对记录字段无效')
        if row['status']=='resolved' and not row['source_ids']:raise HTTPException(422,'已补齐的缺口必须绑定附件定位')
        from .conversation_attachments import source_text
        for source_id in row['source_ids']:
            if not isinstance(source_id,str) or not source_id.startswith('attachment:'):raise HTTPException(422,'附件核对须引用read_attachment返回的source_id')
            source_text(runtime,run,source_id)
    documents = args.get('documents')
    if not isinstance(documents,list) or not 1<=len(documents)<=10:
        raise HTTPException(422,'请登记本次要起草的文稿范围')
    user = current_user(runtime,run)
    user_text = user['body']['text'].strip()
    quote = args.get('request_quote')
    if not isinstance(quote,str) or not quote.strip() or quote not in user_text:
        raise HTTPException(422,'需求依据须来自本轮用户原话')
    rows = store.listing(runtime,run['session_id'])['items']
    cleaned = []
    for raw in documents:
        if not isinstance(raw,dict) or set(raw)-{'title','kind','document_id','checked_topics','gaps'} or not isinstance(raw.get('title'),str) or not 1<=len(raw['title'].strip())<=120 or raw.get('kind') not in ('announcement','analysis'):
            raise HTTPException(422,'文稿核对对象无效')
        topics = raw.get('checked_topics')
        if not isinstance(topics,list) or not 1<=len(topics)<=50 or not all(isinstance(t,str) and 0<len(t)<=2000 for t in topics):
            raise HTTPException(422,'须说明已核对的必要内容及适用条件')
        if 'document_id' in raw and not isinstance(raw['document_id'],str):
            raise HTTPException(422,'已有文稿编号格式无效')
        document = resolved(rows,{**raw,'title':raw['title'].strip()})
        if document.get('document_id'):
            old = store.version(runtime,run['session_id'],document['document_id'])
            if old['kind']!=document['kind']:
                raise HTTPException(409,'核对对象类型与当前文稿不一致')
        if run.get('target_document_id') and document.get('document_id')!=run['target_document_id']:
            raise HTTPException(409,'核对对象与本轮指定文稿不一致')
        if run['stage']=='announcement' and document['kind']!='announcement' or run.get('document_kind') in ('announcement','analysis') and document['kind']!=run['document_kind']:
            raise HTTPException(422,'核对文种与本轮任务不一致')
        if not isinstance(document.get('gaps'),list) or len(document['gaps'])>50:
            raise HTTPException(422,'缺口登记须为分类清单')
        gaps = {}
        for gap in document['gaps']:
            if not isinstance(gap,dict) or set(gap)!={'label','reason','category','state'} or gap['category'] not in ('content','evidence','review','publication') or gap['state'] not in ('missing','conflict','pending') or not all(isinstance(gap[k],str) and 0<len(gap[k])<=2000 for k in ('label','reason')) or not label(gap['label']):
                raise HTTPException(422,'缺口类别、说明或状态无效')
            item = {**gap,'label':label(gap['label'])}
            key = (item['category'],item['label'])
            if key not in gaps or item['state']=='conflict':gaps[key]=item
        cleaned.append({**document,'gaps':list(gaps.values())})
    if len({identity(d) for d in cleaned})!=len(cleaned):
        raise HTTPException(422,'本轮核对清单不能重复登记同一文稿')
    prior = previous(runtime,run)
    same = bool(prior) and same_scope(prior['documents'], cleaned)
    value = {'contract_version':VERSION,'run_id':rid,'board':run['board'],'company_code':run.get('company_code',''),
             'attachment_resolution':resolutions,
             'documents':cleaned,'output':'word' if run['stage']=='document' else 'text',
             'input_fingerprint':run['document_context_sha256'],'user_message_seq':user['seq'],
             'request_quote':quote,'status':'ready','accepted_content':[]}
    carried = [set() for _ in cleaned]
    consent = None
    for source in (run.get('document_preflight'), prior):
        if not source or source.get('status') not in ('ready','authorized'):
            continue
        for index, document in enumerate(cleaned):
            for stored in source['documents']:
                if same_document(stored, document):
                    carried[index] |= accepted_for(source, stored)
        if consent is None and source.get('consent') and same_scope(source['documents'], cleaned):
            consent = source['consent']
    if args['decision']=='proceed_with_gaps':
        choice = args.get('choice_quote','').strip()
        if not same or prior.get('status')!='waiting_choice' or args.get('notice_id')!=prior.get('notice_id') or user['seq']<=prior['user_message_seq'] or choice!=user_text:
            raise HTTPException(422,'缺口选择须绑定前轮同一文稿提醒和完整本轮用户原话，不能代签或跨事项沿用')
        if any(g['state']=='conflict' for d in prior['documents'] for g in d['gaps'] if g['category']=='content'):
            return wait(runtime,rid,value,'前轮存在互相冲突的正文事实；普通“带缺口继续”不授权选择其中一种冲突事实，请先核对冲突。')
        # The notice fixes which gaps this draft may keep; gaps noticed only now still wait.
        for index, document in enumerate(cleaned):
            declared = {(gap['category'],gap['label']) for gap in document['gaps']}
            for stored in prior['documents']:
                if not same_document(stored, document):
                    continue
                carried[index] |= accepted_for(prior, stored) | content_pairs(stored)
                for gap in stored['gaps']:
                    if (gap['category'],gap['label']) not in declared:
                        document['gaps'].append(dict(gap))
                        declared.add((gap['category'],gap['label']))
        consent = {'notice_id':prior['notice_id'],'run_id':rid,'user_message_seq':user['seq'],'quote':choice,'scope':'incomplete_draft_only'}
    if args['decision']=='draft_with_placeholders':
        choice=args.get('choice_quote','').strip()
        if choice!=user_text:
            raise HTTPException(422,'先做待补稿须来自本轮用户完整原话；不能根据历史模型建议代签')
        if any(g['state']=='conflict' for d in cleaned for g in d['gaps'] if g['category']=='content'):
            return wait(runtime,rid,value,'存在互相冲突的正文事实，请先核对冲突；一般留空指令不选择其中一种事实。')
        carried=[content_pairs(document) for document in cleaned]
        consent={'run_id':rid,'user_message_seq':user['seq'],'quote':choice,'scope':'incomplete_draft_only','mode':'explicit_placeholders'}
    missing = [[document['title'],gap['label']] for index, document in enumerate(cleaned)
               for gap in document['gaps'] if gap['category']=='content' and (gap['label'],gap['state']) not in carried[index]]
    if missing:
        return wait(runtime,rid,value)
    value.update(status='authorized' if any(content_pairs(d) for d in cleaned) else 'ready',
                 accepted_content=accepted_rows(cleaned),consent=consent,notice_id=(consent or {}).get('notice_id'))
    runtime.store.update(rid,document_preflight=value)
    runtime.trace(rid,'document_preflight_registered',value)
    return next_context(runtime,rid,'起草前核对已登记。仅按已核对文稿及已接受的内容缺口继续，正文和文件仍待审阅。')


def link_saved(runtime, rid, published):
    """The first save assigns the document id; keep plan and consent bound to it."""
    run = runtime.store.run(rid)
    plan = run.get('document_preflight')
    rows = [row for row in published or [] if isinstance(row,dict) and row.get('document_id')]
    if not plan or not rows:
        return plan
    links, documents = [], []
    for document in plan['documents']:
        match = None if document.get('document_id') else next(
            (row for row in rows if row.get('title')==document['title'] and row.get('kind')==document['kind']), None)
        if not match:
            documents.append(document)
            continue
        links.append((document['title'],document['kind'],match['document_id']))
        documents.append({**document,'document_id':match['document_id']})
    if not links:
        return plan
    accepted = []
    for record in accepted_records(plan):
        key = record.get('key')
        for title, kind, document_id in links:
            if record.get('kind')==kind and key==title:
                key = document_id
        accepted.append({**record,'key':key})
    updated = {**plan,'documents':documents,'accepted_content':accepted}
    runtime.store.update(rid,document_preflight=updated)
    runtime.trace(rid,'document_preflight_linked',{'links':[{'title':t,'kind':k,'document_id':i} for t,k,i in links]})
    return updated


def enforce(runtime, rid, documents):
    run = runtime.store.run(rid)
    if not allowed(run):
        return next_context(runtime,rid,'当前没有有效的起草前核对记录。先调用assess_document_readiness；不能保存正文或生成Word。')
    plan = run['document_preflight']
    if not isinstance(documents,list) or not same_scope(plan['documents'], [d for d in documents if isinstance(d,dict) and 'title' in d and 'kind' in d]):
        runtime.store.update(rid,document_preflight={**plan,'status':'scope_changed'})
        return next_context(runtime,rid,'文稿范围发生变化，请重新核对，已有选择不授权另一份文稿。')
    return None


def check_new_gaps(runtime, rid, item, pending):
    """Reconcile body gaps internally; string differences cannot request consent."""
    run = runtime.store.run(rid)
    plan = run['document_preflight']
    target = next((d for d in plan['documents'] if same_document(d, item)), None)
    if target is None:
        return next_context(runtime,rid,'正文文稿与本轮核对记录不一致，请重新登记起草前核对后再生成文件。')
    accepted = {gap['label'] for gap in target['gaps'] if gap['category']=='content'} | {
        row['label'] for row in accepted_records(plan)
        if row.get('kind')==item['kind'] and row.get('key') in (item.get('document_id'), item['title'])}
    new = [text for text in labels(pending) if not covers(accepted, text)]
    if not new:return None
    return next_context(runtime,rid,'正文待补与已登记内容未对齐，请先自行核对并登记类别：'+'；'.join(new)+
        '。依据查证、格式和复核问题不能变成用户事实缺口；同一已接受缺口沿用原label。只有确实需要用户补充或选择的新业务事实才提示用户，不因字符串差异重复确认。')


def document_gaps(run,item):
    plan = run.get('document_preflight') or {}
    target = next((d for d in plan.get('documents',[]) if same_document(d, item)), None)
    return target['gaps'] if target else []
