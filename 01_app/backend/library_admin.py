"""Canonical library commit protocol and read view.

Writes take the per-board lock, check the manifest fingerprint, snapshot the
previous bytes and replace the manifest atomically before rebuilding
projections. Row rules and projections live in ``library_write``; this module
keeps the historical import path used by the API, workspace, ingestion,
lifecycle and template callers.
"""
import copy
import json
from pathlib import Path
from fastapi import HTTPException
from .domain import Seeds
from .library_write import COLLECTIONS, checked_rows, rebuild_index, rebuild_profile_projections, validate, validate_change
from .public_store import atomic, locked, official_url, sha, template_dir


def state(root, collection, board=None):
    seeds=Seeds(root).for_board(board)
    if collection not in COLLECTIONS:raise HTTPException(422,'资料库无效')
    name,key=COLLECTIONS[collection];path=seeds.public_dir/name;raw=path.read_bytes()
    data=json.loads(raw)
    return {'board':board,'collection':collection,'fingerprint':sha(raw),'items':checked_rows(data,key,board)}


def update(root,collection,items,expected_fingerprint,board=None):
    root=Path(root)
    seeds=Seeds(root).for_board(board)
    if collection not in COLLECTIONS or not items or len(items)>200:raise HTTPException(422,'资料库或更新数量无效')
    with locked(root,board):
        name,key=COLLECTIONS[collection];path=seeds.public_dir/name;old=path.read_bytes()
        if sha(old)!=expected_fingerprint:raise HTTPException(409,'资料库版本已变化，请重新读取后比较')
        document=json.loads(old);rows=checked_rows(document,key,board)
        # Validate the complete batch before any canonical or index write.
        incoming=[x.get('id') for x in items if isinstance(x,dict) and isinstance(x.get('id'),str)]
        if len(incoming)!=len(items) or len(set(incoming))!=len(incoming):raise HTTPException(422,'更新条目 id 重复或无效')
        existing={s['id']:s for s in rows}
        catalog=json.loads((seeds.public_dir/'catalog.json').read_text())
        profiles=json.loads((seeds.public_dir/'profiles.json').read_text())
        for item in items:
            previous=existing.get(item['id']);merged={**copy.deepcopy(previous or {}),**item}
            try:existing[item['id']]=validate(root,collection,merged,previous,catalog,profiles,board)
            except (TypeError,ValueError,KeyError,OSError):raise HTTPException(422,'资料字段或原件结构无效，未写入更新')
        revised=list(existing.values())
        if key:document[key]=revised
        else:document=revised
        raw=(json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode()
        history=seeds.public_dir/'history';history.mkdir(exist_ok=True)
        backup=history/(name.removesuffix('.json')+'-'+sha(old)+'.json')
        if backup.exists():
            if backup.read_bytes()!=old:raise HTTPException(409,'资料历史快照校验失败')
        else:
            with backup.open('xb') as stream:stream.write(old)
        atomic(path,raw)
        # Committed canonical truth first; rebuildable projections never turn a
        # committed edit into a failure.
        warnings=rebuild_profile_projections(seeds,collection,revised)
        rebuild_index(root,board,warnings,'目录索引待重建；当前检索继续读取已提交的 JSON 真源')
        return {'status':'updated','board':board,'collection':collection,'fingerprint':sha(raw),'updated_ids':incoming,
                'previous_fingerprint':sha(old),'history':str(backup.relative_to(root)),
                'projection_warnings':list(dict.fromkeys(warnings))}


def remove(root,collection,ids,expected_fingerprint,board=None):
    """Delete selected active rows; preserve prior evidence versions for existing references."""
    root=Path(root);seeds=Seeds(root).for_board(board)
    if collection not in COLLECTIONS or not isinstance(ids,list) or not ids or len(ids)>200:raise HTTPException(422,'删除对象无效')
    with locked(root,board):
        name,key=COLLECTIONS[collection];path=seeds.public_dir/name;old=path.read_bytes()
        if sha(old)!=expected_fingerprint:raise HTTPException(409,'知识库已变化，请重新预览删除范围')
        doc=json.loads(old);rows=checked_rows(doc,key,board);known={r['id'] for r in rows}
        if len(set(ids))!=len(ids) or not set(ids)<=known:raise HTTPException(409,'部分待删除对象不存在')
        kept=[r for r in rows if r['id'] not in ids]
        if key:doc[key]=kept
        else:doc=kept
        history=seeds.public_dir/'history';history.mkdir(exist_ok=True)
        archive=history/(name.removesuffix('.json')+'-'+sha(old)+'.json')
        if not archive.exists():atomic(archive,old)
        template_manifest=None;template_old=None
        warnings=[]
        if collection=='profiles':
            template_manifest=seeds.template_dir/'manifest.json';template_old=template_manifest.read_bytes()
            templates=json.loads(template_old);remaining=[r for r in templates if r.get('profile_id') not in ids]
            template_history=seeds.template_dir/'history';template_history.mkdir(exist_ok=True)
            atomic(template_history/('manifest-'+sha(template_old)+'.json'),template_old)
            atomic(template_manifest,(json.dumps(remaining,ensure_ascii=False,indent=2)+'\n').encode())
        try:atomic(path,(json.dumps(doc,ensure_ascii=False,indent=2)+'\n').encode())
        except Exception:
            if template_manifest is not None:atomic(template_manifest,template_old)
            raise
        if collection=='profiles':
            profile_dir=seeds.public_dir/'profiles'
            for identity in ids:
                candidate=profile_dir/(identity+'.json')
                try:
                    current=Path(seeds.root)
                    if current.is_symlink():raise OSError('资料投影根目录含符号链接')
                    relative=profile_dir.relative_to(current)
                    for part in relative.parts:
                        current=current/part
                        if current.is_symlink():raise OSError('资料投影目录链含符号链接')
                    if candidate.parent!=profile_dir or candidate.resolve(strict=False).parent!=profile_dir.resolve():
                        raise OSError('资料投影路径越界')
                    if candidate.is_symlink():raise OSError('资料投影文件是符号链接')
                    if candidate.exists() and not candidate.is_file():raise OSError('资料投影文件不是普通文件')
                    if candidate.is_file():candidate.unlink()
                except (OSError,ValueError):
                    warnings.append('文种独立文件投影待重建')
        rebuild_index(root,board,warnings,'派生索引待重建；检索真源已更新')
        return {'status':'deleted','deleted_ids':ids,'fingerprint':sha(path.read_bytes()),'history':str(archive.relative_to(root)),'projection_warnings':warnings}
