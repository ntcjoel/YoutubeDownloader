"""Unit tests for tasks.py"""
import os
import json
import tempfile
import importlib
import pytest
from unittest.mock import patch, MagicMock
from tasks import Task, TaskStatus


class TestTask:
    def test_task_to_dict(self):
        t = Task(url="https://youtube.com/watch?v=abc", format="video", quality="1080p")
        d = t.to_dict()
        assert d["url"] == "https://youtube.com/watch?v=abc"
        assert d["format"] == "video"
        assert d["quality"] == "1080p"
        assert d["status"] == "pending"
        assert d["progress"] == 0
        assert d["id"] == t.id

    def test_task_from_dict(self):
        d = {
            "id": "test123",
            "url": "https://youtube.com/watch?v=xyz",
            "format": "audio",
            "quality": "bestaudio",
            "title": "Test Song",
            "category": "music",
            "status": "completed",
            "progress": 100,
            "filename": "/path/to/song.mp3",
        }
        t = Task.from_dict(d)
        assert t.id == "test123"
        assert t.url == "https://youtube.com/watch?v=xyz"
        assert t.format == "audio"
        assert t.status == TaskStatus.COMPLETED
        assert t.filename == "/path/to/song.mp3"

    def test_task_update(self):
        t = Task(url="https://youtube.com/watch?v=abc", format="video", quality="720p")
        t.update(status=TaskStatus.DOWNLOADING, progress=50, message="Halfway done")
        assert t.status == TaskStatus.DOWNLOADING
        assert t.progress == 50
        assert t.message == "Halfway done"

    def test_task_update_partial(self):
        t = Task(url="https://youtube.com/watch?v=abc", format="video")
        t.update(progress=25)
        assert t.progress == 25
        assert t.status == TaskStatus.PENDING  # unchanged

    def test_task_update_filename(self):
        t = Task(url="https://youtube.com/watch?v=abc", format="video")
        t.update(filename="/path/to/video.mp4")
        assert t.filename == "/path/to/video.mp4"

    def test_task_update_error(self):
        t = Task(url="https://youtube.com/watch?v=abc", format="video")
        t.update(status=TaskStatus.ERROR, error="Connection timeout")
        assert t.status == TaskStatus.ERROR
        assert t.error == "Connection timeout"

    def test_task_status_enum_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.DOWNLOADING.value == "downloading"
        assert TaskStatus.PROCESSING.value == "processing"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.ERROR.value == "error"

    def test_task_to_dict_all_fields_present(self):
        t = Task(url="https://youtube.com/watch?v=full", format="audio", quality="192k",
                 title="My Song", category="music")
        t.update(status=TaskStatus.COMPLETED, progress=100, filename="/path/song.mp3")
        d = t.to_dict()
        required = {"id", "url", "title", "format", "quality", "category",
                    "status", "progress", "message", "filename", "error",
                    "created_at", "updated_at"}
        assert set(d.keys()) == required


