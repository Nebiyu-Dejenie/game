"""The Keno result screen tells the truth about money: a payout smaller
than the stake is shown as money returned, not celebrated as a win; only a
real profit gets the win treatment. Also: the operator's default stake is
the chip the player starts on.

Deterministic on purpose: no round engine runs. The test seeds an open
round, places a real ticket through the UI (a real debit), then publishes
the settlement frame the engine would send to that player's channel, with
a chosen payout -- the one thing a real random draw can't pin down."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from packages.core import keno, keno_tickets
from tests.integration.conftest import create_funded_user, next_telegram_id
from tests.integration.test_keno_miniapp_e2e import _clean_keno_lock_and_rounds, _seed_fast_config_and_tier  # noqa: F401
from tests.integration.test_miniapp_e2e import prepare_page

pytestmark = pytest.mark.e2e


async def _open_round_and_player(pool, conn, browser, *, default_stake: str | None = None):
    await _seed_fast_config_and_tier(conn)
    current = await conn.fetchrow(
        "SELECT t.id FROM keno_tier_state s JOIN keno_risk_tiers t ON t.id = s.current_tier_id WHERE s.id = 1"
    )
    if default_stake is not None:
        await conn.execute("UPDATE keno_risk_tiers SET default_stake = $2 WHERE id = $1", current["id"], Decimal(default_stake))
    config_id = await conn.fetchval(
        "SELECT id FROM keno_configs WHERE effective_from <= now() ORDER BY effective_from DESC LIMIT 1"
    )
    round_id = await conn.fetchval(
        """
        INSERT INTO keno_rounds (seq, status, config_id, tier_id, server_seed_hash, betting_opened_at)
        VALUES ((SELECT COALESCE(MAX(seq), 0) + 1 FROM keno_rounds), 'betting_open', $1, $2, $3, now())
        RETURNING id
        """,
        config_id, current["id"], keno.server_seed_hash(keno.generate_server_seed()),
    )
    telegram_id = next_telegram_id()
    page, errors = await prepare_page(browser, telegram_id, first_name="ResultPlayer")
    async with pool.acquire() as setup:
        user_id = await create_funded_user(setup, Decimal("1000.00"))
    await pool.execute("UPDATE users SET telegram_id = $1 WHERE id = $2", telegram_id, user_id)
    return page, errors, user_id, round_id


async def _enter_keno(page, gateway_server) -> None:
    http_base = gateway_server.replace("ws://", "http://").replace("/ws", "")
    await page.goto(http_base + "/")
    await page.wait_for_selector("#screen-rooms.active", timeout=10000)
    await page.click("#open-keno-btn")
    await page.wait_for_selector("#screen-keno.active", timeout=10000)
    await page.click("#keno-onboard-skip-btn")
    await page.wait_for_selector(".keno-cell:not(.locked)", timeout=10000)


async def _bet_and_settle(page, pool, redis, user_id, round_id, *, stake: str, payout: str, matches: int) -> None:
    await page.click('.keno-cell[aria-label="7"]')
    await page.click(f'#keno-stake-chips .amount-chip:has-text("{stake}")')
    await page.wait_for_function("!document.getElementById('keno-play-btn').disabled", timeout=5000)
    await page.click("#keno-play-btn")
    await page.wait_for_function(
        "!document.getElementById('keno-my-tickets-section').classList.contains('hidden')", timeout=10000
    )
    ticket_id = await pool.fetchval(
        "SELECT id FROM keno_tickets WHERE user_id = $1 AND round_id = $2", user_id, round_id
    )
    assert ticket_id is not None  # a real ticket, really debited
    await redis.publish(
        f"user:{user_id}",
        json.dumps({
            "t": "keno.ticket.settled", "round_id": round_id, "ticket_id": ticket_id, "matches": matches,
            "payout": payout, "jackpot_payout": None, "stake": stake,
        }),
    )
    await page.wait_for_selector("#screen-keno-result.active", timeout=10000)


async def test_a_payout_below_the_stake_is_not_celebrated(gateway_server, pool, redis, browser, conn):
    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        await _bet_and_settle(page, pool, redis, user_id, round_id, stake="50.00", payout="20.00", matches=1)

        title = await page.text_content("#keno-result-title")
        amount = await page.text_content("#keno-result-amount")
        meta = await page.text_content("#keno-result-meta")
        assert "won" not in title.lower() and "ገበያ" not in title
        assert "20.00" in amount
        assert "+" not in amount
        assert "−30.00" in meta  # net this round, shown honestly
        assert not await page.locator("#keno-result-title.win").count()
        assert await page.locator("#keno-result-confetti > *").count() == 0
        assert errors == [], errors
    finally:
        await page.close()


async def test_a_real_profit_is_celebrated(gateway_server, pool, redis, browser, conn):
    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        await _bet_and_settle(page, pool, redis, user_id, round_id, stake="10.00", payout="34.00", matches=1)

        assert await page.locator("#keno-result-title.win").count() == 1
        assert "34.00" in await page.text_content("#keno-result-amount")
        assert "+24.00" in await page.text_content("#keno-result-meta")
        assert await page.locator("#keno-result-confetti > *").count() > 0
        assert errors == [], errors
    finally:
        await page.close()


async def test_the_operator_default_stake_is_preselected(gateway_server, pool, redis, browser, conn):
    page, errors, _, _ = await _open_round_and_player(pool, conn, browser, default_stake="20.00")
    try:
        await _enter_keno(page, gateway_server)
        selected = page.locator("#keno-stake-chips .amount-chip.selected")
        await selected.wait_for()
        assert (await selected.text_content()).startswith("20.00")
        assert errors == [], errors
    finally:
        await page.close()


async def _bet(page, pool, user_id, round_id, *, stake: str) -> int:
    await page.click('.keno-cell[aria-label="7"]')
    await page.click(f'#keno-stake-chips .amount-chip:has-text("{stake}")')
    await page.wait_for_function("!document.getElementById('keno-play-btn').disabled", timeout=5000)
    await page.click("#keno-play-btn")
    await page.wait_for_function(
        "!document.getElementById('keno-my-tickets-section').classList.contains('hidden')", timeout=10000
    )
    ticket_id = await pool.fetchval("SELECT id FROM keno_tickets WHERE user_id = $1 AND round_id = $2", user_id, round_id)
    assert ticket_id is not None
    return ticket_id


async def test_a_refunded_round_says_so_instead_of_showing_a_loss(gateway_server, pool, redis, browser, conn):
    """A round that failed before its draw refunds the stake. The player used
    to see nothing until a later round, and history called it "lost"."""
    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        ticket_id = await _bet(page, pool, user_id, round_id, stake="10.00")
        await redis.publish(
            f"user:{user_id}",
            json.dumps({"t": "keno.ticket.refunded", "round_id": round_id, "ticket_id": ticket_id, "stake": "10.00"}),
        )
        await page.wait_for_selector("#screen-keno-result.active", timeout=10000)

        locales = Path(__file__).resolve().parents[2] / "web/miniapp/locales"
        titles = {json.loads((locales / f"{lang}.json").read_text())["keno.result.refunded_title"] for lang in ("en", "am")}
        assert await page.text_content("#keno-result-title") in titles
        assert "10.00" in await page.text_content("#keno-result-amount")
        assert not await page.locator("#keno-result-title.win").count()
        assert await page.locator("#keno-result-confetti > *").count() == 0
        assert await page.locator("#keno-result-verify-btn.hidden").count() == 1
        assert errors == [], errors
    finally:
        await page.close()


async def test_a_keno_result_does_not_take_over_a_screen_outside_keno(gateway_server, pool, redis, browser, conn):
    """A player who places a ticket and goes back to the Bingo rooms stays
    there when the Keno round settles; the result used to take over the
    screen, including a live Bingo game."""
    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        ticket_id = await _bet(page, pool, user_id, round_id, stake="10.00")
        await page.evaluate("window.__triggerBackButton()")
        await page.wait_for_selector("#screen-rooms.active", timeout=5000)

        await redis.publish(
            f"user:{user_id}",
            json.dumps({
                "t": "keno.ticket.settled", "round_id": round_id, "ticket_id": ticket_id, "matches": 1,
                "payout": "34.00", "jackpot_payout": None, "stake": "10.00",
            }),
        )
        # Give the frame time to arrive and be handled.
        await page.wait_for_timeout(1500)
        assert await page.locator("#screen-rooms.active").count() == 1
        assert await page.locator("#screen-keno-result.active").count() == 0
        assert errors == [], errors
    finally:
        await page.close()


async def test_the_payout_preview_is_capped_at_the_max_win_per_ticket(gateway_server, pool, redis, browser, conn):
    """Settlement caps a ticket's payout at the tier's max win; the preview
    used to show the uncapped figure."""
    page, errors, _, _ = await _open_round_and_player(pool, conn, browser)
    try:
        await conn.execute(
            "UPDATE keno_risk_tiers SET max_win_per_ticket = 25.00 "
            "WHERE id = (SELECT current_tier_id FROM keno_tier_state WHERE id = 1)"
        )
        await _enter_keno(page, gateway_server)
        await page.click('.keno-cell[aria-label="7"]')
        await page.click('#keno-stake-chips .amount-chip:has-text("50.00")')
        await page.wait_for_function("!document.getElementById('keno-play-btn').disabled", timeout=5000)
        assert (await page.text_content("#keno-payout-amount")).strip() == "25.00 ETB"
        assert errors == [], errors
    finally:
        await page.close()


async def test_a_settlement_missed_while_away_is_picked_up_on_return(gateway_server, pool, redis, browser, conn):
    """Events sent while the app was in the background or the socket was
    down are lost. The ticket used to stay "pending" forever; coming back
    now re-reads it."""
    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        ticket_id = await _bet(page, pool, user_id, round_id, stake="10.00")
        # Settled with no event reaching this client.
        await pool.execute(
            "UPDATE keno_tickets SET status = 'won', payout = 34.00, matches = 1, settled_at = now() WHERE id = $1",
            ticket_id,
        )
        await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        await page.wait_for_selector("#screen-keno-result.active", timeout=10000)
        assert "34.00" in await page.text_content("#keno-result-amount")
        assert errors == [], errors
    finally:
        await page.close()


async def test_a_reload_keeps_the_rounds_tickets(gateway_server, pool, redis, browser, conn):
    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        await _bet(page, pool, user_id, round_id, stake="10.00")
        await page.reload()
        await page.wait_for_selector("#screen-rooms.active", timeout=10000)
        await page.click("#open-keno-btn")
        await page.wait_for_selector("#screen-keno.active", timeout=10000)
        await page.wait_for_function(
            "!document.getElementById('keno-my-tickets-section').classList.contains('hidden')", timeout=10000
        )
        assert await page.locator("#keno-my-tickets-list .keno-ticket-row").count() == 1
        assert errors == [], errors
    finally:
        await page.close()


async def test_an_autoplay_rounds_result_shows_without_leaving_the_board(gateway_server, pool, redis, browser, conn):
    """Autoplay's tickets are placed server-side, so the client never knew
    about them and showed nothing per round."""
    from packages.core import keno_autoplay

    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        session = await keno_autoplay.start_session(
            pool, user_id=user_id, picks=[7], stake=Decimal("10"), rounds_total=3
        )
        ticket = await keno_tickets.place_ticket(
            pool, redis, user_id=user_id, picks=[7], stake=Decimal("10"),
            idempotency_key=f"autoplay:{session.id}:{round_id}", autoplay_session_id=session.id,
        )
        await redis.publish("keno:live", json.dumps({"t": "keno.betting.closed", "round_id": round_id}))
        await page.wait_for_function(
            "!document.getElementById('keno-my-tickets-section').classList.contains('hidden')", timeout=10000
        )
        await redis.publish(
            f"user:{user_id}",
            json.dumps({
                "t": "keno.ticket.settled", "round_id": round_id, "ticket_id": ticket.id, "matches": 1,
                "payout": "34.00", "jackpot_payout": None, "stake": "10.00",
            }),
        )
        await page.wait_for_function(
            "document.getElementById('keno-play-status').textContent.includes('34.00')", timeout=10000
        )
        assert await page.locator("#screen-keno.active").count() == 1
        assert errors == [], errors
    finally:
        await keno_autoplay.stop_session(pool, user_id=user_id)
        await page.close()


async def test_the_keno_screen_shows_the_balance_and_follows_a_stake(gateway_server, pool, redis, browser, conn):
    page, errors, user_id, round_id = await _open_round_and_player(pool, conn, browser)
    try:
        await _enter_keno(page, gateway_server)
        await page.wait_for_function(
            "document.getElementById('keno-balance-amount').textContent === '1000.00 ETB'", timeout=10000
        )
        await _bet(page, pool, user_id, round_id, stake="10.00")
        await page.wait_for_function(
            "document.getElementById('keno-balance-amount').textContent === '990.00 ETB'", timeout=10000
        )
        assert errors == [], errors
    finally:
        await page.close()


async def test_the_keno_button_follows_the_switch_without_a_restart(gateway_server, pool, redis, browser, conn):
    """Availability was checked once at boot: a player with the app open
    when Keno was switched on never saw the button, and one with it open
    when Keno was switched off kept a button into an empty board."""
    page, errors, _, _ = await _open_round_and_player(pool, conn, browser)
    config_id = await conn.fetchval(
        "SELECT id FROM keno_configs WHERE effective_from <= now() ORDER BY effective_from DESC LIMIT 1"
    )
    try:
        await conn.execute("UPDATE keno_configs SET keno_enabled = false WHERE id = $1", config_id)
        http_base = gateway_server.replace("ws://", "http://").replace("/ws", "")
        await page.goto(http_base + "/")
        await page.wait_for_selector("#screen-rooms.active", timeout=10000)
        await page.wait_for_timeout(1000)
        assert await page.locator("#open-keno-btn.hidden").count() == 1

        await conn.execute("UPDATE keno_configs SET keno_enabled = true WHERE id = $1", config_id)
        await page.click("#open-wallet-btn")
        await page.wait_for_selector("#screen-wallet.active", timeout=5000)
        await page.click("#wallet-back-btn")
        await page.wait_for_selector("#screen-rooms.active", timeout=5000)
        await page.wait_for_selector("#open-keno-btn:not(.hidden)", timeout=5000)

        await conn.execute("UPDATE keno_configs SET keno_enabled = false WHERE id = $1", config_id)
        await page.click("#open-wallet-btn")
        await page.wait_for_selector("#screen-wallet.active", timeout=5000)
        await page.click("#wallet-back-btn")
        await page.wait_for_selector("#open-keno-btn.hidden", state="attached", timeout=5000)
        assert errors == [], errors
    finally:
        await conn.execute("UPDATE keno_configs SET keno_enabled = true WHERE id = $1", config_id)
        await page.close()
