"""Locate an old workspace reference without rewriting historical evidence."""
import argparse
import json
import sys
from pathlib import Path

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from backend import paths


def locate(value,workspace=None,former_root=None):
    workspace=Path(workspace or APP.parent).resolve()
    path=Path(value)
    if path.is_absolute():
        path=path.relative_to(Path(former_root or workspace).resolve())
    relative=paths._normalized(path)
    mapping=json.loads((APP/'config/workspace-layout.json').read_text('utf-8'))
    for row in sorted(mapping['legacy_paths'],key=lambda r:-len(r['from'])):
        if relative==row['from'] or relative.startswith(row['from']+'/'):
            relative=row['to']+relative[len(row['from']):]
            break
    target=workspace/relative
    if not target.resolve().is_relative_to(workspace):
        raise ValueError('引用超出当前工作区')
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='核对历史路径的当前保存位置')
    parser.add_argument('path')
    parser.add_argument('--former-root',type=Path)
    args=parser.parse_args()
    target=locate(args.path,former_root=args.former_root)
    print(json.dumps({'path':str(target),'exists':target.exists()},ensure_ascii=False))
    raise SystemExit(0 if target.exists() else 1)
