MASTER BUILD SPECIFICATION — ADD "KENO" TO THE LIVE TELEGRAM BINGO PLATFORM
Role: You are the Principal Architect and sole senior engineer of this platform. You built and shipped the Bingo game currently live at https://arada.fun You own this codebase.

Mode: Work autonomously in VS Code, end to end, until Keno runs in production beside Bingo. Do not stop at files. Do not stop at a prototype. Do not hand me architecture decisions you can answer by reading the repository.

Golden rule: Bingo is live. Real users, real money, real balances. Keno must be purely additive. If a change isn't required, don't make it. If a shared change is required, make it backward compatible and prove it.

Business context: The operator is launching with limited capital (under 50,000 ETB reserve), expects high player volume, and typical stakes around 50 ETB. The economics in Part 7 are therefore not optional decoration — they are survival requirements. Build them as specified.

PART 0 — RULES OF ENGAGEMENT
Inspect before you write. No code, no migration, no Docker change until Part 1 is delivered.
Never fabricate results. If you didn't run it, say "NOT RUN". If a test fails, show the failure. A false PASS is the worst possible outcome of this task.
Never print secrets. No tokens, DB passwords, bot token, or tunnel credentials. Reference them by env-var name only.
Never guess ports, paths, credentials, table names, or service names. Read them from the repo and from ~/jo-bingo/deploy.
No destructive operations. No DROP DATABASE, no dropping or destructively altering Bingo tables, no truncating wallets, no resetting production. Additive migrations only, each with a tested down.
Ask only if genuinely blocked — a missing credential, or something that risks production money. Everything else: decide, document, continue.
Small, reviewable commits. Feature-flagged from commit one.
Kill switch first. Before Keno touches production there must be one admin toggle + env flag that instantly stops new rounds and blocks new tickets (while still settling in-flight tickets) without affecting Bingo.
PART 1 — DISCOVERY (deliver a report, write no feature code)
Read the entire repository and deploy directory. Produce docs/keno/00-discovery.md containing:

A. System map — every service/container, responsibility, framework, startup, health check, restart policy. The real request path (Cloudflare → Tunnel → Traefik → gateway → workers/DB/Redis), actual router rules, actual internal ports, and how internal-only services are enforced today.

B. Code inventory — directory layout and module boundaries; where domain logic lives vs transport vs persistence; existing conventions for naming, error handling, validation, DTOs, logging, config loading, DI. The Bingo engine: its loop, state machine, where state lives, restart recovery, locking, scheduling. engine-worker and payout-worker: queue technology, job shape, retries, dead-letter, idempotency. Realtime: transport, socket auth, room model, event envelope, reconnect behavior.

C. Data layer — full current schema (tables, columns, types, FKs, indexes, unique constraints, enums); migration tool and how it runs at deploy; the wallet/ledger model in detail (balance column or double-entry? how is a Bingo stake deducted and a win credited? what guarantees atomicity? what idempotency keys exist?); Redis key namespaces, TTLs, pub/sub channels, locks, and what is cache vs source of truth.

D. Identity & security — Telegram initData validation (where, how, replay protection, session/JWT issuance, expiry, refresh); admin auth and permission model; existing rate limiting, validation, CORS, CSP.

E. Mini App frontend — framework, build, routing, state, styling, i18n, assets; how it authenticates and subscribes to realtime; Telegram SDK usage (theme params, viewport, BackButton, MainButton, haptics, safe areas).

F. Ops — Prometheus naming conventions in use, existing dashboards, alert rules, Loki log format/labels, backup job scope.

G. Integration plan — the point of the report. For each of auth, wallet/ledger, user model, admin auth, realtime transport, worker framework, migrations, metrics, logging, Docker/Traefik, i18n: state exactly what you will reuse, extend, or create new, with file paths. List which Bingo files (if any) you must touch, why, and how backward compatibility is preserved. Include a risk list with mitigations.

H. Open decisions — only things genuinely requiring the operator. Use the defaults in Part 7 and mark them as "default, changeable in admin".

Then continue to implementation without waiting.

PART 2 — THE PRODUCT
A Fast Keno game running continuously inside the same Telegram Mini App as Bingo, sharing account, wallet, login, and admin.

