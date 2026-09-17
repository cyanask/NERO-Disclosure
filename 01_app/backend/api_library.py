"""Read-only library, template and knowledge endpoints.

These routes only read registered libraries and templates; they never touch event
state, so they live outside create_app's workflow surface. mount() returns the few
handles the in-process Pi router still dispatches.
"""
import json
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from . import library
from .boards import require_board
from .domain import Seeds


class Surface:
    """Named handles for the operations dispatched by the in-process router."""

    def __init__(self,search,item,templates,knowledge):
        self.search,self.item,self.templates,self.knowledge=search,item,templates,knowledge


def mount(app,root,seeds,security):
    @app.get('/api/templates')
    def templates(request: Request, kind: str | None = None, board: str | None = None):
        security.actor(request)
        return [{k:v for k,v in entry.items() if k not in ('file','sections')} for entry in seeds.for_board(board).templates(kind)]

    @app.get('/api/knowledge')
    def knowledge(request: Request, q: str = '', board: str | None = None):
        security.actor(request)
        if len(q) > 500:
            raise HTTPException(422, '查询过长')
        return [item for item in seeds.for_board(board).knowledge() if q.casefold() in json.dumps(item, ensure_ascii=False).casefold()]

    @app.get('/api/library/search')
    def search(request: Request, collection: str = 'laws', q: str = '', kind: str | None = None, board: str | None = None, offset: int = 0, limit: int = 20, view: str = 'items', company: str = '', violation: str | None = None, disposition: str | None = None, year: int | None = None):
        security.actor(request)
        if len(q)>500 or offset<0 or not 1<=limit<=100 or view not in ('items','groups','candidates'):
            raise HTTPException(422, '检索参数超出范围')
        scoped=Seeds(root,require_board(board),{'layer':board,'stock_code':company}) if company else seeds.for_board(board)
        return library.search(scoped,collection,q=q,kind=kind,offset=offset,limit=limit,view=view,violation=violation,disposition=disposition,year=year)

    @app.get('/api/library/items/{item_id}')
    def item(item_id: str, request: Request, page: int | None = None, board: str | None = None, view: str = 'auto', company: str = ''):
        security.actor(request)
        scoped=Seeds(root,require_board(board),{'layer':board,'stock_code':company}) if company else seeds.for_board(board)
        return library.item(scoped,item_id,page,view)

    @app.get('/api/library/assets/{item_id}')
    def library_asset(item_id: str, request: Request, board: str | None = None):
        security.actor(request)
        path=library.asset(seeds.for_board(board),item_id)
        return FileResponse(path,filename=path.name)

    @app.get('/api/library/items/{item_id}/evidence/{document_id}')
    def library_evidence_asset(item_id: str,document_id: str,request: Request,board: str | None = None):
        security.actor(request)
        path=library.evidence_asset(seeds.for_board(board),item_id,document_id)
        return FileResponse(path,filename=path.name)

    return Surface(search,item,templates,knowledge)
