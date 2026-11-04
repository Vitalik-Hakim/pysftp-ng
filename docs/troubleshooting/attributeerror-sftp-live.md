# AttributeError: 'Connection' object has no attribute '_sftp_live'

With pysftp 0.2.9, this error appears after a connection has already failed:

```text
paramiko.ssh_exception.SSHException: No hostkey for host 127.0.0.1 found.
Exception ignored in: <function Connection.__del__ at 0x107454b80>
Traceback (most recent call last):
  ...
AttributeError: 'Connection' object has no attribute '_sftp_live'
```

## Why it happens

This error hides the real problem instead of causing one. pysftp 0.2.9's `Connection.__init__`
checks for the server's host key before it sets its `_sftp_live` attribute. When that check fails,
Python later cleans up the half-built object: its `__del__` method calls `close()`, and `close()`
reads `_sftp_live`, which was never set. Python reports that second error as "Exception ignored",
after the real one.

The real error is the one printed above it, most often
[No hostkey for host ... found](no-hostkey-for-host.md).

## Fix

pysftp-ng sets up its state before it does anything that can fail, so a failed connection reports
only the real error and closes its network connection:

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

Then fix the error that remains. For a missing host key, add the server to `known_hosts` rather
than turning host key checking off.

## Check that it's fixed

Run the same code again. Only the real error appears, with no "Exception ignored in" lines after
it. Once that error is fixed, the connection succeeds.
