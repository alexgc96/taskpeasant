"""Storage guarantees: atomic writes and the cross-process write lock.

These cover the two hardening features that shipped in 0.5.0 without tests
of their own. A regression here would otherwise leave the suite green, so
the tests target `write_tasks` and `_os_exclusive_lock` directly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time as time_mod

import pytest
import yaml

from taskpeasant import storage
from taskpeasant.storage import _os_exclusive_lock, _win_exclusive, write_tasks


def _original_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _tmp_files(directory):
    return sorted(p.name for p in os.scandir(directory) if p.name.endswith(".tmp"))


def _write_seed(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(content, fh, default_flow_style=False, sort_keys=False)


# 1. A failed write leaves the original intact and removes its temp file.
def test_failed_replace_leaves_original_intact(monkeypatch, tmp_path, yaml_file, make_task):
    seed = {"studio_meta": {"name": "keep me"}, "taskpeasant_tasks": []}
    _write_seed(yaml_file, seed)
    before = _original_bytes(yaml_file)

    def boom(src, dst):
        # Let the temp file be created, then fail the rename so the cleanup
        # path in write_tasks runs.
        raise OSError("simulated rename failure")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        write_tasks(yaml_file, [make_task(description="never lands")])

    assert _original_bytes(yaml_file) == before
    # The lock sidecar is expected; only stray .tmp files are a problem.
    assert _tmp_files(tmp_path) == []


def test_failed_dump_leaves_original_intact(monkeypatch, tmp_path, yaml_file, make_task):
    seed = {"tasks": {"context": "work"}, "taskpeasant_tasks": []}
    _write_seed(yaml_file, seed)
    before = _original_bytes(yaml_file)

    def boom(*args, **kwargs):
        raise OSError("simulated dump failure")

    monkeypatch.setattr(storage.yaml, "dump", boom)
    with pytest.raises(OSError, match="simulated dump failure"):
        write_tasks(yaml_file, [make_task()])

    assert _original_bytes(yaml_file) == before
    assert _tmp_files(tmp_path) == []


# 2. No temp files left after a normal write, and write_tasks takes the OS lock.
def test_normal_write_leaves_no_temp_files(tmp_path, yaml_file, make_task):
    write_tasks(yaml_file, [make_task(description="one")])
    assert _tmp_files(tmp_path) == []
    with open(yaml_file, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert [t["description"] for t in doc["taskpeasant_tasks"]] == ["one"]


def test_write_tasks_acquires_os_exclusive_lock(monkeypatch, yaml_file, make_task):
    observed = []
    real_replace = storage.os.replace

    def spy_replace(src, dst):
        depth_map = getattr(storage._os_lock_depth, "by_path", {})
        observed.append((depth_map.get(yaml_file, 0), os.path.exists(yaml_file + ".lock")))
        return real_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", spy_replace)
    write_tasks(yaml_file, [make_task(description="locked")])
    assert observed == [(1, True)]
    assert storage._os_lock_depth.by_path.get(yaml_file, 0) == 0


# 3. Sibling keys survive an atomic write.
def test_sibling_keys_survive_atomic_write(yaml_file, make_task):
    seed = {
        "studio_meta": {"name": "host app", "version": 3},
        "tasks": {"context": "work", "labels": ["a", "b"]},
        "taskpeasant_tasks": [],
    }
    _write_seed(yaml_file, seed)
    write_tasks(yaml_file, [make_task(description="atomic")])
    with open(yaml_file, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert doc["studio_meta"] == seed["studio_meta"]
    assert doc["tasks"] == seed["tasks"]
    assert len(doc["taskpeasant_tasks"]) == 1


# 4. The lock is re-entrant in one thread without re-acquiring the backend lock.
def test_lock_is_reentrant_in_one_thread(monkeypatch, yaml_file, make_task):
    acquisitions = 0
    real_win_exclusive = storage._win_exclusive

    class _FastClock:
        def __init__(self):
            self.t = 0.0

        def monotonic(self):
            return self.t

        def sleep(self, _secs):
            self.t += 31.0

    clock = _FastClock()
    monkeypatch.setattr(storage.sys, "platform", "win32")
    monkeypatch.setattr(time_mod, "monotonic", clock.monotonic)
    monkeypatch.setattr(time_mod, "sleep", clock.sleep)

    @storage.contextlib.contextmanager
    def counting_win_exclusive(lock_path):
        nonlocal acquisitions
        acquisitions += 1
        with real_win_exclusive(lock_path):
            yield

    monkeypatch.setattr(storage, "_win_exclusive", counting_win_exclusive)

    # Without re-entry tracking, _win_exclusive would fail immediately on TimeoutError
    # rather than hanging; with re-entry, the backend lock is entered only once.
    with _os_exclusive_lock(yaml_file):
        assert os.path.exists(yaml_file + ".lock")
        write_tasks(yaml_file, [make_task(description="reentrant")])
        assert acquisitions == 1
    assert not os.path.exists(yaml_file + ".lock")


def test_reentrant_lock_depth_is_restored(yaml_file, monkeypatch):
    class _FastClock:
        def __init__(self):
            self.t = 0.0

        def monotonic(self):
            return self.t

        def sleep(self, _secs):
            self.t += 31.0

    clock = _FastClock()
    monkeypatch.setattr(storage.sys, "platform", "win32")
    monkeypatch.setattr(time_mod, "monotonic", clock.monotonic)
    monkeypatch.setattr(time_mod, "sleep", clock.sleep)

    with _os_exclusive_lock(yaml_file):
        depth = storage._os_lock_depth.by_path
        before = {k: v for k, v in depth.items() if k != yaml_file}
        assert depth[yaml_file] == 1
        with _os_exclusive_lock(yaml_file):
            assert depth[yaml_file] == 2
        assert depth[yaml_file] == 1
    assert depth[yaml_file] == 0
    for key, value in before.items():
        assert depth.get(key) == value


# 5. Windows path: a pre-existing sidecar triggers TimeoutError once the
# deadline is reached, without waiting the full 30 seconds.
def test_win_exclusive_times_out_when_sidecar_exists(monkeypatch, tmp_path):
    lock_path = str(tmp_path / "tasks.yaml.lock")
    with open(lock_path, "w") as fh:
        fh.write("")

    class _Clock:
        def __init__(self):
            self.t = 0.0

        def monotonic(self):
            return self.t

        def sleep(self, _secs):
            self.t += 31.0  # jump past the 30 s deadline on the first wait

    clock = _Clock()
    monkeypatch.setattr(time_mod, "monotonic", clock.monotonic)
    monkeypatch.setattr(time_mod, "sleep", clock.sleep)

    with pytest.raises(TimeoutError, match="Could not acquire write lock"):
        with _win_exclusive(lock_path):
            pass


# 6. The lock excludes another process (POSIX). A child holds the advisory
# lock, then a second child signals startup before attempting the lock and
# must wait until the holder releases it.
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl.flock only")
def test_lock_excludes_another_process(tmp_path, yaml_file):
    lock_path = yaml_file + ".lock"
    ready = str(tmp_path / "ready")
    started = str(tmp_path / "started")
    release = str(tmp_path / "release")
    acquired = str(tmp_path / "acquired")
    repo_root = os.path.dirname(os.path.dirname(storage.__file__))

    holder = textwrap.dedent(
        """
        import os, sys, time
        sys.path.insert(0, {repo!r})
        from taskpeasant.storage import _posix_exclusive
        with _posix_exclusive({lock!r}):
            open({ready!r}, "w").close()
            deadline = time.monotonic() + 10
            while not os.path.exists({release!r}) and time.monotonic() < deadline:
                time.sleep(0.02)
        """.format(repo=repo_root, lock=lock_path, ready=ready, release=release)
    )

    contender = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, {repo!r})
        from taskpeasant.storage import _posix_exclusive
        open({started!r}, "w").close()
        with _posix_exclusive({lock!r}):
            open({acquired!r}, "w").close()
        """.format(repo=repo_root, lock=lock_path, started=started, acquired=acquired)
    )

    holder_proc = subprocess.Popen([sys.executable, "-c", holder])
    try:
        deadline = time_mod.monotonic() + 10.0
        while not os.path.exists(ready) and time_mod.monotonic() < deadline:
            time_mod.sleep(0.02)
        assert os.path.exists(ready), "holder never acquired the lock"

        contender_proc = subprocess.Popen([sys.executable, "-c", contender])
        try:
            deadline = time_mod.monotonic() + 10.0
            while not os.path.exists(started) and time_mod.monotonic() < deadline:
                time_mod.sleep(0.02)
            assert os.path.exists(started), "contender never started"

            time_mod.sleep(0.15)
            assert contender_proc.poll() is None, "contender acquired a held lock"
            assert not os.path.exists(acquired)

            open(release, "w").close()
            contender_proc.wait(timeout=10)
            assert contender_proc.returncode == 0
            assert os.path.exists(acquired)
        finally:
            if contender_proc.poll() is None:
                open(release, "w").close()
                contender_proc.wait(timeout=10)
    finally:
        open(release, "w").close()
        holder_proc.wait(timeout=10)
