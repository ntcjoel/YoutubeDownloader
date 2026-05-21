"""
Task management module - all tasks stored in memory dict with state transitions and history
"""
import os
import json
import fcntl
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional
from threading import Lock
from app_logging import get_logger

log = get_logger("tasks")

_TASKS_STATE_FILE = os.path.join(os.path.dirname(__file__), "tasks_state.json")
_TASKS_LOCK_FILE = _TASKS_STATE_FILE + ".lock"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class Task:
    def __init__(self, url: str, format: str, quality: str = "1080p", title: str = None, category: str = None):
        self.id = str(uuid.uuid4())[:8]
        self.url = url
        self.title = title
        self.format = format
        self.quality = quality
        self.category = category
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.message = "Pending..."
        self.filename: Optional[str] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now().strftime("%H:%M:%S")
        self.updated_at = datetime.now().strftime("%H:%M:%S")

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "format": self.format,
            "quality": self.quality,
            "category": self.category,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "filename": self.filename,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        t = cls(
            url=d["url"],
            format=d["format"],
            quality=d.get("quality", "1080p"),
            title=d.get("title"),
            category=d.get("category"),
        )
        t.id = d["id"]
        t.status = TaskStatus(d.get("status", "pending"))
        t.progress = d.get("progress", 0)
        t.message = d.get("message", "")
        t.filename = d.get("filename")
        t.error = d.get("error")
        t.created_at = d.get("created_at", datetime.now().strftime("%H:%M:%S"))
        t.updated_at = d.get("updated_at", datetime.now().strftime("%H:%M:%S"))
        return t

    def update(self, status: Optional[TaskStatus] = None,
                progress: Optional[int] = None,
                message: Optional[str] = None,
                filename: Optional[str] = None,
                error: Optional[str] = None,
                title: Optional[str] = None):
        if status is not None:
            self.status = status
        if progress is not None:
            self.progress = progress
        if message is not None:
            self.message = message
        if filename is not None:
            self.filename = filename
        if error is not None:
            self.error = error
        if title is not None:
            self.title = title
        self.updated_at = datetime.now().strftime("%H:%M:%S")


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._lock = Lock()
        self._processing_queue: list[str] = []
        self._current_task_id: Optional[str] = None
        self._history: list[dict] = []
        self._history_page_size = 10
        self._load_tasks()

    def _load_tasks(self):
        """Restore task states on startup. Incomplete tasks are marked as error."""
        if not os.path.exists(_TASKS_STATE_FILE):
            return
        try:
            if os.path.exists(_TASKS_LOCK_FILE):
                lock_fd = open(_TASKS_LOCK_FILE, "r")
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)
                try:
                    with open(_TASKS_STATE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                finally:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                    lock_fd.close()
            else:
                with open(_TASKS_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as e:
            log.warning("Failed to load task state: %s", e)
            return
        recovered = 0
        for d in data:
            # Skip completed tasks
            if d.get("status") == "completed":
                continue
            # Mark incomplete tasks as error (interrupted)
            if d.get("status") in ("downloading", "processing", "pending"):
                d["status"] = "error"
                d["error"] = d.get("error") or "Interrupted by server restart"
                d["message"] = "Interrupted"
            task = Task.from_dict(d)
            self._tasks[task.id] = task
            self._processing_queue.append(task.id)
            recovered += 1
        if recovered:
            log.info("Recovered %d task(s) from previous session", recovered)

    def _save_tasks(self):
        """Persist all task states to disk with file locking for thread safety."""
        try:
            lock_fd = open(_TASKS_LOCK_FILE, "w")
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                with open(_TASKS_STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump([t.to_dict() for t in self._tasks.values()], f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
        except Exception as e:
            log.warning("Failed to save task state: %s", e)

    def save_tasks(self):
        """Explicit save called by downloader after state changes."""
        self._save_tasks()

    def create_task(self, url: str, format: str, quality: str = "1080p", category: str = None) -> Task:
        with self._lock:
            task = Task(url, format, quality, category=category)
            self._tasks[task.id] = task
            self._processing_queue.append(task.id)
            self._save_tasks()
            return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[dict]:
        """Return all tasks sorted by creation time (newest first)"""
        with self._lock:
            return sorted(
                [t.to_dict() for t in self._tasks.values()],
                key=lambda x: x["created_at"],
                reverse=True
            )

    def get_pending_tasks(self) -> list[str]:
        """Return pending task IDs (excluding current running task)"""
        with self._lock:
            return [tid for tid in self._processing_queue
                    if tid != self._current_task_id and
                    self._tasks[tid].status in (TaskStatus.PENDING,)]

    def get_current_task_id(self) -> Optional[str]:
        return self._current_task_id

    def set_current_task(self, task_id: Optional[str]):
        self._current_task_id = task_id

    def mark_running(self, task_id: str):
        """Mark task as currently running"""
        with self._lock:
            self._current_task_id = task_id

    def remove_task(self, task_id: str):
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
            if task_id in self._processing_queue:
                self._processing_queue.remove(task_id)
            if self._current_task_id == task_id:
                self._current_task_id = None
        self._save_tasks()

    def clear_completed(self):
        """Remove all completed and error tasks"""
        with self._lock:
            completed = [tid for tid, t in self._tasks.items()
                         if t.status in (TaskStatus.COMPLETED, TaskStatus.ERROR)]
            for tid in completed:
                del self._tasks[tid]
                if tid in self._processing_queue:
                    self._processing_queue.remove(tid)
        self._save_tasks()

    def record_completed(self, task_id: str):
        """Record completed task in history"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            self._history.insert(0, {
                "id": task.id,
                "title": task.title,
                "url": task.url,
                "format": task.format,
                "quality": task.quality,
                "status": task.status.value,
                "filename": task.filename,
                "created_at": task.created_at,
                "completed_at": task.updated_at,
            })
            # Keep max 200 entries
            if len(self._history) > 200:
                self._history = self._history[:200]

    def get_history(self, page: int = 1) -> dict:
        """Return paginated history"""
        with self._lock:
            total = len(self._history)
            start = (page - 1) * self._history_page_size
            end = start + self._history_page_size
            pages = (total + self._history_page_size - 1) // self._history_page_size
            return {
                "items": self._history[start:end],
                "page": page,
                "pages": pages,
                "total": total,
            }


# Global singleton
task_manager = TaskManager()
