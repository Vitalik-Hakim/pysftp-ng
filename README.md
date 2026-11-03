# pysftp-ng

[![CI](https://github.com/Vitalik-Hakim/pysftp-ng/actions/workflows/ci.yml/badge.svg)](https://github.com/Vitalik-Hakim/pysftp-ng/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pysftp-ng.svg)](https://pypi.org/project/pysftp-ng/)
[![Python](https://img.shields.io/pypi/pyversions/pysftp-ng.svg)](https://pypi.org/project/pysftp-ng/)

A maintained, drop-in fork of [pysftp](https://pypi.org/project/pysftp/). Your code still says
`import pysftp` and uses the same API, but it now works with current paramiko (3.4 through 5.x)
and Python 3.9 through 3.14.

## Why this exists

pysftp 0.2.9 came out in July 2016 and is still installed around 11.8 million times a month.
It no longer works with current dependencies. paramiko 4.0 removed DSA keys, so a fresh
`pip install pysftp` now fails the moment you import it:

```
ImportError: cannot import name 'DSSKey' from 'paramiko'
```

There has been no upstream release since 2016. pysftp-ng fixes that break and a set of
long-standing bugs, and keeps the API stable so existing code keeps running.

## Switching over

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

No code changes are needed. In `requirements.txt` or `pyproject.toml`, replace `pysftp` with
`pysftp-ng`. Don't install both packages, because they provide the same `pysftp` module.

## Usage

```python
import pysftp

with pysftp.Connection("sftp.example.com", username="me", private_key="~/.ssh/id_ed25519") as sftp:
    sftp.put("report.csv", "/upload/report.csv")
    with sftp.cd("/download"):
        sftp.get_r(".", "local-copy")
```

Extra connection options go on a `CnOpts` object:

```python
cnopts = pysftp.CnOpts()  # loads ~/.ssh/known_hosts
cnopts.timeout = 10  # new: limit for connecting, the handshake and logging in

with pysftp.Connection(
    "sftp.example.com", port=2222, username="me", password="...", cnopts=cnopts
) as sftp:
    print(sftp.listdir())
```

## What's fixed compared with pysftp 0.2.9

Each item below has a test in `tests/`. Tests marked `regression` reproduce bugs in pysftp 0.2.9.

- **paramiko 4 and 5.** Imports and runs without DSA. On paramiko < 4, DSA keys still work.
- **Modern keys.** Ed25519 and ECDSA key files work, encrypted or not, in OpenSSH or PEM format.
  You can also pass any paramiko key object, such as `Ed25519Key` or `AgentKey`, as `private_key`.
- **Default keys.** With no password or key given, pysftp-ng tries `~/.ssh/id_rsa`, `id_ecdsa` and
  `id_ed25519` in OpenSSH's order and uses the first one the server accepts. 0.2.9 only looked
  for `id_rsa` and `id_dsa`.
- **known_hosts on non-standard ports.** OpenSSH stores these as `[host]:port`, including in hashed
  form. pysftp-ng finds them; 0.2.9 failed with "No hostkey for host ... found".
- **Hosts with several known keys.** pysftp-ng only negotiates key types that are in known_hosts
  and accepts any key that matches. 0.2.9 pinned whichever key was listed first. If the server had
  retired that key type, or the first line was an old `ssh-dss` key, the connection failed with
  "Incompatible ssh peer".
- **Cleaner failures.** No more `AttributeError: 'Connection' object has no attribute '_sftp_live'`
  hiding the real error. A failed connection closes its transport.
- **Logging.** `close()` removes only the log handler it added. 0.2.9 removed every handler on the
  `paramiko` logger, including your application's.
- **Windows paths.** `put_r` and `put_d` build remote paths with `/` on every OS (0.2.9 sent
  backslashes from Windows), and they no longer change the process's working directory.
- **`get_r`.** Works on Windows clients, creates missing local directories, and no longer crashes
  on a broken symlink.
- **Speed.** `walktree` sends one listing request per directory instead of one `stat` per entry.
- **Path traversal.** If a server returns a file name that would land outside the target
  directory, such as `../../.bashrc`, `get_r`, `get_d` and `walktree` skip it with a warning.
- **Smaller fixes.** New `CnOpts.timeout` option. The username falls back to the OS user when
  `LOGNAME` isn't set, as on Windows. `ConnectionException` has a readable message.

## Compatibility

- The public API of pysftp 0.2.9 is kept: same names, arguments and return values. The deprecated
  `log` and `ciphers` arguments still work and emit a `DeprecationWarning`.
- Behaviour changes are limited to the fixes above. The [changelog](CHANGELOG.md) lists every one.
- The test suite runs against Python 3.9–3.14 and paramiko 3.4, 3.5, 4.0 and 5.1. It uses an
  in-process SFTP server, so no external server is needed.

## Security

Host key checking is on by default and verifies the server before any password or key is sent.
Setting `cnopts.hostkeys = None` turns verification off and exposes you to man-in-the-middle
attacks, so don't do it outside a test environment.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Credits

pysftp was written by Jeff Hinrichs (Dundee Media & Technology), with contributions from Don
Reilly, James Kruth and Nick Robinson-Wall. pysftp-ng is forked from the 0.2.9 release and keeps
its BSD 3-Clause license.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
