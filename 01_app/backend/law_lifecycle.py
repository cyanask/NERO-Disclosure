"""法源生命周期：内容版本、法律适用与月检记录分开管理。

法规正文仍由板块 `catalog.json` 的真源条目管理；本模块只维护月检与待处理变更
记录（`law_lifecycle.json`）。到期、失败或仅刷新核验日期都不进入业务版本指纹，
因此不会阻断或失效正在进行的制稿流程（见 gates.LIFECYCLE_FIELDS）。
"""
import copy
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from fastapi import HTTPException
from .domain import Seeds
from . import library_admin

STORE='law_lifecycle.json'
HISTORY_LIMIT=24
CHECK_INTERVAL_DAYS=30
FAILURE_RETRY_DAYS=1
MAX_SNAPSHOT_CHARS=40000
STATUSES=('unscheduled','current','changed','failed')
SESSION_TITLE='法规生命周期'


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _path(root,board):
    return Seeds(Path(root)).for_board(board).public_dir/STORE


def load(root,board):
    path=_path(root,board)
    try:value=json.loads(path.read_text('utf-8'))
    except (OSError,ValueError):value={}
    if not isinstance(value,dict):value={}
    value.setdefault('board',board)
    records=value.get('records')
    value['records']=records if isinstance(records,dict) else {}
    return value


def save(root,board,document):
    document=dict(document);document['board']=board;document['updated_at']=now_iso()
    raw=(json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode()
    library_admin.atomic(_path(root,board),raw)


def instruments(root,board):
    """Group the canonical law articles into their owning instrument."""
    seeds=Seeds(Path(root)).for_board(board)
    catalog=json.loads((seeds.public_dir/'catalog.json').read_text('utf-8'))
    groups={}
    try:titles={r['id']:r.get('title') for r in json.loads((seeds.public_dir/'instruments.json').read_text('utf-8'))}
    except (OSError,ValueError,KeyError):titles={}
    for row in catalog.get('sources',[]):
        key=row.get('instrument_id') or row['id']
        group=groups.setdefault(key,{'instrument_id':key,'title':row.get('title') or key,'url':None,
            'source_ids':[],'article_count':0,'effective_from':None,'effective_to':None,'as_of':None})
        group['source_ids'].append(row['id']);group['article_count']+=1
        if row.get('title') and len(str(row['title']))>len(str(group['title'])):group['title']=row['title']
        if not group['url'] and row.get('url'):group['url']=row['url']
        for name in ('effective_from','effective_to','as_of'):
            value=row.get(name)
            if not value:continue
            if name=='effective_to':group[name]=max(group[name],value) if group[name] else value
            else:group[name]=max(group[name],value) if group[name] else value
    friendly={'chinext-announcement-formats-202607':'创业板上市公司公告格式（2026年7月）',
              'chinext-business-guide-202601':'创业板上市公司自律监管指南 · 业务办理（2026年1月）'}
    for key,group in groups.items():group['title']=friendly.get(key) or titles.get(key) or group['title']
    return groups


def source_stamp(root,board,instrument_id):
    rows=library_admin.state(root,'laws',board)['items']
    rows=[{k:r.get(k) for k in ('id','text','sha256','document_sha256','effective_from','effective_to')}
          for r in rows if (r.get('instrument_id') or r['id'])==instrument_id]
    return hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _next_check(today,days):
    return (today+timedelta(days=days)).isoformat()


def _overdue(record,today):
    if record.get('status') in ('failed',):
        return True
    target=record.get('next_check_at')
    if not target:return True
    try:return date.fromisoformat(target)<=today
    except (TypeError,ValueError):return True


def state(root,board,today=None):
    """Merged view for the lifecycle page: canonical articles plus review record."""
    today=today or date.today()
    document=load(root,board);groups=instruments(root,board)
    rows=[]
    for key,group in sorted(groups.items()):
        record=copy.deepcopy(document['records'].get(key) or {})
        status=record.get('status') if record.get('status') in STATUSES else 'unscheduled'
        rows.append({**group,'status':status,'last_checked_at':record.get('last_checked_at'),
                     'last_result':record.get('last_result'),'next_check_at':record.get('next_check_at'),
                     'pending_change':record.get('pending_change'),'history':record.get('history',[])[-HISTORY_LIMIT:],
                     'method':record.get('method'),'last_outcome':record.get('last_outcome'),
                     'evidence':record.get('evidence'),'run_id':record.get('run_id'),
                     'validity':record.get('validity','uncertain'),'validity_evidence':record.get('validity_evidence'),
                     'due':_overdue(record,today) if status!='changed' else False,
                     'needs_attention':status in ('changed','failed') or (status=='unscheduled')})
    return {'board':board,'generated_at':now_iso(),'records':rows,
            'summary':{'total':len(rows),'current':sum(1 for r in rows if r['status']=='current'),
                       'unscheduled':sum(1 for r in rows if r['status']=='unscheduled'),
                       'changed':sum(1 for r in rows if r['status']=='changed'),
                       'failed':sum(1 for r in rows if r['status']=='failed'),
                       'due':sum(1 for r in rows if r['due']),
                       'pending_changes':sum(1 for r in rows if r.get('pending_change'))}}


def _bounded_detail(exc):
    detail=getattr(exc,'detail',None) or str(exc) or '核验未完成'
    return str(detail)[:500]


def _excerpt(raw):
    if raw.startswith(b'%PDF-'):
        try:
            import io
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(raw))
            return '\n'.join((page.extract_text() or '') for page in reader.pages[:12])
        except Exception:
            return '(PDF 原件已登记哈希；本轮未提取正文)'
    try:text=raw.decode('utf-8')
    except UnicodeDecodeError:text=raw.decode('gb18030',errors='replace')
    text=re.sub(r'<(script|style)[^>]*>.*?</\1>',' ',text,flags=re.S|re.I)
    return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',text)).strip()


