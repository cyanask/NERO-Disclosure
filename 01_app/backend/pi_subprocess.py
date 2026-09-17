"""One bounded child process for Pi work: filtered env, line reader, ordered shutdown.

Main model rounds, semantic review, Word production and model-control commands all
need the same four things: a vendor-neutral child environment, a reader that never
blocks the caller, a bounded wait, and terminate-then-kill escalation. This module
owns those; each caller keeps only its own protocol.
"""
import json
import os
import queue
import shutil
import subprocess
import threading
from fastapi import HTTPException

SAFE_ENV=('PATH','SYSTEMROOT','WINDIR','TMPDIR','TEMP','TMP','LANG','SSL_CERT_FILE','NODE_EXTRA_CA_CERTS',
          'NERO_DISCLOSURE_HOME','PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE','PYTHONUTF8')
KILL_GRACE=3.0


def child_env(extra=None):
    """Pass only the variables a worker needs; provider keys and host credentials stay out."""
    env={k:v for k,v in os.environ.items() if k in SAFE_ENV}
    env.update(extra or {})
    env['PYTHONUTF8']='1'
    return env


def node_path():
    node=shutil.which('node')
    if not node:raise HTTPException(409,'Node 尚未就绪')
    return node


class Session:
    """A child process with a non-blocking line reader and one shutdown path."""

    def __init__(self,argv,cwd,env=None,max_line=9000000):
        self.process=subprocess.Popen([str(part) for part in argv],cwd=str(cwd),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,env=child_env(env))
        self.max_line=max_line
        self._send_lock=threading.Lock()
        self._lines=queue.Queue()
        self._reader=threading.Thread(target=self._read,daemon=True);self._reader.start()

    def _read(self):
        try:
            while line:=self.process.stdout.readline(self.max_line):self._lines.put(line)
        finally:self._lines.put(None)

    @property
    def pid(self):
        return self.process.pid

    @property
    def returncode(self):
        return self.process.returncode

    def poll(self):
        return self.process.poll()

    def live(self):
        return self.process.poll() is None

    def send(self,payload):
        """One JSON request line per call."""
        with self._send_lock:
            self.process.stdin.write(json.dumps(payload,ensure_ascii=False)+'\n');self.process.stdin.flush()

    def read(self,timeout=.2):
        """Next raw line; None means the child closed stdout, queue.Empty means still running."""
        return self._lines.get(timeout=timeout)

    def wait(self,timeout=KILL_GRACE):
        return self.process.wait(timeout=timeout)

    def terminate(self):
        """Terminate, then kill after the grace period. Safe to call from a timer thread."""
        if self.process.poll() is None:self.process.terminate()
        try:self.process.wait(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=KILL_GRACE)

    def close(self):
        """Always terminate, close both pipes and join the reader."""
        try:
            self.terminate()
        finally:
            for pipe in (self.process.stdin,self.process.stdout):
                if pipe:pipe.close()
            self._reader.join(timeout=1)
