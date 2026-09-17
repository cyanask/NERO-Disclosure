"""Approved V2 only: real Pi + local fake provider + isolated Web browser slice."""
import argparse
import asyncio
import json
import os
import hashlib
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths


def serve(port,directory,web_root,model_settings=False):
    from fastapi import Request
    from fastapi.responses import StreamingResponse,JSONResponse
    from fastapi.staticfiles import StaticFiles
    from backend.app import create_app
    import uvicorn
    sys.path.insert(0,str(ROOT/'tests'))
    from test_agent_tasks import candidate
    os.environ['DISCLOSURE_V2_FIXTURE_KEY']='public-local-fixture-not-a-credential'
    models=[{'key':'fixture-'+key,'label':'本地接口样例 '+key.upper(),'provider':'fixture-'+key,'api':'openai-completions',
             'id':'fixture-'+key,'baseUrl':f'http://127.0.0.1:{port}/fixture/v1','api_key_env':'DISCLOSURE_V2_FIXTURE_KEY',
             'contextWindow':200000,'maxTokens':4096,'enabled':True} for key in ('a','b')]
    app=create_app(directory,workspace_paths.knowledge_of(ROOT),pi_config={'models':models})
    observations=[]
    if model_settings:
        from test_model_settings import FakeVault
        app.state.pi_runtime.settings.vault=FakeVault()

    @app.get('/fixture/observations')
    def observed():return observations

    @app.post('/fixture/v1/chat/completions')
    async def fake(request:Request):
        packet=await request.json();messages=packet['messages']
        last_user=next((m.get('content','') for m in reversed(messages) if m['role']=='user'),'')
        if isinstance(last_user,list):last_user=''.join(part.get('text','') for part in last_user if isinstance(part,dict) and part.get('type')=='text')
        elif not isinstance(last_user,str):last_user=json.dumps(last_user,ensure_ascii=False)
        if '故障测试' in last_user:return JSONResponse({'error':{'message':'Local fixture denied','type':'authentication_error'}},status_code=401)
        system=next((m.get('content','') for m in messages if m['role'] in ('system','developer')),'')
        probe=last_user=='Reply PI_CONNECTION_OK.'
        if probe:
            observations.append({'kind':'probe_received','model':packet['model'],'reasoning_effort':packet.get('reasoning_effort'),'message_count':len(messages),'roles':[m['role'] for m in messages],'tools':len(packet.get('tools',[])),'system_matches':system=='This is a connection test. Reply only PI_CONNECTION_OK. Do not use tools.'})
            assert system=='This is a connection test. Reply only PI_CONNECTION_OK. Do not use tools.'
            assert len(messages)==2 and not packet.get('tools') and packet.get('reasoning_effort')=='max'
            observations.append({'kind':'connection_probe','model':packet['model'],'reasoning_effort':packet['reasoning_effort'],'message_count':len(messages),'tools':0,'customer_context':False})
            stage='chat'
        else:
            ctx=json.loads(system.split('本轮绑定上下文：\n',1)[1]);stage=ctx.get('stage','chat')
        tool=None
        if stage=='assessment':
            if '请列出还缺什么' in last_user:
                tool=('request_information',{'questions':['会议实际召开日期是什么？','请补充决议是否已经作出及资料来源。']})
            else:
                tool=('submit_candidate',{'result':candidate()}) if any(m['role']=='tool' for m in messages) else ('search_library',{'collection':'laws','query':'董事会决议'})
        async def chunks():
            def chunk(delta,finish=None):
                return 'data: '+json.dumps({'id':'local-fixture','object':'chat.completion.chunk','created':int(time.time()),'model':packet['model'],
                                          'choices':[{'index':0,'delta':delta,'finish_reason':finish}]},ensure_ascii=False)+'\n\n'
            yield chunk({'role':'assistant'})
            if tool:
                await asyncio.sleep(3)
                yield chunk({'tool_calls':[{'index':0,'id':'fixture-'+str(uuid4()),'type':'function','function':{'name':tool[0],'arguments':json.dumps(tool[1],ensure_ascii=False)}}]})
                yield chunk({},'tool_calls')
            else:
                for text in ['PI_CONNECTION_OK'] if probe else ['这是本地接口样例。','已收到当前事项说明。','本轮只验证会话和工具连接，','不作真实法律结论。']:
                    await asyncio.sleep(1.2 if '慢速' in last_user else .1);yield chunk({'content':text})
                yield chunk({},'stop')
            yield 'data: [DONE]\n\n'
        return StreamingResponse(chunks(),media_type='text/event-stream')
    app.mount('/',StaticFiles(directory=web_root,html=True))
    uvicorn.run(app,host='127.0.0.1',port=port,log_level='error',access_log=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--approved-v2',action='store_true')
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--build-web',action='store_true')
    parser.add_argument('--model-settings',action='store_true',help='需当前模型设置增量 V2 批准；使用隔离内存凭据库')
    parser.add_argument('--settings-only',action='store_true',help='聚焦新模型设置；原操作台已通过的回归不重复')
    parser.add_argument('--port',type=int)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--web-root',type=Path,default=ROOT/'frontend/dist')
    parser.add_argument('--output',type=Path,default=workspace_paths.local_of(ROOT)/'records/docs/qa/pi-console-20260911/v2')
    parser.add_argument('--browser',type=Path)
    parser.add_argument('--playwright',type=Path)
    args=parser.parse_args()
    if not args.approved_v2:parser.error('须先取得当前范围的 V2 批准')
    if args.serve:return serve(args.port,args.data_dir,args.web_root,args.model_settings)
    if not args.browser or not args.browser.is_file() or not args.playwright or not args.playwright.exists():parser.error('请传入已安装的 bundled headless shell 和 Playwright 路径，不自动下载')
    args.output.mkdir(parents=True,exist_ok=True)
    if args.build_web:
        if args.web_root.resolve()!=(ROOT/'frontend/dist').resolve():parser.error('构建仅更新本项目 frontend/dist')
        import zipfile
        backup=args.output/('frontend-before-'+str(uuid4())+'.zip')
        with zipfile.ZipFile(backup,'x',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(args.web_root.rglob('*')):
                if file.is_file():archive.write(file,file.relative_to(ROOT/'frontend'))
        if zipfile.ZipFile(backup).testzip() is not None:raise RuntimeError('页面包备份校验失败')
        build=subprocess.run(['npm','run','build'],cwd=ROOT/'frontend',capture_output=True,text=True,timeout=120)
        (args.output/'build-output.txt').write_text(build.stdout+build.stderr)
        if build.returncode:raise RuntimeError('页面构建失败，原包备份已保留')
    if not (args.web_root/'index.html').is_file():parser.error('须先构建本轮 Web 页面包')
    directory=args.output/('fixture-'+str(uuid4()));directory.mkdir()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--approved-v2','--serve','--port',str(port),
                           '--data-dir',str(directory),'--web-root',str(args.web_root.resolve()),*(['--model-settings'] if args.model_settings else [])],cwd=ROOT,
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    report={'level':'V2','real_pi':True,'provider':'local synthetic OpenAI-compatible stream','external_model_calls':False,
            'data_dir':str(directory),'live_customer_data':False,'human_acceptance':False,'url':url}
    try:
        import httpx
        with httpx.Client(base_url=url,headers={'Origin':url},trust_env=False,timeout=15) as client:
            for _ in range(100):
                try:
                    if client.get('/api/meta').status_code==200:break
                except httpx.RequestError:pass
                if proc.poll() is not None:raise RuntimeError('隔离服务提前退出')
                time.sleep(.1)
            else:raise RuntimeError('隔离服务启动超时')
            session=client.get('/api/session').json();client.headers['X-CSRF-Token']=session['csrf_token']
            event=client.post('/api/scenarios/board-01/import',json={'request_id':str(uuid4())});event.raise_for_status()
            e=event.json();change=client.patch('/api/events/'+e['id'],json={'expected_revision':e['revision'],'title':'V2 模拟董事会议案'});change.raise_for_status()
            report['event_id']=e['id']
            index_response=client.get('/');index_response.raise_for_status()
            html=index_response.text
            if index_response.content!=(args.web_root/'index.html').read_bytes():raise RuntimeError('服务首页与本轮页面包不一致')
            report['served_index_sha256']=hashlib.sha256(index_response.content).hexdigest()
            report['served_assets']=[]
            for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"',html):
                response=client.get(asset);response.raise_for_status()
                local_file=args.web_root/asset.lstrip('/')
                if response.content!=local_file.read_bytes():raise RuntimeError('服务资源与本轮页面包不一致: '+asset)
                report['served_assets'].append({'url':asset,'sha256':hashlib.sha256(response.content).hexdigest(),'matches_local':True})
            if not report['served_assets']:raise RuntimeError('页面未加载本轮构建资源')
            browser=subprocess.run(['node',str(ROOT/'scripts/validate_pi_console_browser.mjs'),url,str(args.output.resolve()),
                                    str(args.browser.resolve()),str(args.playwright.resolve()),*(['settings-only' if args.settings_only else 'model-settings'] if args.model_settings else [])],cwd=ROOT,timeout=240,text=True,capture_output=True)
            (args.output/'browser-output.txt').write_text(browser.stdout+browser.stderr)
            if args.model_settings:report['model_observations']=client.get('/fixture/observations').json()
            if browser.returncode:raise RuntimeError('浏览器检查未通过，见 browser-output.txt')
            report['browser']=json.loads((args.output/'browser-report.json').read_text())
            report['runs']=client.get('/api/chat/runs?board=base').json()
            if args.model_settings:report['model_observations']=client.get('/fixture/observations').json()
            report['status']='passed'
    except Exception as exc:
        report.update(status='failed',error=str(exc));raise
    finally:
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        report['server_stopped']=proc.poll() is not None
        if proc.stderr:
            (args.output/'fixture-stderr.txt').write_text(proc.stderr.read(12000).decode('utf-8',errors='replace'))
            proc.stderr.close()
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'report':str(args.output/'report.json')},ensure_ascii=False))


if __name__=='__main__':main()
