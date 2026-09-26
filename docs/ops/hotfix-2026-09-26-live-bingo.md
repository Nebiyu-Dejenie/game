# Hotfix runbook: live Bingo fixes (2026-09-26)

**Status: awaiting operator approval. Nothing is deployed.** Written for the
operator to approve and for whoever runs it. Operator's instruction: these
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
