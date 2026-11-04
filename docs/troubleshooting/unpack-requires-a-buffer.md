# SSHException: unpack requires a buffer of 4 bytes

pysftp 0.2.9 raises this when `private_key` points to an Ed25519 or ECDSA key in OpenSSH format:

```text
paramiko.ssh_exception.SSHException: unpack requires a buffer of 4 bytes

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  ...
struct.error: unpack requires a buffer of 4 bytes

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  ...
paramiko.ssh_exception.SSHException: unpack requires a buffer of 4 bytes
```

## Why it happens

pysftp 0.2.9 tries to read the key file as an RSA key, then as a DSA key, and never as anything
else. Since OpenSSH 7.8, `ssh-keygen` writes new keys in its own format, which starts with
`-----BEGIN OPENSSH PRIVATE KEY-----`. For an Ed25519 or ECDSA key in that format, both attempts
fail, and paramiko's DSA reader reports this low-level parsing error. To see a key's format:

```bash
head -1 ~/.ssh/id_ed25519
```

## Fix

pysftp-ng reads the key type from the file, and loads RSA, ECDSA and Ed25519 keys in OpenSSH or PEM
format:

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

```python
with pysftp.Connection("sftp.example.com", username="me", private_key="~/.ssh/id_ed25519") as sftp:
    print(sftp.listdir())
```

For an encrypted key, add `private_key_pass="passphrase"`. See [Authentication](../authentication.md).

## Check that it's fixed

The connection opens and lists the remote directory. If the key is encrypted and you didn't give a
passphrase, pysftp-ng now says so with `PasswordRequiredException` instead of this error.
