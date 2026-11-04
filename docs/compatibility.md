# Compatibility

pysftp-ng supports Python 3.9 to 3.14 and paramiko 3.4 to 5.x, and keeps the pysftp 0.2.9 API
unchanged until 1.0.

## What is tested

| What | Versions |
| --- | --- |
| Python on Linux | 3.9 to 3.14, each with paramiko 3.4.1 and the newest paramiko |
| macOS and Windows | Python 3.13 with the newest paramiko |
| Pre-release | The next Python pre-release, allowed to fail |
| Real server | OpenSSH 10.3 in Docker, with the newest paramiko |

CI runs on every change and once a week, so a new paramiko or Python release that breaks something
shows up there. paramiko 3.4 is the oldest version supported because it is the first with the fix
for the Terrapin attack (CVE-2023-48795).

## Support policy

- **Python:** every CPython version that is not end of life and that the newest paramiko supports.
  A version is dropped in a minor release after it reaches end of life, and the changelog says so.
- **paramiko:** 3.4 and later. The minimum is raised only for a security reason or when a fix needs
  a newer API, and only in a minor release.
- **New Python versions** join CI once their first beta is out, and become fully supported when
  they are released.

## Versions and deprecations

pysftp-ng uses semantic versioning:

- **Patch releases** (0.3.x) carry fixes only.
- **Minor releases** (0.x.0) add opt-in features and may deprecate parts of the pysftp 0.2.9 API,
  but never remove them.
- **Removals** wait for 1.0, after at least one minor release of warnings.

A deprecated feature raises a `DeprecationWarning` that names its replacement and the earliest
version that will remove it. The `log` and `ciphers` arguments to `Connection` are deprecated in
favour of `CnOpts`, and stay until 1.0.
