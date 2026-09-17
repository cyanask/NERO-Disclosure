#!/usr/bin/env python3
"""Verify a copied NERO_Disclosure directory against its release manifest.

This checks file identity (path/bytes/SHA-256) recorded in BUILD_MANIFEST.json.
It proves the directory matches the NERO-published version, not legal content.
The default source scope covers the source package only; the runtime package,
the data package and generated caches stay outside it (see docs/PACKAGE_BOUNDARY.md)
and are therefore not checked here.
"""
import hashlib
import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser=argparse.ArgumentParser(description='核对指定发布清单，不改写历史回执')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--manifest',type=Path)
    args=parser.parse_args()
    root=args.root.resolve()
    manifest_path=args.manifest or root/'BUILD_MANIFEST.json'
    if not manifest_path.is_file():
        print(json.dumps({"verified": False, "error": "BUILD_MANIFEST.json 缺失"}, ensure_ascii=False))
        return 2
    try:
        manifest = json.loads(manifest_path.read_text("utf-8"))
        rows=manifest['files']
        if not isinstance(rows,list) or not rows or manifest.get('files_count')!=len(rows):raise ValueError('清单为空或文件数量不符')
        if len({row['path'] for row in rows})!=len(rows):raise ValueError('清单路径重复')
        for row in rows:
            if not isinstance(row['path'],str) or Path(row['path']).is_absolute() or '..' in Path(row['path']).parts:raise ValueError('清单路径无效')
            if not isinstance(row['bytes'],int) or row['bytes']<0 or not isinstance(row['sha256'],str) or len(row['sha256'])!=64:raise ValueError('清单字段无效')
    except (KeyError,TypeError,ValueError) as exc:
        print(json.dumps({'verified':False,'error':'发布清单无效：'+str(exc)},ensure_ascii=False));return 2
    producer = manifest.get("producer", {})
    version = manifest.get("version", "")
    product = manifest.get("product", "")
    scope = manifest.get("scope", "legacy-full")
    if manifest.get('path_base')=='workspace' and root.name=='01_app':
        root=root.parent
    mismatches = []
    checked = 0
    for row in manifest.get("files", []):
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            mismatches.append(row["path"])
            continue
        checked += 1
        if path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            mismatches.append(row["path"])
    result = {
        "verified": not mismatches,
        "scope": scope,
        "producer": producer.get("name", "NERO"),
        "producer_label": producer.get("label", "NERO 出品"),
        "product": product,
        "version": version,
        "files_checked": checked,
        "files_recorded": len(manifest.get("files", [])),
        "mismatches": mismatches[:20],
        "boundary": "完整性指纹不等于密码学签名；如需防伪签章应使用 NERO 受控密钥对清单摘要签名并提供公钥验证。",
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
