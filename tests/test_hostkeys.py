"""Host key verification against known_hosts."""

from __future__ import annotations

import warnings

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dsa

import pysftp
from tests.conftest import PASSWORD, USER, known_hosts_line, write_known_hosts


def _connect(server, known_hosts):
    return pysftp.Connection(
        "127.0.0.1",
        port=server.port,
        username=USER,
        password=PASSWORD,
        cnopts=pysftp.CnOpts(knownhosts=known_hosts),
    )


@pytest.mark.regression
def test_port_qualified_entry(server, tmp_path):
    """OpenSSH writes non-22 ports as [host]:port; 0.2.9 only looked up the
    bare hostname and failed with "No hostkey for host ... found"."""
    kh = write_known_hosts(
        tmp_path / "kh",
        [known_hosts_line(f"[127.0.0.1]:{server.port}", k) for k in server.host_keys],
    )
    with _connect(server, kh) as conn:
        assert conn.listdir() == []


def test_bare_host_entry_still_works(server, tmp_path):
    kh = write_known_hosts(
        tmp_path / "kh", [known_hosts_line("127.0.0.1", k) for k in server.host_keys]
    )
    with _connect(server, kh) as conn:
        assert conn.listdir() == []


def test_hashed_entry(server, tmp_path):
    kh = write_known_hosts(
        tmp_path / "kh",
        [known_hosts_line(f"[127.0.0.1]:{server.port}", k, hashed=True) for k in server.host_keys],
    )
    with _connect(server, kh) as conn:
        assert conn.listdir() == []


def test_no_entry_raises(server, tmp_path):
    key = paramiko.ECDSAKey.generate()
    kh = write_known_hosts(tmp_path / "kh", [known_hosts_line("example.com", key)])
    with pytest.raises(paramiko.SSHException, match=r"No hostkey for host 127\.0\.0\.1 found"):
        _connect(server, kh)


def test_changed_key_rejected_before_password_is_sent(server, tmp_path):
    impostor = paramiko.ECDSAKey.generate()
    kh = write_known_hosts(
        tmp_path / "kh", [known_hosts_line(f"[127.0.0.1]:{server.port}", impostor)]
    )
    with pytest.raises(pysftp.BadHostKeyException):
        _connect(server, kh)
    assert server.password_attempts == []


@pytest.mark.regression
def test_stale_key_type_listed_first(server_factory, host_keys, tmp_path):
    """0.2.9 pinned the first key it found for a host. If the server had
    since dropped that key type, the connection failed even though another
    known key matched."""
    srv = server_factory(host_key_types=("ed25519",))
    retired = paramiko.ECDSAKey.generate()
    host = f"[127.0.0.1]:{srv.port}"
    kh = write_known_hosts(
        tmp_path / "kh",
        [known_hosts_line(host, retired), known_hosts_line(host, host_keys["ed25519"])],
    )
    with _connect(srv, kh) as conn:
        assert conn.remote_server_key.get_name() == "ssh-ed25519"


def test_rsa_only_entry_negotiates_rsa(server, host_keys, tmp_path):
    kh = write_known_hosts(
        tmp_path / "kh", [known_hosts_line(f"[127.0.0.1]:{server.port}", host_keys["rsa"])]
    )
    with _connect(server, kh) as conn:
        assert conn.remote_server_key.get_name() == "ssh-rsa"


def test_hostkeys_none_skips_verification(server, tmp_path):
    key = paramiko.ECDSAKey.generate()
    kh = write_known_hosts(tmp_path / "kh", [known_hosts_line("example.com", key)])
    cnopts = pysftp.CnOpts(knownhosts=kh)
    cnopts.hostkeys = None
    with pysftp.Connection(
        "127.0.0.1", port=server.port, username=USER, password=PASSWORD, cnopts=cnopts
    ) as conn:
        assert conn.listdir() == []


@pytest.mark.regression
def test_known_hosts_with_legacy_dsa_line(server, tmp_path):
    """An old ssh-dss line listed first made 0.2.9 pin DSA ("Incompatible ssh
    peer"), and such lines must not break loading on paramiko 4+, which has
    no DSA support at all."""
    with warnings.catch_warnings():  # cryptography deprecates SSH DSA serialisation
        warnings.simplefilter("ignore")
        dss = (
            dsa.generate_private_key(key_size=1024)
            .public_key()
            .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
            .decode()
        )
    host = f"[127.0.0.1]:{server.port}"
    lines = [f"{host} {dss}"] + [known_hosts_line(host, k) for k in server.host_keys]
    kh = write_known_hosts(tmp_path / "kh", lines)
    with _connect(server, kh) as conn:
        assert conn.listdir() == []


def test_missing_known_hosts_warns(tmp_path):
    with pytest.warns(UserWarning, match=r"disable HostKey checking \(cnopts.hostkeys = None\)"):
        cnopts = pysftp.CnOpts(knownhosts=str(tmp_path / "missing"))
    assert len(cnopts.hostkeys) == 0


def test_empty_known_hosts_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.write_text("")
    with pytest.raises(pysftp.HostKeysException):
        pysftp.CnOpts(knownhosts=str(empty))


def test_get_hostkey_accepts_port(server, known_hosts_file):
    cnopts = pysftp.CnOpts(knownhosts=known_hosts_file)
    assert isinstance(cnopts.get_hostkey("127.0.0.1", server.port), paramiko.PKey)
    with pytest.raises(paramiko.SSHException):
        cnopts.get_hostkey("127.0.0.1")


def test_cnopts_subclass_with_0_2_9_get_hostkey(server, host_keys, known_hosts_file):
    """Code that overrode get_hostkey(host) for pysftp 0.2.9 keeps working."""

    class PinnedCnOpts(pysftp.CnOpts):
        def get_hostkey(self, host):
            return host_keys["ed25519"]

    cnopts = PinnedCnOpts(knownhosts=known_hosts_file)
    with pysftp.Connection(
        "127.0.0.1", port=server.port, username=USER, password=PASSWORD, cnopts=cnopts
    ) as conn:
        assert conn.remote_server_key.get_name() == "ssh-ed25519"
