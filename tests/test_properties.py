"""Property-based tests for the path helpers, with Hypothesis.

The server chooses the file names that get_d and get_r turn into local paths, so the safety
rules are checked against many generated names, under both POSIX and Windows path rules.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
from stat import S_IFDIR, S_IFLNK, S_IFREG

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import pysftp
from pysftp import _local_to_remote, _remote_to_local, _unsafe_remote_name

# Pure string work, but CI runners can be slow, and a timing failure would only be noise.
relaxed = settings(deadline=None)

# Each OS's path rules: the path module, the separators _unsafe_remote_name checks for
# there, and a target directory.
FLAVOURS = [
    pytest.param(posixpath, ("/",), "/home/user/target", id="posix"),
    pytest.param(ntpath, ("\\", "/"), "C:\\Users\\user\\target", id="windows"),
]

# Names a hostile server could send, joined from pieces that mean something in a path
# ("..", separators, drive prefixes such as "D:") so that dangerous combinations come up
# often, and from any other text.
PIECES = st.sampled_from(["..", ".", "/", "\\", ":", "D:", "c:", "a", " "]) | st.text(max_size=3)
NAMES = st.lists(PIECES, max_size=6).map("".join)

# Path components with no separators or drive colons, for paths that are well formed.
COMPONENTS = st.lists(
    st.text(st.characters(exclude_characters="/\\:"), min_size=1, max_size=8),
    min_size=1,
    max_size=5,
)


def inside(flavour, target, path):
    """True if path, once normalised, is target or below it."""
    return flavour.commonpath([target, flavour.normpath(path)]) == target


@pytest.mark.parametrize(("flavour", "seps", "target"), FLAVOURS)
@relaxed
@given(name=NAMES)
def test_names_that_pass_the_check_stay_in_the_target(flavour, seps, target, name):
    # get_d joins each name that passes the check onto the target directory.
    if not _unsafe_remote_name(name, seps):
        assert inside(flavour, target, flavour.join(target, name))


@pytest.mark.parametrize(("flavour", "seps", "target"), FLAVOURS)
@relaxed
@given(rpath=st.lists(NAMES, max_size=5).map("/".join))
def test_remote_paths_that_pass_the_check_stay_in_the_target(flavour, seps, target, rpath):
    # get_r checks every part of a remote path, then maps it with _remote_to_local.
    if not any(_unsafe_remote_name(part, seps) for part in rpath.split("/")):
        assert inside(flavour, target, _remote_to_local(target, rpath, join=flavour.join))


@relaxed
@given(name=NAMES.filter(bool))
def test_reparent_keeps_names_that_pass_the_check_in_the_target(name):
    # The same check as get_d, through reparent and this OS's path rules. An empty
    # name makes reparent raise IndexError, as in pysftp 0.2.9.
    target = os.path.abspath("target")
    if not _unsafe_remote_name(name):
        assert inside(os.path, target, pysftp.reparent(target, name))


@relaxed
@given(parts=COMPONENTS)
def test_reparent_moves_absolute_paths_under_the_new_parent(parts):
    target = os.path.abspath("target")
    moved = pysftp.reparent(target, os.sep + os.sep.join(parts))
    assert os.path.normpath(moved) == os.path.normpath(os.path.join(target, *parts))


@pytest.mark.parametrize(("sep", "altsep"), [("/", None), ("\\", "/")], ids=["posix", "windows"])
@relaxed
@given(parts=st.lists(st.text(st.characters(exclude_characters="/\\")), max_size=5), data=st.data())
def test_local_paths_become_posix_remote_paths(sep, altsep, parts, data):
    # put_r's mapping: join with "/", whichever separators the local path used.
    seps = [sep, altsep] if altsep else [sep]
    relpath = parts[0] if parts else ""
    for part in parts[1:]:
        relpath += data.draw(st.sampled_from(seps)) + part
    kept = [part for part in parts if part not in ("", ".")]
    expected = posixpath.join("/srv/remote", *kept) if kept else "/srv/remote"
    assert _local_to_remote("/srv/remote", relpath, sep=sep, altsep=altsep) == expected


@relaxed
@given(parts=COMPONENTS, absolute=st.booleans())
def test_path_advance_and_retreat_walk_the_same_steps(parts, absolute):
    path = (os.sep if absolute else "") + os.sep.join(parts)
    forward = list(pysftp.path_advance(path))
    assert len(forward) == len(parts)
    assert forward[-1] == path
    assert list(pysftp.path_retreat(path)) == forward[::-1]


@relaxed
@given(perm=st.integers(0, 0o7777), kind=st.sampled_from([S_IFREG, S_IFDIR, S_IFLNK]))
def test_st_mode_to_int_matches_pysftp_029(perm, kind):
    mode = kind | perm
    # pysftp 0.2.9 kept the last three octal digits of the whole mode.
    assert pysftp.st_mode_to_int(mode) == int(oct(mode)[-3:])
    # Read back as octal, the digits are the permission bits.
    assert int(str(pysftp.st_mode_to_int(mode)), 8) == perm & 0o777
