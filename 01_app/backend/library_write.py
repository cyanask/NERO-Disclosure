"""Manifest row rules and rebuildable projections.

The commit protocol (lock, version guard, history snapshot, atomic replace)
lives in ``library_admin``; this module owns what a row must satisfy and how the
per-profile files and the SQLite index are rebuilt after a commit. Projection
failures are reported as warnings and never fail a committed edit.
"""
import json
import re
from datetime import date
from fastapi import HTTPException
from .domain import Seeds
from .library import safe_file
from .public_store import atomic, official_url, sha, template_dir

COLLECTIONS = {'laws':('catalog.json','sources'), 'cases':('catalog.json','cases'),
               'blacklist_cases':('catalog.json','blacklist_cases'), 'profiles':('profiles.json',None)}
BLACKLIST_DISPOSITIONS={'administrative_penalty','disciplinary_action','regulatory_measure'}
BLACKLIST_DOCUMENT_ROLES={'regulatory_decision','affected_announcement','correction','remediation','follow_up'}


def checked_rows(data,key,board):
    if key and data.get('board')!=board:
        raise HTTPException(409,'知识库清单与当前板块不一致')
    rows=data[key] if key else data
    if any(row.get('library_board')!=board or (row.get('layers') and row['layers']!=[board]) for row in rows):
        raise HTTPException(409,'知识库含其他板块记录，请先核对清单归属')
    return rows


def _verified_asset(root,entry,path_key='original_path',hash_key='sha256'):
    if not entry.get(path_key):raise HTTPException(422,'证据文件缺少原件或结构化正文')
    actual=sha(safe_file(Seeds(root),entry[path_key]).read_bytes())
    if entry.get(hash_key) and entry[hash_key]!=actual:raise HTTPException(422,'原件或提取文件哈希不符')
    entry[hash_key]=actual


def _validate_blacklist(root,row,board):
    required=('company','stock_code','authority','decision_date','decision_number','wrongdoing_summary','regulator_finding')
    for key in required:
        if not isinstance(row.get(key),str) or not row[key].strip():raise HTTPException(422,'黑名单案例字段缺失：'+key)
    if not re.fullmatch(r'\d{6}',row['stock_code']):raise HTTPException(422,'证券代码须为6位数字')
    try:date.fromisoformat(row['decision_date'])
    except ValueError:raise HTTPException(422,'处理决定日期无效')
    if row.get('disposition_type') not in BLACKLIST_DISPOSITIONS:raise HTTPException(422,'监管处理性质无效')
    for key in ('announcement_kinds','violation_types','drafting_checks'):
        if not isinstance(row.get(key),list) or not row[key] or any(not isinstance(x,str) or not x.strip() for x in row[key]):raise HTTPException(422,'黑名单案例分类或检查项无效：'+key)
    documents=row.get('evidence_documents')
    if not isinstance(documents,list) or not documents:raise HTTPException(422,'黑名单案例须登记证据文件')
    if len({d.get('id') for d in documents})!=len(documents):raise HTTPException(422,'证据文件编号重复')
    for document in documents:
        if not isinstance(document,dict) or document.get('role') not in BLACKLIST_DOCUMENT_ROLES or not isinstance(document.get('id'),str):raise HTTPException(422,'证据文件结构或角色无效')
        if not isinstance(document.get('title'),str) or not document['title'].strip() or not official_url(document.get('url')):raise HTTPException(422,'证据文件须登记标题和官方来源')
        _verified_asset(root,document);_verified_asset(root,document,'document_path','document_sha256')
        parsed=json.loads(safe_file(Seeds(root),document['document_path']).read_text('utf-8'))
        if not isinstance(parsed.get('pages'),list) or not parsed['pages']:raise HTTPException(422,'证据文件缺少页级正文')
    decisions=[d for d in documents if d['role']=='regulatory_decision']
    if not decisions:raise HTTPException(422,'黑名单案例缺少官方处理决定')
    row.update(schema_version='nero.disclosure.blacklist_case.v1',source_kind='blacklist_case',layer_at_misconduct=board)
    row['evidence_complete']=all(any(d['role']==role for d in documents) for role in ('regulatory_decision','affected_announcement'))
    admitted=row.get('admission_status')=='admitted'
    if admitted:
        scope=row.get('case_scope') or {}
        if row.get('verification_status')!='official_decision_verified' or scope.get('verified_board_at_misconduct')!=board:
            raise HTTPException(422,'已核实案例须完成官方决定和违规时点板块核验')
    else:
        row['admission_status']='pending_review';row['verification_status']='official_decision_pending_review'
    primary=decisions[0]
    for key in ('url','original_path','document_path','sha256','document_sha256','page_count'):
        if primary.get(key) is not None:row[key]=primary[key]
    return row


