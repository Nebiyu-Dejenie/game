"""What players are told when an admin emergency-stops a Bingo room
(platform audit, 2026-09-29). The refund itself was already right; the
messages weren't. They were sent to everyone in the room's latest round
whether or not anything was refunded, so stopping a room between rounds,
or clicking Stop twice, told the players of an already-finished round
"Your stake of X ETB has been refunded" when nothing was, and broadcast
round_voided over a finished result. The amount was also the room's
per-card stake, not what each player got back."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import asyncpg
import pytest

from packages.core.notifications import NOTIFICATIONS_STREAM
from services.admin import queries
from services.engine.round_engine import RoundEngine, load_room_config
from tests.integration.conftest import create_funded_user, create_room
from tests.integration.test_admin_auth import create_test_admin

pytestmark = pytest.mark.asyncio


async def _stop(pool, redis, room_id: int) -> dict:
    admin_id, *_ = await create_test_admin(pool)
    return await queries.stop_room_admin(
        pool, redis, admin_id=admin_id, room_id=room_id, reason="emergency stop for a test",
        confirmation="STOP", ip_address=None,
    )


async def _stop_messages_since(redis, conn: asyncpg.Connection, since_id: str, user_ids: list[int]) -> dict[int, list[dict]]:
    tg_to_user = {
        r["telegram_id"]: r["id"]
        for r in await conn.fetch("SELECT id, telegram_id FROM users WHERE id = ANY($1)", user_ids)
    }
    out: dict[int, list[dict]] = {u: [] for u in user_ids}
    for _, fields in await redis.xrange(NOTIFICATIONS_STREAM, min=f"({since_id}"):
        if fields["key"] != "notify.room_emergency_stopped":
            continue
        user_id = tg_to_user.get(int(fields["telegram_id"]))
        if user_id is not None:
            out[user_id].append(json.loads(fields["kwargs"]))
    return out


async def _stream_tip(redis) -> str:
    last = await redis.xrevrange(NOTIFICATIONS_STREAM, count=1)
    return last[0][0] if last else "0-0"


async def test_stopping_a_room_whose_last_round_finished_tells_nobody_they_were_refunded(pool, redis, conn):
    room_id = await create_room(conn, stake=Decimal("20.00"))
    round_id = await conn.fetchval(
        "INSERT INTO rounds (room_id, seq, status, stake, house_cut_bps, server_seed_hash) "
        "VALUES ($1, 1, 'done', 20.00, 2000, 'test-hash') RETURNING id",
        room_id,
    )
    a = await create_funded_user(conn, Decimal("0"))
    b = await create_funded_user(conn, Decimal("0"))
    await conn.execute(
        "INSERT INTO round_entries (round_id, card_no, user_id) VALUES ($1, 1, $2), ($1, 2, $3)", round_id, a, b
    )
    tip = await _stream_tip(redis)
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"room:{room_id}")

    result = await _stop(pool, redis, room_id)
    await asyncio.sleep(0.3)
    broadcasts = []
    while (m := await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)) is not None:
        broadcasts.append(json.loads(m["data"]))
    await pubsub.aclose()

    assert result["refunded_entrants"] == 0
    assert await _stop_messages_since(redis, conn, tip, [a, b]) == {a: [], b: []}
    assert not any(msg.get("t") == "round_voided" for msg in broadcasts)


async def test_each_player_is_told_what_they_actually_got_back_and_only_once(pool, redis, conn, card_pool):
    room = await load_room_config(
        pool, await create_room(conn, stake=Decimal("20.00"), min_players=3, max_cards_per_player=4, lobby_seconds=60)
    )
    two_cards = await create_funded_user(conn, Decimal("100.00"))
    one_card = await create_funded_user(conn, Decimal("100.00"))
    engine = RoundEngine(pool, redis, room, card_pool)
    task = asyncio.create_task(engine.run_forever())
    try:
        assert (await engine.join(two_cards, 1)).ok
        assert (await engine.join(two_cards, 2)).ok
        assert (await engine.join(one_card, 3)).ok
        tip = await _stream_tip(redis)

        first = await _stop(pool, redis, room.id)
        second = await _stop(pool, redis, room.id)  # a double click
    finally:
        await engine.stop()
        await asyncio.wait_for(task, timeout=15)

    assert (first["refunded_entrants"], second["refunded_entrants"]) == (3, 0)
    messages = await _stop_messages_since(redis, conn, tip, [two_cards, one_card])
    assert [m["amount"] for m in messages[two_cards]] == ["40.00"]
    assert [m["amount"] for m in messages[one_card]] == ["20.00"]
