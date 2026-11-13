# Connection options

Options that change how pysftp-ng connects are set on a `CnOpts` object, which you pass to
`Connection` as `cnopts`. Each option is off by default, so code written for pysftp 0.2.9 behaves as
before.

```python
import pysftp

cnopts = pysftp.CnOpts()
cnopts.timeout = 10
with pysftp.Connection("sftp.example.com", username="me", password="secret", cnopts=cnopts) as sftp:
    print(sftp.listdir())
```

Host key checking has [its own page](hostkeys.md). The older `log`, `compression` and `ciphers`
options are described in the [API reference](api.rst).

## timeout

`cnopts.timeout` limits, in seconds, how long pysftp-ng waits for the TCP connection, the server's
SSH banner, the key exchange and the login. The default, `None`, leaves paramiko's own limits in
place. *New in 0.3.0.*

```python
cnopts.timeout = 10
```

## keepalive

`cnopts.keepalive` sends a keepalive packet after that many seconds without traffic. Firewalls and
NAT routers often drop connections that sit idle, for example between transfers in a long-running
job, and the packets keep them open. The server ignores them. The default, `0`, sends none.
*New in 0.4.0.*

```python
cnopts.keepalive = 30
```

## sock

`cnopts.sock` runs the SSH session over a connection you provide instead of a TCP connection to the
host, for example to reach a server behind a jump host. It takes an already-connected socket or a
`paramiko.ProxyCommand`. The default, `None`, connects directly. *New in 0.4.0.*

```python
import paramiko

cnopts = pysftp.CnOpts()
cnopts.sock = paramiko.ProxyCommand("ssh -W sftp.internal:22 me@jump.example.com")
with pysftp.Connection("sftp.internal", username="me", password="secret", cnopts=cnopts) as sftp:
    print(sftp.listdir())
```

Here `ssh -W` logs in to the jump host with your usual SSH setup and forwards the connection.
pysftp-ng still checks the host key of `sftp.internal` against `known_hosts`, so the jump host
can't pose as the server.

The connection closes what you pass in, so use a new socket or `ProxyCommand` for each connection.
paramiko's `ProxyCommand` doesn't work on Windows; pass a connected socket there.

## allow_agent

`cnopts.allow_agent = True` also offers the keys held by your ssh-agent, after the key you pass or
the default key files. A key that was already offered isn't offered again. The default, `False`,
leaves the agent alone. *New in 0.4.0.*

```python
cnopts = pysftp.CnOpts()
cnopts.allow_agent = True
with pysftp.Connection("sftp.example.com", username="me", cnopts=cnopts) as sftp:
    print(sftp.listdir())
```

Like every key, agent keys are offered only after the server's host key has been verified. Offering
a key tells the server you hold it, which is why this is off by default. pysftp-ng closes its
connection to the agent once the login is done, and never forwards the agent to the server.

On Windows, paramiko doesn't read `SSH_AUTH_SOCK`. It asks Pageant if that's running, and otherwise
the ssh-agent service that comes with Windows' OpenSSH. The service is disabled by default:
Microsoft's [key management guide](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)
shows how to start it and add your keys with `ssh-add`.

## ssh_config

`cnopts.ssh_config` reads four settings for the host from an OpenSSH config file: `HostName`,
`Port`, `User` and `IdentityFile`. Set it to `True` for `~/.ssh/config`, or to the path of another
file. The default, `None`, reads no config. *New in 0.4.0.*

```text
Host reports
    HostName sftp.example.com
    Port 2222
    User me
    IdentityFile ~/.ssh/id_ed25519
```

```python
cnopts = pysftp.CnOpts()
cnopts.ssh_config = True
with pysftp.Connection("reports", cnopts=cnopts) as sftp:
    print(sftp.listdir())
```

- Arguments you pass to `Connection` win. The config's `Port` applies when you leave `port` at 22.
- When you pass neither a password nor a key, the `IdentityFile` keys replace the default key files.
- paramiko expands every `~` in an `IdentityFile`, where OpenSSH expands only a leading one. A path
  with a `~` inside it, such as a Windows short name like `C:\Users\JOHNSM~1\.ssh\id_ed25519`, then
  points somewhere else, so write such paths out in full.
- As with `ssh`, the host key is looked up for the `HostName` and port, so here `known_hosts` needs
  an entry for `[sftp.example.com]:2222`.
- Other settings, such as `ProxyCommand` and `ProxyJump`, aren't used. For a jump host, see `sock`
  above.
- paramiko reads the file and evaluates `Match` blocks as `ssh` does, including `Match exec`, which
  runs the command it names. Only point this option at a config file you trust.
