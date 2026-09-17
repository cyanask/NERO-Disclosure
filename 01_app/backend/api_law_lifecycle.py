"""Law lifecycle endpoints: state view, monthly check and the browser-triggered run."""
import json
from uuid import uuid4
from fastapi import HTTPException, Request
from sqlalchemy import text
from . import models as m, law_lifecycle
from .boards import require_board


def mount(app,ctx):
    @app.get('/api/law-lifecycle')
    def law_lifecycle_state(request: Request, board: str, today: str | None = None):
        ctx.security.actor(request)
        require_board(board)
        parsed=None
        if today:
            from datetime import date
            try:parsed=date.fromisoformat(today)
            except ValueError:raise HTTPException(422,'日期格式无效') from None
        value=law_lifecycle.state(ctx.root,board,today=parsed)
        # Read only the adopted source references. A governance GET must not
        # invoke event.load, which can invalidate workflow state as a side effect.
        with ctx.store.engine.connect() as conn:
            refs=conn.execute(text("SELECT id,json_extract(body,'$.title') AS title,json_extract(body,'$.assessment.source_ids') AS ids,json_extract(body,'$.law_bindings') AS bindings FROM events WHERE json_extract(body,'$.layer')=:board"),{'board':board}).mappings().all()
        for row in value['records']:
            ids=set(row['source_ids'])
            row['affected_matters']=[{'id':r['id'],'title':r['title']} for r in refs
                if ids.intersection((json.loads(r['ids']) if r['ids'] else [])+list((json.loads(r['bindings']) if r['bindings'] else {}).values()))]
        return value

    @app.post('/api/law-lifecycle/check')
    def law_lifecycle_check(payload: m.LawLifecycleCheck, request: Request):
        ctx.security.actor(request)
        require_board(payload.board)
        return law_lifecycle.run(ctx.root,payload.board,instrument_id=payload.instrument_id,force=payload.force,
                                 failed_only=payload.failed_only,dry_run=payload.dry_run)

    @app.post('/api/law-lifecycle/run')
    def law_lifecycle_run(payload: m.LifecycleRunRequest, request: Request):
        """Browser manual trigger: one Pi run checks one law and registers through the fixed path."""
        ctx.security.actor(request)
        require_board(payload.board)
        target=law_lifecycle.instruments(ctx.root,payload.board).get(payload.instrument_id)
        if target is None:raise HTTPException(404,'法规不在当前板块清单')
        sessions=[s for s in ctx.runtime.store.sessions(payload.board,'',False)
                  if s['title']==law_lifecycle.SESSION_TITLE and s['event_id'].startswith('conversation:')]
        session=sessions[0] if sessions else ctx.runtime.store.create_session(payload.board,'',law_lifecycle.SESSION_TITLE,str(uuid4()))
        run=ctx.runtime.accept(session['id'],{'text':f'核验法规《{target["title"]}》（{payload.instrument_id}）的官方原文并登记结论。',
            'model_key':payload.model_key,'stage':'lifecycle','request_id':str(uuid4()),
            'lifecycle':{'instrument_id':payload.instrument_id}})
        return {'run_id':run['id'],'session_id':session['id'],'instrument_id':payload.instrument_id,'title':target['title']}

    return law_lifecycle_state