Must be usable by someone with zero technical knowledge, on a cheap Android phone, on a slow network, in Amharic or English, entirely inside Telegram:

Open bot → Tap Play → GAME CENTER
                        ├── 🎱 BINGO  (existing, untouched)
                        └── 🔵 KENO   (new)
Tap Keno → board appears → tap numbers → tap stake → tap PLAY → watch balls drop → result → play again. Three taps to a bet.

Game Center is a new hub, not a rewrite. Per game: icon, name, one-line description in the user's language, live status ("Betting open · 0:23", "Drawing…"), shared ETB balance at top. Built so a third game is added by config, not by rewriting the hub.

PART 3 — KENO DOMAIN LOGIC
3.1 Rules (all configurable, none hard-coded)
Number pool: 1..80 · Numbers drawn: 20
Picks per ticket: min 1, max 10 (restricted by risk tier — see Part 7)
Stake options: configurable ETB list + min/max
Round cycle: configurable (launch value in Part 7)
One ticket = one pick-set + one stake; multiple tickets per user per round up to a configurable cap
3.2 Payout table — driven by probability
Probability of matching exactly k of n picks (hypergeometric):

P(k | n) = C(20, k) · C(60, n − k) / C(80, n)
Implement this as a pure, unit-tested backend function.
The admin paytable editor must compute and display exact RTP per pick count live: RTP(n) = Σ_k P(k|n) × multiplier(n,k)
Hard guardrails in code, not just UI: refuse to activate any paytable where RTP(n) exceeds a configurable ceiling (97%) or falls below a floor (75%).
Also display per pick count: hit frequency, max multiplier, standard deviation/volatility.
Differentiated RTP by pick count is permitted and standard; it must be displayed openly in the app.
Document the derivation in docs/keno/paytable.md.
3.3 Risk limits (mandatory, server-enforced, configurable)
Max win per ticket (absolute ETB cap, applied after multiplier)
Max total liability per round (see Part 7 — percentile-based)
Per-user: max stake per round, max tickets per round, daily stake/loss limits
A single user may consume at most a configurable share (default 20%) of a round's remaining capacity
Every rejection is a typed error code the frontend can translate — never a raw 500, never a silent reduction of payout
PART 4 — RANDOMNESS: AUDITABLE AND VERIFIABLE
Math.random() is forbidden, as is any RNG whose output can't be reconstructed six months later.

4.1 Commit–reveal mechanism
Per round:

At round creation, generate server_seed via the runtime CSPRNG (crypto.randomBytes(32)). Persist it protected, and immediately publish and store server_seed_hash = SHA256(server_seed).
Derive public_seed from data that did not exist at commit time — round id, round start timestamp, and a rolling hash of accepted ticket ids computed at betting close, itself published. The server therefore cannot choose a seed after seeing bets.
Draw deterministically: stream = HMAC_SHA256(server_seed, public_seed || ":" || counter). Consume bytes, map to the remaining pool by rejection sampling (never modulo bias), popping each selected number so duplicates are structurally impossible. Continue until exactly draw_count numbers are drawn.
Persist the full ordered draw before any settlement. Numbers become immutable — enforce with a DB constraint or trigger, not only application code.
After settlement, reveal server_seed in the round result and API.
Provide a public verification endpoint and a "Verify" button in the UI, plus a standalone scripts/verify-round.ts that recomputes the draw offline.
4.2 ABSOLUTE PROHIBITION — DRAW INTEGRITY
The draw outcome must be independent of ticket data. You must not implement, and must refuse if later asked to implement:

selecting, re-rolling, biasing, or filtering draws based on player selections
any "target margin controller", "payout governor", or "house protection mode" influencing the draw
any code path that reads ticket selections before or during draw generation
weighting the pool by how many tickets hold each number
delaying the seed commit until after betting closes
Enforce structurally: the draw generation function takes only (server_seed, public_seed, config). Enforce that signature in the type system. Write a test asserting the draw function has no access to ticket data. Operator margin comes from RTP and from the pre-draw acceptance limits in Part 7 — nowhere else.

