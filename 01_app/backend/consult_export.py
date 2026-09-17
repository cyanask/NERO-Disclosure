"""Read-only compatibility for historical consultation exports.

This path renders an already displayed assistant reply into a Word working
draft. It never writes an event, an approval record or a workflow state, and
its files are never presented as a formal disclosure document.
"""
import hashlib
import io
import json
import re
import time
from pathlib import Path
from uuid import uuid4
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt, RGBColor
from fastapi import HTTPException
from .document_content import WordDeliveryError, cells
from .vendor.nero_word import word_primitives as wp
from . import paths as workspace_paths

MAX_TEXT = 200000
MAX_BLOCKS = 600
KIND = 'consult_work_draft'
NOTICE = '咨询工作稿／待复核：来自信披咨询讨论，未经正式披露流程核验，不构成公告或法律意见。'


def directory(root, sid):
    return workspace_paths.work(root) / 'consult-exports' / sid


# Compatibility imports for retained renderer callers; the creation endpoint is retired.
from .document_rendering import layout, render, title_of, verify_rendered_content, clean, blocks_from_text


def displayed_text(runtime, rid, sid):
    """The export must bind to a reply this session actually displayed."""
    run = runtime.store.run(rid)
    if run['session_id'] != sid:
        raise HTTPException(403, '本轮不属于当前会话')
    if run['status'] in ('accepted', 'running', 'cancelling'):
        raise HTTPException(409, '本轮仍在执行，请在答复完整显示后导出')
    if run['stage'] not in ('chat', 'knowledge'):
        raise HTTPException(409, '此入口仅导出咨询或知识库答复；公告制作请使用正文确认入口')
    values = []
    rows = runtime.store.journal(rid)
    while rows:
        for row in rows:
            if row['kind'] == 'assistant' and row['body'].get('text') and row['body'].get('phase') != 'progress' and row['body'].get('stopReason') != 'toolUse':
                values.append(str(row['body']['text']))
        if len(rows) < 1000:
            break
        rows = runtime.store.journal(rid, after=rows[-1]['seq'])
    return run, values


def normalize(value):
    # Only platform line endings and outer blank space may differ. Interior
    # spaces, paragraph boundaries, numbers and table cells bind the approval.
    return str(value).replace('\r\n', '\n').strip()


def create(runtime, sid, body):
    runtime.store.session(sid)
    raise HTTPException(410, '单条回复导出已停用，请在会话中提出 Word 需求')


def safe_name(value):
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', '', str(value)).strip(' .')
    return (cleaned or '咨询工作稿')[:60]


def listing(runtime, sid):
    runtime.store.session(sid)
    folder = directory(runtime.root, sid)
    rows = []
    if folder.is_dir():
        for path in sorted(folder.glob('*.json')):
            try:
                value = json.loads(path.read_text('utf-8'))
            except (OSError, ValueError):
                continue
            if value.get('session_id') == sid and value.get('id') == path.stem:
                rows.append({**value, 'download': f'/api/chat/sessions/{sid}/exports/{value["id"]}/file'})
    return {'kind': KIND, 'items': sorted(rows, key=lambda r: r.get('created_at', ''), reverse=True), 'notice': NOTICE}


def file_path(runtime, sid, export_id):
    if not re.fullmatch(r'[a-f0-9-]{36}', str(export_id)):
        raise HTTPException(422, '导出编号无效')
    runtime.store.session(sid)
    folder = directory(runtime.root, sid)
    receipt = folder / (export_id + '.json')
    if not receipt.is_file():
        raise HTTPException(404, '导出文件不存在')
    value = json.loads(receipt.read_text('utf-8'))
    if value.get('session_id') != sid:
        raise HTTPException(403, '导出记录不属于当前会话')
    target = folder / (value['sha256'] + '.docx')
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != value['sha256']:
        raise HTTPException(409, '导出文件缺失或已变化，请重新导出')
    return target, value['filename']
