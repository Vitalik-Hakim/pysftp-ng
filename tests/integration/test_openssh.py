"""pysftp against a real OpenSSH server.

These run only when the PYSFTP_INTEGRATION_* settings are set; see
tests/integration/openssh-server.sh. In CI they run in the integration job.
"""

from __future__ import annotations

import hashlib
import os
import stat

import paramiko
import pytest

import pysftp
from tests.conftest import known_hosts_line, write_known_hosts
from tests.integration.conftest import SKIP_REASON, settings_missing

if settings_missing():
    pytest.skip(SKIP_REASON, allow_module_level=True)

pytestmark = pytest.mark.integration

MiB = 1024 * 1024


def _write(sftp: pysftp.Connection, path: str, data: bytes) -> None:
    with sftp.open(path, "wb") as fobj:
        fobj.write(data)


def _read(sftp: pysftp.Connection, path: str) -> bytes:
    with sftp.open(path, "rb") as fobj:
        return fobj.read()


def test_password_login(openssh_connect):
    with openssh_connect() as sftp:
        assert sftp.pwd.startswith("/")
        assert isinstance(sftp.listdir(), list)


def test_ed25519_key_login(openssh, openssh_connect):
    assert paramiko.PKey.from_path(openssh.key).get_name() == "ssh-ed25519"
    with openssh_connect(private_key=openssh.key) as sftp:
        assert sftp.pwd.startswith("/")


def test_known_hosts_from_ssh_keyscan(openssh, openssh_connect):
    """ssh-keyscan -p writes [host]:port entries, which 0.2.9 couldn't find."""
    with open(openssh.known_hosts) as fobj:
        entries = [line.split() for line in fobj if line.strip() and not line.startswith("#")]
    assert entries
    assert all(name == f"[{openssh.host}]:{openssh.port}" for name, _, _ in entries)
    with openssh_connect() as sftp:
        assert sftp.remote_server_key.get_base64() in {key for _, _, key in entries}


def test_wrong_host_key_is_rejected(openssh, openssh_connect, tmp_path):
    not_the_host_key = paramiko.PKey.from_path(openssh.key)
    entry = known_hosts_line(f"[{openssh.host}]:{openssh.port}", not_the_host_key)
    hosts = write_known_hosts(tmp_path / "known_hosts", [entry])
    with pytest.raises(paramiko.BadHostKeyException):
        openssh_connect(cnopts=pysftp.CnOpts(knownhosts=hosts))


def test_put_and_get(remote, tmp_path):
    src = tmp_path / "up.txt"
    src.write_bytes(b"hello\n" * 1000)
    remote.put(str(src), "up.txt")
    remote.get("up.txt", str(tmp_path / "down.txt"))
    assert (tmp_path / "down.txt").read_bytes() == src.read_bytes()


def test_put_r_and_get_r(remote, tmp_path):
    files = {"a.txt": b"a", "sub/b.txt": b"b", "sub/deeper/c.txt": b"c"}
    up = tmp_path / "up"
    for name, data in files.items():
        (up / name).parent.mkdir(parents=True, exist_ok=True)
        (up / name).write_bytes(data)
    remote.mkdir("tree")
    remote.put_r(str(up), "tree")
    remote.get_r("tree", str(tmp_path / "down"))
    # As in 0.2.9, get_r re-creates the remote path under the local directory.
    for name, data in files.items():
        assert (tmp_path / "down" / "tree" / name).read_bytes() == data


def test_symlink_argument_order(remote):
    """symlink(target, link) makes link point at target, as on the in-process server."""
    _write(remote, "target.txt", b"t")
    remote.symlink("target.txt", "link")
    assert stat.S_ISLNK(remote.lstat("link").st_mode)
    assert _read(remote, "link") == b"t"
    assert remote.readlink("link") == f"{remote.pwd}/target.txt"


@pytest.mark.regression
def test_readlink_resolves_a_relative_target_from_the_link_directory(remote):
    """0.2.9 resolved it from the current directory, so other directories got wrong paths."""
    remote.mkdir("sub")
    _write(remote, "sub/target.txt", b"t")
    remote.symlink("target.txt", "sub/link")
    assert remote.readlink("sub/link") == f"{remote.pwd}/sub/target.txt"


def test_normalize_and_pwd_follow_symlinks(openssh, remote):
    base = remote.pwd
    remote.mkdir("real")
    remote.symlink("real", "linked")
    if openssh.windows:
        # Windows' OpenSSH server doesn't resolve symlinks here.
        assert remote.normalize("linked") == f"{base}/linked"
        return
    assert remote.normalize("linked") == f"{base}/real"
    with remote.cd("linked"):
        assert remote.pwd == f"{base}/real"


def test_normalize_needs_existing_parents(openssh, remote):
    assert remote.normalize("missing") == f"{remote.pwd}/missing"
    if openssh.windows:
        # Windows' OpenSSH server doesn't check that the parents exist.
        assert remote.normalize("missing/child") == f"{remote.pwd}/missing/child"
        return
    with pytest.raises(FileNotFoundError):
        remote.normalize("missing/child")


def test_chmod_and_mkdir_read_the_mode_as_octal_digits(remote):
    _write(remote, "f.txt", b"f")
    remote.chmod("f.txt", 600)
    assert stat.S_IMODE(remote.stat("f.txt").st_mode) == 0o600
    remote.mkdir("d", mode=700)
    assert stat.S_IMODE(remote.stat("d").st_mode) == 0o700


def test_rename_onto_an_existing_file_fails(remote):
    """OpenSSH refuses to overwrite with a plain SFTP rename, and pysftp passes that on."""
    _write(remote, "old.txt", b"old")
    _write(remote, "new.txt", b"new")
    with pytest.raises(OSError, match="Failure"):
        remote.rename("old.txt", "new.txt")
    assert _read(remote, "old.txt") == b"old"
    assert _read(remote, "new.txt") == b"new"


def test_execute(openssh, remote):
    if openssh.windows:
        # Windows' OpenSSH server runs commands with cmd.exe.
        assert remote.execute("echo hello") == [b"hello\r\n"]
        assert b"cannot find" in remote.execute(r"type C:\no\such\dir\file")[0]
        return
    assert remote.execute("echo hello") == [b"hello\n"]
    # With nothing on stdout, execute returns what the command wrote to stderr.
    assert b"No such file" in remote.execute("ls /no/such/dir")[0]


def test_50_mib_transfer_keeps_every_byte(openssh, remote, tmp_path):
    src = tmp_path / "big.bin"
    digest = hashlib.sha256()
    with open(src, "wb") as fobj:
        for _ in range(50):
            chunk = os.urandom(MiB)
            digest.update(chunk)
            fobj.write(chunk)
    remote.put(str(src), "big.bin")
    assert remote.stat("big.bin").st_size == 50 * MiB
    if openssh.windows:
        # remote.pwd is like /C:/Users/name; PowerShell wants C:/Users/name.
        path = f"{remote.pwd[1:]}/big.bin"
        command = (
            f"powershell -NoProfile -Command \"(Get-FileHash -Algorithm SHA256 '{path}').Hash\""
        )
    else:
        command = f"sha256sum {remote.pwd}/big.bin"
    on_server = remote.execute(command)[0].split()[0].decode().lower()
    assert on_server == digest.hexdigest()
    remote.get("big.bin", str(tmp_path / "back.bin"))
    back = hashlib.sha256((tmp_path / "back.bin").read_bytes()).hexdigest()
    assert back == digest.hexdigest()
