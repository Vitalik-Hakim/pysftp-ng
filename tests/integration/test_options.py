"""The opt-in CnOpts options against a real OpenSSH server."""

from __future__ import annotations

import time

import pytest

import pysftp
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
