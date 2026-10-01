"""The daily deposit cap under concurrent requests (platform audit #69,
#73). _check_deposit_eligibility summed today's deposits and the caller
inserted the new one afterwards, with nothing serializing a player's
requests in between (for Chapa, not even a transaction). Several deposits
started at once each saw the same total, all passed, and together went
past the player's responsible-gaming cap or the platform's
daily_deposit_cap_etb. The sleep after the check widens the window that
slow traffic opens in production."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from services.payments import deposits
from tests.integration.conftest import create_user
from tests.integration.test_payments_deposits import FakePaymentProvider


async def test_concurrent_deposits_cannot_together_exceed_the_daily_cap(pool, redis, conn, monkeypatch):
    real_check = deposits._check_deposit_eligibility

    async def slow_check(*args, **kwargs):
        await real_check(*args, **kwargs)
        await asyncio.sleep(0.2)

    monkeypatch.setattr(deposits, "_check_deposit_eligibility", slow_check)
    user_id = await create_user(conn)

    async def deposit() -> bool:
        try:
            await deposits.create_deposit_intent(
                pool, redis, FakePaymentProvider(),
                user_id=user_id, amount=Decimal("200.00"), phone_e164="+251911000000",
                return_url="https://app.test/return", callback_url="https://payments.test/webhooks/chapa",
                min_deposit=Decimal("10.00"), daily_cap=Decimal("500.00"),
            )
            return True
        except deposits.DailyDepositCapExceeded:
            return False

    results = await asyncio.gather(*(deposit() for _ in range(5)))

    spoken_for = await conn.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE user_id = $1 AND direction = 'in' "
        "AND status IN ('pending', 'processing', 'review', 'approved', 'succeeded')",
        user_id,
    )
    assert (results.count(True), spoken_for) == (2, Decimal("400.00"))
