# Migrating from pysftp

pysftp-ng installs the same `pysftp` module as pysftp 0.2.9, with the same API, so moving to it is a
dependency change. Your code doesn't change.

## Switch packages

```bash
pip uninstall -y pysftp
pip install pysftp-ng
```

```{warning}
Don't install both packages. They provide the same `pysftp` module, so the one installed last
overwrites the other's files, and uninstalling either one removes the module.
```

## Update your requirements

Replace `pysftp` with `pysftp-ng` wherever you declare dependencies.

In `requirements.txt`:

```text
pysftp-ng>=0.3.1
```

In `pyproject.toml`:

```toml
[project]
dependencies = [
    "pysftp-ng>=0.3.1",
]
```

In `setup.py` or `setup.cfg`, change `install_requires` the same way. With Poetry or uv, remove
`pysftp` and add `pysftp-ng`:

```bash
poetry remove pysftp && poetry add pysftp-ng
uv remove pysftp && uv add pysftp-ng
```

If you pinned paramiko below 4 to keep pysftp importing, you can remove that pin. pysftp-ng works
with paramiko 3.4 to 5.x.

## What changes for your code

Nothing in the API: every public name, argument and default from pysftp 0.2.9 is kept until 1.0.
The behaviour changes are bug fixes, and the [changelog](changelog.md) lists each one. The ones
you are most likely to notice:

- Hosts on a non-standard port are found in `known_hosts` in OpenSSH's `[host]:port` form.
- A server key that doesn't match `known_hosts` raises `paramiko.BadHostKeyException`. It is a
  subclass of `SSHException`, so existing `except SSHException` blocks still catch it.
- Ed25519 and ECDSA key files work.

## Check that it worked

```bash
python -c "import pysftp; print(pysftp.__version__)"
```

This prints the pysftp-ng version, 0.3.1 or later. `pip show pysftp` should report that the package
isn't installed.
