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
_DATA_DIR = os.path.join(os.path.dirname(__file__), "logs")  # only dir 1000:1000 can write to
_TASKS_LOCK_FILE = os.path.join(_DATA_DIR, "tasks_state.json.lock")


class TaskType(str, Enum):
    SINGLE = "single"
    PLAYLIST = "playlist"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


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
        # Playlist fields
        self.task_type: str = "single"
        self.parent_id: Optional[str] = None
        self.total: int = 0
        self.completed: int = 0
        self.failed: int = 0
        self.children: list[str] = []

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
            "task_type": self.task_type,
            "parent_id": self.parent_id,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "children": self.children,
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
        t.task_type = d.get("task_type", "single")
        t.parent_id = d.get("parent_id")
        t.total = d.get("total", 0)
        t.completed = d.get("completed", 0)
        t.failed = d.get("failed", 0)
        t.children = d.get("children", [])
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
        """Restore task states on startup."""
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
            task = Task.from_dict(d)
            self._tasks[task.id] = task

            if task.task_type == "playlist":
                # Playlists: keep if downloading, mark error if pending/processing
                if task.status in (TaskStatus.DOWNLOADING, TaskStatus.PENDING):
                    self._processing_queue.append(task.id)
                    recovered += 1
                elif task.status == TaskStatus.PROCESSING:
                    task.status = TaskStatus.ERROR
                    task.message = "Interrupted"
                    task.error = "Interrupted by server restart"
                    self._processing_queue.append(task.id)
                    recovered += 1
                # completed/error/cancelled playlists - keep but don't re-queue
            else:
                # Single tasks
                if task.status == TaskStatus.COMPLETED:
                    continue  # skip
                if task.status in (TaskStatus.DOWNLOADING, TaskStatus.PROCESSING, TaskStatus.PENDING):
                    task.status = TaskStatus.ERROR
                    task.error = "Interrupted by server restart"
                    task.message = "Interrupted"
                self._processing_queue.append(task.id)
                recovered += 1

        if recovered:
            log.info("Recovered %d task(s) from previous session", recovered)

    def _save_tasks(self):
        """Persist all task states to disk with file locking."""
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
            task.task_type = "single"
            self._tasks[task.id] = task
            self._processing_queue.append(task.id)
            self._save_tasks()
            return task

    def create_playlist_task(self, url: str, format: str, quality: str, title: str,
                            children_ids: list[str], category: str = None) -> Task:
        """Create a playlist task with pre-created child IDs."""
        with self._lock:
            task = Task(url, format, quality, title=title, category=category)
            task.task_type = "playlist"
            task.status = TaskStatus.DOWNLOADING
            task.children = children_ids
            task.total = len(children_ids)
            task.completed = 0
            task.failed = 0
            self._tasks[task.id] = task
            self._processing_queue.append(task.id)
            self._save_tasks()
            return task

    def add_child_task(self, child_task: Task):
        """Register a video sub-task."""
        with self._lock:
            self._tasks[child_task.id] = child_task

    def on_child_done(self, child_id: str, child_status: TaskStatus):
        """Called when a SubTask finishes — update playlist counters and status."""
        with self._lock:
            child = self._tasks.get(child_id)
            if not child or not child.parent_id:
                return
            parent = self._tasks.get(child.parent_id)
            if not parent or parent.task_type != "playlist":
                return

            if child_status == TaskStatus.COMPLETED:
                parent.completed += 1
            elif child_status in (TaskStatus.ERROR, TaskStatus.CANCELLED):
                parent.failed += 1

            total_done = parent.completed + parent.failed
            parent.progress = int(total_done / parent.total * 100) if parent.total > 0 else 0
            parent.message = f"{total_done}/{parent.total}"

            if total_done >= parent.total:
                if parent.failed == 0:
                    parent.status = TaskStatus.COMPLETED
                    parent.message = "Done"
                elif parent.completed > 0:
                    parent.status = TaskStatus.ERROR
                    parent.message = f"Done ({parent.failed} failed)"
                else:
                    parent.status = TaskStatus.ERROR
                    parent.message = f"All {parent.failed} failed"
            self._save_tasks()

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
            task = self._tasks.get(task_id)
            if not task:
                return
            # Cascade delete for playlist
            if task.task_type == "playlist":
                for cid in task.children:
                    if cid in self._tasks:
                        del self._tasks[cid]
                    if cid in self._processing_queue:
                        self._processing_queue.remove(cid)
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
            to_remove = []
            for tid, t in self._tasks.items():
                if t.task_type == "playlist":
                    if t.status not in (TaskStatus.COMPLETED, TaskStatus.ERROR, TaskStatus.CANCELLED):
                        continue
                else:
                    if t.status not in (TaskStatus.COMPLETED, TaskStatus.ERROR):
                        continue
                to_remove.append(tid)
            for tid in to_remove:
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
