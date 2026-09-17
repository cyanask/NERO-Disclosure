"""Progress uses the real Pi protocol call ID without logging another copy of inputs/results."""
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from fastapi import HTTPException
from backend.pi_runtime import PiRuntime
from backend import pi_subprocess


def test_process_records_correlated_success_failure_and_preserves_tool_protocol(monkeypatch):
    traces=[];sent=[];events=[]
    messages=iter([json.dumps({'type':'tool_call','id':identity,'name':'knowledge_read','args':{'fail':fail,'private':'private-argument'}})
                   for identity,fail in [('attempt-1',False),('attempt-2',True)]]+[json.dumps({'type':'done'})])
    class Session:
        process=SimpleNamespace(pid=123)
        returncode=0
        def __init__(self,*a,**kw):pass
        def send(self,payload):sent.append(payload)
        def read(self):return next(messages,None)
        def wait(self):return 0
        def close(self):pass
    monkeypatch.setattr(pi_subprocess,'Session',Session)
    monkeypatch.setattr(pi_subprocess,'node_path',lambda:'node')
    runtime=SimpleNamespace(code_root=Path(__file__).resolve().parents[1],lock=threading.RLock(),active={'r':{}},
        trace=lambda rid,kind,body:traces.append((kind,body)),finish_interrupted_call=lambda rid:None,
        add_timing=lambda *a:None,store=SimpleNamespace(update=lambda *a,**kw:None))
    def bridge(name,args):
        if args['fail']:raise HTTPException(409,'failed secret-key')
        return {'data':{'text':'private-result'}}
    PiRuntime.process(runtime,'r',{'apiKey':'secret-key'},events.append,bridge,threading.Event())
    receipts=[(kind,b) for kind,b in traces if b.get('transport')=='pi_model']
    assert [kind for kind,_ in receipts]==['tool_started','tool_returned','tool_started','tool_failed']
    assert [b['id'] for _,b in receipts]==['attempt-1','attempt-1','attempt-2','attempt-2']
    encoded=json.dumps(receipts)
    assert all(v not in encoded for v in ('private-argument','private-result','secret-key'))
    assert sent[1]['id']=='attempt-1' and sent[1]['data']['text']=='private-result'
    assert sent[2]['id']=='attempt-2' and 'error' in sent[2]
    assert events==[{'type':'done'}]
