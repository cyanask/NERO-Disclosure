"""On-demand document work owned by the existing Pi run, not a second controller."""
import base64
import json
import queue
import re
import sys
import tempfile
import time
from pathlib import Path
from fastapi import HTTPException
from . import document_store as store, document_files, pi_subprocess
from .intent_control import bound
from .document_schema import obj
from .document_context import context, seeds_for

GUIDE = '''制作或修改 Word 文档时，先完成起草前核对；一般新缺口先提醒，本轮明确要求缺项留空或标注待补并先制作时按draft_with_placeholders登记后继续，不反复要求相同选择，不要求通过事项全部节点。
根据当前事实、用户最新修订、已有方案和文稿组织完整内容，按需检索缺少的依据。历史助手答复只作候选，不能当作已核事实。
用户没有要求改变文种时，不擅自将公告换成分析备忘录。用户接受已告知缺口后，按现有资料制作可下载的待审阅草稿；缺少事实或存在矛盾的部分用与起草前核对一致的【待补：label】，不再要求先补齐这些缺口。不得推测缺失事实，不把依据定位失败直接当作事实缺失。
选择匹配文种的模板，必要时read_document_template读取章节；模板适配只负责结构，不能套用案例事实。将聊天整理为可独立阅读的文稿，去除重复和操作说明，保留用户问题涉及的主题、条件及分析。
调用make_word才会生成文件，不能只回复正文或提供点击导出的说明。一次请求的多份文稿一起提交，每份有独立标题和内容。
公告的内容与依据由主控智能体按公告Skill判断，可按需要继续查证、修订。非公告按用户要求完整整理，不套用公告的逐句依据复核。允许忠实转述和综合，不为通过制文而删减正文；用户的问题保留为问题，不冒充已发生的事实。
basis是可选的来源记录，不代表已经核验。提供时用户或事项使用sources给定id；库条款使用library:条款id；本轮下载原文使用download:download_id:页码。直接引语忠于原文；检查金额、日期、主体、拟实施与已实施，不得伪造审批或引文。
Word有公告和咨询回复两类，按用户所指的当前对象选择。已有公告正文优先沿用；明确要求把咨询答复出Word时用analysis。两者都有且指向不明时只问一个澄清问题。
已有文稿修改必须带document_id和base_version。已有公告Word先read_document读取系统内当前锚点，用edits局部修改并保存新版本。仅需现有Word文件时可只提供当前文稿编号和版本，不重复改写。会话面向Word输出，系统外修改的文件不接回会话，也不要求用户回传。
用户要求重新整理、扩充或完整重写备忘录时，应回到相关会话和资料组织完整内容，不把已有短稿当作内容范围，也不沿用历史依据退回记录作为删减要求。系统生成且未经人工确认的非公告，可以在同一document_id下提交完整text、不带edits，保存新版本；即使本轮标为revise也可如此。只改局部时才用edits。公告、人工修改稿和已确认稿仍按锚点修改，不整体覆盖。
文件生成只产生待审阅版本，不改变事项进度或代替人工确认。成功后用简短回复指出文件、主要待补项；文件卡片提供文字预览、下载和版本记录，需要修改时请用户直接在对话框说明。'''


