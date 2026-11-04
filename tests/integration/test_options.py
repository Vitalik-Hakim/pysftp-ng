"""The opt-in CnOpts options against a real OpenSSH server."""

from __future__ import annotations

import shlex
import sys
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
