"""A friendly Python SFTP interface.

pysftp-ng is a maintained fork of pysftp 0.2.9. It keeps the ``pysftp``
import name and public API, so existing code works unchanged, and it runs on
current paramiko (3.4 through 5.x) and Python (3.9 through 3.14).
"""

from __future__ import annotations

import getpass
import logging
import os
import posixpath
import socket
import tempfile
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from stat import S_ISDIR, S_ISLNK, S_ISREG
from typing import IO, Any, Union

import paramiko
from paramiko import (  # re-exported for pysftp 0.2.9 compatibility
    AgentKey,
    AuthenticationException,
    BadHostKeyException,
    PasswordRequiredException,
    RSAKey,
    SSHException,
)

try:  # DSA support was removed in paramiko 4.0; only re-export it where it exists.
    from paramiko import DSSKey  # noqa: F401
except ImportError:  # pragma: no cover - depends on the installed paramiko
    pass

from pysftp.exceptions import (
    ConnectionException,
    CredentialException,
    HostKeysException,
)
from pysftp.helpers import (  # part of the public API
    WTCallbacks,
    cd,
    known_hosts,
    path_advance,
    path_retreat,
    reparent,
    st_mode_to_int,
    walktree,
)

__version__ = "0.3.2"

__all__ = [
    "AgentKey",
    "AuthenticationException",
    "BadHostKeyException",
    "CnOpts",
    "Connection",
    "ConnectionException",
    "CredentialException",
    "HostKeysException",
    "PasswordRequiredException",
    "RSAKey",
    "SSHException",
    "WTCallbacks",
    "cd",
    "known_hosts",
    "path_advance",
    "path_retreat",
    "reparent",
    "st_mode_to_int",
    "walktree",
]

StrPath = Union[str, "os.PathLike[str]"]

# Default keys tried, in order, when neither a password nor a key is given.
# This is OpenSSH's order; id_rsa stays first so behaviour matches pysftp 0.2.9
# for anyone who has both an RSA key and a newer one.
_DEFAULT_KEY_FILES = ("id_rsa", "id_ecdsa", "id_ed25519", "id_dsa")

# Host key algorithms that can be negotiated for each key type stored in
# known_hosts. RSA keys are stored as "ssh-rsa" but are verified with SHA-2
# signatures on modern servers.
_HOSTKEY_ALGORITHMS = {
    "ssh-rsa": ("rsa-sha2-512", "rsa-sha2-256", "ssh-rsa"),
}

_LOG_FORMAT = "%(levelname)-.3s [%(asctime)s.%(msecs)03d] %(threadName)s %(name)s: %(message)s"
_LOG_DATEFMT = "%Y%m%d-%H:%M:%S"


class CnOpts:  # pylint:disable=r0903
    """additional connection options beyond authentication

    :ivar bool|str log: initial value: False -
        log connection/handshake details? If set to True,
        pysftp creates a temporary file and logs to that.  If set to a valid
        path and filename, pysftp logs to that.  The name of the logfile can
        be found at  ``.logfile``
    :ivar bool compression: initial value: False - Enables compression on the
        transport, if set to True.
    :ivar list|None ciphers: initial value: None -
        List of ciphers to use in order.
    :ivar float|None timeout: initial value: None - seconds to wait for the
        TCP connection, the SSH banner, key exchange and authentication.
        ``None`` waits as long as paramiko's own defaults allow (the pysftp
        0.2.9 behaviour). *New in pysftp-ng 0.3.0.*
    :ivar int keepalive: initial value: 0 - after this many seconds without
        traffic, send a keepalive packet, so that firewalls and NAT routers
        don't drop an idle connection. 0 sends none (the pysftp 0.2.9
        behaviour). *New in pysftp-ng 0.4.0.*
    :ivar socket|paramiko.ProxyCommand|None sock: initial value: None - an
        already-connected socket, or a ``paramiko.ProxyCommand``, to run the SSH
        session over instead of opening a TCP connection to the host, for
        example to reach a server through a jump host. The host key is still
        checked for the host and port you pass to Connection. The connection
        closes it, so it serves one connection only. *New in pysftp-ng 0.4.0.*
    :ivar bool allow_agent: initial value: False - also offer the keys in your
        ssh-agent, after the key you pass or the default key files. Like every
        key, they are offered only once the server's host key is verified.
        False leaves the agent alone (the pysftp 0.2.9 behaviour). *New in
        pysftp-ng 0.4.0.*
    :ivar paramiko.hostkeys.HostKeys|None hostkeys: HostKeys object to use for
        host key checking. Set to ``None`` to disable host key checking, which
        exposes you to man-in-the-middle attacks.
    :param filepath|None knownhosts: initial value: None - file to load
        hostkeys. If not specified, uses ~/.ssh/known_hosts
    :returns: (CnOpts) a connection options object, used for passing
        extended options to the Connection
    :raises HostKeysException:
    """

    def __init__(self, knownhosts: StrPath | None = None) -> None:
        self.log: bool | str = False
        self.compression: bool = False
        self.ciphers: list[str] | None = None
        self.timeout: float | None = None
        self.keepalive: int = 0
        self.sock: Any = None
        self.allow_agent: bool = False
        if knownhosts is None:
            knownhosts = known_hosts()
        knownhosts = os.fspath(knownhosts)
        self.hostkeys: paramiko.hostkeys.HostKeys | None = paramiko.hostkeys.HostKeys()
        try:
            self.hostkeys.load(knownhosts)
        except OSError:
            # can't find known_hosts in the standard place
            warnings.warn(
                f"Failed to load HostKeys from {knownhosts}.  You will need to "
                "explicitly load HostKeys (cnopts.hostkeys.load(filename)) or "
                "disable HostKey checking (cnopts.hostkeys = None).",
                UserWarning,
                stacklevel=2,
            )
        else:
            if len(self.hostkeys.items()) == 0:
                raise HostKeysException("No Host Keys Found")

    def _lookup(self, host: str, port: int = 22) -> dict[str, paramiko.PKey]:
        """return every known key for host as {keytype: PKey}.

        OpenSSH records hosts on a non-standard port as ``[host]:port``; that
        form is checked first, then the bare hostname (which is what pysftp
        0.2.9 required, so existing known_hosts files keep working).
        """
        if self.hostkeys is None:
            return {}
        candidates = [host]
        if port != 22:
            candidates.insert(0, f"[{host}]:{port}")
        for name in candidates:
            found = self.hostkeys.lookup(name)
            if found:
                return dict(found)
        return {}

    def get_hostkey(self, host: str, port: int = 22) -> paramiko.PKey:
        """return the matching hostkey to use for verification for the host
        indicated or raise an SSHException

        :param str host: hostname or IP address
        :param int port: *Default: 22* - port, used to find ``[host]:port``
            entries. *New in pysftp-ng 0.3.0.*
        """
        kval = self._lookup(host, port)
        if not kval:
            raise SSHException(f"No hostkey for host {host} found.")
        # return the pkey from the dict
        return next(iter(kval.values()))


