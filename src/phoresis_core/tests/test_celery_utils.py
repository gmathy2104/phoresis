"""Tests for phoresis_core.celery_utils."""

from phoresis_core.celery_utils import RobustTask, robust_task


def test_robust_task_decorator_returns_celery_task() -> None:
    @robust_task(soft_time_limit=10, time_limit=20)
    def my_task(self, x):
        return x * 2

    assert hasattr(my_task, "delay")
    assert hasattr(my_task, "apply_async")


def test_robust_task_uses_robust_task_base() -> None:
    @robust_task(soft_time_limit=10, time_limit=20)
    def my_task(self, x):
        return x

    assert isinstance(my_task, RobustTask) or issubclass(my_task.__class__, RobustTask)


def test_robust_task_runs_eagerly_in_test_mode(settings) -> None:
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True

    @robust_task(soft_time_limit=10, time_limit=20)
    def add(self, a, b):
        return a + b

    result = add.apply(args=(2, 3)).get()
    assert result == 5
