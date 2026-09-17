"""Canonical public-library locations, atomic writes and the board update lock.

Leaf module: it must not import backend.domain, backend.library or
backend.announcement_history. Those modules share this storage boundary, and
keeping it here lets them do so without import cycles.
"""
import hashlib
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from .boards import require_board

_LOCK = threading.RLock()


def board_dir(root, board):
    """Canonical manifest directory for one board."""
    return Path(root)/'data/public/boards'/require_board(board)


def template_dir(root, board):
    """Retained template directory for one board."""
    return Path(root)/'templates/boards'/require_board(board)


def sha(raw):return hashlib.sha256(raw).hexdigest()


@contextmanager
def locked(root,board):
    with _LOCK:
        path=board_dir(root,board)/'.library-update.lock'
        with path.open('a+b') as stream:
            if os.name=='nt':
                import msvcrt
                stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
                msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX)
            try:yield
            finally:
                if os.name=='nt':
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream,fcntl.LOCK_UN)




def atomic(path,raw):
    path=Path(path)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)




def official_url(value):
    if not isinstance(value,str):return False
    try:u=urlsplit(value or '')
    except ValueError:return False
    host=(u.hostname or '').lower()
    return u.scheme=='https' and not u.username and not u.password and any(host==d or host.endswith('.'+d) for d in ('gov.cn','neeq.com.cn','neeq.cc','sse.com.cn','szse.cn','bse.cn','cninfo.com.cn'))