class Connection:  # pylint:disable=r0902,r0904
    """Connects and logs into the specified hostname.
    Arguments that are not given are guessed from the environment.

    :param str host:
        The Hostname or IP of the remote machine.
    :param str|None username: *Default: None* -
        Your username at the remote machine.
    :param str|obj|None private_key: *Default: None* -
        path to private key file(str) or a paramiko key object
        (``paramiko.PKey``, including ``paramiko.AgentKey``)
    :param str|None password: *Default: None* -
        Your password at the remote machine.
    :param int port: *Default: 22* -
        The SSH port of the remote machine.
    :param str|None private_key_pass: *Default: None* -
        password to use, if private_key is encrypted.
    :param list|None ciphers: *Deprecated* -
        see ``pysftp.CnOpts`` and ``cnopts`` parameter
    :param bool|str log: *Deprecated* -
        see ``pysftp.CnOpts`` and ``cnopts`` parameter
    :param None|CnOpts cnopts: *Default: None* - extra connection options
        set in a CnOpts object.
    :param str|None default_path: *Default: None* -
        set a default path upon connection.
    :returns: (Connection) connection to the requested host
    :raises ConnectionException:
    :raises CredentialException:
    :raises SSHException:
    :raises AuthenticationException:
    :raises PasswordRequiredException:
    :raises HostKeysException:
    :raises BadHostKeyException: if the server's key doesn't match known_hosts

    """

    def __init__(  # pylint:disable=r0913
        self,
        host: str,
        username: str | None = None,
        private_key: StrPath | paramiko.PKey | None = None,
        password: str | None = None,
        port: int = 22,
        private_key_pass: str | None = None,
        ciphers: list[str] | None = None,
        log: bool | str = False,
        cnopts: CnOpts | None = None,
        default_path: str | None = None,
    ) -> None:
        # Set first, so close() and __del__ are safe however far __init__ gets.
        self._sftp_live = False
        self._sftp: paramiko.SFTPClient | None = None
        self._transport: paramiko.Transport | None = None
        self._log_handlers: list[logging.Handler] = []
        self._log_prev_level: int | None = None
        self._agent: paramiko.Agent | None = None
        # starting point for transport.connect options
        self._tconnect: dict[str, Any] = {
            "username": username,
            "password": password,
            "hostkey": None,
            "pkey": None,
        }
        self._cnopts = cnopts or CnOpts()
        self._default_path = default_path
        if log:
            warnings.warn(
                "log parameter is deprecated and will be removed in a future "
                "release. Use cnopts param.",
                DeprecationWarning,
                stacklevel=2,
            )
            self._cnopts.log = log
        if ciphers is not None:
            warnings.warn(
                "ciphers parameter is deprecated and will be removed in a "
                "future release. Use cnopts param.",
                DeprecationWarning,
                stacklevel=2,
            )
            self._cnopts.ciphers = ciphers
        keepalive = self._option("keepalive", 0)
        if keepalive < 0:
            raise ValueError("cnopts.keepalive must be 0 (off) or a number of seconds")
        # check that we have a hostkey to verify, before touching the network
        self._known_keys: dict[str, paramiko.PKey] | None = None
        if self._cnopts.hostkeys is not None:
            if getattr(type(self._cnopts), "get_hostkey", None) is CnOpts.get_hostkey:
                self._tconnect["hostkey"] = self._cnopts.get_hostkey(host, port)
                self._known_keys = self._cnopts._lookup(host, port)
            else:
                # get_hostkey(host) overridden with the 0.2.9 signature: trust
                # exactly the key it returns, as 0.2.9 did.
                key = self._cnopts.get_hostkey(host)
                self._tconnect["hostkey"] = key
                self._known_keys = {key.get_name(): key}

        self._set_username()
        try:
            pkeys = self._set_authentication(password, private_key, private_key_pass)
            self._set_logging()
            # Begin the SSH transport.
            self._start_transport(host, port)
            self._transport.use_compression(self._cnopts.compression)
            self._start_client(host)
            self._authenticate(password, pkeys)
            self._close_agent()
            if keepalive:
                self._transport.set_keepalive(keepalive)
        except BaseException:
            self.close()
            raise

    def _option(self, name: str, default: Any) -> Any:
        """Return a CnOpts option, or its default when cnopts doesn't have it, as with
        a pysftp 0.2.9-style subclass whose __init__ doesn't call CnOpts.__init__."""
        return getattr(self._cnopts, name, default)

    def _set_authentication(
        self,
        password: str | None,
        private_key: StrPath | paramiko.PKey | None,
        private_key_pass: str | None,
    ) -> list[paramiko.PKey]:
        """Work out which keys to offer. A password, if given, is preferred."""
        if password is not None:
            return []
        keys: list[paramiko.PKey] = []
        problem: Exception | None = None
        if isinstance(private_key, paramiko.PKey):
            # a paramiko key object, including an AgentKey from the ssh-agent
            keys.append(private_key)
        elif private_key:
            keys.append(_load_private_key(private_key, private_key_pass))
        else:
            # No key given: try the default keys that exist, in OpenSSH's order.
            ssh_dir = os.path.expanduser(os.path.join("~", ".ssh"))
            paths = [os.path.join(ssh_dir, name) for name in _DEFAULT_KEY_FILES]
            paths = [pth for pth in paths if os.path.isfile(pth)]
            if not paths:
                problem = CredentialException("No password or key specified.")
            for pth in paths:
                try:
                    keys.append(_load_private_key(pth, private_key_pass))
                except (SSHException, OSError) as exc:  # encrypted, unsupported, unreadable
                    problem = problem or exc
        if self._option("allow_agent", False):
            keys.extend(self._agent_keys(keys))
        if not keys:
            raise problem or CredentialException("No usable private key found.")
        self._tconnect["pkey"] = keys[0]
        return keys

    def _agent_keys(self, offered: list[paramiko.PKey]) -> list[paramiko.PKey]:
        """Return the ssh-agent's keys that aren't in offered already. The agent
        connection stays open for the login, which needs it to sign."""
        self._agent = paramiko.Agent()
        seen = {key.asbytes() for key in offered}
        return [key for key in self._agent.get_keys() if key.asbytes() not in seen]

    def _close_agent(self) -> None:
        agent = getattr(self, "_agent", None)
        if agent is not None:
            agent.close()
            self._agent = None

    def _start_transport(self, host: str, port: int) -> None:
        """start the transport and set the ciphers if specified."""
        timeout = self._option("timeout", None)
        sock = self._option("sock", None)
        try:
            if sock is None:
                # Open the socket ourselves (paramiko leaks it when the connect
                # fails) but keep paramiko's error type and message.
                try:
                    sock = socket.create_connection((host, port), timeout=timeout)
                except socket.gaierror:
                    raise
                except OSError as exc:  # refused, unreachable, timed out
                    raise SSHException(f"Unable to connect to {host}: {exc}") from exc
            self._transport = paramiko.Transport(sock)
            if timeout is not None:
                self._transport.banner_timeout = timeout
                self._transport.handshake_timeout = timeout
                self._transport.auth_timeout = timeout
            # Set security ciphers if set
            if self._cnopts.ciphers is not None:
                ciphers = self._cnopts.ciphers
                self._transport.get_security_options().ciphers = ciphers
        except (AttributeError, socket.gaierror) as exc:
            # couldn't connect
            raise ConnectionException(host, port) from exc

    def _start_client(self, host: str) -> None:
        """Negotiate the SSH session and verify the server's host key before
        any credentials are sent."""
        transport = self._transport
        known = self._known_keys
        if known is not None:
            # Only negotiate host key types we can verify. pysftp 0.2.9 pinned
            # whichever known key came first, so connections failed whenever
            # the server had dropped that key type.
            wanted: set[str] = set()
            for keytype in known:
                wanted.update(_HOSTKEY_ALGORITHMS.get(keytype, (keytype,)))
            options = transport.get_security_options()
            preferred = [alg for alg in options.key_types if alg in wanted]
            if not preferred:
                raise SSHException(
                    f"No usable hostkey for host {host} found: known_hosts only "
                    f"has {', '.join(sorted(known))}, which this version of "
                    "paramiko can't verify."
                )
            options.key_types = preferred

        transport.start_client(timeout=self._option("timeout", None))

        if known is not None:
            server_key = transport.get_remote_server_key()
            expected = known.get(server_key.get_name())
            if expected is None or expected != server_key:
                raise BadHostKeyException(host, server_key, expected or self._tconnect["hostkey"])
            self._tconnect["hostkey"] = expected

    def _authenticate(self, password: str | None, pkeys: list[paramiko.PKey]) -> None:
        """Authenticate with the password, or with each key in turn."""
        transport = self._transport
        username = self._tconnect["username"]
        if password is not None:
            transport.auth_password(username, password)
            return
        last_error: Exception | None = None
        for pkey in pkeys:
            try:
                transport.auth_publickey(username, pkey)
            except AuthenticationException as exc:
                last_error = exc
                continue
            self._tconnect["pkey"] = pkey
            return
        raise last_error or AuthenticationException("Authentication failed.")

    def _set_username(self) -> None:
        """set the username for the connection. If not passed, then look to the
        environment.  Still nothing? Throw exception."""
        if self._tconnect["username"] is None:
            username = os.environ.get("LOGNAME")
            if not username:
                try:
                    username = getpass.getuser()
                except Exception:  # pylint:disable=broad-except
                    username = None
            if not username:
                raise CredentialException("No username specified.")
            self._tconnect["username"] = username

    def _set_logging(self) -> None:
        """set logging for connection"""
        if not self._cnopts.log:
            return
        if isinstance(self._cnopts.log, bool):
            # Log to a temporary file.
            fhnd, self._cnopts.log = tempfile.mkstemp(".txt", "ssh-")
            os.close(fhnd)  # don't want os file descriptors open
        lgr = logging.getLogger("paramiko")
        handler = logging.FileHandler(self._cnopts.log)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))
        lgr.addHandler(handler)
        self._log_handlers.append(handler)
        if lgr.level == logging.NOTSET or lgr.level > logging.DEBUG:
            self._log_prev_level = lgr.level
            lgr.setLevel(logging.DEBUG)

    def _sftp_connect(self) -> None:
        """Establish the SFTP connection."""
        if not self._sftp_live:
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            if self._default_path is not None:
                self._sftp.chdir(self._default_path)
            self._sftp_live = True

    @property
    def pwd(self) -> str:
        """return the current working directory

        :returns: (str) current working directory

        """
        self._sftp_connect()
        return self._sftp.normalize(".")

    def get(
        self,
        remotepath: str,
        localpath: StrPath | None = None,
        callback: Callable[[int, int], object] | None = None,
        preserve_mtime: bool = False,
    ) -> None:
        """Copies a file between the remote host and the local host.

        :param str remotepath: the remote path and filename, source
        :param str localpath:
            the local path and filename to copy, destination. If not specified,
            file is copied to local current working directory
        :param callable callback:
            optional callback function (form: ``func(int, int)``) that accepts
            the bytes transferred so far and the total bytes to be transferred.
        :param bool preserve_mtime:
            *Default: False* - make the modification time(st_mtime) on the
            local file match the time on the remote. (st_atime can differ
            because stat'ing the localfile can/does update it's st_atime)

        :returns: None

        :raises: IOError

        """
        if not localpath:
            localpath = os.path.split(remotepath)[1]
        localpath = os.fspath(localpath)

        self._sftp_connect()
        if preserve_mtime:
            sftpattrs = self._sftp.stat(remotepath)

        self._sftp.get(remotepath, localpath, callback=callback)
        if preserve_mtime:
            os.utime(localpath, (sftpattrs.st_atime, sftpattrs.st_mtime))

    def get_d(self, remotedir: str, localdir: StrPath, preserve_mtime: bool = False) -> None:
        """get the contents of remotedir and write to locadir. (non-recursive)

        :param str remotedir: the remote directory to copy from (source)
        :param str localdir: the local directory to copy to (target)
        :param bool preserve_mtime: *Default: False* -
            preserve modification time on files

        :returns: None

        File names from the server that would write outside localdir are
        skipped with a RuntimeWarning.
        """
        localdir = os.fspath(localdir)
        self._sftp_connect()
        with self.cd(remotedir):
            for sattr in self._sftp.listdir_attr("."):
                if S_ISREG(sattr.st_mode):
                    rname = sattr.filename
                    if _unsafe_remote_name(rname):
                        _warn_unsafe(rname)
                        continue
                    self.get(rname, reparent(localdir, rname), preserve_mtime=preserve_mtime)

    def get_r(self, remotedir: str, localdir: StrPath, preserve_mtime: bool = False) -> None:
        """recursively copy remotedir structure to localdir

        As in pysftp 0.2.9, the remote path is re-created under localdir:
        ``get_r('pub/data', 'out')`` writes ``out/pub/data/...``.

        :param str remotedir: the remote directory to copy from
        :param str localdir: the local directory to copy to
        :param bool preserve_mtime: *Default: False* -
            preserve modification time on files

        File names from the server that would write outside localdir are
        skipped with a RuntimeWarning.

        :returns: None

        """
        localdir = os.fspath(localdir)
        self._sftp_connect()
        wtcb = WTCallbacks()
        self.walktree(remotedir, wtcb.file_cb, wtcb.dir_cb, wtcb.unk_cb)
        prefix = remotedir.rstrip("/") + "/" if remotedir.rstrip("/") else "/"

        def safe(rpath: str) -> bool:
            # Names below remotedir come from the server; drop any that would
            # escape localdir once mapped onto the local filesystem.
            below = rpath[len(prefix) :] if rpath.startswith(prefix) else rpath
            bad = [part for part in below.split("/") if _unsafe_remote_name(part)]
            if bad:
                _warn_unsafe(bad[0])
            return not bad

        dirs = [dname for dname in wtcb.dlist if safe(dname)]
        files = [fname for fname in wtcb.flist if safe(fname)]
        # handle directories we recursed through
        for dname in dirs:
            os.makedirs(_remote_to_local(localdir, dname), exist_ok=True)
        for fname in files:
            # they may have told us to start down farther, so we may not have
            # recursed through some, ensure local dir structure matches
            head = posixpath.dirname(fname)
            if head:
                os.makedirs(_remote_to_local(localdir, head), exist_ok=True)
            self.get(fname, _remote_to_local(localdir, fname), preserve_mtime=preserve_mtime)

    def getfo(
        self,
        remotepath: str,
        flo: IO[bytes],
        callback: Callable[[int, int], object] | None = None,
    ) -> int:
        """Copy a remote file (remotepath) to a file-like object, flo.

        :param str remotepath: the remote path and filename, source
        :param flo: open file like object to write, destination.
        :param callable callback:
            optional callback function (form: ``func(int, int``)) that accepts
            the bytes transferred so far and the total bytes to be transferred.

        :returns: (int) the number of bytes written to the opened file object

        :raises: Any exception raised by operations will be passed through.

        """
        self._sftp_connect()
        return self._sftp.getfo(remotepath, flo, callback=callback)

    def put(
        self,
        localpath: StrPath,
        remotepath: str | None = None,
        callback: Callable[[int, int], object] | None = None,
        confirm: bool = True,
        preserve_mtime: bool = False,
    ) -> paramiko.SFTPAttributes:
        """Copies a file between the local host and the remote host.

        :param str localpath: the local path and filename
        :param str remotepath:
            the remote path, else the remote :attr:`.pwd` and filename is used.
        :param callable callback:
            optional callback function (form: ``func(int, int``)) that accepts
            the bytes transferred so far and the total bytes to be transferred.
        :param bool confirm:
            whether to do a stat() on the file afterwards to confirm the file
            size
        :param bool preserve_mtime:
            *Default: False* - make the modification time(st_mtime) on the
            remote file match the time on the local. (st_atime can differ
            because stat'ing the localfile can/does update it's st_atime)

        :returns:
            (SFTPAttributes) attributes of the remote file

        :raises IOError: if remotepath doesn't exist
        :raises OSError: if localpath doesn't exist

        """
        localpath = os.fspath(localpath)
        if not remotepath:
            remotepath = os.path.split(localpath)[1]
        self._sftp_connect()

        if preserve_mtime:
            local_stat = os.stat(localpath)
            times = (local_stat.st_atime, local_stat.st_mtime)

        sftpattrs = self._sftp.put(localpath, remotepath, callback=callback, confirm=confirm)
        if preserve_mtime:
            self._sftp.utime(remotepath, times)
            sftpattrs = self._sftp.stat(remotepath)

        return sftpattrs

    def put_d(
        self,
        localpath: StrPath,
        remotepath: str,
        confirm: bool = True,
        preserve_mtime: bool = False,
    ) -> None:
        """Copies a local directory's contents to a remotepath

        :param str localpath: the local path to copy (source)
        :param str remotepath:
            the remote path to copy to (target)
        :param bool confirm:
            whether to do a stat() on the file afterwards to confirm the file
            size
        :param bool preserve_mtime:
            *Default: False* - make the modification time(st_mtime) on the
            remote file match the time on the local. (st_atime can differ
            because stat'ing the localfile can/does update it's st_atime)

        :returns: None

        :raises IOError: if remotepath doesn't exist
        :raises OSError: if localpath doesn't exist
        """
        localpath = os.fspath(localpath)
        self._sftp_connect()
        wtcb = WTCallbacks()
        walktree(localpath, wtcb.file_cb, wtcb.dir_cb, wtcb.unk_cb, recurse=False)
        for fname in wtcb.flist:
            dest = _local_to_remote(remotepath, os.path.relpath(fname, localpath))
            self.put(fname, dest, confirm=confirm, preserve_mtime=preserve_mtime)

    def put_r(
        self,
        localpath: StrPath,
        remotepath: str,
        confirm: bool = True,
        preserve_mtime: bool = False,
    ) -> None:
        """Recursively copies a local directory's contents to a remotepath

        :param str localpath: the local path to copy (source)
        :param str remotepath:
            the remote path to copy to (target)
        :param bool confirm:
            whether to do a stat() on the file afterwards to confirm the file
            size
        :param bool preserve_mtime:
            *Default: False* - make the modification time(st_mtime) on the
            remote file match the time on the local. (st_atime can differ
            because stat'ing the localfile can/does update it's st_atime)

        :returns: None

        :raises IOError: if remotepath doesn't exist
        :raises OSError: if localpath doesn't exist
        """
        localpath = os.fspath(localpath)
        self._sftp_connect()
        wtcb = WTCallbacks()
        walktree(localpath, wtcb.file_cb, wtcb.dir_cb, wtcb.unk_cb)
        for dname in wtcb.dlist:
            pth = _local_to_remote(remotepath, os.path.relpath(dname, localpath))
            if not self.isdir(pth):
                self.mkdir(pth)

        for fname in wtcb.flist:
            dest = _local_to_remote(remotepath, os.path.relpath(fname, localpath))
            self.put(fname, dest, confirm=confirm, preserve_mtime=preserve_mtime)

    def putfo(
        self,
        flo: IO[bytes],
        remotepath: str | None = None,
        file_size: int = 0,
        callback: Callable[[int, int], object] | None = None,
        confirm: bool = True,
    ) -> paramiko.SFTPAttributes:
        """Copies the contents of a file like object to remotepath.

        :param flo: a file-like object that supports .read()
        :param str remotepath: the remote path.
        :param int file_size:
            the size of flo, if not given the second param passed to the
            callback function will always be 0.
        :param callable callback:
            optional callback function (form: ``func(int, int``)) that accepts
            the bytes transferred so far and the total bytes to be transferred.
        :param bool confirm:
            whether to do a stat() on the file afterwards to confirm the file
            size

        :returns:
            (SFTPAttributes) attributes of the remote file

        :raises: TypeError, if remotepath not specified, any underlying error

        """
        self._sftp_connect()
        return self._sftp.putfo(
            flo, remotepath, file_size=file_size, callback=callback, confirm=confirm
        )

    def execute(self, command: str) -> list[bytes]:
        """Execute the given commands on a remote machine.  The command is
        executed without regard to the remote :attr:`.pwd`.

        :param str command: the command to execute.

        :returns: (list of bytes) the lines of standard output, or of standard
            error if there was no standard output

        :raises: Any exception raised by command will be passed through.

        """
        channel = self._transport.open_session()
        try:
            channel.exec_command(command)
            output = channel.makefile("rb", -1).readlines()
            if output:
                return output
            return channel.makefile_stderr("rb", -1).readlines()
        finally:
            channel.close()

    @contextmanager
    def cd(self, remotepath: str | None = None) -> Iterator[None]:  # pylint:disable=c0103
        """context manager that can change to a optionally specified remote
        directory and restores the old pwd on exit.

        :param str|None remotepath: *Default: None* -
            remotepath to temporarily make the current directory
        :returns: None
        :raises: IOError, if remote path doesn't exist
        """
        original_path = self.pwd
        try:
            if remotepath is not None:
                self.cwd(remotepath)
            yield
        finally:
            self.cwd(original_path)

    def chdir(self, remotepath: str) -> None:
        """change the current working directory on the remote

        :param str remotepath: the remote path to change to

        :returns: None

        :raises: IOError, if path does not exist

        """
        self._sftp_connect()
        self._sftp.chdir(remotepath)

    cwd = chdir  # synonym for chdir

    def chmod(self, remotepath: str, mode: int = 777) -> None:
        """set the mode of a remotepath to mode, where mode is an integer
        representation of the octal mode to use.

        :param str remotepath: the remote path/file to modify
        :param int mode: *Default: 777* -
            int representation of octal mode for directory

        :returns: None

        :raises: IOError, if the file doesn't exist

        """
        self._sftp_connect()
        self._sftp.chmod(remotepath, mode=int(str(mode), 8))

    def chown(self, remotepath: str, uid: int | None = None, gid: int | None = None) -> None:
        """set uid and/or gid on a remotepath, you may specify either or both.
        Unless you have **permission** to do this on the remote server, you
        will raise an IOError: 13 - permission denied

        :param str remotepath: the remote path/file to modify
        :param int uid: the user id to set on the remotepath
        :param int gid: the group id to set on the remotepath

        :returns: None

        :raises:
            IOError, if you don't have permission or the file doesn't exist

        """
        self._sftp_connect()
        if uid is None or gid is None:
            if uid is None and gid is None:  # short circuit if no change
                return
            rstat = self._sftp.stat(remotepath)
            if uid is None:
                uid = rstat.st_uid
            if gid is None:
                gid = rstat.st_gid

        self._sftp.chown(remotepath, uid=uid, gid=gid)

    def getcwd(self) -> str | None:
        """return the current working directory on the remote. This is a wrapper
        for paramiko's method and not to be confused with the SFTP command,
        cwd.

        :returns: (str) the current remote path. None, if not set.

        """
        self._sftp_connect()
        return self._sftp.getcwd()

    def listdir(self, remotepath: str = ".") -> list[str]:
        """return a list of files/directories for the given remote path.
        Unlike, paramiko, the directory listing is sorted.

        :param str remotepath: path to list on the server

        :returns: (list of str) directory entries, sorted

        """
        self._sftp_connect()
        return sorted(self._sftp.listdir(remotepath))

    def listdir_attr(self, remotepath: str = ".") -> list[paramiko.SFTPAttributes]:
        """return a list of SFTPAttribute objects of the files/directories for
        the given remote path. The list is in arbitrary order. It does not
        include the special entries '.' and '..'.

        The returned SFTPAttributes objects will each have an additional field:
        longname, which may contain a formatted string of the file's
        attributes, in unix format. The content of this string will depend on
        the SFTP server.

        :param str remotepath: path to list on the server

        :returns: (list of SFTPAttributes), sorted

        """
        self._sftp_connect()
        return sorted(self._sftp.listdir_attr(remotepath), key=lambda attr: attr.filename)

    def mkdir(self, remotepath: str, mode: int = 777) -> None:
        """Create a directory named remotepath with mode. On some systems,
        mode is ignored. Where it is used, the current umask value is first
        masked out.

        :param str remotepath: directory to create`
        :param int mode: *Default: 777* -
            int representation of octal mode for directory

        :returns: None

        """
        self._sftp_connect()
        self._sftp.mkdir(remotepath, mode=int(str(mode), 8))

    def normalize(self, remotepath: str) -> str:
        """Return the expanded path, w.r.t the server, of a given path.  This
        can be used to resolve symlinks or determine what the server believes
        to be the :attr:`.pwd`, by passing '.' as remotepath.

        :param str remotepath: path to be normalized

        :return: (str) normalized form of the given path

        :raises: IOError, if remotepath can't be resolved
        """
        self._sftp_connect()
        return self._sftp.normalize(remotepath)

    def isdir(self, remotepath: str) -> bool:
        """return true, if remotepath is a directory

        :param str remotepath: the path to test

        :returns: (bool)

        """
        self._sftp_connect()
        try:
            result = S_ISDIR(self._sftp.stat(remotepath).st_mode)
        except OSError:  # no such file
            result = False
        return result

    def isfile(self, remotepath: str) -> bool:
        """return true if remotepath is a file

        :param str remotepath: the path to test

        :returns: (bool)

        """
        self._sftp_connect()
        try:
            result = S_ISREG(self._sftp.stat(remotepath).st_mode)
        except OSError:  # no such file
            result = False
        return result

    def makedirs(self, remotedir: str, mode: int = 777) -> None:
        """create all directories in remotedir as needed, setting their mode
        to mode, if created.

        If remotedir already exists, silently complete. If a regular file is
        in the way, raise an exception.

        :param str remotedir: the directory structure to create
        :param int mode: *Default: 777* -
            int representation of octal mode for directory

        :returns: None

        :raises: OSError

        """
        self._sftp_connect()
        if self.isdir(remotedir):
            pass

        elif self.isfile(remotedir):
            raise OSError(
                f"a file with the same name as the remotedir, '{remotedir}', already exists."
            )
        else:
            head, tail = posixpath.split(remotedir)
            if head and not self.isdir(head):
                self.makedirs(head, mode)

            if tail:
                self.mkdir(remotedir, mode=mode)

    def readlink(self, remotelink: str) -> str:
        """Return the target of a symlink (shortcut).  The result will be
        an absolute pathname.

        :param str remotelink: remote path of the symlink

        :return: (str) absolute path to target

        """
        self._sftp_connect()
        target = self._sftp.readlink(remotelink)
        if target and not target.startswith("/"):
            # A relative target is relative to the directory holding the link.
            target = posixpath.join(posixpath.dirname(remotelink), target)
        return self._sftp.normalize(target)

    def remove(self, remotefile: str) -> None:
        """remove the file @ remotefile, remotefile may include a path, if no
        path, then :attr:`.pwd` is used.  This method only works on files

        :param str remotefile: the remote file to delete

        :returns: None

        :raises: IOError

        """
        self._sftp_connect()
        self._sftp.remove(remotefile)

    unlink = remove  # synonym for remove

    def rmdir(self, remotepath: str) -> None:
        """remove remote directory

        :param str remotepath: the remote directory to remove

        :returns: None

        """
        self._sftp_connect()
        self._sftp.rmdir(remotepath)

    def rename(self, remote_src: str, remote_dest: str) -> None:
        """rename a file or directory on the remote host.

        :param str remote_src: the remote file/directory to rename

        :param str remote_dest: the remote file/directory to put it

        :returns: None

        :raises: IOError

        """
        self._sftp_connect()
        self._sftp.rename(remote_src, remote_dest)

    def stat(self, remotepath: str) -> paramiko.SFTPAttributes:
        """return information about file/directory for the given remote path

        :param str remotepath: path to stat

        :returns: (SFTPAttributes) attributes of the remote path

        """
        self._sftp_connect()
        return self._sftp.stat(remotepath)

    def lstat(self, remotepath: str) -> paramiko.SFTPAttributes:
        """return information about file/directory for the given remote path,
        without following symbolic links. Otherwise, the same as .stat()

        :param str remotepath: path to stat

        :returns: (SFTPAttributes) attributes of the remote path, without following symlinks

        """
        self._sftp_connect()
        return self._sftp.lstat(remotepath)

    def close(self) -> None:
        """Closes the connection and cleans up."""
        # Close SFTP Connection.
        if getattr(self, "_sftp_live", False) and self._sftp is not None:
            try:
                self._sftp.close()
            finally:
                self._sftp_live = False
        # Close the ssh-agent connection, if a failed login left it open.
        self._close_agent()
        # Close the SSH Transport.
        transport = getattr(self, "_transport", None)
        if transport is not None:
            transport.close()
            self._transport = None
        # remove only the log handler this connection added, so handlers set
        # up by the application survive (pysftp 0.2.9 removed all of them)
        handlers = getattr(self, "_log_handlers", None)
        if handlers:
            lgr = logging.getLogger("paramiko")
            for handler in handlers:
                lgr.removeHandler(handler)
                handler.close()
            self._log_handlers = []
            if self._log_prev_level is not None:
                lgr.setLevel(self._log_prev_level)
                self._log_prev_level = None

    def open(self, remote_file: str, mode: str = "r", bufsize: int = -1) -> paramiko.SFTPFile:
        """Open a file on the remote server.

        See https://docs.paramiko.org/en/stable/api/sftp.html for details.

        :param str remote_file: name of the file to open.
        :param str mode:
            mode (Python-style) to open file (always assumed binary)
        :param int bufsize: *Default: -1* - desired buffering

        :returns: (SFTPFile) a handle to the open remote file

        :raises: IOError, if the file could not be opened.

        """
        self._sftp_connect()
        return self._sftp.open(remote_file, mode=mode, bufsize=bufsize)

    def exists(self, remotepath: str) -> bool:
        """Test whether a remotepath exists.

        :param str remotepath: the remote path to verify

        :returns: (bool) True, if remotepath exists, else False

        """
        self._sftp_connect()
        try:
            self._sftp.stat(remotepath)
        except OSError:
            return False
        return True

    def lexists(self, remotepath: str) -> bool:
        """Test whether a remotepath exists.  Returns True for broken symbolic
        links

        :param str remotepath: the remote path to verify

        :returns: (bool), True, if lexists, else False

        """
        self._sftp_connect()
        try:
            self._sftp.lstat(remotepath)
        except OSError:
            return False
        return True

    def symlink(self, remote_src: str, remote_dest: str) -> None:
        """create a symlink for a remote file on the server

        :param str remote_src: path of original file
        :param str remote_dest: path of the created symlink

        :returns: None

        :raises:
            any underlying error, IOError if something already exists at
            remote_dest

        """
        self._sftp_connect()
        self._sftp.symlink(remote_src, remote_dest)

    def truncate(self, remotepath: str, size: int) -> int:
        """Change the size of the file specified by path. Used to modify the
        size of the file, just like the truncate method on Python file objects.
        The new file size is confirmed and returned.

        :param str remotepath: remote file path to modify
        :param int|long size: the new file size

        :returns: (int) new size of file

        :raises: IOError, if file does not exist

        """
        self._sftp_connect()
        self._sftp.truncate(remotepath, size)
        return self._sftp.stat(remotepath).st_size

    def walktree(
        self,
        remotepath: str,
        fcallback: Callable[[str], object],
        dcallback: Callable[[str], object],
        ucallback: Callable[[str], object],
        recurse: bool = True,
    ) -> None:
        """recursively descend, depth first, the directory tree rooted at
        remotepath, calling discreet callback functions for each regular file,
        directory and unknown file type.

        Symbolic links are followed, as in pysftp 0.2.9; a broken link is
        reported to ucallback. Entries are visited in sorted order.

        :param str remotepath:
            root of remote directory to descend, use '.' to start at
            :attr:`.pwd`
        :param callable fcallback:
            callback function to invoke for a regular file.
            (form: ``func(str)``)
        :param callable dcallback:
            callback function to invoke for a directory. (form: ``func(str)``)
        :param callable ucallback:
            callback function to invoke for an unknown file type.
            (form: ``func(str)``)
        :param bool recurse: *Default: True* - should it recurse

        :returns: None

        :raises:

        """
        self._sftp_connect()
        # One listdir_attr round trip per directory, instead of a stat() per
        # entry as in pysftp 0.2.9.
        for attr in self.listdir_attr(remotepath):
            entry = attr.filename
            if entry in (".", "..") or "/" in entry:
                # never valid in a directory listing; a hostile server could
                # use it to point callers outside the tree being walked
                _warn_unsafe(entry)
                continue
            pathname = posixpath.join(remotepath, entry)
            mode = attr.st_mode
            if mode is None or S_ISLNK(mode):
                try:
                    mode = self._sftp.stat(pathname).st_mode
                except OSError:  # broken symlink
                    mode = None
            if mode is not None and S_ISDIR(mode):
                # It's a directory, call the dcallback function
                dcallback(pathname)
                if recurse:
                    # now, recurse into it
                    self.walktree(pathname, fcallback, dcallback, ucallback)
            elif mode is not None and S_ISREG(mode):
                # It's a file, call the fcallback function
                fcallback(pathname)
            else:
                # Unknown file type
                ucallback(pathname)

    @property
    def sftp_client(self) -> paramiko.SFTPClient:
        """give access to the underlying, connected paramiko SFTPClient object

        see https://docs.paramiko.org/en/stable/api/sftp.html

        :params: None

        :returns: (SFTPClient) the active paramiko SFTPClient

        """
        self._sftp_connect()
        return self._sftp

    @property
    def active_ciphers(self) -> tuple[str, str]:
        """Get tuple of currently used local and remote ciphers.

        :returns:
            (tuple of  str) currently used ciphers (local_cipher,
            remote_cipher)

        """
        return self._transport.local_cipher, self._transport.remote_cipher

    @property
    def active_compression(self) -> tuple[str, str]:
        """Get tuple of currently used local and remote compression.

        :returns:
            (tuple of  str) currently used compression (local_compression,
            remote_compression)

        """
        localc = self._transport.local_compression
        remotec = self._transport.remote_compression
        return localc, remotec

    @property
    def security_options(self) -> paramiko.transport.SecurityOptions:
        """return the available security options recognized by paramiko.

        :returns:
            (SecurityOptions) security preferences of the ssh transport. These are tuples
            of acceptable `.ciphers`, `.digests`, `.key_types`, and key
            exchange algorithms `.kex`, listed in order of preference.

        """

        return self._transport.get_security_options()

    @property
    def logfile(self) -> bool | str:
        """return the name of the file used for logging or False it not logging

        :returns: (str)logfile or (bool) False

        """
        return self._cnopts.log

    @property
    def timeout(self) -> float | None:
        """(float|None) *Default: None* -
            get or set the underlying socket timeout for pending read/write
            ops.

        :returns:
            (float|None) seconds to wait for a pending read/write operation
            before raising socket.timeout, or None for no timeout
        """
        self._sftp_connect()
        channel = self._sftp.get_channel()

        return channel.gettimeout()

    @timeout.setter
    def timeout(self, val: float | None) -> None:
        """setter for timeout"""
        self._sftp_connect()
        channel = self._sftp.get_channel()
        channel.settimeout(val)

    @property
    def remote_server_key(self) -> paramiko.PKey:
        """return the remote server's key"""
        return self._transport.get_remote_server_key()

    def __del__(self) -> None:
        """Attempt to clean up if not explicitly closed."""
        try:
            self.close()
        except Exception:  # noqa: S110  # pylint:disable=broad-except
            pass  # interpreter shutdown or a half-built object; nothing to do

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, etype: Any, value: Any, traceback: Any) -> None:
        self.close()