def tools(*,announcement=False,allow_production=False):
    string = {'type': 'string'}
    basis = obj({'statement': string, 'source_id': {'type':'string','description':'sources中的user/event编号，或library:条款id、download:下载id:页码、document:文稿id:版本'}, 'quote': string}, ['statement', 'source_id', 'quote'])
    edit = obj({'block_id': string, 'original': string, 'replacement': string}, ['block_id', 'original', 'replacement'])
    document = obj({'document_id': string, 'base_version': {'type': 'integer', 'minimum': 1},
                    'title': {'type': 'string', 'minLength': 1, 'maxLength': 120},
                    'kind': {'type': 'string', 'enum': ['announcement', 'analysis']},
                    'template_id': string, 'text': {'type': 'string', 'maxLength': 100000},
                    'pending': {'type': 'array', 'items': string, 'maxItems': 50},
                    'basis': {'type': 'array', 'items': basis, 'maxItems': 100},
                    'edits': {'type': 'array', 'items': edit, 'maxItems': 100}},
                   ['title', 'kind', 'template_id', 'pending'])
    definitions = [
        {'name': 'read_document_context', 'description': '读取当前事实、最新文稿和本轮可用来源；不会推进事项。', 'parameters': obj()},
        {'name': 'read_document_template', 'description': '读取本板块和本公司模板的章节、版式依据和实际模板内容。',
         'parameters': obj({'template_id': string}, ['template_id'])},
        {'name': 'read_document', 'description': '读取系统内当前或历史文稿及修改锚点。修改必须基于最新版本。',
         'parameters': obj({'document_id': string, 'version': {'type': 'integer', 'minimum': 1}}, ['document_id'])},
        {'name': 'save_announcement' if announcement else 'make_word',
         'description': '保存已判断披露范围、适配模板的完整公告正文版本，等待用户确认；本工具不生成Word。' if announcement else '整理完成后制作一份或多份Word。重新整理系统生成且未经人工确认的非公告时，可提交完整text保存新版本；局部修改使用edits。',
         'parameters': obj({'documents': {'type': 'array', 'items': document, 'minItems': 1, 'maxItems': 10},
                            **({'assessment':obj({'disclosure_needed':{'type':'string','enum':['yes','no','uncertain']},
                                                 'disclosure_scope':string,'reason':string,'consultation_run_id':string},
                                                ['disclosure_needed','disclosure_scope','reason'])} if announcement else {})},
                           ['documents','assessment'] if announcement else ['documents'])}]
    from .document_preflight import tool
    return definitions[:-1]+[tool()]+definitions[-1:]


def template(runtime, run, identity):
    from .document_rendering import layout
    if identity in ('builtin:analysis', 'source:current'):
        return {'id': identity, 'name': '当前稿原有版式' if identity=='source:current' else '分析材料通用版式', 'layout': layout(runtime.root, run['board']),
                'sections': [], 'sha256': None, 'raw': None}
    seeds = seeds_for(runtime, run)
    row = next((r for r in seeds.templates() if r['id'] == identity), None)
    if not row:
        raise HTTPException(422, '模板不在当前板块和公司范围内')
    root = seeds.root / 'templates'
    path = root / row['file']
    if not path.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise HTTPException(409, '模板路径无效')
    raw = path.read_bytes()
    parsed = document_files.inspect(raw)
    layouts = json.loads((seeds.template_dir / 'layout_profiles.json').read_text('utf-8'))
    spec = next((r for r in layouts if r['id'] == row.get('layout_profile_id')), None)
    if not spec:
        raise HTTPException(409, '模板缺少版式规则')
    if spec.get('source_observations_path'):
        from .library import safe_file
        if store.sha(safe_file(seeds, spec['source_observations_path']).read_bytes()) != spec['source_observations_sha256']:
            raise HTTPException(409, '模板版式依据已变化，请核对版本')
    if row.get('authority') == 'user_uploaded':
        spec = {**spec, 'template_authority': 'user_uploaded'}
    return {**row, 'layout': spec, 'sha256': store.sha(raw), 'raw': raw, 'template_text': parsed['text']}


def read_document(runtime, run, args):
    row=store.version(runtime,run['session_id'],args['document_id'],args.get('version'))
    if row.get('format','docx')=='text':
        saved=store.snapshot(runtime,run['session_id'],args['document_id'],row['version'])
        return {'document':store.public_version(run['session_id'],row),'text':saved['text'],'snapshot':saved}
    path, row = store.file(runtime, run['session_id'], args['document_id'], args.get('version'))
    result = document_files.inspect(path.read_bytes())
    return {'document': store.public_version(run['session_id'], row), 'blocks': result['blocks'],
            'snapshot': store.snapshot(runtime, run['session_id'], args['document_id'], args.get('version'))}


