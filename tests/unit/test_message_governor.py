"""MessageGovernor 消息治理层单元测试."""

from typing import Any
from unittest.mock import MagicMock, patch

from app.message.core.dispatcher import MessageDispatcher
from app.message.core.governor import GovernorPolicy, MessageGovernor, build_policies
from app.message.core.governor_store import MemoryGovernorStore
from app.message.core.template_engine import TemplateEngine


def _client(client_id=1, name="TG"):
    return {"id": client_id, "name": name, "client": MagicMock()}


def _resolver(cid):
    return _client(int(cid)) if str(cid).isdigit() else None


class TestMemoryGovernorStore:
    def test_window_incr_and_ttl(self):
        store = MemoryGovernorStore()
        now = [1000.0]
        store = MemoryGovernorStore(clock=lambda: now[0])
        assert store.incr_window("k", 10) == 1
        assert store.incr_window("k", 10) == 2
        now[0] += 11
        assert store.incr_window("k", 10) == 1

    def test_dedup_expiry(self):
        now = [1000.0]
        store = MemoryGovernorStore(clock=lambda: now[0])
        assert store.mark_dedup("d", 5) is False
        assert store.mark_dedup("d", 5) is True
        now[0] += 6
        assert store.mark_dedup("d", 5) is False

    def test_append_drain_and_keys(self):
        store = MemoryGovernorStore()
        store.append("msg_governor:buf:a", "1", 60)
        store.append("msg_governor:buf:b", "2", 60)
        assert sorted(store.keys("msg_governor:buf:*")) == ["msg_governor:buf:a", "msg_governor:buf:b"]
        assert store.drain("msg_governor:buf:a") == ["1"]
        assert store.drain("msg_governor:buf:a") == []


class TestGovernorStandalone:
    def _governor(self, **kwargs):
        sender = MagicMock(return_value=True)
        policies = kwargs.pop(
            "policies",
            {
                "digest_type": GovernorPolicy(mode="digest", threshold=2, window=60),
                "dedup_type": GovernorPolicy(mode="dedup", dedup_ttl=300),
            },
        )
        gov = MessageGovernor(
            sender=sender,
            store=MemoryGovernorStore(),
            client_resolver=_resolver,
            policies=policies,
            **kwargs,
        )
        return gov, sender

    def _intercept(self, gov, *, client=None, title="t", text="x", user_id="", msg_type="digest_type"):
        return gov.intercept(
            client=client or _client(),
            title=title,
            text=text,
            image=None,
            url=None,
            user_id=user_id,
            msg_type=msg_type,
        )

    def test_immediate_passes_through(self):
        gov, _ = self._governor()
        assert self._intercept(gov, msg_type="unknown_type") is False

    def test_disabled_always_passes(self):
        gov, _ = self._governor(enabled=False)
        for _ in range(10):
            assert self._intercept(gov) is False

    def test_dedup_suppresses_identical_within_ttl(self):
        gov, _ = self._governor()
        assert self._intercept(gov, msg_type="dedup_type", title="same", text="body") is False
        assert self._intercept(gov, msg_type="dedup_type", title="same", text="body") is True
        assert self._intercept(gov, msg_type="dedup_type", title="same", text="other") is False

    def test_dedup_isolated_per_user(self):
        gov, _ = self._governor()
        assert self._intercept(gov, msg_type="dedup_type", user_id="u1") is False
        assert self._intercept(gov, msg_type="dedup_type", user_id="u2") is False

    def test_digest_threshold_then_buffer(self):
        gov, sender = self._governor()
        assert self._intercept(gov, title="a") is False
        assert self._intercept(gov, title="b") is False
        assert self._intercept(gov, title="c") is True
        assert self._intercept(gov, title="d") is True
        assert sender.call_count == 0

        gov.flush_once()
        assert sender.call_count == 1
        kwargs = sender.call_args.kwargs
        assert "已合并" in kwargs["title"]
        assert "2" in kwargs["title"]
        assert "c" in kwargs["text"] and "d" in kwargs["text"]
        assert kwargs["client"].get("id") == 1

    def test_digest_isolated_per_user_and_client(self):
        gov, sender = self._governor(policies={"digest_type": GovernorPolicy(mode="digest", threshold=1)})
        self._intercept(gov, user_id="u1", title="u1-1")
        # 另一用户的第一条仍立即放行
        assert self._intercept(gov, user_id="u2", title="u2-1") is False
        gov.flush_once()
        assert sender.call_count == 0

    def test_flush_uses_switch_label(self):
        gov, sender = self._governor(policies={"transfer_fail": GovernorPolicy(mode="digest", threshold=0)})
        self._intercept(gov, msg_type="transfer_fail", title="入库失败A")
        gov.flush_once()
        assert sender.call_count == 1
        assert "入库失败" in sender.call_args.kwargs["title"]

    def test_digest_truncates_samples(self):
        gov, sender = self._governor(
            policies={"digest_type": GovernorPolicy(mode="digest", threshold=0)},
            max_samples=2,
        )
        for i in range(5):
            self._intercept(gov, title=f"m{i}")
        gov.flush_once()
        text = sender.call_args.kwargs["text"]
        assert "m0" in text and "m1" in text
        assert "m4" not in text
        assert "另有 3 条" in text

    def test_sender_failure_does_not_raise(self):
        gov, sender = self._governor(policies={"digest_type": GovernorPolicy(mode="digest", threshold=0)})
        sender.side_effect = RuntimeError("boom")
        self._intercept(gov, title="x")
        gov.flush_once()

    def test_digest_uses_default_template(self):
        sender = MagicMock(return_value=True)
        gov = MessageGovernor(
            sender=sender,
            store=MemoryGovernorStore(),
            client_resolver=_resolver,
            policies={"transfer_fail": GovernorPolicy(mode="digest", threshold=0)},
            template_engine=TemplateEngine(),
        )
        gov.intercept(
            client=_client(),
            title="入库失败A",
            text="",
            image=None,
            url=None,
            user_id="",
            msg_type="transfer_fail",
        )
        gov.flush_once()
        title = sender.call_args.kwargs["title"]
        text = sender.call_args.kwargs["text"]
        assert "入库失败" in title and "1" in title
        assert "入库失败A" in text

    def test_missing_client_still_sends_summary(self):
        gov, sender = self._governor(policies={"digest_type": GovernorPolicy(mode="digest", threshold=0)})
        gov.intercept(
            client={"id": "missing", "name": "gone", "client": MagicMock()},
            title="x",
            text="",
            image=None,
            url=None,
            user_id="",
            msg_type="digest_type",
        )
        gov.flush_once()
        assert sender.call_count == 1
        assert sender.call_args.kwargs["client"] is None


