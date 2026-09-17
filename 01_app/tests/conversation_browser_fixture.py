"""Isolated browser QA service. Never use the business data directory."""
import argparse,os,sys
from uuid import uuid4
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from fastapi.staticfiles import StaticFiles
from backend.app import create_app
from conftest import LOCAL, isolated_root
from test_pi_runtime import CONFIG
from test_agent_tasks import candidate
import uvicorn

network_failure=False

def runner(packet,emit,bridge,stop):
    global network_failure
    emit({'type':'started'})
    if packet.get('routeFirst'):
        text=packet['prompt']
        if any(x in text for x in ('天气','旅游','写代码')):
            bridge('route_request',{'domain':'unrelated','intent':'consult','reason':'隔离模型演示无关请求拒绝'});emit({'type':'done'});return
        if '流程跟踪测试' in text:
            bridge('route_request',{'domain':'disclosure','intent':'workflow','reason':'隔离测试进入真实业务节点','session_title':'董事会披露流程跟踪','event':{'company_name':'隔离测试公司','title':'董事会测试事项','summary':'隔离测试：公司拟召开董事会，具体议案待补充','output_mode':'text'}})
            if not stop.wait(15):bridge('request_information',{'questions':['请补充本次董事会拟审议的议案。']})
            emit({'type':'done'});return
        if '知识库查询测试' in text:
            bridge('route_request',{'domain':'knowledge','intent':'query','reason':'隔离测试知识库查询','session_title':'董事会规则查询'})
            emit({'type':'done'});return
        routed=bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'隔离模型演示信披咨询','session_title':'董事会召开与披露安排'})
        packet={**packet,'tools':routed['next_context']['tools']}
    if 'submit_candidate' in [t['name'] for t in packet['tools']]:
        bridge('submit_candidate',{'result':candidate()})
        emit({'type':'finalization_started'})
        emit({'type':'assistant','phase':'final','message':1,'stopReason':'stop','text':'这是隔离测试结果：**模拟议案需准备披露，尚待你审阅确认。**\n\n| 文件 | 适用条件 | 内容要求 |\n| --- | --- | --- |\n| 模拟董事会决议公告 | 本次模拟议案涉及股东会表决 | 会议日期、表决结果、议案内容 |\n\n当前材料仅用于界面测试。真实披露义务、期限和例外仍由专业人员核验。'})
        emit({'type':'finalization_completed'})
    else:
        if '断线测试' in packet['prompt']:
            network_failure=True
            try:stop.wait(120)
            finally:network_failure=False
        if '慢速输入测试' in packet['prompt']:
            stop.wait(120)
        emit({'type':'assistant','phase':'answer','message':0,'stopReason':'stop','text':'已收到你的补充。这是隔离测试对话，没有修改真实业务记录。'})
    emit({'type':'done'})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--web-root',type=Path,default=ROOT/'frontend/dist',help='Use an isolated web build without replacing the served bundle')
    parser.add_argument('--empty',action='store_true',help='Start without seeded sessions')
    parser.add_argument('--composer-failures',action='store_true',help='Fail the first create and send, only in this isolated fixture')
    parser.add_argument('--progress-samples',action='store_true',help='Seed isolated completed, failed and waiting records for progress UI checks')
    a=parser.parse_args()
    if a.port==8765:raise SystemExit('模拟测试服务禁止使用正式端口8765')
    assert a.data_dir.resolve().name=='browser-fixture' and a.data_dir.resolve()!=LOCAL/'var'
    a.data_dir.mkdir(parents=True,exist_ok=True);os.environ['DISCLOSURE_TEST_KEY']='offline-browser-fixture'
    app=create_app(a.data_dir,isolated_root(a.data_dir),{'allowed_hosts':['testserver','127.0.0.1','localhost']},pi_config={**CONFIG,'workflow_policy':'continuous-v1'},pi_runner=runner)
    from fastapi.responses import JSONResponse
    @app.middleware('http')
    async def progress_network_failure(request,call_next):
        if network_failure and request.method=='GET' and request.url.path.startswith('/api/chat/runs/'):
            return JSONResponse({'detail':'隔离测试：进度连接暂不可用'},status_code=503)
        response=await call_next(request)
        if request.url.path.endswith('/stream'):
            original=response.body_iterator
            async def stream():
                try:
                    async for chunk in original:
                        if network_failure:break
                        yield chunk
                finally:await original.aclose()
            response.body_iterator=stream()
        return response
    if (a.progress_samples or not a.empty) and not app.state.pi_runtime.store.sessions('chinext'):
        store=app.state.pi_runtime.store
        sample=store.create_session('chinext','','隔离进展测试',str(uuid4()),company_code='300001')
        for stage,status in [('chat','failed'),('announcement','waiting_user'),('chat','completed')]:
            run,_=store.accept(sample,{'stage':stage,'text':'隔离界面测试','company_code':'300001','request_id':str(uuid4())},CONFIG['models'][0])
            rid=run['id'];store.append(rid,'user',{'text':'隔离进展测试，不代表真实业务判断。'})
            store.append(rid,'tool_started',{'id':'read-1','name':'knowledge_read','transport':'pi_model'})
            store.append(rid,'tool_failed' if status=='failed' else 'tool_returned',{'id':'read-1','name':'knowledge_read','transport':'pi_model'})
            store.update(rid,status=status,reason='隔离测试状态',questions=['请确认本次交易金额口径。'] if status=='waiting_user' else [])
            if status=='waiting_user':store.append(rid,'questions',{'questions':['请确认本次交易金额口径。']})
            store.append(rid,'assistant',{'text':'这是隔离测试答复，真实内容仍由用户审阅。','phase':'answer','stopReason':'stop','message':0})
    if a.composer_failures:
        from fastapi.responses import JSONResponse
        failures=set()
        @app.middleware('http')
        async def fail_first_write(request,call_next):
            path=request.url.path
            operation='create' if path=='/api/chat/sessions' else 'send' if path.startswith('/api/chat/sessions/') and path.endswith('/runs') else ''
            if request.method=='POST' and operation and operation not in failures:
                failures.add(operation)
                return JSONResponse({'detail':f'隔离测试：{operation} 首次请求失败，请重试，输入应保留。'},status_code=503)
            return await call_next(request)
    app.mount('/',StaticFiles(directory=a.web_root,html=True))
    uvicorn.run(app,host='127.0.0.1',port=a.port,log_level='warning')

if __name__=='__main__':main()
