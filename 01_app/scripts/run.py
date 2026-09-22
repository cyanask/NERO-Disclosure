"""Serve the approved local Web demo and its API from one loopback origin."""
import argparse
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
from backend.app import create_app
from fastapi.staticfiles import StaticFiles
import uvicorn
from scripts.service_instance import service_instance, exec_restart


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data-dir',type=Path,default=workspace_paths.var(ROOT))
    parser.add_argument('--seed-root',type=Path,default=workspace_paths.knowledge_of(ROOT))
    parser.add_argument('--web-root',type=Path,default=ROOT/'frontend/dist')
    args=parser.parse_args()
    with service_instance(args.data_dir.resolve()) as instance:
        if instance.url:
            print('本项目已在运行：'+instance.url)
            return
        serve(args, instance)


def serve(args, instance):
    from backend.knowledge_packages import load
    load(args.seed_root, ROOT)
    if not 1024<=args.port<=65535:
        raise ValueError('端口应在1024至65535之间')
    directory=args.data_dir.resolve()
    directory.mkdir(parents=True,exist_ok=True)
    dist=args.web_root.resolve()
    if not (dist/'index.html').is_file():
        raise SystemExit('尚无Web静态资源。请先在frontend执行 npm ci 和 npm run build。')
    app=create_app(data_dir=directory,seed_root=args.seed_root.resolve())
    app.mount('/',StaticFiles(directory=dist,html=True),name='workbench')
    print(f'本机演示入口 http://127.0.0.1:{args.port} ，按 Ctrl+C 停止。')
    print('Pi 在网页选择模型并发送后启动；任务与核验由内部工作流处理。')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,log_level='warning',access_log=False))
    restart_requested=False
    def restart():
        nonlocal restart_requested
        restart_requested=True
        server.should_exit=True
    app.state.service_control.restart=restart
    instance.publish(args.port)
    server.run()
    if restart_requested:
        # Uvicorn has drained requests and completed runtime.close() at this point.
        # Re-exec the same interpreter and exact launcher arguments to load new code.
        exec_restart(sys.executable,[sys.executable,str(Path(__file__).resolve()),*sys.argv[1:]],dict(os.environ))


if __name__=='__main__':
    main()
