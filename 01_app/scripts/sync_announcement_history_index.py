#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
from backend.announcement_index import sync
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=workspace_paths.knowledge_of(ROOT));p.add_argument('--board',required=True);p.add_argument('--stock-code',required=True);args=p.parse_args()
print(json.dumps(sync(args.root,args.board,args.stock_code),ensure_ascii=False))
