"""Company-scoped published originals and their single, derived announcement schedule."""
import copy
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from .boards import require_board
from .public_store import atomic, locked, sha


def now(): return datetime.now(timezone.utc).isoformat()
def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()


def company_key(code):
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
        raise HTTPException(422, '请选择公司并提供六位证券代码')
    return code


def directory(root, board, code):
    return Path(root)/'data/client_announcements'/require_board(board)/company_key(code)


def state(root, board, code):
    path=directory(root,board,code)/'catalog.json'
    value=json.loads(path.read_text()) if path.exists() else {
        'board':board,'stock_code':code,'company_name':'','items':[],
        'coverage':{'from':None,'through':None,'complete':False,'note':'尚未确认历史覆盖范围'},'revision':0}
    return {**value,'fingerprint':sha(encoded(value))}


def companies(root, board):
    require_board(board);base=Path(root)/'data/client_announcements'/board
    return [{'stock_code':p.parent.name,'company_name':(v:=json.loads(p.read_text()))['company_name'],
             'count':sum(not r.get('deleted_at') for r in v['items'])} for p in sorted(base.glob('*/catalog.json'))]


def save(root, board, code, expected, change, actor):
    with locked(root,board):
        previous=state(root,board,code)
        if previous['fingerprint']!=expected:raise HTTPException(409,'公司历史公告已变化，请重新读取')
        target=directory(root,board,code);target.mkdir(parents=True,exist_ok=True)
        history=target/'history';history.mkdir(exist_ok=True)
        before={k:v for k,v in previous.items() if k!='fingerprint'}
        value=copy.deepcopy(before);change(value)
        value.update(revision=previous['revision']+1,updated_at=now(),updated_by=actor)
        atomic(history/(previous['fingerprint']+'.json'),encoded(before))
        atomic(target/'catalog.json',encoded(value))
        result=state(root,board,code)
    try:
        from .announcement_index import sync
        result['index']={'status':'current',**sync(root,board,code)}
    except Exception as exc:result['index']={'status':'stale','error':str(exc)[:300]}
    return result


def register_company(root, board, code, name):
    if not isinstance(name,str) or not 2<=len(name.strip())<=150:raise HTTPException(422,'请填写公司名称')
    old=state(root,board,code)
    if old['company_name']:
        if old['company_name']!=name.strip():raise HTTPException(409,'该证券代码已登记其他名称，请核对公司')
        return old
    return save(root,board,code,old['fingerprint'],lambda v:v.update(company_name=name.strip()),'用户登记')


def number(value):
    if value.isdigit():return int(value)
    digits=dict(zip('零〇一二两三四五六七八九',[0,0,1,2,2,3,4,5,6,7,8,9]))
    total=current=0
    for ch in value:
        if ch in digits:current=digits[ch]
        elif ch in '十百千':total+=(current or 1)*{'十':10,'百':100,'千':1000}[ch];current=0
        else:return None
    return total+current


N=r'[零〇一二两三四五六七八九十百千\d]+'


def extract_fields(text, title=''):
    """Only unambiguous literal fields; raw quotes survive normalization."""
    clean=re.sub(r'\s+','',text);heading=re.sub(r'\s+','',title)
    result={'meeting':None,'announcement_number':None,'meeting_date':None,'anchors':{}}
    announcement=re.search(r'公告编号[:：]([12]\d{3}[-－—]\d+)',clean)
    if announcement:
        result['announcement_number']=re.sub('[－—]','-',announcement[1]);result['anchors']['announcement_number']=announcement[0]
    # A title/first paragraph identifies this document's meeting; later references do not.
    sample=heading or clean[:350]
    board=re.search(rf'第({N})届(?:董事会|监事会)第({N})次(?:临时)?会议|第({N})届第({N})次(?:董事会|监事会)(?:会议)?',sample)
    shareholder=re.search(rf'([12]\d{{3}})年(?:度)?第({N})次临时股东(?:大)?会|([12]\d{{3}})年(?:度)?(?:年度)?股东(?:大)?会',sample)
    annual_board=re.search(rf'(董事会|监事会)([12]\d{{3}})年(?:度)?第({N})次会议',sample)
    match=board or shareholder or annual_board
    if board:
        result['meeting']={'organ':'监事会' if '监事会' in board[0] else '董事会','term':number(board[1] or board[3]),'year':None,'sequence':number(board[2] or board[4]),'basis':'term','meeting_type':'meeting'}
    elif shareholder:
        result['meeting']={'organ':'股东会','term':None,'year':int(shareholder[1] or shareholder[3]),'sequence':number(shareholder[2]) if shareholder[2] else None,'basis':'year','meeting_type':'临时' if shareholder[2] else '年度'}
    elif annual_board:
        result['meeting']={'organ':annual_board[1],'term':None,'year':int(annual_board[2]),'sequence':number(annual_board[3]),'basis':'year','meeting_type':'meeting'}
    if match:result['anchors']['meeting']=match[0]
    dates=set()
    for m in re.finditer(r'(?:召开(?:时间|日期)?|会议(?:时间|日期)|于)[:：为]?([12]\d{3})年(\d{1,2})月(\d{1,2})日',clean):
        nearby=clean[max(0,m.start()-15):m.end()+30]
        if '召开' not in nearby and '会议时间' not in nearby and '会议日期' not in nearby:continue
        try:dates.add(date(int(m[1]),int(m[2]),int(m[3])).isoformat())
        except ValueError:continue
    if len(dates)==1:result['meeting_date']=next(iter(dates))
    result['relation']='corrected' if re.search('更正|修订',heading) else 'cancelled' if re.search('取消|终止',heading) else 'postponed' if '延期' in heading else 'progress' if '进展' in heading else 'new'
    return result


