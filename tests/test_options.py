"""Opt-in CnOpts options added after pysftp 0.2.9. Each is off by default."""

from __future__ import annotations

import shlex
import socket
import sys
import time
from typing import ClassVar

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


class FakeAgent:
    """Stands in for paramiko.Agent, holding the keys a test gives it."""

    keys: ClassVar[tuple] = ()
    created: ClassVar[list] = []

    def __init__(self):
        self.closed = False
        FakeAgent.created.append(self)

    def get_keys(self):
        return tuple(FakeAgent.keys)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_agent(monkeypatch):
    FakeAgent.keys = ()
    FakeAgent.created = []
    monkeypatch.setattr(paramiko, "Agent", FakeAgent)
    return FakeAgent


def _connect_to(srv, tmp_path, **kw):
    lines = [known_hosts_line(f"[127.0.0.1]:{srv.port}", key) for key in srv.host_keys]
    cnopts = pysftp.CnOpts(knownhosts=write_known_hosts(tmp_path / "kh_agent", lines))
    cnopts.allow_agent = kw.pop("allow_agent", True)
    return pysftp.Connection("127.0.0.1", port=srv.port, username=USER, cnopts=cnopts, **kw)


def test_agent_is_not_used_by_default(connect, fake_home, fake_agent, client_keys):
    fake_agent.keys = (client_keys["ed25519"].pkey,)
    with pytest.raises(pysftp.CredentialException, match="No password or key specified"):
        connect(password=None)
    assert fake_agent.created == []


def test_allow_agent_logs_in_with_an_agent_key(
    server, fake_home, fake_agent, client_keys, tmp_path
):
    fake_agent.keys = (client_keys["ed25519"].pkey,)
    with _connect_to(server, tmp_path) as sftp:
        assert sftp.listdir() == []
    assert server.publickey_attempts == ["ssh-ed25519"]
    assert [agent.closed for agent in fake_agent.created] == [True]


def test_agent_keys_come_after_the_given_key(
    server_factory, fake_home, fake_agent, client_keys, tmp_path
):
    srv = server_factory(authorized=["ed25519"])
    fake_agent.keys = (client_keys["ed25519"].pkey,)
    with _connect_to(srv, tmp_path, private_key=client_keys["rsa"].path) as sftp:
        assert sftp.listdir() == []
    assert srv.publickey_attempts == ["ssh-rsa", "ssh-ed25519"]


def test_a_key_is_not_offered_twice(server_factory, fake_home, fake_agent, client_keys, tmp_path):
    srv = server_factory(authorized=["rsa"])
    fake_agent.keys = (client_keys["ed25519"].pkey, client_keys["rsa"].pkey)
    with _connect_to(srv, tmp_path, private_key=client_keys["ed25519"].path) as sftp:
        assert sftp.listdir() == []
    assert srv.publickey_attempts == ["ssh-ed25519", "ssh-rsa"]


def test_a_password_skips_the_agent(server, fake_agent, client_keys, tmp_path):
    fake_agent.keys = (client_keys["ed25519"].pkey,)
    with _connect_to(server, tmp_path, password=PASSWORD) as sftp:
        assert sftp.listdir() == []
    assert fake_agent.created == []
    assert server.publickey_attempts == []