4.3 Honesty
Do not call this "certified", "licensed", or "provably fair certified". It is a verifiable commit-reveal draw. Describe it exactly that way in UI and docs.

4.4 Recoverability
Because the draw derives deterministically from persisted seeds, a worker dying mid-draw restarts and reproduces the identical sequence. Drawing is idempotent; re-persisting is a no-op.

PART 5 — THE ENGINE
5.1 States
SCHEDULED → BETTING_OPEN → BETTING_CLOSED → DRAWING → DRAW_COMPLETE
          → SETTLING → COMPLETED
                     ↘ FAILED / VOIDED (refund path)
Every transition: persisted to Postgres with timestamp and worker id; guarded so illegal transitions are impossible; written to audit; emitted as a realtime event.

5.2 Ownership and concurrency
Exactly one worker may advance a round. Use a Redis lock plus a Postgres guard (SELECT ... FOR UPDATE on the round row, and an optimistic UPDATE ... WHERE state = expected). Redis is a fast path; Postgres is truth. Two workers on one round must produce one settlement — write a test that runs two workers against one round and asserts it.

5.3 Restart recovery
On boot, before new work: scan non-terminal rounds, determine true state from Postgres, resume.

Crashed in BETTING_OPEN → recompute remaining time from betting_closes_at; close immediately if elapsed.
Crashed in DRAWING after N balls → read persisted balls, re-derive from seeds, continue at N+1. Never re-randomize.
Crashed in SETTLING → re-run; idempotency keys make paid tickets no-ops.
Stuck beyond a configurable threshold → mark FAILED, auto-refund every ticket via a refund ledger transaction, alert, continue. A stuck round must never silently eat user money.
5.4 Timing discipline
The engine drives time; the browser does not. Clients receive server_time, betting_closes_at, draw_started_at and render countdowns locally with drift correction. No database writes per animation frame — persist the draw once, stream the reveal.

PART 6 — MONEY
Reuse the existing wallet/ledger. Do not create a second wallet. Extend with new transaction types; do not build a parallel system.

6.1 Bet placement (single DB transaction)
BEGIN
  validate ticket (picks in range, no duplicates, count within min/max, stake in allowed set)
  re-read round with lock; assert state = BETTING_OPEN
  validate risk tier, per-user limits, round exposure capacity
  lock user wallet row (SELECT ... FOR UPDATE)
  assert balance >= stake
  insert ledger debit (type: keno_stake, idempotency_key: client_request_id)
  update balance
  insert ticket + selections
COMMIT
Client sends an idempotency key with every bet. A retry returns the original ticket. Enforce with a unique index, not an existence check.
CHECK (balance >= 0) constraint so no logic bug can produce a negative balance.
Unique constraint on (round_id, user_id, normalized_picks) if duplicate identical tickets are disallowed.
6.2 Settlement (idempotent by construction)
Compute matches from the persisted draw; use the paytable version pinned to the round at creation, never the current one. An admin editing the paytable mid-round must not alter in-flight results.
Apply max-win cap.
Credit via a ledger entry with a deterministic idempotency key: keno:settle:{round_id}:{ticket_id}, unique-indexed. A crash between credit and mark-settled is harmless: the retry conflicts, is skipped, and the ticket is marked settled.
Settle in batched transactions — no N+1.
Every ticket ends won, lost, or refunded. A reconciliation job alerts on unsettled tickets in COMPLETED rounds.
6.3 Invariants (automated, must always hold)
Σ keno stakes − Σ keno payouts − Σ keno refunds == net keno revenue
per round: Σ ticket stakes == Σ stake ledger entries
no ticket settled twice; no ledger entry without a ticket; no ticket without a ledger entry
Expose as a metric and admin report; run in CI against simulated rounds.

PART 7 — ECONOMICS, BANKROLL PROTECTION & LAUNCH CONFIGURATION
This part is a survival requirement, not a preference.

7.1 Prize reserve
Introduce an operator prize reserve as a first-class, persisted, auditable concept.

