"""The deposit polling fallback when Chapa can't answer for one deposit
(platform audit, 2026-09-29, #29 and #30). poll_pending_deposits called
fetch_status for every 'processing' Chapa deposit in one unguarded loop.
ChapaProvider.fetch_status raises for a non-'success' envelope, a status
outside its map (such as 'reversed'), a non-JSON body or a malformed
amount, and the first such raise ended the pass. Nothing ever moves that
row out of 'processing', so every 30-second pass stopped at it again, and
every deposit after it whose webhook was lost stayed uncredited."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from packages.core import ledger
from services.payments import deposits
from services.payments.provider import StatusResult
from tests.integration.conftest import create_user
from tests.integration.test_payments_deposits import FakePaymentProvider


@dataclass
class _ChapaAnswersOnlyFor(FakePaymentProvider):
    """Raises for every deposit except the ones it has a status for, the
    way ChapaProvider._map_status raises for a status it doesn't know."""

    async def fetch_status(self, our_ref):
        if our_ref not in self.statuses:
            raise ValueError("unrecognized chapa status: 'reversed'")
        return self.statuses[our_ref]


async def _processing_deposit(pool, redis, conn, provider) -> tuple[int, str]:
    user_id = await create_user(conn)
    intent = await deposits.create_deposit_intent(
        pool, redis, provider,
        user_id=user_id, amount=Decimal("100.00"), phone_e164="+251911000000",
        return_url="https://app.test/return", callback_url="https://payments.test/webhooks/chapa",
        min_deposit=Decimal("10.00"), daily_cap=Decimal("50000.00"),
    )
    return user_id, intent.our_ref


async def _cash(conn, user_id: int) -> Decimal:
    account = await ledger.get_or_create_account(conn, user_id, "user_cash")
    return await ledger.balance(conn, account.id)


async def test_one_deposit_chapa_cannot_answer_for_does_not_stop_the_others_being_credited(pool, redis, conn):
    provider = _ChapaAnswersOnlyFor()
    _, unanswerable_ref = await _processing_deposit(pool, redis, conn, provider)
    paid_user, paid_ref = await _processing_deposit(pool, redis, conn, provider)
    provider.statuses[paid_ref] = StatusResult(
        status="succeeded", amount=Decimal("100.00"), provider_ref=f"AP-{paid_ref}", raw={}
    )

    credited = await deposits.poll_pending_deposits(pool, redis, provider, older_than_seconds=0)

    assert credited >= 1
    assert await _cash(conn, paid_user) == Decimal("100.00")
    assert await conn.fetchval("SELECT status FROM payments WHERE our_ref = $1", paid_ref) == "succeeded"
    assert await conn.fetchval("SELECT status FROM payments WHERE our_ref = $1", unanswerable_ref) == "processing"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Policy, not fixed here: when an unpaid Chapa checkout stops being polled and stops "
        "counting toward the daily deposit cap needs a checkout lifetime and a terminal status "
        "chosen for it, and a decision on crediting a payment that arrives after that."
    ),
)
async def test_a_month_old_checkout_chapa_never_heard_of_is_no_longer_polled(pool, redis, conn):
    provider = FakePaymentProvider()
    _, our_ref = await _processing_deposit(pool, redis, conn, provider)
    await conn.execute(
        "UPDATE payments SET created_at = now() - interval '30 days', updated_at = now() - interval '30 days' "
        "WHERE our_ref = $1",
        our_ref,
    )
    polled: list[str] = []
    real_fetch_status = provider.fetch_status

    async def recording_fetch_status(ref):
        polled.append(ref)
        return await real_fetch_status(ref)  # Chapa's 404: 'pending', no amount

    provider.fetch_status = recording_fetch_status

    await deposits.poll_pending_deposits(pool, redis, provider, older_than_seconds=0)
    await deposits.poll_pending_deposits(pool, redis, provider, older_than_seconds=0)

    assert polled.count(our_ref) <= 1
    assert await conn.fetchval("SELECT status FROM payments WHERE our_ref = $1", our_ref) != "processing"
