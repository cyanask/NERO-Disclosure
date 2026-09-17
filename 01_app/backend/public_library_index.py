"""Read-only access to the rebuildable law/case SQLite FTS projection."""
import hashlib,json,os,re,sqlite3
from pathlib import Path

SCHEMA='nero.public.library.index.v3'

def db_path(root,board):return Path(root)/'data/public/boards'/board/'disclosure_library.sqlite3'
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def connect(path):
    conn=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row;return conn

def status(root,board):
    path=db_path(root,board);base=path.parent
    if not path.exists():return {'status':'missing'}
    conn=None
    try:
        conn=connect(path);meta={r['key']:json.loads(r['value']) for r in conn.execute('SELECT key,value FROM meta_info')}
        current={'catalog_sha256':digest(base/'catalog.json'),'profiles_sha256':digest(base/'profiles.json'),
                 'instruments_sha256':digest(base/'instruments.json') if (base/'instruments.json').exists() else None}
        if meta.get('schema')!=SCHEMA or any(meta.get(k)!=v for k,v in current.items()):return {'status':'stale',**meta}
        changed=[]
        for row in conn.execute('SELECT path,size,mtime_ns,sha256 FROM index_assets'):
            try:s=(Path(root)/row['path']).stat()
            except OSError:changed.append(row['path']);continue
            if s.st_size!=row['size']:
                changed.append(row['path']);continue
            if s.st_mtime_ns!=row['mtime_ns'] and digest(Path(root)/row['path'])!=row['sha256']:
                changed.append(row['path'])
        return {'status':'current' if not changed else 'stale','changed_assets':changed,**meta}
    except (sqlite3.Error,OSError,ValueError,KeyError):return {'status':'invalid'}
    finally:
        if conn:conn.close()

def _phrase(value):return '"'+value.replace('"','""')+'"'

