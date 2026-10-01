# Project State

The one page to read first. It says where the project stands today, what's
safe to change, what's waiting on whom, and where the detail lives. Every
other document goes deeper on one topic; this one links to them.

**Last updated:** 2026-10-01 · **Production:** `2aa504a` (deployed 2026-10-01 07:38 UTC, the Step 1 release) ·
**Main:** a few commits ahead (fixes for the next deploy) ·
**Alembic head:** `b5d9e3a1c7f2` (production and main agree)

## Contents

1. [How to keep this document true](#how-to-keep-this-document-true)
2. [Current Status](#current-status)
3. [Standing Rules](#standing-rules)
4. [Keno Launch Plan](#keno-launch-plan)
5. [Decisions Needed](#decisions-needed)
6. [Architecture](#architecture)
7. [Environments](#environments)
8. [Completed](#completed)
9. [In Progress](#in-progress)
10. [Known Bugs](#known-bugs)
11. [Known Risks](#known-risks)
12. [Technical Debt](#technical-debt)
13. [Important Decisions](#important-decisions)
14. [Game Rules](#game-rules)
15. [Money Model](#money-model)
16. [Database State](#database-state)
17. [API State](#api-state)
18. [Integrations](#integrations)
19. [Security](#security)
20. [Operations](#operations)
21. [Testing Status](#testing-status)
22. [Documentation Health](#documentation-health)
23. [Future Ideas](#future-ideas)
24. [Deferred Ideas](#deferred-ideas)
25. [Open Questions](#open-questions)
26. [Recommended Next Work](#recommended-next-work)
27. [Document Map](#document-map)
28. [Glossary](#glossary)
29. [Change Log](#change-log)

---

## How to keep this document true

This file is a snapshot, so it goes stale unless it's updated at the moments
the state changes. Update it in the same commit as the change when you:

| Event | Update these sections |
|---|---|
| Deploy to production | Current Status, Keno Launch Plan, Completed, the header line |
| Operator makes or changes a decision | Decisions Needed, Important Decisions (and DECISIONS.md) |
| Add a migration | Database State, the header line (`tests/unit/test_project_state_doc.py` fails until you do) |
| Add or remove a service | Architecture (the same test checks the service list) |
| Verify, fix or find an audit finding | Known Bugs (and `audit/platform-audit-2026-09.md`) |
| Start or finish a piece of work | In Progress, Completed, Recommended Next Work |

Rules for editing it:
- **Facts only, with a source.** Link the file, commit or doc that shows it.
  If something can't be confirmed, write "unconfirmed" rather than a guess.
- **Snapshot, not history.** Replace a stale line; don't append "update:" to
  it. History belongs in git, DECISIONS.md and the Change Log at the bottom.
- **Bump "Last updated"** and add one line to the Change Log.

---

## Current Status

| | State | Source |
|---|---|---|
| Brand / domain | Zemen Game at `arada.click` (Mini App, bot, admin, finance, agent portal, SMS) | [PRODUCTION_DOMAIN_AND_CLOUDFLARE.md](PRODUCTION_DOMAIN_AND_CLOUDFLARE.md), README |
| Production commit | `2aa504a`, alembic `b5d9e3a1c7f2`, deployed 2026-10-01 07:38 UTC; rollback image `jobingo:rollback-a7603c5` | [ops/hotfix-2026-09-26-live-bingo.md](ops/hotfix-2026-09-26-live-bingo.md) "Deploy record: Step 4" |
| Bingo | **Live with real money** | same |
| Keno | **Deployed but off** (`keno_enabled = false`), beta allowlist on, Tier 1. **Reserve 30,000.00** (funded 2026-10-01 08:12 UTC), so the per-round ceiling is 3,000.00 | runbook "Stage 1 reserve funding" |
| Telebirr SMS deposits | **Still enabled** (`payment_provider_availability`: `true` since 2026-09-22, read 2026-10-01). The operator meant to switch them off on 2026-09-29 because of the forged-SMS hole (audit #9). See D0. | deploy pre-flight 2026-10-01 |
| Monitoring | **No Prometheus or Alertmanager in production.** No alert has ever fired there. Config is ready but not started (profile `monitoring`). | `deploy/docker-compose.prod.yml` |
| Step 1 release | **Deployed 2026-10-01 07:38 UTC** (`2aa504a`); every post-deploy check passed, and there were no errors or restarts after 6 minutes | runbook "Deploy record: Step 4" |
| Git | `origin` = `github.com/Nebiyu-Dejenie/game`, in sync with local `main` (pushed 2026-10-01). The server's checkout still points at the dead `igame` remote, so deploys travel as a git bundle. The repo has no self-hosted runner, so CD can't deploy. | `gh api .../actions/runners` |
| CI | Unbroken on 2026-10-01 (it had failed on every run since 2026-09-26, waiting for a container name that no longer exists). mypy, the full suite and the image build now pass on GitHub. | `.github/workflows/ci.yml` |
| Audit | 115 findings. Every critical and high one is verified; see [Known Bugs](#known-bugs) | [audit/platform-audit-2026-09.md](audit/platform-audit-2026-09.md) |
| Ledger oddity | `house_float` reads −31,000.00 after the reserve funding; the −1,000.00 it had before came from ledger transaction #1, still an open question | [Open Questions](#open-questions) |

---

## Standing Rules

These are the operator's rules. Treat them as hard gates, not preferences.

1. **No real money moves without explicit confirmation of the exact
   transaction.** That covers funding or withdrawing the Keno reserve,
   adjustments and grants. Show accounts, amounts and resulting balances;
   the operator confirms; then post; then verify.
2. **`keno_enabled` is flipped by the operator, never by anyone else.**
3. **No manual SQL against a shared database** (production, or anything
   shared) without first showing the exact statement and its target.
   Test-fixture SQL in test files, and application functions such as
   `ledger.post()` on a throwaway test database, are fine.
4. **Never fabricate results.** Quote real output. If a step was skipped or
   failed, say so.
5. **Reproduce first, then fix, with a test that fails on the old code and
   passes on the new one.** Then deploy.
6. **Small, reviewable commits** with a detailed message giving the reason,
   pushed to `origin`. Every commit ends with the co-author trailer.
7. **Deploys:** present the plan, get approval, deploy between Bingo rounds
   (restarting the engine refunds any round in flight), verify, record it in
   the runbook.
8. **Policy changes are the operator's.** Limits, game rules and what players
   are told aren't changed to fix a bug. Record a strict `xfail` test and
   ask.

---

## Keno Launch Plan

The operator's four steps. Status as of the header date.

| Step | What | Status |
|---|---|---|
| 1 | Ship the Keno fixes and every verified audit fix, then deploy | **Done 2026-10-01** (`2aa504a`) |
| 2 | Fund the prize reserve: 30,000.00 ETB, `house_float` → `keno_reserve` (`keno_reserve_deposit`) | **Done 2026-10-01 08:12 UTC**, after the operator confirmed. Ledger transaction #4, audit row #7; reserve 30,000.00, house_float −31,000.00, Tier 1, ceiling 3,000.00, reconcile OK |
| 3 | Add internal testers to the beta allowlist | **Next.** Needs each tester's Telegram username or numeric id; they must have opened the bot once. Added with the audited allowlist function under admin id 1 |
| 4 | Flip `keno_enabled` | **The operator does this themselves** |

What limits Keno at a 30,000 reserve (Tier 1, `max_round_exposure_pct` 10%, so
the ceiling is 3,000): independent picks never approach the ceiling (net
exposure peaks at 292 to 1,910). Identical picks aren't limited at all; see
[Known Risks](#known-risks), R1.

---

## Decisions Needed

Waiting on the operator, roughly in the order they unblock work.

| # | Decision | Recommendation | Blocks |
|---|---|---|---|
| **D0** | **Telebirr SMS deposits are still enabled in production** (read 2026-10-01), with the forged-SMS hole (#9) | Switch them off now: admin console → Payments → Provider availability → Telebirr SMS deposits off | Player money safety |
| D1 | A network path to the server (the dev PC is on another network) | Rejoin the server's LAN, or add Tailscale or Cloudflare Access SSH | Every deploy |
| D2 | OK to push to `origin` (the auto-mode check blocked it) | Yes | The remote falling behind local work |
| D3 | Alerting: an ops Telegram chat id, a token for a separate ops bot, a healthchecks.io URL | Provide all three | Monitoring |
| D4 | Identical-picks exposure fix (it changes the risk model) | Approve before any opening wider than a few testers | Keno Stage 2 |
| D5 | #25: per-IP Keno ticket limit shared behind carrier NAT | Remove it, or raise it well above the per-player 20/min (e.g. 300/min) | Fair ticket limits |
| D6 | #57: two 5/5 jackpot winners in one round | Equal split per ticket, leftover cent stays in the pool | Jackpot correctness |
| D7 | #39: a full round stops everyone else's autoplay | Skip that round instead of stopping (this reverses a 2026-09-25 rule) | Autoplay UX |
| D8 | #30: abandoned Chapa checkouts never expire | Needs Chapa's expiry behaviour first | Deposit cap accuracy |
| D9 | Telebirr redemption design | Read it and approve controls E1, E2 and R1 before re-enabling the rail | Telebirr |
| D10 | VPS migration and off-box backups | Decide sizing and provider | Disaster recovery |
| D11 | Simulated players share real pots and aren't disclosed | Legal review | Compliance |
| D12 | `PHONE_ENCRYPTION_KEY` in git history (LB-D3) | Rotate the key, or rewrite history | Security |
| D13 | `house_float` −1,000.00 from transaction #1 | Explain or correct it with a reversing entry | Clean books |
| D14 | **Who funds the jackpot slice when a Keno ticket is refunded?** See the trace below | Decide A or B; until then A (today's behaviour) stays, pinned by a test | Accurate jackpot accounting |

**D14, traced on 2026-10-01.** Nothing has been changed; the code's comments now
describe it accurately.

- **What happens today (A).** At placement, a 20.00 stake is split: 19.70 to `keno_reserve`, 0.30 (1.5%) to `keno_jackpot_pool` (`packages/core/keno_tickets.py`). A refund on a failed round pays the player the full 20.00, all of it from `keno_reserve`, and leaves the 0.30 in the pool (`services/engine/keno_round_engine.py`, `_refund_one_ticket`). Net: the player is whole, the reserve is down 0.30, the pool is up 0.30. Pinned by `test_a_refund_returns_the_full_stake_from_the_reserve_and_leaves_the_jackpot_slice_in_the_pool`.
- **What the repository says.**
  - `keno.md` 5.3: a stuck round refunds every ticket and "must never silently eat user money". Both options satisfy this.
  - `keno.md` 8.3: the jackpot is "player-funded … zero operator liability", "pays only from the pool and can never exceed the pool balance". Under A, the operator's reserve funds the slice of every refunded ticket, so the pool is no longer purely player-funded.
  - The original code (6fcfaba, 2026-09-17) had a docstring saying the refund reverses the split, a comment saying "the jackpot diversion is never refunded", and no rationale in the commit message.
  - No decision in DECISIONS.md covers it.
- **Option B (reverse the split).** Take the 0.30 back from the pool. The catch: `_pay_jackpot` pays out the *whole* pool, including slices from the next round's tickets, whose betting overlaps settlement. A refund right after a jackpot could therefore drive the pool negative. B needs a rule for that, for example take back at most what the pool holds and let the reserve cover the rest.
- **Size.** Refunds only happen when a round fails before its draw, which is rare. The cost is 1.5% of the refunded stakes; a failed round with 10,000 ETB staked costs the reserve 150.

---

## Architecture

One Python 3.12 codebase, one Docker image (`jobingo:latest`), nine app
services, Postgres 15 and Redis 7. Cloudflare Tunnel is the only way in.

```mermaid
flowchart LR
  P[Players: Telegram + Mini App] --> CF[Cloudflare Tunnel]
  A[Admins / finance / agents] --> CF
  CF -->|arada.click| GW[gateway :8000]
  CF -->|arada.click/webhook| BOT[bot :8003]
  CF -->|admin. / finance.| ADM[admin :8001]
  CF -->|payments. / agent.| PAY[payments :8002]
  CF -->|sms.| SMS[sms :8006]
  GW <--> R[(Redis 7)]
  ENG[engine-worker :8004] <--> R
  KENO[keno-worker :8008] <--> R
  PW[payout-worker :8005] <--> R
  BOT <--> R
  SIM[simulated-players-worker :8007] <--> R
  GW --> PG[(Postgres 15)]
  ENG --> PG
  KENO --> PG
  PW --> PG
  ADM --> PG
  PAY --> PG
  SMS --> PG
  BOT --> PG
  PW -->|payouts| CHAPA[Chapa API]
  PAY <-->|webhooks| CHAPA
```

| Service | Entrypoint | Port | Does |
|---|---|---|---|
| `postgres` | `postgres:15` (`jobingo-postgres`) | – | Database, WAL-archived to `backups/wal_archive` |
| `redis` | `redis:7` (`jobingo-redis`) | – | Streams, pub/sub, locks, sessions, rate limits |
| `migrate` | `alembic -c migrations/alembic.ini upgrade head` | – | One-shot; every app service waits for it |
| `gateway` | `uvicorn services.gateway.app:app` | 8000 | Mini App files, player REST, `/ws` |
| `admin` | `uvicorn services.admin.app:app` | 8001 | Admin and finance API, `/console` UI |
| `payments` | `uvicorn services.payments.app:app` | 8002 | Chapa webhook, Telebirr ingest, agent portal |
| `bot` | `python -m services.bot.app` | 8003 | Telegram webhook; also runs the notification relay, campaign worker, bot content sync and command registry |
| `sms` | `uvicorn services.sms.app:app` | 8006 | SMS Control Plane, a separate bulk-SMS product |
| `engine-worker` | `python -m services.engine.worker` | 8004 | Bingo round engines, one per room, each behind a Redis room lock |
| `payout-worker` | `python -m services.payments.payout_worker` | 8005 | Sends payouts; runs 7 periodic sweeps (deposit polling, stuck payouts, provider and Telebirr reconciliation, bonus wagering, ledger reconciliation, degraded devices) |
| `simulated-players-worker` | `python -m services.engine.simulated_players_worker` | 8007 | Admin-controlled bot players; off until enabled |
| `keno-worker` | `python -m services.engine.keno_worker` | 8008 | The single global Keno round cycle, behind `keno:round:lock` |
| `reconcile-job` | `python -m packages.core.reconcile_job` | – | One-shot ledger check (profile `reconcile`; not scheduled) |
| `cloudflared` | `cloudflare/cloudflared` | – | Ingress |
| `prometheus` | `prom/prometheus:v2.55.1` | 127.0.0.1:9090 | Profile `monitoring`, **not started** |
| `alertmanager` | `prom/alertmanager:v0.27.0` | 127.0.0.1:9093 | Profile `monitoring`, **not started** |

Shared code lives in `packages/core`. The key modules:
- **Ledger:** `ledger.py`, the only way money moves.
- **Games:** `bingo.py` and `keno.py` (pure game math); `keno_tickets.py`, `keno_autoplay.py`, `keno_exposure.py`, `keno_tier_automation.py` and `keno_config.py`.
- **Player money:** `bonuses.py`, `referrals.py` and `responsible_gaming.py`.
- **Infrastructure:** `notifications.py` (producer for `bot_notifications`), `rate_limit.py` (Redis token buckets), `platform_settings.py` (limits editable at runtime), `config.py`, `metrics.py`.
- **Other products:** `campaigns.py` (Notification Center) and `sms/` (SMS product).

---

## Environments

| Environment | Where | Notes |
|---|---|---|
| **Production (current)** | `zemen-game-server`, 192.168.1.115, checkout `~/apps/igame`, `deploy/docker-compose.prod.yml` | Reachable only from its LAN. The containerized Cloudflare tunnel serves `arada.click`. |
| Older deployment | `arada.fun` | Host-level cloudflared forwarding to an untracked Traefik stack (DECISIONS 2026-09-01 and 09-14). Current status: unconfirmed. |
| Dev machine | WSL | Dev DB on 5433 is on an old schema: **don't run tests against it**. `~/AradaBingo` is archived and now uses its own database (`aradabingo_dev`). |
| Test databases | Throwaway containers | Postgres 15 on 5434 and Redis 7 on 6381 (more on 5435–5437 / 6382–6384 for parallel work). See [Testing Status](#testing-status). |

---

## Completed

The major milestones. Details in git and the linked docs.

- **Platform (Aug–Sep 2026):**
  - Bingo engine, Mini App, bot and admin console; the double-entry ledger with append-only triggers.
  - Chapa deposits and payouts; manual payments with two-person approval at 2,000 ETB or more.
  - Telebirr SMS ingestion; responsible gaming; bonuses and referrals.
  - Notification Center; SMS Control Plane; simulated players.
  - WAL archiving and point-in-time recovery; RBAC with 4 roles.
- **Keno:** a full product. Commit-reveal draws, paytables with an RTP guardrail, risk tiers with automation and a circuit breaker, autoplay and multi-race, a jackpot, and admin screens. Deployed off, 2026-09-29.
- **Production deploys on 2026-09-29:**
  - The live Bingo hotfix (`b226a33`): a double refund on drop, an un-voided round paying twice, and join into a voided round.
  - All of main (`28f4bac`, migration `b5d9e3a1c7f2`).
  - Three more live fixes (`a7603c5`): the gateway subscription surviving Redis drops, emergency-stop messages, and a manual bonus grant that paid twice.
- **Audit, criticals:** #1, #2, #4 to #8 fixed and deployed; #9 is behind a disabled rail and a design.
- **Audit, highs:** all verified. 17 are fixed on main awaiting deploy (listed in the runbook); 6 were already deployed.
- **Payout safety:** an unknown outcome stays `processing` until an admin reconciles it, and a payout is never re-sent.
- **Monitoring config** is written, and the `RoundVoided` alert no longer fires on empty rooms.

---

## In Progress

| Work | State | Next action |
|---|---|---|
| Step 1 release | **Deployed 2026-10-01** (`2aa504a`) | Watch production; the next deploy carries #81 and later fixes |
| Keno launch Steps 2–4 | Waiting on Step 1 | See [Keno Launch Plan](#keno-launch-plan) |
| Audit medium/low verification | 66 not yet verified | Money paths first; see [Recommended Next Work](#recommended-next-work) |
| Lock-order sweep | Done for Keno and payments; admin, bot and gateway still to do | |

**Step 1 pre-deploy review (2026-10-01):**
- **Scope:** `a7603c5..main`. Every commit from the Keno fixes onward; 26 code and config files.
- **Migrations:** none, so alembic stays `b5d9e3a1c7f2`.
- **Build inputs** (Dockerfile, requirements.lock, pyproject.toml): unchanged since the running image. The image builds on GitHub CI.
- **Debug leftovers:** the only hits for print, breakpoint, console.log, localhost or a credential string were the deliberate loopback port bindings for Prometheus and Alertmanager.
- **Money and game paths:** each was reviewed and reproduced when it was made (see each commit message). One regression was found by CI's chaos test and fixed: the engine now pauses calls during a Redis outage, instead of playing on.
- **Not changed:** infrastructure. The monitoring profile stays off until D3.

---

## Known Bugs

Tracked in [audit/platform-audit-2026-09.md](audit/platform-audit-2026-09.md)
(115 findings; each has an id, file, trigger, impact and status).

| Severity | Total | Fixed and deployed | Fixed, deploy pending | Open or partly fixed | Not yet verified |
|---|---|---|---|---|---|
| Critical | 9 | 7 | 0 | 1 (#9) | 1 (#3) |
| High | 26 | 23 | 0 | 3 (#25, #32, #33) | 0 |
| Medium | 46 | 10 (+2 already fixed) | 1 (#81) | 4 (#39, #41, #55, #57) | 29 |
| Low | 34 | 1 | 0 | 1 (#86) | 32 |

Open items that matter most:
- **Telebirr SMS rail (#3, #9, #32, #33).** Anyone can mint evidence by texting a fake SMS. Whoever submits a reference first gets the deposit. `1,500.00` is parsed as 1. One transfer could be credited on two rails. **The rail is off**, and the fixes are designed in [payments/telebirr-evidence-and-redemption-design.md](payments/telebirr-evidence-and-redemption-design.md).
- **#25, #39, #57:** confirmed, waiting on the operator's rule ([Decisions Needed](#decisions-needed)). #25 and #57 have strict `xfail` tests.
- **#41 / #55 (partly):** the stop-loss is safe, because it's enforced from tickets at placement. After a hard crash, `stop_on_win` and the session summary can still miss one round's result.
- **Not yet in the audit:**
  - A Keno refund pays the full stake from `keno_reserve`, and the 1.5% jackpot slice stays in the pool. The player is made whole; the reserve funds the slice. Traced, documented and pinned by a test; the rule is decision D14.

---

## Known Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | **Correlated Keno exposure.** The round check assumes independent tickets, so many identical tickets aren't limited. At a 30,000 reserve, one all-hit round of identical 1-pick tickets empties the reserve at 1,308 / 654 / 262 tickets (stakes 10 / 20 / 50); the correct 3,000 cap would be 131 / 66 / 27. A 1-pick all-hit is 25%. | Low with a few testers; high once open | Keep Stage 1 to a small allowlist; fix before widening (D4) |
| R2 | **No production alerting.** A dead worker, stuck round or ledger mismatch pages nobody. | Certain until fixed / high | Start the monitoring profile (D3) |
| R3 | **Single server, local backups only.** Backups sit in `~/backups` on the same machine. | Low / critical | Off-box backups, VPS plan (D10) |
| R4 | **Deploy path depends on the dev machine's LAN.** It was down from 2026-09-29 evening to 2026-10-01 06:45 UTC. | Recurring / blocks fixes | D1 |
| R5 | **Telebirr SMS deposits still on** with the forgery hole (#9). | Exploitable now / high | D0 |
| R6 | **Simulated players in real pots, undisclosed.** | Legal | D11 |
| R7 | **Secrets in git history** (`PHONE_ENCRYPTION_KEY`). | Low / high | D12 |
| R8 | **App ports published on the server's LAN,** and the gateway trusts `CF-Connecting-IP` from anyone who can reach port 8000. | Low (LAN only) | Bind to the tunnel network only |
| R9 | **Shared-state test suite.** One test can starve or poison later ones, e.g. the 55 leaked connections found on 2026-09-30. | Medium / slows work | [KNOWN_TEST_FLAKES.md](KNOWN_TEST_FLAKES.md) |
| R10 | **Licensing and compliance for real-money Keno** are still open. | – | [keno/12-compliance.md](keno/12-compliance.md) |

---

## Technical Debt

- **Very large files:**
  - `services/admin/app.py` (2,771 lines), `services/admin/queries.py` (2,720), `services/engine/round_engine.py` (1,484) and `services/admin/keno_queries.py` (1,324).
  - Split the admin ones by domain (payments, keno, users, content).
  - The Mini App's `web/miniapp/js/app.v6.js` is 2,334 lines.
- **Duplication:**
  - The payment-reference SQL is copied in 4 payment modules.
  - The Redis lock Lua scripts are identical in `room_lock.py` and `keno_lock.py`.
  - Redis session logic exists in both `admin/auth.py` and `payments/agent_auth.py`.
  - The admin role list is in both the migration CHECK and `rbac.py`.
- **Unscheduled jobs:**
  - `reconcile-job` and the WAL prune are "deploy-time steps" with no cron in this deployment.
  - The hourly ledger sweep inside the payout worker is the only automatic reconciliation.
- **Payments:**
  - No Chapa payout webhook or status poll, so `processing` payouts need manual reconciliation.
  - No bulk Chapa settlement-report reconciliation.
  - SantimPay and ArifPay have config keys but no adapters.
  - `services/wallet` is an empty package.
- **Unused ledger kinds:** `commission` and `keno_jackpot_contribution`.
- **i18n:** Oromo (`om`) and Tigrinya (`ti`) are stubs that fall back to English or Amharic.
- **Deploy tooling:**
  - The server's checkout points at a dead remote.
  - The CD workflow (self-hosted runner) isn't how production is deployed today; deploys are manual bundles.
- **Tests:**
  - The test database is never truncated, and Keno's global singletons (round lock, reserve, betting-open index) are shared across tests.
- **Stale docstrings:**
  - `services/gateway/queries.py:31` ("bot not yet built").
  - The Telebirr evidence migration ("no reader/writer yet").

---

## Important Decisions

[DECISIONS.md](../DECISIONS.md) is the full log (184 dated entries,
2026-08-22 to 09-27). These are the ones that constrain future work.

| Date | Decision | Why |
|---|---|---|
| 08-22 | The spec pack in `idea.md` is authoritative. Stack: Python 3.12, FastAPI, aiogram 3, Postgres 15, Redis 7 | The only consistent part of the spec |
| 08-24 | SantimPay and ArifPay are not built | API docs unreachable; a guessed webhook signature would be a forgery hole |
| 08-24 | Phone numbers encrypted at rest (AES-GCM plus an HMAC blind index); admin search is exact-match only | Privacy |
| 08-25 | Rate limiting fails closed on a Redis error | Safety over availability |
| 08-26 | CD only after green CI; GHCR plus a self-hosted runner | No path from red CI to production |
| 08-26 | 18+ self-declaration, no hard age verification | The spec asks for a declaration |
| 08-31 | Manual payment rail | Keep money moving when Chapa is down |
| 09-01 | Two-person approval at 2,000 ETB or more; one admin can't give both approvals | Maker-checker |
| 09-01 | Abandoned checkouts counting toward the deposit cap were deliberately not fixed | Both fixes open a double-credit or lost-money path |
| 09-02 | Unique DB and Redis aliases (`jobingo-postgres` / `jobingo-redis`) | Wrong-database incident: bare names resolved to another app's containers |
| 09-03 | Rounds are server-owned and continuous; solo play allowed (`min_players` 1); 432-card pool | Product |
| 09-06 | Emergency single-room stop, with a row-lock guard on voids | A double-payment race |
| 09-07 | The SMS Control Plane is a separate product in this repo | Scope |
| 09-17 | The ledger is append-only by trigger; corrections are reversing posts | Auditability |
| 09-21 | Player wording is "verifiable commit-reveal", never "provably fair" | Accuracy |
| 09-21 | The daily loss cap is combined across Bingo and Keno; autoplay is charged per round | Responsible gaming |
| 09-21 | Keno stays off until spec Parts 7, 14, 15 and 17 are complete | Operator rule |
| 09-25 | Refunded stakes don't count as losses (same-day stakes only) | Operator |
| 09-26 | `origin` moves to `Nebiyu-Dejenie/game`; the `igame` remote is gone | Operator |
| 09-27 | Business configuration lives in the admin console; `keno_enabled` changes only through the kill switch; the 20-from-80 math is locked; responsible-gaming settings can only get stricter | Operator |
| 09-29 | An unknown payout outcome stays `processing`, with an admin reconciliation view; a payout is never re-sent | Operator approved |
| 09-29 | Retention approved: Keno counts 100% toward playthrough; badge-only streaks; notifications on by default with one-tap off; referral reward only after the referee wagers 3× their deposit | Operator approved; build after the Keno launch |
| 09-29 | Bingo parity approved (~7 weeks), starting with the pot-accounting invariant and a simulated-player exposure cap | Operator approved; after the audit closes |
| 09-29 | Telebirr: don't build the redemption fixes until the operator has read the design | Operator |

---

## Game Rules

### Bingo
Sources: `packages/core/bingo.py`, `services/engine/round_engine.py`,
`services/engine/settlement.py`, [BINGO_WINNING_RULES.md](BINGO_WINNING_RULES.md).

- **Round states:** `lobby` → `running` → `done`, or `voided` (refunded).
  `settling` exists in memory only; the DB row stays `running` until `done`.
- **Card pool:** 432 fixed 5×5 cards built from seed `jobingo-card-pool-v1`, with
  B-I-N-G-O columns over 1–75 and a free centre square. The draw is an
  HMAC-SHA256 Fisher-Yates shuffle of 1–75. The seed's hash is published when
  the round is created and the seed is revealed at settlement.
- **Room settings** (defaults):

  | Setting | Default |
  |---|---|
  | stake | required |
  | `house_cut_bps` | 2000 (20%) |
  | `min_players` | 1 (distinct players) |
  | `max_players` | 100 |
  | `lobby_seconds` | 30 |
  | `call_interval_ms` | 4000 |
  | `max_cards_per_player` | 1 (range 1–20) |
  | `min_winning_lines` | 2 (range 1–4) |
  | `win_patterns` | rows, columns, diagonals |

- **Winning:** a card needs at least `min_winning_lines` complete lines. The
  first valid claim opens a **50 ms tie window**; every card claimed inside
  it shares the prize.
  - The derash (prize) is pot × (1 − cut), rounded down.
  - It's split evenly per winning card, each share rounded down. The leftover goes to `house_revenue`.
  - A player with two winning cards gets two shares.
  - Every card a single call completes counts as that call's tie, however slow the database is (#22).
- **Claims:** auto-mark is on by default, and the server claims for auto-mark cards on every call.
  - A manual claim with no complete line locks out that card for the round.
  - A claim with some lines but too few is refused without a lockout.
  - Three false claims block claiming for the rest of that connection.
- **No result:**
  - A lobby with too few players refunds everyone (`lobby_underfilled`).
  - An empty lobby runs anyway and ends exhausted.
  - All 75 numbers called with no winner refunds everyone (`exhausted_no_winner`).
- **Emergency stop** (admin, reason required), in one transaction: refund every entrant, set the room inactive, write the audit record. A row lock makes stop and settlement mutually exclusive ([EMERGENCY_ROOM_STOP.md](EMERGENCY_ROOM_STOP.md)).
- **Simulated players:**
  - Bot accounts playing through the real engine, always on auto-mark.
  - Funded from `house_float` (5,000.00 each); up to 200 on the roster; 1–4 cards per join.
  - They can never withdraw and are blocked from Keno.

### Keno
Sources: `packages/core/keno*.py`, [keno/05-paytable-and-rtp.md](keno/05-paytable-and-rtp.md),
[keno/07-economics-and-bankroll.md](keno/07-economics-and-bankroll.md),
[keno/06-fairness-and-verification.md](keno/06-fairness-and-verification.md).

- **Game:** 20 numbers drawn from 80. Players pick 1–10, capped by tier.
- **Timing:** a 45 s cycle of 25 s betting, 12 s draw and 8 s result. One global round at a time.
- **Paytables:** `low_variance` (Tiers 1–2, picks 1–6) and `standard` (Tiers 3–4, picks 1–10), both tuned to 82% RTP. A paytable outside 75–97% RTP can't be activated.
- **Risk tiers** (a tier sets max picks, top multiplier, stakes, profile, max win and exposure):

  | Tier | Min reserve | Stakes | Max win / ticket | Round exposure |
  |---|---|---|---|---|
  | 1 | 0 | 10 / 20 / 50 | 800 | 10% of reserve |
  | 2 | 200,000 | 10 / 20 / 50 | 3,000 | 10% |
  | 3 | 1,000,000 | + 100 | 50,000 | 10% |
  | 4 | 5,000,000 | + 200 | 250,000 | 10% |

  - Promotion needs the reserve above the next threshold for 7 days straight. Demotion is immediate.
  - **Circuit breaker:** if the last 24 h of actual payouts exceed 3.0× expected, the tier drops one level. After a trip, only fresh evidence counts (#50).
- **Per-round exposure:** expected payout + 3.09 × √variance, net of the stakes already in the reserve, must stay under reserve × exposure %. Tickets are assumed independent (see R1).
- **Per player:** at most 3 tickets per round, and at most a 20% share of the round's capacity.
- **Jackpot:**
  - 1.5% of every stake goes to `keno_jackpot_pool`.
  - Paid when a 5-pick ticket hits 5/5, from the pool only, on top of the normal payout.
  - Only the pass that settled the ticket pays it (#56). The multi-winner rule is pending (D6).
- **Autoplay:**
  - One mechanism covers autoplay and multi-race. Options: `rounds_total` (at most 100), `stop_on_win_amount`, `stop_on_loss_amount`; at least one is required.
  - One active session per player. The stake is charged each round.
  - The round count is kept in the ticket's own transaction (#40). The stop-loss is enforced from tickets, counting unsettled ones as lost.
- **Fairness:**
  - The server seed (32 bytes) is hashed and published when the round is created.
  - The public seed is `round_id:close_epoch:sha256(sorted ticket ids)`.
  - The seed is revealed once the round is finished.
- **Access:** `keno_enabled` is the kill switch (superadmin only, default off). `beta_restricted` limits play to the allowlist.

### Responsible gaming
Source: `packages/core/responsible_gaming.py`.
- Daily deposit and loss caps (none by default). Lowering one applies at once; raising one waits 24 h.
- The loss cap covers Bingo and Keno together, by Ethiopian calendar day.
- Self-exclusion for at least 180 days, which the player can't undo. Cool-off of 24 h, 7 d or 30 d.
- 18+ self-declaration. Reality-check reminders at 60, 120 and 180 minutes.
- Known gaps: no platform-wide maximum cap, no real age verification, no helpline links.

### Bonuses and referrals
Sources: `packages/core/bonuses.py`, `referrals.py`.
- **Welcome bonus:** set by admin rule, on the first qualifying deposit. Wagering defaults to 3×, with no expiry by default.
- **Playthrough:** today only real-cash Bingo stakes count, minus refunds. Keno counting is approved but not built.
- **Referral reward:** once per referee, on their qualifying deposit. Blocked for self-referral and for accounts sharing a payout account.

---

## Money Model

Source: `packages/core/ledger.py`.

- **Double entry:** every transaction's entries sum to zero, enforced by a deferred trigger. Rows are append-only; corrections are reversing posts.
- **`ledger.post()`:**
  - One global idempotency-key namespace. A replay of the same operation returns the original; a mismatch raises `IdempotencyKeyConflict`.
  - Balance rows are locked in sorted account order.
- **Can't go negative:** `user_cash`, `user_bonus` and `user_locked`. System accounts can.
- **Lock order convention:** the player's advisory lock → the users row (`FOR NO KEY UPDATE`) → the round row → balance rows.

| Account | Kind |
|---|---|
| `user_cash`, `user_bonus`, `user_locked` | Per player |
| `house_float` | Operator's funding float; counterparty for adjustments, the reserve and simulated players |
| `house_revenue` | Bingo house cut and rounding |
| `pot_escrow` | Bingo stakes while a round runs |
| `provider_settlement` | Money in and out through payment providers |
| `promo_expense` | Bonus grants |
| `keno_reserve` | Keno prize reserve; pays Keno wins |
| `keno_jackpot_pool` | Keno jackpot |

**Flows:**
- **Bingo:**
  - Stake: `user_cash` → `pot_escrow`.
  - Settlement: `pot_escrow` → winners plus `house_revenue`.
  - Refund reverses the stake.
- **Keno:**
  - Stake: `user_cash` → `keno_reserve` plus `keno_jackpot_pool` (1.5%).
  - Win: `keno_reserve` → `user_cash`.
  - Refund: the full stake from `keno_reserve`; the jackpot slice stays in the pool (D14).
- **Reserve:** `house_float` ↔ `keno_reserve`, one transfer per `request_id`.
- **Deposits** (Chapa, manual, Telebirr): `provider_settlement` → `user_cash`.
- **Withdrawals:**
  - Request: `user_cash` → `user_locked`, status `approved` or `review`.
  - The worker marks it `processing` and sends it to Chapa exactly once.
  - Success: `user_locked` → `provider_settlement`. Failure refunds it.
  - An unknown outcome stays `processing` until an admin resolves it.
- **Bonuses:** grant `promo_expense` → `user_bonus`; conversion `user_bonus` → `user_cash`.
- **Reconciliation:**
  - An hourly ledger sweep runs in the payout worker.
  - `reconcile-job` is a one-shot nightly check (not scheduled).
  - The test suite asserts the ledger reconciles at the end of every run.

---

## Database State

- **Migrations:** 47, one straight chain from `81d041ff4513` (ledger foundation) to **`b5d9e3a1c7f2`** (admin configuration management). Production is at the head.
- **Tables by domain:**
  - **Identity:** `users`, `responsible_gaming_limits`.
  - **Ledger:** `accounts`, `ledger_transactions`, `ledger_entries`, `account_balances`.
  - **Bingo:** `cards`, `rooms`, `rounds`, `round_entries`, `round_winners`, `claim_attempts`.
  - **Keno:** `keno_configs`, `keno_paytables`, `keno_risk_tiers`, `keno_tier_state`, `keno_tier_changes`, `keno_rounds`, `keno_round_events`, `keno_tickets`, `keno_ticket_selections`, `keno_jackpot_pool`, `keno_autoplay_sessions`, `keno_beta_allowlist`.
  - **Payments:** `payment_methods`, `payments`, `payment_events`, `manual_payment_destinations`, `payment_provider_availability`, `payment_evidence`, `payment_agents`, `ingestion_devices`.
  - **Bonuses:** `bonus_rules`, `bonuses`.
  - **Admin:** `admin_users`, `admin_audit_log`. Sessions live in Redis and RBAC in code.
  - **Content:** `notification_templates`, `notification_campaigns`, `notification_deliveries`, `bot_i18n_overrides`, `bot_commands`, `platform_announcement`, `platform_settings`.
  - **SMS:** `sms_tenants`, `sms_contacts`, `sms_suppressions`, `sms_templates`, `sms_campaigns`, `sms_campaign_events`, `sms_delivery_nodes`, `sms_messages`, `sms_delivery_attempts`, `sms_import_jobs`, `sms_import_rows`.
  - **Simulated players:** `simulated_players`, `simulated_players_settings`.
- **Invariants the database enforces:**
  - Entries sum to zero; non-negative player balances.
  - Append-only ledger and audit log.
  - Immutable Keno draws.
  - One `betting_open` Keno round; one active autoplay session per player; one referral bonus per referee.
  - Unique idempotency keys (ledger, Keno tickets, SMS); unique `payments.our_ref`; unique `(provider, event_id)` payment events.
- **Redis:**

  | Key or stream | Use |
  |---|---|
  | `room:{id}:cmds` / `cmdreply:{id}` | Gateway → engine commands and their replies |
  | `room:{id}`, `keno:live`, `user:{id}` | Pub/sub the gateway relays to players |
  | `payouts` (group `payout-workers`) | Payout queue |
  | `bot_notifications` (group `bot-notification-workers`, dead letters `bot_notifications:dead`) | Notification queue |
  | `rl:{scope}:{key}` | Rate limits |
  | `room:lock:{id}`, `keno:round:lock` | Engine locks, 15 s TTL |
  | `admin_session:*` | Admin sessions, 8 h |
  | `agent_session:*` | Agent sessions |
  | `seen:tg:*` | Bot dedup |

---

## API State

- **Gateway REST** (`services/gateway/app.py`). Auth header: `Authorization: tma <initData>`.
  - Account and history: `GET /api/me`, `GET /api/history`, `GET /api/rounds/{id}/fairness`, `GET /api/limits`, `GET /api/announcement`, `GET /api/invite`.
  - Payments: `GET /api/payment-methods`, `GET /api/manual-payment-destinations`, `POST /api/deposit`, `POST /api/deposit/manual`, `POST /api/wallet/deposits/telebirr/redeem`, `POST /api/withdraw`.
  - Keno: `GET /api/keno/state`, `POST`/`GET /api/keno/tickets`, `POST`/`GET`/`DELETE /api/keno/autoplay`, `GET /api/keno/stats`, `GET /api/keno/rounds/recent`, `GET /api/keno/rounds/hot-cold` (lookback 1–200), `GET /api/keno/rounds/{id}`.
  - Also `/healthz`, `/metrics`, and the static Mini App at `/`.
- **Gateway WebSocket** `/ws`:
  - The first frame must be `{t: "auth", init_data}`.
  - Client frames: `ping`, `rooms`, `join`, `leave`, `take_card`, `drop_card`, `set_auto`, `claim`, `mark` (ignored).
  - Engine commands only go out for rooms that exist, with at most 100 waiting per process and 3 per player.
- **Payments:** `POST /webhooks/chapa`, `POST /internal/telebirr/ingest`, and the agent portal (`/agent-portal/login`, `logout`, `me`, `submissions`).
- **Admin:** 133 routes and the `/console` UI, grouped:

  | Area | Routes |
  |---|---|
  | Payments and withdrawals | ~32 |
  | Keno (configs, kill switch, paytables, tiers, allowlist, reserve, simulator) | 23 |
  | Notifications | 15 |
  | Simulated players | 11 |
  | Rounds and rooms (void, emergency stop) | 9 |
  | Bonuses | 8 |
  | Users | 6 |
  | Admin users | 5 |
  | Telegram commands | 5 |
  | Reports and risk | 5 |
  | Settings, audit log, dashboard, search, health, auth | the rest |

- **Bot:** `/start` (with `ref_` deep links), `/play`, `/balance`, `/history`, `/invite`, `/rules`, `/support`, `/deposit`, `/withdraw`, `/limits`, `/language`, `/change_username`, `/portal` (agents). It also handles receipts, shared contacts and pasted Telebirr SMS.
- **SMS:** 38 routes. Campaigns, CSV import, templates, contacts, suppressions and delivery nodes (per-node credentials).

---

## Integrations

| Integration | State |
|---|---|
| Chapa | Live: checkout, webhook, status polling, payouts (`services/payments/chapa.py`) |
| Manual payments | Live: admin-approved deposits and withdrawals, two-person approval at 2,000 ETB or more |
| Telebirr SMS evidence | Built, **switched off**; fixes designed, awaiting approval (D9) |
| SantimPay, ArifPay | Not built; config keys exist and they're hardcoded unavailable |
| Telegram | aiogram webhook with a secret token; Mini App initData auth |
| Cloudflare | Containerized tunnel, ingress as code (`deploy/cloudflared/config.yml.example`) |
| Game aggregators | Research only ([platform/provider-integration.md](platform/provider-integration.md)) |

---

## Security

- **Players:** Telegram initData HMAC-SHA256, constant-time comparison, 24 h replay window.
- **Admins:**
  - bcrypt password plus TOTP; server-side sessions (8 h) that can be revoked; accounts created only by CLI.
  - 4 roles (support, finance, ops, superadmin) and 51 permissions in `services/admin/rbac.py`.
  - Console IP allowlist (`ADMIN_IP_ALLOWLIST`).
- **Rate limits** (fail closed):

  | Bucket | Limit |
  |---|---|
  | WS messages | 30/s |
  | take_card | 10/min |
  | claim | 5/min |
  | deposit | 5/h |
  | Telebirr redeem | 10/h |
  | admin login | 5 per 15 min |
  | Keno tickets | 20/min per player and per IP (see D5) |

- **Data:** phone numbers AES-256-GCM with an HMAC blind index; log redaction; append-only ledger and audit log by trigger.
- **Secrets:** production secrets live in `deploy/.env` on the server (key names in `.env.prod.example`), plus the gitignored cloudflared and alertmanager files.
- **Open:**
  - The Telebirr forgery hole (rail off).
  - `PHONE_ENCRYPTION_KEY` in git history (D12).
  - LAN-exposed app ports (R8).
  - Undisclosed simulated players (D11).
  - See also [SECRET_SECURITY_AUDIT.md](SECRET_SECURITY_AUDIT.md) and [TELEGRAM_SECURITY_AUDIT.md](TELEGRAM_SECURITY_AUDIT.md).

---

## Operations

- **Deploy:**
  1. Bring the commits over as a git bundle (the server's remote is dead).
  2. `./deploy/backup.sh`.
  3. `docker tag jobingo:latest jobingo:rollback-<old sha>`.
  4. `git checkout --detach <sha>`.
  5. `docker build -t jobingo:latest .` (`docker compose build` does nothing for this stack).
  6. `docker compose run --rm migrate` if there's a migration.
  7. `up -d --no-deps <services>`.
  8. Verify.

  Always confirm a migration landed with `SELECT version_num FROM alembic_version`. Full procedure and records: [ops/hotfix-2026-09-26-live-bingo.md](ops/hotfix-2026-09-26-live-bingo.md).
- **Rollback:** retag the rollback image, `up -d --no-deps`, check out the old sha. No schema downgrade has been needed so far. See also [PRODUCTION_ROLLBACK.md](PRODUCTION_ROLLBACK.md).
- **Backups:** `deploy/backup.sh` writes to `~/backups` on the server, alongside WAL archiving. They are **on the same machine**. See [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md).
- **Monitoring:**
  - Every service exposes `/metrics`, and the rules live in `deploy/prometheus/alerts.yml` and `alerts.prod.yml`.
  - Start it with `docker compose -f deploy/docker-compose.prod.yml --profile monitoring up -d prometheus alertmanager`, once `deploy/alertmanager/alertmanager.yml` and the bot token file exist.
- **Kill switches:** Keno `keno_enabled`; Bingo per-room emergency stop; provider availability per rail (`payment_provider_availability`).
- **Runbooks:** [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md), [LAUNCH_DAY_OPERATIONS.md](LAUNCH_DAY_OPERATIONS.md), [keno/08-runbook.md](keno/08-runbook.md), [PRODUCTION_SMOKE_TEST.md](PRODUCTION_SMOKE_TEST.md).

---

## Testing Status

- **Suite:** 33 unit files, 125 integration files (17 of them browser e2e), 7 frontend `.mjs` files.
- **Default run:** excludes the `load`, `e2e`, `chaos_infra` and `keno_statistical` markers.
- **Latest full run** (2026-09-30, main): **1,863 passed, 2 failed, 3 xfailed**; mypy clean across 166 files.
  - The 2 failures are the backup drills, which can't run against a throwaway database.
  - The 3 xfails are strict and wait on operator decisions (#25, #30, #57).
- **Run it locally:**

  ```bash
  docker run -d --name jobingo-verify-pg -e POSTGRES_USER=jobingo -e POSTGRES_PASSWORD=jobingo -e POSTGRES_DB=jobingo -p 5434:5432 postgres:15
  docker run -d --name jobingo-verify-redis -p 6381:6379 redis:7
  export DATABASE_URL=postgresql://jobingo:jobingo@localhost:5434/jobingo
  export DATABASE_URL_SYNC=postgresql+psycopg2://jobingo:jobingo@localhost:5434/jobingo
  export REDIS_URL=redis://localhost:6381/0
  .venv/bin/alembic -c migrations/alembic.ini upgrade head   # tests don't migrate
  .venv/bin/python -m mypy packages services migrations
  .venv/bin/python -m pytest tests -q                          # ~15-20 min
  .venv/bin/python -m pytest -m e2e tests/integration -q       # browser tests
  ```

- **Rules of thumb:**
  - Never point tests at the dev database on 5433.
  - Don't run two full suites against one database.
  - A test that fails only in the full run is usually shared state; see [KNOWN_TEST_FLAKES.md](KNOWN_TEST_FLAKES.md).
- **CI** (`.github/workflows/ci.yml`): mypy, the default suite, `chaos_infra` (one process per file), then e2e. Load tests run in a separate job that's allowed to fail; there's also a Docker build.
  - It had never passed on this repository until 2026-10-01.
  - First green results on GitHub: mypy, the default suite (1,869 passed, 3 xfailed) and the Docker build.
  - The chaos run found the Redis-outage regression (now fixed).
  - The load job's `test_many_sockets_receive_a_call_within_budget` measured a p99 of 414 ms against a 300 ms budget on a shared runner; not investigated yet.

---

## Documentation Health

Places where a document says one thing and the code or reality says another.
Fix a doc when you touch its area.

| Doc | Says | Reality |
|---|---|---|
| The 2026-09-06 launch pack (LAUNCH_BLOCKERS, FINAL_HUMAN_ACTIONS, PRODUCTION_READINESS, FINAL_LAUNCH_ACCEPTANCE, RELEASE_CANDIDATE) | arada.fun, server .173, a `prod` remote, head `4bbb21e0f5ad`, no Keno | arada.click on .115, `origin`, head `b5d9e3a1c7f2`, Keno deployed off; the incident, DR and rollback docs now exist |
| README.md, keno/PROGRESS.md | `igame` is the active repo | `origin` = Nebiyu-Dejenie/game |
| keno/PROGRESS.md | No Keno admin UI | Exists since 2026-09-25 |
| keno/07-economics-and-bankroll.md | Jackpot fix "not yet deployed"; exposure is gross payout | Deployed; exposure is net of stakes (since 09-23) |
| RBAC_MATRIX.md | 34 permissions | 51 in `rbac.py` |
| BOT_COMMAND_CATALOG.md | 18 handlers | 19 (`on_customer_telebirr_paste` is missing) |
| TELEBIRR_SMS_OPERATIONS_GUIDE.md | "Not yet deployed" | Deployed, then switched off |
| `deploy/docker-compose.prod.yml` header | "six deployable units", `sms.arada.fun` | Nine app services, `sms.arada.click` |
| DECISIONS.md header | "Newest first" | Mostly oldest first after line 10,000; it has no entry for the arada.click rebrand |
| Keno refund docstring | Reverses the stake split | Corrected 2026-10-01 to match the code; the rule is D14 |
| `awaiting_reconciliation` in docs | A payment status | A worker outcome; the row stays `processing` |

---

## Future Ideas

Approved or designed, not built:
- **Retention** ([platform/retention-design.md](platform/retention-design.md)), approved:
  - Keno counts 100% toward playthrough.
  - Badge-only streaks.
  - Notifications on by default with one-tap off.
  - Referral reward after the referee wagers 3× their deposit.
  - Visible playthrough progress.
  - About 3–4 weeks.
- **Bingo parity** (approved, ~7 weeks): starts with the pot-accounting invariant and a simulated-player exposure cap.
- **Telebirr controls:** E1–E5 and R1–R4 plus parser fixes, ~1.5–2 weeks, awaiting approval.
- **Keno UX backlog** ([keno/PROGRESS.md](keno/PROGRESS.md)): overdue-numbers heatmap, draw pacing and sound, saved number sets, colour-blind audit, jackpot ticker and last-winner banner, fairness-UI polish.
- **Game aggregator / seamless wallet** (research, ~2–3 months, needs licensing first).
- **Gambling UI conventions** (research, Parts B–E, [design/gambling-ui-conventions.md](design/gambling-ui-conventions.md)).
- **VPS migration** ([ops/vps-migration.md](ops/vps-migration.md)): plan written, not executed.

---

## Deferred Ideas

Deliberately not built, with the reason:

| Idea | Why deferred |
|---|---|
| SantimPay, ArifPay | API docs unreachable; guessing a signature is a forgery hole |
| Abandoned-checkout expiry | Needs Chapa's expiry behaviour; both naive fixes risk double credit or lost money |
| KYC document pipeline, device fingerprinting | Product and legal choices |
| Holder-name match and risk score on withdrawals | No identity source |
| Unifying the two IP-allowlist checks | No bug today; security-critical code |
| Keno per-number voice, onboarding art | No assets |
| Making technical constants configurable | Operator decision, 09-27 |
| Risk-simulator session metrics | No data yet |
| Reserve floor, jackpot cap and seed | Business decisions (floor 0, cap none, seed 0 at launch) |
| Bonus lifecycle as "Promotions"; campaign templates; referral dashboard; notification pause; forced logout | P2–P3 |
| Tax export | Not needed yet |
| Full SMS Control Plane roadmap | Separate product, built in slices |

---

## Open Questions

- Why did `house_float` read −1,000.00 from ledger transaction #1, and what's the correction?
- Is Telebirr SMS really off in production? This is checked in the Step 1 pre-flight.
- Is the `arada.fun` deployment still running, and does anything still point at it?
- Does Chapa reuse a transaction reference across a failed and a later successful attempt? The #28 fix handles it either way, but the answer decides #30.
- Are the systemd timers (backup, basebackup, WAL prune, reconcile) installed on the arada.click server? Unconfirmed.
- Licensing for real-money Keno: status unconfirmed ([keno/12-compliance.md](keno/12-compliance.md)).

---

## Recommended Next Work

In order. Each item says what it unblocks.

1. ~~Deploy Step 1~~: done 2026-10-01 (`2aa504a`). **Switch Telebirr SMS deposits off** (D0).
2. **Keno Steps 2–3:** show the reserve transaction, then post and verify it after confirmation; then add the testers. The operator flips Step 4.
3. **Start monitoring** (needs D3), then test-fire an alert end to end.
4. **Fix correlated Keno exposure** (after D4), before Stage 2.
5. **Verify the remaining medium and low findings, money paths first:**
   - #69 and #73: the deposit cap race.
   - #70 and #71: the webhook doesn't check direction.
   - #77: withdrawal cents.
   - #78: banned players can withdraw.
   - #79: the chargeback window.
   - #81 and #108: duplicate withdrawals.
   - #36: a welcome-bonus race.
   - #46: the reserve floor.
6. **Lock-order sweep** for admin, bot and gateway.
7. **Off-box backups** and the VPS decision (D10).
8. **Telebirr controls** after the operator approves the design (D9).
9. **Retention build**, then **Bingo parity**.
10. **Refresh stale docs** from [Documentation Health](#documentation-health): the launch pack, RBAC matrix, bot catalog and Keno economics.
11. **Split the admin modules** and remove the duplication listed in Technical Debt.

---

## Document Map

| Area | Documents |
|---|---|
| Start here | this file; [README.md](../README.md) (setup, CI/CD, deployments); [DECISIONS.md](../DECISIONS.md) |
| Operations | [ops/hotfix-2026-09-26-live-bingo.md](ops/hotfix-2026-09-26-live-bingo.md) (deploy records and the next deploy), [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md), [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md), [DISASTER_RECOVERY_DRILL.md](DISASTER_RECOVERY_DRILL.md), [PRODUCTION_ROLLBACK.md](PRODUCTION_ROLLBACK.md), [PRODUCTION_SMOKE_TEST.md](PRODUCTION_SMOKE_TEST.md), [PRODUCTION_HOST_VERIFICATION.md](PRODUCTION_HOST_VERIFICATION.md), [EMERGENCY_ROOM_STOP.md](EMERGENCY_ROOM_STOP.md), [LAUNCH_DAY_OPERATIONS.md](LAUNCH_DAY_OPERATIONS.md), [ops/vps-migration.md](ops/vps-migration.md), [PRODUCTION_DOMAIN_AND_CLOUDFLARE.md](PRODUCTION_DOMAIN_AND_CLOUDFLARE.md) |
| Launch pack (stale, 09-06) | [LAUNCH_BLOCKERS.md](LAUNCH_BLOCKERS.md), [FINAL_HUMAN_ACTIONS.md](FINAL_HUMAN_ACTIONS.md), [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md), [FINAL_LAUNCH_ACCEPTANCE.md](FINAL_LAUNCH_ACCEPTANCE.md), [RELEASE_CANDIDATE.md](RELEASE_CANDIDATE.md) |
| Admin guides | [ADMIN_DASHBOARD_GUIDE.md](ADMIN_DASHBOARD_GUIDE.md), [ADMIN_FEATURE_INVENTORY.md](ADMIN_FEATURE_INVENTORY.md), [FINANCE_DASHBOARD_GUIDE.md](FINANCE_DASHBOARD_GUIDE.md), [AGENT_DASHBOARD_GUIDE.md](AGENT_DASHBOARD_GUIDE.md), [NOTIFICATION_CENTER_ADMIN_GUIDE.md](NOTIFICATION_CENTER_ADMIN_GUIDE.md), [BOT_COMMAND_CATALOG.md](BOT_COMMAND_CATALOG.md), [keno/09-admin-guide.md](keno/09-admin-guide.md) |
| Payments | [TELEBIRR_SMS_OPERATIONS_GUIDE.md](TELEBIRR_SMS_OPERATIONS_GUIDE.md), [TELEBIRR_PRODUCTION_CHECKLIST.md](TELEBIRR_PRODUCTION_CHECKLIST.md), [TELEBIRR_MACRODROID_QUICK_SETUP.md](TELEBIRR_MACRODROID_QUICK_SETUP.md), [TELEBIRR_ROLES_AND_ACCESS.md](TELEBIRR_ROLES_AND_ACCESS.md), [payments/telebirr-evidence-and-redemption-design.md](payments/telebirr-evidence-and-redemption-design.md) |
| Keno | [keno/](keno/) 00-discovery to 12-compliance, [keno/PROGRESS.md](keno/PROGRESS.md) |
| Security and compliance | [audit/platform-audit-2026-09.md](audit/platform-audit-2026-09.md), [SECRET_SECURITY_AUDIT.md](SECRET_SECURITY_AUDIT.md), [TELEGRAM_SECURITY_AUDIT.md](TELEGRAM_SECURITY_AUDIT.md), [RBAC_MATRIX.md](RBAC_MATRIX.md), [PRODUCTION_ACCESS_MATRIX.md](PRODUCTION_ACCESS_MATRIX.md), [RESPONSIBLE_GAMING_REQUIREMENTS.md](RESPONSIBLE_GAMING_REQUIREMENTS.md), [PLATFORM_POLICY_REVIEW.md](PLATFORM_POLICY_REVIEW.md) |
| Product and business | [BINGO_WINNING_RULES.md](BINGO_WINNING_RULES.md), [BUSINESS_KPI_DICTIONARY.md](BUSINESS_KPI_DICTIONARY.md), [BUSINESS_OPERATING_SYSTEM.md](BUSINESS_OPERATING_SYSTEM.md), [NOTIFICATION_CENTER_ARCHITECTURE.md](NOTIFICATION_CENTER_ARCHITECTURE.md), [NOTIFICATION_CENTER_OPERATIONS.md](NOTIFICATION_CENTER_OPERATIONS.md), [SMS_CONTROL_PLANE.md](SMS_CONTROL_PLANE.md), [SMS_MACRODROID_ADAPTER.md](SMS_MACRODROID_ADAPTER.md), [TELEGRAM_COMMAND_OPERATIONS.md](TELEGRAM_COMMAND_OPERATIONS.md), [TELEGRAM_PERFORMANCE.md](TELEGRAM_PERFORMANCE.md), [platform/retention-design.md](platform/retention-design.md), [platform/provider-integration.md](platform/provider-integration.md), [design/gambling-ui-conventions.md](design/gambling-ui-conventions.md) |
| Testing | [KNOWN_TEST_FLAKES.md](KNOWN_TEST_FLAKES.md), [keno/10-test-report.md](keno/10-test-report.md), [keno/11-load-test-report.md](keno/11-load-test-report.md) |

---

## Glossary

| Term | Meaning |
|---|---|
| Derash | The Bingo prize: the pot minus the house cut |
| Round | One Bingo game in a room, or one global Keno draw |
| Tie window | 50 ms after the first valid Bingo claim, during which other claims share the prize |
| Tier | A Keno risk level (1–4) that sets stakes, picks, max win and exposure |
| Exposure ceiling | Reserve × `max_round_exposure_pct`: what one Keno round may put at risk |
| Reserve | `keno_reserve`, the operator money that pays Keno wins |
| `house_float` | The operator's funding account, the counterparty for adjustments and reserve transfers |
| Allowlist | `keno_beta_allowlist`: who may play Keno while `beta_restricted` is on |
| Kill switch | `keno_enabled`; for Bingo, the per-room emergency stop |
| Simulated player | An admin-controlled bot account that plays Bingo with house money |
| Playthrough | Wagering required before a bonus converts to cash |
| `our_ref` | Our reference for a payment (`DEP-` or `WD-<year>-<number>`) |
| Idempotency key | A unique key per money operation, so a retry can't move money twice |
| Stage 1 | Keno open to a small internal allowlist only |
| Step 1–4 | The operator's Keno launch sequence ([Keno Launch Plan](#keno-launch-plan)) |

---

## Change Log

- **2026-10-01 (later still):** Keno Stage 1 reserve funded: 30,000.00 from house_float, after the operator confirmed the exact transaction. Verified (ledger transaction #4, audit row #7, reconcile OK, Tier 1, ceiling 3,000.00). Step 3 (testers) is next.
- **2026-10-01 (later):** **Deployed the Step 1 release** (`2aa504a`, 07:38 UTC) through the runbook script. Every check passed; no errors or restarts after 6 minutes.
  - The pre-flight found Telebirr SMS deposits still enabled (new D0).
  - Also shipped: the payment fixes #70/#71, #78 and #79.
  - #81 is fixed on main for the next deploy.
- **2026-10-01:** The operator authorized the Step 1 deploy. It's still blocked by the network: the server is unreachable from the dev machine, and the repo has no CD runner.
  - Pre-deploy review done. Main pushed to `origin`.
  - CI repaired, and its chaos test found a regression in the #23 fix: Bingo calls played on through a Redis outage. Fixed in 2fefe43.
  - Keno refund and jackpot accounting traced and recorded as decision D14 (behaviour unchanged, pinned by a test).
- **2026-09-30:** Created. Built from four surveys of the code and docs (architecture and API, game and money rules, database and tests, decisions and roadmap), this session's production reads, and the audit tracker.
