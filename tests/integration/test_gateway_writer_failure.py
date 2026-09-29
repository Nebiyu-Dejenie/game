"""What happens to a player's socket when the gateway task that writes to
it dies (platform audit, 2026-09-29). Nothing noticed: the reader kept
answering pings, so the client never reconnected, but no call, round
result or balance update ever reached it again. When the socket finally
closed, _cleanup re-raised the writer's exception before it unsubscribed
anything, so the connection's mailbox stayed in the fan-out hub for the
life of the process. Reproduced here by failing the writer's state_sync
read, which is what a DB error or a pool-acquire timeout looks like."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
import websockets

from packages.core import metrics
from services.gateway import queries
from tests.integration.conftest import build_init_data, create_room, next_telegram_id
from tests.integration.test_gateway_gameplay import wait_until

pytestmark = pytest.mark.asyncio


async def _connect_and_join(gateway_server: str, room_id: int):
    from services.gateway.app import app as gateway_app

    ws = await websockets.connect(gateway_server)
    await ws.send(json.dumps({"t": "auth", "init_data": build_init_data(next_telegram_id())}))
    user_id = json.loads(await ws.recv())["user"]["id"]
    await ws.send(json.dumps({"t": "join", "room_id": room_id}))
    assert json.loads(await ws.recv())["t"] == "state_sync"
    handler = next(h for h in gateway_app.state.connections if h._user_id == user_id)
    return ws, handler


def _kill_the_writer(monkeypatch, handler) -> None:
    """The next state_sync the writer builds raises, as it would if the
    database were down."""

    async def _failing_build_state_sync(*_args, **_kwargs):
        raise ConnectionError("simulated database outage")

    monkeypatch.setattr(queries, "build_state_sync", _failing_build_state_sync)
    handler._cq.request_state_sync()


async def _close_code(ws, *, within: float) -> int | None:
    try:
        async with asyncio.timeout(within):
            while True:
                await ws.recv()
    except websockets.ConnectionClosed as exc:
        return exc.rcvd.code if exc.rcvd is not None else None
    except TimeoutError:
        return None


async def test_a_dead_writer_closes_the_socket_so_the_client_reconnects(gateway_server, conn, monkeypatch):
    room_id = await create_room(conn, stake=Decimal("10.00"))
    ws, handler = await _connect_and_join(gateway_server, room_id)
    try:
        _kill_the_writer(monkeypatch, handler)
        assert await _close_code(ws, within=3) == 1011
    finally:
        await ws.close()


async def test_a_socket_whose_writer_died_is_still_unsubscribed_when_it_closes(
    gateway_server, conn, monkeypatch
):
    from services.gateway.app import app as gateway_app

    hub = gateway_app.state.hub
    room_id = await create_room(conn, stake=Decimal("10.00"))
    open_before = metrics.gateway_connections._value.get()
    ws, handler = await _connect_and_join(gateway_server, room_id)
    cq, user_id = handler._cq, handler._user_id
    _kill_the_writer(monkeypatch, handler)
    await wait_until(lambda: handler._writer_task is None or handler._writer_task.done(), timeout=3)

    await ws.close()
    await wait_until(lambda: handler not in gateway_app.state.connections, timeout=5)

    assert cq not in hub._room_subscribers.get(room_id, ())
    assert cq not in hub._user_subscribers.get(user_id, ())
    assert cq not in hub._keno_subscribers
    assert metrics.gateway_connections._value.get() == open_before
