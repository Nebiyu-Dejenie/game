"""Payout worker (spec section 8.3 steps 5-8, Prompt 8): consumes the
'payouts' Redis Stream with a real consumer group so more than one worker
replica can safely share the queue, and so a crashed worker's in-flight job
gets redelivered rather than lost -- to *any* live consumer, not only a
replacement process that happens to reuse the exact same consumer name
(XAUTOCLAIM in process_next()/run_forever() reclaims a stale entry from
whichever consumer originally owned it once it's been idle too long; a
real gap a code review pass caught, since the original crash-recovery
check only ever looked at the *current* consumer's own pending list).

A payout is sent to the provider at most once (operator decision,
2026-09-26). Only an 'approved' payment is ever dispatched. One that is
already 'processing' when its stream entry arrives (a crash after the
provider call, a duplicate enqueue) is never sent again: whether the first
send reached Chapa is unknown, and this code no longer relies on Chapa
deduplicating a repeated our_ref. It used to, and if Chapa instead rejected
the repeat, the worker refunded a transfer that had already gone out. The
same rule covers any exception from create_payout(), a timeout included:
the outcome is unknown, so the payment stays 'processing' with no refund,
and an admin resolves it from the reconciliation view
(services/admin/queries.py list_payouts_awaiting_reconciliation /
resolve_payout_admin). Locked funds an admin can resolve beat paying twice.
Settlement itself goes through services/payments/payout_settlement.py,
shared with those admin actions, so the worker and an admin can never both
resolve one payout.

A provider result of "processing" (Chapa merely *accepted* the transfer
request, with no confirmation it actually completed) is deliberately never
treated as settled -- see process_one()'s own comment on that branch. This
codebase has no payout webhook route and no status-polling fallback for
outbound transfers (unlike services/payments/deposits.py's own
poll_pending_deposits() for inbound ones), so there is currently no way to
learn a "processing" transfer later actually failed; wrongly marking it
succeeded here would be a silent, permanent, unrecoverable loss with no
signal anywhere. A payment left at status='processing' is a real,
currently-unresolved gap in this module's coverage, not a bug being
papered over -- see the admin reconciliation view above for the
operator-visibility this converts it into, and DECISIONS.md for why a full
automated fix remains blocked on Chapa's transfer-status response
vocabulary rather than guessed at.
"""

from __future__ import annotations

import asyncio
import json
import signal
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import asyncpg
import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from packages.core import ledger, metrics, tracing
from packages.core.config import get_settings
from packages.core.db_pool import create_pool
from packages.core.logging import configure_logging
from packages.core.notifications import notify_user
from packages.core.redis_conn import get_redis
from services.payments.bonus_sweep import sweep_bonus_wagering
from services.payments.chapa import ChapaProvider
from services.payments.deposits import poll_pending_deposits, run_provider_reconciliation
from services.payments.device_registry import check_for_degraded_devices
from services.payments.ledger_reconcile_sweep import sweep_ledger_reconciliation
from services.payments.payout_settlement import mark_payout_failed, mark_payout_paid
from services.payments.telebirr_reconcile import run_telebirr_reconciliation
from services.payments.provider import PaymentProvider
from services.payments.withdrawals import PAYOUT_STREAM, sweep_stuck_approved_payouts

logger = structlog.get_logger()
_tracer = tracing.get_tracer(__name__)

GROUP = "payout-workers"
_PENDING_STATUSES = ("approved", "processing")
# How long a stream entry can sit unacked in another consumer's PEL before
# XAUTOCLAIM will steal it -- long enough that a normal in-flight job (a
# real Chapa call, httpx timeout=15.0 elsewhere in this module) is never
# prematurely reclaimed out from under a consumer that's still actually
# working on it; matches this codebase's other "how long before we
# consider something possibly crashed" thresholds (services/payments/
# deposits.py's poll_pending_deposits(), withdrawals.py's
# sweep_stuck_approved_payouts(), both default to a similar order of
# magnitude).
CLAIM_STALE_AFTER_MS = 60_000


