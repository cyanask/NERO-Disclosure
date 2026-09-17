"""Local transport safety. There are no users, passwords or human privileges."""
import hmac
import secrets
import time
from urllib.parse import urlsplit
from fastapi import HTTPException


class Security:
    def __init__(self, config, store):
        self.store = store
        self.sessions = {}
        self.hosts = set(config.get('allowed_hosts', ['127.0.0.1', 'localhost']))
        self._internal_marker = object()

    def internal_agent_request(self):
        """In-process only; the marker cannot be supplied by an HTTP client."""
        from starlette.requests import Request
        host = sorted(self.hosts)[0]
        return Request({'type':'http','method':'POST','scheme':'http','path':'/internal/pi/workflow',
                        'query_string':b'','headers':[(b'host',host.encode())],
                        '_pi_marker':self._internal_marker})

    def origin(self, request, required=False):
        if request.url.hostname not in self.hosts:
            raise HTTPException(403, 'Host 不在本地允许列表')
        origin = request.headers.get('origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != request.url.scheme or parsed.netloc != request.headers.get('host'):
                raise HTTPException(403, 'Origin 与当前服务不一致')
        elif required:
            raise HTTPException(403, '浏览器写操作缺少 Origin')

    def default_session(self, request):
        now = time.time()
        self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > now}
        token = request.cookies.get('disclosure_session', '')
        if token not in self.sessions:
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {'csrf_token':secrets.token_urlsafe(32), 'expires':now+28800}
        return token, {'local_mode':True, 'csrf_token':self.sessions[token]['csrf_token'],
                       'identity_assurance':'none', 'authorization':'verify_and_gate'}

    def actor(self, request):
        self.origin(request)
        if request.scope.get('_pi_marker') is self._internal_marker:
            return {'actor':'Pi 本机运行时','channel':'agent','actor_id':'disclosure-pi-local-runtime','identity_assurance':'in_process_transport'}
        if request.headers.get('authorization'):
            raise HTTPException(403, '此服务仅支持网页会话；外部连接凭证不再接纳')
        token = request.cookies.get('disclosure_session', '')
        session = self.sessions.get(token)
        if request.method not in ('GET', 'HEAD'):
            self.origin(request, required=True)
            if not session or session['expires'] <= time.time():
                raise HTTPException(403, '本机会话已过期，请刷新页面')
            if not hmac.compare_digest(request.headers.get('x-csrf-token',''), session['csrf_token']):
                raise HTTPException(403, 'CSRF 校验失败')
        return {'actor':'本机操作', 'channel':'web', 'actor_id':'local-browser', 'identity_assurance':'none'}
