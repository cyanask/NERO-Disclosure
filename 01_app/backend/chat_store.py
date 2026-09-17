"""Independent conversation journal; never rewrites disclosure snapshots."""
import json
import hashlib
import sqlite3
import time
import re
from contextlib import contextmanager
from uuid import uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException

LIVE = ('accepted', 'running', 'cancelling')


def question_title(text):
    """Immediate, deterministic first-question label; Pi may summarize it once."""
    text=re.sub(r'\s+',' ',str(text)).strip()
    text=re.sub(r'^(?:你好[，,！!。 ]*|请(?:你)?(?:帮我|帮忙)?(?:分析一下|分析|判断一下|判断|看一下)?[，, ]*)','',text).strip()
    text=re.split(r'[\n。！？!?]',text,maxsplit=1)[0].strip(' #*`，,：:；;')
    return (text[:27]+'…' if len(text)>28 else text) or '信披需求'


class ChatStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, board TEXT NOT NULL,
                event_id TEXT NOT NULL, title TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL, updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                event_id TEXT NOT NULL, status TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL,
                request_body TEXT NOT NULL, body TEXT NOT NULL);
              CREATE UNIQUE INDEX IF NOT EXISTS one_live_event ON runs(event_id)
                WHERE status IN ('accepted','running','cancelling');
              CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS journal_run ON journal(run_id,seq);
              CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id);
              CREATE INDEX IF NOT EXISTS runs_board ON runs(json_extract(body,'$.board'));
              CREATE INDEX IF NOT EXISTS sessions_board ON sessions(board,archived,updated DESC);
            ''')
            # Additive metadata only; existing messages, runs and business snapshots stay intact.
            c.execute('BEGIN IMMEDIATE')
            if 'company_code' not in {row['name'] for row in c.execute('PRAGMA table_info(sessions)')}:
                c.execute("ALTER TABLE sessions ADD COLUMN company_code TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.create_function('title_lower',1,lambda value:str(value or '').lower(),deterministic=True)
        c.create_function('question_title',1,question_title,deterministic=True)
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def session(self, sid):
        with self.connect() as c:
            row = c.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not row: raise HTTPException(404, '会话不存在')
        return self.display_session(dict(row))

    def display_session(self, row):
        # Existing unnamed conversations get a read-only fallback from their first question.
        if row['title']=='新会话':
            with self.connect() as c:
                first=c.execute("SELECT j.body FROM runs r JOIN journal j ON j.run_id=r.id WHERE r.session_id=? AND j.kind='user' ORDER BY r.rowid,j.seq LIMIT 1",(row['id'],)).fetchone()
            if first:row={**row,'title':question_title(json.loads(first[0]).get('text',''))}
        return row

    def sessions(self, board, query='', archived=False, limit=None, offset=0):
        self.pagination(limit,offset)
        # Use the same display title for search and pagination, including legacy
        # unnamed sessions. SQLite's built-in lower() only covers ASCII.
        sql='''WITH displayed AS (
          SELECT s.id,s.board,s.event_id,s.company_code,
            CASE WHEN s.title='新会话' THEN COALESCE((
              SELECT question_title(json_extract(j.body,'$.text')) FROM runs r
              JOIN journal j ON j.run_id=r.id
              WHERE r.session_id=s.id AND j.kind='user' ORDER BY r.rowid,j.seq LIMIT 1
            ),s.title) ELSE s.title END AS title,s.archived,s.created,s.updated
          FROM sessions s WHERE s.board=? AND s.archived=?)
          SELECT * FROM displayed WHERE instr(title_lower(title),title_lower(?))>0
          ORDER BY updated DESC,id DESC LIMIT ? OFFSET ?'''
        params=[board,int(archived),query,limit if limit is not None else -1,offset]
        with self.connect() as c:
            rows = c.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def pagination(limit,offset):
        if offset<0 or (limit is not None and limit<1):raise HTTPException(422,'分页参数无效')

    def summarize_title(self, rid, title):
        if not isinstance(title,str) or not title.strip():return False
        title=re.sub(r'\s+',' ',title).strip()[:28]
        if title=='新会话':return False
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT body FROM runs WHERE id=?',(rid,)).fetchone()
            run=json.loads(row[0])
            if not run.get('session_title_pending'):return False
            changed=c.execute('UPDATE sessions SET title=? WHERE id=? AND title=?',(title,run['session_id'],run['session_title_seed'])).rowcount
            run['session_title_pending']=False
            c.execute('UPDATE runs SET body=? WHERE id=?',(json.dumps(run,ensure_ascii=False),rid))
        return bool(changed)

    def create_session(self, board, event_id, title, request_id, company_code=''):
        company_code=company_code or ''
        sid, now = str(uuid5(NAMESPACE_URL,'disclosure-session:'+request_id)), time.time()
        event_id = event_id or 'conversation:'+sid
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
            if old:
                if (old['board'],old['event_id'],old['title'],old['company_code'])!=(board,event_id,title,company_code):raise HTTPException(409,'会话请求编号已用于其他内容')
                return dict(old)
            c.execute('INSERT INTO sessions(id,board,event_id,title,archived,created,updated,company_code) VALUES (?,?,?,?,0,?,?,?)', (sid, board, event_id, title, now, now,company_code))
        return self.session(sid)

    def bind_event(self, sid, event_id):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT event_id FROM sessions WHERE id=?',(sid,)).fetchone()
            if not old or not old[0].startswith('conversation:'):raise HTTPException(409,'会话已经绑定事项')
            c.execute('UPDATE sessions SET event_id=? WHERE id=?',(event_id,sid))
        return self.session(sid)

    def edit_session(self, sid, title=None, archived=None):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM runs WHERE session_id=? AND status IN ('accepted','running','cancelling')", (sid,)).fetchone():
                raise HTTPException(409, '请先停止当前执行，再修改会话')
            if title is not None:
                c.execute('UPDATE sessions SET title=?,updated=? WHERE id=?', (title,time.time(),sid))
                for row in c.execute('SELECT id,body FROM runs WHERE session_id=?',(sid,)).fetchall():
                    run=json.loads(row['body'])
                    if run.get('session_title_pending'):
                        run['session_title_pending']=False
                        c.execute('UPDATE runs SET body=? WHERE id=?',(json.dumps(run,ensure_ascii=False),row['id']))
            if archived is not None: c.execute('UPDATE sessions SET archived=?,updated=? WHERE id=?', (int(archived),time.time(),sid))
        return self.session(sid)

    def accept(self, session, payload, model, title_text=None):
        logical = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM runs WHERE request_id=?', (payload['request_id'],)).fetchone()
            if old:
                if old['request_body'] != logical: raise HTTPException(409, '请求编号已用于不同内容')
                return json.loads(old['body']), False
            if c.execute('SELECT archived FROM sessions WHERE id=?', (session['id'],)).fetchone()[0]:
                raise HTTPException(409, '会话已归档，请先恢复')
            run = {'id':str(uuid4()), 'session_id':session['id'], 'event_id':session['event_id'], 'board':session['board'],
                   'attachment_ids':payload.get('attachment_ids',[]),
                   'company_code':payload.get('company_code',''),
                   'status':'accepted', 'stage':payload['stage'], 'created':time.time(), 'updated':time.time(),
                   'model':model, 'skill_status':'pending' if payload['stage'] != 'chat' else 'not_applicable',
                   'reason':'已接收，等待 Pi 启动', 'request_id':payload['request_id']}
            stored_title=c.execute('SELECT title FROM sessions WHERE id=?',(session['id'],)).fetchone()[0]
            if stored_title=='新会话' and not c.execute('SELECT 1 FROM runs WHERE session_id=?',(session['id'],)).fetchone():
                seed=question_title(payload.get('text','') if title_text is None else title_text)
                run.update(session_title_seed=seed,session_title_pending=True)
                c.execute('UPDATE sessions SET title=? WHERE id=?',(seed,session['id']))
            try:
                c.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)', (run['id'],session['id'],session['event_id'],'accepted',payload['request_id'],logical,json.dumps(run,ensure_ascii=False)))
            except sqlite3.IntegrityError: raise HTTPException(409, '当前事项已有执行中的会话，请先停止或等待完成')
            c.execute('UPDATE sessions SET updated=? WHERE id=?', (time.time(),session['id']))
        return run, True

    def run(self, rid):
        with self.connect() as c: row=c.execute('SELECT body FROM runs WHERE id=?',(rid,)).fetchone()
        if not row: raise HTTPException(404, '执行不存在')
        return json.loads(row[0])

    def update(self, rid, **values):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT body FROM runs WHERE id=?',(rid,)).fetchone()
            run=json.loads(row[0]); run.update(values, updated=time.time())
            c.execute('UPDATE runs SET status=?,event_id=?,body=? WHERE id=?',(run['status'],run['event_id'],json.dumps(run,ensure_ascii=False),rid))
        return run

    def runs(self, sid=None, board=None, limit=None, offset=0):
        self.pagination(limit,offset)
        # Session and board both filter in SQL; ordering stays newest first.
        sql='SELECT body FROM runs';clauses=[];params=[]
        if sid is not None:clauses.append('session_id=?');params.append(sid)
        if board is not None:clauses.append("json_extract(body,'$.board')=?");params.append(board)
        if clauses:sql+=' WHERE '+' AND '.join(clauses)
        sql+=' ORDER BY rowid DESC'
        sql+=' LIMIT ? OFFSET ?';params += [limit if limit is not None else -1,offset]
        with self.connect() as c:
            rows=c.execute(sql,tuple(params)).fetchall()
        return [r for row in rows if (r:=json.loads(row[0])) and (sid is None or r['session_id']==sid) and (board is None or r['board']==board)]

    def append(self, rid, kind, body):
        with self.connect() as c:
            c.execute('INSERT INTO journal(run_id,at,kind,body) VALUES (?,?,?,?)',(rid,time.time(),kind,json.dumps(body,ensure_ascii=False)))

    def journal(self, rid, after=0):
        self.run(rid)
        with self.connect() as c:
            rows=c.execute('SELECT * FROM journal WHERE run_id=? AND seq>? ORDER BY seq LIMIT 1000',(rid,after)).fetchall()
        return [{**dict(r),'body':json.loads(r['body'])} for r in rows]