keno_reserve — funded by explicit operator deposit, grown by net GGR, reduced by net payouts and explicit withdrawals.
Every stake and payout adjusts it through the ledger in the same transaction. It must reconcile exactly: reserve = deposits + Σ stakes − Σ payouts − Σ refunds − Σ withdrawals
Withdrawal floor: the admin cannot withdraw below a configurable reserve floor. Attempts are blocked and audited.
Critical: display prize reserve and player-balance liability separately on the dashboard. Player balances are money owed. Alert when liabilities approach available cash. Operators die of this more often than of bad luck.
7.2 Tiered risk ladder
Offered bets scale automatically with the reserve. Store tiers as config rows (keno_risk_tiers), not code. Each defines min_reserve, max_pick_count, max_top_multiplier, max_stake, max_win_per_ticket, max_round_exposure_pct, paytable_version.

Tier	Min reserve (ETB)	Picks	Top multiplier	Max stake	Max win/ticket
1	0	1–5	16x	50	800
2	200,000	1–6	60x	50	3,000
3	1,000,000	1–8	500x	100	50,000
4	5,000,000	1–10	5,000x	200	250,000
Tier is evaluated at round creation and pinned to the round with the config and paytable version. Never mid-round.
Promotion requires the reserve to hold above the threshold for 7 consecutive days (prevents flapping on a lucky day). Demotion is immediate on falling below, and never affects in-flight rounds or accepted tickets.
All tier changes audited, exposed as a metric, alerted.
The UI must clearly show currently available pick counts, stakes, and the live paytable. Nothing hidden.
Why the 16x cap at launch matters: with a ~40,000 ETB reserve and 50 ETB stakes, a low-variance table keeps the daily swing near the daily expected profit and the reserve compounds safely. Jackpot-scale multipliers push the daily swing an order of magnitude above the reserve — one hit and the operator cannot pay. Do not raise the launch top multiplier.

7.3 Round exposure control
Before accepting any ticket, inside the bet transaction:

if projected_round_exposure > reserve × max_round_exposure_pct:
    reject with typed error BET_ROUND_CAPACITY_REACHED
Compute exposure at the 99.9th percentile of simulated payout, not absolute worst case — absolute worst case is unusable at this reserve size. Implement via Monte Carlo over the live paytable, recomputed when the paytable changes, cached.
Rejection message must be honest: "This round is full. Your bet was not placed — try the next round." Never take the money and quietly reduce the payout.
Metric keno_round_exposure_ratio; alert above 80%.
Daily circuit breaker: if 24h payouts exceed a configurable multiple of expected, automatically demote a tier and alert. This is a pre-draw acceptance control affecting future rounds only — never a drawn result.
7.4 Paytable profiles
Ship two profiles at the same target RTP:

low_variance (Tier 1–2 default): compressed multipliers, high hit frequency, payout on 50%+ of tickets at 4–5 picks.
standard (Tier 3+): conventional shape with larger top prizes.
Build a risk-of-ruin simulator in admin: given reserve, daily handle, and a paytable, run N simulated days and report the distribution of ending reserve, worst drawdown, and probability of breaching the floor. Also report median session length and handle per 100 ETB deposited for each candidate paytable — select the paytable that maximizes handle per deposit, not the one with the lowest RTP.

7.5 LAUNCH CONFIGURATION (defaults)
Target RTP:            82%  (18% house edge), both profiles
RTP guardrails:        floor 75%, ceiling 97%
Launch tier:           Tier 1
Pick counts:           1–5
Top multiplier:        16x        ← do not raise at launch
Stake options:         10 / 20 / 50 ETB
Max win per ticket:    800 ETB
Max tickets/user/round: 3
Round cycle:           45s  (25s betting / 12s draw / 8s results)
Progressive diversion: 1.5% of stake (see 8.3)
PART 8 — PROFIT OPTIMIZATION ENGINE
Monthly GGR = DAU × sessions/day × rounds/session × tickets/round × avg stake × house edge
Edge is capped by market tolerance. The other five terms are not. Maximize handle, not edge. Instrument every term.

Required metrics: keno_dau, keno_sessions_per_user, keno_rounds_per_session, keno_tickets_per_round, keno_avg_stake, keno_hold_pct, keno_arpdau, keno_d1/d7/d30_retention, keno_player_ltv, keno_deposit_conversion_rate, keno_session_duration_seconds.

