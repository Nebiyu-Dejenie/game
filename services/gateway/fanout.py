"""Redis pub/sub -> local WebSocket fan-out.

One FanoutHub per gateway process, subscribing once to `room:*` and
`user:*`. Every message it receives from Redis was serialized exactly once
by whoever published it (the engine, via round_engine.py's `_publish_room`)
-- the hub's only job is handing that same string to every locally
connected socket that's interested, never re-serializing it per connection.
That's what makes the cost of one number call independent of how many
players are watching it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict, deque

import structlog
from redis.asyncio import Redis

from packages.core import metrics

logger = structlog.get_logger()

_PATTERNS = ("room:*", "user:*", "keno:*")
# Backoff between attempts to re-subscribe after the Redis subscription
# drops: quick for a blip, capped so a longer outage doesn't turn into a
# tight retry loop.
_RESUBSCRIBE_MIN_DELAY = 0.5
_RESUBSCRIBE_MAX_DELAY = 10.0

MAX_QUEUE_SIZE = 100

# Message types safe to drop for a connection that's falling behind: the
# next state_sync fully supersedes them. Anything else (round_end, balance,
# card_taken) is kept -- losing a settlement message because a socket was
# briefly slow is not an acceptable trade.
DROPPABLE_TYPES = {"lobby_tick", "call"}


def _peek_type(raw_message: str) -> str | None:
    try:
        parsed = json.loads(raw_message)
    except json.JSONDecodeError:
        return None
    return parsed.get("t") if isinstance(parsed, dict) else None


class ConnectionQueue:
    """A bounded outbound mailbox for one WebSocket connection.

    Implements the spec's section 6.4 backpressure rule at the application
    level: Starlette/ASGI doesn't expose the raw socket send-buffer size the
    spec's "64 KB" language assumes, so queue depth is the equivalent signal
    here. When the queue is full, this connection is provably behind --
    dropping its pending droppable (tick-shaped) messages and flagging a
    fresh `state_sync` is strictly better than either blocking the whole
    room's fan-out on one slow reader or silently growing memory forever.

    A deque plus one Event, not an asyncio.Queue raced against a second
    Event: the race cost two new tasks, an asyncio.wait and a cancelled
    task per message for every idle socket, which is every socket at the
    moment a number is called. Measured 2026-10-05 with 1,000 parked
    writers, one broadcast took 27 ms to reach them all that way.
    """

    def __init__(self) -> None:
        self._messages: deque[str] = deque()
        self.needs_state_sync = False
        # Set whenever there is something for the writer to act on: a new
        # message, or needs_state_sync raised. A code review pass caught
        # that the writer loop only checks needs_state_sync at the top of
        # its loop, immediately before blocking -- if the flag flips while
        # it's parked on an empty queue (the queue was drained around the
        # same moment the overflow below happened), nothing else wakes it
        # until some unrelated message arrives, which near a quiet round
        # boundary (calls pausing before settlement) could leave a
        # recovering client's board stale for a real, unbounded stretch.
        self._wakeup = asyncio.Event()

    def qsize(self) -> int:
        return len(self._messages)

    def offer(self, raw_message: str) -> None:
        if len(self._messages) >= MAX_QUEUE_SIZE:
            self._handle_full(raw_message)
            return
        self._messages.append(raw_message)
        self._wakeup.set()

    def request_state_sync(self) -> None:
        """Ask this connection's writer to send a fresh state_sync, waking it
        if it's parked on an empty queue. Used when the fan-out itself lost
        messages (see FanoutHub._listen)."""
        self.needs_state_sync = True
        self._wakeup.set()

    def _handle_full(self, raw_message: str) -> None:
        if _peek_type(raw_message) in DROPPABLE_TYPES:
            self.request_state_sync()
            return
        # A non-droppable message arrived while full: everything currently
        # queued is stale relative to it, so clear the backlog and keep
        # this one rather than lose it.
        self._messages.clear()
        self._messages.append(raw_message)
        self._wakeup.set()

    async def get_or_wake(self) -> str | None:
        """Waits for either the next queued message or needs_state_sync
        being raised, whichever happens first. Returns the message, or
        None if needs_state_sync is up and nothing is queued -- the
        caller's own top-of-loop needs_state_sync check is what actually
        acts on that; this only makes sure that check runs promptly
        instead of waiting on whatever unrelated message arrives next.

        Both conditions are checked before clearing the wakeup, and
        nothing awaits between the check and the wait, so a message or
        flag that arrived earlier (while the writer was busy sending) is
        never lost by the clear.
        """
        while not self._messages:
            if self.needs_state_sync:
                return None
            self._wakeup.clear()
            await self._wakeup.wait()
        return self._messages.popleft()


class FanoutHub:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._pubsub = redis.pubsub()
        self._room_subscribers: dict[int, set[ConnectionQueue]] = defaultdict(set)
        self._user_subscribers: dict[int, set[ConnectionQueue]] = defaultdict(set)
        # Keno has exactly one continuous round stream, not a per-room
        # concept (services/engine/keno_round_engine.py publishes every
        # public round event to one literal channel, "keno:live") -- a
        # plain set, not a dict keyed by an id that doesn't exist here.
        self._keno_subscribers: set[ConnectionQueue] = set()
        self._listener_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._pubsub.psubscribe(*_PATTERNS)
        self._listener_task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        with contextlib.suppress(Exception):  # the connection may already be gone
            await self._pubsub.punsubscribe(*_PATTERNS)
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]

    def subscribe_room(self, room_id: int, cq: ConnectionQueue) -> None:
        self._room_subscribers[room_id].add(cq)

    def unsubscribe_room(self, room_id: int, cq: ConnectionQueue) -> None:
        subs = self._room_subscribers.get(room_id)
        if subs is None:
            return
        subs.discard(cq)
        if not subs:
            del self._room_subscribers[room_id]

    def subscribe_user(self, user_id: int, cq: ConnectionQueue) -> None:
        self._user_subscribers[user_id].add(cq)

    def unsubscribe_user(self, user_id: int, cq: ConnectionQueue) -> None:
        subs = self._user_subscribers.get(user_id)
        if subs is None:
            return
        subs.discard(cq)
        if not subs:
            del self._user_subscribers[user_id]

    def subscribe_keno(self, cq: ConnectionQueue) -> None:
        self._keno_subscribers.add(cq)

    def unsubscribe_keno(self, cq: ConnectionQueue) -> None:
        self._keno_subscribers.discard(cq)

    async def _listen(self) -> None:
        """Delivers every published message to the subscribed connections,
        for the life of the gateway.

        Supervised (platform audit, 2026-09-29): the subscription used to
        end the first time Redis closed its connection -- a Redis restart,
        a timeout, a network blip -- and nothing restarted or reported it.
        Every connected player then stopped receiving Bingo calls, round
        results, balance updates and Keno events, while pings still
        answered, so no client ever reconnected. Reproduced with a single
        CLIENT KILL TYPE pubsub (test_gateway_fanout_resilience.py). Now a
        dropped subscription is logged, counted, and re-established with
        backoff, and every connection is asked for a fresh state_sync,
        because pub/sub doesn't replay what was published during the gap.
        """
        delay = _RESUBSCRIBE_MIN_DELAY
        while True:
            try:
                async for message in self._pubsub.listen():
                    delay = _RESUBSCRIBE_MIN_DELAY
                    self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("gateway_fanout_subscription_lost")
                metrics.gateway_fanout_resubscribes_total.inc()
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RESUBSCRIBE_MAX_DELAY)
            try:
                await self._resubscribe()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("gateway_fanout_resubscribe_failed")
                continue
            logger.info("gateway_fanout_resubscribed")
            self._request_state_sync_everywhere()

    async def _resubscribe(self) -> None:
        old = self._pubsub
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(*_PATTERNS)
        with contextlib.suppress(Exception):
            await old.aclose()  # type: ignore[no-untyped-call]

    def _request_state_sync_everywhere(self) -> None:
        queues: set[ConnectionQueue] = set(self._keno_subscribers)
        for subs in self._room_subscribers.values():
            queues.update(subs)
        for subs in self._user_subscribers.values():
            queues.update(subs)
        for cq in queues:
            cq.request_state_sync()

    def _dispatch(self, message: object) -> None:
        if not isinstance(message, dict) or message.get("type") != "pmessage":
            return
        channel = message["channel"]
        data = message["data"]
        if channel.startswith("room:"):
            room_id_str = channel.removeprefix("room:")
            if not room_id_str.isdigit():
                return
            for cq in list(self._room_subscribers.get(int(room_id_str), ())):
                cq.offer(data)
        elif channel.startswith("user:"):
            user_id_str = channel.removeprefix("user:")
            if not user_id_str.isdigit():
                return
            for cq in list(self._user_subscribers.get(int(user_id_str), ())):
                cq.offer(data)
        elif channel == "keno:live":
            for cq in list(self._keno_subscribers):
                cq.offer(data)
