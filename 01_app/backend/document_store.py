"""Session-scoped document versions. These records never advance business gates."""
import hashlib
import json
import re
import time
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .public_store import atomic


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def folder(runtime, sid):
    runtime.store.session(sid)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', sid):
        raise HTTPException(422, '会话编号无效')
    target = runtime.local_root / 'work' / 'documents' / sid
    for parent in (target, *target.parents):
        if parent.is_symlink():
            raise HTTPException(409, '文档目录不能使用符号链接')
        if parent == runtime.local_root:
            break
    return target


def load(runtime, sid):
    path = folder(runtime, sid) / 'index.json'
    if path.is_symlink():
        raise HTTPException(409, '文档版本记录不能使用符号链接')
    if not path.exists():
        return {'revision': 0, 'documents': []}
    try:
        value = json.loads(path.read_text('utf-8'))
        if not isinstance(value['documents'], list) or not isinstance(value['revision'], int):
            raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(409, '文档版本记录无法读取，未覆盖原记录') from None


def version(runtime, sid, document_id, number=None):
    document = next((d for d in load(runtime, sid)['documents'] if d['id'] == document_id), None)
    if not document:
        raise HTTPException(404, '文档不属于当前会话')
    row = next((v for v in document['versions'] if v['version'] == (number or document['current_version'])), None)
    if not row:
        raise HTTPException(404, '文档版本不存在')
    return row


def file(runtime, sid, document_id, number=None):
    row = version(runtime, sid, document_id, number)
    if row.get('format','docx')=='text':
        raise HTTPException(409,'当前版本是公告正文，可随时要求制作 Word')
    if not re.fullmatch(r'[a-f0-9]{64}', str(row.get('sha256', ''))):
        raise HTTPException(409, '文档文件标识无效')
    target = folder(runtime, sid) / (row['sha256'] + '.docx')
    if target.is_symlink() or not target.is_file() or sha(target.read_bytes()) != row['sha256']:
        raise HTTPException(409, '文档文件缺失或内容已变化，不能作为当前版本使用')
    return target, row


def snapshot(runtime, sid, document_id, number=None):
    row = version(runtime, sid, document_id, number)
    if not re.fullmatch(r'[a-f0-9]{64}', str(row.get('snapshot_sha256', ''))):
        raise HTTPException(409, '文稿快照标识无效')
    path = folder(runtime, sid) / (row['snapshot_sha256'] + '.json')
    if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != row['snapshot_sha256']:
        raise HTTPException(409, '文稿快照缺失或内容已变化')
    return json.loads(path.read_text('utf-8'))


def public_version(sid, row):
    return {**row, 'format':row.get('format','docx'),
            'download': f'/api/chat/sessions/{sid}/documents/{row["document_id"]}/versions/{row["version"]}/file' if row.get('format','docx')=='docx' else None}


def listing(runtime, sid):
    index = load(runtime, sid)
    items = []
    for document in index['documents']:
        row = version(runtime, sid, document['id'])
        try:
            if row.get('format','docx')=='text':snapshot(runtime,sid,document['id'],row['version'])
            else:file(runtime, sid, document['id'],row['version'])
            available = True
        except HTTPException:
            available = False
        items.append({**public_version(sid, row), 'available': available,
                      'text':snapshot(runtime,sid,document['id'],row['version'])['text'] if row.get('format')=='text' and available else None,
                      'history': [public_version(sid, v) for v in reversed(document['versions'])]})
    return {'revision': index['revision'], 'items': items}


