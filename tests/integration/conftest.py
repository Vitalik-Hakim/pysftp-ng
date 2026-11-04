"""Fixtures for tests against a real SSH server.

The tests are skipped unless every PYSFTP_INTEGRATION_* setting is present.
tests/integration/openssh-server.sh starts a server in Docker and prints them.
"""

from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass

import pytest

import pysftp

SETTINGS = tuple(
    f"PYSFTP_INTEGRATION_{name}"
    for name in ("HOST", "PORT", "USER", "PASSWORD", "KEY", "KNOWN_HOSTS")
)
SKIP_REASON = "needs a real SSH server; see tests/integration/openssh-server.sh"


def settings_missing() -> bool:
    return not all(os.environ.get(name) for name in SETTINGS)


@dataclass(frozen=True)
class Server:
    host: str
    port: int
    user: str
    password: str
    key: str  # an Ed25519 private key the server accepts
    known_hosts: str  # captured with ssh-keyscan


@pytest.fixture(scope="session")
def openssh() -> Server:
    if settings_missing():
        pytest.skip(SKIP_REASON)
    host, port, user, password, key, known_hosts = (os.environ[name] for name in SETTINGS)
    return Server(host, int(port), user, password, key, known_hosts)


@pytest.fixture
def openssh_connect(openssh):
    """Factory for connections to the real server. Host key checking stays on."""
    opened: list[pysftp.Connection] = []

    def _connect(**kw):
        kw.setdefault("username", openssh.user)
        if "private_key" not in kw:
            kw.setdefault("password", openssh.password)
        kw.setdefault("port", openssh.port)
        kw.setdefault("cnopts", pysftp.CnOpts(knownhosts=openssh.known_hosts))
        conn = pysftp.Connection(openssh.host, **kw)
        opened.append(conn)
        return conn

    yield _connect
    for conn in opened:
        conn.close()


@pytest.fixture
def remote(openssh_connect):
    """A connection whose working directory is a new, empty folder."""
    sftp = openssh_connect()
    path = f"{sftp.pwd}/pysftp-it-{uuid.uuid4().hex[:12]}"
    sftp.mkdir(path)
    sftp.chdir(path)
    yield sftp
    _rmtree(sftp, path)


def _rmtree(sftp: pysftp.Connection, path: str) -> None:
    for entry in sftp.listdir_attr(path):
        child = f"{path}/{entry.filename}"
        if stat.S_ISDIR(entry.st_mode):
            _rmtree(sftp, child)
        else:
            sftp.remove(child)
    sftp.rmdir(path)
