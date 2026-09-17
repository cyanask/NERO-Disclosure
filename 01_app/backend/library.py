"""Bounded, read-only access to the reviewed local public-source snapshot."""
import hashlib
import json
from fastapi import HTTPException
from .library_search import match_rows
from .event_kinds import KINDS


def profiles(seeds, kind=None):
    path=seeds.public_dir/'profiles.json'
    values=json.loads(path.read_text('utf-8')) if path.exists() else []
    if any(p.get('library_board') != seeds.board or p.get('layers') != [seeds.board] for p in values):
        raise HTTPException(409,'文种清单与当前板块不一致')
    company=(getattr(seeds,'event_scope',None) or {}).get('stock_code','')
    return [p for p in values if (kind is None or p['kind']==kind) and (not p.get('company_scope') or p['company_scope']==company)]


def selected(seeds,event):
    seeds = seeds.for_event(event)
    return selected_from_catalog(event, {'profiles':profiles(seeds,None if event.get('intake_mode')=='open' else event['kind'])})


def selected_from_catalog(event, catalog):
    """Resolve the already-bound profile in a frozen task snapshot."""
    opened=event.get('intake_mode')=='open'
    choices=[p for p in catalog.get('profiles',[]) if opened or p['kind']==event['kind']]
    requested=event['facts'].get('disclosure_profile_id') or ((event.get('plan') or {}).get('profile_id') if opened else None)
    if requested:
        match=next((p for p in choices if p['id']==requested),None)
        if not match:raise HTTPException(422,'文种 profile 不适用于该事项')
        return match
    if opened:return None
    kind=event['kind'];facts=event['facts'];number=None
    if kind=='management_change':
        change=str(facts.get('change_type',''))
        number='61-3' if '换届' in change else '61-1' if any(w in change for w in ('辞','离职','resign')) else '61-2'
    elif kind=='related_transaction':
        number='16' if facts.get('is_guarantee') is True else '17-2' if facts.get('daily_expected') is True else '17-1'
    return next((p for p in choices if p.get('official_format_number')==number),choices[0] if choices else None)


def applicable_templates(seeds,event):
    seeds = seeds.for_event(event)
    profile=selected(seeds,event)
    if event.get('intake_mode')=='open':
        return [t for t in seeds.templates() if profile and t.get('profile_id')==profile['id']]
    return [t for t in seeds.templates(event['kind']) if profile is None or t.get('profile_id')==profile['id']]


CASE_KIND_LABELS = {
    'board_resolution': ('第1号 董事会决议类公告案例', '涵盖挂牌公司董事会召开、出席及议案表决全套合规公告范例。'),
    'shareholder_notice': ('第3-5号 股东会通知与延期类公告案例', '涵盖年度股东会、临时股东会通知、延期召开及增加临时提案等全套程序范例。'),
    'management_change': ('第61号 董监高人员变动类公告案例', '涵盖董监高任命、免职、辞任离职及届满换届等实际披露范例。'),
    'related_transaction': ('第13-17号 关联交易与重大资产类公告案例', '涵盖日常关联交易预计、购买出售资产、对外投资、委托理财及担保等实践范例。'),
    'litigation_arbitration': ('第63号 重大诉讼仲裁类公告案例', '涵盖挂牌公司涉案立案、一审判决及执行进展公告范例。')
}

def admitted_case(row, board):
    """Original-file verification and publication-board verification are separate."""
    return (row.get('eligible_as_case_evidence') is True
            and row.get('verification_status') == 'official_original_indexed'
            and bool(row.get('original_path'))
            and row.get('layer_at_publication') == board
            and (row.get('case_scope') or {}).get('verified_board_at_publication') == board)


def admitted_blacklist_case(row,board):
    """A regulator decision and misconduct-board review are required for admission."""
    return (row.get('admission_status')=='admitted'
            and row.get('verification_status')=='official_decision_verified'
            and row.get('layer_at_misconduct')==board
            and (row.get('case_scope') or {}).get('verified_board_at_misconduct')==board
            and any(d.get('role')=='regulatory_decision' for d in row.get('evidence_documents',[])))


def case_categories(seeds):
    catalog = seeds.catalog()
    cases = [c for c in catalog.get('cases', []) if admitted_case(c, seeds.board)]
    from collections import defaultdict
    by_kind = defaultdict(list)
    for c in cases:
        by_kind[c.get('kind', 'other')].append(c)
    
    categories = []
    for kind, (title, desc) in CASE_KIND_LABELS.items():
        cs = by_kind.get(kind, [])
        companies = list(dict.fromkeys(c.get('company') or c.get('company_name', '') for c in cs if c.get('company') or c.get('company_name')))
        categories.append({
            'id': f'category-case-{kind}',
            'kind': kind,
            'title': title if seeds.board in ('base','innovation') else KINDS[kind][0]+'案例',
            'description': '官方原件及公告时点层级均已核实的本板块案例；待核资料不计入。',
            'library_board': seeds.board,
            'case_count': len(cs),
            'companies': companies,
            'published_at': '2025-2026',
            'cases': cs
        })
    return categories


