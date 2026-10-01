# Hotfix runbook: live Bingo fixes (2026-09-26)

**Status: deployed 2026-09-29.** The operator approved ("deploy") on
2026-09-29. Two steps, both verified; see "Deploy record" at the end. Operator's instruction: these
fixes go out as soon as the server is reachable, before anything else,
without waiting for the VPS migration.

## What ships

Branch `hotfix/live-bingo-2026-09-26`, commit **`b226a33`**. That's
production's current commit `4645669` plus exactly three fixes from `main`,
cherry-picked unchanged. The production-code diffs are byte-identical to the
reviewed commits; nothing else from `main` rides along.

| From main | Fixes | Files |
|---|---|---|
| `b583cf7` | A Bingo round voided from outside the engine (admin void, emergency stop, or the engine's own underfilled-lobby refund racing a player) moved real money: a dropped card refunded twice (100 → 120), a voided round flipped back to running and paid winners from an already-refunded pot, and a join took a stake nobody would refund. | `services/engine/round_engine.py` |
| `b2f1ce0` | Bonus playthrough counted refunded stakes, so take-and-drop or an underfilled lobby cleared a bonus (which converts to withdrawable cash) with nothing at risk. | `packages/core/bonuses.py` |
| `ac6c777` | Keno's round-open event sent `server_time` in seconds. Every connection receives it, so every player's countdowns, the Bingo lobby's included, showed garbage for up to 20 s after each Keno round opened. | `services/engine/keno_round_engine.py`, `web/miniapp/js/ws.js` |

No migrations. The alembic version stays `a7c3e9f2d146`.

Tested on the branch itself: 1,629 passed. Three tests failed, and all three
fail identically on `4645669`, so they aren't caused by these fixes:
`test_wal_archiving_supports_point_in_time_recovery`,
`test_full_campaign_to_delivery_flow_over_real_http`, and the announcement
marquee browser test.

Containers that pick up the change: `engine-worker` (Bingo engine),
`keno-worker`, `payout-worker` (runs the bonus sweep), `gateway` (serves the
Mini App's `ws.js`). The others keep running unchanged code.

## Steps (on zemen-game-server, `~/apps/igame`)

**0. Pre-flight (read-only).**
```
git status --short && git rev-parse HEAD          # clean, 4645669
docker compose -f deploy/docker-compose.prod.yml ps  # all up
```

**1. Get the commit onto the server.** The `igame` remote is unreachable
from the dev machine as of 2026-09-26, so the commit travels as a git bundle
over SSH instead of a fetch:
```
# dev machine
git bundle create /tmp/hotfix.bundle 4645669..hotfix/live-bingo-2026-09-26
scp /tmp/hotfix.bundle zemen-game-server:/tmp/
# server
git fetch /tmp/hotfix.bundle hotfix/live-bingo-2026-09-26:hotfix/live-bingo-2026-09-26
git diff --stat 4645669 b226a33                   # expect the 7 files above plus 3 test files
```

**2. Backup and rollback image.**
```
COMPOSE_FILE=deploy/docker-compose.prod.yml POSTGRES_USER=<prod user> ./deploy/backup.sh
docker tag jobingo:latest jobingo:rollback-4645669
```

**3. Check for Bingo rounds in flight.** Restarting the engine voids and
refunds any round it owned (crash recovery), so deploy between rounds.
Read-only; target: the production database.
```sql
SELECT r.id, r.room_id, r.status, count(e.card_no) AS cards
FROM rounds r LEFT JOIN round_entries e ON e.round_id = r.id
WHERE r.status IN ('lobby', 'running', 'settling')
GROUP BY r.id ORDER BY r.id;
```
If a `running` round has real players, wait for it to finish.

**4. Build and restart the four containers.**
```
git checkout --detach b226a33
docker build -t jobingo:latest .
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps engine-worker keno-worker payout-worker gateway
```

## Verification

1. `docker compose ps`: the four containers are up and not restarting. Their
   logs for 5 minutes show no tracebacks. The engine's recovery log lists
   only rounds from step 3.
2. The fixed code is what's running:
   ```
   docker compose exec engine-worker grep -c "AND status = 'lobby' RETURNING id" services/engine/round_engine.py   # 1
   docker compose exec keno-worker grep -c "int(time.time() \* 1000)" services/engine/keno_round_engine.py          # 1
   docker compose exec payout-worker grep -c "regexp_replace" packages/core/bonuses.py                              # 1
   curl -s https://arada.click/js/ws.js | grep -c "server_time > 1e12"                                              # 1
   ```
3. The clock fix on the wire: `docker compose exec redis redis-cli SUBSCRIBE keno:live`
   for about a minute; a `keno.betting.open` frame carries a 13-digit
   `server_time`.
4. `curl -s -o /dev/null -w '%{http_code}' https://arada.click/healthz` returns 200.
5. `docker compose run --rm reconcile-job` exits 0 (no ledger drift).
6. `SELECT version_num FROM alembic_version` is still `a7c3e9f2d146`.

A real-money Bingo join isn't part of this verification. It would move a real
stake and needs the operator's explicit confirmation of the account and
amount first.

## Rollback (under 2 minutes, no data changes to undo)

```
docker tag jobingo:rollback-4645669 jobingo:latest
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps engine-worker keno-worker payout-worker gateway
git checkout --detach 4645669
```
Roll back on tracebacks or restart loops in the four containers, a failing
`/healthz`, or a reconcile mismatch. Rolling back brings the three bugs back.

## After

Delete the leftover `~/apps/igame/verify_bingo_join.py`. Then continue with
the Track A items that were waiting for the server.

## Deploy record (2026-09-29)

The server had been up 5 days (`uptime`): the "outages" since 24 Sep were
the network path to it, not the machine. All containers had kept running.

**Pre-flight (read-only).**
- Production was at `4645669`, alembic `a7c3e9f2d146`, Keno off, allowlist on.
- `telebirr_sms` deposits: **enabled** since 2026-09-22, but `payment_evidence`
  had **0 rows**, so no Telebirr SMS had ever been ingested or redeemed.
- The only Bingo round in play had 0 cards.

**Step 1: this hotfix, 08:05 UTC.**
- Backup `~/backups/jobingo-20260929T080420Z.dump`; image tagged
  `jobingo:rollback-4645669`.
- `b226a33` built; `engine-worker`, `keno-worker`, `payout-worker` and
  `gateway` restarted.
- Verified: the fixed code was in all four containers, `ws.js` served
  the fix, `/healthz` 200, no errors, Keno `server_time` 13 digits (ms),
  reconcile OK, alembic unchanged. The two empty rounds were voided with
  nothing to refund.
- The leftover `verify_bingo_join.py` was deleted.

**Step 2: all of `main` (`28f4bac`), 08:43 UTC.** At the operator's
instruction to pull the configuration-management work and deploy.
- Verified before deploying, on a throwaway database migrated from empty:
  mypy clean; 1,806 passed; 89 of 91 browser tests passed. The failures
  were the two backup drills, which target the dev container rather than
  the throwaway database, and two known or ordering flakes that pass on
  their own. The new migration was round-tripped (downgrade and upgrade).
- Backup `~/backups/jobingo-20260929T084305Z.dump`; image tagged
  `jobingo:rollback-b226a33`.
- Migration `a7c3e9f2d146` -> `b5d9e3a1c7f2` applied; all nine app
  containers restarted.
- Verified: Keno still off and allowlist still on, `platform_settings`
  empty (every limit still equals the environment value), `/healthz` and
  admin health 200, the new code in the containers, no errors in any of
  the nine, reconcile OK, Bingo and Keno rounds cycling.

**Current rollback** (to the hotfix; no schema downgrade needed, since the
new migration only adds columns, a table and CHECKs the older code
ignores):
```
docker tag jobingo:rollback-b226a33 jobingo:latest
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps gateway admin payments bot sms engine-worker payout-worker simulated-players-worker keno-worker
git checkout --detach b226a33
```

The server's checkout is detached at `28f4bac`. Its `origin` still points
at the old `igame` repo, which no longer resolves.

**Step 3: three more live fixes (`a7603c5`), 09:38 UTC.** At the
operator's "continue deploy". Four commits on top of `28f4bac`, no
migration. Only `gateway` and `admin` restarted, so no Bingo round was
interrupted.
- `63ea8ed`: the gateway's Redis subscription now survives Redis closing
  it. Before, a single `CLIENT KILL TYPE pubsub` froze every player's
  screen until a manual restart.
- `0e4ce63`: an emergency stop only tells players about a refund that
  actually happened, with their real refunded amount.
- `a7603c5`: a manual bonus grant happens once per intended grant (a
  double-click used to grant twice).
- Verified before deploying: 1,814 passed; the only failures were the two
  backup drills, which can't run against the throwaway database. After:
  the fixed code is in both containers, `/healthz` and admin health 200,
  no errors, alembic `b5d9e3a1c7f2`, reconcile OK.
- Backup `~/backups/jobingo-20260929T093749Z.dump`; image tagged
  `jobingo:rollback-28f4bac`.
- Rollback: `docker tag jobingo:rollback-28f4bac jobingo:latest`, then
  `up -d --no-deps gateway admin` and `git checkout --detach 28f4bac`.

Bingo rounds after the deploy were all empty (0 cards) and ended voided
after ~5 minutes, as they did before it: nobody was playing, and an empty
room keeps calling numbers so it never looks dead.

## Step 4 (prepared 2026-09-30, not yet run): the Keno fixes and the audit's high findings

Waiting on the network, not on code. The dev machine is on another network
(Wi-Fi 10.64.6.x) and can't reach the server's LAN address. Production
is unaffected (`/healthz` 200, still `a7603c5`).

**What ships** (`a7603c5..main`, no migrations, alembic stays
`b5d9e3a1c7f2`):
- the three Keno audit fixes: `be4f873` (a drawn stuck round is settled,
  not refunded), `6b3899e` (a ticket placed during a stuck-round refund is
  refunded too), `939a29b` (autoplay stop-loss doesn't overshoot);
- `24d2649`: a Keno reserve deposit or withdrawal happens once per
  intended transfer (a double-clicked 30,000 deposit moved 60,000). This
  is needed before the Stage 1 reserve funding;
- the 13 fixed high findings in `docs/audit/platform-audit-2026-09.md`
  (#15, #16, #19, #22 to #24, #26 to #31, #34, #35);
- four fixed medium findings on Keno: #56 (a ticket is claimed before
  it's paid, and only the claiming pass pays its jackpot), #40 (autoplay
  counts a round in the ticket's own transaction), #50 (the circuit
  breaker demotes one tier per trip), #64 (hot-cold lookback bounded);
- `fc4fd3b`, `d5c5703`: monitoring config (profile-gated, doesn't start).
- payments fixes from the medium findings:
  - `b07aedd`: a deposit webhook only touches an incoming payment from the
    same provider; one naming a withdrawal used to fail it without a
    refund (#70/#71).
  - `f18bdda`: a withdrawal from a banned or limited account goes to review
    instead of auto-approving (#78).
  - `1b5c2cc`: the chargeback window starts at the credit, not at the
    checkout (#79).
- `2fefe43`: a Bingo number call waits out a Redis outage, and the round
  stops for recovery to refund if the engine lost the room meanwhile. This
  fixes a regression in #23 found by CI's chaos test.
- CI repairs (`40e5c6d`, `9053103`): not deployed code, but they're why
  GitHub CI now verifies the release.

Verified before deploying: mypy clean; full suite 1,857 passed; the only
failures were the two backup drills (they can't run against the
throwaway database) and `test_full_campaign_to_delivery_flow_over_real_http`
(fails identically on `4645669`).

**All nine app containers restart**, because `packages/core` changed.
Restarting the Bingo engine voids and refunds any round it owns, so the
script stops before touching anything if a real (not simulated) player
holds a card in an open round. Run it between rounds.

```
# dev machine
git bundle create /tmp/step1.bundle a7603c5..main
scp /tmp/step1.bundle deploy5.sh zemen-game-server:/tmp/
ssh zemen-game-server 'bash /tmp/deploy5.sh'
```

The script (`/tmp/deploy5.sh` on the server):
```bash
#!/usr/bin/env bash
# Step 1 deploy: the Keno fixes, the reserve double-post fix and the 13
# verified high-finding fixes. a7603c5 -> main. No migrations.
set -euo pipefail
cd ~/apps/igame
C="docker compose -f deploy/docker-compose.prod.yml"
U=$($C exec -T postgres printenv POSTGRES_USER </dev/null); D=$($C exec -T postgres printenv POSTGRES_DB </dev/null)
Q() { $C exec -T postgres psql -U "$U" -d "$D" -At -c "$1" </dev/null; }
APPS="gateway admin payments bot sms engine-worker payout-worker simulated-players-worker keno-worker"

echo "== pre-flight"
echo "at: $(git rev-parse --short HEAD)  alembic: $(Q 'SELECT version_num FROM alembic_version')"
git fetch -q /tmp/step1.bundle main:deploy/main-step1
TARGET=$(git rev-parse --short deploy/main-step1); echo "fetched $TARGET"
git diff --stat HEAD deploy/main-step1 -- migrations | tail -1
# Restarting the engine voids and refunds any round it owns. Refuse if a
# real (not simulated) player holds a card in any open round.
LIVE=$(Q "SELECT count(*) FROM rounds r JOIN round_entries e ON e.round_id = r.id JOIN users u ON u.id = e.user_id
          WHERE r.status IN ('lobby','running','settling') AND NOT u.is_simulated")
echo "real players' cards in open Bingo rounds: $LIVE"
if [ "$LIVE" != "0" ]; then echo "ABORT: real players in an open round; retry between rounds"; exit 1; fi
echo "open Keno rounds with pending tickets: $(Q "SELECT count(*) FROM keno_tickets t JOIN keno_rounds k ON k.id = t.round_id WHERE t.status = 'pending'")"
echo "Telebirr SMS deposits (operator switched off; expect f): $(Q "SELECT enabled||' since '||updated_at FROM payment_provider_availability WHERE provider = 'telebirr_sms' AND direction = 'in'")"

echo "== backup and rollback image"
COMPOSE_FILE=deploy/docker-compose.prod.yml POSTGRES_USER=$U BACKUP_DIR=$HOME/backups ./deploy/backup.sh "$D" </dev/null
docker tag jobingo:latest jobingo:rollback-a7603c5

BINGO_BEFORE=$(Q 'SELECT COALESCE(max(id), 0) FROM rounds'); KENO_BEFORE=$(Q 'SELECT COALESCE(max(id), 0) FROM keno_rounds')

echo "== build and restart"
git checkout -q --detach deploy/main-step1; echo "checked out $(git rev-parse --short HEAD)"
docker build -q -t jobingo:latest . </dev/null >/dev/null; echo "built $(docker image inspect jobingo:latest --format '{{.Id}}' | cut -c8-19)"
$C up -d --no-deps $APPS </dev/null 2>&1 | tail -3
sleep 40

echo "== verify"
echo "alembic (expect b5d9e3a1c7f2): $(Q 'SELECT version_num FROM alembic_version')"
echo "keno enabled|allowlist (expect f|t): $(Q "SELECT keno_enabled||'|'||beta_restricted FROM keno_configs WHERE effective_from <= now() ORDER BY effective_from DESC LIMIT 1")"
g() { printf '%-15s %-45s %s\n' "$1" "$3" "$($C exec -T "$1" grep -c "$3" "$2" </dev/null || true)"; }
g keno-worker   services/engine/keno_round_engine.py 'drawn_numbers"\] is not None'
g keno-worker   services/engine/keno_round_engine.py "status IN ('draw_complete', 'settling')"
g gateway       packages/core/keno_tickets.py        'class AutoplayLossLimitPending'
g gateway       services/gateway/connection.py       'MAX_COMMANDS_IN_FLIGHT = '
g gateway       services/gateway/connection.py       'gateway_writer_failed'
g engine-worker services/engine/round_engine.py      'claimed_at=call_time'
g engine-worker services/engine/round_engine.py      'engine_command_reply_failed'
g engine-worker services/engine/round_engine.py      'CALL_UPDATE_ATTEMPTS = '
g engine-worker services/engine/round_engine.py      'async def _publish_call'
g engine-worker services/engine/room_lock.py         'async def confirm'
g payout-worker services/payments/withdrawals.py     'async def _refs_still_queued'
g payout-worker services/payments/payout_worker.py   'payout_consumer_exited'
g payout-worker services/payments/deposits.py        'deposit_poll_failed'
g payments      services/payments/deposits.py        'event_id=f"{event.event_id}:{event.status}"'
g payments      services/payments/withdrawals.py     'greatest(6, length(n::text))'
g payments      services/payments/deposits.py        'mark that withdrawal failed without refunding it'
g gateway       services/payments/withdrawals.py     '("banned", "limited")'
g gateway       services/payments/withdrawals.py     'LEFT JOIN ledger_transactions lt ON lt.id = p.ledger_txn_id'
g admin         services/admin/keno_queries.py       '_RESERVE_TRANSFER_LOCK_KEY = '
g bot           services/bot/notification_relay.py   'DEAD_LETTER_STREAM = '
g admin         web/admin/js/screens/keno/overview.js 'request_id: transferRequestId'
g keno-worker   services/engine/keno_round_engine.py 'if is_jackpot and settled:'
g keno-worker   packages/core/keno_tier_automation.py 'last_trip = await conn.fetchval'
g gateway       packages/core/keno_tickets.py        'rounds_placed = rounds_placed + 1'
g gateway       services/gateway/app.py              'Query(default=50, ge=1, le=200)'
echo "healthz: $(curl -s -o /dev/null -w '%{http_code}' https://arada.click/healthz)"
$C ps --format '{{.Service}} {{.Status}}' </dev/null | grep -E "$(echo $APPS | tr ' ' '|')"
for s in $APPS; do printf '%-26s errors in last 40s: %s\n' "$s" "$($C logs --since 40s $s </dev/null 2>&1 | grep -ciE 'traceback|exception|"level": "error"' || true)"; done
echo "new rounds since restart: Bingo $(Q "SELECT count(*) FROM rounds WHERE id > $BINGO_BEFORE")  Keno $(Q "SELECT count(*) FROM keno_rounds WHERE id > $KENO_BEFORE")"
echo "reconcile: $($C run --rm reconcile-job </dev/null 2>&1 | grep -o '"event": "[a-z_]*"' | tail -1)"
rm -f /tmp/step1.bundle
```

**Rollback** (no schema change to undo):
```
docker tag jobingo:rollback-a7603c5 jobingo:latest
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps gateway admin payments bot sms engine-worker payout-worker simulated-players-worker keno-worker
git checkout --detach a7603c5
```

**After it's green: Stage 1 reserve funding** (the operator's Step 2).
Nothing is posted until the operator confirms the exact transaction:
`keno_reserve_deposit`, house_float -30,000.00 and keno_reserve +30,000.00.
It goes through the same audited function as the admin console's
Deposit button, run in the admin container, with a fixed request_id so a
re-run is a no-op rather than a second transfer:
```python
# docker compose -f deploy/docker-compose.prod.yml exec -T admin python - <ADMIN_ID> < reserve_funding.py
import asyncio, sys
from decimal import Decimal
from packages.core import ledger
from packages.core.config import get_settings
from packages.core.db_pool import create_pool
from services.admin import keno_queries

async def main() -> None:
    pool = await create_pool(dsn=get_settings().database_url, min_size=1, max_size=2)
    try:
        result = await keno_queries.deposit_to_reserve_admin(
            pool, admin_id=int(sys.argv[1]), amount=Decimal("30000.00"),
            reason="Stage 1 Keno prize reserve funding, confirmed by the operator",
            request_id="stage1-reserve-funding-2026-09",
        )
        async with pool.acquire() as conn:
            house_float = await ledger.get_or_create_account(conn, None, "house_float")
            print(result, "house_float:", await ledger.balance(conn, house_float.id))
    finally:
        await pool.close()

asyncio.run(main())
```

## Deploy record: Step 4, 2026-10-01 07:38 UTC (`2aa504a`)

The operator authorized it on 2026-10-01 ("You can deploy now"). The server
became reachable from the dev machine at 06:45 UTC.

- **What went out:** `a7603c5..2aa504a`, everything listed under "What ships"
  above. No migration.
- **Verified before deploying:**
  - Pre-deploy review recorded in `docs/PROJECT_STATE.md`.
  - mypy clean.
  - On GitHub CI (on `3d559f9`, the same code apart from a chaos test and
    docs): 1,876 passed, 3 xfailed; the image built.
  - CI's chaos step watched a real Redis restart. The engine paused its
    calls, confirmed it still owned the room, and settled normally; only the
    test's old refund-only assertion failed, and it was updated in `2aa504a`.
  - On `2aa504a` itself, the only failure was the known timing flake
    `test_claim_rejected_on_one_line_then_accepted_once_a_second_line_completes`.
- **Pre-flight:**
  - Production at `a7603c5`, alembic `b5d9e3a1c7f2`.
  - 0 real players' cards in open Bingo rounds; 0 pending Keno tickets.
  - **Telebirr SMS deposits still enabled (since 2026-09-22)**, although the
    operator meant to switch them off on 2026-09-29. Not changed by this
    deploy; it's for the operator.
- **Backup and rollback image:** backup
  `~/backups/jobingo-20261001T073818Z.dump`; image tagged
  `jobingo:rollback-a7603c5`.
- **Build and restart:** image `582a9eaaffa0`; all nine app containers
  restarted.
- **Verified after the restart:**
  - alembic `b5d9e3a1c7f2`; Keno `false|true` (off, allowlist on).
  - All 25 code checks found the fix in its container.
  - `/healthz` 200, all nine containers up, 0 errors in their logs.
  - New rounds since the restart: Bingo 2, Keno 4.
  - Reconcile: `ledger_reconciliation_ok`.
- **Six minutes later:** 0 errors, 0 restarts in all nine, `/healthz` 200.

**Rollback** (no schema change to undo):
```
docker tag jobingo:rollback-a7603c5 jobingo:latest
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps gateway admin payments bot sms engine-worker payout-worker simulated-players-worker keno-worker
git checkout --detach a7603c5
```
The server's checkout is detached at `2aa504a`.
