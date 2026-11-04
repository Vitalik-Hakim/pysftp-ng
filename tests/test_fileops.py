"""File and directory operations against the test server."""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

import pysftp


def _symlinks_supported() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink("target", os.path.join(tmp, "link"))
        except (OSError, NotImplementedError):
            return False
    return True


needs_symlinks = pytest.mark.skipif(
    not _symlinks_supported(), reason="creating symlinks needs extra rights on this OS"
)


def test_put_get_roundtrip(sftp, root, tmp_path):
    src = tmp_path / "up.bin"
    src.write_bytes(b"x" * 10_000)
    progress = []
    attrs = sftp.put(str(src), "/up.bin", callback=lambda done, total: progress.append(done))
    assert attrs.st_size == 10_000
    assert progress[-1] == 10_000
    assert (root / "up.bin").read_bytes() == src.read_bytes()

    dest = tmp_path / "down.bin"
    sftp.get("/up.bin", str(dest))
    assert dest.read_bytes() == src.read_bytes()


def test_put_get_default_names(sftp, root, tmp_path, monkeypatch):
    src = tmp_path / "local.txt"
    src.write_text("data")
    sftp.put(src)  # pathlib.Path works too
    assert (root / "local.txt").read_text() == "data"
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    sftp.get("/local.txt")
    assert (workdir / "local.txt").read_text() == "data"