8.1 Round velocity (largest lever)
Overlap the cycle: open betting for round N+1 during round N's results phase. Zero dead time. Worth 20–30% more rounds per session at no cost.
Pre-warm the next round in Redis so there is no gap.
Ball reveal must stay legible at 12s for 20 balls on a low-end Android; if not, reveal in accelerating batches rather than lengthening the cycle.
A/B test 45s vs 60s behind config; report measured handle per player-hour for each.
8.2 Tickets per round & session length
Multi-ticket (default 3), Repeat last ticket (one tap, on the main button), Lucky Pick (instant random), Auto-play for the next 5/10/25 rounds with a visible counter, running balance, and one-tap stop.
Auto-play must hard-stop on: insufficient balance, tier change, responsible-gaming limit reached, or session timer.
Low variance produces longer sessions and more total handle at fixed RTP — this is why the launch paytable targets high hit frequency.
8.3 Player-funded progressive jackpot (zero operator liability)
Divert a configurable slice of every stake (default 1.5%) into a progressive pool held as a separate ledger account. This is taken from the payout budget, not added to player cost — base-game RTP drops 1.5% and returns through the jackpot, keeping total RTP honest and disclosed.
The jackpot pays only from the pool and can never exceed the pool balance. Operator liability is structurally zero. Verify with a test.
Trigger: a rare, purely draw-determined condition (e.g. all picks matched on a 5-spot). Never influenced by tickets, pool size, or time.
Seed the pool with a small configurable amount so it is never empty at launch.
Display the live pool prominently — a visible growing number is the strongest engagement driver in this category, and it gives big-prize excitement the reserve cannot otherwise afford.
If capped, overflow goes to a secondary pool for the next cycle — never to operator revenue, and this must be stated in the rules.
8.4 Retention
Daily streak bonus; Referral bonus credited after the referred player completes N rounds (not on signup — prevents farming), with referral chains tracked for fraud review.
Welcome bonus with playthrough: bonus credit usable only for stakes, released to withdrawable balance after a configurable wagering multiple. Enforce server-side via a separate bonus-balance ledger account; bonus funds are never directly withdrawable. Terms displayed in full, in the player's language, before acceptance.
Telegram re-engagement: bot notifications on jackpot milestones, streak about to break, big community wins. Rate-limited, user-toggleable, max one per day by default.
Cross-sell Bingo in Keno's idle moments and vice versa; shared wallet makes switching frictionless. Track cross-game LTV.
8.5 Deposit friction (often the real bottleneck)
Instrument deposit funnel conversion at every step and time-to-first-bet after deposit.
Use the payment rails already integrated for Bingo. Do not build a second payment system.
One-tap deposit amounts; minimum as low as the rails allow; balance and deposit shortcut inside the Keno screen so players never leave the game to top up.
Alert on deposit failure-rate spikes — a broken rail is silent revenue loss.
8.6 Cohort analytics (admin)
Player cohorts by signup week with retention curve, cumulative handle, cumulative GGR, LTV. Segment by stake band and pick-count preference. Actual vs theoretical hold with confidence bands so variance isn't mistaken for a bug. Config changes annotated on the timeline so lever impact is visible. Churn-signal list the operator can act on.

PART 9 — DATABASE
Additive migrations only, clearly namespaced (keno_*, or generic game_* only if it fits the existing schema without touching Bingo tables — decide in Part 1 and justify).

Minimum entities (adapt to existing conventions): keno_configs (versioned; changes are new rows, never edits) · keno_paytables (versioned matrix, stores computed RTP at save) · keno_risk_tiers · keno_rounds (state, timestamps, config/paytable/tier versions, server_seed_hash, server_seed, public_seed, ordered drawn_numbers, totals, exposure) · keno_tickets · keno_ticket_selections (unique constraint preventing duplicate numbers) · keno_round_events (audit) · keno_reserve_ledger · keno_jackpot_pool · admin config-change audit.

Requirements: correct FKs with sane ON DELETE; indexes for every query you actually write ((user_id, created_at DESC), (round_id, status), partial index on non-terminal status for the recovery scan); unique constraints carrying idempotency guarantees; NUMERIC for money (never float); UTC timestamps; documented rollback per migration.

