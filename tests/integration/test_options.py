"""The opt-in CnOpts options against a real OpenSSH server."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

import paramiko
import pytest

import pysftp
from tests.conftest import write_relay_script
from tests.integration.conftest import SKIP_REASON, settings_missing

if settings_missing():
    pytest.skip(SKIP_REASON, allow_module_level=True)

pytestmark = pytest.mark.integration


def test_keepalive(openssh, openssh_connect):
    cnopts = pysftp.CnOpts(knownhosts=openssh.known_hosts)
    cnopts.keepalive = 1
    with openssh_connect(cnopts=cnopts) as sftp:
        time.sleep(2.5)  # long enough for keepalives to go out with no other traffic
        assert sftp.pwd.startswith("/")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="paramiko's ProxyCommand calls select() on a pipe, which Windows doesn't support",
)
def test_sock_with_a_proxycommand(openssh, tmp_path):
    # Name the server sftp.invalid, which never resolves, so the session can only run
    # over the ProxyCommand.
    known_hosts = tmp_path / "known_hosts"
    with open(openssh.known_hosts) as fobj:
        entries = fobj.read()
    known_hosts.write_text(entries.replace(f"[{openssh.host}]:", "[sftp.invalid]:"))
    cnopts = pysftp.CnOpts(knownhosts=str(known_hosts))
    command = [sys.executable, write_relay_script(tmp_path), openssh.host, str(openssh.port)]
    proxy = paramiko.ProxyCommand(shlex.join(command))
    cnopts.sock = proxy
    transport = None
    try:
        with pysftp.Connection(
            "sftp.invalid",
            port=openssh.port,
            username=openssh.user,
            password=openssh.password,
            cnopts=cnopts,
        ) as sftp:
            transport = sftp.sftp_client.get_channel().get_transport()
            assert sftp.pwd.startswith("/")
    finally:
        if transport is not None:
            transport.join(timeout=10)
        if proxy.process.poll() is None:
            proxy.process.terminate()
        proxy.process.wait(timeout=10)
        for pipe in (proxy.process.stdin, proxy.process.stdout, proxy.process.stderr):
            pipe.close()


@pytest.fixture
def agent_with_key(openssh, monkeypatch, tmp_path):
    """An ssh-agent holding the server's key: a new ssh-agent on Unix. On Windows, paramiko
    ignores SSH_AUTH_SOCK and uses the ssh-agent service that comes with Windows' OpenSSH."""
    if sys.platform == "win32":
        yield from _windows_agent(openssh, tmp_path)
    else:
        yield from _unix_agent(openssh, monkeypatch)


def _unix_agent(openssh, monkeypatch):
    # Unix socket paths have a short length limit, so keep the agent's under /tmp.
    sock_dir = tempfile.mkdtemp(dir="/tmp")
    sock = os.path.join(sock_dir, "agent.sock")
    agent = subprocess.Popen(
        ["ssh-agent", "-D", "-a", sock], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 10
        while not os.path.exists(sock) and time.monotonic() < deadline:
            time.sleep(0.05)
        env = {**os.environ, "SSH_AUTH_SOCK": sock}
        subprocess.run(["ssh-add", openssh.key], env=env, check=True, capture_output=True)
        monkeypatch.setenv("SSH_AUTH_SOCK", sock)
        yield
    finally:
        agent.terminate()
        agent.wait(timeout=10)
        shutil.rmtree(sock_dir, ignore_errors=True)


def _windows_agent(openssh, tmp_path):
    from paramiko import win_openssh, win_pageant

    if win_pageant.can_talk_to_agent():
        pytest.skip("Pageant is running, and paramiko asks it before the ssh-agent service")
    if not win_openssh.can_talk_to_agent():
        if openssh.windows:  # windows-openssh-server.py starts the service
            pytest.fail("Windows' ssh-agent service isn't running")
        pytest.skip("Windows' ssh-agent service isn't running")
    # Windows' own ssh-add. Others on the PATH, such as Git for Windows', may use another agent.
    openssh_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH")
    ssh_add = os.path.join(openssh_dir, "ssh-add.exe")
    key = paramiko.Ed25519Key.from_private_key_file(openssh.key)
    public = tmp_path / "agent-key.pub"
    public.write_text(f"{key.get_name()} {key.get_base64()}\n")
    subprocess.run([ssh_add, openssh.key], check=True)
    try:
        yield
    finally:
        # The service keeps the keys it's given, even across restarts, so take this one out.
        subprocess.run([ssh_add, "-d", str(public)], check=True)


def test_allow_agent_with_a_real_ssh_agent(openssh, openssh_connect, fake_home, agent_with_key):
    cnopts = pysftp.CnOpts(knownhosts=openssh.known_hosts)
    cnopts.allow_agent = True
    # No password, and fake_home has no key files, so only the agent can log in.
    with openssh_connect(password=None, cnopts=cnopts) as sftp:
        assert sftp.pwd.startswith("/")


def test_ssh_config_alias(openssh, fake_home, tmp_path):
    config = tmp_path / "ssh_config"
    config.write_text(
        "Host pysftp-alias\n"
        f"    HostName {openssh.host}\n"
        f"    Port {openssh.port}\n"
        f"    User {openssh.user}\n"
        f"    IdentityFile {openssh.key}\n"
    )
    cnopts = pysftp.CnOpts(knownhosts=openssh.known_hosts)
    cnopts.ssh_config = config
    # Only the config says where pysftp-alias is, who to log in as and which key to use.
    with pysftp.Connection("pysftp-alias", cnopts=cnopts) as sftp:
        assert sftp.pwd.startswith("/")
