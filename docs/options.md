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