def default_fetch(url):
    from . import public_sources
    return public_sources.fetch(url)


def articles(root,board,instrument_id,limit=400):
    """Bounded registered-article index for one instrument (no full text bodies)."""
    seeds=Seeds(Path(root)).for_board(board)
    catalog=json.loads((seeds.public_dir/'catalog.json').read_text('utf-8'))
    rows=[row for row in catalog.get('sources',[]) if (row.get('instrument_id') or row['id'])==instrument_id]
    return [{'id':row['id'],'article':row.get('article'),'title':row.get('title'),
             'effective_from':row.get('effective_from'),'effective_to':row.get('effective_to'),
             'text_sha256':row.get('text_sha256'),'chars':len(row.get('text') or '')} for row in rows[:limit]]


def _document_text(root,source):
    try:document=json.loads((Path(root)/source['document_path']).read_text('utf-8'))
    except (OSError,ValueError,KeyError,TypeError):return ''
    return '\n'.join(page.get('text','') for page in document.get('pages',[]))


def record_result(root,board,payload,*,run_id=None,actor=None,fetch=None,expected_source=None):
    """固定登记路径：Pi 运行只提交结论，原件、指纹与到期时间由后端写入。

    - unchanged/changed 必须附本轮已下载原件，或由后端按官方地址下载并登记哈希；
    - 未变化与既有基线不一致时拒绝登记为 unchanged，反之亦然；
    - 法规正文永不在此改写。
    """
    groups=instruments(root,board)
    instrument_id=str(payload.get('instrument_id') or '')
    target=groups.get(instrument_id)
    if target is None:raise HTTPException(404,'法规不在当前板块清单')
    outcome=str(payload.get('outcome') or '')
    if outcome not in ('unchanged','changed','unavailable'):raise HTTPException(422,'核验结论无效')
    detail=str(payload.get('detail') or '').strip()
    if not detail:raise HTTPException(422,'核验结论必须说明依据')
    url=str(payload.get('official_url') or '').strip()
    download_id=payload.get('download_id')
    validity=payload.get('validity') or 'uncertain';validity_evidence=None
    if validity not in ('current','repealed','superseded','not_yet_effective','uncertain'):raise HTTPException(422,'效力结论无效')
    if validity!='uncertain':
        from . import public_sources
        source,document=public_sources.receipt(root,run_id,payload.get('validity_download_id'))
        quote=payload.get('validity_quote') or ''
        text='\n'.join(p.get('text','') for p in document.get('pages',[]))
        if source['board']!=board or not quote.strip() or re.sub(r'\s+','',quote) not in re.sub(r'\s+','',text):
            raise HTTPException(422,'效力结论须引用本轮官方原件中的可定位原文')
        validity_evidence={'url':source['final_url'],'sha256':source['sha256'],'download_id':source['download_id'],'quote':quote}
    today=date.today();checked_at=now_iso();evidence={};snapshot=''
    if outcome in ('unchanged','changed'):
        from . import public_sources
        if download_id:
            source,_=public_sources.receipt(root,run_id,download_id)
            if source.get('board')!=board:raise HTTPException(409,'原件板块与当前法规板块不一致')
        elif url and library_admin.official_url(url):
            source=public_sources.acquire(root,run_id,board,url)
        else:
            raise HTTPException(422,'登记未变化或变化须附本轮已下载原件，或提供官方 HTTPS 原文地址')
        evidence={'download_id':source.get('download_id'),'sha256':source.get('sha256'),
                  'original_path':source.get('original_path'),'final_url':source.get('final_url'),
                  'retrieved_at':source.get('retrieved_at')}
        snapshot=_document_text(root,source)[:MAX_SNAPSHOT_CHARS]
        baseline=(load(root,board)['records'].get(instrument_id) or {}).get('fetch_sha256')
        if outcome=='unchanged' and baseline and baseline!=evidence['sha256']:
            raise HTTPException(409,'原件指纹与既有基线不一致，不能登记为未变化；请核对修订后按 changed 登记')
        if outcome=='changed' and baseline and baseline==evidence['sha256'] and validity not in ('repealed','superseded','not_yet_effective'):
            raise HTTPException(409,'原件与既有基线一致，不能登记为变化')
    elif url and not library_admin.official_url(url):
        raise HTTPException(422,'官方原文地址必须为已登记官方域的 HTTPS 地址')
    status={'unchanged':'current','changed':'changed','unavailable':'failed'}[outcome]
    if outcome=='unavailable':next_check=_next_check(today,FAILURE_RETRY_DAYS)
    elif outcome=='changed':next_check=None
    else:next_check=_next_check(today,CHECK_INTERVAL_DAYS)
    record={'last_checked_at':checked_at,'last_result':detail[:1000],'status':status,'next_check_at':next_check,
            'method':'pi-runtime','checked_by':(actor or {}).get('actor','Pi 本机运行时'),'run_id':run_id,
            'evidence':evidence or None,'evidence_note':payload.get('evidence_note'),'last_outcome':outcome,
            'validity':validity,'validity_evidence':validity_evidence}
    if evidence.get('sha256'):record['fetch_sha256']=evidence['sha256']
    if outcome=='changed':
        record['pending_change']={'detected_at':checked_at,'url':evidence.get('final_url') or url or target.get('url'),
            'previous_sha256':baseline,'new_sha256':evidence.get('sha256'),'download_id':evidence.get('download_id'),
            'snapshot':snapshot}
    elif outcome=='unchanged':
        record['pending_change']=None
    with library_admin.locked(root,board):
        if expected_source and source_stamp(root,board,instrument_id)!=expected_source:
            raise HTTPException(409,'核验期间法规版本已变化，请重新核验该法规')
        document=load(root,board)
        existing=document['records'].get(instrument_id) or {}
        history=copy.deepcopy(existing.get('history') or [])
        history.append({'at':checked_at,'status':status,'detail':record['last_result'],'method':'pi-runtime'})
        record['history']=history[-HISTORY_LIMIT:]
        if not evidence.get('sha256') and existing.get('fetch_sha256'):record['fetch_sha256']=existing['fetch_sha256']
        merged={**existing,**record}
        if outcome=='unchanged':merged.pop('pending_change',None)
        document['records'][instrument_id]=merged
        save(root,board,document)
    return {'instrument_id':instrument_id,'title':target['title'],'outcome':outcome,'status':status,
            'detail':record['last_result'],'next_check_at':next_check,'evidence':evidence or None,'method':'pi-runtime',
            'validity':validity,'validity_evidence':validity_evidence}


