"""Verify portable file bytes on any OS; never claims Windows execution."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runtime/windows-x64'


def verify(base=BASE):
    base=Path(base);issues=[]
    manifest=json.loads((base/'bundle.json').read_text('utf-8'))
    for row in manifest['files']:
        p=(base/row['path']).resolve()
        if not p.is_relative_to(base.resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:
            issues.append(row['path'])
    lock=json.loads((base/'runtime.lock.json').read_text('utf-8'))
    for name in ('python','uv'):
        p=base/'downloads'/(name+'.zip')
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=lock[name+'_sha256']:issues.append(name+'_download_hash')
    return {'status':'passed' if not issues else 'failed','files_checked':len(manifest['files']),'mismatches':issues,
            'windows_execution_verified':False,'boundary':'仅核对文件与来源哈希；Windows实际运行由本机doctor另行验证。'}


if __name__=='__main__':
    result=verify();print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['status']=='passed' else 1)
