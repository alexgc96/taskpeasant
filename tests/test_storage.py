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


# 2. No temp files left after a normal write.
def test_normal_write_leaves_no_temp_files(tmp_path, yaml_file, make_task):
    write_tasks(yaml_file, [make_task(description="one")])
    assert _tmp_files(tmp_path) == []
    with open(yaml_file, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert [t["description"] for t in doc["taskpeasant_tasks"]] == ["one"]


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


# 4. The lock is re-entrant in one thread (nested acquisition does not block).
def test_lock_is_reentrant_in_one_thread(yaml_file):
    with _os_exclusive_lock(yaml_file):
        with _os_exclusive_lock(yaml_file):
            # If the lock were not re-entrant this nested acquisition would
            # deadlock (Windows sidecar) rather than simply proceed.
            assert os.path.exists(yaml_file + ".lock") or sys.platform != "win32"


def test_reentrant_lock_depth_is_restored(yaml_file):
    depth_map = getattr(storage._os_lock_depth, "by_path", {})
    before = dict(depth_map)
    with _os_exclusive_lock(yaml_file):
        with _os_exclusive_lock(yaml_file):
            assert depth_map.get(yaml_file, 0) == 2
    assert depth_map.get(yaml_file, 0) == 0
    # Other paths were untouched.
    for key, value in before.items():
        assert depth_map.get(key) == value


# 6. Windows path: a pre-existing sidecar triggers TimeoutError once the
# deadline is reached, without waiting the full 30 seconds.
@pytest.mark.skipif(sys.platform == "win32", reason="covered by the real path on Windows")
def test_win_exclusive_times_out_when_sidecar_exists(monkeypatch, tmp_path):
    lock_path = str(tmp_path / "tasks.yaml.lock")
    # Simulate another process holding the sidecar.
    with open(lock_path, "w") as fh:
        fh.write("")

    import time as time_mod

    class _Clock:
        def __init__(self):
            self.t = 0.0

        def monotonic(self):
            return self.t

        def sleep(self, _secs):
            self.t += 31.0  # jump past the 30 s deadline on the first wait

    clock = _Clock()
    # _win_exclusive imports `time` locally, so patch the module's functions.
    monkeypatch.setattr(time_mod, "monotonic", clock.monotonic)
    monkeypatch.setattr(time_mod, "sleep", clock.sleep)

    with pytest.raises(TimeoutError, match="Could not acquire write lock"):
        with _win_exclusive(lock_path):
            pass


# 5. The lock excludes another process (POSIX). A child holds the advisory
# lock, then a second child tries to acquire it and must wait until released.
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl.flock only")
def test_lock_excludes_another_process(tmp_path, yaml_file):
    lock_path = yaml_file + ".lock"
    ready = str(tmp_path / "ready")
    release = str(tmp_path / "release")
    acquired = str(tmp_path / "acquired")

    holder = textwrap.dedent(
        """
        import os, sys, time
        import fcntl
        sys.path.insert(0, {repo!r})
        from taskpeasant.storage import _posix_exclusive
        with _posix_exclusive({lock!r}):
            open({ready!r}, "w").close()
            deadline = time.monotonic() + 10
            while not os.path.exists({release!r}) and time.monotonic() < deadline:
                time.sleep(0.02)
        """.format(
            repo=os.path.dirname(os.path.dirname(storage.__file__)),
            lock=lock_path,
            ready=ready,
            release=release,
        )
    )

    contender = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, {repo!r})
        from taskpeasant.storage import _posix_exclusive
        with _posix_exclusive({lock!r}):
            open({acquired!r}, "w").close()
        """.format(
            repo=os.path.dirname(os.path.dirname(storage.__file__)),
            lock=lock_path,
            acquired=acquired,
        )
    )

    holder_proc = subprocess.Popen([sys.executable, "-c", holder])
    try:
        deadline = 10.0
        waited = 0.0
        while not os.path.exists(ready) and waited < deadline:
            import time

            time.sleep(0.02)
            waited += 0.02
        assert os.path.exists(ready), "holder never acquired the lock"

        contender_proc = subprocess.Popen([sys.executable, "-c", contender])
        import time

        time.sleep(0.3)
        # The contender must still be blocked while the holder owns the lock.
        assert contender_proc.poll() is None, "contender acquired a held lock"
        assert not os.path.exists(acquired)

        open(release, "w").close()
        contender_proc.wait(timeout=10)
        assert contender_proc.returncode == 0
        assert os.path.exists(acquired)
    finally:
        open(release, "w").close()
        holder_proc.wait(timeout=10)
