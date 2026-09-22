"""Restart handover must survive this workspace's own TIME_WAIT sockets.

A restart stops the old server and immediately binds the same port again. The
connections the browser had open leave TIME_WAIT sockets behind, and a bare
bind() reports them as an occupied port, so the handover used to fail until the
kernel dropped them.
"""
import socket

import pytest

pytest.importorskip('fcntl')

from scripts import portable_runtime as setup
from scripts.macos_desktop import listen


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def listener(port):
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port))
    server.listen(8)
    return server


def test_restart_handover_survives_our_own_time_wait_sockets():
    port = free_port()
    server = listener(port)
    client = socket.create_connection(('127.0.0.1', port))
    peer, _ = server.accept()
    peer.close(); client.close(); server.close()  # server closes first: TIME_WAIT
    blocked = False
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1', port))
        except OSError: blocked = True
    if not blocked:
        pytest.skip('this kernel leaves no bind-blocking TIME_WAIT entry behind')
    assert setup.listening(port) is False
    assert setup.service_state(setup.ROOT, port) == 'free'
    channel, bound = listen(port, exact=True)
    assert bound == port
    channel.close()


def test_listen_never_takes_a_port_with_a_live_listener():
    port = free_port()
    server = listener(port)
    try:
        assert setup.listening(port) is True
        with pytest.raises(RuntimeError, match='占用'):
            listen(port, exact=True)
    finally:
        server.close()