A completed round must be fully reconstructable from the database alone — config, paytable, tier, seeds, draw, every ticket, every ledger entry. If Redis is wiped, nothing of record is lost.

PART 10 — API
Follow existing project conventions exactly: same versioning prefix, auth middleware, error envelope, validation approach, pagination style. Do not invent a new style for Keno. Conceptually: list games / game center state · current round (state, timestamps, server time, seed hash, recent results) · place ticket (idempotent, rate-limited) · my tickets (current + paginated history) · round result by id with verification payload · recent results and hot/cold stats · my statistics · verify round. Plus admin endpoints for config, paytable, tiers, rounds, reports, audit behind existing admin auth and permission checks.

Do not break or alter any existing Bingo endpoint. Add a contract test pinning Bingo's responses that fails if they change.

PART 11 — REALTIME
Reuse the existing transport; add a Keno channel. Events, namespaced and versioned:

keno.round.created · keno.betting.open · keno.betting.closing · keno.betting.closed · keno.draw.started · keno.number.drawn · keno.draw.completed · keno.ticket.settled (owner only) · keno.round.completed · keno.jackpot.updated

Every event carries round_id, monotonic sequence, and server_time.
On connect/reconnect the client requests a full snapshot and reconciles; it never rebuilds state from missed deltas. A player who loses signal at ball 7 and returns at ball 15 sees the correct board instantly.
Private data (tickets, balance) goes only to that user's authenticated socket. Never broadcast balances or others' tickets.
Socket auth uses the existing Telegram-derived session. Rate-limit subscriptions and messages; cap connections per user.
A short-polling fallback must still produce a correct experience on bad networks.
PART 12 — SECURITY
Client is hostile. Server is authoritative.

Telegram initData HMAC validated server-side on every session issuance, with freshness/expiry and replay protection. Reuse the existing implementation — no second auth path.
The client never sends winning numbers, match count, payout, balance, or ticket status. Only picks, stake, round id, idempotency key.
Validate and normalize all input with the existing validator; reject unknown fields.
Rate-limit bet placement per user and per IP; per-user cooldown against bot spam; typed errors.
Re-check round state inside the transaction — a bet arriving 50ms after close must fail.
Admin is permission-checked, fully audited, and structurally unable to alter a completed round's numbers, seeds, or settled payouts. Voiding with refunds is allowed and logged; editing history is impossible.
Log collusion/multi-account signals for review: many accounts per device/IP, identical pick patterns, abnormal win rates, referral farming.
Secrets stay in the existing mechanism. Postgres, Redis, workers, admin remain internal exactly as today.
PART 13 — TELEGRAM MINI APP UI/UX
Mobile-first, thumb-first, Amharic-first. Must feel like a commercial product.

Screens: Game Center → Keno (board, picks, stake, PLAY) → Draw → Result → History/Stats.

Board: 80 tiles, 8 per row on phones, tap to select/deselect, hit targets ≥44px, four clearly distinct states — unselected / selected / drawn / matched — distinguishable by shape or icon as well as colour (colour-blind safe). Quick actions: Clear, Lucky Pick, Repeat.

Feel: balls reveal with a short satisfying animation; matched picks pop with haptic feedback (HapticFeedback.impactOccurred); running match counter; potential payout for the current selection updates live from the server-provided paytable; bold countdown; unmistakable WIN (amount, confetti, haptic success) vs LOSE (calm, no shame, one-tap Play again); live jackpot pool always visible.

Telegram integration: respect themeParams (light/dark), expand(), BackButton, MainButton for the primary action, safe-area insets, enableClosingConfirmation() during an active bet, disableVerticalSwipes where it conflicts with the board. Test on Android, iPhone, desktop Telegram, and a 360px screen.

Performance: small bundle, Keno lazy-loaded separately from Bingo, no heavy animation libraries, CSS transforms only, 60fps on a low-end Android, graceful at 200ms+ latency and on reconnect. Assume expensive mobile data.

i18n: Amharic + English from day one, from the existing string files. ETB formatting. No hard-coded display text.

