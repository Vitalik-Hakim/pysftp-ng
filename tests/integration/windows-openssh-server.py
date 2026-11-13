"""Start the OpenSSH server built into Windows for the integration tests, then print the
PYSFTP_INTEGRATION_* settings that point the tests at it.

Run it as an administrator on a throwaway Windows machine, such as a GitHub Actions
runner: it installs the OpenSSH Server feature, adds a local user, and starts sshd and the
ssh-agent service. The user's password comes from PYSFTP_INTEGRATION_PASSWORD, which the
tests read as well, so this script never prints it.

    $env:PYSFTP_INTEGRATION_PASSWORD = "<a new random password>"
    python tests/integration/windows-openssh-server.py >> $env:GITHUB_ENV

Whoever runs it reads its output, so nothing but the settings may reach stdout.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HOST = "127.0.0.1"
PORT = 2222
USER = "pysftp"
OPENSSH = Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH")
SSHD_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData"), "ssh")
SSHD_CONFIG = SSHD_DIR / "sshd_config"
SSHD_LOG = SSHD_DIR / "logs" / "sshd.log"  # written because of SyslogFacility LOCAL0


def run(*command: str) -> None:
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def powershell(command: str) -> None:
    run("powershell", "-NoProfile", "-NonInteractive", "-Command", command)


def wait_for(port: int, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            socket.create_connection((HOST, port), timeout=2).close()
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def keyscan(known_hosts: Path) -> None:
    """Record every host key the server offers, as tests/integration/openssh-server.sh does."""
    for _ in range(60):
        found = subprocess.run(
            [str(OPENSSH / "ssh-keyscan.exe"), "-p", str(PORT), HOST],
            capture_output=True,
            text=True,
        ).stdout
        if found.strip():
            known_hosts.write_text(found)
            return
        time.sleep(1)
    sys.exit("The OpenSSH server didn't answer ssh-keyscan")


def login_failed(what: str) -> None:
    """Exit, showing the end of sshd's log, which says why it refused the login."""
    if SSHD_LOG.exists():
        lines = SSHD_LOG.read_text(errors="replace").splitlines(True)
        print("--- end of sshd.log\n" + "".join(lines[-40:]), file=sys.stderr)
    sys.exit(f"sshd refused the {what}; its log is above")


def main() -> None:
    password = os.environ.get("PYSFTP_INTEGRATION_PASSWORD")
    if not password:
        sys.exit("Set PYSFTP_INTEGRATION_PASSWORD to the password for the new user")
    # resolve() gives the long form of the path. %TEMP% can use an 8.3 short name such as
    # RUNNER~1, and paramiko's ssh_config expands every ~ in an IdentityFile, not only a
    # leading one.
    work = Path(tempfile.mkdtemp(prefix="pysftp-windows-sshd-")).resolve()

    for feature in ("OpenSSH.Server~~~~0.0.1.0", "OpenSSH.Client~~~~0.0.1.0"):
        powershell(f"Add-WindowsCapability -Online -Name {feature}")
    run("net", "user", USER, password, "/add", "/y")
    # The allow_agent test uses the ssh-agent service, which is disabled until it's set up.
    powershell("Set-Service -Name ssh-agent -StartupType Manual; Start-Service ssh-agent")

    # The first start writes sshd_config and the host keys. Then move sshd to PORT, so
    # known_hosts gets [host]:port entries, as with the Linux server, and have it log to
    # SSHD_LOG. Options near the top of sshd_config win.
    powershell("Set-Service -Name sshd -StartupType Manual; Start-Service sshd")
    wait_for(22)
    powershell("Stop-Service sshd")
    # Windows Server 2025's sshd_config admits only the groups that AllowGroups names:
    # administrators and "openssh users". Join the second, as an administrator would.
    if subprocess.run(["net", "localgroup", "OpenSSH Users"], capture_output=True).returncode == 0:
        run("net", "localgroup", "OpenSSH Users", USER, "/add")
    config = SSHD_CONFIG.read_text(encoding="utf-8-sig")  # drops a byte order mark, if any
    settings = f"Port {PORT}\nSyslogFacility LOCAL0\nLogLevel DEBUG\n"
    SSHD_CONFIG.write_text(settings + config, encoding="utf-8")
    powershell("Start-Service sshd")
    wait_for(PORT)

    known_hosts = work / "known_hosts"
    keyscan(known_hosts)
    hostkey = paramiko.HostKeys(str(known_hosts)).lookup(f"[{HOST}]:{PORT}")["ssh-ed25519"]

    key = Ed25519PrivateKey.generate()
    key_path = work / "id_ed25519"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
    )
    # Windows' ssh-add refuses a private key whose ACL lets another account use it, and counts
    # OWNER RIGHTS as one. The key gets that entry from mkdtemp's folder, and removing it takes
    # both steps: /inheritance:r, so the folder can't hand it back whenever the ACL changes,
    # and /remove for the copy the key already has. The current user gets an entry, so the
    # key is theirs to read without an administrator's token.
    me = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
    run("icacls", str(key_path), "/inheritance:r", "/grant:r", f"{me}:F")
    run("icacls", str(key_path), "/remove", "*S-1-3-4")
    public = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )

    # The first login creates the user's profile, and with it their home directory. The
    # public key goes in over SFTP, so the file belongs to the user, as sshd requires.
    transport = paramiko.Transport((HOST, PORT))
    try:
        try:
            transport.connect(hostkey=hostkey, username=USER, password=password)
        except paramiko.AuthenticationException:
            login_failed("password")
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.mkdir(".ssh")
        with sftp.open(".ssh/authorized_keys", "w") as fobj:
            fobj.write(public + b" pysftp-integration\n")
    finally:
        transport.close()

    transport = paramiko.Transport((HOST, PORT))
    try:
        pkey = paramiko.Ed25519Key.from_private_key_file(str(key_path))
        transport.connect(hostkey=hostkey, username=USER, pkey=pkey)
    except paramiko.AuthenticationException:
        login_failed("key in .ssh/authorized_keys")
    finally:
        transport.close()

    print(f"PYSFTP_INTEGRATION_HOST={HOST}")
    print(f"PYSFTP_INTEGRATION_PORT={PORT}")
    print(f"PYSFTP_INTEGRATION_USER={USER}")
    print(f"PYSFTP_INTEGRATION_KEY={key_path}")
    print(f"PYSFTP_INTEGRATION_KNOWN_HOSTS={known_hosts}")
    print("PYSFTP_INTEGRATION_SERVER_OS=windows")


if __name__ == "__main__":
    main()