def search(seeds,collection,q="",kind=None,offset=0,limit=20,view="items",as_of=None,violation=None,disposition=None,year=None):
    catalog=seeds.catalog()
    all_cases = catalog.get("cases", [])
    admitted = [r for r in all_cases if admitted_case(r, seeds.board)]
    candidates = [r for r in all_cases if not admitted_case(r, seeds.board)]
    all_blacklist=catalog.get('blacklist_cases',[])
    admitted_blacklist=[r for r in all_blacklist if admitted_blacklist_case(r,seeds.board)]
    pending_blacklist=[r for r in all_blacklist if not admitted_blacklist_case(r,seeds.board)]
    if view == "candidates" and collection not in ("cases","blacklist_cases"):
        raise HTTPException(422, "待核资料视图仅适用于案例库")
    values={"laws":catalog.get("instruments",[]) if view=="groups" else catalog["sources"],
            "cases":case_categories(seeds) if view=="groups" else candidates if view=="candidates" else admitted,
            "blacklist_cases":pending_blacklist if view=="candidates" else admitted_blacklist,
            "profiles":profiles(seeds)}
    if collection not in values:raise HTTPException(422,"资料类型无效")
    rows=[row for row in values[collection] if not kind or kind in row.get("event_kinds",row.get('announcement_kinds',[row.get("kind")]))]
    if collection=='blacklist_cases':
        rows=[row for row in rows if (not violation or violation in row.get('violation_types',[]))
              and (not disposition or disposition==row.get('disposition_type'))
              and (not year or str(row.get('decision_date','')).startswith(str(year)))]
    matches, terms, strategy = match_rows(rows, q)
    from .public_library_index import search as index_search
    indexed=index_search(seeds.root,seeds.board,collection,q,view,kind)
    if indexed:
        known={row['id'] for row,_ in matches};byid={row['id']:row for row in rows}
        matches += [(byid[identity],list(terms)) for identity in indexed['ids'] if identity in byid and identity not in known]
        strategy={**strategy,'index':'fts5','index_expanded':any(identity not in known for identity in indexed['ids'])}
    found=[]
    for row, matched_terms in matches:
        fields = {"id","title","article","url","source_kind","instrument_id","effective_from","effective_to",
                  "as_of","kind","company","stock_code","layers","library_board","published_at","page_count","original_path",
                  "document_path","sha256","text_sha256","verification_status","scope_review_status","article_count","registered_source_count",
                  "case_admission_status","case_scope","review_status","normative_source_ids","category_id","count",
                  "announcement_kinds","violation_types","disposition_type","authority","decision_date","decision_number",
                  "wrongdoing_summary","regulator_finding","drafting_checks","admission_status","evidence_complete","evidence_documents"}
        result={k:v for k,v in row.items() if k in fields}
        if collection == "cases" and view != "groups":
            result["eligible_as_case_evidence"] = admitted_case(row, seeds.board)
        if collection=='blacklist_cases':result['eligible_as_blacklist_evidence']=admitted_blacklist_case(row,seeds.board)
        result["matched_terms"]=matched_terms
        result["unmatched_terms"]=[term for term in terms if term not in matched_terms]
        body=row.get("text","")
        if body:
            hits=[body.casefold().find(term) for term in terms if term in body.casefold()]
            start=max(0,min(hits)-80) if hits else 0
            result["text_preview"]=body[start:start+420]
            result["preview_is_full_text"]=start==0 and len(body)<=420
        found.append(result)
    if as_of and collection=="laws" and view=="items":
        def covered(row):
            from datetime import date
            try:
                point=date.fromisoformat(as_of)
                return (date.fromisoformat(row["effective_from"])<=point<=date.fromisoformat(row["as_of"]) and
                        (not row.get("effective_to") or point<=date.fromisoformat(row["effective_to"])))
            except (KeyError,TypeError,ValueError):
                return False
        found.sort(key=lambda row:(not covered(row),not bool(row.get("original_path"))))
    boundary="无结果不代表不存在义务；监管案例用于错误预防，当前适用规则仍须在法规库核对。" if collection=='blacklist_cases' else "无结果不代表不存在义务；案例只作披露实践参考。"
    res = {"board":seeds.board,"scope_notice":catalog.get("scope_notice"),"collection":collection,"total":len(found),"offset":offset,"limit":limit,"items":found[offset:offset+limit],"as_of":catalog.get("as_of"),"boundary":boundary}
    res["passages"] = indexed['passages'] if indexed else []
    res["catalog_indexed"] = bool(indexed)
    res["retrieval_backend"] = "sqlite_fts5+canonical_json" if indexed else "canonical_json"
    if indexed:res['index']=indexed['index']
    res["view"] = view
    res["search_strategy"] = strategy
    res["case_scope_summary"] = {"admitted": len(admitted), "candidates": len(candidates),
        "boundary": "数量按接纳状态分别统计；待核资料不代表本板块已核实案例。"}
    res['blacklist_scope_summary']={'admitted':len(admitted_blacklist),'candidates':len(pending_blacklist),
        'boundary':'只有官方处理决定和违规时点板块均已核实的事项进入已核实视图。'}
    return res

