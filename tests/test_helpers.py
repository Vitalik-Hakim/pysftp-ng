"""Pure helper functions, including the cross-platform path handling."""

from __future__ import annotations

import ntpath
import os
from stat import S_IFDIR, S_IFREG

import pytest

import pysftp
from pysftp import _local_to_remote, _remote_to_local, _unsafe_remote_name


@pytest.mark.regression
def test_local_to_remote_from_windows_paths():
    """0.2.9 built remote paths with os.path.join, so put_r from Windows
    created remote files named like 'pkg\\inner\\c.txt'."""
    assert (
        _local_to_remote("/dest", "pkg\\inner\\c.txt", sep="\\", altsep="/")
        == "/dest/pkg/inner/c.txt"
    )
    assert _local_to_remote("/dest", ".\\a.txt", sep="\\", altsep="/") == "/dest/a.txt"


def test_local_to_remote_posix():
    assert _local_to_remote("/dest", "pkg/b.txt", sep="/", altsep=None) == "/dest/pkg/b.txt"
    assert _local_to_remote("/dest", ".", sep="/", altsep=None) == "/dest"


def test_remote_to_local_on_windows():
    assert _remote_to_local("C:\\out", "/data/sub/f.txt", join=ntpath.join) == (
        "C:\\out\\data\\sub\\f.txt"
    )
    assert _remote_to_local("C:\\out", "./f.txt", join=ntpath.join) == "C:\\out\\f.txt"


@pytest.mark.parametrize(
    ("name", "seps", "unsafe"),
    [
        ("normal.txt", ("/",), False),
        ("..", ("/",), True),
        ("../x", ("/",), True),
        ("a\\b", ("/",), False),  # a legal file name on POSIX
        ("..\\x", ("\\", "/"), True),  # a path traversal on Windows
    ],
)
def test_unsafe_remote_name(name, seps, unsafe):
    assert _unsafe_remote_name(name, seps) is unsafe


def test_st_mode_to_int():
    assert pysftp.st_mode_to_int(S_IFREG | 0o640) == 640
    assert pysftp.st_mode_to_int(S_IFDIR | 0o755) == 755


def test_path_advance_and_retreat():
    assert list(pysftp.path_advance("a/b/c", sep="/")) == [
        "a",
        os.path.join("a", "b"),
        os.path.join("a", "b", "c"),
    ]
    assert next(iter(pysftp.path_retreat("a/b", sep="/"))) == os.path.join("a", "b")
    assert list(pysftp.path_advance("")) == []
    assert list(pysftp.path_retreat("")) == []


def test_reparent():
    assert pysftp.reparent("new", "/abs/path") == os.path.join("new", "./abs/path")
    assert pysftp.reparent("new", "rel") == os.path.join("new", "rel")


def test_local_cd(tmp_path):
    start = os.getcwd()
    with pysftp.cd(str(tmp_path)):
        assert os.path.samefile(os.getcwd(), tmp_path)
    assert os.getcwd() == start


def test_connection_exception_message():
    exc = pysftp.ConnectionException("example.com", 2222)
    assert str(exc) == "Could not connect to host:port.  example.com:2222"
    assert exc.args == ("example.com", 2222)
    assert (exc.host, exc.port) == ("example.com", 2222)