Zero-knowledge onboarding: a first-time overlay explaining Keno in three sentences and three pictures; "How to play" always reachable; paytable readable in-app; exact payout shown before confirming the bet.

PART 14 — RESPONSIBLE GAMING & COMPLIANCE
Build now; retrofitting is far harder. These are enforced at the same transaction point as the bet, and apply across auto-play and multi-ticket paths.

Per-user configurable daily/weekly stake and loss limits; user-initiated self-exclusion / cooldown blocking bets across both games.
Visible session timer and periodic reality-check nudge.
Minimum-age acknowledgement consistent with Bingo.
All bonus, jackpot, and RTP figures displayed honestly. No hidden mechanics.
docs/keno/compliance.md listing shipped RTP, risk limits, audit trail, data retention, and an explicit note that regulatory licensing (Ethiopian National Lottery Administration or applicable authority) is a business/legal responsibility outside the code — flag it to the operator rather than assuming it is handled.
PART 15 — ADMIN PANEL
Inside the existing admin, same auth and layout language:

Dashboard: live round, state, countdown, tickets, stake, exposure ratio, engine health, last 20 rounds; prize reserve vs player liability shown separately; today's profit; theoretical vs actual RTP with confidence band; daily standard deviation vs reserve; current risk tier and next-tier threshold; projected monthly profit at current handle.
Config: kill switch, pool, draw count, min/max picks, stakes, durations, limits, jackpot diversion. Versioned; effective from the next round only.
Paytable editor: matrix with live RTP, hit frequency, volatility, risk-of-ruin simulation, handle-per-deposit, and the hard guardrails.
Rounds & results: searchable; drawn numbers, seeds, verification link, per-round P&L.
Reports: stake, payout, GGR, margin vs theoretical, ticket counts, unique players, pick-count and payout distributions, per-day/per-hour.
Cohort analytics per Part 8.6.
Players: Keno history, limits, flags.
Audit: every config change, tier change, void/refund, admin action, with actor and diff.
Explicitly absent: any control able to change a completed result.
PART 16 — OBSERVABILITY
Follow existing Prometheus naming. At minimum: keno_rounds_created_total, keno_rounds_completed_total, keno_rounds_failed_total, keno_tickets_created_total, keno_tickets_settled_total, keno_stake_total, keno_payout_total, keno_actual_rtp, keno_reserve_balance, keno_player_liability, keno_round_exposure_ratio, keno_jackpot_pool, keno_draw_duration_seconds, keno_settlement_duration_seconds, keno_settlement_errors_total, keno_active_players, keno_ws_connections, keno_bet_rejections_total{reason}, plus all Part 8 business metrics.

Structured logs with round_id as correlation id on every line of a round's lifecycle. A Grafana dashboard for Keno. Alerts for: round stuck, settlement errors, exposure above 80%, actual RTP diverging sharply over a large sample, engine heartbeat missing, unsettled tickets in completed rounds, reserve near floor, liabilities near available cash, deposit failure spike.

PART 17 — TESTING (show real output)
Unit: hypergeometric probabilities against known values; RTP calculation; paytable guardrails; match counting; payout + cap logic; draw determinism; rejection sampling free of modulo bias; ticket validation; tier evaluation; exposure calculation; jackpot pool accounting.

Integration: full round lifecycle; bet → deduct → draw → settle → credit; idempotent re-bet; idempotent re-settlement; betting after close rejected; insufficient balance rejected; exposure cap rejection; per-user share cap; config change mid-round doesn't affect the running round; void + refund; bonus playthrough enforcement; jackpot cannot exceed pool.

Chaos — actually run these:

Kill the worker mid-draw (after ball 7) → restart → identical remaining sequence, correct completion
Kill during settlement → restart → no double payout (assert ledger totals)
Two workers on one round → one settlement
docker stop redis mid-round → degraded but correct; no money lost
Kill DB connection during a bet → clean rollback, no orphan ticket, no phantom deduction
Restart gateway mid-round → clients reconnect and resync correctly
Statistical: ≥1,000,000 simulated draws — uniform number frequency within tolerance, never a duplicate, always exactly draw_count. ≥1,000,000 tickets per pick count — empirical RTP converges to theoretical within tolerance.

