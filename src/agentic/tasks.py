from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal[
    "created",
    "running",
    "paused",
    "pause_requested",
    "cancelled",
    "cancel_requested",
    "completed",
    "failed",
    "failed_budget",
]
StepHandler = Callable[["TaskContext"], Any]
Emitter = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class TaskBudget:
    max_steps: int | None = None


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    query: str
    step_index: int
    step_name: str
    prior_results: list[Any]


@dataclass(frozen=True)
class StoredStep:
    index: int
    name: str
    result: Any
    completed_at: float


@dataclass(frozen=True)
class StoredTask:
    task_id: str
    query: str
    status: TaskStatus
    plan: list[str]
    steps: list[StoredStep]
    created_at: float
    updated_at: float
    error: str | None = None


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    results: list[Any] = field(default_factory=list)
    error: str | None = None


class TaskStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_task(self, query: str, plan: Sequence[str]) -> StoredTask:
        now = time.time()
        task_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agentic_tasks
                    (task_id, query, status, plan_json, created_at, updated_at, error)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (task_id, query, "created", json.dumps(list(plan)), now, now),
            )
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("Task was not persisted")
        return task

    def get_task(self, task_id: str) -> StoredTask | None:
        with self._connect() as conn:
            task_row = conn.execute(
                """
                SELECT task_id, query, status, plan_json, created_at, updated_at, error
                FROM agentic_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if task_row is None:
                return None
            step_rows = conn.execute(
                """
                SELECT step_index, step_name, result_json, completed_at
                FROM agentic_checkpoints
                WHERE task_id = ?
                ORDER BY step_index ASC
                """,
                (task_id,),
            ).fetchall()

        return self._row_to_task(task_row, step_rows)

    def list_tasks(self) -> list[StoredTask]:
        with self._connect() as conn:
            task_rows = conn.execute(
                """
                SELECT task_id, query, status, plan_json, created_at, updated_at, error
                FROM agentic_tasks
                ORDER BY created_at DESC, task_id DESC
                """
            ).fetchall()
        return [task for row in task_rows if (task := self.get_task(row["task_id"])) is not None]

    def update_status(self, task_id: str, status: TaskStatus, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agentic_tasks
                SET status = ?, updated_at = ?, error = ?
                WHERE task_id = ?
                """,
                (status, time.time(), error, task_id),
            )

    def request_pause(self, task_id: str) -> None:
        self.update_status(task_id, "pause_requested")

    def request_cancel(self, task_id: str) -> None:
        self.update_status(task_id, "cancel_requested")

    def save_checkpoint(self, task_id: str, step_index: int, step_name: str, result: Any) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agentic_checkpoints
                    (task_id, step_index, step_name, result_json, completed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, step_index, step_name, json.dumps(result, default=str), now),
            )
            conn.execute(
                """
                UPDATE agentic_tasks
                SET updated_at = ?
                WHERE task_id = ?
                """,
                (now, task_id),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agentic_tasks (
                    task_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agentic_checkpoints (
                    task_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    step_name TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    completed_at REAL NOT NULL,
                    PRIMARY KEY (task_id, step_index),
                    FOREIGN KEY (task_id) REFERENCES agentic_tasks(task_id)
                )
                """
            )

    @staticmethod
    def _row_to_task(task_row: sqlite3.Row, step_rows: Sequence[sqlite3.Row]) -> StoredTask:
        return StoredTask(
            task_id=task_row["task_id"],
            query=task_row["query"],
            status=task_row["status"],
            plan=json.loads(task_row["plan_json"]),
            steps=[
                StoredStep(
                    index=row["step_index"],
                    name=row["step_name"],
                    result=json.loads(row["result_json"]),
                    completed_at=row["completed_at"],
                )
                for row in step_rows
            ],
            created_at=task_row["created_at"],
            updated_at=task_row["updated_at"],
            error=task_row["error"],
        )


class AgenticTaskRunner:
    def __init__(self, store: TaskStore, emit: Emitter | None = None):
        self.store = store
        self._emit = emit or (lambda _kind, _payload: None)

    def start_task(
        self,
        query: str,
        steps: Sequence[tuple[str, StepHandler]],
        budget: TaskBudget | None = None,
    ) -> TaskResult:
        task = self.store.create_task(query, [name for name, _handler in steps])
        self.store.update_status(task.task_id, "running")
        self._emit("task_started", {"task_id": task.task_id, "query": query})
        return self._run(task.task_id, steps, budget or TaskBudget())

    def resume_task(
        self,
        task_id: str,
        steps: Sequence[tuple[str, StepHandler]],
        budget: TaskBudget | None = None,
    ) -> TaskResult:
        task = self.store.get_task(task_id)
        if task is None:
            return TaskResult(task_id=task_id, status="failed", error="task_not_found")
        if task.status == "completed":
            return TaskResult(task_id=task_id, status="completed", results=self._results(task))
        self.store.update_status(task_id, "running")
        self._emit("task_resumed", {"task_id": task_id, "from_step": len(task.steps)})
        return self._run(task_id, steps, budget or TaskBudget())

    def _run(
        self,
        task_id: str,
        steps: Sequence[tuple[str, StepHandler]],
        budget: TaskBudget,
    ) -> TaskResult:
        task = self.store.get_task(task_id)
        if task is None:
            return TaskResult(task_id=task_id, status="failed", error="task_not_found")

        completed = len(task.steps)
        results = self._results(task)
        for step_index in range(completed, len(steps)):
            control = self._control_status(task_id)
            if control is not None:
                return control
            if budget.max_steps is not None and step_index >= budget.max_steps:
                self.store.update_status(task_id, "failed_budget", "max_steps_exceeded")
                self._emit(
                    "budget_exhausted",
                    {"task_id": task_id, "at_step": step_index, "reason": "max_steps_exceeded"},
                )
                return TaskResult(
                    task_id=task_id,
                    status="failed_budget",
                    results=results,
                    error="max_steps_exceeded",
                )

            step_name, handler = steps[step_index]
            context = TaskContext(
                task_id=task_id,
                query=task.query,
                step_index=step_index,
                step_name=step_name,
                prior_results=list(results),
            )
            self._emit(
                "step_started",
                {"task_id": task_id, "step_index": step_index, "step_name": step_name},
            )
            try:
                result = handler(context)
            except Exception as exc:
                self.store.update_status(task_id, "failed", str(exc))
                self._emit("task_failed", {"task_id": task_id, "error": str(exc)})
                return TaskResult(task_id=task_id, status="failed", results=results, error=str(exc))

            self.store.save_checkpoint(task_id, step_index, step_name, result)
            results.append(result)
            self._emit(
                "step_completed",
                {
                    "task_id": task_id,
                    "step_index": step_index,
                    "step_name": step_name,
                    "result": result,
                },
            )

        control = self._control_status(task_id)
        if control is not None:
            return control

        self.store.update_status(task_id, "completed")
        self._emit("task_completed", {"task_id": task_id, "steps": len(results)})
        return TaskResult(task_id=task_id, status="completed", results=results)

    def _control_status(self, task_id: str) -> TaskResult | None:
        task = self.store.get_task(task_id)
        if task is None:
            return TaskResult(task_id=task_id, status="failed", error="task_not_found")
        if task.status == "pause_requested":
            self.store.update_status(task_id, "paused")
            self._emit("task_paused", {"task_id": task_id, "at_step": len(task.steps)})
            return TaskResult(task_id=task_id, status="paused", results=self._results(task))
        if task.status == "cancel_requested":
            self.store.update_status(task_id, "cancelled")
            self._emit("task_cancelled", {"task_id": task_id, "at_step": len(task.steps)})
            return TaskResult(task_id=task_id, status="cancelled", results=self._results(task))
        return None

    @staticmethod
    def _results(task: StoredTask) -> list[Any]:
        return [step.result for step in task.steps]
