"""Disposable browser fixture: real HTTP and storage, synthetic provider and official-page bytes."""
import argparse
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from backend.app import create_app
from backend import public_sources
from conftest import isolated_root
from test_pi_runtime import CONFIG
from fastapi.staticfiles import StaticFiles
import uvicorn


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--web-root',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8772)
    args=parser.parse_args()
    if args.port==8765 or args.data_dir.resolve().is_relative_to(ROOT) or args.data_dir.name!='company-browser-fixture':
        raise SystemExit('Only a disposable fixture directory and a non-business port are allowed')
    args.data_dir.mkdir(parents=True,exist_ok=True)
    root=isolated_root(args.data_dir)
    existing=root/'data/client_announcements'
    if existing.exists() and not (root/'data/preserved-client_announcements').exists():
        existing.rename(root/'data/preserved-client_announcements')
    pages={}
    public_sources.search=lambda query,board:{'items':[],'query':query,'coverage':'隔离页面测试，未连接互联网'}
    public_sources.fetch=lambda url,**kwargs:(pages[url].encode(),'text/html',url)
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'})
        if packet['stage']=='company_lookup':
            context=json.loads(packet['system'].rsplit('\n',1)[-1])
            if context['stock_code']=='300997':
                stop.wait(20)
                return
            if context['stock_code']=='300996':
                bridge('submit_candidate',{'status':'needs_review','reason':'隔离测试：公司名称与代码未取得一致的官方依据。'})
                return
            board='innovation' if context['stock_code']=='300999' else 'chinext'
            label='全国股转系统创新层' if board=='innovation' else '深圳证券交易所创业板'
            quote=f"隔离验收样本。公司全称：{context['company_name']}；证券代码：{context['stock_code']}；所属市场：{label}。"
            url='https://www.szse.cn/company-fixture-'+context['stock_code']+'.html'
            pages[url]='<html><body><p>'+quote+'</p></body></html>'
            bridge('company_search',{'query':'当前板块'})
            if stop.wait(2):return
            doc=bridge('company_read',{'url':url})['data']
            bridge('submit_candidate',{'status':'verified','board':board,'reason':'隔离测试已返回匹配的公司资料；此回执不证明真实互联网核实。',
                'sources':[{'download_id':doc['download_id'],'page':1,'quote':quote}]})
        else:
            if packet.get('routeFirst'):
                bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'隔离验收信披咨询'})
            emit({'type':'assistant','message':0,'text':'这是本公司范围内的隔离测试回复，没有调用真实模型。'})
        emit({'type':'done'})
    os.environ['DISCLOSURE_TEST_KEY']='isolated-test-not-a-credential'
    config={**CONFIG,'routes':{'default':'fixture-a'}}
    app=create_app(args.data_dir,root,{'allowed_hosts':['127.0.0.1','localhost']},pi_config=config,pi_runner=runner)
    app.mount('/',StaticFiles(directory=args.web_root,html=True))
    print(json.dumps({'fixture':str(args.data_dir),'url':f'http://127.0.0.1:{args.port}/','live_model':False}),flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning',access_log=False)


if __name__=='__main__':main()
