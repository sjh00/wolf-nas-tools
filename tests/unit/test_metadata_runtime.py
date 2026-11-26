"""Provider runtime 限流/熔断/URL 安全测试."""

import pytest

from app.media.metadata import ProviderDescriptor
from app.media.metadata.runtime import ProviderRuntime, UnsafeProviderURL, validate_outbound_url


def test_validate_url_rejects_loopback_and_private():
    with pytest.raises(UnsafeProviderURL):
        validate_outbound_url("http://127.0.0.1:8080/x")
    with pytest.raises(UnsafeProviderURL):
        validate_outbound_url("http://localhost/x")
    with pytest.raises(UnsafeProviderURL):
        validate_outbound_url("http://192.168.1.10/x")


def test_runtime_opens_circuit_after_failures():
    runtime = ProviderRuntime(
        ProviderDescriptor(
            provider_key="demo",
            display_name="demo",
            circuit_failures=2,
            circuit_cooldown_seconds=60,
        )
    )
    runtime.record_failure()
    runtime.record_failure()

    with pytest.raises(Exception, match="熔断"):
        runtime.acquire()

    runtime.record_success()
    runtime.acquire()


def test_runtime_is_open_flips_and_cooldown_grows():
    """熔断状态可查询，且连续失败时冷却时间要翻倍，否则限流源会一直被请求."""
    runtime = ProviderRuntime(
        ProviderDescriptor(
            provider_key="demo-cooldown",
            display_name="demo",
            circuit_failures=2,
            circuit_cooldown_seconds=60,
        )
    )
    assert runtime.is_open is False

    runtime.record_failure()
    assert runtime.is_open is False

    runtime.record_failure()
    assert runtime.is_open is True
    first = runtime.snapshot()["open_until_seconds"]

    runtime.record_failure()
    second = runtime.snapshot()["open_until_seconds"]
    assert second > first

    runtime.record_success()
    assert runtime.is_open is False
