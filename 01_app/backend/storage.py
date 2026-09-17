"""Transactional local demonstration store; never opens another project's database.

Lock discipline: writes always run inside ``transaction()`` (``BEGIN IMMEDIATE``);
reads that must not mutate run inside ``read()`` (``PRAGMA query_only=ON``, no
deferred write upgrade). Callers decide which one they need, so a GET stays out
of the write lock unless it genuinely has to record a state repair.
"""
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from sqlalchemy import create_engine, text


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class Store:
    def __init__(self, path):
        self._write_connection=ContextVar('disclosure_write_connection',default=None)
        self.engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread': False, 'timeout': 15})
        with self.engine.begin() as conn:
            conn.execute(text('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL)'))
            conn.execute(text('CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, digest TEXT NOT NULL, response TEXT NOT NULL)'))
            conn.execute(text('CREATE TABLE IF NOT EXISTS versions (event_id TEXT, revision INTEGER, body TEXT NOT NULL, PRIMARY KEY(event_id, revision))'))

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            token=self._write_connection.set(conn)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._write_connection.reset(token)

    @contextmanager
    def read(self):
        """Read-only connection: no write lock, and SQLite rejects accidental writes."""
        with self.engine.connect() as conn:
            conn.exec_driver_sql('PRAGMA query_only=ON')
            try:
                yield conn
            finally:
                conn.rollback()
                conn.exec_driver_sql('PRAGMA query_only=OFF')

    def get(self, conn, event_id):
        row = conn.execute(text('SELECT body FROM events WHERE id=:id'), {'id': event_id}).scalar()
        return json.loads(row) if row else None

    def company_drafts(self, board, code):
        if not code:return []
        query=text("SELECT body FROM events WHERE json_extract(body,'$.layer')=:board AND json_extract(body,'$.stock_code')=:code")
        args={'board':board,'code':code}
        current=self._write_connection.get()
        # Gate checks invoked inside a write must share its snapshot. A second
        # connection can block on our own exclusive lock after a large save.
        if current is not None and not current.closed:
            rows=current.execute(query,args).scalars().all()
        else:
            with self.read() as conn:rows=conn.execute(query,args).scalars().all()
        return [r for raw in rows if (r:=json.loads(raw)).get('draft')]

    def save(self, conn, event):
        values = {'id': event['id'], 'body': canonical(event), 'revision': event['revision']}
        conn.execute(text('INSERT INTO events VALUES (:id,:body) ON CONFLICT(id) DO UPDATE SET body=:body'), values)
        conn.execute(text('INSERT INTO versions VALUES (:id,:revision,:body)'), values)

    def cached(self, conn, key, payload):
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        row = conn.execute(text('SELECT digest,response FROM requests WHERE key=:key'), {'key': key}).first()
        if row:
            if row.digest != digest:
                from fastapi import HTTPException
                raise HTTPException(409, 'request_id 已用于不同请求')
            return digest, json.loads(row.response)
        return digest, None

    def cache(self, conn, key, digest, response):
        conn.execute(text('INSERT INTO requests VALUES (:key,:digest,:response)'), {'key': key, 'digest': digest, 'response': canonical(response)})
