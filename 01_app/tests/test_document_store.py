"""Focused document-store contracts using an isolated ChatStore and synthetic bytes."""
import json
from pathlib import Path
from types import SimpleNamespace
from threading import RLock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import document_store
from backend.chat_store import ChatStore


def make_runtime(tmp_path):
    return SimpleNamespace(
        local_root=tmp_path,
        store=ChatStore(tmp_path / 'conversations.sqlite3'),
        lock=RLock(),
    )


def session(runtime, title='存储合同测试'):
    return runtime.store.create_session('chinext', None, title, str(uuid4()))


def word(title, raw, **values):
    return {'title': title, 'kind': 'analysis', 'raw': raw,
            'snapshot': {'text': title + ' 快照'}, **values}


def text(title, **values):
    return {'title': title, 'kind': 'announcement', 'raw': None,
            'snapshot': {'text': title + ' 正文'}, **values}


def test_listing_reads_index_once_and_text_snapshot_once(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    current = session(runtime)
    document_store.publish(runtime, current['id'], [word('Word', b'synthetic-word'), text('正文')], 0)
    index = document_store.load(runtime, current['id'])
    text_row = next(row for row in index['documents'][1]['versions'] if row['version'] == 1)
    snapshot_path = document_store.folder(runtime, current['id']) / (text_row['snapshot_sha256'] + '.json')

    loads = []
    original_load = document_store.load

    def counted_load(runtime_arg, sid):
        loads.append((runtime_arg, sid))
        return original_load(runtime_arg, sid)

    reads = []
    original_read_bytes = Path.read_bytes

    def counted_read_bytes(path):
        if path == snapshot_path:
            reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(document_store, 'load', counted_load)
    monkeypatch.setattr(Path, 'read_bytes', counted_read_bytes)
    result = document_store.listing(runtime, current['id'])

    assert len(loads) == 1
    assert reads == [snapshot_path]
    assert result['items'][1]['available'] is True
    assert result['items'][1]['text'] == '正文 正文'


def test_mixed_versions_history_scope_archive_and_unavailable_state(tmp_path):
    runtime = make_runtime(tmp_path)
    own = session(runtime, '当前会话')
    other = session(runtime, '其他会话')
    first = document_store.publish(runtime, own['id'], [word('报告', b'v1'), text('正文')], 0)
    revised = document_store.publish(runtime, own['id'], [word('报告', b'v2', document_id=first[0]['document_id'], base_version=1)], 1)
    foreign = document_store.publish(runtime, other['id'], [word('外部', b'other')], 0)[0]

    current = document_store.listing(runtime, own['id'])['items']
    report = next(item for item in current if item['document_id'] == first[0]['document_id'])
    body = next(item for item in current if item['document_id'] == first[1]['document_id'])
    assert report['version'] == 2 and [row['version'] for row in report['history']] == [2, 1]
    assert body['available'] is True and body['text'] == '正文 正文'
    assert document_store.version(runtime, own['id'], report['document_id'], 1)['sha256'] == first[0]['sha256']
    path, row = document_store.file(runtime, own['id'], report['document_id'], 1)
    assert path.read_bytes() == b'v1' and row['version'] == 1
    assert document_store.snapshot(runtime, own['id'], body['document_id'], 1)['text'] == '正文 正文'

    runtime.store.edit_session(own['id'], archived=True)
    assert document_store.listing(runtime, own['id'])['items'][0]['version'] == 2

    own_root = document_store.folder(runtime, own['id'])
    (own_root / (revised[0]['sha256'] + '.docx')).write_bytes(b'tampered')
    (own_root / (first[1]['snapshot_sha256'] + '.json')).unlink()
    unavailable = document_store.listing(runtime, own['id'])['items']
    assert next(item for item in unavailable if item['document_id'] == report['document_id'])['available'] is False
    assert next(item for item in unavailable if item['document_id'] == body['document_id'])['available'] is False

    with pytest.raises(HTTPException) as error:
        document_store.file(runtime, own['id'], foreign['document_id'])
    assert error.value.status_code == 404


def test_corrupt_index_fails_closed(tmp_path):
    runtime = make_runtime(tmp_path)
    current = session(runtime)
    document_store.publish(runtime, current['id'], [word('报告', b'v1')], 0)
    document_store.folder(runtime, current['id']).joinpath('index.json').write_text('{broken', encoding='utf-8')

    with pytest.raises(HTTPException) as error:
        document_store.listing(runtime, current['id'])
    assert error.value.status_code == 409


def test_snapshot_with_matching_hash_but_invalid_json_is_unavailable(tmp_path):
    runtime = make_runtime(tmp_path)
    current = session(runtime)
    saved = document_store.publish(runtime, current['id'], [text('正文')], 0)[0]
    base = document_store.folder(runtime, current['id'])
    invalid = b'{broken-json'
    snapshot_path = base / (saved['snapshot_sha256'] + '.json')
    invalid_path = base / (document_store.sha(invalid) + '.json')
    snapshot_path.rename(invalid_path)
    invalid_path.write_bytes(invalid)
    index = document_store.load(runtime, current['id'])
    index['documents'][0]['versions'][0]['snapshot_sha256'] = document_store.sha(invalid)
    (base / 'index.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')

    listed = document_store.listing(runtime, current['id'])['items'][0]
    assert listed['available'] is False and listed['text'] is None
    with pytest.raises(HTTPException, match='文稿快照内容无效'):
        document_store.snapshot(runtime, current['id'], saved['document_id'])


def test_file_and_snapshot_symlinks_are_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    current = session(runtime)
    saved_word, saved_text = document_store.publish(runtime, current['id'], [word('Word', b'word'), text('正文')], 0)
    base = document_store.folder(runtime, current['id'])
    word_path = base / (saved_word['sha256'] + '.docx')
    snapshot_path = base / (saved_text['snapshot_sha256'] + '.json')
    word_bytes = word_path.read_bytes()
    snapshot_bytes = snapshot_path.read_bytes()
    outside_word = tmp_path / 'outside-word'
    outside_snapshot = tmp_path / 'outside-snapshot'
    outside_word.write_bytes(word_bytes)
    outside_snapshot.write_bytes(snapshot_bytes)
    word_path.unlink()
    snapshot_path.unlink()
    try:
        word_path.symlink_to(outside_word)
        snapshot_path.symlink_to(outside_snapshot)
    except OSError:
        pytest.skip('当前测试环境不支持创建符号链接')

    listed = document_store.listing(runtime, current['id'])['items']
    assert all(item['available'] is False for item in listed)
    with pytest.raises(HTTPException) as file_error:
        document_store.file(runtime, current['id'], saved_word['document_id'])
    with pytest.raises(HTTPException) as snapshot_error:
        document_store.snapshot(runtime, current['id'], saved_text['document_id'])
    assert file_error.value.status_code == snapshot_error.value.status_code == 409
