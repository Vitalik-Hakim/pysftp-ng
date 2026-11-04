"""Opt-in CnOpts options added after pysftp 0.2.9. Each is off by default."""

from __future__ import annotations

import time

import paramiko
import pytest


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
