"""消息治理聚合任务注册测试."""

from unittest.mock import MagicMock

from app.services import scheduler_jobs


def _deps(message):
    return {
        "thread_executor": MagicMock(),
        "site_userinfo": MagicMock(),
        "subscription_monitor": MagicMock(),
        "media_server": MagicMock(),
        "sync_engine": MagicMock(),
        "subscribe_service": MagicMock(),
        "message": message,
    }


def _flush_calls(scheduler):
    return [c for c in scheduler.register_interval.call_args_list if c.kwargs.get("job_id") == "MessageGovernor.flush"]


def test_registers_flush_job_when_enabled():
    scheduler = MagicMock()
    message = MagicMock()
    message.governor_flush_seconds.return_value = 45

    scheduler_jobs.load_default_jobs(scheduler, **_deps(message))

    calls = _flush_calls(scheduler)
    assert len(calls) == 1
    assert calls[0].kwargs["seconds"] == 45
    assert calls[0].kwargs["func"] == message.flush_governor


def test_skips_when_disabled():
    scheduler = MagicMock()
    message = MagicMock()
    message.governor_flush_seconds.return_value = 0

    scheduler_jobs.load_default_jobs(scheduler, **_deps(message))

    assert _flush_calls(scheduler) == []


def test_skips_without_message():
    scheduler = MagicMock()

    scheduler_jobs.load_default_jobs(scheduler, **_deps(None))

    assert _flush_calls(scheduler) == []


def test_skips_on_config_error():
    scheduler = MagicMock()
    message = MagicMock()
    message.governor_flush_seconds.side_effect = RuntimeError("boom")

    scheduler_jobs.load_default_jobs(scheduler, **_deps(message))

    assert _flush_calls(scheduler) == []
