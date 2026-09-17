#!/usr/bin/env python3
"""Download one issuer's official CNINFO announcement directory into history.

The issuer scope, source URLs and bytes are persisted.  The coverage flag stays
unconfirmed until a user reviews the official directory count.
"""
import argparse, hashlib, io, json, re, sys, time, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
from backend import announcement_history as history
from backend import file_ingestion
from backend.library_admin import atomic, sha

API='http://www.cninfo.com.cn/new/hisAnnouncement/query'
HEADERS={'User-Agent':'Mozilla/5.0',
         'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','Referer':'https://www.cninfo.com.cn/',
         'Accept':'application/json, text/javascript, */*; q=0.01','X-Requested-With':'XMLHttpRequest'}

def clean(value):return re.sub(r'<[^>]+>','',value or '').strip()

def query(page, page_size, search_key, date_range=''):
    params={'pageNum':str(page),'pageSize':str(page_size),'column':'szse_gem','tabName':'fulltext','plate':'szse',
            'stock':'','searchkey':search_key,'secid':'','category':'','trade':'','seDate':date_range,
            'sortName':'','sortType':'','isHLtitle':'true'}
    req=Request(API,data=urlencode(params).encode(),headers=HEADERS)
    last=None
    for attempt in range(4):
        try:return json.loads(urlopen(req,timeout=30).read())
        except Exception as exc:
            last=exc;time.sleep(1.5*(attempt+1))
    raise last

def official_page(url, code):
    return 'https://www.cninfo.com.cn/new/disclosure/detail?'+urlencode({'plate':'szse','stockCode':code,'announcementId':url})

