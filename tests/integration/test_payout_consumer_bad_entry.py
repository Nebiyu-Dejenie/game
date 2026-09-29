"""The payout consumer and an entry it can't use (platform audit,
2026-09-29, #31). run_forever read fields['our_ref'] to call process_one
and read it again in its except handler, so an entry without one (a hand
XADD with only payment_id, say) raised KeyError inside the handler. That
ended run_forever, the entry was never acked, and the next start read it
first and died again. main_async never looked at the consumer task, so the
process kept running its sweeps and metrics server with nothing paying
anyone out."""

from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal

from redis.exceptions import ConnectionError as RedisConnectionError

from services.payments import payout_worker, withdrawals
from tests.integration.conftest import create_funded_user
from tests.integration.test_payout_worker import FakePayoutProvider, _approved_withdrawal


async def test_an_entry_without_our_ref_is_dropped_and_the_consumer_keeps_paying(pool, redis, conn):
    await redis.xadd(withdrawals.PAYOUT_STREAM, {"payment_id": "12345"})
    user_id = await create_funded_user(conn, Decimal("500.00"))
    our_ref = await _approved_withdrawal(pool, redis, conn, user_id, Decimal("100.00"))

    task = asyncio.create_task(
        payout_worker.run_forever(pool, redis, FakePayoutProvider(), consumer_name="w-bad-entry")
    )
    try:
        for _ in range(50):
            status = await conn.fetchval("SELECT status FROM payments WHERE our_ref = $1", our_ref)
            if status == "succeeded" or task.done():
                break
            await asyncio.sleep(0.1)
        assert not task.done(), f"run_forever() died: {task.exception()!r}"
        assert status == "succeeded"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Acked, so a restart doesn't read it first and stall on it again.
    pending = await redis.xpending(withdrawals.PAYOUT_STREAM, payout_worker.GROUP)
    assert pending["pending"] == 0


class _Closable:
    async def close(self) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass


async def test_the_worker_process_exits_when_its_consumer_task_dies(monkeypatch):
    # Redis not reachable yet when the worker starts: ensure_group() sits
    # before run_forever's loop, outside its exception handling.
    async def redis_down(_redis):
        raise RedisConnectionError("Connection refused")

    async def fake_pool(**_kwargs):
        return _Closable()

    async def fake_metrics_server(_port):
        return _Closable()

    monkeypatch.setattr(payout_worker, "ensure_group", redis_down)
    monkeypatch.setattr(payout_worker, "create_pool", fake_pool)
    monkeypatch.setattr(payout_worker, "get_redis", _Closable)
    monkeypatch.setattr(payout_worker, "configure_logging", lambda _level: None)
    monkeypatch.setattr(payout_worker.tracing, "configure_tracing", lambda *_a: None)
    monkeypatch.setattr(payout_worker.metrics, "start_metrics_server", fake_metrics_server)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *_a: None)

    # Returning lets the process exit, and restart: unless-stopped brings
    # it back. Before, it waited for SIGTERM forever.
    await asyncio.wait_for(payout_worker.main_async(), timeout=5)
