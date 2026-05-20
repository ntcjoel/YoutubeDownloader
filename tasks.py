"""
任务管理模块
所有任务存储在内存字典中，支持状态流转和历史记录
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional
from threading import Lock

class TaskStatus(str, Enum):
    PENDING = "pending"          # 等待中
    DOWNLOADING = "downloading"  # 下载中
    PROCESSING = "processing"    # 处理中（如合并）
    COMPLETED = "completed"      # 完成
    ERROR = "error"              # 错误

class Task:
    def __init__(self, url: str, format: str, quality: str = "1080p", title: str = None):
        self.id = str(uuid.uuid4())[:8]
        self.url = url
        self.title = title        # 视频标题
        self.format = format          # "video" or "audio"
        self.quality = quality        # "1080p", "720p", etc.
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.message = "等待中..."
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
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "filename": self.filename,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

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
        self._processing_queue: list[str] = []   # 等待处理的任务ID队列
        self._current_task_id: Optional[str] = None
        self._history: list[dict] = []            # 完成的下载历史（分页）
        self._history_page_size = 10

    def create_task(self, url: str, format: str, quality: str = "1080p") -> Task:
        with self._lock:
            task = Task(url, format, quality)
            self._tasks[task.id] = task
            self._processing_queue.append(task.id)
            return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[dict]:
        """返回所有任务，按创建时间倒序"""
        with self._lock:
            return sorted(
                [t.to_dict() for t in self._tasks.values()],
                key=lambda x: x["created_at"],
                reverse=True
            )

    def get_pending_tasks(self) -> list[str]:
        """返回等待处理的任务ID列表（不含正在处理的）"""
        with self._lock:
            return [tid for tid in self._processing_queue
                    if tid != self._current_task_id and
                    self._tasks[tid].status in (TaskStatus.PENDING,)]

    def get_current_task_id(self) -> Optional[str]:
        return self._current_task_id

    def set_current_task(self, task_id: Optional[str]):
        self._current_task_id = task_id

    def mark_running(self, task_id: str):
        """标记任务为当前运行状态"""
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

    def clear_completed(self):
        """清除所有已完成和错误的任务"""
        with self._lock:
            completed = [tid for tid, t in self._tasks.items()
                         if t.status in (TaskStatus.COMPLETED, TaskStatus.ERROR)]
            for tid in completed:
                del self._tasks[tid]
                if tid in self._processing_queue:
                    self._processing_queue.remove(tid)

    def record_completed(self, task_id: str):
        """将完成的任务记入历史记录"""
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
            # 最多保留 200 条
            if len(self._history) > 200:
                self._history = self._history[:200]

    def get_history(self, page: int = 1) -> dict:
        """返回分页后的历史记录"""
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


# 全局单例
task_manager = TaskManager()
