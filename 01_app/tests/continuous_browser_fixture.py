"""Synthetic continuous-workflow UI fixture, never production business state."""
import argparse,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles
from backend.app import create_app
from conftest import LOCAL, isolated_root
from test_pi_runtime import CONFIG,settled
from test_autonomous_control import send_auto
from test_continuous_runtime import setup,runner_for
import uvicorn
p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--port',type=int,default=8767);a=p.parse_args()
if a.port==8765:raise SystemExit('模拟测试服务禁止使用正式端口8765')
assert a.data_dir.resolve().name=='browser-fixture' and not a.data_dir.resolve().is_relative_to(LOCAL/'var')
a.data_dir.mkdir(parents=True,exist_ok=True);os.environ['DISCLOSURE_TEST_KEY']='isolated-browser-fixture'
config={**CONFIG,'workflow_policy':'continuous-v1'}
def make():
 app=create_app(a.data_dir,isolated_root(a.data_dir),{'allowed_hosts':['testserver','127.0.0.1','localhost']},pi_config=config)
 runtime=app.state.pi_runtime
 def model(packet,emit,bridge,stop):
  event=runtime.event(runtime.store.session(packet['session_id'])['event_id'])
  return runner_for(runtime,event.get('output_mode')=='word')(packet,emit,bridge,stop)
 runtime.runner=model
 return app
app=make()
if not app.state.pi_runtime.store.sessions('chinext'):
 with TestClient(app) as c:
  t=c.get('/api/session').json()['csrf_token'];c.headers.update({'Origin':'http://testserver','X-CSRF-Token':t})
  r=app.state.pi_runtime
  for mode,title in [('text','连续正文确认测试'),('word','Word前完整正文确认测试')]:
   s,e=setup(c,r,mode);out=settled(c,send_auto(c,s,'仅隔离测试：完成当前工作稿',expected_revision=e['revision']));assert out['run']['status']=='waiting_approval',out['run']
   c.patch('/api/chat/sessions/'+s['id'],json={'title':title})
 app=make()
app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True))
uvicorn.run(app,host='127.0.0.1',port=a.port,log_level='warning')
