"""Engine commands for rooms that don't exist (platform audit, 2026-09-29,
#16). The gateway only checked that room_id was an integer. send_command
XADDs to room:{room_id}:cmds, which creates that stream, and no engine ever
reads, trims or expires a stream for a room it doesn't own. A player
sending set_auto or drop_card with a new made-up room_id each time created
one permanent Redis key per frame, and held a pooled Redis connection for
the 5 s reply timeout each time. Redis has no maxmemory in production and
holds the room locks, Keno state, rate limits and payout queue."""

from __future__ import annotations

import asyncio
import json
import random

import pytest
import websockets

from services.engine.commands import stream_key
from tests.integration.conftest import build_init_data, next_telegram_id

pytestmark = pytest.mark.asyncio


async def test_a_command_for_a_room_that_does_not_exist_is_refused_and_leaves_no_stream(gateway_server, redis, conn):
    made_up = [random.randint(10**8, 10**9) for _ in range(3)]
    assert await conn.fetchval("SELECT count(*) FROM rooms WHERE id = ANY($1)", made_up) == 0

    async with websockets.connect(gateway_server, open_timeout=30) as ws:
        await ws.send(json.dumps({"t": "auth", "init_data": build_init_data(next_telegram_id())}))
        assert json.loads(await asyncio.wait_for(ws.recv(), timeout=30))["t"] == "authed"

        replies = []
        for frame in (
            {"t": "set_auto", "room_id": made_up[0], "auto": False},
            {"t": "drop_card", "room_id": made_up[1], "card_no": 1},
            {"t": "take_card", "room_id": made_up[2], "card_no": 1},
        ):
            await ws.send(json.dumps(frame))
            replies.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=10)))

    assert [r.get("code") for r in replies] == ["bad_room_id"] * 3, replies
    assert [await redis.exists(stream_key(room_id)) for room_id in made_up] == [0, 0, 0]
