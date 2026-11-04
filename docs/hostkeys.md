# Host keys

pysftp-ng checks the server's host key against `known_hosts` before it sends any password or key.
Host key checking is on by default.

## Where the keys come from

`pysftp.CnOpts()` loads `~/.ssh/known_hosts`. To use another file, pass it in:

```python
cnopts = pysftp.CnOpts(knownhosts="/etc/myapp/known_hosts")
with pysftp.Connection("sftp.example.com", username="me", password="secret", cnopts=cnopts) as sftp:
    print(sftp.listdir())
```

To add the keys from a second file, load it into the same object:

```python
cnopts = pysftp.CnOpts()
cnopts.hostkeys.load("/etc/myapp/extra_known_hosts")
```

## How a host is looked up

For a server on a port other than 22, pysftp-ng first looks for an entry named `[host]:port`, which
is how OpenSSH records those servers. If there isn't one, it looks for the bare host name, which is
what pysftp 0.2.9 required, so older files keep working. For port 22, it looks up the bare host
name.

Entries hashed by OpenSSH's `HashKnownHosts` option are found the same way.

With `cnopts.ssh_config` on, the lookup uses the `HostName` and `Port` from your SSH config, as
`ssh` does; see [Connection options](options.md).

When `known_hosts` lists several keys for a host, pysftp-ng only negotiates the key types listed and
accepts whichever one matches. A key that doesn't match raises `paramiko.BadHostKeyException`.

## Adding a server's key

`ssh-keyscan` prints a server's host keys in `known_hosts` format:

```bash
ssh-keyscan -p 2222 sftp.example.com >> ~/.ssh/known_hosts
ssh-keygen -lf ~/.ssh/known_hosts
```

`ssh-keyscan` trusts whatever answers on the network, so compare the fingerprints from
`ssh-keygen -lf` with ones the server's administrator gives you before relying on them. Connecting
once with `ssh -p 2222 me@sftp.example.com` and checking the fingerprint it shows works too.

## Why not turn checking off

Setting `cnopts.hostkeys = None` turns host key checking off:

```python
cnopts = pysftp.CnOpts()
cnopts.hostkeys = None  # unsafe: any machine on the network path can pose as the server
```

Without the check, anyone who can intercept the connection, for example through spoofed DNS or a
hostile Wi-Fi network, can pose as the server and receive your password and your files. Use it only
for throwaway test servers. To fix a missing key, add the key instead; see
[No hostkey for host ... found](troubleshooting/no-hostkey-for-host.md).