def item(seeds,item_id,page=None,view='auto'):
    if view not in ('auto','document'):raise HTTPException(422,'读取范围须为 auto 或 document')
    if item_id.startswith('category-case-'):
        cats = case_categories(seeds)
        match = next((c for c in cats if c['id'] == item_id), None)
        if match: return match
    row=next((r for r in seeds.knowledge()+profiles(seeds) if r['id']==item_id),None)
    if row is None:raise HTTPException(404,'资料不存在')
    result=dict(row)
    # If row is an instrument (法规大类), enrich with its articles
    catalog = seeds.catalog()
    if any(i['id'] == item_id for i in catalog.get('instruments', [])):
        result['articles'] = [{k:v for k,v in s.items() if k in ('id','title','article','text','url','sha256','board_applicability','scope_review_status')} for s in catalog.get('sources', []) if s.get('instrument_id') == item_id]
        return result
    if row.get('schema_version')=='nero.disclosure.profile.v1':
        catalog=seeds.catalog()
        result['normative_sources']=[{k:v for k,v in s.items() if k in ('id','title','article','url','source_kind')} for s in catalog['sources'] if s['id'] in row['normative_source_ids']]
        result['case_sources']=[{k:v for k,v in s.items() if k in ('id','title','published_at','source_kind','page_count','verification_status','scope_review_status','library_board')} for s in catalog['cases'] if s['id'] in {e['case_id'] for e in row['case_evidence']}]
    path=row.get('document_path')
    if path:
        document=safe_file(seeds,path)
        if row.get('document_sha256') and hashlib.sha256(document.read_bytes()).hexdigest()!=row['document_sha256']:
            raise HTTPException(409,'提取正文哈希不符，须重新核验')
        data=json.loads(document.read_text('utf-8'))
        pages=data.get('pages',[])
        result['available_pages']=[p['page'] for p in pages]
        if page is not None:
            pages=[p for p in pages if p['page']==page]
            if not pages:raise HTTPException(404,'页码不存在')
            result.pop('text',None)
        elif view=='auto' and row.get('article') and row.get('source_kind') in ('official_rule','regulation','statute') and row.get('text'):
            pages=[]
            result['read_scope']='article'
            result['reading_note']='返回本条款全文；定义、例外及引用条款须另核。用 page 读取指定页，或 view=document 展开原文。'
        result['pages']=pages
        result['text_completeness']=('registered_article_text' if result.get('read_scope')=='article' else row.get('text_completeness','imported_text_unverified')
            if row.get('verification_status')=='imported_source_unverified'
            else data.get('text_completeness','machine_extracted_full_document'))
    elif page is not None:raise HTTPException(422,'此条目按条款或profile读取，不支持页码过滤')
    return result


def safe_file(seeds,path):
    root=(seeds.root/'data/public').resolve();target=(seeds.root/path).resolve()
    if not target.is_relative_to(root) or not target.is_file():raise HTTPException(409,'资料原件路径不可用')
    return target


def asset(seeds,item_id):
    row=item(seeds,item_id)
    if not row.get('original_path'):raise HTTPException(404,'此来源仅有已登记全文快照，未保存独立原件')
    path=safe_file(seeds,row['original_path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise HTTPException(409,'原件哈希不符，须重新核验')
    return path


def evidence_asset(seeds,item_id,document_id):
    row=item(seeds,item_id)
    evidence=next((d for d in row.get('evidence_documents',[]) if d.get('id')==document_id),None)
    if not evidence or not evidence.get('original_path'):raise HTTPException(404,'证据原件不存在')
    path=safe_file(seeds,evidence['original_path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=evidence.get('sha256'):raise HTTPException(409,'证据原件哈希不符，须重新核验')
    return path


def matching_profile(document,catalog):
    """Resolve a uniquely named public document standard, after document planning.

    This is not an intake/type allowlist. Unmatched or ambiguous names stay
    source-led; existing explicit profile choices are never replaced.
    """
    import re
    if document.get('purpose')!='public':return None
    def name(value):
        value=re.sub(r'\s+','',value or '')
        value=re.sub(r'^第[0-9一二三四五六七八九十百]+号[：:、—-]*','',value)
        value=re.sub(r'^(?:挂牌公司|上市公司)','',value)
        value=re.sub(r'(?:格式模板|格式)$','',value)
        value=re.sub(r'第[0-9一二三四五六七八九十百]+(?:届|次会议)','',value)
        return value
    title=name(document.get('title'))
    found=[p for p in catalog.get('profiles',[]) if name(p.get('title')) and title.endswith(name(p['title']))]
    return found[0] if len(found)==1 else None
