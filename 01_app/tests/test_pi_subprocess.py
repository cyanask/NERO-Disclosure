"""Runner seam: spawn, non-blocking line reads, bounded shutdown."""
import json
import queue
import sys
import time
from pathlib import Path
import pytest
from fastapi import HTTPException
from backend import pi_subprocess

CHILD = """
import json, sys, time
for line in sys.stdin:
    item = json.loads(line)
    if item.get('op') == 'echo':
        print(json.dumps({'type': 'echo', 'value': item['value']}, ensure_ascii=False), flush=True)
    elif item.get('op') == 'sleep':
        time.sleep(item.get('seconds', 30))
        print(json.dumps({'type': 'done'}), flush=True)
"""


def child(tmp_path, **extra):
    script = tmp_path / 'child.py'
    script.write_text(CHILD)
    return pi_subprocess.Session([sys.executable, str(script)], tmp_path, env=extra)


def test_round_trip_reads_one_json_line_per_send(tmp_path):
    session = child(tmp_path)
    try:
        session.send({'op': 'echo', 'value': '第一行'})
        assert json.loads(session.read(timeout=5)) == {'type': 'echo', 'value': '第一行'}
        session.send({'op': 'echo', 'value': 'second'})
        assert json.loads(session.read(timeout=5))['value'] == 'second'
    finally:
        session.close()


def test_silent_child_times_out_instead_of_blocking_the_caller(tmp_path):
    session = child(tmp_path)
    try:
        with pytest.raises(queue.Empty):
            session.read(timeout=.1)
        assert session.live()
    finally:
        session.close()


def test_close_reports_eof_and_ends_a_sleeping_child(tmp_path):
    session = child(tmp_path)
    session.send({'op': 'sleep', 'seconds': 30})
    started = time.monotonic()
    session.close()
    assert session.read(timeout=1) is None and not session.live()
    assert time.monotonic() - started < pi_subprocess.KILL_GRACE * 2


def test_finished_child_is_not_left_running_and_pipes_are_closed(tmp_path):
    session = child(tmp_path)
    session.send({'op': 'echo', 'value': 'x'})
    session.read(timeout=5)
    session.close()
    assert session.returncode is not None and session.process.stdout.closed


def test_child_env_passes_runtime_variables_only(tmp_path, monkeypatch):
    monkeypatch.setenv('PATH', '/usr/bin')
    monkeypatch.setenv('OPENAI_API_KEY', 'secret-value')
    monkeypatch.delenv('PYTHONUTF8', raising=False)
    env = pi_subprocess.child_env({'PI_NO_OAUTH': '1'})
    assert env['PATH'] == '/usr/bin' and env['PI_NO_OAUTH'] == '1' and env['PYTHONUTF8']=='1'
    assert 'OPENAI_API_KEY' not in env


def test_node_path_reports_a_missing_runtime(monkeypatch):
    monkeypatch.setattr(pi_subprocess.shutil, 'which', lambda name: None)
    with pytest.raises(HTTPException):
        pi_subprocess.node_path()
