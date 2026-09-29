"""Consumer side of the bot-notification relay (packages/core/
notifications.py is the producer): reads the 'bot_notifications' Redis
Stream with a real consumer group -- same reasoning as
services/payments/payout_worker.py, the first consumer group in this
codebase -- and is the only thing in this module allowed to call
Notifier.send(), keeping services/bot/handlers.py's "nothing sends a
Telegram message except through Notifier" invariant intact even for
notifications that originate outside the bot process entirely.

A Telegram private chat's id is always the same as the user's telegram_id
-- no separate chat-id lookup needed, matching how the rest of this
codebase already treats them as interchangeable (e.g. dedup.py, the bot's
own handlers).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import asyncpg
import structlog
from redis.asyncio import Redis

from packages.core import metrics
from packages.core.notifications import NOTIFICATIONS_STREAM
from services.bot.i18n import resolve_language, t
from services.bot.notifier import Notifier

logger = structlog.get_logger()

GROUP = "bot-notification-workers"

# An entry that raises is retried with its own exponential backoff (base
# x 2^(attempts-1), capped), while newer entries keep flowing. Once it has
# failed DEAD_LETTER_AFTER_ATTEMPTS times over at least
# DEAD_LETTER_AFTER_SECONDS it's copied to DEAD_LETTER_STREAM, acked and
# counted. The time floor keeps a short DB or Redis outage from
# dead-lettering ordinary notifications; an entry that can never render (a
# Bot Content override with a stray '{}', a key this bot doesn't know) is
# moved aside within about ten minutes. Before this (platform audit,
# 2026-09-29) such an entry was retried in a loop with no sleep, and every
# later notification for every player waited behind it.
RETRY_BACKOFF_BASE_SECONDS = 1.0
RETRY_BACKOFF_MAX_SECONDS = 60.0
DEAD_LETTER_AFTER_ATTEMPTS = 5
DEAD_LETTER_AFTER_SECONDS = 600.0
DEAD_LETTER_STREAM = f"{NOTIFICATIONS_STREAM}:dead"


@dataclass
class _Failure:
    attempts: int
    first_failed_at: float
    retry_at: float


async def ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(NOTIFICATIONS_STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _language_for_telegram_id(pool: asyncpg.Pool, telegram_id: int) -> str:
    row = await pool.fetchrow("SELECT language FROM users WHERE telegram_id = $1", telegram_id)
    return resolve_language(row["language"] if row else None)


async def process_one(pool: asyncpg.Pool, redis: Redis, notifier: Notifier, *, msg_id: str, fields: dict[str, str]) -> None:
    telegram_id = int(fields["telegram_id"])
    delivery_id_raw = fields.get("delivery_id")

    if delivery_id_raw is not None:
        # The idempotency guard that makes services/bot/campaign_worker
        # .py's own stuck-delivery reclaim safe: a reclaim can enqueue a
        # second stream entry for a delivery whose *original* enqueue
        # actually succeeded (the process only died before recording that
        # fact) -- this relay's own per-user sequential processing
        # (_drain_one_user() below never runs two entries for the same
        # user concurrently) guarantees that by the time a duplicate
        # entry for the same delivery is dequeued, an earlier one already
        # ran to completion, including the mark_delivery_outcome() call
        # below. Re-checking the delivery's live status right before
        # ever calling notifier.send() is what turns "a delivery might
        # get enqueued twice" into "still sent at most once" -- without
        # this check, the reclaim sweep alone would risk a real duplicate
        # Telegram message.
        current_status = await pool.fetchval(
            "SELECT status FROM notification_deliveries WHERE id = $1", int(delivery_id_raw)
        )
        if current_status != "processing":
            logger.info(
                "notification_relay_skipped_already_resolved_delivery",
                delivery_id=delivery_id_raw,
                status=current_status,
            )
            await redis.xack(NOTIFICATIONS_STREAM, GROUP, msg_id)
            return

    # Two message shapes share this one stream: notify_user()'s own
    # {key, kwargs} (an i18n lookup -- every existing caller) and the
    # Notification Center's {raw_text, delivery_id} (an admin-authored
    # campaign message -- there is no i18n key for content an admin typed
    # themselves). raw_text's presence is what distinguishes them, not a
    # separate stream or a type field, so every existing producer/consumer
    # of NOTIFICATIONS_STREAM is untouched.
    if "raw_text" in fields:
        text = fields["raw_text"]
    else:
        key = fields["key"]
        kwargs: dict[str, Any] = json.loads(fields["kwargs"])
        language = await _language_for_telegram_id(pool, telegram_id)
        text = t(key, language, **kwargs)

    # Notifier.send() only enqueues -- the actual Telegram API call happens
    # later, in Notifier's own background worker, subject to its global
    # rate pace and 429 backoff. A code review pass caught that acking
    # right after send() returned meant this stream entry was marked done
    # the instant the notification landed in Notifier's in-memory queue,
    # not when it was actually delivered (or given up on) -- a crash of
    # this process before Notifier's worker got to it lost the
    # notification outright, with no redelivery path left, since the
    # stream entry claiming it was already gone. Awaiting the future
    # send() now returns makes this ack happen only once Notifier reaches
    # a real terminal outcome for this message.
    # Notifier's own priority lanes (services/bot/notifier.py): a campaign
    # broadcast (identified the same way this function already
    # distinguishes campaign vs. transactional above -- delivery_id
    # present) must never delay a player's own interactive command reply
    # or an individual transactional push (deposit confirmation, win
    # notification) behind however many broadcast recipients happen to be
    # queued first. Everything else (the default) stays "high".
    priority = "low" if delivery_id_raw is not None else "high"
    done = await notifier.send(telegram_id, text, priority=priority)
    outcome = await done

    delivery_id = fields.get("delivery_id")
    if delivery_id is not None:
        # Local import: keeps packages/core/campaigns.py (which never
        # otherwise appears in the bot process's import graph) out of
        # every other, non-campaign call through this same relay.
        from packages.core.campaigns import mark_delivery_outcome
        from packages.core.metrics import notification_campaign_deliveries_total

        notification_campaign_deliveries_total.labels(outcome=outcome).inc()
        await mark_delivery_outcome(
            pool,
            delivery_id=int(delivery_id),
            outcome="delivered" if outcome == "delivered" else "failed",
            failure_reason=None if outcome == "delivered" else outcome,
        )

    await redis.xack(NOTIFICATIONS_STREAM, GROUP, msg_id)


def _flatten(streams: Any) -> list[tuple[str, dict[str, str]]]:
    entries: list[tuple[str, dict[str, str]]] = []
    pairs = streams.items() if isinstance(streams, dict) else streams
    for _stream_name, messages in pairs:
        for msg_id, fields in messages:
            entries.append((msg_id, fields))
    return entries


async def process_next(
    pool: asyncpg.Pool, redis: Redis, notifier: Notifier, *, consumer_name: str = "relay-1"
) -> bool:
    """Processes at most one queued notification. Returns False if the
    stream was empty. Built as a single-shot step, same reasoning as
    payout_worker.process_next(): deterministic for tests, and a real
    run_forever() loop is just this called repeatedly.
    """
    await ensure_group(redis)

    pending = await redis.xreadgroup(GROUP, consumer_name, {NOTIFICATIONS_STREAM: "0"}, count=1)
    entries = _flatten(pending)
    if not entries:
        fresh = await redis.xreadgroup(GROUP, consumer_name, {NOTIFICATIONS_STREAM: ">"}, count=1)
        entries = _flatten(fresh)
    if not entries:
        return False

    msg_id, fields = entries[0]
    await process_one(pool, redis, notifier, msg_id=msg_id, fields=fields)
    return True


async def _record_failure(
    redis: Redis, failures: dict[str, _Failure], msg_id: str, fields: dict[str, str], exc: Exception
) -> None:
    now = time.monotonic()
    failure = failures.setdefault(msg_id, _Failure(attempts=0, first_failed_at=now, retry_at=now))
    failure.attempts += 1
    if (
        failure.attempts >= DEAD_LETTER_AFTER_ATTEMPTS
        and now - failure.first_failed_at >= DEAD_LETTER_AFTER_SECONDS
    ):
        dead_fields: dict[Any, Any] = {**fields, "original_id": msg_id, "error": repr(exc)[:500]}
        try:
            await redis.xadd(DEAD_LETTER_STREAM, dead_fields)
            await redis.xack(NOTIFICATIONS_STREAM, GROUP, msg_id)
        except Exception:
            logger.exception("notification_dead_letter_failed", msg_id=msg_id)
        else:
            failures.pop(msg_id, None)
            metrics.notification_relay_dead_lettered_total.inc()
            logger.error(
                "notification_dead_lettered",
                msg_id=msg_id,
                telegram_id=fields.get("telegram_id"),
                key=fields.get("key"),
                attempts=failure.attempts,
            )
        return
    failure.retry_at = now + min(
        RETRY_BACKOFF_MAX_SECONDS, RETRY_BACKOFF_BASE_SECONDS * 2 ** (failure.attempts - 1)
    )


async def _drain_one_user(
    pool: asyncpg.Pool,
    redis: Redis,
    notifier: Notifier,
    entries: list[tuple[str, dict[str, str]]],
    failures: dict[str, _Failure] | None = None,
) -> None:
    # A code-review pass caught two related gaps here: db_pool.py's new
    # bounded pool.acquire() turns sustained-load pool exhaustion into a
    # real TimeoutError (previously an indefinite hang), and this
    # function's caller runs every user's own _drain_one_user()
    # concurrently via asyncio.gather() -- without a try/except here, one
    # user's failure would propagate into that gather() and (its default
    # behavior, no return_exceptions=True) cancel every other user's
    # still-in-flight delivery in the same batch too, not just skip the
    # one that failed. process_one() only acks on a normal exit, so a
    # message that raises here is simply picked back up by this same
    # consumer's own pending-entries re-read next iteration -- the exact
    # redelivery-on-crash guarantee this module's own docstring already
    # promises, just without actually crashing anything.
    for msg_id, fields in entries:
        try:
            await process_one(pool, redis, notifier, msg_id=msg_id, fields=fields)
        except Exception as exc:
            logger.exception("notification_relay_process_one_failed", msg_id=msg_id)
            if failures is not None:
                await _record_failure(redis, failures, msg_id, fields, exc)
        else:
            if failures is not None:
                failures.pop(msg_id, None)


async def _process_batch(
    pool: asyncpg.Pool,
    redis: Redis,
    notifier: Notifier,
    entries: list[tuple[str, dict[str, str]]],
    failures: dict[str, _Failure] | None = None,
) -> None:
    # A code review pass caught that awaiting process_one() for each entry
    # in turn made this a head-of-line-blocking loop: process_one() awaits
    # notifier.send()'s returned future all the way to a terminal outcome,
    # which for a chat currently in a Telegram 429 backoff can mean several
    # retry/sleep cycles (see Notifier._run()). One backed-off chat_id in
    # the batch used to stall delivery to every other, unrelated user in
    # it for the whole backoff duration. Grouping by telegram_id and
    # running each user's entries concurrently fixes that while still
    # keeping a single user's own notifications in their original stream
    # order (so a 429 on their first message can't let their second one
    # jump ahead and arrive out of sequence).
    by_user: dict[int, list[tuple[str, dict[str, str]]]] = {}
    for msg_id, fields in entries:
        by_user.setdefault(int(fields["telegram_id"]), []).append((msg_id, fields))
    await asyncio.gather(
        *(_drain_one_user(pool, redis, notifier, user_entries, failures) for user_entries in by_user.values())
    )


async def run_forever(
    pool: asyncpg.Pool, redis: Redis, notifier: Notifier, *, consumer_name: str = "relay-1"
) -> None:
    await ensure_group(redis)
    # This consumer's failing entries, by stream id. In memory on purpose:
    # after a restart every pending entry is simply retried again.
    failures: dict[str, _Failure] = {}
    while True:
        # Read-phase failures (Redis itself, say) get isolated the same
        # way as services/payments/payout_worker.py's run_forever() --
        # back off and retry the whole iteration rather than letting an
        # exception escape this loop and silently kill the fire-and-forget
        # relay_task with no automatic restart (services/bot/app.py only
        # ever cancels it at shutdown, never checks its health in between).
        #
        # Pending entries (redelivered after a crash, or waiting out a
        # retry backoff) are read alongside new ones, never instead of
        # them: an entry that keeps failing must not hold up everyone
        # else's notifications while it waits.
        try:
            pending = _flatten(
                await redis.xreadgroup(GROUP, consumer_name, {NOTIFICATIONS_STREAM: "0"}, count=100)
            )
            now = time.monotonic()
            due = [(i, f) for i, f in pending if i not in failures or failures[i].retry_at <= now]
            # Wait for new entries only until the next retry is due.
            next_retry = min((failures[i].retry_at for i, _ in pending if i in failures), default=None)
            block_ms = 5000 if next_retry is None else max(1, min(5000, int((next_retry - now) * 1000) + 1))
            fresh = await redis.xreadgroup(
                GROUP,
                consumer_name,
                {NOTIFICATIONS_STREAM: ">"},
                count=10,
                block=None if due else block_ms,
            )
            entries = due + _flatten(fresh)
        except Exception:
            logger.exception("notification_relay_read_failed")
            await asyncio.sleep(1)
            continue

        if entries:
            await _process_batch(pool, redis, notifier, entries, failures)