def source_text(runtime, run, context_value, identity):
    if identity.startswith('attachment:'):
        from .conversation_attachments import source_text as attachment_source
        return attachment_source(runtime,run,identity)
    match = next((s for s in context_value['sources'] if s['id'] == identity), None)
    if match:
        return match['text']
    if identity.startswith('library:'):
        reply = runtime.operation(run['id'], 'library.read', {'board': run['board'], 'company': run.get('company_code', ''),
                                                             'item_id': identity.removeprefix('library:')})
        return json.dumps(reply, ensure_ascii=False)
    if identity.startswith('document:'):
        parts = identity.split(':')
        if len(parts) != 3 or not parts[2].isdigit():
            raise HTTPException(422, '文稿来源编号无效')
        row=store.version(runtime,run['session_id'],parts[1],int(parts[2]))
        if row.get('format','docx')=='text':return store.snapshot(runtime,run['session_id'],parts[1],int(parts[2]))['text']
        path, _ = store.file(runtime, run['session_id'], parts[1], int(parts[2]))
        return document_files.inspect(path.read_bytes())['text']
    if identity.startswith('download:'):
        from .public_sources import receipt
        parts=identity.split(':')
        if len(parts)!=3 or not parts[2].isdigit():
            raise HTTPException(422,'下载来源编号无效')
        source,document=receipt(runtime.root,run['id'],parts[1])
        page=int(parts[2])
        if not 1<=page<=len(document['pages']):
            raise HTTPException(422,'下载来源页码无效')
        return ('来源地址：'+source['final_url']+'\n取得时间：'+source['retrieved_at']+
                '\n来源状态：公开下载原件，下载不代表已核实权威、版本及适用性。\n原文：\n'+document['pages'][page-1]['text'])
    raise HTTPException(422, '正文依据未绑定当前会话来源')


def run_script(runtime, rid, packet, stop):
    directory = runtime.directory / 'pi-runs' / rid
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='document-', dir=directory) as temporary:
        source, output = Path(temporary) / 'context.json', Path(temporary) / 'document.docx'
        source.write_text(json.dumps(packet, ensure_ascii=False), encoding='utf-8')
        script = runtime.code_root / 'scripts/agent_word.py'
        runtime.trace(rid, 'script_started', {'script': 'scripts/agent_word.py', 'sha256': store.sha(script.read_bytes()),
                                            'input_fingerprint': packet['input_fingerprint']})
        session = pi_subprocess.Session([sys.executable, str(script), '--context', str(source), '--output', str(output)], runtime.code_root)
        try:
            deadline = time.monotonic() + 120
            lines = []
            while True:
                if stop.is_set() or time.monotonic() > deadline:
                    raise HTTPException(409, 'Word 制作已停止或超时')
                try:
                    line = session.read(timeout=.05)
                except queue.Empty:
                    continue
                if line is None:
                    break
                lines.append(line)
                if sum(map(len, lines)) > 100000:
                    raise HTTPException(409, 'Word 制作回执超过范围')
            session.wait()
            try:
                receipt = json.loads(''.join(lines))
            except ValueError:
                raise HTTPException(409, 'Word 工具未返回有效回执') from None
            if session.returncode or not output.is_file():
                raise HTTPException(422, receipt.get('error', 'Word 工具未生成文件'))
            raw = output.read_bytes()
            if receipt.get('sha256') != store.sha(raw):
                raise HTTPException(409, 'Word 制作文件哈希不一致')
            runtime.trace(rid, 'script_returned', {k: receipt[k] for k in ('sha256', 'bytes', 'input_fingerprint')})
            return raw
        finally:
            session.close()


