"""Rebuildable per-company SQLite index over canonical history JSON and files."""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from . import announcement_tags

SCHEMA='nero.announcement.index.v2'
LARGE_PAGES=80
LARGE_TITLE=re.compile(r'招股(?:意向)?说明书|法律意见书|年度报告|半年度报告|审计报告|问询函.*回复')
HEADING_RULES=[
    (1,re.compile(r'^(?:第[一二三四五六七八九十百千万零〇两\d]+(?:篇|编|部分)|释\s*义|目\s*录|绪\s*言|正\s*文)$')),
    (1,re.compile(r'^第[一二三四五六七八九十百千万零〇两\d]+章(?:\s|$|[^，。；]{0,60}$)')),
    (2,re.compile(r'^第[一二三四五六七八九十百千万零〇两\d]+节(?:\s|$|[^，。；]{0,60}$)')),
    (2,re.compile(r'^[一二三四五六七八九十百]+、[^。；]{1,100}$')),
    (3,re.compile(r'^（[一二三四五六七八九十百]+）[^。；]{1,100}$')),
    (4,re.compile(r'^(?:\d{1,3}[.、]|\([0-9]{1,3}\))[^。；]{1,100}$')),
]


def paths(root,board,code):
    base=Path(root)/'data/client_announcements'/board/code
    return base,base/'catalog.json',base/'announcement_history.sqlite3'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def heading(text):
    value=re.sub(r'\s+',' ',text).strip()
    for level,pattern in HEADING_RULES:
        if pattern.match(value):return level,value[:300]
    return None


def document_start(text):
    value=re.sub(r'\s+','',text)
    return len(value)<=300 and bool(re.search(r'(?:招股(?:意向)?说明书|法律意见书|补充法律意见|年度报告|半年度报告)(?:（.*?）)?$',value))


def units(document):
    order=0
    for page in document.get('pages',[]):
        blocks=page.get('blocks')
        if not blocks:
            blocks=[{'type':'paragraph','anchor':f"page:{page['page']}:line:{n}",'text':line.strip()}
                    for n,line in enumerate(page.get('text','').splitlines(),1) if line.strip()]
        for block in blocks:
            block_type=block.get('type','paragraph')
            if block_type=='table_candidate':text='\n'.join('\t'.join(str(c) for c in row) for row in block.get('rows',[]))
            else:text=str(block.get('text','')).strip()
            if not text:continue
            order+=1
            yield {'page':int(page.get('page') or 1),'ordinal':order,'unit_type':block_type,
                   'anchor':block.get('anchor') or f"page:{page.get('page',1)}:unit:{order}",'text':text}


def connect(path,readonly=False):
    uri='file:'+str(path)+'?mode=ro' if readonly else str(path)
    conn=sqlite3.connect(uri,uri=readonly)
    conn.row_factory=sqlite3.Row
    return conn


def create(conn):
    conn.executescript('''
      PRAGMA journal_mode=OFF;
      PRAGMA synchronous=OFF;
      CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE announcements(id TEXT PRIMARY KEY,title TEXT NOT NULL,published_at TEXT,
        announcement_number TEXT,kind TEXT,page_count INTEGER NOT NULL,sha256 TEXT NOT NULL,
        document_sha256 TEXT NOT NULL,original_path TEXT NOT NULL,document_path TEXT NOT NULL,
        needs_review INTEGER NOT NULL DEFAULT 0,relation TEXT,meeting_json TEXT,related_ids_json TEXT);
      CREATE INDEX idx_announcements_date ON announcements(published_at DESC);
      CREATE INDEX idx_announcements_number ON announcements(announcement_number);
      CREATE INDEX idx_announcements_kind ON announcements(kind);
      CREATE TABLE classifications(announcement_id TEXT PRIMARY KEY,result_json TEXT NOT NULL);
      CREATE TABLE sections(id TEXT PRIMARY KEY,announcement_id TEXT NOT NULL,parent_id TEXT,
        level INTEGER NOT NULL,title TEXT NOT NULL,path TEXT NOT NULL,start_page INTEGER NOT NULL,
        end_page INTEGER NOT NULL,start_ordinal INTEGER NOT NULL,end_ordinal INTEGER NOT NULL);
      CREATE INDEX idx_sections_announcement_page ON sections(announcement_id,start_page,end_page);
      CREATE TABLE document_pages(id TEXT PRIMARY KEY,announcement_id TEXT NOT NULL,page INTEGER NOT NULL,
        method TEXT,text_length INTEGER NOT NULL,text_sha256 TEXT NOT NULL,needs_review INTEGER NOT NULL DEFAULT 0,
        UNIQUE(announcement_id,page));
      CREATE INDEX idx_document_pages_announcement ON document_pages(announcement_id,page);
      CREATE TABLE units(id TEXT PRIMARY KEY,announcement_id TEXT NOT NULL,page INTEGER NOT NULL,
        ordinal INTEGER NOT NULL,unit_type TEXT NOT NULL,anchor TEXT NOT NULL,section_id TEXT,
        section_path TEXT NOT NULL,text TEXT NOT NULL,text_sha256 TEXT NOT NULL);
      CREATE INDEX idx_units_announcement_page ON units(announcement_id,page,ordinal);
      CREATE INDEX idx_units_type ON units(unit_type);
      CREATE TABLE relations(source_id TEXT NOT NULL,target_id TEXT NOT NULL,relation TEXT NOT NULL,
        PRIMARY KEY(source_id,target_id,relation));
      CREATE VIRTUAL TABLE unit_fts USING fts5(unit_id UNINDEXED,text,tokenize='trigram');
      CREATE TABLE assets(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL);
    ''')