def _load_private_key(path: StrPath, password: str | None) -> paramiko.PKey:
    """Load an RSA, ECDSA or Ed25519 private key (DSA too, on paramiko < 4)
    from path, in OpenSSH or PEM format, detecting the type from the file.

    :raises PasswordRequiredException: the key is encrypted and no password
        was given
    :raises SSHException: the password is wrong, or the file isn't a key
    :raises OSError: the file can't be read
    """
    path = os.path.expanduser(os.fspath(path))
    secret = password.encode("utf-8") if isinstance(password, str) else password
    try:
        return paramiko.PKey.from_path(path, secret)
    except TypeError as exc:  # raised by cryptography when no password was given
        if secret is None:
            raise PasswordRequiredException(f"Private key file is encrypted: {path}") from exc
        raise
    except ValueError as exc:  # wrong password, or not a private key
        raise SSHException(f"Could not load private key {path}: {exc}") from exc
    except paramiko.UnknownKeyType as exc:
        legacy_dss = getattr(paramiko, "DSSKey", None)
        if legacy_dss is not None:  # paramiko < 4.0 can still load DSA keys
            return legacy_dss.from_private_key_file(path, password)
        raise SSHException(f"Unsupported private key type in {path}: {exc}") from exc


def _unsafe_remote_name(name: str, local_seps: tuple[str, ...] | None = None) -> bool:
    """True if a server-supplied file name would escape the target directory
    once used as part of a local path.

    A malicious server can return names such as ``../../.bashrc`` (or, for a
    Windows client, ``..\\..\\x``); pysftp 0.2.9 wrote them wherever they
    pointed.
    """
    if local_seps is None:
        local_seps = (os.sep, os.altsep) if os.altsep else (os.sep,)
    return name == ".." or "/" in name or any(sep in name for sep in local_seps)


def _warn_unsafe(name: str) -> None:
    warnings.warn(
        f"skipping unsafe file name from server: {name!r}",
        RuntimeWarning,
        stacklevel=3,
    )


def _local_to_remote(
    remotepath: str,
    relpath: str,
    sep: str = os.sep,
    altsep: str | None = os.altsep,
) -> str:
    """Join a relative *local* path onto a remote directory using POSIX
    separators, whatever the local OS uses. pysftp 0.2.9 used os.path.join,
    which put backslashes into remote paths on Windows."""
    if altsep:
        relpath = relpath.replace(altsep, sep)
    parts = [p for p in relpath.split(sep) if p not in ("", ".")]
    return posixpath.join(remotepath, *parts) if parts else remotepath


def _remote_to_local(
    localdir: str,
    remotepath: str,
    join: Callable[..., str] = os.path.join,
) -> str:
    """Re-parent a remote POSIX path under localdir, as reparent() does, but
    splitting on "/" so it is correct on Windows too."""
    parts = [p for p in remotepath.split("/") if p not in ("", ".")]
    return join(localdir, *parts) if parts else localdir
