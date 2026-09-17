"""Explicit knowledge ownership; no inference from a source ID or market label."""
from fastapi import HTTPException

BOARDS = [
    {'id':'sse-main','name':'上交所主板','available':False},
    {'id':'star','name':'科创板','available':False},
    {'id':'szse-main','name':'深交所主板','available':False},
    {'id':'chinext','name':'创业板','available':True},
    {'id':'bse','name':'北交所','available':False},
    {'id':'innovation','name':'创新层','available':False},
    {'id':'base','name':'基础层','available':False},
]

ACTIVE_BOARDS = frozenset(board['id'] for board in BOARDS if board['available'])
ARCHIVED_BOARDS = frozenset(('base', 'innovation'))


def require_board(board):
    if board is None:
        raise HTTPException(422,'请指定知识库所属板块 board：chinext')
    match = next((b for b in BOARDS if b['id']==board),None)
    if match is None:
        raise HTTPException(422,'板块编号无效')
    if not match['available']:
        if board in ARCHIVED_BOARDS:
            raise HTTPException(409,'基础层和创新层知识库已归档；当前工作区仅开放创业板')
        raise HTTPException(409,'该板块暂不可用')
    return board
