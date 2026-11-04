# SSHException: No hostkey for host ... found.

pysftp raises this before it connects, when it can't find the server in `known_hosts`:

```text
paramiko.ssh_exception.SSHException: No hostkey for host 127.0.0.1 found.
```

With pysftp 0.2.9, it is often followed by
[AttributeError: 'Connection' object has no attribute '_sftp_live'](attributeerror-sftp-live.md).

## Why it happens

pysftp checks the server's host key against `~/.ssh/known_hosts`, or the file given to `CnOpts`,
before it sends any credentials. Here it found no entry for the host. There are two common causes:

- The server isn't in `known_hosts` yet.
- The server listens on a port other than 22. OpenSSH (`ssh`, `ssh-keyscan -p`) records such
  servers as `[host]:port`, and pysftp 0.2.9 only looks for the bare host name, so it never finds
  the entry.

## Fix

pysftp-ng looks for `[host]:port` first and then the bare host name, which fixes the second cause:

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

If the server isn't in `known_hosts`, add it, and compare its fingerprint with one from the server's
administrator. [Host keys](../hostkeys.md) explains how.

```bash
ssh-keyscan -p 2222 sftp.example.com >> ~/.ssh/known_hosts
```

Don't work around this error with `cnopts.hostkeys = None`. That turns off the check that stops
someone else from posing as the server.

## Check that it's fixed

```bash
ssh-keygen -F '[sftp.example.com]:2222'
```

This prints the entry when it is there; for port 22, use the bare host name. The connection then
succeeds.
