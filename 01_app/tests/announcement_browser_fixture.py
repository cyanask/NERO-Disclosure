"""Isolated UI fixture. All company and document content is synthetic."""
import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_announcement_workspace import workspace,upload,commit,docx_bytes
from backend.app import create_app
from fastapi.staticfiles import StaticFiles
import uvicorn

p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--port',type=int,default=8767);args=p.parse_args()
assert str(args.data_dir.resolve()).startswith(('/tmp/','/private/tmp/'))
args.data_dir.mkdir(parents=True,exist_ok=True)
if not (args.data_dir/'data/public/boards/chinext/catalog.json').exists():
    setup=workspace.__wrapped__(args.data_dir);c,root,_=next(setup)
    result=commit(c,upload(c));assert result.status_code==200,result.text
    (root/'ui-upload.docx').write_bytes(docx_bytes(title='第三届董事会第三次会议决议公告',day='2025年6月5日'))
    try:next(setup)
    except StopIteration:pass
app=create_app(args.data_dir/'var',args.data_dir,{'allowed_hosts':['localhost','127.0.0.1','testserver']})
app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True))
uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