def validate(root,collection,row,previous,catalog,profiles,board):
    if row.get('library_board',board)!=board:
        raise HTTPException(422,'条目与目标知识库板块不一致')
    row['library_board']=board
    if row.get('layers') and row['layers']!=[board]:
        raise HTTPException(422,'条目层级必须与目标板块一致')
    if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9][\w.-]{0,149}',row['id']):
        raise HTTPException(422,'资料必须有有效的 id')
    if not isinstance(row.get('title'),str) or not row['title'].strip():raise HTTPException(422,'资料标题缺失')
    if collection=='laws':
        for key in ('text','instrument_id','article','effective_from','as_of'):
            if not isinstance(row.get(key),str) or not row[key].strip():raise HTTPException(422,'法源字段缺失：'+key)
        if row.get('effective_to') is not None and not isinstance(row['effective_to'],str):raise HTTPException(422,'法源失效日期须为日期字符串或空值')
        try:
            start=date.fromisoformat(row['effective_from']);as_of=date.fromisoformat(row['as_of'])
            end=date.fromisoformat(row['effective_to']) if row.get('effective_to') else None
            if end and end<start:raise ValueError()
            if as_of>date.today():raise ValueError()
        except (TypeError,ValueError):raise HTTPException(422,'法源生效、失效或核验日期无效')
        if not official_url(row.get('url')):raise HTTPException(422,'法源须提供官方 HTTPS 原文地址')
        if row.get('source_kind') not in ('official_rule','official_format','regulation','statute'):raise HTTPException(422,'法源类型无效')
        row['effective_to']=row.get('effective_to') or None
        if previous and any((row.get(k) or None)!=(previous.get(k) or None) for k in ('effective_from','effective_to','instrument_id')):
            raise HTTPException(422,'修订法源适用期间或制度版本须使用新 id，保留旧版本；不能覆写历史时效')
        replacements=row.get('replaces_source_ids',[])
        if not isinstance(replacements,list) or any(not isinstance(x,str) or not x or x==row['id'] for x in replacements):raise HTTPException(422,'替代法源编号列表无效')
        row['text_sha256']=sha(row['text'].encode())
        # `sha256` keeps its original-file meaning; text has a different field.
        if not row.get('original_path'):row.pop('sha256',None)
    if collection in ('laws','cases'):
        for path_key,hash_key in (('original_path','sha256'),('document_path','document_sha256')):
            if row.get(path_key):
                actual=sha(safe_file(Seeds(root),row[path_key]).read_bytes())
                if row.get(hash_key) and row[hash_key]!=actual:raise HTTPException(422,'原件或提取文件哈希不符')
                row[hash_key]=actual
        if collection=='cases' and (not row.get('original_path') or not row.get('document_path')):
            raise HTTPException(422,'案例收录须绑定原件与提取正文')
    if collection=='cases':
        if row.get('source_kind')!='official_case' or not official_url(row.get('url')):raise HTTPException(422,'案例须登记官方原文来源')
        document=json.loads(safe_file(Seeds(root),row['document_path']).read_text('utf-8'))
        if not isinstance(document,dict) or not isinstance(document.get('pages'),list) or not document['pages']:raise HTTPException(422,'案例提取正文缺少页级记录')
    if collection=='blacklist_cases':
        row=_validate_blacklist(root,row,board)
    if collection=='profiles':
        sections=row.get('sections');refs=row.get('normative_source_ids');evidence=row.get('case_evidence')
        if not isinstance(sections,list) or any(not isinstance(s,dict) or not isinstance(s.get('id'),str) or not isinstance(s.get('title'),str) or not isinstance(s.get('fields'),list) for s in sections):raise HTTPException(422,'文种章节结构无效')
        if not isinstance(refs,list) or any(not isinstance(x,str) for x in refs):raise HTTPException(422,'文种法源引用结构无效')
        if not isinstance(evidence,list) or any(not isinstance(e,dict) or not isinstance(e.get('case_id'),str) for e in evidence):raise HTTPException(422,'文种案例引用结构无效')
        if not isinstance(row.get('kind'),str) or not 1<=len(row['kind'].strip())<=100:raise HTTPException(422,'文种事项标签无效')
        row['schema_version']='nero.disclosure.profile.v1'
        if not isinstance(row.get('official_format_number'),str) or not row['official_format_number']:raise HTTPException(422,'文种官方格式编号缺失')
        if not isinstance(row.get('layers'),list) or not row['layers'] or set(row['layers'])-{board}:raise HTTPException(422,'文种层级须与当前板块一致')
        for section in sections:
            if not section['id'].strip() or not section['title'].strip():raise HTTPException(422,'文种章节编号或标题为空')
            for field in section['fields']:
                if not isinstance(field,dict) or not isinstance(field.get('prompt',''),str):raise HTTPException(422,'文种字段结构无效')
                rows=field.get('table_rows')
                if rows is None:rows=[]
                if not isinstance(rows,list) or any(not isinstance(r,list) or any(not isinstance(v,str) for v in r) for r in rows):raise HTTPException(422,'文种表格结构无效')
        legal={s['id'] for s in catalog['sources']};cases={s['id'] for s in catalog.get('cases',[])}
        if not row.get('sections') or len({s['id'] for s in row['sections']})!=len(row['sections']):raise HTTPException(422,'文种章节缺失或编号重复')
        if not row.get('normative_source_ids') or not set(row['normative_source_ids'])<=legal:raise HTTPException(422,'文种法源引用无效')
        if (not row.get('case_evidence') and row.get('scope_review_status')!='format_and_case_evidence_pending') or any(e['case_id'] not in cases for e in row['case_evidence']):raise HTTPException(422,'文种案例引用无效')
        layouts=json.loads((Seeds(root).for_board(board).template_dir/'layout_profiles.json').read_text())
        if row.get('layout_profile_id') not in {p['id'] for p in layouts}:raise HTTPException(422,'文种版式规则无效')
        if previous and row.get('kind')!=previous.get('kind'):raise HTTPException(422,'修改文种事项类型须使用新 id')
    return row


