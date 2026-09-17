"""Browser-only, company-scoped evidence projections; the journal stays authoritative."""
from fastapi import HTTPException, Request, Query
from . import evidence_summary
from .boards import require_board
from .chat_store import LIVE


def mount(app, runtime, browser):
    def scoped(sid, board, company):
        require_board(board)
        session = runtime.store.session(sid)
        if session['board'] != board or runtime.session_company(session) != company:
            raise HTTPException(403, '会话不属于当前公司或板块')
        return session

    def run_view(run):
        return {k: run.get(k) for k in ('id', 'session_id', 'stage', 'status', 'created', 'updated')}

    @app.get('/api/chat/evidence-sessions')
    def sessions(request: Request, board: str, company: str = Query(pattern=r'^\d{6}$'),
                 archived: bool = False, offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
        browser(request); require_board(board)
        rows = [s for s in runtime.store.sessions(board, archived=archived)
                if runtime.session_company(s) == company]
        result = []
        for session in rows[offset:offset+limit]:
            runs = runtime.store.runs(session['id'])
            result.append({**{k: session[k] for k in ('id', 'title', 'updated', 'event_id')},
                           'run_count': len(runs), 'status': runs[0]['status'] if runs else 'empty'})
        return {'items': result, 'total': len(rows)}

    @app.get('/api/chat/sessions/{sid}/evidence')
    def summary(sid: str, request: Request, board: str, company: str = Query(pattern=r'^\d{6}$'), run_id: str = ''):
        browser(request); session = scoped(sid, board, company)
        runs = runtime.store.runs(sid)
        selected = [r for r in runs if r['id'] == run_id] if run_id else runs
        if run_id and not selected: raise HTTPException(404, '本会话没有这轮执行')
        rows = evidence_summary.journal(runtime.store, [r['id'] for r in selected])
        return {**evidence_summary.build(selected, rows), 'session_id': sid, 'title': session['title'],
                'board': board, 'company': company, 'runs': [run_view(r) for r in runs],
                'scope': 'run' if run_id else 'session', 'run_id': run_id,
                'live': any(r['status'] in LIVE for r in selected),
                'status': selected[0]['status'] if selected else 'empty'}