async def ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(PAYOUT_STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def process_one(
    pool: asyncpg.Pool, redis: Redis, provider: PaymentProvider, *, msg_id: str, our_ref: str
) -> str:
    """Returns 'succeeded' | 'failed' | 'processing' | 'awaiting_reconciliation'
    | 'skipped'. Always
    acks -- the only way a job is left unacked (and therefore
    redelivered) is this process dying mid-call, which is exactly the
    crash-recovery case the spec asks to be tested.
    """
    with _tracer.start_as_current_span(
        "payout.dispatch", attributes={"our_ref": our_ref}
    ) as span:
        async with pool.acquire() as conn:
            async with conn.transaction():
                payment = await conn.fetchrow(
                    "SELECT id, user_id, amount, method_id, status, provider FROM payments "
                    "WHERE our_ref = $1 FOR UPDATE",
                    our_ref,
                )
                if payment is None or payment["status"] not in _PENDING_STATUSES:
                    await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
                    span.set_attribute("payout.outcome", "skipped")
                    return "skipped"

                # Defense in depth: this worker is started with exactly
                # one provider instance (Chapa, in production -- see
                # main_async()) and nothing should ever enqueue a
                # different provider's payment onto this stream --
                # approve_withdrawal_admin's own guard query already
                # refuses to enqueue a 'manual' row. If one still turns
                # up here (a bug, a stale/hand-crafted XADD), refuse to
                # dispatch it to the wrong rail rather than silently
                # calling create_payout() with mismatched data.
                if payment["provider"] != provider.name:
                    logger.error(
                        "payout_provider_mismatch",
                        our_ref=our_ref,
                        payment_provider=payment["provider"],
                        worker_provider=provider.name,
                    )
                    await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
                    span.set_attribute("payout.outcome", "skipped")
                    return "skipped"

                if payment["status"] == "processing":
                    # Already sent, or possibly sent: never send it again.
                    # See this module's docstring.
                    logger.warning("payout_redelivered_while_processing", our_ref=our_ref)
                    metrics.payouts_awaiting_reconciliation_total.labels(cause="redelivered").inc()
                    await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
                    span.set_attribute("payout.outcome", "awaiting_reconciliation")
                    return "awaiting_reconciliation"

                await conn.execute(
                    "UPDATE payments SET status = 'processing', updated_at = now() WHERE id = $1",
                    payment["id"],
                )

                payment_id = payment["id"]
                user_id = payment["user_id"]
                amount = payment["amount"]
                method_id = payment["method_id"]

        method = await pool.fetchrow(
            "SELECT kind, account_ref, holder_name FROM payment_methods WHERE id = $1", method_id
        )
        assert method is not None
        method_payload: dict[str, str] = {
            "kind": method["kind"],
            "account_ref": method["account_ref"],
            "holder_name": method["holder_name"],
            "bank_code": method["kind"],
        }

        try:
            with _tracer.start_as_current_span("payout.provider_call") as provider_span:
                provider_span.set_attribute("provider.name", provider.name)
                result = await provider.create_payout(method=method_payload, amount=amount, our_ref=our_ref)
        except Exception as exc:
            # The request may or may not have reached Chapa (a timeout after
            # sending looks exactly like a failure to connect), so this is an
            # unknown outcome, not a failure: no refund, the funds stay
            # locked, and the payout waits for an admin.
            logger.error("payout_outcome_unknown", our_ref=our_ref, error=str(exc))
            metrics.payouts_awaiting_reconciliation_total.labels(cause="provider_error").inc()
            await pool.execute(
                "UPDATE payments SET failure_reason = $2, updated_at = now() WHERE id = $1 AND status = 'processing'",
                payment_id,
                f"outcome unknown: {exc}"[:500],
            )
            await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
            span.set_attribute("payout.outcome", "awaiting_reconciliation")
            return "awaiting_reconciliation"

        if result.status == "succeeded":
            async with pool.acquire() as conn:
                async with conn.transaction():
                    txn = await mark_payout_paid(conn, payment_id=payment_id, provider_ref=result.provider_ref)
            if txn is None:
                # Resolved by an admin while this call was in flight. If they
                # marked it failed and refunded it, the player now has the
                # money twice; that needs a person, now.
                logger.error("payout_succeeded_after_admin_resolution", our_ref=our_ref, provider_ref=result.provider_ref)
            else:
                metrics.ledger_transactions_total.labels(kind=txn.kind).inc()
                await ledger.publish_balance_update(pool, redis, user_id)
                await notify_user(pool, redis, user_id=user_id, key="notify.withdrawal_succeeded", amount=str(amount))
            await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
            span.set_attribute("payout.outcome", "succeeded")
            return "succeeded"

        if result.status == "processing":
            # A code review pass caught this treating a merely-accepted
            # transfer as fully settled -- moving locked funds to
            # provider_settlement and telling the player they'd been
            # paid, on nothing more than Chapa having *acknowledged* the
            # request. There is no payout webhook route and no polling
            # fallback for outbound transfers (unlike deposits.py's
            # poll_pending_deposits()), so a transfer Chapa later actually
            # rejects (a bad account number, say) was never reconciled:
            # silent, permanent, unrecoverable player money loss with no
            # signal anywhere it had happened. Left deliberately
            # unresolved instead: the payment stays at status='processing'
            # (already set above), locked funds stay exactly where they
            # already were, and neither a success nor a failure
            # notification goes out -- both would be a real claim about
            # an outcome this worker does not actually know yet. Still
            # records provider_ref, though -- an admin resolving this
            # manually (see services.admin.queries
            # .list_stuck_processing_payouts(), the operator-visibility
            # half of this) needs Chapa's own reference to look the
            # transfer up with them at all. A full fix (automated
            # payout-status polling against Chapa's real transfer-
            # verification response) remains blocked on the same
            # Chapa status-vocabulary gap documented elsewhere in this
            # codebase's history: the exact response shape for
            # GET /v1/transfers/verify/<tx_ref> could not be confirmed
            # from Chapa's docs, and guessing a status mapping here is
            # exactly the kind of money-safety risk not worth taking.
            await pool.execute(
                "UPDATE payments SET provider_ref = $2, raw_response = $3, updated_at = now() "
                "WHERE id = $1",
                payment_id,
                result.provider_ref,
                json.dumps(result.raw_response, default=str),
            )
            metrics.payouts_awaiting_reconciliation_total.labels(cause="provider_accepted").inc()
            await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
            span.set_attribute("payout.outcome", "processing")
            return "processing"

        # A definite rejection from the provider: safe to return the funds.
        async with pool.acquire() as conn:
            async with conn.transaction():
                txn = await mark_payout_failed(
                    conn, payment_id=payment_id, reason=f"provider reported status={result.status}"
                )
        if txn is not None:
            metrics.ledger_transactions_total.labels(kind=txn.kind).inc()
            await ledger.publish_balance_update(pool, redis, user_id)
            await notify_user(pool, redis, user_id=user_id, key="notify.withdrawal_failed", amount=str(amount))
        await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
        span.set_attribute("payout.outcome", "failed")
        return "failed"


def _flatten(streams: Any) -> list[tuple[str, dict[str, str]]]:
    """redis-py's xreadgroup() return shape differs by version/protocol --
    a list of (stream_name, [(id, fields), ...]) pairs on some, a dict of
    {stream_name: [(id, fields), ...]} on others. Normalize both here so
    callers never need to know which one they got.
    """
    entries: list[tuple[str, dict[str, str]]] = []
    pairs = streams.items() if isinstance(streams, dict) else streams
    for _stream_name, messages in pairs:
        for msg_id, fields in messages:
            entries.append((msg_id, fields))
    return entries


async def _claim_stale_entries(
    redis: Redis, consumer_name: str, *, count: int, min_idle_time: int
) -> list[tuple[str, dict[str, str]]]:
    """XAUTOCLAIMs entries idle longer than min_idle_time ms from *any*
    consumer in the group, not just consumer_name's own pending list --
    the cross-consumer half of crash recovery process_next()'s own "this
    consumer's own pending entries first" step can't provide on its own.
    Confirmed directly against this codebase's real Redis version, not
    assumed from docs: XAUTOCLAIM returns
    [next_cursor, [(id, fields), ...], [deleted_ids]] -- the middle
    element is already in the exact (msg_id, fields) shape _flatten()
    produces, so no reshaping is needed here.
    """
    _cursor, claimed, _deleted = await redis.xautoclaim(
        PAYOUT_STREAM,
        GROUP,
        consumer_name,
        min_idle_time=min_idle_time,
        start_id="0-0",
        count=count,
    )
    return list(claimed)


async def process_next(
    pool: asyncpg.Pool,
    redis: Redis,
    provider: PaymentProvider,
    *,
    consumer_name: str = "worker-1",
    claim_stale_after_ms: int = CLAIM_STALE_AFTER_MS,
) -> str | None:
    """Processes at most one job, in order: this consumer's own still-
    pending entries (crash recovery under the same consumer name), then a
    stale entry claimed from a *different*, possibly-dead consumer (cross
    -consumer crash recovery), then a genuinely new one. Returns the
    outcome, or None if the stream was empty. Built as a single-shot step
    so tests can drive it deterministically instead of racing a
    background loop.
    """
    await ensure_group(redis)

    pending = await redis.xreadgroup(GROUP, consumer_name, {PAYOUT_STREAM: "0"}, count=1)
    entries = _flatten(pending)
    if not entries:
        entries = await _claim_stale_entries(
            redis, consumer_name, count=1, min_idle_time=claim_stale_after_ms
        )
    if not entries:
        fresh = await redis.xreadgroup(GROUP, consumer_name, {PAYOUT_STREAM: ">"}, count=1)
        entries = _flatten(fresh)
    if not entries:
        return None

    msg_id, fields = entries[0]
    return await process_one(pool, redis, provider, msg_id=msg_id, our_ref=fields["our_ref"])


async def run_forever(
    pool: asyncpg.Pool,
    redis: Redis,
    provider: PaymentProvider,
    *,
    consumer_name: str = "worker-1",
    claim_stale_after_ms: int = CLAIM_STALE_AFTER_MS,
) -> None:
    await ensure_group(redis)
    while True:
        # A code-review pass caught that this loop had no exception
        # isolation at all: db_pool.py's new bounded pool.acquire()
        # turns a sustained-load pool exhaustion into a real TimeoutError
        # (previously an indefinite hang) -- correct for an HTTP handler,
        # but an unguarded `for` loop here let that exception escape
        # run_forever() entirely, silently killing this fire-and-forget
        # task with no automatic restart (main_async() only awaits a
        # shutdown signal, never checks this task's health). Two levels
        # of isolation: a read-phase failure (Redis itself, say) backs off
        # and retries the whole iteration; a single message's failure
        # doesn't stop the rest of its own batch from being processed --
        # process_one() only acks on a normal exit, so a message that
        # raises here is simply picked back up by this same consumer's
        # own pending-entries re-read next iteration, the exact
        # redelivery-on-crash guarantee this module's own docstring
        # already promises, just without the crash.
        try:
            pending = await redis.xreadgroup(GROUP, consumer_name, {PAYOUT_STREAM: "0"}, count=10)
            entries = _flatten(pending)
            if not entries:
                entries = await _claim_stale_entries(
                    redis, consumer_name, count=10, min_idle_time=claim_stale_after_ms
                )
            if not entries:
                fresh = await redis.xreadgroup(
                    GROUP, consumer_name, {PAYOUT_STREAM: ">"}, count=10, block=5000
                )
                entries = _flatten(fresh)
        except Exception:
            logger.exception("payout_worker_read_failed")
            await asyncio.sleep(1)
            continue

        for msg_id, fields in entries:
            # .get, not [...]: an entry without our_ref (a hand-made XADD)
            # used to raise KeyError again inside this except handler, which
            # ended run_forever(), and the unacked entry killed it again on
            # the next start.
            our_ref = fields.get("our_ref")
            try:
                if our_ref is None:
                    # Nothing to look the payout up by. Acked so it can't
                    # stall the queue; a real 'approved' payout it stood for
                    # is re-enqueued by sweep_stuck_approved_payouts().
                    logger.error("payout_entry_without_our_ref", msg_id=msg_id, fields=fields)
                    await redis.xack(PAYOUT_STREAM, GROUP, msg_id)
                    continue
                await process_one(pool, redis, provider, msg_id=msg_id, our_ref=our_ref)
            except Exception:
                logger.exception("payout_worker_process_one_failed", msg_id=msg_id, our_ref=our_ref)


DEPOSIT_POLL_INTERVAL_SECONDS = 30
WITHDRAWAL_SWEEP_INTERVAL_SECONDS = 60
# "Hourly" per services.payments.deposits.reconcile()'s own docstring,
# quoting spec -- this is what actually runs it; see
# run_provider_reconciliation()'s own docstring for why it lives here
# rather than as an external cron job like packages/core/reconcile_job.py.
PROVIDER_RECONCILE_INTERVAL_SECONDS = 3600
BONUS_SWEEP_INTERVAL_SECONDS = 60
# Cheap (one indexed query, no external calls) and purely observational
# (structured-log only, see device_registry.check_for_degraded_devices's
# own docstring) -- a short interval costs nothing and gets a real
# operator to the "PRIMARY INGESTION DEGRADED" signal faster.
DEVICE_HEALTH_SWEEP_INTERVAL_SECONDS = 300
# Same cadence as the two provider-level reconciliation sweeps above --
# reconciliation as a job class already has an established interval in
# this codebase; reusing it rather than inventing a new number.
LEDGER_RECONCILE_INTERVAL_SECONDS = PROVIDER_RECONCILE_INTERVAL_SECONDS
METRICS_PORT = 8005


async def _run_periodic_sweep(
    name: str, interval_seconds: int, sweep: Callable[[], Awaitable[Any]]
) -> None:
    # One bad sweep must not kill the other background jobs sharing this
    # process, the same reasoning as _handle_command()'s and the
    # auto-claim scan's own isolation fixes elsewhere in this codebase --
    # a real DB/Redis blip on one timer tick shouldn't silently stop every
    # future tick of this specific sweep forever.
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await sweep()
        except Exception:
            logger.exception("payments_periodic_sweep_failed", sweep=name)


async def main_async() -> None:
    """Real production entrypoint: the payout stream consumer (this
    module's own run_forever(), the primary job) alongside six other
    "safe to run on a timer" payments sweeps that need a periodic invoker
    somewhere -- deposits.py's poll_pending_deposits() (a webhook that
    never arrives), withdrawals.py's sweep_stuck_approved_payouts() (an
    enqueue that never landed, since that XADD runs after the DB commit,
    not inside it), deposits.py's run_provider_reconciliation() (spec's
    own hourly Chapa-vs-our-records check, previously built and tested but
    never actually invoked from anywhere -- an architecture audit caught
    this), telebirr_reconcile.py's run_telebirr_reconciliation()
    (the same hourly cadence, CTO directive sections 124-127),
    bonus_sweep.py's sweep_bonus_wagering() (the only thing that ever
    converts a sticky bonus grant into real cash, or expires an unwagered
    one -- see packages/core/bonuses.py's own module docstring),
    ledger_reconcile_sweep.py's sweep_ledger_reconciliation() (the ledger-
    level "cached balance equals sum of ledger entries" check --
    packages/core/reconcile_job.py already built and tested this exact
    comparison as a standalone CLI, but never had a real scheduler; this
    reuses its comparison logic from a process that already runs on a
    timer, instead of standing up a new one), and device_registry.py's
    check_for_degraded_devices() (the automated Telebirr ingestion
    devices' own "has this phone gone quiet" signal -- purely a
    structured log warning, never a financial action). All eight share
    one process/provider rather than separate ones since none of them
    individually justifies its own container, and all are already
    designed to be safe under concurrent, independent invocation.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    tracing.configure_tracing("payout-worker", settings.otel_exporter_endpoint)

    pool = await create_pool(dsn=settings.database_url, min_size=2, max_size=20)
    redis = get_redis()
    provider = ChapaProvider(settings.chapa_api_key)
    metrics_runner = await metrics.start_metrics_server(METRICS_PORT)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    consumer_task = asyncio.create_task(run_forever(pool, redis, provider))

    # run_forever() only ends by raising (ensure_group() at startup is
    # outside its loop's handling, for one). Nothing awaited this task, so
    # the process kept running its sweeps and metrics server with nothing
    # paying out. Stopping instead lets restart: unless-stopped bring the
    # container back.
    def _consumer_exited(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            logger.error("payout_consumer_exited", exc_info=task.exception())
            stop_event.set()

    consumer_task.add_done_callback(_consumer_exited)
    sweep_tasks = [
        asyncio.create_task(
            _run_periodic_sweep(
                "poll_pending_deposits",
                DEPOSIT_POLL_INTERVAL_SECONDS,
                lambda: poll_pending_deposits(pool, redis, provider),
            )
        ),
        asyncio.create_task(
            _run_periodic_sweep(
                "sweep_stuck_approved_payouts",
                WITHDRAWAL_SWEEP_INTERVAL_SECONDS,
                lambda: sweep_stuck_approved_payouts(pool, redis),
            )
        ),
        asyncio.create_task(
            _run_periodic_sweep(
                "run_provider_reconciliation",
                PROVIDER_RECONCILE_INTERVAL_SECONDS,
                lambda: run_provider_reconciliation(pool, provider),
            )
        ),
        asyncio.create_task(
            _run_periodic_sweep(
                "run_telebirr_reconciliation",
                PROVIDER_RECONCILE_INTERVAL_SECONDS,
                lambda: run_telebirr_reconciliation(pool),
            )
        ),
        asyncio.create_task(
            _run_periodic_sweep(
                "sweep_bonus_wagering",
                BONUS_SWEEP_INTERVAL_SECONDS,
                lambda: sweep_bonus_wagering(pool, redis),
            )
        ),
        asyncio.create_task(
            _run_periodic_sweep(
                "sweep_ledger_reconciliation",
                LEDGER_RECONCILE_INTERVAL_SECONDS,
                lambda: sweep_ledger_reconciliation(pool),
            )
        ),
        asyncio.create_task(
            _run_periodic_sweep(
                "check_for_degraded_devices",
                DEVICE_HEALTH_SWEEP_INTERVAL_SECONDS,
                lambda: check_for_degraded_devices(pool),
            )
        ),
    ]

    try:
        await stop_event.wait()
    finally:
        consumer_task.cancel()
        for task in sweep_tasks:
            task.cancel()
        await asyncio.gather(consumer_task, *sweep_tasks, return_exceptions=True)
        await metrics_runner.cleanup()
        await redis.aclose()
        await pool.close()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
