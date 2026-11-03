"""Private key handling: files, key objects, passphrases, default keys."""

from __future__ import annotations

import shutil

import paramiko
import pytest

import pysftp
from tests.conftest import PASSPHRASE, _write_private, new_key


@pytest.mark.parametrize(
    "name",
    [
        "rsa",
        "rsa_pem",
        pytest.param("ecdsa", marks=pytest.mark.regression),
        pytest.param("ed25519", marks=pytest.mark.regression),
    ],
)
def test_key_file(connect, client_keys, name):
    """0.2.9 could only load RSA (and DSA) key files."""
    conn = connect(private_key=client_keys[name].path)
    assert conn.listdir() == []


def test_encrypted_key(connect, client_keys):
    conn = connect(private_key=client_keys["ed25519_enc"].path, private_key_pass=PASSPHRASE)
    assert conn.listdir() == []


def test_encrypted_key_without_passphrase(connect, client_keys):
    with pytest.raises(paramiko.PasswordRequiredException):
        connect(private_key=client_keys["ed25519_enc"].path)


def test_encrypted_key_wrong_passphrase(connect, client_keys):
    with pytest.raises(paramiko.SSHException):
        connect(private_key=client_keys["ed25519_enc"].path, private_key_pass="wrong")


@pytest.mark.regression
def test_key_object(connect, client_keys):
    """0.2.9 only accepted RSAKey/AgentKey objects; anything else was treated
    as a path and crashed with TypeError."""
    conn = connect(private_key=client_keys["ed25519"].pkey)
    assert conn.listdir() == []


def test_unauthorized_key_rejected(connect, tmp_path):
    stranger = _write_private(new_key("ed25519"), tmp_path / "stranger")
    with pytest.raises(paramiko.AuthenticationException):
        connect(private_key=str(stranger))


def test_missing_key_file(connect, tmp_path):
    with pytest.raises(FileNotFoundError):
        connect(private_key=str(tmp_path / "nope"))


@pytest.mark.regression
def test_default_ed25519_key(connect, client_keys, fake_home, server):
    """0.2.9 only looked for ~/.ssh/id_rsa and ~/.ssh/id_dsa."""
    shutil.copy(client_keys["ed25519"].path, fake_home / ".ssh" / "id_ed25519")
    conn = connect(password=None)
    assert conn.listdir() == []
    assert server.password_attempts == []


def test_default_keys_tried_in_order(connect, client_keys, fake_home, server):
    _write_private(new_key("rsa"), fake_home / ".ssh" / "id_rsa")  # not authorized
    shutil.copy(client_keys["ecdsa"].path, fake_home / ".ssh" / "id_ecdsa")
    conn = connect(password=None)
    assert conn.listdir() == []
    assert server.publickey_attempts == ["ssh-rsa", "ecdsa-sha2-nistp256"]


def test_default_encrypted_key_skipped(connect, client_keys, fake_home):
    shutil.copy(client_keys["ed25519_enc"].path, fake_home / ".ssh" / "id_rsa")
    shutil.copy(client_keys["ed25519"].path, fake_home / ".ssh" / "id_ed25519")
    conn = connect(password=None)
    assert conn.listdir() == []


def test_no_credentials(connect, fake_home):
    with pytest.raises(pysftp.CredentialException, match="No password or key"):
        connect(password=None)


def test_password_preferred_over_key(connect, client_keys, server):
    conn = connect(password="secret", private_key=client_keys["ed25519"].path)
    assert conn.listdir() == []
    assert server.password_attempts
    assert server.publickey_attempts == []