def make_word(runtime, rid, args, stop, *,text_only=False):
    run = runtime.store.run(rid)
    if run.get('outcome'):
        raise HTTPException(409, '本轮已结束或正在等待用户确认')
    from . import document_preflight as preflight
    held=preflight.enforce(runtime,rid,args.get('documents') if isinstance(args,dict) else None)
    if held:return held
    required={'documents','assessment'} if text_only else {'documents'}
    if set(args) != required or not isinstance(args['documents'], list) or not 1 <= len(args['documents']) <= 10:
        raise HTTPException(422, '请提供本次要制作的文稿清单')
    assessment=args.get('assessment')
    if text_only:
        if not isinstance(assessment,dict) or set(assessment)-{'disclosure_needed','disclosure_scope','reason','consultation_run_id'} or assessment.get('disclosure_needed') not in ('yes','no','uncertain') or not all(isinstance(assessment.get(k),str) and assessment[k].strip() for k in ('disclosure_scope','reason')):
            raise HTTPException(422,'拟公告前须说明是否披露、披露范围及判断理由')
        if assessment.get('consultation_run_id'):
            prior=runtime.store.run(assessment['consultation_run_id'])
            if prior['session_id']!=run['session_id'] or prior['stage']!='chat':raise HTTPException(403,'咨询结论不属于当前会话')
    frozen = run['document_context']
    if bound(run['event_id']) and runtime.event(run['event_id'])['revision'] != frozen['event_revision']:
        raise HTTPException(409, '事项资料已变化，请读取当前文稿上下文后继续')
    prepared = []
    seen = set()
    for item in args['documents']:
        allowed = {'document_id', 'base_version', 'title', 'kind', 'template_id', 'text', 'pending', 'basis', 'edits'}
        if not isinstance(item, dict) or set(item) - allowed or not all(k in item for k in ('title', 'kind', 'template_id', 'pending')):
            raise HTTPException(422, '文稿字段不完整或含不支持的字段')
        item={**item,'basis':item.get('basis',[])}
        if item['kind'] not in ('announcement', 'analysis') or not isinstance(item['title'], str) or not 1 <= len(item['title'].strip()) <= 120:
            raise HTTPException(422, '文稿标题或类型无效')
        if run.get('target_document_id') and len(args['documents'])==1:
            target=next((d for d in frozen['documents'] if d['document_id']==run['target_document_id']),None)
            if not target or item.get('document_id',target['document_id'])!=target['document_id']:
                raise HTTPException(409,'制作对象与本轮指定的当前文稿不一致')
            item={**item,'document_id':target['document_id'],'base_version':item.get('base_version',target['version'])}
        if text_only and item['kind']!='announcement':raise HTTPException(422,'拟公告任务不能改成咨询回复')
        if not text_only and run.get('document_kind') in ('announcement','analysis') and item['kind']!=run['document_kind']:
            raise HTTPException(422,'文稿类型与本轮用户选择的公告或咨询回复不一致')
        if not isinstance(item['pending'], list) or len(item['pending']) > 50 or not all(isinstance(p, str) and 0 < len(p) <= 2000 for p in item['pending']):
            raise HTTPException(422, '待补事项格式无效')
        if not isinstance(item['basis'], list) or len(item['basis']) > 100:
            raise HTTPException(422, '依据绑定格式无效')
        for binding in item['basis']:
            if not isinstance(binding,dict) or set(binding)!={'statement','source_id','quote'} or not all(isinstance(v,str) and v.strip() for v in binding.values()):
                raise HTTPException(422,'事实依据绑定格式无效')
            # Keep access/integrity checks for private or run-bound objects;
            # these do not decide whether a quote supports the prose.
            if binding['source_id'].startswith(('document:','attachment:','download:')):
                source_text(runtime,run,frozen,binding['source_id'])
        key = item.get('document_id') or item['title']
        if not item.get('document_id') and any(d['title']==item['title'] and d['kind']==item['kind'] for d in frozen['documents']):
            raise HTTPException(409, '已有同名当前文稿，请使用其 document_id 和 base_version 创建新版本')
        if key in seen:
            raise HTTPException(422, '本批次不能重复制作同一文稿')
        seen.add(key)
        selected = template(runtime, run, item['template_id'])
        if selected['id'] == 'source:current' and not item.get('document_id'):
            raise HTTPException(422, '沿用当前稿版式须指定当前文稿')
        if item['kind'] == 'announcement' and selected['id'] == 'builtin:analysis':
            raise HTTPException(422, '公告须选择对应公告模板')
        packet = {'kind': 'runtime_document', 'document': item, 'layout': selected['layout'],
                  'company_name': (frozen.get('event') or {}).get('company_name') or runtime.company_scope(run).get('company_name', ''),
                  'board': run['board'],
                  'generated_at': time.strftime('%Y-%m-%d %H:%M'),
                  'template_base64': base64.b64encode(selected['raw']).decode() if selected['raw'] else None,
                  'template_sha256': selected['sha256'], 'input_fingerprint': run['document_context_sha256']}
        text = item.get('text', '')
        human_source=False
        if item.get('document_id'):
            previous=store.version(runtime,run['session_id'],item['document_id'])
            if item.get('base_version') != previous['version']:
                raise HTTPException(409, '文稿已更新，不能基于旧版本制作')
            if previous['kind']!=item['kind']:raise HTTPException(409,'不能将已有公告或咨询文稿改成另一类；请明确新建需求')
            saved=store.snapshot(runtime,run['session_id'],item['document_id'])
            if previous.get('format','docx')=='docx':store.file(runtime,run['session_id'],item['document_id'])
            human_source=previous['source_type'] in ('human_import','human_saved','manual_revision')
            if previous.get('format','docx')=='text':
                if not text:text=saved['text'];item={**item,'text':text};packet['document']=item
            elif text_only:raise HTTPException(409,'已有当前公告Word，请进入document任务并优先修改现有文件')
            if previous.get('format','docx')=='docx' and not text and not item.get('edits') and len(args['documents'])==1:
                path,previous=store.file(runtime,run['session_id'],item['document_id'])
                result=[store.public_version(run['session_id'],previous)]
                runtime.store.update(rid,documents=result,outcome='completed')
                runtime.trace(rid,'documents_reused',{'documents':result,'business_state_changed':False})
                return {'data':{'documents':result,'reused_current':True},'terminate':True,'finalize':True}
            can_rewrite=(item['kind']=='analysis' and previous['source_type'] in ('runtime','anchored_revision','reply_render')
                         and previous.get('review_status')!='accepted')
            if previous.get('format','docx')=='docx' and (not can_rewrite or item.get('edits')):
                path,_=store.file(runtime,run['session_id'],item['document_id'],previous['version'])
                if not item.get('edits') or text:
                    raise HTTPException(409, '请读取当前 Word 的锚点并提交局部 edits，保留已有版式')
                raw_source = path.read_bytes()
                item={**item,'edits':[{**e,'replacement':preflight.normalize_markers(e['replacement'])} for e in item['edits']]}
                packet['document']=item
                changed, parsed = document_files.patch(raw_source, item['edits'])
                text = parsed['text']
                packet.update(source_base64=base64.b64encode(raw_source).decode(), source_sha256=previous['sha256'])
            elif selected['id']=='source:current':
                raise HTTPException(422, '沿用当前 Word 版式须提供局部 edits；重制请明确选择模板')
        if not isinstance(text, str) or not 1 <= len(text) <= 100000:
            raise HTTPException(422, '请先组织完整文稿正文')
        if not packet.get('source_base64'):
            text=preflight.normalize_markers(text)
        # The main agent owns content judgment. Saving must not force it to
        # shorten a draft until a separate paragraph/quote reviewer accepts it.
        evidence=item['basis']
        review_receipt={'source':'not_run','policy':'main_agent' if item['kind']=='announcement' else 'not_applicable'}
        warnings=[];gap_details=[]
        gaps=preflight.document_gaps(run,item)
        content_labels=[g['label'] for g in gaps if g['category']=='content']
        other_labels={g['label'] for g in gaps if g['category']!='content'}
        body_labels=preflight.labels(re.findall(r'【待补[：:]?([^】]+)】', text))
        if other_labels & set(body_labels):
            return preflight.next_context(runtime,rid,'复核、发布待办或系统依据问题不属于正文内容缺口，请从正文待补占位中移出，保留在分类登记中。')
        pending = preflight.labels([p for p in preflight.labels(item['pending']) if p not in other_labels]+body_labels+content_labels)
        held=preflight.check_new_gaps(runtime,rid,item,pending)
        if held:return held
        absent=[p for p in content_labels if not preflight.covers(body_labels,p)]
        if absent:
            return preflight.next_context(runtime,rid,'请在正文对应位置标注这些已接受的内容缺口，沿用登记label，不要在文末堆叠清单：'+'；'.join(absent))
        item = {**item, 'pending':pending}
        packet['document'] = item
        raw = None if text_only else run_script(runtime, rid, packet, stop)
        parsed = {'text':text} if text_only else document_files.inspect(raw)
        pending=preflight.labels(pending+re.findall(r'【待补[：:]?([^】]+)】',parsed['text']))
        # Renderer-owned placeholders (such as missing announcement header
        # fields) are recorded in pending but are not a model-side content gap.
        checks = {'structure': 'text_saved' if text_only else 'passed', 'body_readback': 'not_created' if text_only else 'passed', 'evidence_bindings': 'recorded_unverified' if evidence else 'not_provided', 'basis_count': len(evidence),
                  'fact_source_coverage': 'not_run',
                  'substantive_review': 'model_prepared_pending_user', 'visual_review': 'pending_user',
                  'manual_source_preserved': bool(packet.get('source_base64')) and human_source,'source_package_preserved':bool(packet.get('source_base64'))}
        snapshot = {'document': item, 'text': text, 'basis': evidence,'assessment':assessment,'method':run.get('skill'),
                    'semantic_review':review_receipt,
                    'context': frozen, 'context_sha256': run['document_context_sha256'],
                    'template': {k: v for k, v in selected.items() if k != 'raw'},
                    'checks': checks, 'warnings':warnings, 'gap_details':gap_details,
                    'preflight':run['document_preflight'],'source_sha256': packet.get('source_sha256')}
        prepared.append({**item, 'raw': raw, 'snapshot': snapshot, 'pending': pending,
                         'checks': checks, 'warnings':warnings, 'run_id': rid, 'template_name': selected['name'],
                         'source_type': ('manual_revision' if human_source else 'anchored_revision') if packet.get('source_base64') else 'runtime_text' if text_only else 'runtime'})
    with runtime.lock:
        if bound(run['event_id']) and runtime.event(run['event_id'])['revision'] != frozen['event_revision']:
            raise HTTPException(409, '制作期间事项资料已变化，文件未登记为当前版本')
        result = store.publish(runtime, run['session_id'], prepared, frozen['document_revision'], stop)
        runtime.store.update(rid, documents=result, outcome='completed',announcement_assessment=assessment,document_evidence_issues=[])
        preflight.link_saved(runtime, rid, result)
    runtime.trace(rid, 'drafts_saved' if text_only else 'documents_created', {'documents': result, 'business_state_changed': False})
    return {'data': {'documents': result,'text_saved':text_only,'assessment':assessment,
                     'review': '公告正文已保存，可回复确认或随时要求制作Word' if text_only else '待用户审阅，未发布', 'business_state_changed': False}, 'terminate': True, 'finalize': True}


