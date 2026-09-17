"""Validate and atomically update law records; original and text hashes differ."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
from backend.library_admin import state, update
from fastapi import HTTPException


def main():
    parser=argparse.ArgumentParser(description='法律库版本维护；保留原件、旧版本及校验记录')
    parser.add_argument('--root',type=Path,default=workspace_paths.knowledge_of(ROOT))
    parser.add_argument('--board',required=True,choices=['base','innovation','chinext'])
    sub=parser.add_subparsers(dest='command',required=True)
    add=sub.add_parser('add')
    for name in ('inst','article','title','text'):add.add_argument('--'+name,required=True)
    for name in ('url','effective-from','effective-to','as-of'):add.add_argument('--'+name)
    batch=sub.add_parser('import');batch.add_argument('file',type=Path)
    sub.add_parser('sync')
    args=parser.parse_args()
    try:
        if args.command=='sync':
            from scripts.sync_sqlite_library import sync_library_db
            print(json.dumps({'status':'indexed','counts':sync_library_db(root=args.root,board=args.board)},ensure_ascii=False));return 0
        current=state(args.root,'laws',board=args.board)
        if args.command=='import':
            items=json.loads(args.file.read_text('utf-8'))
            if not isinstance(items,list):raise ValueError('导入文件须为 JSON 数组')
        else:
            number=args.article.removeprefix('a')
            row={'id':f'{args.inst}-a{number}','instrument_id':args.inst,'article':'第'+number+'条',
                 'title':args.title,'text':args.text,'source_kind':'official_rule','layers':[args.board],'library_board':args.board}
            for key in ('url','effective_from','effective_to','as_of'):
                if getattr(args,key) is not None:row[key]=getattr(args,key)
            items=[row]
        result=update(args.root,'laws',items,current['fingerprint'],board=args.board)
        print(json.dumps(result,ensure_ascii=False));return 0
    except (HTTPException,ValueError,OSError) as exc:
        print(json.dumps({'status':'failed','detail':getattr(exc,'detail',str(exc))},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
