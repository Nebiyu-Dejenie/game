"""A Bingo room's round loop used to end on the first Redis or Postgres
error it met (platform audit, 2026-09-29). Every room broadcasts each lobby
tick and each call, so one Redis blip raised out of every room's loop at
once; a single failed per-call UPDATE did the same to one room, and so did
a winner's balance push failing after the payout had committed. The engine
task ended mid-round, and the worker's next recovery sweep voided and
refunded the round, so a player who was about to win lost the win.
Reproduced here with a Redis publish, and a per-call UPDATE, that each
fail once."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import asyncpg
import pytest
import redis.exceptions

from packages.core import bingo
from services.engine import round_engine
from services.engine.round_engine import RoundEngine, load_room_config
from tests.integration.conftest import create_funded_user, create_room

pytestmark = pytest.mark.asyncio

# Two lines, since a win needs the room's min_winning_lines (2 by default).
_TWO_LINES = [
    bingo.Pattern(name="row_0", kind="row", cells=((0, 0), (0, 1), (0, 2), (0, 3), (0, 4))),
    bingo.Pattern(name="col_0", kind="col", cells=((0, 0), (1, 0), (2, 0), (3, 0), (4, 0))),
]


class _RedisPublishFailsOnce:
    """The real client, except that the first publish matching `should_fail`
    raises the ConnectionError a dropped Redis connection gives (the client
    is configured with no retries)."""

    def __init__(self, real_redis, should_fail) -> None:
        self._real = real_redis
        self._should_fail = should_fail
        self.failed = asyncio.Event()

    async def publish(self, channel, message):
        if not self.failed.is_set() and self._should_fail(channel, message):
            self.failed.set()
            raise redis.exceptions.ConnectionError("Connection closed by server.")
        return await self._real.publish(channel, message)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _PoolFetchrowFailsOnce:
    """The real pool, except that the first fetchrow whose SQL starts with
    `sql_prefix` raises the error a pooled connection dropped by Postgres
    gives."""

    def __init__(self, real_pool, sql_prefix: str) -> None:
        self._real = real_pool
        self._sql_prefix = sql_prefix
        self.failed = asyncio.Event()

    async def fetchrow(self, query, *args, **kwargs):
        if not self.failed.is_set() and query.startswith(self._sql_prefix):
            self.failed.set()
            raise asyncpg.exceptions.ConnectionDoesNotExistError("connection was closed in the middle of operation")
        return await self._real.fetchrow(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


async def _wait_until(predicate, timeout: float = 10.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def _settled_or_engine_ended(pool, task: asyncio.Task, round_id: int, timeout: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline and not task.done():
        if await pool.fetchval("SELECT status FROM rounds WHERE id = $1", round_id) in ("done", "voided"):
            return
        await asyncio.sleep(0.05)


async def _start_two_player_round(engine_pool, engine_redis, pool, card_pool, conn, *, is_active: bool = False):
    room_id = await create_room(
        conn, stake=Decimal("10.00"), min_players=2, call_interval_ms=15, is_active=is_active
    )
    room = await load_room_config(pool, room_id)
    engine = RoundEngine(engine_pool, engine_redis, room, card_pool)
    task = asyncio.create_task(engine.run_forever())
    user_a = await create_funded_user(conn)
    user_b = await create_funded_user(conn)
    assert (await engine.join(user_a, 1, auto_mark=True)).ok
    assert (await engine.join(user_b, 2, auto_mark=True)).ok
    await _wait_until(lambda: engine.status == "running", timeout=5)
    return room_id, engine, task, user_a


def _card_1_wins(monkeypatch, card_pool) -> None:
    grid_a = card_pool[1]
    monkeypatch.setattr(
        round_engine.bingo, "winning_patterns", lambda grid, called, enabled: _TWO_LINES if grid is grid_a else []
    )


async def _winners(pool, round_id: int) -> set[int]:
    return {r["user_id"] for r in await pool.fetch("SELECT user_id FROM round_winners WHERE round_id = $1", round_id)}


async def test_a_redis_error_broadcasting_a_call_does_not_end_the_round(pool, redis, card_pool, conn, monkeypatch):
    flaky_redis = _RedisPublishFailsOnce(redis, lambda channel, message: json.loads(message).get("t") == "call")
    room_id, engine, task, user_a = await _start_two_player_round(pool, flaky_redis, pool, card_pool, conn)
    round_id = engine.round_id
    try:
        await asyncio.wait_for(flaky_redis.failed.wait(), timeout=5)
        _card_1_wins(monkeypatch, card_pool)
        await _settled_or_engine_ended(pool, task, round_id)

        assert not task.done(), f"the room's engine ended: {task.exception()!r}"
        status = await pool.fetchval("SELECT status FROM rounds WHERE id = $1", round_id)
        assert (status, await _winners(pool, round_id)) == ("done", {user_a})
    finally:
        await engine.stop()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=15)


async def test_a_redis_error_pushing_the_winners_balance_still_ends_the_round_and_opens_the_next(
    pool, redis, card_pool, conn, monkeypatch
):
    armed = asyncio.Event()  # set once the round runs, so the joins' own balance pushes go through
    flaky_redis = _RedisPublishFailsOnce(redis, lambda channel, message: armed.is_set() and channel.startswith("user:"))
    # Active, so the engine goes on to open the next round rather than
    # stopping at the between-rounds is_active check.
    room_id, engine, task, user_a = await _start_two_player_round(
        pool, flaky_redis, pool, card_pool, conn, is_active=True
    )
    round_id = engine.round_id
    room_messages = redis.pubsub()
    await room_messages.subscribe(f"room:{room_id}")
    try:
        armed.set()
        _card_1_wins(monkeypatch, card_pool)
        await _settled_or_engine_ended(pool, task, round_id)
        await asyncio.wait_for(flaky_redis.failed.wait(), timeout=5)
        await _wait_until(lambda: task.done() or engine.round_id not in (None, round_id), timeout=10)

        assert not task.done(), f"the room's engine ended: {task.exception()!r}"
        round_end = None
        deadline = asyncio.get_running_loop().time() + 5
        while round_end is None and asyncio.get_running_loop().time() < deadline:
            message = await room_messages.get_message(ignore_subscribe_messages=True, timeout=0.2)
            payload = json.loads(message["data"]) if message is not None else {}
            if payload.get("t") == "round_end" and payload.get("round_id") == round_id:
                round_end = payload
        assert round_end is not None, "players never got round_end"
        assert [w["user_id"] for w in round_end["winners"]] == [user_a]
    finally:
        await pool.execute("UPDATE rooms SET is_active = false WHERE id = $1", room_id)
        await room_messages.aclose()
        await engine.stop()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=15)


async def test_a_failed_per_call_update_is_retried_not_fatal_to_the_round(pool, redis, card_pool, conn, monkeypatch):
    flaky_pool = _PoolFetchrowFailsOnce(pool, "UPDATE rounds SET call_index")
    room_id, engine, task, user_a = await _start_two_player_round(flaky_pool, redis, pool, card_pool, conn)
    round_id = engine.round_id
    try:
        await asyncio.wait_for(flaky_pool.failed.wait(), timeout=5)
        _card_1_wins(monkeypatch, card_pool)
        await _settled_or_engine_ended(pool, task, round_id)

        assert not task.done(), f"the room's engine ended: {task.exception()!r}"
        status = await pool.fetchval("SELECT status FROM rounds WHERE id = $1", round_id)
        assert (status, await _winners(pool, round_id)) == ("done", {user_a})
    finally:
        await engine.stop()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=15)
