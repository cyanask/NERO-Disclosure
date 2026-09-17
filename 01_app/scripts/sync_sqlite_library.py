#!/usr/bin/env python3
"""
Build and maintain SQLite local directory index and classification database for
NERO Disclosure laws, reference cases, blacklist cases, profiles, instruments, and rules.
DB Path: data/public/boards/<board>/disclosure_library.sqlite3
"""
import hashlib
import json
import sqlite3
import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
KNOWLEDGE = workspace_paths.knowledge_of(ROOT)
def get_connection(board):
    from backend.domain import Seeds
    path = Seeds(KNOWLEDGE).for_board(board).public_dir/'disclosure_library.sqlite3'
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    with conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            instrument_id TEXT,
            title TEXT NOT NULL,
            article TEXT,
            text TEXT,
            market TEXT NOT NULL,
            url TEXT,
            source_kind TEXT,
            sha256 TEXT,
            raw_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sources_market ON sources(market);
        CREATE INDEX IF NOT EXISTS idx_sources_inst ON sources(instrument_id);

        CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY,
            stock_code TEXT,
            company TEXT NOT NULL,
            kind TEXT NOT NULL,
            subtype TEXT,
            published_at TEXT,
            title TEXT NOT NULL,
            market TEXT NOT NULL,
            verification_status TEXT,
            page_count INTEGER,
            document_path TEXT,
            sha256 TEXT,
            admitted INTEGER NOT NULL DEFAULT 0,
            case_admission_status TEXT,
            raw_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cases_market ON cases(market);
        CREATE INDEX IF NOT EXISTS idx_cases_company ON cases(company);
        CREATE INDEX IF NOT EXISTS idx_cases_kind ON cases(kind);

        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            official_format_number TEXT,
            market TEXT NOT NULL,
            applicability TEXT,
            layout_profile_id TEXT,
            sections_count INTEGER,
            raw_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_profiles_market ON profiles(market);
        CREATE INDEX IF NOT EXISTS idx_profiles_kind ON profiles(kind);

        CREATE TABLE IF NOT EXISTS instruments (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            market TEXT NOT NULL,
            effective_from TEXT,
            as_of TEXT,
            url TEXT,
            raw_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_instruments_market ON instruments(market);

        CREATE TABLE IF NOT EXISTS meta_info (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE law_fts USING fts5(source_id UNINDEXED,title,article,text,context,tokenize='trigram');
        CREATE TABLE case_pages(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,page INTEGER NOT NULL,method TEXT,
            text_length INTEGER NOT NULL,text_sha256 TEXT NOT NULL,needs_review INTEGER NOT NULL DEFAULT 0,
            UNIQUE(case_id,page));
        CREATE INDEX idx_case_pages_case ON case_pages(case_id,page);
        CREATE TABLE case_sections(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,parent_id TEXT,level INTEGER NOT NULL,
            title TEXT NOT NULL,path TEXT NOT NULL,start_page INTEGER NOT NULL,end_page INTEGER NOT NULL,
            start_ordinal INTEGER NOT NULL,end_ordinal INTEGER NOT NULL);
        CREATE INDEX idx_case_sections_page ON case_sections(case_id,start_page,end_page);
        CREATE TABLE case_units(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,page INTEGER NOT NULL,ordinal INTEGER NOT NULL,
            unit_type TEXT NOT NULL,anchor TEXT NOT NULL,section_id TEXT,section_path TEXT NOT NULL,text TEXT NOT NULL,
            text_sha256 TEXT NOT NULL);
        CREATE INDEX idx_case_units_page ON case_units(case_id,page,ordinal);
        CREATE INDEX idx_case_units_type ON case_units(unit_type);
        CREATE VIRTUAL TABLE case_fts USING fts5(unit_id UNINDEXED,text,tokenize='trigram');
        CREATE TABLE blacklist_cases(
            id TEXT PRIMARY KEY,stock_code TEXT,company TEXT NOT NULL,title TEXT NOT NULL,market TEXT NOT NULL,
            decision_date TEXT,decision_number TEXT,authority TEXT,disposition_type TEXT,announcement_kinds TEXT,
            violation_types TEXT,admitted INTEGER NOT NULL DEFAULT 0,evidence_complete INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL);
        CREATE INDEX idx_blacklist_company ON blacklist_cases(company);
        CREATE INDEX idx_blacklist_decision_date ON blacklist_cases(decision_date);
        CREATE INDEX idx_blacklist_disposition ON blacklist_cases(disposition_type);
        CREATE TABLE blacklist_units(id TEXT PRIMARY KEY,blacklist_id TEXT NOT NULL,document_id TEXT NOT NULL,
            document_role TEXT NOT NULL,page INTEGER NOT NULL,ordinal INTEGER NOT NULL,unit_type TEXT NOT NULL,
            anchor TEXT NOT NULL,section_path TEXT NOT NULL,text TEXT NOT NULL,text_sha256 TEXT NOT NULL);
        CREATE INDEX idx_blacklist_units_case ON blacklist_units(blacklist_id,document_id,page,ordinal);
        CREATE VIRTUAL TABLE blacklist_fts USING fts5(unit_id UNINDEXED,text,tokenize='trigram');
        CREATE TABLE index_assets(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL);
        ''')

def sync_library_db(root=None,board=None):
    base = Path(root) if root is not None else KNOWLEDGE
    from backend.domain import Seeds
    P = Seeds(base).for_board(board).public_dir
    DB_PATH = P / "disclosure_library.sqlite3"
    fd, name = tempfile.mkstemp(prefix=".library-index-", suffix=".sqlite3", dir=P)
    os.close(fd)
    try:
        counts=_build_index(base,P,Path(name),board)
        os.replace(name, DB_PATH)
        return counts
    finally:
        if os.path.exists(name): os.unlink(name)


class IndexRows:
    """Rows accumulated for one rebuild; keeps the loader and writer signatures small."""

    def __init__(self):
        self.law_fts=[]
        self.case_pages=[];self.case_sections=[];self.case_units=[];self.case_fts=[]
        self.blacklist_units=[];self.blacklist_fts=[]
        self.assets=[];self.errors=[];self.warnings=[]
        self.case_pages_seen=0;self.blacklist_pages_seen=0


def load_catalogs(P):
    catalog = json.loads((P / 'catalog.json').read_text('utf-8'))
    profiles = json.loads((P / 'profiles.json').read_text('utf-8'))
    instruments = json.loads((P / 'instruments.json').read_text('utf-8')) if (P / 'instruments.json').is_file() else []
    return catalog, profiles, instruments


def insert_sources(conn,board,catalog,rows):
    # Insert sources
    for s in catalog.get('sources', []):
        m = board
        conn.execute('''
            INSERT INTO sources (id, instrument_id, title, article, text, market, url, source_kind, sha256, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            s['id'],
            s.get('instrument_id'),
            s.get('title', ''),
            s.get('article'),
            s.get('text', ''),
            m,
            s.get('url'),
            s.get('source_kind'),
            s.get('sha256'),
            json.dumps(s, ensure_ascii=False)
        ))
        context=json.dumps({'instrument_id':s.get('instrument_id'),'effective_from':s.get('effective_from'),
            'effective_to':s.get('effective_to'),'as_of':s.get('as_of'),'layers':s.get('layers'),
            'event_kinds':s.get('event_kinds'),'board_applicability':s.get('board_applicability')},ensure_ascii=False)
        rows.law_fts.append((s['id'],s.get('title',''),s.get('article',''),s.get('text',''),context))


def insert_cases(conn,root,board,catalog,rows):
    # Insert cases
    for c in catalog.get('cases', []):
        m = board
        conn.execute('''
            INSERT INTO cases (id, stock_code, company, kind, subtype, published_at, title, market, verification_status, page_count, document_path, sha256, admitted, case_admission_status, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            c['id'],
            c.get('stock_code') or c.get('security_code'),
            c.get('company') or c.get('company_name', ''),
            c.get('kind', ''),
            c.get('subtype'),
            c.get('published_at'),
            c.get('title', ''),
            m,
            c.get('verification_status'),
            c.get('page_count', 1),
            c.get('document_path'),
            c.get('sha256'),
            int(_admitted(c,board)),
            c.get('case_admission_status'),
            json.dumps(c, ensure_ascii=False)
        ))
        document_path=c.get('document_path')
        if not document_path:
            issue={'id':c['id'],'reason':'document_path_missing'}
            (rows.errors if _admitted(c,board) else rows.warnings).append(issue);continue
        document_file=Path(root)/document_path
        try:
            raw=document_file.read_bytes();actual=hashlib.sha256(raw).hexdigest()
            if c.get('document_sha256') and c['document_sha256']!=actual:raise ValueError('document_sha256_mismatch')
            stat=document_file.stat();rows.assets.append((document_path,actual,stat.st_size,stat.st_mtime_ns));document=json.loads(raw)
        except (OSError,ValueError,json.JSONDecodeError) as exc:rows.errors.append({'id':c['id'],'reason':str(exc)});continue
        original_path=c.get('original_path')
        if original_path:
            try:
                source=Path(root)/original_path;source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
                if c.get('sha256') and c['sha256']!=source_hash:raise ValueError('original_sha256_mismatch')
                stat=source.stat();rows.assets.append((original_path,source_hash,stat.st_size,stat.st_mtime_ns))
            except (OSError,ValueError) as exc:rows.errors.append({'id':c['id'],'reason':str(exc)});continue
        pages=document.get('pages',[]);rows.case_pages_seen+=len(pages)
        if len(pages)!=int(c.get('page_count') or len(pages)):
            issue={'id':c['id'],'reason':'page_count_mismatch','declared':c.get('page_count'),'actual':len(pages)}
            (rows.errors if _admitted(c,board) else rows.warnings).append(issue)
        from backend.announcement_index import units,heading,document_start
        stack=[];sections=[];before=len(rows.case_units)
        for page in pages:
            text=str(page.get('text',''));pid=c['id']+f":page:{page.get('page',1)}"
            rows.case_pages.append((pid,c['id'],int(page.get('page') or 1),page.get('method'),len(text),hashlib.sha256(text.encode()).hexdigest(),int(bool(page.get('ocr') or page.get('image_review_required') or page.get('table_review_required')))))
        for unit in units(document):
            if document_start(unit['text']):stack=[]
            found=heading(unit['text'])
            if found:
                level,title=found
                while stack and stack[-1]['level']>=level:stack.pop()
                sid=c['id']+f":section:{unit['ordinal']}";section={'id':sid,'parent_id':stack[-1]['id'] if stack else None,'level':level,'title':title,'path':' / '.join([s['title'] for s in stack]+[title]),'start_page':unit['page'],'end_page':unit['page'],'start_ordinal':unit['ordinal'],'end_ordinal':unit['ordinal']};sections.append(section);stack.append(section)
            for open_section in stack:open_section.update(end_page=unit['page'],end_ordinal=unit['ordinal'])
            current=stack[-1] if stack else None;uid=c['id']+f":unit:{unit['ordinal']}";section_path=current['path'] if current else ''
            rows.case_units.append((uid,c['id'],unit['page'],unit['ordinal'],unit['unit_type'],unit['anchor'],current['id'] if current else None,section_path,unit['text'],hashlib.sha256(unit['text'].encode()).hexdigest()));rows.case_fts.append((uid,unit['text']))
        rows.case_sections.extend((s['id'],c['id'],s['parent_id'],s['level'],s['title'],s['path'],s['start_page'],s['end_page'],s['start_ordinal'],s['end_ordinal']) for s in sections)
        if pages and len(rows.case_units)==before:
            issue={'id':c['id'],'reason':'case_units_missing'}
            (rows.errors if _admitted(c,board) else rows.warnings).append(issue)


def insert_blacklist(conn,root,board,catalog,rows):
    # One blacklist row is one misconduct matter; every linked official
    # document remains separately locatable inside the shared index.
    from backend.announcement_index import units,heading,document_start
    for case in catalog.get('blacklist_cases',[]):
        admitted=_blacklist_admitted(case,board)
        conn.execute('''INSERT INTO blacklist_cases
            (id,stock_code,company,title,market,decision_date,decision_number,authority,disposition_type,
             announcement_kinds,violation_types,admitted,evidence_complete,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            case['id'],case.get('stock_code'),case.get('company',''),case.get('title',''),board,
            case.get('decision_date'),case.get('decision_number'),case.get('authority'),case.get('disposition_type'),
            json.dumps(case.get('announcement_kinds',[]),ensure_ascii=False),json.dumps(case.get('violation_types',[]),ensure_ascii=False),
            int(admitted),int(bool(case.get('evidence_complete'))),json.dumps(case,ensure_ascii=False)))
        for evidence in case.get('evidence_documents',[]):
            document_path=evidence.get('document_path');original_path=evidence.get('original_path')
            try:
                raw=(Path(root)/document_path).read_bytes();actual=hashlib.sha256(raw).hexdigest()
                if evidence.get('document_sha256') and evidence['document_sha256']!=actual:raise ValueError('document_sha256_mismatch')
                stat=(Path(root)/document_path).stat();rows.assets.append((document_path,actual,stat.st_size,stat.st_mtime_ns));document=json.loads(raw)
                source=Path(root)/original_path;source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
                if evidence.get('sha256') and evidence['sha256']!=source_hash:raise ValueError('original_sha256_mismatch')
                stat=source.stat();rows.assets.append((original_path,source_hash,stat.st_size,stat.st_mtime_ns))
            except (OSError,ValueError,TypeError,json.JSONDecodeError) as exc:
                (rows.errors if admitted else rows.warnings).append({'id':case['id'],'document_id':evidence.get('id'),'reason':str(exc)});continue
            pages=document.get('pages',[]);rows.blacklist_pages_seen+=len(pages);stack=[]
            for unit in units(document):
                if document_start(unit['text']):stack=[]
                found=heading(unit['text'])
                if found:
                    level,title=found
                    while stack and stack[-1][0]>=level:stack.pop()
                    stack.append((level,title))
                uid=f"{case['id']}:document:{evidence['id']}:unit:{unit['ordinal']}"
                path=' / '.join(x[1] for x in stack)
                rows.blacklist_units.append((uid,case['id'],evidence['id'],evidence['role'],unit['page'],unit['ordinal'],unit['unit_type'],unit['anchor'],path,unit['text'],hashlib.sha256(unit['text'].encode()).hexdigest()))
                rows.blacklist_fts.append((uid,unit['text']))


def insert_reference_rows(conn,board,profiles,instruments):
    # Insert profiles
    for pr in profiles:
        m = board
        conn.execute('''
            INSERT INTO profiles (id, kind, title, official_format_number, market, applicability, layout_profile_id, sections_count, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            pr['id'],
            pr.get('kind', ''),
            pr.get('title', ''),
            pr.get('official_format_number'),
            m,
            pr.get('applicability'),
            pr.get('layout_profile_id'),
            len(pr.get('sections', [])),
            json.dumps(pr, ensure_ascii=False)
        ))

    # Insert instruments
    for ins in instruments:
        m = board
        conn.execute('''
            INSERT INTO instruments (id, title, market, effective_from, as_of, url, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            ins['id'],
            ins.get('title', ''),
            m,
            ins.get('effective_from'),
            ins.get('as_of'),
            ins.get('url'),
            json.dumps(ins, ensure_ascii=False)
        ))


def write_index(conn,P,board,catalog,rows):
    conn.execute('INSERT OR REPLACE INTO meta_info (key, value) VALUES (?, ?)', ('version', json.dumps('board-libraries-v3')))
    conn.execute('INSERT OR REPLACE INTO meta_info (key, value) VALUES (?, ?)', ('board', json.dumps(board)))
    conn.execute('INSERT OR REPLACE INTO meta_info (key, value) VALUES (?, ?)', ('updated_at', json.dumps(str(Path(P / "catalog.json").stat().st_mtime))))
    conn.executemany('INSERT INTO law_fts(source_id,title,article,text,context) VALUES (?,?,?,?,?)',rows.law_fts)
    conn.executemany('INSERT INTO case_pages VALUES (?,?,?,?,?,?,?)',rows.case_pages)
    conn.executemany('INSERT INTO case_sections VALUES (?,?,?,?,?,?,?,?,?,?)',rows.case_sections)
    conn.executemany('INSERT INTO case_units VALUES (?,?,?,?,?,?,?,?,?,?)',rows.case_units)
    conn.executemany('INSERT INTO case_fts(unit_id,text) VALUES (?,?)',rows.case_fts)
    conn.executemany('INSERT INTO blacklist_units VALUES (?,?,?,?,?,?,?,?,?,?,?)',rows.blacklist_units)
    conn.executemany('INSERT INTO blacklist_fts(unit_id,text) VALUES (?,?)',rows.blacklist_fts)
    conn.executemany('INSERT OR REPLACE INTO index_assets VALUES (?,?,?,?)',rows.assets)
    coverage={'law_rows':len(catalog.get('sources',[])),'law_fts_rows':len(rows.law_fts),'case_rows':len(catalog.get('cases',[])),
        'case_pages':len(rows.case_pages),'expected_case_pages':rows.case_pages_seen,'declared_case_pages':sum(int(c.get('page_count') or 0) for c in catalog.get('cases',[])),
        'case_sections':len(rows.case_sections),'case_units':len(rows.case_units),'admitted_cases':sum(_admitted(c,board) for c in catalog.get('cases',[])),
        'candidate_cases':sum(not _admitted(c,board) for c in catalog.get('cases',[])),
        'blacklist_rows':len(catalog.get('blacklist_cases',[])),'blacklist_documents':sum(len(c.get('evidence_documents',[])) for c in catalog.get('blacklist_cases',[])),
        'blacklist_pages':rows.blacklist_pages_seen,'blacklist_units':len(rows.blacklist_units),
        'admitted_blacklist_cases':sum(_blacklist_admitted(c,board) for c in catalog.get('blacklist_cases',[])),
        'candidate_blacklist_cases':sum(not _blacklist_admitted(c,board) for c in catalog.get('blacklist_cases',[]))}
    if rows.errors or coverage['law_rows']!=coverage['law_fts_rows'] or coverage['case_pages']!=coverage['expected_case_pages']:raise ValueError('public library FTS coverage failed: '+json.dumps(rows.errors[:10],ensure_ascii=False))
    metadata={'schema':'nero.public.library.index.v3','catalog_sha256':hashlib.sha256((P/'catalog.json').read_bytes()).hexdigest(),
        'profiles_sha256':hashlib.sha256((P/'profiles.json').read_bytes()).hexdigest(),
        'instruments_sha256':hashlib.sha256((P/'instruments.json').read_bytes()).hexdigest() if (P/'instruments.json').exists() else None,
        'coverage':coverage,'warnings':rows.warnings,'locator_contract':{'law_text':'canonical_source_row','case_page':'source_page','case_section_path':'heuristic_heading_path','case_unit':'source_extract','blacklist_unit':'evidence_document_page_and_anchor'}}
    for key,value in metadata.items():conn.execute('INSERT OR REPLACE INTO meta_info(key,value) VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
    return coverage


def _build_index(root,P,DB_PATH,board):
    conn = sqlite3.connect(str(DB_PATH))
    try:
        # Rebuilds are atomic disposable projections. Keep SQLite's temporary
        # sort/FTS state in memory so a nearly full portable workspace does not
        # need several copies of the index on disk.
        conn.execute('PRAGMA journal_mode=OFF')
        conn.execute('PRAGMA synchronous=OFF')
        conn.execute('PRAGMA temp_store=MEMORY')
        init_db(conn)

        catalog, profiles, instruments = load_catalogs(P)
        rows = IndexRows()
        with conn:
            for table in ('sources','cases','blacklist_cases','profiles','instruments'):
                conn.execute(f'DELETE FROM {table}')
            insert_sources(conn,board,catalog,rows)
            insert_cases(conn,root,board,catalog,rows)
            insert_blacklist(conn,root,board,catalog,rows)
            insert_reference_rows(conn,board,profiles,instruments)
            coverage = write_index(conn,P,board,catalog,rows)
        cur = conn.cursor()
        s_cnt = cur.execute('SELECT count(*) FROM sources').fetchone()[0]
        c_cnt = cur.execute('SELECT count(*) FROM cases').fetchone()[0]
        p_cnt = cur.execute('SELECT count(*) FROM profiles').fetchone()[0]
        i_cnt = cur.execute('SELECT count(*) FROM instruments').fetchone()[0]
        return {'sources':s_cnt,'cases':c_cnt,'profiles':p_cnt,'instruments':i_cnt,**coverage}
    finally:
        conn.close()


def _admitted(row,board):
    return (row.get('eligible_as_case_evidence') is True and row.get('verification_status')=='official_original_indexed'
            and bool(row.get('original_path')) and row.get('layer_at_publication')==board
            and (row.get('case_scope') or {}).get('verified_board_at_publication')==board)


def _blacklist_admitted(row,board):
    return (row.get('admission_status')=='admitted' and row.get('verification_status')=='official_decision_verified'
            and row.get('layer_at_misconduct')==board and (row.get('case_scope') or {}).get('verified_board_at_misconduct')==board
            and any(d.get('role')=='regulatory_decision' for d in row.get('evidence_documents',[])))


if __name__ == '__main__':
    import argparse
    sys.path.insert(0,str(ROOT))
    parser=argparse.ArgumentParser(description='按板块重建目录索引')
    parser.add_argument('--board',required=True,choices=['base','innovation','chinext'])
    print(json.dumps(sync_library_db(board=parser.parse_args().board),ensure_ascii=False))