def publish(runtime, sid, prepared, expected_revision, stop=None):
    """Publish a complete batch atomically after all files pass their checks."""
    with runtime.lock:
        index = load(runtime, sid)
        if index['revision'] != expected_revision:
            raise HTTPException(409, '当前文档已有新版本，请读取最新文稿后继续')
        if runtime.store.session(sid)['archived']:
            raise HTTPException(409, '会话已归档，不能生成文档')
        if stop and stop.is_set():
            raise HTTPException(409, '已停止制作，未登记新版本')
        base = folder(runtime, sid)
        base.mkdir(parents=True, exist_ok=True)
        result = []
        for item in prepared:
            identity = item.get('document_id') or uuid4().hex
            document = next((d for d in index['documents'] if d['id'] == identity), None)
            if item.get('document_id') and not document:
                raise HTTPException(404, '修改对象不属于当前会话')
            if document and item.get('base_version') != document['current_version']:
                raise HTTPException(409, '修改基于旧稿，未覆盖当前版本')
            if not document:
                document = {'id': identity, 'current_version': 0, 'versions': []}
                index['documents'].append(document)
            raw = item.get('raw')
            snap = json.dumps(item['snapshot'], ensure_ascii=False, sort_keys=True).encode()
            raw_sha, snap_sha = sha(raw if raw is not None else item['snapshot']['text'].encode()), sha(snap)
            files=[(snap_sha+'.json',snap)]
            if raw is not None:files.append((raw_sha+'.docx',raw))
            for name, content in files:
                target = base / name
                if target.exists():
                    if target.is_symlink() or target.read_bytes() != content:
                        raise HTTPException(409, '已有文档版本内容异常，未覆盖')
                else:
                    atomic(target, content)
            number = document['current_version'] + 1
            row = {'document_id': identity, 'version': number, 'title': item['title'],
                   'filename': re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', item['title'])[:100] + '.docx',
                   'kind': item['kind'], 'source_type': item.get('source_type', 'runtime'),
                   'run_id': item.get('run_id'), 'created': time.time(),
                   'sha256': raw_sha, 'bytes': len(raw) if raw is not None else len(item['snapshot']['text'].encode()), 'snapshot_sha256': snap_sha,
                   'format':'docx' if raw is not None else 'text',
                   'parent_sha256': document['versions'][-1]['sha256'] if document['versions'] else None,
                   'template_id': item.get('template_id'), 'template_name': item.get('template_name'),
                   'pending': item.get('pending', []), 'warnings':item.get('warnings',[]), 'checks': item.get('checks', {}),
                   'review_status': 'pending', 'reviews': []}
            document['current_version'] = number
            document['versions'].append(row)
            result.append(public_version(sid, row))
        if stop and stop.is_set():
            raise HTTPException(409, '已停止制作，未登记新版本')
        index['revision'] += 1
        atomic(base / 'index.json', (json.dumps(index, ensure_ascii=False, indent=2) + '\n').encode())
        return result


def review(runtime, sid, document_id, body):
    with runtime.lock:
        if runtime.store.session(sid)['archived']:
            raise HTTPException(409, '已归档会话不能修改文档审阅记录')
        index = load(runtime, sid)
        document = next((d for d in index['documents'] if d['id'] == document_id), None)
        if not document or document['current_version'] != body.get('version'):
            raise HTTPException(409, '当前文档版本已变化，请重新审阅')
        row = document['versions'][-1]
        text_only=row.get('format','docx')=='text'
        if text_only:snapshot(runtime,sid,document_id,row['version'])
        else:file(runtime, sid, document_id,row['version'])
        if row['sha256'] != body.get('sha256'):
            raise HTTPException(409, '审阅文件与当前版本不一致')
        decision = body.get('decision')
        if decision not in ('accepted', 'needs_revision'):
            raise HTTPException(422, '文档审阅决定无效')
        if decision == 'accepted' and (body.get('content_reviewed') is not True or not text_only and body.get('visual_reviewed') is not True):
            raise HTTPException(422, '请审阅当前文件的内容和版式后确认')
        if decision == 'accepted' and row.get('pending') and not text_only:
            raise HTTPException(409, '当前文稿仍有待补事项，请先补齐后定稿')
        row['review_status'] = decision
        row['reviews'].append({'decision': decision, 'at': time.time(), 'actor': '本机使用者',
                               'sha256': row['sha256'], 'content_reviewed': body.get('content_reviewed') is True,
                               'visual_reviewed': body.get('visual_reviewed') is True,
                               **({k:body[k] for k in ('source_run_id','source_message_seq')} if body.get('source_run_id') else {})})
        index['revision'] += 1
        atomic(folder(runtime, sid) / 'index.json', (json.dumps(index, ensure_ascii=False, indent=2) + '\n').encode())
        return public_version(sid, row)