def check(root,board,instrument_id,*,fetch=None,today=None,dry_run=False):
    """One official-source check for one instrument. Never updates law text itself."""
    fetch=fetch or default_fetch
    groups=instruments(root,board)
    target=groups.get(instrument_id)
    if target is None:raise HTTPException(404,'法规不在当前板块清单')
    url=(target.get('url') or '').strip()
    today=today or date.today()
    checked_at=now_iso()
    if not url:
        result={'status':'failed','detail':'法规缺少官方原文地址，无法核验；请先在知识库补齐官方地址'}
        next_check=_next_check(today,FAILURE_RETRY_DAYS)
    else:
        try:
            raw,content_type,final_url=fetch(url)
        except Exception as exc:
            result={'status':'failed','detail':'官方来源暂不可用：'+_bounded_detail(exc)}
            next_check=_next_check(today,FAILURE_RETRY_DAYS)
        else:
            digest=hashlib.sha256(raw).hexdigest()
            previous=(load(root,board)['records'].get(instrument_id) or {}).get('fetch_sha256')
            if previous is None:
                result={'status':'current','detail':'首次核验：已登记官方原件指纹，作为后续月度核验基线',
                        'source_sha256':digest,'final_url':final_url}
            elif previous==digest:
                result={'status':'current','detail':'官方原件与核验基线一致；未检出变化，仍需人工判断修订、废止与过渡安排',
                        'source_sha256':digest,'final_url':final_url}
            else:
                result={'status':'changed','detail':'官方原件与基线不一致，需核对修订、废止或过渡安排后再决定是否接纳新版本',
                        'source_sha256':digest,'previous_sha256':previous,'final_url':final_url,
                        'snapshot':_excerpt(raw)[:MAX_SNAPSHOT_CHARS]}
            next_check=_next_check(today,CHECK_INTERVAL_DAYS) if result['status']!='changed' else None
    record={'last_checked_at':checked_at,'last_result':result['detail'],'status':result['status'],
            'next_check_at':next_check,'source_sha256':result.get('source_sha256'),'final_url':result.get('final_url')}
    document=load(root,board)
    existing=document['records'].get(instrument_id) or {}
    if result['status']=='changed':
        record['pending_change']={'detected_at':checked_at,'url':result.get('final_url') or url,
            'previous_sha256':result.get('previous_sha256'),'new_sha256':result.get('source_sha256'),
            'snapshot':result.get('snapshot','')}
    elif existing.get('pending_change') and result['status']=='current' and result.get('source_sha256')==existing.get('fetch_sha256'):
        # Same baseline confirmed again: the previously flagged change was resolved or withdrawn elsewhere.
        result['changed_since']=existing['pending_change'].get('detected_at')
    if result['status']!='changed':record.pop('pending_change',None)
    if result.get('source_sha256'):record['fetch_sha256']=result['source_sha256']
    elif existing.get('fetch_sha256'):record['fetch_sha256']=existing['fetch_sha256']
    history=copy.deepcopy(existing.get('history') or [])
    history.append({'at':checked_at,'status':result['status'],'detail':result['detail']})
    record['history']=history[-HISTORY_LIMIT:]
    if not dry_run:
        with library_admin.locked(root,board):
            fresh=load(root,board)
            fresh['records'][instrument_id]={**(fresh['records'].get(instrument_id) or {}),**record}
            save(root,board,fresh)
    return {'instrument_id':instrument_id,'title':target['title'],'next_check_at':next_check,**result}


def run(root,board,*,fetch=None,today=None,instrument_id=None,force=False,failed_only=False,limit=None,dry_run=False):
    """Fixed monthly entry: check due instruments, or one named / failed instrument."""
    today=today or date.today()
    if instrument_id:
        targets=[instrument_id]
    else:
        document=load(root,board);groups=instruments(root,board)
        targets=[]
        for key in sorted(groups):
            record=document['records'].get(key) or {}
            status=record.get('status') if record.get('status') in STATUSES else 'unscheduled'
            if failed_only and status!='failed':continue
            if force or _overdue(record,today):targets.append(key)
        if limit:targets=targets[:limit]
    results=[]
    for key in targets:
        try:results.append(check(root,board,key,fetch=fetch,today=today,dry_run=dry_run))
        except HTTPException as exc:results.append({'instrument_id':key,'status':'failed','detail':_bounded_detail(exc)})
    return {'board':board,'checked_at':now_iso(),'count':len(results),
            'changed':[r['instrument_id'] for r in results if r['status']=='changed'],
            'failed':[r['instrument_id'] for r in results if r['status']=='failed'],
            'current':[r['instrument_id'] for r in results if r['status']=='current'],
            'results':results}
