"""Test driver for private workflow services; never emulates retired HTTP routes.

Synthetic callers exercise ownership in-process. Real browser/HTTP requests still
use production authentication, and cannot obtain an internal identity via headers.
"""
from contextvars import ContextVar
import httpx
from fastapi import HTTPException
from backend.security import Security

_caller = ContextVar('workflow_test_caller',default=None)
CALLERS=[{'Authorization':'Bearer fixture-internal-0'},{'Authorization':'Bearer fixture-internal-1'}]

def install_callers(monkeypatch):
    original=Security.actor
    def actor(self,request):
        value=original(self,request)
        identity=_caller.get()
        if value['channel']=='agent' and identity:
            value={**value,'actor_id':identity,'actor':'同名内部执行上下文'}
        return value
    monkeypatch.setattr(Security,'actor',actor)

def invoke(client,headers,operation,args,*,wrapped=False):
    identity=(headers or CALLERS[0])['Authorization']
    mark=_caller.set(identity)
    try:
        data=client.app.state.pi_runtime.route(operation,args)
        if wrapped:data={'operation':operation,'protocol_version':'1','data':data}
        return httpx.Response(200,json=data)
    except HTTPException as exc:return httpx.Response(exc.status_code,json={'detail':exc.detail})
    finally:_caller.reset(mark)

def route(client,headers,body):
    return invoke(client,headers,body['operation'],body.get('args',{}),wrapped=True)

def context(client,event,task,headers):
    return invoke(client,headers,'task.context',{'event_id':event['id'],'task_id':task['id']})
