"""ThreadExecutor 上下文传播测试：提交到线程池应继承调用方 contextvars。"""

import contextvars

from app.infrastructure.thread.executor import ThreadExecutor

_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("executor_ctx_var", default="default")


def _read_var() -> str:
    return _VAR.get()


def test_executor_propagates_contextvars():
    executor = ThreadExecutor(max_workers=1, name="ctx-propagation-test")
    try:
        token = _VAR.set("from-caller")
        try:
            assert executor.submit(_read_var).result(timeout=5) == "from-caller"
        finally:
            _VAR.reset(token)
    finally:
        executor.shutdown(wait=True)