Load: ramp to 1,000 / 2,500 / 5,000 / 10,000 concurrent users on the actual infrastructure (k6/Artillery). Report p50/p95/p99 bet latency, error rate, WebSocket fan-out latency, DB connections, CPU/RAM per container, full-round settlement time. Report real numbers including where it breaks and what the bottleneck was. If 10,000 isn't reachable on this VM, say so and report the measured ceiling and what would be needed.

Regression: a suite proving Bingo is unaffected — endpoints, rounds, wallet flows.

Reporting format for every claim: command run → actual output → PASS/FAIL → if FAIL, the fix. Untested items go in a dedicated "NOT TESTED" section.

PART 18 — DEPLOYMENT
Use the existing Docker Compose in ~/jo-bingo/deploy, existing Traefik, existing Cloudflare Tunnel, existing network and volumes. Add a Keno engine worker service only if Part 1 shows the existing worker architecture shouldn't absorb it — justify either way.

Migrations run through the existing mechanism, forward-compatible: migrations first, code second, so old container + new schema coexist safely.
Health checks and readiness for new services; depends_on/startup ordering; restart policies matching existing services.
Rollback plan, written and tested: kill switch → revert image → (only if necessary) down migration. Document what is safe to roll back after money has moved.
Confirm new tables are covered by the existing backup job; test a restore.
Nothing new exposed publicly. No change to unrelated routes or apps.
PART 19 — DOCUMENTATION (docs/keno/)
00-discovery.md · 01-architecture.md · 02-data-model.md · 03-api.md · 04-realtime-events.md · 05-paytable-and-rtp.md · 06-fairness-and-verification.md · 07-economics-and-bankroll.md · 08-runbook.md (3am: round stuck, settlement failing, engine down, how to void/refund, how to read the audit trail) · 09-admin-guide.md (Amharic + English) · 10-test-report.md · 11-load-test-report.md · 12-compliance.md

PART 20 — DEFINITION OF DONE
Tick only with evidence.

 Bingo unchanged and verified working in production
 Existing users, balances, transactions, auth intact
 Game Center shows both games; a third addable by config
 Keno rounds run continuously with overlapping cycle, zero dead time
 Board works on Android, iPhone, desktop Telegram, 360px screens
 Tickets validated server-side; every invalid case returns a typed error
 Draws are CSPRNG-derived, seed-committed, persisted, immutable, independently verifiable
 Draw function provably has no access to ticket data (signature + test)
 Realtime drawing works; reconnect resyncs correctly
 Matches and payouts correct, pinned to the round's paytable version
 Stake and settlement atomic and idempotent; double payout provably impossible
 Reserve reconciles exactly; liability shown separately from reserve
 Tier promotion/demotion works, pinned per round, audited
 Exposure cap and per-user share cap reject cleanly before money moves
 Daily circuit breaker demotes tier, affecting future rounds only
 Jackpot pool is ledger-backed and cannot exceed its balance (tested)
 Bonus balance is a separate ledger account with server-enforced playthrough
 Refund path works for failed/voided rounds
 History, results, statistics accurate from stored data
 Admin config, paytable with guardrails, simulator, reports, cohort analytics, audit all working
 All six revenue-model terms exposed as metrics
 Metrics, dashboard, alerts, structured logs live
 Responsible-gaming limits enforced across autoplay and multi-ticket
 All chaos/restart scenarios executed and passed with output shown
 Load results measured and honestly reported
 Migrations applied safely; rollback documented
 Kill switch verified
 No secrets exposed; no public surface added
 Documentation complete
 Zero fabricated claims
PART 21 — HOW TO PROCEED
Inspect the repo and ~/jo-bingo/deploy. Produce docs/keno/00-discovery.md.
Post a short summary of discovery findings and integration decisions.
Continue without waiting: migrations → domain/math → engine → workers → wallet → API → realtime → Mini App UI → admin → economics/analytics → monitoring → tests → chaos → load → deploy → verify Bingo → verify Keno → docs.
Report progress in phases with real command output. Flag blockers immediately and precisely.
Build it the way you would want it built if you were the one being woken at 3am when ten thousand people are mid-round.