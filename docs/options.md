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
