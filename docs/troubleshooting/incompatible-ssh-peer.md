# Incompatible ssh peer (no acceptable host key)

pysftp 0.2.9 fails with this error while it negotiates with the server:

```text
Exception (client): Incompatible ssh peer (no acceptable host key)
Traceback (most recent call last):
  ...
paramiko.ssh_exception.IncompatiblePeer: Incompatible ssh peer (no acceptable host key)
```

`IncompatiblePeer` is a subclass of paramiko's `SSHException`.

## Why it happens

When `known_hosts` lists several keys for a server, pysftp 0.2.9 takes the first one and asks the
server for that key type only. If the server no longer has a key of that type, the handshake fails,
even when a key further down the list would match. A common case is an old `ssh-dss` (DSA) line,
which current OpenSSH servers no longer offer, listed before the server's other keys.

## Fix

pysftp-ng negotiates every key type listed for the host that paramiko can verify, and accepts the
server's key if it matches any of them:

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

You can also remove stale entries and capture the server's current keys, after checking their
fingerprints as [Host keys](../hostkeys.md) explains:

```bash
ssh-keygen -R sftp.example.com
ssh-keyscan sftp.example.com >> ~/.ssh/known_hosts
```

## Check that it's fixed

```python
with pysftp.Connection("sftp.example.com", username="me", password="secret") as sftp:
    print(sftp.remote_server_key.get_name())
```

This prints the type of key the server used, such as `ssh-ed25519`.
