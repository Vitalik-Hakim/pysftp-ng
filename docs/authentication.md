# Authentication

pysftp-ng logs in with a password or with private keys, after it has verified the server's host
key.

## User name

Pass `username`. If you leave it out, pysftp-ng uses the `LOGNAME` environment variable and then the
name of the user running Python.

## Password

```python
pysftp.Connection("sftp.example.com", username="me", password="secret")
```

When a password is given, pysftp-ng uses it and doesn't try any keys.

## Key file

```python
pysftp.Connection("sftp.example.com", username="me", private_key="~/.ssh/id_ed25519")
```

RSA, ECDSA and Ed25519 keys work, in OpenSSH format (`-----BEGIN OPENSSH PRIVATE KEY-----`, what
`ssh-keygen` writes by default) or in PEM format. DSA keys work only with paramiko older than 4.0,
which removed DSA support.

For an encrypted key, pass its passphrase as `private_key_pass`. Without it, pysftp-ng raises
`paramiko.PasswordRequiredException`.

```python
pysftp.Connection(
    "sftp.example.com",
    username="me",
    private_key="~/.ssh/id_ed25519",
    private_key_pass="passphrase",
)
```

## Key object

`private_key` also accepts any paramiko key object, such as a key loaded in your own code or one
from the ssh-agent:

```python
import paramiko

key = paramiko.Ed25519Key.from_private_key_file("/secrets/deploy_key")
pysftp.Connection("sftp.example.com", username="deploy", private_key=key)

agent_keys = paramiko.Agent().get_keys()
pysftp.Connection("sftp.example.com", username="me", private_key=agent_keys[0])
```

## Default keys

With neither `password` nor `private_key`, pysftp-ng looks for these files in `~/.ssh`, in OpenSSH's
order:

1. `id_rsa`
2. `id_ecdsa`
3. `id_ed25519`
4. `id_dsa`, with paramiko older than 4.0 only

It loads the ones that exist and offers each to the server in turn, and the first one the server
accepts is used. If one of them is encrypted, `private_key_pass` is used as its passphrase. If none
of the files exist, pysftp-ng raises `CredentialException("No password or key specified.")`.

pysftp 0.2.9 only looked for `id_rsa` and `id_dsa`.
