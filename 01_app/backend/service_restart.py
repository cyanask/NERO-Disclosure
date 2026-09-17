"""Idle-only restart handoff to the local launcher; never accept client commands."""
import threading
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException, Request
from pydantic import Field
from starlette.responses import JSONResponse

from .models import Strict

PATH = '/api/governance/service/restart'


class RestartRequest(Strict):
    instance_id: str = Field(min_length=1, max_length=128)


class ServiceControl:
    def __init__(self, runtime):
        self.runtime = runtime
        self.instance_id = str(uuid4())
        self.lock = threading.RLock()
        self.writes = 0
        self.pending = False
        self.error = ''
        self.restart = None

    def reason(self):
        if self.restart is None:
            return '当前启动方式不支持页面重启，请使用项目启动入口。'
        if self.runtime.active:
            return '当前有模型任务运行，请等待结束或先停止任务。'
        # Includes the gap between a round settling and its next batch/continuation.
        workers = [t for t in threading.enumerate() if t.is_alive()]
        if any(t.name.startswith('disclosure-pi-') for t in workers):
            return '模型任务仍在收尾，请稍后重试。'
        if any(t.name == 'version-verify' for t in workers):
            return '完整校验正在运行，请等待结束或先停止校验。'
        if any(t.name == 'disclosure-model-login' for t in workers):
            return '模型登录正在进行，请先完成或取消登录。'
        return ''

    def state(self):
        with self.lock:
            reason = self.reason()
            return {'instance_id': self.instance_id, 'supported': self.restart is not None,
                    'pending': self.pending, 'can_restart': not self.pending and not reason,
                    'reason': reason, 'error': self.error}

    def begin(self, instance_id):
        with self.lock:
            if instance_id != self.instance_id:
                raise HTTPException(409, '服务已更换，请刷新状态后再操作，未重复重启。')
            if self.pending:
                return False
            if self.writes > 1:
                raise HTTPException(409, '其他操作尚未完成，请稍后重试。')
            reason = self.reason()
            if reason:
                raise HTTPException(409, reason)
            self.pending = True
            self.error = ''
            return True

    def dispatch(self):
        try:
            self.restart()
        except Exception:
            with self.lock:
                self.pending = False
                self.error = '未能请求重启，服务仍在运行，请检查启动终端。'


class RestartGuard:
    """Reserve shutdown atomically against incoming mutations; drain existing reads."""
    def __init__(self, app, control):
        self.app, self.control = app, control

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        write = scope['method'] not in ('GET', 'HEAD', 'OPTIONS')
        with self.control.lock:
            blocked = self.control.pending and scope['path'] not in (PATH, '/api/session')
            if not blocked and write:
                self.control.writes += 1
        if blocked:
            return await JSONResponse({'detail': '服务正在重启，请等待重新连接。'}, status_code=503)(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            if write:
                with self.control.lock:
                    self.control.writes -= 1


def mount(app, runtime, security):
    control = ServiceControl(runtime)
    app.state.service_control = control
    app.add_middleware(RestartGuard, control=control)

    @app.get(PATH)
    def state(request: Request):
        security.actor(request)
        return control.state()

    @app.post(PATH, status_code=202)
    def restart(body: RestartRequest, request: Request, background: BackgroundTasks):
        if security.actor(request)['channel'] != 'web':
            raise HTTPException(403, '重启仅接受本机页面请求')
        if control.begin(body.instance_id):
            background.add_task(control.dispatch)
        return {'instance_id': control.instance_id, 'pending': True}
