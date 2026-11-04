"""Connecting, credentials, options and connection lifecycle."""

from __future__ import annotations

import gc
import logging
import re
import socket
import sys
import threading
import time

import paramiko
import pytest

import pysftp
from tests.conftest import PASSWORD, USER


def test_version():
    """__version__ is a valid version string. The release workflow checks it matches the tag."""
    assert re.fullmatch(r"\d+(\.\d+)+((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?", pysftp.__version__)


def test_password_login(sftp, root):
    (root / "hello.txt").write_text("hi")
    assert sftp.pwd == "/"
    assert sftp.listdir() == ["hello.txt"]


def test_context_manager_closes(connect):
    with connect() as conn:
        assert conn.listdir() == []
    assert conn._transport is None
    assert conn._sftp_live is False


def test_close_is_idempotent(sftp):
    sftp.close()
    sftp.close()


def test_wrong_password_raises_and_closes_transport(connect, monkeypatch):
    created: list[paramiko.Transport] = []
    real_transport = paramiko.Transport

    def recording_transport(*args, **kwargs):
        transport = real_transport(*args, **kwargs)
        created.append(transport)
        return transport

    monkeypatch.setattr(pysftp.paramiko, "Transport", recording_transport)
    with pytest.raises(paramiko.AuthenticationException):
        connect(password="nope")
    client_side = [t for t in created if not t.server_mode]
    assert len(client_side) == 1
    assert not client_side[0].is_active()


@pytest.mark.regression
def test_failed_connect_has_no_noise_from_del(server, tmp_path, monkeypatch):
    """0.2.9 printed "AttributeError: 'Connection' object has no attribute
    '_sftp_live'" from __del__ whenever __init__ failed early, burying the
    real error."""
    unraisable = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    other = tmp_path / "known_hosts_other"
    key = paramiko.ECDSAKey.generate()
    other.write_text(f"example.com {key.get_name()} {key.get_base64()}\n")
    with pytest.raises(paramiko.SSHException, match=r"No hostkey for host 127\.0\.0\.1"):
        pysftp.Connection(
            "127.0.0.1",
            port=server.port,
            username=USER,
            password=PASSWORD,
            cnopts=pysftp.CnOpts(knownhosts=str(other)),
        )
    gc.collect()
    assert unraisable == []


def test_unknown_host_raises_connectionexception():
    cnopts = pysftp.CnOpts.__new__(pysftp.CnOpts)
    cnopts.__dict__.update(log=False, compression=False, ciphers=None, timeout=None, hostkeys=None)
    with pytest.raises(pysftp.ConnectionException) as excinfo:
        pysftp.Connection("no-such-host.invalid", username=USER, password=PASSWORD, cnopts=cnopts)
    assert "no-such-host.invalid:22" in str(excinfo.value)


def _no_hostkey_cnopts(tmp_path):
    empty = tmp_path / "kh_unused"
    key = paramiko.ECDSAKey.generate()
    empty.write_text(f"example.com {key.get_name()} {key.get_base64()}\n")
    cnopts = pysftp.CnOpts(knownhosts=str(empty))
    cnopts.hostkeys = None
    return cnopts


def test_timeout_on_silent_server(tmp_path):
    """A server that accepts TCP but never speaks SSH used to hang for
    paramiko's 15 s banner timeout; cnopts.timeout bounds it."""
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    held = []
    threading.Thread(target=lambda: held.append(listener.accept()), daemon=True).start()
    cnopts = _no_hostkey_cnopts(tmp_path)
    cnopts.timeout = 1
    start = time.monotonic()
    with pytest.raises(paramiko.SSHException):
        pysftp.Connection("127.0.0.1", port=port, username=USER, password=PASSWORD, cnopts=cnopts)
    assert time.monotonic() - start < 10
    listener.close()
    for conn, _addr in held:
        conn.close()


