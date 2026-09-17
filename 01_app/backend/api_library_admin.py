"""Scenario samples and canonical library maintenance endpoints."""
from fastapi import HTTPException, Request
from . import models as m, library_admin


class Surface:
    """Route functions the in-process router still dispatches by name."""

    def __init__(self,scenarios,import_scenario,library_manage,library_update):
        self.scenarios=scenarios
        self.import_scenario=import_scenario
        self.library_manage=library_manage
        self.library_update=library_update


def mount(app,ctx,create_event):
    @app.get('/api/scenarios')
    def scenarios(request: Request, board: str | None = None):
        ctx.security.actor(request)
        return (ctx.seeds.for_board(board) if board is not None else ctx.seeds).scenarios()

    @app.post('/api/scenarios/{scenario_id}/import')
    def import_scenario(scenario_id: str, payload: m.Import, request: Request):
        source = next((s for s in ctx.seeds.scenarios() if s['id'] == scenario_id), None)
        if source is None:
            raise HTTPException(404, '模拟样本不存在')
        body = {key:source[key] for key in ('company_id','kind','title','summary','facts')}
        body['request_id'] = payload.request_id
        return create_event(m.Create(**body).model_dump(), request)

    @app.get('/api/library/{collection}/manage')
    def library_manage(collection: str,request: Request,board: str | None = None,company:str=''):
        ctx.security.actor(request)
        value=library_admin.state(ctx.root,collection,board=board)
        value['items']=[r for r in value['items'] if r.get('company_scope') in (None,'',company)]
        return value

    @app.post('/api/library/{collection}/update')
    def library_update(collection: str,payload: m.LibraryUpdate,request: Request,board: str | None = None):
        ctx.security.actor(request)
        return library_admin.update(ctx.root,collection,payload.items,payload.expected_fingerprint,board=board)

    return Surface(scenarios,import_scenario,library_manage,library_update)
