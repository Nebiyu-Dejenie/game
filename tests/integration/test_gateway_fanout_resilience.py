"""The gateway's one Redis subscription (FanoutHub) carries every Bingo
call, round result, balance update and Keno event to connected players.
It used to end for good the first time Redis closed its connection, and
nothing restarted or reported it (platform audit, 2026-09-29). Reproduced
here against a real Redis with CLIENT KILL TYPE pubsub, which is what a
Redis restart, a timeout or a network blip looks like to the gateway."""

from __future__ import annotations

import asyncio

import pytest

from services.gateway.fanout import ConnectionQueue, FanoutHub

pytestmark = pytest.mark.asyncio


async def _delivered(redis, cq: ConnectionQueue, channel: str, text: str, *, within: float) -> bool:
    """Publishes `text` repeatedly until it arrives (the resubscribe is
    asynchronous) or `within` seconds pass."""
    deadline = asyncio.get_running_loop().time() + within
    while asyncio.get_running_loop().time() < deadline:
        await redis.publish(channel, text)
        await asyncio.sleep(0.2)
        while cq.qsize():
            if await cq.get_or_wake() == text:
                return True
    return False


async def test_the_fanout_survives_redis_dropping_its_subscription(redis) -> None:
    hub = FanoutHub(redis)
    await hub.start()
    room_cq, keno_cq = ConnectionQueue(), ConnectionQueue()
    hub.subscribe_room(424242, room_cq)
    hub.subscribe_keno(keno_cq)
    try:
        assert await _delivered(redis, keno_cq, "keno:live", "before", within=5)

        killed = await redis.execute_command("CLIENT", "KILL", "TYPE", "pubsub")
        assert killed >= 1

        assert await _delivered(redis, keno_cq, "keno:live", "after-keno", within=15), "keno events stopped"
        assert await _delivered(redis, room_cq, "room:424242", "after-room", within=5), "room events stopped"
        # Whatever was published during the gap is gone; every connection
        # is asked to re-sync instead of carrying on with a stale board.
        assert room_cq.needs_state_sync and keno_cq.needs_state_sync
    finally:
        await hub.stop()
