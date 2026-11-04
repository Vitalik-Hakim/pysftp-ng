from __future__ import annotations

import os
import textwrap
from collections import namedtuple
from pathlib import Path

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

import pysftp
from tests.sftp_server import SFTPTestServer

USER = "tester"
PASSWORD = "secret"
PASSPHRASE = "hunter2"

KeyFile = namedtuple("KeyFile", "path pkey")


def _write_private(key, path: Path, *, passphrase: str | None = None, legacy_pem=False):
    if legacy_pem:
        fmt = serialization.PrivateFormat.TraditionalOpenSSL
    else:
        fmt = serialization.PrivateFormat.OpenSSH
    enc = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, fmt, enc))
    path.chmod(0o600)
    return path


def _keyfile(key, path: Path, **kw) -> KeyFile:
    _write_private(key, path, **kw)
    password = kw.get("passphrase")
    pkey = paramiko.PKey.from_path(str(path), password.encode() if password else None)
    return KeyFile(str(path), pkey)


def new_key(kind: str):
    if kind == "rsa":
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)
    if kind == "ecdsa":
        return ec.generate_private_key(ec.SECP256R1())
    if kind == "ed25519":
        return ed25519.Ed25519PrivateKey.generate()
    raise ValueError(kind)


@pytest.fixture(scope="session")
def keydir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("keys")


@pytest.fixture(scope="session")
def host_keys(keydir) -> dict[str, paramiko.PKey]:
    return {
        kind: _keyfile(new_key(kind), keydir / f"host_{kind}").pkey
        for kind in ("ed25519", "ecdsa", "rsa")
    }


@pytest.fixture(scope="session")
def client_keys(keydir) -> dict[str, KeyFile]:
    return {
        "rsa": _keyfile(new_key("rsa"), keydir / "client_rsa"),
        "rsa_pem": _keyfile(new_key("rsa"), keydir / "client_rsa_pem", legacy_pem=True),
        "ecdsa": _keyfile(new_key("ecdsa"), keydir / "client_ecdsa"),
        "ed25519": _keyfile(new_key("ed25519"), keydir / "client_ed25519"),
        "ed25519_enc": _keyfile(
            new_key("ed25519"), keydir / "client_ed25519_enc", passphrase=PASSPHRASE
        ),
    }


@pytest.fixture
def server_factory(tmp_path, host_keys, client_keys):
    servers: list[SFTPTestServer] = []

    def make(host_key_types=("ed25519", "ecdsa", "rsa"), authorized=None, inject_names=()):
        root = tmp_path / f"srv{len(servers)}"
        root.mkdir()
        if authorized is None:
            authorized = list(client_keys)
        srv = SFTPTestServer(
            str(root),
            [host_keys[kind] for kind in host_key_types],
            username=USER,
            password=PASSWORD,
            authorized_keys=[client_keys[name].pkey for name in authorized],
            inject_names=inject_names,
        )
        servers.append(srv)
        return srv

    yield make
    for srv in servers:
        srv.close()


@pytest.fixture
def server(server_factory) -> SFTPTestServer:
    return server_factory()


def known_hosts_line(host: str, key: paramiko.PKey, *, hashed=False) -> str:
    name = paramiko.HostKeys.hash_host(host) if hashed else host
    return f"{name} {key.get_name()} {key.get_base64()}"


def write_known_hosts(path: Path, lines) -> str:
    path.write_text("\n".join(lines) + "\n")
    return str(path)


@pytest.fixture
def known_hosts_file(tmp_path, server, host_keys) -> str:
    host = f"[127.0.0.1]:{server.port}"
    return write_known_hosts(
        tmp_path / "known_hosts", [known_hosts_line(host, key) for key in server.host_keys]
    )


@pytest.fixture
def cnopts(known_hosts_file) -> pysftp.CnOpts:
    return pysftp.CnOpts(knownhosts=known_hosts_file)


@pytest.fixture
def connect(server, cnopts):
    """Factory for connections to the default test server."""
    opened: list[pysftp.Connection] = []

    def _connect(**kw):
        kw.setdefault("username", USER)
        if "private_key" not in kw:
            kw.setdefault("password", PASSWORD)
        kw.setdefault("cnopts", cnopts)
        kw.setdefault("port", server.port)
        conn = pysftp.Connection("127.0.0.1", **kw)
        opened.append(conn)
        return conn

    yield _connect
    for conn in opened:
        conn.close()


@pytest.fixture
def sftp(connect) -> pysftp.Connection:
    return connect()


@pytest.fixture
def root(server) -> Path:
    """The directory the default test server serves as "/"."""
    return Path(server.root)


def write_relay_script(directory: Path) -> str:
    """Write a stand-in for `ssh -W` that relays stdin and stdout to host:port,
    for use as a paramiko.ProxyCommand."""
    path = directory / "relay.py"
    path.write_text(
        textwrap.dedent(
            """
            import socket, sys, threading
            conn = socket.create_connection((sys.argv[1], int(sys.argv[2])))
            def upstream():
                while True:
                    data = sys.stdin.buffer.read1(65536)
                    if not data:
                        break
                    conn.sendall(data)
                conn.shutdown(socket.SHUT_WR)
            threading.Thread(target=upstream, daemon=True).start()
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            """
        )
    )
    return str(path)


@pytest.fixture
def fake_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def pytest_report_header(config):
    where = os.path.dirname(pysftp.__file__)
    return f"pysftp {pysftp.__version__} from {where}; paramiko {paramiko.__version__}"