def execute(runtime, rid, name, args, stop):
    run = runtime.store.run(rid)
    if not isinstance(args,dict):raise HTTPException(422,'文档工具参数须为对象')
    if run.get('outcome'):
        raise HTTPException(409, '本轮已结束或正在等待用户确认')
    if name in ('assess_document_readiness','make_word','save_announcement'):
        from .document_preflight import previous
        if name=='assess_document_readiness':
            output=args.get('output')
            if output not in (None,'text','word'):raise HTTPException(422,'请选择本次文稿的text或word输出')
            if output is None:
                # Compatibility for existing callers; new tool definitions require output.
                prior=previous(runtime,run) or {}
                output=prior.get('output') or ('text' if all(d.get('kind')=='announcement' for d in args.get('documents',[])) else 'word')
            mode='document' if output=='word' else 'announcement'
        else:mode='announcement' if name=='save_announcement' else 'document'
        updates={'stage':mode,'document_action':'create'}
        plan=run.get('document_preflight') or {}
        if plan and plan.get('output')!=('word' if mode=='document' else 'text'):
            updates['document_preflight']={**plan,'status':'output_changed'}
        runtime.store.update(rid,**updates)
        run=runtime.store.run(rid)
        # Bind the current objects even when the caller starts directly with readiness.
        context(runtime,run)
        run=runtime.store.run(rid)
    if name == 'read_document_context' and not args:
        from .document_context import allowed
        was_allowed = allowed(run)
        value = context(runtime, run)
        if run['stage'] in ('document','announcement') and was_allowed != value['production_allowed']:
            from .document_preflight import next_context
            response = next_context(runtime, rid, '资料版本已更新，请按最新资料核对文稿。工具仍可调用，保存文件时核验本轮文稿和用户要求。')
            response['data'] = value
            return response
        return {'data': value}
    if name == 'assess_document_readiness':
        from .document_preflight import assess
        return assess(runtime,rid,args)
    if name == 'read_document_template' and set(args) == {'template_id'}:
        return {'data': {k: v for k, v in template(runtime, run, args['template_id']).items() if k != 'raw'}}
    if name == 'read_document' and set(args) <= {'document_id', 'version'} and args.get('document_id'):
        return {'data': read_document(runtime, run, args)}
    if name in ('make_word','save_announcement'):
        # A stale/early tool invocation must return the existing gate's repair
        # context without consuming a renderer/content revision attempt.
        from .document_preflight import enforce
        held = enforce(runtime, rid, args.get('documents') if isinstance(args,dict) else None)
        if held:
            runtime.trace(rid, 'document_production_deferred', {'reason':'preflight_or_scope', 'documents_saved':False})
            return held
        attempts=run.get('document_attempts',0)+1
        runtime.store.update(rid,document_attempts=attempts)
        try:
            return make_word(runtime, rid, args, stop,text_only=name=='save_announcement')
        except HTTPException as exc:
            runtime.trace(rid,'document_check_failed',{'attempt':attempts,'detail':exc.detail})
            raise
    raise HTTPException(422, '文档工具参数无效')
