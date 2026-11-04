# pysftp-ng

pysftp-ng is a maintained, drop-in fork of [pysftp](https://pypi.org/project/pysftp/) 0.2.9. Your
code still says `import pysftp` and uses the same API, and it works with paramiko 3.4 to 5.x and
Python 3.9 to 3.14.

pysftp 0.2.9 no longer imports with paramiko 4.0 and later. If that's why you're here, start with
[Migrating from pysftp](migrating.md).

## Install

```bash
pip install pysftp-ng
```

Uninstall pysftp first if it's installed: both packages provide the same `pysftp` module.

## Example

```python
import pysftp

with pysftp.Connection("sftp.example.com", username="me", private_key="~/.ssh/id_ed25519") as sftp:
    sftp.put("report.csv", "/upload/report.csv")
    sftp.get("/download/data.csv", "data.csv")
```

The server's host key must be in `~/.ssh/known_hosts`; [Host keys](hostkeys.md) explains why and
how to add it.

```{toctree}
:hidden:
:caption: Guide

migrating
hostkeys
authentication
cookbook
```

```{toctree}
:hidden:
:caption: Reference

api
compatibility
changelog
security
contributing
```