def test_preserve_mtime(sftp, root, tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("old")
    os.utime(src, (1_000_000_000, 1_000_000_000))
    sftp.put(str(src), "/old.txt", preserve_mtime=True)
    assert int((root / "old.txt").stat().st_mtime) == 1_000_000_000

    os.utime(root / "old.txt", (1_100_000_000, 1_100_000_000))
    dest = tmp_path / "back.txt"
    sftp.get("/old.txt", str(dest), preserve_mtime=True)
    assert int(dest.stat().st_mtime) == 1_100_000_000


def test_putfo_getfo(sftp, root):
    sftp.putfo(io.BytesIO(b"stream"), "/stream.bin", file_size=6)
    assert (root / "stream.bin").read_bytes() == b"stream"
    buf = io.BytesIO()
    assert sftp.getfo("/stream.bin", buf) == 6
    assert buf.getvalue() == b"stream"


def test_open(sftp, root):
    with sftp.open("/notes.txt", "w") as fobj:
        fobj.write(b"line\n")
    with sftp.open("/notes.txt") as fobj:
        assert fobj.read() == b"line\n"


def test_directories_and_predicates(sftp, root):
    sftp.mkdir("/d", mode=755)
    (root / "d" / "f.txt").write_text("f")
    assert sftp.isdir("/d")
    assert not sftp.isfile("/d")
    assert sftp.isfile("/d/f.txt")
    assert sftp.exists("/d/f.txt")
    assert not sftp.exists("/nope")
    assert not sftp.isdir("/nope")
    assert not sftp.isfile("/nope")
    assert sftp.lexists("/d/f.txt")
    assert sftp.listdir("/d") == ["f.txt"]
    sftp.remove("/d/f.txt")
    sftp.rmdir("/d")
    assert sftp.listdir() == []


def test_listings_are_sorted(sftp, root):
    for name in ("b", "c", "a"):
        (root / name).write_text(name)
    assert sftp.listdir() == ["a", "b", "c"]
    assert [a.filename for a in sftp.listdir_attr()] == ["a", "b", "c"]


def test_rename_unlink_stat(sftp, root):
    (root / "a.txt").write_text("abc")
    sftp.rename("/a.txt", "/b.txt")
    assert sftp.stat("/b.txt").st_size == 3
    assert sftp.lstat("/b.txt").st_size == 3
    sftp.unlink("/b.txt")
    assert not (root / "b.txt").exists()


def test_rename_onto_an_existing_file_fails(sftp, root):
    """Like OpenSSH, a plain SFTP rename won't replace an existing file."""
    (root / "old.txt").write_text("old")
    (root / "new.txt").write_text("new")
    with pytest.raises(OSError, match="Failure"):
        sftp.rename("/old.txt", "/new.txt")
    assert (root / "old.txt").read_text() == "old"
    assert (root / "new.txt").read_text() == "new"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX permission bits")
def test_chmod_uses_octal_digits(sftp, root):
    (root / "m.txt").write_text("m")
    sftp.chmod("/m.txt", 640)
    assert pysftp.st_mode_to_int(sftp.stat("/m.txt").st_mode) == 640


def test_chown_noop_and_same_ids(sftp, root):
    (root / "o.txt").write_text("o")
    sftp.chown("/o.txt")  # nothing to change
    st = sftp.stat("/o.txt")
    sftp.chown("/o.txt", uid=st.st_uid)
    sftp.chown("/o.txt", gid=st.st_gid)


def test_truncate(sftp, root):
    (root / "t.txt").write_text("123456")
    assert sftp.truncate("/t.txt", 2) == 2
    assert (root / "t.txt").read_text() == "12"


@needs_symlinks
def test_symlink_readlink_normalize(sftp, root):
    (root / "target.txt").write_text("t")
    (root / "dir").mkdir()
    sftp.symlink("target.txt", "/link.txt")
    assert sftp.readlink("/link.txt") == "/target.txt"
    assert sftp.normalize("dir/../target.txt") == "/target.txt"


@pytest.mark.regression
@needs_symlinks
def test_readlink_resolves_a_relative_target_from_the_link_directory(sftp, root):
    """0.2.9 resolved it from the current directory, so other directories got wrong paths."""
    (root / "sub").mkdir()
    (root / "sub" / "target.txt").write_text("t")
    sftp.symlink("target.txt", "/sub/link")
    assert sftp.readlink("/sub/link") == "/sub/target.txt"


@needs_symlinks
def test_normalize_and_pwd_follow_symlinks(sftp, root):
    """Like OpenSSH, the server resolves symlinks when it normalizes a path."""
    (root / "real").mkdir()
    sftp.symlink("real", "/linked")
    assert sftp.normalize("/linked") == "/real"
    with sftp.cd("/linked"):
        assert sftp.pwd == "/real"


def test_normalize_needs_existing_parents(sftp):
    """Like OpenSSH, only the last part of the path may be missing.
    (OpenSSH reports "No such file"; paramiko's server can only say "Failure".)"""
    assert sftp.normalize("/missing") == "/missing"
    with pytest.raises(OSError, match="Failure"):
        sftp.normalize("/missing/child")


def test_chdir_and_cd_context(sftp, root):
    (root / "x" / "y").mkdir(parents=True)
    sftp.chdir("/x")
    assert sftp.pwd == "/x"
    assert sftp.getcwd() == "/x"
    with sftp.cd("y"):
        assert sftp.pwd == "/x/y"
    assert sftp.pwd == "/x"
    sftp.cwd("/")
    assert sftp.pwd == "/"


def test_makedirs(sftp, root):
    sftp.makedirs("/a/b/c")
    assert (root / "a" / "b" / "c").is_dir()
    sftp.makedirs("/a/b/c")  # already there: no error
    (root / "a" / "file").write_text("f")
    with pytest.raises(OSError, match="already exists"):
        sftp.makedirs("/a/file")


def _tree(root):
    (root / "data" / "sub" / "deep").mkdir(parents=True)
    (root / "data" / "empty").mkdir()
    (root / "data" / "top.txt").write_text("top")
    (root / "data" / "sub" / "mid.txt").write_text("mid")
    (root / "data" / "sub" / "deep" / "low.txt").write_text("low")
    if _symlinks_supported():
        os.symlink("missing-target", root / "data" / "broken")


@pytest.mark.regression
@needs_symlinks
def test_walktree(sftp, root):
    """0.2.9 crashed with FileNotFoundError on a broken symlink."""
    _tree(root)
    files, dirs, unknown = [], [], []
    sftp.walktree("/data", files.append, dirs.append, unknown.append)
    assert files == ["/data/sub/deep/low.txt", "/data/sub/mid.txt", "/data/top.txt"]
    assert dirs == ["/data/empty", "/data/sub", "/data/sub/deep"]
    assert unknown == ["/data/broken"]
    files.clear()
    sftp.walktree("/data", files.append, dirs.append, unknown.append, recurse=False)
    assert files == ["/data/top.txt"]


def test_walktree_lists_each_directory_once(sftp, root, server):
    """0.2.9 sent a stat() per entry; now it's one listing per directory."""
    (root / "w" / "s").mkdir(parents=True)
    for i in range(20):
        (root / "w" / f"f{i}.txt").write_text("x")
        (root / "w" / "s" / f"g{i}.txt").write_text("x")
    server.calls.clear()
    sftp.walktree("/w", lambda p: None, lambda p: None, lambda p: None)
    assert server.calls["list_folder"] == 2
    assert server.calls["stat"] == 0


def test_get_d(sftp, root, tmp_path):
    _tree(root)
    out = tmp_path / "out"
    out.mkdir()
    sftp.get_d("/data/sub", str(out))
    assert sorted(os.listdir(out)) == ["mid.txt"]


def test_get_r_keeps_0_2_9_layout(sftp, root, tmp_path):
    _tree(root)
    out = tmp_path / "out"
    out.mkdir()
    sftp.chdir("/")
    sftp.get_r("data", str(out))
    assert (out / "data" / "top.txt").read_text() == "top"
    assert (out / "data" / "sub" / "deep" / "low.txt").read_text() == "low"
    assert (out / "data" / "empty").is_dir()


def test_get_r_creates_missing_local_parents(sftp, root, tmp_path):
    _tree(root)
    out = tmp_path / "not" / "yet"
    sftp.get_r("/data/sub", str(out))
    assert (out / "data" / "sub" / "mid.txt").read_text() == "mid"


def _local_tree(base):
    (base / "pkg" / "inner").mkdir(parents=True)
    (base / "pkg" / "blank").mkdir()
    (base / "a.txt").write_text("a")
    (base / "pkg" / "b.txt").write_text("b")
    (base / "pkg" / "inner" / "c.txt").write_text("c")


def test_put_d(sftp, root, tmp_path):
    src = tmp_path / "src"
    _local_tree(src)
    (root / "dest").mkdir()
    cwd = os.getcwd()
    sftp.put_d(str(src), "/dest")
    assert os.getcwd() == cwd  # 0.2.9 changed the process's cwd while working
    assert sorted(os.listdir(root / "dest")) == ["a.txt"]


def test_put_r(sftp, root, tmp_path):
    src = tmp_path / "src"
    _local_tree(src)
    (root / "dest").mkdir()
    cwd = os.getcwd()
    sftp.put_r(src, "/dest")
    assert os.getcwd() == cwd
    assert (root / "dest" / "a.txt").read_text() == "a"
    assert (root / "dest" / "pkg" / "inner" / "c.txt").read_text() == "c"
    assert (root / "dest" / "pkg" / "blank").is_dir()
    sftp.put_r(src, "/dest")  # second run over existing directories works


def test_hostile_names_are_skipped(server_factory, tmp_path):
    """A malicious server listing "../x" must not make get_r/get_d write
    outside the target directory."""
    srv = server_factory(inject_names=["../escaped.txt"])
    (Path(srv.root) / "ok.txt").write_text("ok")
    out = tmp_path / "out"
    out.mkdir()
    with pysftp.Connection(
        "127.0.0.1", port=srv.port, username="tester", password="secret", cnopts=_no_check()
    ) as conn:
        with pytest.warns(RuntimeWarning, match="unsafe file name"):
            conn.get_r("/", str(out))
        with pytest.warns(RuntimeWarning, match="unsafe file name"):
            conn.get_d("/", str(out))
    assert (out / "ok.txt").read_text() == "ok"
    assert not (tmp_path / "escaped.txt").exists()


def _no_check():
    cnopts = pysftp.CnOpts.__new__(pysftp.CnOpts)
    cnopts.__dict__.update(log=False, compression=False, ciphers=None, timeout=None, hostkeys=None)
    return cnopts
