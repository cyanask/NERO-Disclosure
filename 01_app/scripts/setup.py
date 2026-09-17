"""Prepare local storage. This application has no user/password initialization."""
import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths

def initialize(directory:Path) -> None:
    directory.mkdir(parents=True,exist_ok=True)
    print('本地存储已准备；免登录，所有流转由 Verify/Gate 控制。')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,default=workspace_paths.var(ROOT))
    initialize(parser.parse_args().data_dir.resolve())
