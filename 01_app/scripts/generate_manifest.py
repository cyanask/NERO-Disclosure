#!/usr/bin/env python3
"""Rebuild BUILD_MANIFEST.json for the source package.

The repository README describes the three data roots. The default ``source`` scope covers the
source package only (code, docs, tests and the delivered frontend bundle). The
legacy ``full`` scope inventories the whole working directory, including the data
and runtime packages that are shipped by folder copy instead of a code baseline.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import paths as workspace_paths
from scripts.release_version import current as released_version
KNOWLEDGE = workspace_paths.knowledge_of(ROOT)
LOCAL = workspace_paths.local_of(ROOT)
LEGACY_EXCLUDE_DIRS = {'.git', '.pytest_cache', '__pycache__', 'var', 'node_modules', '.venv'}
PACKAGE_EXCLUDE_DIRS = LEGACY_EXCLUDE_DIRS | {'data', 'runtime', 'work', 'output',
                                              'design-output', 'exports', 'screenshots', '.playwright-cli'}
EXCLUDE_FILES = {'BUILD_MANIFEST.json', '.DS_Store', 'test_localsystem.txt'}
RUNTIME_SOURCE = ('runtime/pi', 'runtime/windows-x64')


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def inventory(exclude_dirs, base=None):
    """Every file outside the excluded packages, skipping caches and scratch output."""
    base = Path(base or ROOT)
    files = []
    for folder,dirs,names in os.walk(base,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d not in exclude_dirs)
        for name in sorted(names):
            p=Path(folder)/name;rel=p.relative_to(base)
            if not p.is_file() or p.is_symlink():continue
            if name in EXCLUDE_FILES or name.endswith(('.pyc','.log','.tsbuildinfo')):continue
            if name.startswith('.') and name!='.gitignore':continue
            files.append({"path":str(rel),"bytes":p.stat().st_size,"sha256":compute_sha256(p)})
    return files


def main():
    parser = argparse.ArgumentParser(description='重建 BUILD_MANIFEST.json（默认仅源码包）')
    parser.add_argument('--scope', choices=('source', 'full'), default='source',
                        help='source=源码包（默认）；full=含运行包与数据包的整目录清单')
    parser.add_argument('--output', type=Path, default=ROOT / 'BUILD_MANIFEST.json')
    args = parser.parse_args()

    if args.scope == 'source':
        files = inventory(PACKAGE_EXCLUDE_DIRS)
        # Runtime executors and locks are software, even though installed
        # interpreters, node_modules and archives are separate runtime payload.
        extra=[ROOT/'runtime/portable-runtime.lock.tsv']
        for name in RUNTIME_SOURCE:
            extra.extend(p for p in (ROOT/name).glob('*') if p.suffix in ('.py','.mjs','.json','.txt'))
        for p in extra:
            if p.is_file():
                files.append({'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':compute_sha256(p)})
    else:
        # 整目录记录跨三类根：路径以相对工作区的形式登记（01_app/…、02_knowledge/…、03_local/…）。
        files = []
        for base in sorted({ROOT, KNOWLEDGE, LOCAL}):
            prefix = base.relative_to(ROOT.parent).as_posix() + '/' if ROOT.name=='01_app' else ''
            for row in inventory(LEGACY_EXCLUDE_DIRS, base):
                row['path'] = prefix + row['path']
                files.append(row)
        files.sort(key=lambda row: row['path'])

    manifest = {
        "schema_version": "nero.disclosure.manifest.v1",
        "product": "NERO_Disclosure",
        "version": released_version(),
        "scope": args.scope,
        "path_base": "workspace" if args.scope == 'full' and ROOT.name == '01_app' else "app",
        "producer": {
            "name": "NERO",
            "label": "NERO 出品",
            "fingerprint": hashlib.sha256(b"NERO_DISCLOSURE_NEEQ_AUTHOR_NERO").hexdigest()[:16]
        },
        "description": "NERO 信息披露AI系统 Harness（创业板独立知识库；基础层和创新层已外部归档）",
        "files_count": len(files),
        "files": files
    }

    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"Successfully generated BUILD_MANIFEST.json (scope={args.scope}) with {len(files)} files.")


if __name__ == '__main__':
    main()