def sync(root,board,code):
    base,catalog_path,index_path=paths(root,board,code)
    catalog=json.loads(catalog_path.read_text())
    index_path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.announcement-index-',suffix='.sqlite3',dir=index_path.parent);os.close(fd)
    try:
        conn=connect(name);create(conn);announcement_rows=[];page_rows=[];section_rows=[];unit_rows=[];fts_rows=[];relation_rows=[];asset_rows=[];integrity=[];secondary_errors=[];document_stats={};classifications=[]
        active=[r for r in catalog.get('items',[]) if not r.get('deleted_at')]
        for row in active:
            if row.get('deleted_at'):continue
            classify_kind=announcement_tags.document_kind
            announcement_rows.append((row['id'],row['title'],row.get('published_at'),row.get('announcement_number'),classify_kind(row['title']),int(row.get('page_count') or 0),row['sha256'],row['document_sha256'],row['original_path'],row['document_path'],int(bool(row.get('needs_review'))),row.get('relation'),json.dumps(row.get('meeting'),ensure_ascii=False),json.dumps(row.get('related_ids',[]),ensure_ascii=False)))
            for target in row.get('related_ids',[]):relation_rows.append((row['id'],target,row.get('relation') or 'related'))
            valid=True
            for key,hash_key in (('original_path','sha256'),('document_path','document_sha256')):
                path=Path(root)/row[key]
                try:
                    stat=path.stat();actual=digest(path)
                    asset_rows.append((row[key],row[hash_key],stat.st_size,stat.st_mtime_ns))
                    if actual!=row[hash_key]:valid=False
                except OSError:valid=False
            if not valid:integrity.append(row['id']);continue
            document=json.loads((Path(root)/row['document_path']).read_text());stack=[];sections=[]
            classifications.append((row['id'],json.dumps(announcement_tags.classify(row,document),ensure_ascii=False)))
            if len(document.get('pages',[]))!=int(row.get('page_count') or 0):secondary_errors.append({'id':row['id'],'reason':'page_count_mismatch'})
            for page in document.get('pages',[]):
                text=str(page.get('text',''));pid=row['id']+f":page:{page.get('page',1)}"
                page_rows.append((pid,row['id'],int(page.get('page') or 1),page.get('method'),len(text),hashlib.sha256(text.encode()).hexdigest(),int(bool(page.get('ocr') or page.get('image_review_required') or page.get('table_review_required')))))
            start_units=len(unit_rows)
            for unit in units(document):
                if document_start(unit['text']):stack=[]
                found=heading(unit['text'])
                if found:
                    level,title=found
                    while stack and stack[-1]['level']>=level:stack.pop()
                    sid=row['id']+f":section:{unit['ordinal']}";section={'id':sid,'parent_id':stack[-1]['id'] if stack else None,'level':level,'title':title,'path':' / '.join([s['title'] for s in stack]+[title]),'start_page':unit['page'],'end_page':unit['page'],'start_ordinal':unit['ordinal'],'end_ordinal':unit['ordinal']};sections.append(section);stack.append(section)
                for open_section in stack:open_section.update(end_page=unit['page'],end_ordinal=unit['ordinal'])
                current=stack[-1] if stack else None;uid=row['id']+f":unit:{unit['ordinal']}";section_path=current['path'] if current else ''
                unit_rows.append((uid,row['id'],unit['page'],unit['ordinal'],unit['unit_type'],unit['anchor'],current['id'] if current else None,section_path,unit['text'],hashlib.sha256(unit['text'].encode()).hexdigest()))
                fts_rows.append((uid,unit['text']))
            section_rows.extend((s['id'],row['id'],s['parent_id'],s['level'],s['title'],s['path'],s['start_page'],s['end_page'],s['start_ordinal'],s['end_ordinal']) for s in sections)
            document_stats[row['id']]={'pages':len(document.get('pages',[])),'units':len(unit_rows)-start_units,'sections':len(sections),'large':int(row.get('page_count') or 0)>=LARGE_PAGES or bool(LARGE_TITLE.search(row['title']))}
            if document_stats[row['id']]['large'] and (not document_stats[row['id']]['pages'] or not document_stats[row['id']]['units']):secondary_errors.append({'id':row['id'],'reason':'large_document_secondary_index_missing'})
        conn.executemany('INSERT INTO announcements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',announcement_rows)
        conn.executemany('INSERT INTO classifications VALUES (?,?)',classifications)
        conn.executemany('INSERT INTO document_pages VALUES (?,?,?,?,?,?,?)',page_rows)
        conn.executemany('INSERT INTO sections VALUES (?,?,?,?,?,?,?,?,?,?)',section_rows)
        conn.executemany('INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?)',unit_rows)
        conn.executemany('INSERT INTO unit_fts(unit_id,text) VALUES (?,?)',fts_rows)
        conn.executemany('INSERT OR IGNORE INTO relations VALUES (?,?,?)',relation_rows)
        conn.executemany('INSERT OR REPLACE INTO assets VALUES (?,?,?,?)',asset_rows)
        large=[v for v in document_stats.values() if v['large']]
        metadata={'schema':SCHEMA,'classification_version':announcement_tags.VERSION,'catalog_sha256':digest(catalog_path),'generated_at':datetime.now(timezone.utc).isoformat(),'announcements':len(announcement_rows),'sections':len(section_rows),'units':len(unit_rows),'pages':len(page_rows),'integrity_errors':integrity,'secondary_errors':secondary_errors,
            'coverage':{'active_catalog_items':len(active),'primary_indexed':len(announcement_rows),'page_records':len(page_rows),'expected_pages':sum(int(r.get('page_count') or 0) for r in active),'secondary_indexed_documents':len(document_stats),'large_documents':len(large),'large_documents_indexed':sum(v['pages']>0 and v['units']>0 for v in large)},
            'locator_contract':{'page':'source_page','anchor':'extracted_block','section_path':'heuristic_heading_path','unit_text':'source_extract_not_model_summary'}}
        if integrity or secondary_errors or metadata['coverage']['primary_indexed']!=metadata['coverage']['active_catalog_items'] or metadata['coverage']['page_records']!=metadata['coverage']['expected_pages'] or metadata['coverage']['large_documents_indexed']!=metadata['coverage']['large_documents']:
            raise ValueError('announcement index coverage or integrity check failed')
        conn.executemany('INSERT INTO meta VALUES (?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in metadata.items()]);conn.commit();conn.execute('PRAGMA optimize');conn.close();os.replace(name,index_path);return metadata
    finally:
        if os.path.exists(name):os.unlink(name)


def status(root,board,code):
    base,catalog,index=paths(root,board,code)
    if not index.exists() or not catalog.exists():return {'status':'missing'}
    try:
        conn=connect(index,True);meta={r['key']:json.loads(r['value']) for r in conn.execute('SELECT key,value FROM meta')}
        if meta.get('schema')!=SCHEMA or meta.get('classification_version')!=announcement_tags.VERSION or meta.get('catalog_sha256')!=digest(catalog):return {'status':'stale',**meta}
        changed=[]
        for row in conn.execute('SELECT path,size,mtime_ns,sha256 FROM assets'):
            try:s=(Path(root)/row['path']).stat()
            except OSError:changed.append(row['path']);continue
            if s.st_size!=row['size']:
                changed.append(row['path']);continue
            if s.st_mtime_ns!=row['mtime_ns'] and digest(Path(root)/row['path'])!=row['sha256']:
                changed.append(row['path'])
        return {'status':'current' if not changed else 'stale','changed_assets':changed,**meta}
    except (sqlite3.Error,OSError,ValueError):return {'status':'invalid'}
    finally:
        try:conn.close()
        except Exception:pass


def search(root,board,code,query='',offset=0,limit=20):
    _,_,index=paths(root,board,code);state=status(root,board,code)
    if state['status']!='current':return None
    conn=connect(index,True)
    try:
        if not query.strip():
            total=conn.execute('SELECT COUNT(*) FROM announcements').fetchone()[0]
            items=[dict(r) for r in conn.execute('SELECT * FROM announcements ORDER BY published_at DESC,title,id LIMIT ? OFFSET ?',(limit,offset))]
            return {'items':items,'passages':[],'total':total,'offset':offset,'limit':limit,'index':state}
        q=query.strip();like='%'+q.replace('%','\\%').replace('_','\\_')+'%'
        title_sql="SELECT id FROM announcements WHERE title LIKE ? ESCAPE '\\' OR announcement_number LIKE ? ESCAPE '\\'"
        if len(re.sub(r'\s','',q))>=3:
            phrase='"'+q.replace('"','""')+'"'
            body_sql='SELECT DISTINCT u.announcement_id AS id FROM unit_fts JOIN units u ON u.id=unit_fts.unit_id WHERE unit_fts MATCH ?'
            body_value=phrase
            preview_sql='''SELECT u.announcement_id,a.title,a.published_at,u.page,u.ordinal,u.unit_type,u.anchor,u.section_path,
                snippet(unit_fts,1,'【','】','…',28) text_preview,bm25(unit_fts) score
                FROM unit_fts JOIN units u ON u.id=unit_fts.unit_id JOIN announcements a ON a.id=u.announcement_id
                WHERE unit_fts MATCH ? AND u.announcement_id=? ORDER BY u.page,u.ordinal LIMIT 1'''
        else:
            body_sql="SELECT DISTINCT announcement_id AS id FROM units WHERE text LIKE ? ESCAPE '\\'"
            body_value=like
            preview_sql='''SELECT u.announcement_id,a.title,a.published_at,u.page,u.ordinal,u.unit_type,u.anchor,u.section_path,
                substr(u.text,1,500) text_preview,0 score FROM units u JOIN announcements a ON a.id=u.announcement_id
                WHERE u.text LIKE ? ESCAPE '\\' AND u.announcement_id=? ORDER BY u.page,u.ordinal LIMIT 1'''
        matched_sql=title_sql+' UNION '+body_sql
        params=(like,like,body_value)
        fts_failed=False
        try:
            total=conn.execute('SELECT COUNT(*) FROM ('+matched_sql+') matched',params).fetchone()[0]
            page=[dict(r) for r in conn.execute('WITH matched AS ('+matched_sql+') SELECT a.* FROM announcements a JOIN matched m ON m.id=a.id ORDER BY a.published_at DESC,a.title,a.id LIMIT ? OFFSET ?',params+(limit,offset))]
        except sqlite3.Error:
            fts_failed=True;matched_sql=title_sql;params=(like,like)
            total=conn.execute('SELECT COUNT(*) FROM ('+matched_sql+') matched',params).fetchone()[0]
            page=[dict(r) for r in conn.execute('WITH matched AS ('+matched_sql+') SELECT a.* FROM announcements a JOIN matched m ON m.id=a.id ORDER BY a.published_at DESC,a.title,a.id LIMIT ? OFFSET ?',params+(limit,offset))]
        passages=[]
        if not fts_failed:
            for row in page:
                preview=conn.execute(preview_sql,(body_value,row['id'])).fetchone()
                if preview is not None:passages.append(dict(preview))
        return {'items':page,'passages':passages,'total':total,'offset':offset,'limit':limit,'index':state}
    finally:conn.close()