def fetch_one(item, root, board, code, company):
    adjunct=item['adjunctUrl'];pdf_url='https://static.cninfo.com.cn/'+adjunct
    raw=None;last=None
    for attempt in range(4):
        try:
            raw=subprocess.check_output(['curl','-fsSL','--max-time','45','-A',HEADERS['User-Agent'],'-e','https://www.cninfo.com.cn/',pdf_url],stderr=subprocess.DEVNULL)
            break
        except Exception as exc:
            last=exc;time.sleep(1.0+attempt)
    if raw is None:raise last
    if not raw.startswith(b'%PDF-'):raise ValueError('not a PDF: '+pdf_url)
    digest=hashlib.sha256(raw).hexdigest();base=Path(root)/'data/client_announcements'/board/code
    original=base/'originals'/(digest+'.pdf');document=base/'documents'/(digest+'.json');(base/'originals').mkdir(parents=True,exist_ok=True);(base/'documents').mkdir(parents=True,exist_ok=True)
    if not original.exists():atomic(original,raw)
    parsed=file_ingestion.extract(original)
    atomic(document,history.encoded(parsed))
    full='\n'.join(p.get('text','') for p in parsed['pages']);title=clean(item['announcementTitle'])
    fields=history.extract_fields(full,title)
    published=datetime.fromtimestamp(int(item['announcementTime'])/1000,tz=timezone.utc).date().isoformat()
    announcement_id=str(item.get('announcementId') or item.get('announcementID') or digest[:16])
    row={'id':'announcement-'+code+'-'+announcement_id,'title':title,'text':full,'published_at':published,
        'announcement_number':fields.get('announcement_number'),'meeting':fields.get('meeting'),'meeting_date':fields.get('meeting_date'),
        'anchors':fields.get('anchors',{}),'relation':fields.get('relation'),'related_ids':[],
        'url':pdf_url,'publication_url':pdf_url,'original_path':str(original.relative_to(root)),
        'document_path':str(document.relative_to(root)),'sha256':digest,'document_sha256':sha(document.read_bytes()),
        'page_count':len(parsed['pages']),'text_completeness':parsed['text_completeness'],'needs_review':parsed['needs_review'],
        'warnings':parsed['warnings'],'kind':file_ingestion.classify(title),'source_kind':'official_issuer_or_related',
        'publication_confirmed':True,'source_verified':'cninfo_directory','stock_code':code,'company_name':company,
        'board':board,'retrieval_method':'cninfo_fulltext_company_directory','added_at':datetime.now(timezone.utc).isoformat()}
    return row

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default=str(workspace_paths.knowledge_of(ROOT)));ap.add_argument('--board',default='chinext');ap.add_argument('--stock-code',required=True,help='六位证券代码');ap.add_argument('--company',required=True,help='公司名称，同时用作巨潮目录检索词');ap.add_argument('--date-range',default='',help='可选，格式 2020-01-01 ~ 2026-09-14');ap.add_argument('--workers',type=int,default=6);ap.add_argument('--title',default='');args=ap.parse_args()
    root=Path(args.root);root.mkdir(parents=True,exist_ok=True)
    first=query(1,30,args.company,args.date_range);total=int(first.get('totalAnnouncement') or 0);pages=(total+29)//30
    items=[]
    for page in range(1,pages+1):
        payload=first if page==1 else query(page,30,args.company,args.date_range)
        for item in payload.get('announcements') or []:
            code=item.get('secCode','');name=clean(item.get('secName',''))
            if code==args.stock_code and args.company in name and str(item.get('adjunctUrl','')).lower().endswith('.pdf'):
                item['announcementTitle']=clean(item.get('announcementTitle',''));items.append(item)
    unique={str(x.get('announcementId') or x.get('announcementID') or x.get('adjunctUrl')):x for x in items};items=list(unique.values())
    if args.title:items=[x for x in items if args.title in x.get('announcementTitle','')]
    print(json.dumps({'directory_total':total,'downloadable_records':len(items),'pages':pages},ensure_ascii=False))
    results=[];errors=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(fetch_one,item,root,args.board,args.stock_code,args.company):item for item in items}
        for future in as_completed(jobs):
            try:results.append(future.result())
            except Exception as exc:errors.append({'title':jobs[future].get('announcementTitle'),'error':str(exc)})
    results.sort(key=lambda x:(x['published_at'],x['announcement_number'] or '',x['title']))
    by_meeting={}
    for row in results:
        key=history.meeting_key(row)
        if key:by_meeting.setdefault(key,[]).append(row['id'])
    for row in results:
        key=history.meeting_key(row);row['related_ids']=[x for x in by_meeting.get(key,[]) if x!=row['id']]
    target=Path(root)/'data/client_announcements'/args.board/args.stock_code;target.mkdir(parents=True,exist_ok=True)
    prior=history.state(root,args.board,args.stock_code)
    from backend.announcement_tags import source_key
    by_id={r['id']:r for r in prior.get('items',[])}
    for row in results:
        old=by_id.get(row['id'])
        if old and source_key(old)==source_key(row):
            for key in ('classification_override','classification_review','corrections'):
                if key in old:row[key]=old[key]
    previous=history.state(root,args.board,args.stock_code);merged={r['id']:r for r in previous.get('items',[])};merged.update({r['id']:r for r in results});final_items=sorted(merged.values(),key=lambda x:(x['published_at'],x.get('announcement_number') or '',x['title']))
    catalog={'board':args.board,'stock_code':args.stock_code,'company_name':args.company,'items':final_items,
        'coverage':{'from':min((r['published_at'] for r in final_items),default=None),'through':max((r['published_at'] for r in final_items),default=None),
                    'complete':False,'directory_total':total,'downloaded_records':len(final_items),'failed_records':errors,
                    'note':'已下载巨潮官方目录返回的记录；完整覆盖范围仍待用户确认。'},'revision':prior.get('revision',0)+1,
        'updated_at':datetime.now(timezone.utc).isoformat(),'updated_by':'官方目录批量接纳'}
    atomic(target/'catalog.json',history.encoded(catalog))
    atomic(target/'batch-receipt.json',history.encoded({'directory_total':total,'downloaded_records':len(results),'failed_records':errors,
        'source':'https://www.cninfo.com.cn/','retrieval_at':datetime.now(timezone.utc).isoformat(),'coverage_user_confirmed':False}))
    from backend.announcement_index import sync as sync_index
    indexed=sync_index(root,args.board,args.stock_code)
    from backend.announcement_review import request_local
    review=request_local(root,args.board,args.stock_code,[r['id'] for r in results])
    print(json.dumps({'classification_review':review},ensure_ascii=False))
    print(json.dumps({'status':'completed','directory_total':total,'downloaded_records':len(final_items),'failed_records':len(errors),'company':args.company,'stock_code':args.stock_code,'index':indexed},ensure_ascii=False))
    if errors:print(json.dumps(errors[:10],ensure_ascii=False),file=sys.stderr)

if __name__=='__main__':main()