def meeting_key(fields):
    m=fields.get('meeting') or {}
    return tuple(m.get(k) for k in ('organ','basis','term','year','meeting_type','sequence')) if m else None


def add(root, board, code, entry, expected, actor):
    for key in ('title','published_at','publication_url','original_path','sha256','document_path','document_sha256'):
        if not entry.get(key):raise HTTPException(422,'历史公告缺少：'+key)
    try:
        if date.fromisoformat(entry['published_at'])>date.today():raise ValueError()
    except ValueError:raise HTTPException(422,'发布日期无效或晚于今天')
    if entry.get('publication_confirmed') is not True:raise HTTPException(422,'请确认这是已正式发布的公告；工作稿不能进入历史公告库')
    from .public_store import official_url
    if not official_url(entry['publication_url']):raise HTTPException(422,'请提供交易所、巨潮等官方发布链接')
    current=state(root,board,code)
    if not current['company_name']:raise HTTPException(422,'请先登记当前公司')
    def update(value):
        if any(x['sha256']==entry['sha256'] and not x.get('deleted_at') for x in value['items']):return
        related=set(entry.get('related_ids',[]));known={x['id'] for x in value['items'] if not x.get('deleted_at')}
        if related-known:raise HTTPException(422,'关联公告不属于当前公司或已删除')
        if not related and meeting_key(entry):related={r['id'] for r in visible(value) if meeting_key(r)==meeting_key(entry)}
        row={**entry,'related_ids':sorted(related),'stock_code':code,'company_name':value['company_name'],'board':board,
            'publication_status':'user_confirmed_published','added_at':now(),'actor':actor}
        retired=next((r for r in value['items'] if r['id']==row['id']),None)
        if retired is not None:
            retired.update(row);retired.pop('deleted_at',None)
        else:value['items'].append(row)
    return save(root,board,code,expected,update,actor)


def visible(value):return [r for r in value['items'] if not r.get('deleted_at')]


def snapshot(root, event):
    code=event.get('stock_code')
    if not code or not re.fullmatch(r'\d{6}',code):return {'status':'not_connected','items':[],'coverage':{'complete':False},'fingerprint':None,'not_found_is_absence':False}
    value=state(root,event['layer'],code)
    rows=visible(value)
    from .announcement_index import status as index_status
    indexed=index_status(root,event['layer'],code)
    if indexed.get('status')=='current':integrity=indexed.get('integrity_errors',[])
    else:
        integrity=[]
        for row in rows:
            try:read(root,event['layer'],code,row['id'],1)
            except HTTPException:integrity.append(row['id'])
    # Only this company's history enters this event's context.
    return {'status':'connected' if value['company_name'] else 'not_connected','stock_code':code,
        'company_name':value['company_name'],'coverage':value['coverage'],'fingerprint':value['fingerprint'],'integrity_errors':integrity,'index':indexed,
        'items':[{k:r.get(k) for k in ('id','title','published_at','announcement_number','meeting','meeting_date','relation','related_ids','anchors','sha256','document_sha256','publication_url')} for r in rows],
        'not_found_is_absence':False}


def read(root,board,code,identity,page=None):
    value=state(root,board,code);row=next((r for r in visible(value) if r['id']==identity),None)
    if not row:raise HTTPException(404,'当前公司没有这份历史公告')
    base=directory(root,board,code).resolve()
    for key,h in (('original_path','sha256'),('document_path','document_sha256')):
        path=(Path(root)/row[key]).resolve()
        if not path.is_relative_to(base) or not path.is_file() or sha(path.read_bytes())!=row[h]:raise HTTPException(409,'公告原件或正文版本不一致')
    document=json.loads((Path(root)/row['document_path']).read_text());pages=document['pages']
    if page is not None:
        pages=[p for p in pages if p['page']==page]
        if not pages:raise HTTPException(404,'页码不存在')
    return {**{k:v for k,v in row.items() if k!='text'},'pages':pages,'page_count':len(document['pages'])}


