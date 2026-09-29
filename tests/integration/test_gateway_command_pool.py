"""Engine commands and the gateway's Redis connection pool (platform audit,
2026-09-29). Every take_card, drop_card, set_auto and claim opened its own
pub/sub subscription for the reply, and so held one of the gateway's 200
pooled Redis connections until the engine answered or 5s passed. A room
with no live engine (a worker crash or restart) answers nothing, so about
200 players tapping take_card there within 5s emptied the pool. The rate
limiter shares that pool and fails closed, so from then on every player
on the gateway got "Slow down." for every frame, whatever room they were
in, and further commands tore their sockets down."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
import websockets

from packages.core.redis_conn import MAX_CONNECTIONS
from tests.integration.conftest import build_init_data, create_room, next_telegram_id
from tests.integration.test_gateway_gameplay import wait_until

pytestmark = pytest.mark.asyncio


async def _connect(gateway_server: str):
    ws = await websockets.connect(gateway_server, open_timeout=30)
    await ws.send(json.dumps({"t": "auth", "init_data": build_init_data(next_telegram_id())}))
    assert json.loads(await asyncio.wait_for(ws.recv(), timeout=30))["t"] == "authed"
    return ws


async def _ping(ws) -> str:
    await ws.send(json.dumps({"t": "ping", "ts": 1}))
    reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    return reply.get("code") or reply["t"]


async def test_commands_waiting_on_an_ownerless_room_do_not_lock_out_other_players(gateway_server, conn):
    from services.gateway.app import app as gateway_app

    connections_before = len(gateway_app.state.connections)
    ownerless_room = await create_room(conn, stake=Decimal("10.00"))
    waiting: list = []
    bystanders: list = []
    try:
        for _ in range((MAX_CONNECTIONS + 10) // 30 + 1):
            waiting += await asyncio.gather(*(_connect(gateway_server) for _ in range(30)))
        bystanders = await asyncio.gather(*(_connect(gateway_server) for _ in range(20)))

        # A steady ramp, as players arriving over a couple of seconds would
        # be, rather than one burst.
        for i in range(0, len(waiting), 10):
            await asyncio.gather(
                *(
                    ws.send(json.dumps({"t": "take_card", "room_id": ownerless_room, "card_no": 1}))
                    for ws in waiting[i : i + 10]
                )
            )
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.3)  # every take_card is now waiting for a reply that never comes

        # Players elsewhere on the gateway, doing nothing but ping.
        replies = await asyncio.gather(*(_ping(ws) for ws in bystanders))
        assert replies.count("pong") == len(bystanders), replies
        torn_down = sum(ws.close_code is not None for ws in waiting)
        assert torn_down == 0, f"{torn_down} of {len(waiting)} waiting players were disconnected"
    finally:
        await asyncio.gather(*(ws.close() for ws in waiting + bystanders), return_exceptions=True)
        # Each waiting handler only notices its socket closed once its
        # command times out; let them finish before the next test.
        await wait_until(lambda: len(gateway_app.state.connections) <= connections_before, timeout=20)
