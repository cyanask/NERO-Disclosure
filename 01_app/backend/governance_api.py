"""Manual governance operations; GET reads records and never starts a scan/run."""
from fastapi import HTTPException,Request
from pydantic import Field
from .models import Strict
from .boards import require_board
from . import system_governance as storage, lifecycle_batches, runtime_health, version_governance


class Selection(Strict):
    category:str
    ids:list[str]=Field(min_length=1,max_length=200)


class Confirmation(Strict):
    preview_id:str
    confirmed:bool


class LawBatch(Strict):
    board:str
    model_key:str
    request_id:str=Field(min_length=8,max_length=128)
    instrument_ids:list[str]|None=None


class VerifyRequest(Strict):
    request_id:str=Field(min_length=8,max_length=128)


def mount(app,root,directory,runtime,security):
    version_governance.bind_runtime(runtime)
    from .service_restart import mount as mount_restart
    mount_restart(app,runtime,security)
    def user(request):
        if security.actor(request)['channel']!='web':raise HTTPException(403,'治理操作仅接受本机页面请求')
    def idle():
        if runtime.active:raise HTTPException(409,'当前仍有模型任务运行，请待结束后清理')
    @app.post('/api/governance/scan')
    def scan(request:Request):
        user(request)
        result=storage.scan(root,directory);result['history']=storage.history(directory)
        return result
    @app.post('/api/governance/cleanup-preview')
    def preview(body:Selection,request:Request):
        user(request);runtime.own()
        with runtime.lock:
            idle();return storage.prepare(root,directory,body.category,body.ids)
    @app.post('/api/governance/cleanup')
    def cleanup(body:Confirmation,request:Request):
        user(request);runtime.own()
        if body.confirmed is not True:raise HTTPException(422,'请在清单中明确确认清理')
        with runtime.lock:
            idle();return storage.execute(root,directory,body.preview_id)
    @app.post('/api/governance/cleanup/restore')
    def cleanup_restore(body:Confirmation,request:Request):
        user(request);runtime.own()
        if body.confirmed is not True:raise HTTPException(422,'请在清单中明确确认恢复')
        with runtime.lock:
            idle();return storage.restore(root,directory,body.preview_id)
    @app.post('/api/governance/cleanup/purge')
    def cleanup_purge(body:Confirmation,request:Request):
        user(request);runtime.own()
        if body.confirmed is not True:raise HTTPException(422,'请在清单中明确确认释放空间')
        with runtime.lock:
            idle();return storage.purge(directory,body.preview_id)
    @app.post('/api/governance/laws/runs')
    def start(body:LawBatch,request:Request):
        user(request);require_board(body.board)
        return lifecycle_batches.start(runtime,body.board,body.model_key,body.request_id,body.instrument_ids)
    @app.get('/api/governance/laws/current')
    def current(request:Request,board:str):
        user(request);require_board(board)
        rows=[r for r in runtime.store.runs(board=board) if (r.get('lifecycle') or {}).get('batch_id')]
        return lifecycle_batches.status(runtime,rows[0]['lifecycle']['batch_id']) if rows else None
    @app.get('/api/governance/laws/runs/{identity}')
    def read(identity:str,request:Request):
        user(request);return lifecycle_batches.status(runtime,identity)
    @app.post('/api/governance/laws/runs/{identity}/cancel')
    def stop(identity:str,request:Request):
        user(request);return lifecycle_batches.cancel(runtime,identity)
    @app.post('/api/governance/health/scan')
    def health_scan(request:Request):
        user(request)
        return runtime_health.scan(root,directory,runtime,port=request.url.port)
    @app.get('/api/governance/health')
    def health_read(request:Request):
        user(request);return runtime_health.saved(directory)
    @app.post('/api/governance/version/scan')
    def version_scan(request:Request):
        user(request);return version_governance.scan(root,directory,runtime)
    @app.get('/api/governance/version')
    def version_read(request:Request):
        user(request);return version_governance.saved(directory,root)
    @app.post('/api/governance/version/verify')
    def version_verify(body:VerifyRequest,request:Request):
        user(request);runtime.own()
        return version_governance.verify_start(root,directory,body.request_id)
    @app.get('/api/governance/version/verify')
    def version_verify_state(request:Request):
        user(request);return version_governance.verify_state(directory)
    @app.post('/api/governance/version/verify/cancel')
    def version_verify_cancel(body:VerifyRequest,request:Request):
        user(request);return version_governance.verify_cancel(directory,body.request_id)
