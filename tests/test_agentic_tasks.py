from src.agentic.tasks import AgenticTaskRunner, TaskBudget, TaskContext, TaskStore


def test_runner_persists_task_checkpoints_and_events(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    events = []
    runner = AgenticTaskRunner(
        store=store,
        emit=lambda kind, payload: events.append((kind, payload)),
    )

    def first_step(ctx: TaskContext):
        return {"step": ctx.step_index, "query": ctx.query}

    def second_step(ctx: TaskContext):
        return {"prior": ctx.prior_results[0]["step"]}

    result = runner.start_task(
        query="research RELIANCE",
        steps=[("first", first_step), ("second", second_step)],
    )

    task = store.get_task(result.task_id)
    assert result.status == "completed"
    assert result.results == [{"step": 0, "query": "research RELIANCE"}, {"prior": 0}]
    assert task is not None
    assert task.status == "completed"
    assert [step.name for step in task.steps] == ["first", "second"]
    assert [step.result for step in task.steps] == result.results
    assert [kind for kind, _ in events] == [
        "task_started",
        "step_started",
        "step_completed",
        "step_started",
        "step_completed",
        "task_completed",
    ]


def test_runner_pauses_between_steps_and_resume_continues_from_checkpoint(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    runner = AgenticTaskRunner(store=store)
    calls = []

    def first_step(ctx: TaskContext):
        calls.append("first")
        store.request_pause(ctx.task_id)
        return {"ok": "first"}

    def second_step(ctx: TaskContext):
        calls.append("second")
        return {"prior": ctx.prior_results[0]["ok"]}

    paused = runner.start_task(
        query="research INFY",
        steps=[("first", first_step), ("second", second_step)],
    )
    resumed = runner.resume_task(
        paused.task_id,
        steps=[("first", first_step), ("second", second_step)],
    )

    assert paused.status == "paused"
    assert resumed.status == "completed"
    assert resumed.results == [{"ok": "first"}, {"prior": "first"}]
    assert calls == ["first", "second"]


def test_runner_cancels_between_steps_when_cancel_requested(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    runner = AgenticTaskRunner(store=store)

    def first_step(ctx: TaskContext):
        store.request_cancel(ctx.task_id)
        return {"ok": True}

    def second_step(_: TaskContext):
        raise AssertionError("cancelled task should not execute remaining steps")

    result = runner.start_task(
        query="research SBIN",
        steps=[("first", first_step), ("second", second_step)],
    )

    task = store.get_task(result.task_id)
    assert result.status == "cancelled"
    assert result.results == [{"ok": True}]
    assert task is not None
    assert task.status == "cancelled"


def test_runner_stops_when_budget_is_exhausted(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    runner = AgenticTaskRunner(store=store)

    def make_step(name: str):
        def step(_: TaskContext):
            return {"name": name}

        return step

    result = runner.start_task(
        query="research TCS",
        steps=[("one", make_step("one")), ("two", make_step("two"))],
        budget=TaskBudget(max_steps=1),
    )

    task = store.get_task(result.task_id)
    assert result.status == "failed_budget"
    assert result.results == [{"name": "one"}]
    assert task is not None
    assert task.status == "failed_budget"
    assert task.error == "max_steps_exceeded"


def test_store_lists_tasks_newest_first(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    first = store.create_task("first query", ["step"])
    second = store.create_task("second query", ["step"])

    assert [task.task_id for task in store.list_tasks()] == [second.task_id, first.task_id]
