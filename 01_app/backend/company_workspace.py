"""Company entry, persisted selection and source-backed registration on the one Pi runtime."""
import json
from uuid import uuid4
from fastapi import HTTPException, Request
from pydantic import Field
from . import announcement_history as history
from .boards import ACTIVE_BOARDS, BOARDS, require_board
from .chat_store import LIVE
from .models import Strict
from .public_store import atomic


class Lookup(Strict):
    company_name: str = Field(min_length=2, max_length=150)
    stock_code: str = Field(pattern=r'^\d{6}$')
    model_key: str = Field(default='', max_length=80)
    request_id: str = Field(min_length=8, max_length=128)


class Registration(Strict):
    run_id: str = Field(min_length=1, max_length=100)


class Selection(Strict):
    board: str
    stock_code: str = Field(pattern=r'^\d{6}$')


def company(root, board, code):
    value = history.state(root, board, code)
    if not value['company_name']:
        raise HTTPException(404, '公司尚未登记，请先核实并登记')
    return {k: value[k] for k in ('board', 'stock_code', 'company_name')} | {
        'board_name': next(b['name'] for b in BOARDS if b['id'] == board),
        'verification': value.get('identity_verification'),
    }


def listing(root):
    return [company(root, board, item['stock_code']) for board in sorted(ACTIVE_BOARDS)
            for item in history.companies(root, board) if item['company_name']]


def snapshot(runtime):
    items = listing(runtime.root)
    path = runtime.directory / 'company-workspace.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    selected = next((item for item in items if (item['board'], item['stock_code']) ==
                     (saved.get('board'), saved.get('stock_code'))), None)
    if not selected and len(items) == 1:
        selected = items[0]
    return {'company': selected, 'companies': items}


def select(runtime, board, code):
    value = company(runtime.root, board, code)
    with runtime.lock:
        atomic(runtime.directory / 'company-workspace.json', history.encoded(
            {'board': board, 'stock_code': code}))
    return value


def enqueue(runtime, body):
    """One bounded public identity lookup; name/code never become a business fact by inference."""
    from .company_lookup import STAGE
    name = body.company_name.strip()
    if len(name) < 2:
        raise HTTPException(422, '请填写公司全称')
    runtime.own()
    with runtime.lock:
        prior = next((r for r in runtime.store.runs(board=STAGE)
                      if r['request_id'] == body.request_id), None)
        identity = {'company_name': name, 'stock_code': body.stock_code}
        if prior:
            if prior.get('company_lookup') != identity or (body.model_key and body.model_key != prior['model']['key']):
                raise HTTPException(409, '请求编号已用于其他公司或模型')
            return prior
        # Repeated clicks / another tab share the same live lookup, never duplicate model calls.
        active = next((r for r in runtime.store.runs(board=STAGE)
                       if r['status'] in LIVE and r.get('company_lookup') == identity), None)
        if active:
            if body.model_key and active['model']['key'] != body.model_key:
                raise HTTPException(409, '该公司已有另一模型正在核实，请先停止或等待完成')
            return active
        routes = runtime.settings.read()['routes']
        key = body.model_key or routes.get('knowledge') or routes.get('default')
        if not key:
            raise HTTPException(409, '请先在模型设置中配置并选择用于联网核实的模型')
        runtime.settings.resolve_model(key)
        session = runtime.store.create_session(STAGE, None, name + ' · 公司核实', str(uuid4()), body.stock_code)
        return runtime.accept(session['id'], {'text': '联网核实公司全称、证券代码和当前所属板块，核实成功后登记本公司。',
            'model_key': key, 'stage': STAGE, 'company_code': body.stock_code,
            'company_lookup': identity, 'expected_revision': 0, 'request_id': body.request_id})


def register(runtime, rid):
    from .company_lookup import STAGE
    with runtime.lock:
        run = runtime.store.run(rid)
        result = run.get('company_result') or {}
        if run['stage'] != STAGE or run['status'] != 'completed' or run.get('registration_cancelled') or result.get('status') != 'verified':
            raise HTTPException(409, '尚未取得已完成的公司核实结果，请查看核实状态后重试')
        board, code = require_board(result['board']), run['company_lookup']['stock_code']
        # Re-read the exact downloaded evidence; a stale or altered receipt cannot be registered.
        from .company_lookup import evidence
        evidence(runtime, run, result['board'], result['sources'])
        old = history.register_company(runtime.root, board, code, run['company_lookup']['company_name'])
        if not old.get('identity_verification'):
            history.save(runtime.root, board, code, old['fingerprint'],
                         lambda value: value.update(identity_verification=result), 'Agent联网核实登记')
        selected=select(runtime, board, code)
        runtime.store.update(rid,company_registered={'board':board,'stock_code':code})
        return selected


def mount(app, runtime, security):
    def browser(request):
        if security.actor(request)['channel'] != 'web':
            raise HTTPException(403, '公司设置只接受本机网页操作')

    @app.get('/api/company-workspace')
    def workspace(request: Request):
        browser(request)
        return snapshot(runtime)

    @app.post('/api/company-workspace/select')
    def choose(body: Selection, request: Request):
        browser(request)
        return select(runtime, body.board, body.stock_code)

    @app.post('/api/company-workspace/lookup')
    def lookup(body: Lookup, request: Request):
        browser(request)
        return enqueue(runtime, body)

    @app.post('/api/company-workspace/register')
    def registration(body: Registration, request: Request):
        browser(request)
        return register(runtime, body.run_id)
