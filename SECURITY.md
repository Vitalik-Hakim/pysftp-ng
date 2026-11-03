# Security policy

## Supported versions

Security fixes go into the latest release. pysftp-ng is a drop-in replacement for pysftp 0.2.9,
which gets no further fixes, so upgrading to pysftp-ng is the fix for issues in the original.

## Reporting a vulnerability

Please don't open a public issue for security problems. Report them privately through GitHub:
open the repository's **Security** tab and choose **Report a vulnerability**.

Include what you found, how to reproduce it, and which versions of pysftp-ng, paramiko and
Python you used. You'll get an acknowledgement within 72 hours and a plan for a fix within a
week. You'll be credited in the release notes unless you'd rather not be.

## What counts

Anything that weakens what pysftp-ng promises is in scope. Examples:

- host key verification being skipped or bypassed
- credentials being sent before the server is verified
- files written outside the directory a transfer was aimed at
- private key material leaking into logs or exceptions

Bugs in paramiko itself should go to the [paramiko project](https://github.com/paramiko/paramiko).
