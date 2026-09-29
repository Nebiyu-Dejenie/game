"""Payment references once payment_ref_seq passes 999,999 (platform audit,
2026-09-29, #34). Every our_ref was built with lpad(nextval(...)::text, 6,
'0'), and lpad cuts a longer string down to the length it's given, so a
seven-digit value lost its last digit: 1000001 through 1000009 all became
...-100000. The sequence is shared by withdrawals, Chapa deposits, manual
deposits and Telebirr redemptions, and every checkout attempt uses a value,
so past a million nine in ten of them failed on payments_our_ref_key.
On the withdrawal path, ledger.post also matched the earlier withdrawal's
idempotency key and moved nothing."""

from __future__ import annotations

from decimal import Decimal

from services.payments import deposits, manual, withdrawals
from services.payments.telebirr_redemption import redeem_evidence
from tests.integration.conftest import create_funded_user, create_user
from tests.integration.test_payments_deposits import FakePaymentProvider
from tests.integration.test_payout_worker import FakePayoutProvider
from tests.integration.test_telebirr_redemption import _make_available_evidence


async def _move_ref_sequence_past_six_digits(conn) -> None:
    """Sets the sequence so its next two values are X1 and X2 of one ten,
    seven digits long. Only ever moves it forward, so no earlier ref can be
    produced again."""
    last = await conn.fetchval("SELECT last_value FROM payment_ref_seq")
    base = (max(last, 1_000_000) // 10 + 1) * 10
    await conn.execute("SELECT setval('payment_ref_seq', $1)", base)


async def _withdraw(pool, redis, user_id: int) -> withdrawals.WithdrawalIntent:
    return await withdrawals.request_withdrawal(
        pool, redis, FakePayoutProvider(),
        user_id=user_id, amount=Decimal("100.00"), method_kind="telebirr",
        account_ref="0911223344", holder_name="Test Holder",
        min_withdraw=Decimal("10.00"), auto_approve_limit=Decimal("100000.00"),
        kyc_threshold=Decimal("100000.00"), chargeback_window_minutes=0, min_account_age_hours=0,
    )


async def test_consecutive_withdrawals_past_a_million_get_distinct_refs(pool, redis, conn):
    user_id = await create_funded_user(conn, Decimal("500.00"))
    await _move_ref_sequence_past_six_digits(conn)

    first = await _withdraw(pool, redis, user_id)
    second = await _withdraw(pool, redis, user_id)

    assert first.our_ref != second.our_ref
    assert len(first.our_ref.rsplit("-", 1)[1]) == 7
    # Each withdrawal locked its own 100, not one shared ledger transaction.
    locked = await conn.fetchval(
        "SELECT count(DISTINCT ledger_txn_id) FROM payments WHERE id = ANY($1)",
        [first.payment_id, second.payment_id],
    )
    assert locked == 2


async def test_consecutive_chapa_deposits_past_a_million_get_distinct_refs(pool, redis, conn):
    provider = FakePaymentProvider()
    await _move_ref_sequence_past_six_digits(conn)

    intents = []
    for _ in range(2):
        intents.append(
            await deposits.create_deposit_intent(
                pool, redis, provider,
                user_id=await create_user(conn), amount=Decimal("100.00"), phone_e164="+251911000000",
                return_url="https://app.test/return", callback_url="https://payments.test/webhooks/chapa",
                min_deposit=Decimal("10.00"), daily_cap=Decimal("50000.00"),
            )
        )

    assert intents[0].our_ref != intents[1].our_ref


async def test_consecutive_manual_deposits_past_a_million_get_distinct_refs(pool, redis, conn):
    destination_id = await conn.fetchval(
        "INSERT INTO manual_payment_destinations (method_kind, account_ref, account_name, instructions) "
        "VALUES ('telebirr', '0911000000', 'Zemen Game PLC', 'Send exactly the requested amount') RETURNING id"
    )
    await _move_ref_sequence_past_six_digits(conn)

    intents = []
    for n in range(2):
        intents.append(
            await manual.create_manual_deposit_request(
                pool, redis,
                user_id=await create_user(conn), amount=Decimal("100.00"),
                manual_destination_id=destination_id, external_reference=f"FT-seven-digits-{n}",
                receipt_telegram_file_id=None, min_deposit=Decimal("10.00"), daily_cap=Decimal("50000.00"),
            )
        )

    assert intents[0].our_ref != intents[1].our_ref


async def test_consecutive_telebirr_redemptions_past_a_million_get_distinct_refs(pool, redis, conn):
    references = [await _make_available_evidence(pool, conn) for _ in range(2)]
    await _move_ref_sequence_past_six_digits(conn)

    outcomes = []
    for reference in references:
        outcomes.append(
            await redeem_evidence(
                pool, redis, user_id=await create_funded_user(conn, Decimal("0.00")),
                reference=reference, daily_cap=Decimal("50000.00"),
            )
        )

    assert [o.code for o in outcomes] == ["PAYMENT_REDEEMED", "PAYMENT_REDEEMED"]
    assert outcomes[0].our_ref != outcomes[1].our_ref
