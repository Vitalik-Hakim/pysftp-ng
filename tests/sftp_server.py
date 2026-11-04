"""A small in-process SSH/SFTP server for the test suite, built on paramiko.

It serves a temporary directory as "/", accepts password and public key
logins, answers two fake exec commands (``echo ...`` and ``fail ...``) and
can be told to slip hostile file names into directory listings.
"""

from __future__ import annotations

import os
import posixpath
import socket
import stat
import threading
import time
from collections import Counter

import paramiko
from paramiko import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_SUCCEEDED,
    SFTP_FAILURE,
    SFTP_OK,
    SFTPAttributes,
    SFTPHandle,
    SFTPServer,
    SFTPServerInterface,
)


def _errno(exc: OSError) -> int:
    return SFTPServer.convert_errno(exc.errno)


def _set_attrs(path: str, attr: SFTPAttributes) -> None:
    """Like SFTPServer.set_file_attr, but truncates without zero-filling
    (paramiko's helper reopens the file with "w+", wiping its contents)."""
    if attr._flags & attr.FLAG_SIZE:
        os.truncate(path, attr.st_size)
        attr._flags &= ~attr.FLAG_SIZE
    SFTPServer.set_file_attr(path, attr)


class _Handle(SFTPHandle):
    def stat(self):
        fobj = getattr(self, "readfile", None) or self.writefile
        try:
            return SFTPAttributes.from_stat(os.fstat(fobj.fileno()))
        except OSError as exc:
            return _errno(exc)

    def chattr(self, attr):
        try:
            _set_attrs(self.filename, attr)
        except OSError as exc:
            return _errno(exc)
        return SFTP_OK


class RootedSFTP(SFTPServerInterface):
    """SFTP operations confined to ``root``; the session's cwd is "/"."""

    def __init__(self, server, *args, root, inject=(), calls=None, **kwargs):
        super().__init__(server, *args, **kwargs)
        self.root = root
        self.inject = tuple(inject)
        self.calls = calls if calls is not None else Counter()

    # path helpers -------------------------------------------------------
    def _virtual(self, path):
        """``path`` as an absolute path below the root, normalized lexically."""
        path = path or "."
        if not path.startswith("/"):
            path = "/" + path
        return posixpath.normpath(path).replace("//", "/")

    def _real(self, path):
        return os.path.join(self.root, self._virtual(path).lstrip("/"))

    def canonicalize(self, path):
        """Answer a realpath request the way OpenSSH's sftp-server does: follow
        symlinks, and fail unless every part of the path but the last exists."""
        parts = [part for part in (path or ".").split("/") if part]
        real = os.path.join(self.root, *parts)
        if parts and not os.path.isdir(os.path.dirname(real)):
            raise FileNotFoundError(path)  # paramiko replies with "Failure"
        resolved = os.path.relpath(os.path.realpath(real), os.path.realpath(self.root))
        if resolved == os.curdir:
            return "/"
        if resolved == os.pardir or resolved.startswith(os.pardir + os.sep):
            raise PermissionError(path)  # it leads outside the served directory
        return "/" + resolved.replace(os.sep, "/")

    # operations -----------------------------------------------------------
    def list_folder(self, path):
        self.calls["list_folder"] += 1
        real = self._real(path)
        try:
            out = []
            for name in os.listdir(real):
                attr = SFTPAttributes.from_stat(os.lstat(os.path.join(real, name)))
                attr.filename = name
                out.append(attr)
        except OSError as exc:
            return _errno(exc)
        for name in self.inject:
            fake = SFTPAttributes()
            fake.filename = name
            fake.st_mode = stat.S_IFREG | 0o644
            fake.st_size = 0
            out.append(fake)
        return out

    def stat(self, path):
        self.calls["stat"] += 1
        try:
            return SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as exc:
            return _errno(exc)

    def lstat(self, path):
        self.calls["lstat"] += 1
        try:
            return SFTPAttributes.from_stat(os.lstat(self._real(path)))
        except OSError as exc:
            return _errno(exc)

    def open(self, path, flags, attr):
        real = self._real(path)
        try:
            flags |= getattr(os, "O_BINARY", 0)
            mode = getattr(attr, "st_mode", None)
            fd = os.open(real, flags, mode if mode is not None else 0o666)
        except OSError as exc:
            return _errno(exc)
        if (flags & os.O_CREAT) and attr is not None:
            attr._flags &= ~attr.FLAG_PERMISSIONS
            _set_attrs(real, attr)
        if flags & os.O_WRONLY:
            fstr = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            fstr = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            fstr = "rb"
        try:
            fobj = os.fdopen(fd, fstr)
        except OSError as exc:
            return _errno(exc)
        handle = _Handle(flags)
        handle.filename = real
        handle.readfile = fobj
        handle.writefile = fobj
        return handle

    def remove(self, path):
        try:
            os.remove(self._real(path))
        except OSError as exc:
            return _errno(exc)
        return SFTP_OK

    def rename(self, oldpath, newpath):
        old, new = self._real(oldpath), self._real(newpath)
        # Like OpenSSH, refuse to replace an existing path. os.rename would
        # replace it on Linux and macOS, and refuse on Windows.
        if os.path.lexists(old) and os.path.lexists(new):
            return SFTP_FAILURE
        try:
            os.rename(old, new)
        except OSError as exc:
            return _errno(exc)
        return SFTP_OK

    def mkdir(self, path, attr):
        real = self._real(path)
        try:
            os.mkdir(real)
            if attr is not None:
                _set_attrs(real, attr)
        except OSError as exc:
            return _errno(exc)
        return SFTP_OK

    def rmdir(self, path):
        try:
            os.rmdir(self._real(path))
        except OSError as exc:
            return _errno(exc)
        return SFTP_OK

    def chattr(self, path, attr):
        try:
            _set_attrs(self._real(path), attr)
        except OSError as exc:
            return _errno(exc)
        return SFTP_OK

    def symlink(self, target_path, path):
        target = self._real(target_path) if target_path.startswith("/") else target_path
        try:
            os.symlink(target, self._real(path))
        except OSError as exc:
            return _errno(exc)
        return SFTP_OK

    def readlink(self, path):
        try:
            target = os.readlink(self._real(path))
        except OSError as exc:
            return _errno(exc)
        if os.path.isabs(target) and target.startswith(self.root):
            target = "/" + os.path.relpath(target, self.root)
        return target