@pytest.mark.parametrize("timeout", [None, 2])
def test_connection_refused_raises_sshexception(tmp_path, timeout):
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    cnopts = _no_hostkey_cnopts(tmp_path)
    cnopts.timeout = timeout
    with pytest.raises(paramiko.SSHException, match="Unable to connect"):
        pysftp.Connection("127.0.0.1", port=port, username=USER, password=PASSWORD, cnopts=cnopts)


def test_username_falls_back_to_current_user(connect, monkeypatch):
    monkeypatch.delenv("LOGNAME", raising=False)
    monkeypatch.setattr(pysftp.getpass, "getuser", lambda: USER)
    conn = connect(username=None)
    assert conn.listdir() == []


def test_no_username_raises(connect, monkeypatch):
    monkeypatch.delenv("LOGNAME", raising=False)

    def no_user():
        raise OSError("no user")

    monkeypatch.setattr(pysftp.getpass, "getuser", no_user)
    with pytest.raises(pysftp.CredentialException, match="No username"):
        connect(username=None)


def test_deprecated_log_and_ciphers_params(connect, tmp_path):
    logfile = tmp_path / "deprecated.log"
    with pytest.warns(DeprecationWarning, match="parameter is deprecated") as record:
        conn = connect(log=str(logfile), ciphers=["aes256-ctr"])
    ours = [w for w in record if "parameter is deprecated" in str(w.message)]
    assert len(ours) == 2
    assert all(w.filename == __file__ or "conftest" in w.filename for w in ours)
    assert conn.active_ciphers == ("aes256-ctr", "aes256-ctr")
    conn.close()
    assert logfile.read_text()


@pytest.mark.regression
def test_logging_leaves_application_handlers_alone(connect, cnopts, tmp_path):
    """0.2.9 removed every handler on the "paramiko" logger on close()."""
    lgr = logging.getLogger("paramiko")
    sentinel = logging.NullHandler()
    lgr.addHandler(sentinel)
    level_before = lgr.level
    try:
        cnopts.log = str(tmp_path / "ssh.log")
        conn = connect(cnopts=cnopts)
        assert conn.logfile == cnopts.log
        conn.listdir()
        conn.close()
        assert sentinel in lgr.handlers
        assert lgr.level == level_before
        assert "paramiko.transport" in (tmp_path / "ssh.log").read_text()
    finally:
        lgr.removeHandler(sentinel)


def test_log_true_uses_temp_file(connect, cnopts):
    cnopts.log = True
    conn = connect(cnopts=cnopts)
    assert isinstance(conn.logfile, str)
    assert conn.logfile.endswith(".txt")


def test_execute(sftp):
    assert sftp.execute("echo hello") == [b"hello\n"]
    assert sftp.execute("fail oops") == [b"oops\n"]


def test_ciphers_option(connect, cnopts):
    cnopts.ciphers = ["aes128-ctr"]
    conn = connect(cnopts=cnopts)
    assert conn.active_ciphers == ("aes128-ctr", "aes128-ctr")


def test_compression_option(connect, cnopts):
    cnopts.compression = True
    conn = connect(cnopts=cnopts)
    assert len(conn.active_compression) == 2


def test_properties(sftp):
    assert isinstance(sftp.sftp_client, paramiko.SFTPClient)
    assert "aes256-ctr" in sftp.security_options.ciphers
    assert sftp.remote_server_key.get_name() in {
        "ssh-ed25519",
        "ecdsa-sha2-nistp256",
        "ssh-rsa",
    }
    assert sftp.logfile is False
    sftp.timeout = 5.5
    assert sftp.timeout == 5.5


def test_default_path(connect, root):
    (root / "inbox").mkdir()
    conn = connect(default_path="/inbox")
    assert conn.pwd == "/inbox"


def test_exceptions_reexported():
    assert pysftp.SSHException is paramiko.SSHException
    assert pysftp.AuthenticationException is paramiko.AuthenticationException
    assert issubclass(pysftp.BadHostKeyException, pysftp.SSHException)
    if hasattr(paramiko, "DSSKey"):
        assert pysftp.DSSKey is paramiko.DSSKey
    else:
        assert not hasattr(pysftp, "DSSKey")