def search(root,board,collection,query,view='items',kind=None,passage_limit=30):
    state=status(root,board)
    if state['status']!='current' or collection not in ('laws','cases','blacklist_cases') or not query.strip():return None
    q=query.strip();short=len(re.sub(r'\s','',q))<3;conn=connect(db_path(root,board))
    try:
        if collection=='laws':
            if short:
                like='%'+q.replace('%','\\%').replace('_','\\_')+'%'
                rows=conn.execute("SELECT id source_id,substr(text,1,500) text_preview FROM sources WHERE title LIKE ? ESCAPE '\\' OR article LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\'",(like,like,like)).fetchall()
            else:rows=conn.execute("SELECT source_id,snippet(law_fts,3,'【','】','…',28) text_preview FROM law_fts WHERE law_fts MATCH ? ORDER BY bm25(law_fts)",(_phrase(q),)).fetchall()
            ids=list(dict.fromkeys(r['source_id'] for r in rows))
            return {'ids':ids,'passages':[dict(r) for r in rows[:passage_limit]],'index':state}
        admitted=1 if view!='candidates' else 0
        if collection=='blacklist_cases':
            parameters=[admitted];where='b.admitted=?'
            if kind:where+=' AND b.announcement_kinds LIKE ?';parameters.append('%"'+kind+'"%')
            if short:
                like='%'+q.replace('%','\\%').replace('_','\\_')+'%';parameters.append(like)
                hits=conn.execute(f'''SELECT u.blacklist_id case_id,b.title,b.company,b.decision_date published_at,u.page,u.ordinal,u.unit_type,u.anchor,u.section_path,substr(u.text,1,500) text_preview,0 score FROM blacklist_units u JOIN blacklist_cases b ON b.id=u.blacklist_id WHERE {where} AND u.text LIKE ? ESCAPE '\\' ORDER BY b.decision_date DESC,u.document_id,u.page,u.ordinal LIMIT {int(passage_limit)}''',parameters).fetchall()
                id_rows=conn.execute(f'''SELECT DISTINCT u.blacklist_id case_id FROM blacklist_units u JOIN blacklist_cases b ON b.id=u.blacklist_id WHERE {where} AND u.text LIKE ? ESCAPE '\\' ''',parameters).fetchall()
            else:
                parameters.append(_phrase(q))
                hits=conn.execute(f'''SELECT u.blacklist_id case_id,b.title,b.company,b.decision_date published_at,u.page,u.ordinal,u.unit_type,u.anchor,u.section_path,snippet(blacklist_fts,1,'【','】','…',28) text_preview,bm25(blacklist_fts) score FROM blacklist_fts JOIN blacklist_units u ON u.id=blacklist_fts.unit_id JOIN blacklist_cases b ON b.id=u.blacklist_id WHERE {where} AND blacklist_fts MATCH ? ORDER BY score LIMIT {int(passage_limit)}''',parameters).fetchall()
                id_rows=conn.execute(f'''SELECT DISTINCT u.blacklist_id case_id FROM blacklist_fts JOIN blacklist_units u ON u.id=blacklist_fts.unit_id JOIN blacklist_cases b ON b.id=u.blacklist_id WHERE {where} AND blacklist_fts MATCH ?''',parameters).fetchall()
            title_like='%'+q.replace('%','\\%').replace('_','\\_')+'%';title_params=[admitted];title_where='admitted=?'
            if kind:title_where+=' AND announcement_kinds LIKE ?';title_params.append('%"'+kind+'"%')
            title_params.extend([title_like,title_like,title_like])
            title_ids=[r[0] for r in conn.execute(f"SELECT id FROM blacklist_cases WHERE {title_where} AND (title LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\' OR decision_number LIKE ? ESCAPE '\\')",title_params)]
            return {'ids':list(dict.fromkeys([r['case_id'] for r in id_rows]+title_ids)),'passages':[dict(r) for r in hits],'index':state}
        parameters=[admitted];where='c.admitted=?'
        if kind:where+=' AND c.kind=?';parameters.append(kind)
        if short:
            like='%'+q.replace('%','\\%').replace('_','\\_')+'%';parameters.extend([like])
            hits=conn.execute(f'''SELECT u.case_id,c.title,c.company,c.published_at,u.page,u.ordinal,u.unit_type,u.anchor,u.section_path,substr(u.text,1,500) text_preview,0 score FROM case_units u JOIN cases c ON c.id=u.case_id WHERE {where} AND u.text LIKE ? ESCAPE '\\' ORDER BY c.published_at DESC,u.page,u.ordinal LIMIT {int(passage_limit)}''',parameters).fetchall()
            id_rows=conn.execute(f'''SELECT DISTINCT u.case_id FROM case_units u JOIN cases c ON c.id=u.case_id WHERE {where} AND u.text LIKE ? ESCAPE '\\' ''',parameters).fetchall()
        else:
            parameters.append(_phrase(q))
            hits=conn.execute(f'''SELECT u.case_id,c.title,c.company,c.published_at,u.page,u.ordinal,u.unit_type,u.anchor,u.section_path,snippet(case_fts,1,'【','】','…',28) text_preview,bm25(case_fts) score FROM case_fts JOIN case_units u ON u.id=case_fts.unit_id JOIN cases c ON c.id=u.case_id WHERE {where} AND case_fts MATCH ? ORDER BY score LIMIT {int(passage_limit)}''',parameters).fetchall()
            id_rows=conn.execute(f'''SELECT DISTINCT u.case_id FROM case_fts JOIN case_units u ON u.id=case_fts.unit_id JOIN cases c ON c.id=u.case_id WHERE {where} AND case_fts MATCH ?''',parameters).fetchall()
        title_like='%'+q.replace('%','\\%').replace('_','\\_')+'%';title_params=[admitted]
        title_where='admitted=?'
        if kind:title_where+=' AND kind=?';title_params.append(kind)
        title_params.extend([title_like,title_like]);title_ids=[r[0] for r in conn.execute(f"SELECT id FROM cases WHERE {title_where} AND (title LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\')",title_params)]
        return {'ids':list(dict.fromkeys([r['case_id'] for r in id_rows]+title_ids)),'passages':[dict(r) for r in hits],'index':state}
    finally:conn.close()
