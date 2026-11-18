"""Asynchronous multi-agent background worker and proactive task queue for DarkShadow Level 4.

Enables non-blocking long-horizon tasks (web research, price monitoring, file analysis)
and proactive event-driven notifications without stalling the main UI or Live Voice WebSocket.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """Represents one asynchronous background job."""

    task_id: str
    name: str
    func: Callable[..., Any]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    notified: bool = False


class BackgroundAgentManager:
    """Manages asynchronous worker threads, task lifecycle, and proactive event dispatch."""

    _instance: BackgroundAgentManager | None = None
    _lock = threading.Lock()

    def __init__(self, max_workers: int = 4) -> None:
        self.max_workers = max(1, int(max_workers))
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="DarkShadow-Worker",
        )
        self._tasks: dict[str, BackgroundTask] = {}
        self._tasks_lock = threading.Lock()
        self._completed_notifications: list[str] = []
        self._proactive_monitors: list[Callable[[], str | None]] = []
        self._running = True
        self._monitor_thread: threading.Thread | None = None
        self._start_monitor_daemon()

    @classmethod
    def get_instance(cls) -> BackgroundAgentManager:
        """Singleton accessor for the background agent manager."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def dispatch(
        self,
        name: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Submit a task to execute asynchronously in the bounded worker pool. Returns task ID."""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = BackgroundTask(
            task_id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
        )
        with self._tasks_lock:
            self._tasks[task_id] = task

        self._executor.submit(self._execute_task, task)
        LOGGER.info("Dispatched background task %s ('%s') to worker pool", task_id, name)
        return task_id

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending background task if it hasn't completed."""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                return False
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            LOGGER.info("Cancelled background task %s ('%s')", task_id, task.name)
            return True

    def _execute_task(self, task: BackgroundTask) -> None:
        """Worker thread loop executing the background task."""
        task.status = TaskStatus.RUNNING
        try:
            res = task.func(*task.args, **task.kwargs)
            task.result = res
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            msg = f"Task '{task.name}' poora ho gaya hai."
            if isinstance(res, dict) and "message" in res:
                msg = f"Task '{task.name}': {res['message']}"
            elif isinstance(res, str) and res:
                msg = f"Task '{task.name}': {res}"
            with self._tasks_lock:
                self._completed_notifications.append(msg)
            LOGGER.info("Background task %s completed successfully", task.task_id)
        except Exception as exc:
            LOGGER.warning("Background task %s failed: %s", task.task_id, exc)
            task.error = str(exc)
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            with self._tasks_lock:
                self._completed_notifications.append(
                    f"Task '{task.name}' me error aaya: {exc}"
                )

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        """Query status and result of a specific background task."""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status.value,
                "result": task.result,
                "error": task.error,
                "created_at": task.created_at,
                "completed_at": task.completed_at,
            }

    def list_tasks(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return list of recent background tasks."""
        with self._tasks_lock:
            recent = list(self._tasks.values())[-limit:]
            return [
                {
                    "task_id": t.task_id,
                    "name": t.name,
                    "status": t.status.value,
                    "completed_at": t.completed_at,
                }
                for t in reversed(recent)
            ]

    def pop_notifications(self) -> list[str]:
        """Retrieve and clear pending proactive / completed notifications."""
        with self._tasks_lock:
            notifs = list(self._completed_notifications)
            self._completed_notifications.clear()
            return notifs

    def register_proactive_monitor(self, monitor_fn: Callable[[], str | None]) -> None:
        """Register a periodic monitor function (e.g. price checker, system alerts)."""
        with self._tasks_lock:
            self._proactive_monitors.append(monitor_fn)

    def _start_monitor_daemon(self) -> None:
        """Start daemon thread that periodically checks proactive monitors and ambient sentinels."""
        try:
            from sentinel_copilot import SentinelCoordinator
            sentinel = SentinelCoordinator()
            def _sentinel_check() -> str | None:
                alerts = sentinel.run_all_checks()
                return "\n".join(alerts) if alerts else None
            self.register_proactive_monitor(_sentinel_check)
        except Exception as sent_err:
            LOGGER.debug("Sentinel auto-registration notice: %s", sent_err)

        def _loop() -> None:
            while self._running:
                time.sleep(30.0)  # Check monitors every 30 seconds
                try:
                    with self._tasks_lock:
                        monitors = list(self._proactive_monitors)
                    for m in monitors:
                        try:
                            alert = m()
                            if alert:
                                with self._tasks_lock:
                                    self._completed_notifications.append(str(alert))
                        except Exception as m_exc:
                            LOGGER.debug("Proactive monitor exception: %s", m_exc)
                except Exception as loop_exc:
                    LOGGER.debug("Monitor daemon loop error: %s", loop_exc)

        self._monitor_thread = threading.Thread(
            target=_loop,
            name="DarkShadow-ProactiveMonitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def shutdown(self) -> None:
        """Stop monitor daemon and worker pool."""
        self._running = False
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass
