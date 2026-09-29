"""One notification that can never be rendered (platform audit, 2026-09-29,
#15). The relay acks an entry only after it's handled, and run_forever
re-read its pending list before looking at anything new. An entry that
always raised, such as a Bot Content override with a stray '{}' or a
notify key an older bot doesn't know, was retried forever in a loop with
no sleep, and every later deposit confirmation, withdrawal result and
refund message for every player waited behind it."""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from packages.core import metrics
from packages.core.notifications import NOTIFICATIONS_STREAM
from services.bot import notification_relay
from tests.integration.conftest import next_telegram_id

pytestmark = pytest.mark.asyncio


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[int] = []

    async def send(self, chat_id: int, text: str, **kwargs: object) -> asyncio.Future[str]:
        self.sent.append(chat_id)
        done: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        done.set_result("delivered")
        return done


async def _poison(redis) -> tuple[str, int]:
    telegram_id = next_telegram_id()
    msg_id = await redis.xadd(
        NOTIFICATIONS_STREAM,
        {"telegram_id": str(telegram_id), "key": "notify.deposit_confirmed", "kwargs": "{not json"},
    )
    return msg_id, telegram_id


async def _run_relay_for(pool, redis, notifier, seconds: float) -> None:
    task = asyncio.create_task(notification_relay.run_forever(pool, redis, notifier))
    await asyncio.sleep(seconds)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_one_notification_that_always_fails_does_not_hold_up_everyone_else(pool, redis, monkeypatch):
    attempts = 0
    real_process_one = notification_relay.process_one

    async def counting_process_one(*args, **kwargs):
        nonlocal attempts
        if kwargs["fields"].get("kwargs") == "{not json":
            attempts += 1
        return await real_process_one(*args, **kwargs)

    monkeypatch.setattr(notification_relay, "process_one", counting_process_one)
    notifier = _RecordingNotifier()
    await notification_relay.ensure_group(redis)
    # The poison entry is already pending on this consumer (read once and
    # failed), as it would be after its first attempt.
    _, poisoned_player = await _poison(redis)
    await redis.xreadgroup(notification_relay.GROUP, "relay-1", {NOTIFICATIONS_STREAM: ">"}, count=10)
    waiting_player = next_telegram_id()
    await redis.xadd(  # what notify_user() writes
        NOTIFICATIONS_STREAM,
        {
            "telegram_id": str(waiting_player),
            "key": "notify.deposit_confirmed",
            "kwargs": json.dumps({"amount": "100.00", "balance": "250.00"}),
        },
    )

    await _run_relay_for(pool, redis, notifier, 2.0)

    assert waiting_player in notifier.sent
    assert poisoned_player not in notifier.sent
    assert attempts <= 3, f"retried {attempts} times in 2 s"


async def test_a_notification_that_keeps_failing_is_moved_aside_and_counted(pool, redis, monkeypatch):
    monkeypatch.setattr(notification_relay, "DEAD_LETTER_AFTER_ATTEMPTS", 3)
    monkeypatch.setattr(notification_relay, "DEAD_LETTER_AFTER_SECONDS", 0.0)
    monkeypatch.setattr(notification_relay, "RETRY_BACKOFF_BASE_SECONDS", 0.05)
    dead_before = metrics.notification_relay_dead_lettered_total._value.get()
    await notification_relay.ensure_group(redis)
    msg_id, _ = await _poison(redis)

    await _run_relay_for(pool, redis, _RecordingNotifier(), 2.0)

    pending = await redis.xpending(NOTIFICATIONS_STREAM, notification_relay.GROUP)
    assert pending["pending"] == 0
    dead = await redis.xrange(notification_relay.DEAD_LETTER_STREAM, "-", "+")
    moved = [fields for _id, fields in dead if fields.get("original_id") == msg_id]
    assert len(moved) == 1 and moved[0]["kwargs"] == "{not json"
    assert "JSONDecodeError" in moved[0]["error"]
    assert metrics.notification_relay_dead_lettered_total._value.get() == dead_before + 1
    assert json.loads(json.dumps(moved[0]))  # plain strings, replayable as-is
