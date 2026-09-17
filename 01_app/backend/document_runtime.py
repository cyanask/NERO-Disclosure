"""On-demand document work owned by the existing Pi run, not a second controller."""
import base64
import json
import queue
import re
import sys
import tempfile
import time
from pathlib import Path
from decimal import Decimal
from fastapi import HTTPException
from . import document_store as store, document_files, pi_subprocess
from .intent_control import bound
from .document_schema import obj
from .document_context import context, seeds_for

GUIDE = '''本轮目标是制作或修改 Word 文档。先完成起草前核对；一般新缺口先提醒，本轮明确要求缺项留空或标注待补并先制作时按draft_with_placeholders登记后继续，不反复要求相同选择，不要求通过事项全部节点。
根据当前事实、用户最新修订、已有方案和文稿组织完整内容，按需检索缺少的依据。历史助手答复只作候选，不能当作已核事实。
用户没有要求改变文种时，不擅自将公告换成分析备忘录。用户接受已告知缺口后，按现有资料制作可下载的待审阅草稿；缺少事实或存在矛盾的部分用与起草前核对一致的【待补：label】，不再要求先补齐这些缺口。不得推测缺失事实，不把依据定位失败直接当作事实缺失。
选择匹配文种的模板，必要时read_document_template读取章节；模板适配只负责结构，不能套用案例事实。将聊天整理为可独立阅读的文稿，去除重复、问答和操作说明。
调用make_word才会生成文件，不能只回复正文或提供点击导出的说明。一次请求的多份文稿一起提交，每份有独立标题和内容。
basis将正文中的事实表述绑定来源原句。用户或事项使用sources给定id；库条款使用library:条款id；本轮下载原文使用download:download_id:页码。检查金额、日期、主体、拟实施与已实施，不得伪造审批或引文。
Word有公告和咨询回复两类，按用户所指的当前对象选择。已有公告正文优先沿用；明确要求把咨询答复出Word时用analysis。两者都有且指向不明时只问一个澄清问题。
已有文稿修改必须带document_id和base_version。已有公告Word先read_document读取系统内当前锚点，用edits局部修改并保存新版本。仅需现有Word文件时可只提供当前文稿编号和版本，不重复改写。会话面向Word输出，系统外修改的文件不接回会话，也不要求用户回传。
文件生成只产生待审阅版本，不改变事项进度或代替人工确认。成功后用简短回复指出文件、主要待补项；文件卡片提供文字预览、下载和版本记录，需要修改时请用户直接在对话框说明。'''


NUMBER_PATTERN = r'(?<![A-Za-z0-9])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)*(?:\s*[%％])?'


def number_tokens(text):
    values=set()
    for raw in re.findall(NUMBER_PATTERN,text):
        token=re.sub(r'\s+','',raw).replace(',','').replace('％','%')
        percentage=token.endswith('%');number=token[:-1] if percentage else token
        if number.count('.')>1 or number.isdigit() and len(number)>=6 and number.startswith('0'):
            values.add(token);continue
        normalized=format(Decimal(number),'f')
        if '.' in normalized:normalized=normalized.rstrip('0').rstrip('.')
        values.add(normalized+('%' if percentage else ''))
    return values


def mark_draft_gaps(text, unknown):
    """Keep draft production possible without presenting unsupported numbers as sourced."""
    # Do not check numbers inside URLs, pending markers, or ordered-list labels.
    pattern = r'【待补[^】]*】|https?://\S+|(?m:^\s*(?:#{1,6}\s+)?(?:[-*]\s*)?\d+[.、)]\s+)|'+NUMBER_PATTERN
    def replace(match):
        value = match.group()
        if re.fullmatch(NUMBER_PATTERN, value) and number_tokens(value) & set(unknown):
            return '【待补：核实数值'+value+'及其口径】'
        return value
    return re.sub(pattern, replace, text)


