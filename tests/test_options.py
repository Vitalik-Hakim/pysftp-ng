"""Opt-in CnOpts options added after pysftp 0.2.9. Each is off by default."""

from __future__ import annotations

import shlex
import socket
import sys
import time

import paramiko
import pytest

import pysftp
from tests.conftest import (
    PASSWORD,
    USER,
    known_hosts_line,
    write_known_hosts,
    write_relay_script,
)


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


def test_keepalive_is_off_by_default(connect, monkeypatch):
    calls = []
    monkeypatch.setattr(paramiko.Transport, "set_keepalive", lambda self, n: calls.append(n))
    connect()
    assert calls == []


def test_keepalive_sends_packets_while_idle(connect, cnopts, server):
    cnopts.keepalive = 1
    sftp = connect(cnopts=cnopts)
    assert _wait_for(lambda: "keepalive@lag.net" in server.global_requests)
    assert sftp.listdir() == []  # the connection is still usable


def test_negative_keepalive_is_rejected(connect, cnopts):
    cnopts.keepalive = -1
    with pytest.raises(ValueError, match="keepalive"):
        connect(cnopts=cnopts)


# A host name that never resolves (RFC 2606), so a session with it can only run over
# the socket the test hands over.
UNRESOLVABLE = "sftp.invalid"


def _cnopts_for_unresolvable_host(tmp_path, server, keys=None) -> pysftp.CnOpts:
    name = f"[{UNRESOLVABLE}]:{server.port}"
    lines = [known_hosts_line(name, key) for key in (keys or server.host_keys)]
    return pysftp.CnOpts(knownhosts=write_known_hosts(tmp_path / "known_hosts", lines))


def test_sock_carries_the_session(server, tmp_path):
    cnopts = _cnopts_for_unresolvable_host(tmp_path, server)
    cnopts.sock = socket.create_connection(("127.0.0.1", server.port))
    with pysftp.Connection(
        UNRESOLVABLE, port=server.port, username=USER, password=PASSWORD, cnopts=cnopts
    ) as sftp:
        assert sftp.listdir() == []


def test_sock_still_checks_the_host_key(server, tmp_path):
    cnopts = _cnopts_for_unresolvable_host(tmp_path, server, keys=[paramiko.ECDSAKey.generate()])
    cnopts.sock = socket.create_connection(("127.0.0.1", server.port))
    with pytest.raises(paramiko.BadHostKeyException):
        pysftp.Connection(
            UNRESOLVABLE, port=server.port, username=USER, password=PASSWORD, cnopts=cnopts
        )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="paramiko's ProxyCommand uses select() on a pipe, which Windows doesn't support",
)
def test_sock_accepts_a_proxycommand(server, tmp_path):
    cnopts = _cnopts_for_unresolvable_host(tmp_path, server)
    command = [sys.executable, write_relay_script(tmp_path), "127.0.0.1", str(server.port)]
    proxy = paramiko.ProxyCommand(shlex.join(command))
    cnopts.sock = proxy
    transport = None
    try:
        with pysftp.Connection(
            UNRESOLVABLE, port=server.port, username=USER, password=PASSWORD, cnopts=cnopts
        ) as sftp:
            transport = sftp.sftp_client.get_channel().get_transport()
            assert sftp.listdir() == []
    finally:
        # paramiko's transport thread closes the proxy once more as it exits, and
        # ProxyCommand.close() only signals the process. Let the thread finish, then
        # make sure the process has ended and reap it.
        if transport is not None:
            transport.join(timeout=10)
        if proxy.process.poll() is None:
            proxy.process.terminate()
        proxy.process.wait(timeout=10)
        for pipe in (proxy.process.stdin, proxy.process.stdout, proxy.process.stderr):
            pipe.close()
