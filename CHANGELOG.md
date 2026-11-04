# Changelog

All notable changes are listed here. pysftp-ng follows [Semantic Versioning](https://semver.org/).
Until 1.0, minor releases may deprecate things but won't remove anything from the pysftp 0.2.9
API.

## 0.3.1 (unreleased)

## 0.3.0 (2026-11-04)

First release of pysftp-ng, forked from pysftp 0.2.9 (released 2016-07-04).

### Fixed

- `import pysftp` no longer fails on paramiko 4.0 and later, which removed `DSSKey`.
- Ed25519 and ECDSA private key files now load, encrypted or not, in OpenSSH or PEM format.
  Any `paramiko.PKey` object, not only `RSAKey` or `AgentKey`, can be passed as `private_key`.
- With no password or key given, the default keys `~/.ssh/id_rsa`, `id_ecdsa` and `id_ed25519`
  (and `id_dsa` on paramiko < 4) are each tried, and the first one the server accepts is used.
- known_hosts entries in OpenSSH's `[host]:port` form, plain or hashed, are now found for servers
  on non-standard ports. Bare hostname entries still work.
- Host key verification now negotiates only key types listed in known_hosts and accepts any
  matching key, instead of pinning the first key found. This fixes "Incompatible ssh peer
  (no acceptable host key)" when a retired key type or an old `ssh-dss` line came first.
- A connection that fails part-way no longer raises
  `AttributeError: 'Connection' object has no attribute '_sftp_live'` from `__del__`, and its
  transport is closed instead of left running.
- `close()` removes only the log handler the connection added and restores the logger's level.
  It used to delete every handler on the `paramiko` logger.
- `put_r` and `put_d` join remote paths with `/` on every OS instead of `os.path.join`, which sent
  backslashes from Windows. They no longer `chdir` the whole process.
- `get_r` builds local paths correctly on Windows, creates missing local directories, and
  reports broken symlinks to the unknown-type callback instead of crashing.
- `walktree` uses one `listdir_attr` call per directory instead of a `stat` per entry.
- `get_r`, `get_d` and `walktree` skip, with a `RuntimeWarning`, file names from the server that
  would escape the target directory (for example `../x`).
- `execute()` closes its channel.
- `makedirs` splits remote paths with `posixpath`.
- The missing-known_hosts warning reads "disable HostKey checking" (it said "disableHostKey").
- `path_advance` and `path_retreat` handle an empty path.

### Added

- `CnOpts.timeout`: limit, in seconds, for the TCP connection, SSH banner, key exchange and
  authentication.
- `CnOpts.get_hostkey(host, port=22)` takes an optional port.
- `BadHostKeyException` and `PasswordRequiredException` are re-exported from `pysftp`.
- Type hints and a `py.typed` marker.
- An in-process SFTP server and a test suite covering the API across Python and paramiko
  versions.

### Changed

- Requires Python 3.9+ and paramiko 3.4+. paramiko 3.4 is the first release with the fix for the
  Terrapin attack (CVE-2023-48795).
- A server key that doesn't match known_hosts raises `paramiko.BadHostKeyException`. It is a
  subclass of `SSHException`, so existing `except SSHException` blocks still catch it.
- Connection refused or unreachable still raises `SSHException("Unable to connect to ...")`, but
  pysftp-ng now opens the socket itself, so a failed connect no longer leaks it.
- `str(ConnectionException)` is now the human-readable message. `.args` is unchanged.
- The deprecated `log` and `ciphers` arguments to `Connection` are no longer scheduled for removal
  in 0.3.0. They will be removed no earlier than 1.0.
- If no username is given and `LOGNAME` isn't set, the current OS user is used (`getpass.getuser()`).

For changes before the fork, see the pysftp 0.2.9 changelog.