class _Auth(paramiko.ServerInterface):
    def __init__(self, srv: SFTPTestServer):
        self.srv = srv

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_auth_password(self, username, password):
        self.srv.password_attempts.append(username)
        if username == self.srv.username and password == self.srv.password:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_auth_publickey(self, username, key):
        self.srv.publickey_attempts.append(key.get_name())
        blob = key.asbytes()
        if username == self.srv.username and any(
            blob == known.asbytes() for known in self.srv.authorized_keys
        ):
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return OPEN_SUCCEEDED
        return OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        cmd = command.decode() if isinstance(command, bytes) else command

        def run():
            # let paramiko send its reply to the exec request first
            time.sleep(0.1)
            if cmd.startswith("echo "):
                channel.sendall((cmd[5:] + "\n").encode())
                status = 0
            elif cmd.startswith("fail "):
                channel.sendall_stderr((cmd[5:] + "\n").encode())
                status = 1
            else:
                channel.sendall_stderr(b"unknown command\n")
                status = 127
            channel.send_exit_status(status)
            channel.shutdown_write()
            channel.close()

        threading.Thread(target=run, daemon=True).start()
        return True


class SFTPTestServer:
    """Listens on 127.0.0.1 on a free port until close() is called."""

    def __init__(
        self,
        root: str,
        host_keys,
        username: str = "tester",
        password: str = "secret",
        authorized_keys=(),
        inject_names=(),
    ):
        self.root = root
        self.host_keys = list(host_keys)
        self.username = username
        self.password = password
        self.authorized_keys = list(authorized_keys)
        self.inject_names = tuple(inject_names)
        self.password_attempts: list[str] = []
        self.publickey_attempts: list[str] = []
        self.calls: Counter = Counter()
        self._transports: list[paramiko.Transport] = []
        self._stop = threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(client,), daemon=True).start()

    def _session(self, client):
        transport = paramiko.Transport(client)
        self._transports.append(transport)
        for key in self.host_keys:
            transport.add_server_key(key)
        transport.set_subsystem_handler(
            "sftp",
            SFTPServer,
            RootedSFTP,
            root=self.root,
            inject=self.inject_names,
            calls=self.calls,
        )
        try:
            transport.start_server(server=_Auth(self))
        except (paramiko.SSHException, EOFError, OSError):
            transport.close()

    def close(self):
        self._stop.set()
        self._listener.close()
        for transport in self._transports:
            transport.close()
