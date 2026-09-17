"""Real Python -> Pi child -> local HTTP fixture; no external model or credentials."""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from uuid import uuid4
from test_pi_runtime import client,new_session,send,settled
from backend.conversation_history import state_path


def test_native_subprocess_replay_and_live_message_queue(client):
    c,runtime,_=client;requests=[];working=threading.Event();release=threading.Event();blocked=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            packet=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(packet)
            route=any(t['function']['name']=='route_request' for t in packet.get('tools',[]))
            if route:
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'route-'+str(uuid4()),'type':'function','function':{'name':'route_request','arguments':json.dumps({'domain':'disclosure','intent':'consult','reason':'isolated transport verification'})}}]};stop='tool_calls'
            else:
                if not blocked:blocked.append(True);working.set();assert release.wait(5)
                delta={'role':'assistant','content':'Synthetic typed reply'};stop='stop'
            raw=('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':stop}]})+'\n\ndata: [DONE]\n\n').encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    runtime.config_override=copy.deepcopy(runtime.config_override);runtime.config_override['models'][0]['baseUrl']=f'http://127.0.0.1:{server.server_port}/v1';runtime.runner=None
    try:
        session,event=new_session(c);result,_=send(c,session,event)
        assert working.wait(5)
        message={'text':'Additional instruction','mode':'steer','request_id':str(uuid4())}
        target='/api/chat/runs/'+result.json()['id']+'/messages'
        assert c.post(target,json=message).status_code==200
        assert c.post(target,json=message).status_code==200
        assert c.post(target,json={**message,'text':'different content'}).status_code==409
        release.set();done=settled(c,result)
        assert done['run']['status']=='completed',done
        assert len([r for r in done['events'] if r['kind']=='user_message_delivered'])==1
        path=state_path(runtime,done['run']);checkpoint=json.loads(path.read_text())
        assert checkpoint['session_id']==session['id']
        assert any(m['role']=='user' and m['content']=='Additional instruction' for m in checkpoint['messages'])
        assert 'test-credential-not-real-123456' not in path.read_text()
        result,_=send(c,session,event);assert settled(c,result)['run']['status']=='completed'
        assert any(m['role']=='assistant' and m.get('content')=='Synthetic typed reply' for m in requests[-1]['messages'])
        assert any(m['role']=='user' and m.get('content')=='Additional instruction' for m in requests[-1]['messages'])
        assert c.post(target,json={**message,'request_id':str(uuid4())}).status_code==409
    finally:
        release.set();server.shutdown();server.server_close();thread.join(2)