class TestBuildPolicies:
    def test_overrides_mode_and_threshold(self):
        policies = build_policies({"transfer_fail": "immediate"}, {"custom_message": 9})
        assert policies["transfer_fail"].mode == "immediate"
        assert policies["custom_message"].threshold == 9
        assert policies["download_fail"].mode == "digest"

    def test_unknown_type_gets_default_base(self):
        policies = build_policies({"brand_new": "dedup"})
        assert policies["brand_new"].mode == "dedup"

    def test_bad_threshold_ignored(self):
        bad: dict[str, Any] = {"transfer_fail": "not-a-number"}
        policies = build_policies(None, bad)
        assert policies["transfer_fail"].threshold == 3


class TestDispatcherIntegration:
    def _dispatcher(self):
        with patch("app.message.core.dispatcher.MessageQueueFactory.create") as create:
            queue = MagicMock()
            queue.submit.return_value = True
            create.return_value = queue
            dispatcher = MessageDispatcher(MagicMock(), MagicMock())
        return dispatcher, queue

    def test_sendmsg_governed_and_flushed(self):
        dispatcher, queue = self._dispatcher()
        governor = MessageGovernor(
            sender=dispatcher.submit_now,
            store=MemoryGovernorStore(),
            client_resolver=_resolver,
            policies={"transfer_fail": GovernorPolicy(mode="digest", threshold=2)},
        )
        dispatcher.set_governor(governor)
        client = _client()

        assert dispatcher.sendmsg(client, "t1", "x", msg_type="transfer_fail") is True
        assert dispatcher.sendmsg(client, "t2", "x", msg_type="transfer_fail") is True
        assert queue.submit.call_count == 2

        assert dispatcher.sendmsg(client, "t3", "x", msg_type="transfer_fail") is True
        assert queue.submit.call_count == 2

        governor.flush_once()
        assert queue.submit.call_count == 3
        summary_title = queue.submit.call_args.args[2]
        assert "已合并" in summary_title

    def test_governor_exception_falls_back_to_send(self):
        dispatcher, queue = self._dispatcher()
        governor = MagicMock()
        governor.intercept.side_effect = RuntimeError("boom")
        dispatcher.set_governor(governor)
        assert dispatcher.sendmsg(_client(), "t", "x", msg_type="transfer_fail") is True
        assert queue.submit.call_count == 1

    def test_immediate_type_always_enqueued(self):
        dispatcher, queue = self._dispatcher()
        governor = MessageGovernor(
            sender=dispatcher.submit_now,
            store=MemoryGovernorStore(),
            client_resolver=_resolver,
            policies={"custom_message": GovernorPolicy(mode="immediate")},
        )
        dispatcher.set_governor(governor)
        for i in range(5):
            dispatcher.sendmsg(_client(), f"t{i}", "x", msg_type="custom_message")
        assert queue.submit.call_count == 5