def search(root,event,query='',offset=0,limit=20):
    from .library_search import match_rows
    value=snapshot(root,event)
    if value['status']=='not_connected':return value
    from .announcement_index import search as index_search
    indexed=index_search(root,event['layer'],event['stock_code'],query,offset,limit)
    if indexed is not None:return {**value,**indexed,'retrieval_backend':'company_sqlite_fts5','catalog_indexed':True}
    matches,_,strategy=match_rows(visible(state(root,event['layer'],event['stock_code'])),query)
    ids={r['id'] for r,_ in matches};metadata={r['id']:r for r in value['items']}
    return {**value,'items':[metadata[r['id']] for r,_ in matches[offset:offset+limit]],'passages':[],'total':len(ids),'offset':offset,'limit':limit,'search_strategy':strategy,'retrieval_backend':'canonical_json','catalog_indexed':False}


def context_summary(value):
    return {**value,'items':value.get('items',[])[-30:],'total':len(value.get('items',[])),
        'context_is_partial':len(value.get('items',[]))>30,'instruction':'按公告时间表定位，再用本公司历史查询与页级读取核对相关公告；摘要不代表已读全部原件。'}


def field_check_receipt(event, history):
    """Scope of check()'s metadata comparison, never a full-text review certificate."""
    draft=event.get('draft') or {}
    docs=draft.get('documents') or ([{'title':event.get('title',''),'text':draft.get('text','')}] if draft else [])
    applicable=any(meeting_key(f:=extract_fields(d.get('text',''),d.get('title',''))) or f['announcement_number'] for d in docs)
    rows=history.get('items',[])
    return {'performed':bool(applicable and rows), 'method':'announcement_fields',
            'scope':'all_registered', 'count':len(rows), 'stock_code':history.get('stock_code'),
            'fingerprint':history.get('fingerprint'), 'coverage':history.get('coverage',{}),
            'fields':['公告编号','会议日期'],
            'items':[{k:r.get(k) for k in ('id','title','published_at','sha256')} for r in rows]}


def check(event, history, drafts=()):
    """Detect concrete contradictions; absent history never implies a complete ledger."""
    errors=[];warnings=[]
    draft=event.get('draft') or {};docs=draft.get('documents') or ([{'title':event.get('title',''),'text':draft.get('text','')}] if draft else [])
    prior=history.get('items',[])
    for identity in history.get('integrity_errors',[]):errors.append({'code':'history_integrity','detail':'历史公告原件或提取正文已变化，须重新核对','source_id':identity})
    for doc in docs:
        body=doc.get('text','');fields=extract_fields(body,doc.get('title',''));key=meeting_key(fields)
        if not key and not fields['announcement_number']:continue
        for old in prior:
            related=old['id'] in event.get('facts',{}).get('historical_links',[])
            if fields['announcement_number'] and fields['announcement_number']==old.get('announcement_number') and fields['relation'] not in ('corrected','cancelled'):
                errors.append({'code':'announcement_number_conflict','detail':'公告编号与已发布公告重复：'+old['title'],'source_id':old['id']})
            if key and key==meeting_key(old) and fields.get('meeting_date') and old.get('meeting_date') and fields['meeting_date']!=old['meeting_date'] and not (related and fields['relation'] in ('postponed','corrected')):
                errors.append({'code':'meeting_date_conflict','detail':f"同一届次/序号会议日期矛盾：新稿 {fields['meeting_date']}，历史 {old['meeting_date']}（{old['title']}）",'source_id':old['id']})
        if key and not fields['meeting_date']:warnings.append({'code':'meeting_date_unknown','detail':'本稿会议日期尚不能唯一确定，请在全文确认时核对'})
        for other in drafts:
            if other.get('id')==event.get('id'):continue
            for od in (other.get('draft') or {}).get('documents',[]) or [{'text':(other.get('draft') or {}).get('text',''),'title':other.get('title','')}]:
                f=extract_fields(od.get('text',''),od.get('title',''))
                duplicate=fields['announcement_number'] and fields['announcement_number']==f['announcement_number']
                inconsistent=key and key==meeting_key(f) and fields['meeting_date'] and f['meeting_date'] and fields['meeting_date']!=f['meeting_date']
                if duplicate or inconsistent:errors.append({'code':'concurrent_announcement_conflict','detail':'与同公司其他在制稿编号或会议日期冲突：'+other.get('title',''),'source_id':other['id']})
    coverage=history.get('coverage',{});point=event.get('facts',{}).get('event_date') or event.get('facts',{}).get('assessment_as_of') or date.today().isoformat()
    if docs and not (coverage.get('complete') and coverage.get('from','')<=point<=coverage.get('through','')):
        warnings.append({'code':'history_coverage_unknown','detail':'公告时间表尚未确认完整覆盖；连续性核对仅覆盖已登记公告'})
    return errors,warnings
