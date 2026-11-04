# SSHException: encountered EC key, expected DSA key

pysftp 0.2.9 raises this when `private_key` points to an ECDSA key in PEM format:

```text
paramiko.ssh_exception.SSHException: encountered EC key, expected RSA key

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  ...
paramiko.ssh_exception.SSHException: encountered EC key, expected DSA key
```

## Why it happens

pysftp 0.2.9 tries to read the key file as an RSA key, then as a DSA key, and never as an ECDSA
key. An ECDSA key in PEM format starts with `-----BEGIN EC PRIVATE KEY-----`, as written by
`ssh-keygen -m PEM` or by OpenSSL. paramiko rejects it as an RSA key and again as a DSA key, and the
second message is the one you see last.

The same key in OpenSSH format fails with a different message:
[unpack requires a buffer of 4 bytes](unpack-requires-a-buffer.md).

## Fix

pysftp-ng reads the key type from the file, and loads RSA, ECDSA and Ed25519 keys in OpenSSH or PEM
format:

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

```python
with pysftp.Connection("sftp.example.com", username="me", private_key="~/.ssh/id_ecdsa") as sftp:
    print(sftp.listdir())
```

For an encrypted key, add `private_key_pass="passphrase"`. See [Authentication](../authentication.md).

## Check that it's fixed

The connection opens and lists the remote directory, with no change to the key file.