class TestTaskManager:
    def test_create_task(self):
        import tasks
        importlib.reload(tasks)
        mgr = tasks.TaskManager()
        t = mgr.create_task(url="https://youtube.com/watch?v=test", format="video", quality="1080p")
        assert t.url == "https://youtube.com/watch?v=test"
        assert t.format == "video"
        assert t.status == TaskStatus.PENDING
        assert t.id is not None

    def test_get_task(self):
        import tasks
        importlib.reload(tasks)
        mgr = tasks.TaskManager()
        t = mgr.create_task(url="https://youtube.com/watch?v=get", format="audio")
        assert mgr.get_task(t.id) is not None
        assert mgr.get_task("nonexistent") is None

    def test_get_all_tasks(self):
        import tasks
        importlib.reload(tasks)
        mgr = tasks.TaskManager()
        t1 = mgr.create_task(url="https://youtube.com/watch?v=a", format="video")
        t2 = mgr.create_task(url="https://youtube.com/watch?v=b", format="audio")
        all_tasks = mgr.get_all_tasks()
        ids = [ta["id"] for ta in all_tasks]
        assert t1.id in ids
        assert t2.id in ids

    def test_remove_task(self):
        import tasks
        importlib.reload(tasks)
        mgr = tasks.TaskManager()
        t = mgr.create_task(url="https://youtube.com/watch?v=del", format="video")
        tid = t.id
        mgr.remove_task(tid)
        assert mgr.get_task(tid) is None

    def test_remove_nonexistent_no_raise(self):
        import tasks
        importlib.reload(tasks)
        mgr = tasks.TaskManager()
        mgr.remove_task("no-such-id")  # should not raise

    def test_clear_completed_removes_completed(self):
        import tasks
        importlib.reload(tasks)
        mgr = tasks.TaskManager()
        t = mgr.create_task(url="https://youtube.com/watch?v=comp", format="video")
        t.update(status=TaskStatus.COMPLETED, filename="/fake.mp4")
        mgr.clear_completed()
        assert mgr.get_task(t.id) is None

    def test_clear_completed_keeps_pending(self):
        import tasks
        importlib.reload(tasks)
        mgr = tasks.TaskManager()
        t = mgr.create_task(url="https://youtube.com/watch?v=pend", format="video")
        mgr.clear_completed()
        assert mgr.get_task(t.id) is not None

    def test_save_load_cycle_pending(self):
        """Pending tasks are loaded back from disk by a new TaskManager instance."""
        import tasks
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "tasks_state.json")
            lock_file = os.path.join(tmpdir, "tasks_state.json.lock")

            orig_state = tasks._TASKS_STATE_FILE
            orig_lock = tasks._TASKS_LOCK_FILE
            tasks._TASKS_STATE_FILE = state_file
            tasks._TASKS_LOCK_FILE = lock_file

            try:
                mgr1 = tasks.TaskManager()
                t = mgr1.create_task(url="https://youtube.com/watch?v=save", format="audio")
                # Keep as pending (not completed) so _load_tasks recovers it
                mgr1.save_tasks()

                # Verify file was written
                assert os.path.exists(state_file)

                # New manager loads pending tasks from disk - they become error (interrupted)
                mgr2 = tasks.TaskManager()
                loaded = mgr2.get_task(t.id)
                assert loaded is not None, "Interrupted task should be recovered from disk"
                assert loaded.status == TaskStatus.ERROR
            finally:
                tasks._TASKS_STATE_FILE = orig_state
                tasks._TASKS_LOCK_FILE = orig_lock

    def test_save_load_cycle_completed_skipped(self):
        """Completed tasks are NOT recovered on restart (intentional)."""
        import tasks
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "tasks_state.json")
            lock_file = os.path.join(tmpdir, "tasks_state.json.lock")

            orig_state = tasks._TASKS_STATE_FILE
            orig_lock = tasks._TASKS_LOCK_FILE
            tasks._TASKS_STATE_FILE = state_file
            tasks._TASKS_LOCK_FILE = lock_file

            try:
                mgr1 = tasks.TaskManager()
                t = mgr1.create_task(url="https://youtube.com/watch?v=skip", format="audio")
                t.update(status=TaskStatus.COMPLETED, filename="/fake/song.mp3")
                mgr1.save_tasks()

                # New manager should NOT recover completed tasks
                mgr2 = tasks.TaskManager()
                loaded = mgr2.get_task(t.id)
                assert loaded is None, "Completed tasks should not be recovered"
            finally:
                tasks._TASKS_STATE_FILE = orig_state
                tasks._TASKS_LOCK_FILE = orig_lock

    def test_lock_file_created_on_save(self):
        import tasks
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "tasks_state.json")
            lock_file = os.path.join(tmpdir, "tasks_state.json.lock")

            orig_state = tasks._TASKS_STATE_FILE
            orig_lock = tasks._TASKS_LOCK_FILE
            tasks._TASKS_STATE_FILE = state_file
            tasks._TASKS_LOCK_FILE = lock_file

            try:
                mgr = tasks.TaskManager()
                mgr.save_tasks()
                assert os.path.exists(lock_file)
            finally:
                tasks._TASKS_STATE_FILE = orig_state
                tasks._TASKS_LOCK_FILE = orig_lock

    def test_flock_exclusive_on_save(self):
        """save_tasks uses exclusive lock (LOCK_EX)."""
        import tasks
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "tasks_state.json")
            lock_file = os.path.join(tmpdir, "tasks_state.json.lock")

            orig_state = tasks._TASKS_STATE_FILE
            orig_lock = tasks._TASKS_LOCK_FILE
            tasks._TASKS_STATE_FILE = state_file
            tasks._TASKS_LOCK_FILE = lock_file

            try:
                mgr = tasks.TaskManager()
                mgr.save_tasks()
                # Lock file should exist - open it and try locking
                import fcntl
                fd = open(lock_file, "w")
                try:
                    fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                finally:
                    fd.close()
            finally:
                tasks._TASKS_STATE_FILE = orig_state
                tasks._TASKS_LOCK_FILE = orig_lock