def validate_change(root,collection,row,previous,board):
    """Preview-time check of one proposed row; uses the same manifests a write would."""
    seeds=Seeds(root).for_board(board)
    catalog=json.loads((seeds.public_dir/'catalog.json').read_text())
    profiles=json.loads((seeds.public_dir/'profiles.json').read_text())
    return validate(root,collection,row,previous,catalog,profiles,board)


def rebuild_profile_projections(seeds,collection,revised):
    """Per-profile files are a rebuildable projection of the committed manifest."""
    if collection!='profiles':return []
    warnings=[]
    for row in revised:
        target=seeds.public_dir/'profiles'/(row['id']+'.json')
        if not target.resolve().is_relative_to((seeds.public_dir/'profiles').resolve()):
            warnings.append('文种独立文件投影路径异常，未写入');continue
        try:
            target.parent.mkdir(exist_ok=True)
            atomic(target,(json.dumps(row,ensure_ascii=False,indent=2)+'\n').encode())
        except OSError:warnings.append('文种独立文件投影待重建')
    return warnings


def rebuild_index(root,board,warnings,message):
    """The SQLite directory index is a rebuildable projection of the committed JSON."""
    try:
        from scripts.sync_sqlite_library import sync_library_db
        sync_library_db(root=root,board=board)
    except Exception:warnings.append(message)
