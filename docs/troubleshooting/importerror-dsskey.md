# ImportError: cannot import name 'DSSKey' from 'paramiko'

`import pysftp` fails with this error when pysftp 0.2.9 is installed with paramiko 4.0 or later:

```text
Traceback (most recent call last):
  ...
ImportError: cannot import name 'DSSKey' from 'paramiko' (.../site-packages/paramiko/__init__.py). Did you mean: 'RSAKey'?
```

The path depends on your environment, and the "Did you mean" hint appears on Python 3.12 and later.

## Why it happens

pysftp 0.2.9, the last pysftp release (July 2016), runs `from paramiko import AgentKey, RSAKey,
DSSKey` as soon as it is imported. paramiko 4.0.0, released on 3 August 2025, removed DSA support,
including the `DSSKey` class. pysftp requires `paramiko>=1.17` with no upper limit, so a fresh
install picks up paramiko 4 or 5. The import then fails, even if you never use a DSA key.

## Fix

Replace pysftp with pysftp-ng, which keeps the `pysftp` module and its API:

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

Your code doesn't change. In `requirements.txt` or `pyproject.toml`, replace `pysftp` with
`pysftp-ng`, as [Migrating from pysftp](../migrating.md) shows.

If you can't change packages yet, pinning `paramiko<4` keeps pysftp 0.2.9 importing, but it holds
you on an old paramiko.

## Check that it's fixed

```bash
python -c "import pysftp, paramiko; print(pysftp.__version__, paramiko.__version__)"
```

This prints the pysftp-ng version, 0.3.1 or later, next to paramiko 4 or 5.