def pending_edits(raw, parsed, transform):
    """Fold draft markers into minimal anchors against the original Word version."""
    original = document_files.inspect(raw)
    edits = []
    for before, after in zip(original['blocks'], parsed['blocks']):
        old, new = before['text'], transform(after['text'])
        if old == new:
            continue
        start = 0
        while start < min(len(old), len(new)) and old[start] == new[start]:
            start += 1
        end = 0
        while end < min(len(old), len(new))-start and old[-end-1] == new[-end-1]:
            end += 1
        anchor = old[start:len(old)-end]
        replacement = new[start:len(new)-end]
        if not anchor or old.count(anchor) != 1:
            anchor, replacement = old, new
        edits.append({'block_id':before['id'], 'original':anchor, 'replacement':replacement})
    return edits


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
                   ['title', 'kind', 'template_id', 'pending', 'basis'])
    definitions = [
        {'name': 'read_document_context', 'description': '读取当前事实、最新文稿和本轮可用来源；不会推进事项。', 'parameters': obj()},
        {'name': 'read_document_template', 'description': '读取本板块和本公司模板的章节、版式依据和实际模板内容。',
         'parameters': obj({'template_id': string}, ['template_id'])},
        {'name': 'read_document', 'description': '读取系统内当前或历史文稿及修改锚点。修改必须基于最新版本。',
         'parameters': obj({'document_id': string, 'version': {'type': 'integer', 'minimum': 1}}, ['document_id'])},
        {'name': 'save_announcement' if announcement else 'make_word',
         'description': '保存已判断披露范围、适配模板的完整公告正文版本，等待用户确认；本工具不生成Word。' if announcement else '整理完成后制作一份或多份Word；复用当前公告或咨询回复文稿，生成待审阅文件。',
         'parameters': obj({'documents': {'type': 'array', 'items': document, 'minItems': 1, 'maxItems': 10},
                            **({'assessment':obj({'disclosure_needed':{'type':'string','enum':['yes','no','uncertain']},
                                                 'disclosure_scope':string,'reason':string,'consultation_run_id':string},
                                                ['disclosure_needed','disclosure_scope','reason'])} if announcement else {})},
                           ['documents','assessment'] if announcement else ['documents'])}]
    from .document_preflight import tool
    return definitions[:-1]+[tool()]+(definitions[-1:] if allow_production else [])


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
        _,document=receipt(runtime.root,run['id'],parts[1])
        page=int(parts[2])
        if not 1<=page<=len(document['pages']):
            raise HTTPException(422,'下载来源页码无效')
        return document['pages'][page-1]['text']
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
    mode='announcement' if text_only else 'document'
    if run['stage'] != mode or run.get('intent') != mode:
        raise HTTPException(403, '只有本轮已选择制文需求的 runtime 可以制作 Word')
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
        if not isinstance(item, dict) or set(item) - allowed or not all(k in item for k in ('title', 'kind', 'template_id', 'pending', 'basis')):
            raise HTTPException(422, '文稿字段不完整或含不支持的字段')
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
        prior_text=''
        human_source=False
        if item.get('document_id'):
            previous=store.version(runtime,run['session_id'],item['document_id'])
            if item.get('base_version') != previous['version']:
                raise HTTPException(409, '文稿已更新，不能基于旧版本制作')
            if previous['kind']!=item['kind']:raise HTTPException(409,'不能将已有公告或咨询文稿改成另一类；请明确新建需求')
            prior_text=store.snapshot(runtime,run['session_id'],item['document_id'])['text']
            human_source=previous['source_type'] in ('human_import','human_saved','manual_revision')
            if previous.get('format','docx')=='text':
                if not text:text=store.snapshot(runtime,run['session_id'],item['document_id'])['text'];item={**item,'text':text};packet['document']=item
            elif text_only:raise HTTPException(409,'已有当前公告Word，请进入document任务并优先修改现有文件')
            if previous.get('format','docx')=='docx' and not text and not item.get('edits') and len(args['documents'])==1:
                path,previous=store.file(runtime,run['session_id'],item['document_id'])
                result=[store.public_version(run['session_id'],previous)]
                runtime.store.update(rid,documents=result,outcome='completed')
                runtime.trace(rid,'documents_reused',{'documents':result,'business_state_changed':False})
                return {'data':{'documents':result,'reused_current':True},'terminate':True,'finalize':True}
            if previous.get('format','docx')=='docx' and (previous['source_type'] in ('human_import', 'manual_revision','human_saved') or item.get('edits') or item['kind']=='announcement'):
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
        evidence = []
        verified_sources = []
        unverified = []
        for binding in item['basis']:
            if not isinstance(binding, dict) or set(binding) != {'statement', 'source_id', 'quote'} or not all(isinstance(v, str) and v.strip() for v in binding.values()):
                raise HTTPException(422, '事实依据绑定无效')
            try:
                source = source_text(runtime, run, frozen, binding['source_id'])
            except HTTPException as exc:
                # Missing/malformed source references are drafting gaps. Scope,
                # version, file integrity and permission failures still stop writes.
                if exc.status_code != 422:
                    raise
                unverified.append({**binding, 'reason':str(exc.detail)})
                continue
            from .disclosure_contract import excerpt_in_source
            if not excerpt_in_source(binding['quote'],source) or binding['statement'] not in text:
                unverified.append({**binding, 'reason':'依据原句或对应表述无法定位'})
                continue
            evidence.append({**binding, 'source_sha256': store.sha(source.encode())})
            verified_sources.append(source)
        if unverified:
            return preflight.evidence_repair(runtime,rid,unverified)
        # A numeric coverage check is not a legal/factual verdict. It prevents
        # uncited model numbers from silently becoming document facts.
        clean_text = re.sub(r'https?://\S+|【待补[^】]*】', '', text)
        clean_text = re.sub(r'(?m)^\s*(?:#{1,6}\s+)?(?:[-*]\s*)?\d+[.、)]\s+', '', clean_text)
        numbers = number_tokens(clean_text)
        known_text = '\n'.join([s['text'] for s in frozen['sources']] + verified_sources +
                               [frozen['current_date'], run.get('company_code', ''),prior_text])
        if packet.get('source_base64'):
            known_text += document_files.inspect(base64.b64decode(packet['source_base64']))['text']
        unknown = sorted(numbers - number_tokens(known_text))
        gap_details = [{'kind':'numeric_source_gap', 'values':unknown}] if unknown else []
        warnings = ['部分数值未定位到依据，已在草稿中标注待补。'] if unknown else []
        if unknown:
            if packet.get('source_base64'):
                edits = pending_edits(raw_source, parsed, lambda value: mark_draft_gaps(value, unknown))
                item = {**item, 'edits':edits or item['edits']}
                _, parsed = document_files.patch(raw_source, item['edits'])
                text = parsed['text']
            else:
                text = mark_draft_gaps(text, unknown)
                item = {**item, 'text':text}
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
        checks = {'structure': 'text_saved' if text_only else 'passed', 'body_readback': 'not_created' if text_only else 'passed', 'evidence_bindings': 'passed' if evidence else 'not_provided', 'basis_count': len(evidence),
                  'numeric_source_coverage': 'pending' if unknown else 'passed',
                  'substantive_review': 'model_prepared_pending_user', 'visual_review': 'pending_user',
                  'manual_source_preserved': bool(packet.get('source_base64')) and human_source,'source_package_preserved':bool(packet.get('source_base64'))}
        snapshot = {'document': item, 'text': text, 'basis': evidence,'assessment':assessment,'method':run.get('skill'),
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
        runtime.store.update(rid, documents=result, outcome='completed',announcement_assessment=assessment)
        preflight.link_saved(runtime, rid, result)
    runtime.trace(rid, 'drafts_saved' if text_only else 'documents_created', {'documents': result, 'business_state_changed': False})
    return {'data': {'documents': result,'text_saved':text_only,'assessment':assessment,
                     'review': '公告正文已保存，可回复确认或随时要求制作Word' if text_only else '待用户审阅，未发布', 'business_state_changed': False}, 'terminate': True, 'finalize': True}


def execute(runtime, rid, name, args, stop):
    run = runtime.store.run(rid)
    if run['stage'] not in ('document','announcement') and not (run['stage']=='chat' and name in ('read_document_context','read_document')):
        raise HTTPException(403, '本轮没有文档制作权限')
    if name == 'read_document_context' and not args:
        return {'data': context(runtime, run)}
    if name == 'assess_document_readiness':
        from .document_preflight import assess
        return assess(runtime,rid,args)
    if name == 'read_document_template' and set(args) == {'template_id'}:
        return {'data': {k: v for k, v in template(runtime, run, args['template_id']).items() if k != 'raw'}}
    if name == 'read_document' and set(args) <= {'document_id', 'version'} and args.get('document_id'):
        return {'data': read_document(runtime, run, args)}
    if name in ('make_word','save_announcement'):
        attempts=run.get('document_attempts',0)+1
        runtime.store.update(rid,document_attempts=attempts)
        try:
            if attempts>3:
                raise HTTPException(409,'本轮制文已达到两次修正上限，请根据执行记录处理后继续')
            return make_word(runtime, rid, args, stop,text_only=name=='save_announcement')
        except HTTPException as exc:
            runtime.trace(rid,'document_check_failed',{'attempt':attempts,'detail':exc.detail})
            if attempts>=3:
                runtime.store.update(rid,outcome='failed',document_error=str(exc.detail))
                return {'data':{'status':'failed','reason':exc.detail,'documents_saved':False},'terminate':True,'finalize':True}
            raise
    raise HTTPException(422, '文档工具参数无效')
