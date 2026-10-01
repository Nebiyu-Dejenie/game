# Platform audit findings (2026-09-26 to 2026-09-29)

Raw output of the platform audit's finder agents: 8 of 12 finders completed
(the four whole-codebase sweeps never ran), 115 findings. **None was verified
by an agent.** A status other than "Not yet verified" means it was checked
in the code, and every "Fixed" item was reproduced by a test that fails on
the old code first. This file is the list future sessions work from; update
the status column as items are verified or fixed.

| # | Severity | Where | Finding | Status |
|---|---|---|---|---|
| 1 | critical | `packages/core/keno_tickets.py:365` | A player-supplied Keno idempotency_key goes straight into ledger.post's global key namespace, so a player can pre-empt or reuse any other operation's ledger key | Fixed, deployed (d24fc8a) |
| 2 | critical | `packages/core/keno_tickets.py:365` | Client-supplied idempotency_key is used verbatim as the global ledger idempotency key: free Keno tickets, and a way to silently cancel other players' payouts and deposits | Fixed, deployed (d24fc8a) |
| 3 | critical | `services/admin/queries.py:2206` | One Telebirr transfer can be credited twice: once by manual-deposit approval, once by SMS-evidence redemption | Not yet verified; to add to the Telebirr design (rail is off) |
| 4 | critical | `services/engine/round_engine.py:479` | drop_card refunds a stake that the round's void already refunded (player-triggered double refund) | Fixed, deployed (b583cf7) |
| 5 | critical | `services/engine/round_engine.py:769` | _transition_to_running un-voids an admin-voided lobby round; settlement then pays out stakes that were already refunded | Fixed, deployed (b583cf7) |
| 6 | critical | `services/gateway/fanout.py:189` | FanoutHub listener task dies permanently on any Redis error; nothing restarts it or reports it | Fixed, deployed (63ea8ed) |
| 7 | critical | `services/payments/payout_worker.py:108` | A payout already at 'processing' is sent to Chapa again on any redelivery, and a rejection of that repeat refunds a transfer that already went out | Fixed, deployed (42f191a / f6b7b09) |
| 8 | critical | `services/payments/payout_worker.py:159` | Any exception from create_payout, including a timeout after the request was sent, is treated as a definite failure and refunded | Fixed, deployed (42f191a / f6b7b09) |
| 9 | critical | `services/payments/telebirr_ingest.py:147` | Anyone can mint 'available' Telebirr evidence by texting a fake Telebirr SMS to the collection phone | Confirmed; rail disabled in production 2026-10-01 09:13 UTC (audit row #8); fix designed in docs/payments/telebirr-evidence-and-redemption-design.md |
| 10 | high | `packages/core/bonuses.py:221` | Bonus wagering progress counts stakes that were refunded (dropped cards, voided rounds), so a bonus can be cleared at zero risk and withdrawn | Fixed, deployed (b2f1ce0) |
| 11 | high | `packages/core/ledger.py:192` | ledger.post treats any existing transaction with the same key as success, without checking kind, round, payment or entries | Fixed, deployed (d24fc8a) |
| 12 | high | `services/admin/bonus_queries.py:178` | Manual bonus grant idempotency key is a timestamp: double-submit or retry grants twice | Fixed, deployed (a7603c5) |
| 13 | high | `services/admin/keno_queries.py:155` | Keno kill switch and config create silently reset reserve_withdrawal_floor, beta_restricted and the circuit-breaker multiple to defaults | Fixed, deployed (f95ea22) |
| 14 | high | `services/admin/queries.py:743` | Emergency stop tells every player of the last finished round their stake was refunded when nothing was refunded | Fixed, deployed (0e4ce63) |
| 15 | high | `services/bot/notification_relay.py:224` | Notification relay: one entry that always fails blocks all Telegram notifications, and the retry loop spins with no backoff | Fixed (0528b20), deployed 2026-10-01 |
| 16 | high | `services/engine/commands.py:67` | An unvalidated room_id lets any player create unlimited permanent Redis streams (room:{id}:cmds) | Fixed (bee89be), deployed 2026-10-01 |
| 17 | high | `services/engine/keno_round_engine.py:248` | Next round's autoplay tickets are placed before the previous round's settlement updates net_position, so stop-on-loss/win and manual Stop are overshot by one bet | Fixed (939a29b), deployed 2026-10-01 |
| 18 | high | `services/engine/keno_round_engine.py:591` | Stuck-round recovery refunds rounds whose draw is already persisted and revealed (drawing/draw_complete), cancelling winners' payouts | Fixed (be4f873), deployed 2026-10-01 |
| 19 | high | `services/engine/keno_round_engine.py:627` | Per-cycle sweep only retries 'settling'; a settlement task that dies before setting 'settling' leaves the round orphaned in 'draw_complete' (then refunded on the next restart) | Fixed (2e2e6a6), deployed 2026-10-01 |
| 20 | high | `services/engine/keno_round_engine.py:697` | _fail_and_refund_round selects pending tickets before locking the round row, so a ticket committing mid-refund is left 'pending' in a 'failed' round forever | Fixed (6b3899e), deployed 2026-10-01 |
| 21 | high | `services/engine/round_engine.py:438` | join() can commit a stake into a round that has just been voided; the stake is never refunded | Fixed, deployed (b583cf7) |
| 22 | high | `services/engine/round_engine.py:590` | Same-call auto-mark co-winners can miss the 50ms tie window because each claim awaits a DB insert before taking its timestamp | Fixed (66fe7e5), deployed 2026-10-01 |
| 23 | high | `services/engine/round_engine.py:1218` | Any Redis or DB error in the round loop kills the room's engine and voids the in-flight round | Fixed (b097979), deployed 2026-10-01 |
| 24 | high | `services/engine/round_engine.py:1325` | A Redis error on the command reply publish silently kills the room's only command consumer for good | Fixed (3feea9a), deployed 2026-10-01 |
| 25 | high | `services/gateway/app.py:513` | Per-IP Keno ticket limit (20/min) is shared by every player behind the same carrier CGNAT address | Confirmed (b1815fa, strict xfail); the limit is the operator's decision |
| 26 | high | `services/gateway/connection.py:390` | Each engine command holds a dedicated Redis connection for up to 5s; exhausting the 200-connection pool makes the fail-closed rate limiter block every player on the gateway | Fixed (bee89be), deployed 2026-10-01 |
| 27 | high | `services/gateway/connection.py:501` | Writer task death is never noticed; _cleanup then re-raises it and skips every unsubscribe (frozen client plus a growing hub leak) | Fixed (05c7309), deployed 2026-10-01 |
| 28 | high | `services/payments/deposits.py:298` | Chapa webhook dedupe key is the transaction reference only, without the status, so a later 'success' event can be discarded as a duplicate | Fixed (73573df), deployed 2026-10-01 |
| 29 | high | `services/payments/deposits.py:423` | Deposit polling has no per-item error isolation: one deposit that Chapa rejects aborts the fallback for every other player | Fixed (36ba6f5), deployed 2026-10-01 |
| 30 | high | `services/payments/deposits.py:423` | poll_pending_deposits has no per-row isolation, and 'processing' deposits never expire, so one bad row stops the webhook fallback for everyone | Fixed (36ba6f5), deployed 2026-10-01; expiring abandoned checkouts is a policy decision (strict xfail) |
| 31 | high | `services/payments/payout_worker.py:407` | A payout entry without 'our_ref' crashes the except handler, and the consumer task dies silently while the process looks healthy | Fixed (08341cd), deployed 2026-10-01 |
| 32 | high | `services/payments/telebirr_parser.py:83` | Parser amount regex silently truncates thousands-separated amounts (ETB 1,500.00 is read as 1) | In the Telebirr design (parser fixes) |
| 33 | high | `services/payments/telebirr_redemption.py:152` | Telebirr redemption trusts only knowledge of the reference; whoever submits it first gets another player's deposit | Confirmed; in the Telebirr design |
| 34 | high | `services/payments/withdrawals.py:180` | Seven-digit reference numbers truncate to six digits, so consecutive payment refs collide once payment_ref_seq reaches 1,000,000 | Fixed (797fe74), deployed 2026-10-01 |
| 35 | high | `services/payments/withdrawals.py:361` | sweep_stuck_approved_payouts re-enqueues payouts that are only waiting in the queue, not lost, and adds a new duplicate every tick | Fixed (c1e3077), deployed 2026-10-01 |
| 36 | medium | `packages/core/bonuses.py:90` | Concurrent welcome-bonus grants create two bonuses rows backed by one ledger credit, which poisons the bonus sweep for all players | Fixed (fc82a5f), deploy pending |
| 37 | medium | `packages/core/keno_autoplay.py:210` | Autoplay places a ticket after the player pressed Stop: stale session snapshot and no status re-check in the placement transaction | Already fixed (verified): place_ticket re-checks the session under a row lock |
| 38 | medium | `packages/core/keno_autoplay.py:221` | stop_on_loss / stop_on_win routinely overshoot by one round because round N+1's autoplay tickets are placed before round N's result is recorded | Fixed (939a29b, same as #17), deployed 2026-10-01 |
| 39 | medium | `packages/core/keno_autoplay.py:231` | A round filled to capacity by other players' bets permanently stops everyone else's autoplay sessions | Confirmed; skipping vs stopping on a round-level rejection is the operator's decision |
| 40 | medium | `packages/core/keno_autoplay.py:236` | rounds_placed and exhaustion are updated in separate transactions from the ticket placement, so a crash can buy one extra round | Fixed (50f5753), deployed 2026-10-01 |
| 41 | medium | `packages/core/keno_autoplay.py:273` | record_settlement applies an incremental delta after the money commits and is never replayed, so a crash leaves net_position (and the stop thresholds) permanently wrong | Partly fixed by 939a29b (stop-loss enforced from tickets at placement); stop_on_win and the session summary can still miss a result lost to a hard crash |
| 42 | medium | `packages/core/keno_business_metrics.py:137` | Business-metrics refresh loads the whole 24 h ticket set into the engine process and crunches it in pure Python on the round engine's event loop every 60 s | Not yet verified |
| 43 | medium | `packages/core/keno_tickets.py:202` | Replay short-circuit is not scoped to the user and runs before the per-user lock: cross-user ticket hijack, and a raw 500 on a concurrent retry | Already fixed by d24fc8a (verified); concurrent-retry test added (3ff3d57) |
| 44 | medium | `packages/core/ledger.py:215` | Every ledger.post locks the single global system-account balance row, serializing all players on pot_escrow, provider_settlement, keno_reserve and promo_expense | Not yet verified |
| 45 | medium | `services/admin/bonus_queries.py:178` | Admin manual bonus grant is not idempotent: the key embeds the server timestamp, so a double-click or retry grants twice | Fixed, deployed (a7603c5) |
| 46 | medium | `services/admin/keno_queries.py:580` | Reserve withdrawal floor check is released before the debit (TOCTOU across three transactions) | Not yet verified |
| 47 | medium | `services/bot/campaign_worker.py:171` | The campaign worker loads a whole campaign into the shared notification stream, so every transactional notification waits behind it | Not yet verified |
| 48 | medium | `services/bot/notification_relay.py:207` | The relay waits for the slowest recipient in each batch, so one player's Telegram backoff or starved campaign messages stall everyone | Not yet verified |
| 49 | medium | `services/engine/commands.py:89` | send_command leaks a pooled Redis connection whenever unsubscribe raises in its finally block | Not yet verified |
| 50 | medium | `services/engine/keno_round_engine.py:187` | Circuit breaker re-trips every round within the same 24h window, demoting one tier per round down to the floor | Fixed (c32384e), deployed 2026-10-01 |
| 51 | medium | `services/engine/keno_round_engine.py:270` | Ticket-id hash snapshot at betting close can miss tickets committed by in-flight placements | Not yet verified |
| 52 | medium | `services/engine/keno_round_engine.py:281` | Round transitions have no Postgres fence (no WHERE status = expected), and a worker that lost the lock mid-reveal still completes the draw and settles | Not yet verified |
| 53 | medium | `services/engine/keno_round_engine.py:432` | Round N's single-transaction settlement holds the keno_reserve balance-row lock while every round N+1 bet waits on it, holding the global round lock and a pool connection | Not yet verified |
| 54 | medium | `services/engine/keno_round_engine.py:442` | Whole-round settlement in one transaction holds the keno_reserve (and jackpot) balance-row lock, stalling every next-round bet until it commits | Not yet verified |
| 55 | medium | `services/engine/keno_round_engine.py:481` | Autoplay net_position is applied outside the settlement transaction, so a crash after commit skips it permanently | Partly fixed by 939a29b (as #41) |
| 56 | medium | `services/engine/keno_round_engine.py:523` | _settle_one_ticket posts the payout before claiming the ticket, and _pay_jackpot runs even when the claim failed | Fixed (9c06c90), deployed 2026-10-01 |
| 57 | medium | `services/engine/keno_round_engine.py:550` | Several 5/5 jackpot tickets in one round: the first in unordered fetch order takes the whole pool, the rest get nothing | Confirmed (strict xfail); the multi-winner rule is the operator's decision |
| 58 | medium | `services/engine/refunds.py:80` | The single global pot_escrow balance row serializes every Bingo money move in every room, and refunds hold it across all entrants | Not yet verified |
| 59 | medium | `services/engine/round_engine.py:348` | Emergency stop does not stop new stakes: the engine's join() idle fallback starts a round without checking rooms.is_active | Not yet verified |
| 60 | medium | `services/engine/round_engine.py:843` | Exhausted-round refund leaves the status at 'running', so a late claim is acknowledged and then the round is voided; the orphaned settlement task can crash the engine | Not yet verified |
| 61 | medium | `services/engine/round_engine.py:1280` | Commands whose gateway call already timed out still run later, charging players who were told the action failed | Not yet verified |
| 62 | medium | `services/engine/round_engine.py:1303` | The engine ignores the claim's round_id, so a stale claim is judged against the current round and can lock out a paid card | Not yet verified |
| 63 | medium | `services/gateway/app.py:514` | Keno ticket per-IP rate-limit bucket (20/min) is shared by every player behind the same carrier NAT | Not yet verified |
| 64 | medium | `services/gateway/app.py:657` | hot-cold endpoint's lookback_rounds is not clamped; one request can load all Keno history and block the gateway event loop | Fixed (f732569), deployed 2026-10-01 |
| 65 | medium | `services/gateway/fanout.py:80` | When a ConnectionQueue overflows with a non-droppable message, queued round_end/balance_update messages are discarded without triggering a resync | Not yet verified |
| 66 | medium | `services/payments/app.py:283` | payout_queue_depth uses XLEN on a stream that is never trimmed, so the depth alert is always on and cannot reveal a stalled consumer | Not yet verified |
| 67 | medium | `services/payments/bonus_sweep.py:32` | The bonus sweep has no per-item isolation: one failing bonus, or a Redis publish error, aborts the rest of the tick for every other player | Fixed (fc82a5f), deploy pending |
| 68 | medium | `services/payments/bonus_sweep.py:34` | The same wagering counts in full toward every active bonus a user holds at once | Not yet verified |
| 69 | medium | `services/payments/deposits.py:151` | The daily deposit cap is check-then-act with no per-user lock; concurrent intents or redemptions exceed it | Fixed (a31824d), deploy pending |
| 70 | medium | `services/payments/deposits.py:278` | The deposit webhook handler looks up the payment by our_ref without filtering on direction, so it can change a withdrawal's status | Fixed (b07aedd), deployed 2026-10-01 |
| 71 | medium | `services/payments/deposits.py:278` | _apply_confirmed_status never checks direction='in' or the provider on the payments row it locks | Fixed (b07aedd), deployed 2026-10-01 |
| 72 | medium | `services/payments/deposits.py:567` | run_provider_reconciliation aborts the whole report on one failing fetch_status | Not yet verified |
| 73 | medium | `services/payments/manual.py:79` | The manual (and automatic) daily deposit cap is checked and then inserted without a lock, so parallel requests exceed it | Fixed (a31824d), deploy pending |
| 74 | medium | `services/payments/payout_worker.py:403` | The payout loop retries a failing entry with no backoff, and that entry blocks every new payout | Not yet verified |
| 75 | medium | `services/payments/telebirr_ingest.py:186` | evidence_hash is computed over the raw bytes, so a re-delivery of the same SMS with only formatting differences flips live evidence to 'disputed' | Not yet verified |
| 76 | medium | `services/payments/telebirr_redemption.py:196` | Redeeming a 'rejected' evidence row hits an AssertionError instead of returning a code | Not yet verified |
| 77 | medium | `services/payments/withdrawals.py:118` | Withdrawal amounts are not rounded to cents, which creates a cent per withdrawal and a ledger-versus-balance mismatch | Not yet verified |
| 78 | medium | `services/payments/withdrawals.py:131` | Banned players can still withdraw, and small amounts auto-approve straight to Chapa | Fixed (f18bdda), deployed 2026-10-01: banned or limited accounts go to review |
| 79 | medium | `services/payments/withdrawals.py:151` | The chargeback window is measured from when the deposit was created, not when it was credited, so a player can easily get around it | Fixed (1b5c2cc), deployed 2026-10-01 |
| 80 | medium | `services/payments/withdrawals.py:250` | The 'withdrawals exceed deposits' review rule never fires for Chapa, because Chapa payouts never reach 'succeeded' | Not yet verified |
| 81 | medium | `services/payments/withdrawals.py:312` | A Redis error after the withdrawal commits reports failure for a withdrawal that exists, and a retry creates a second one | Fixed (ac047af), deploy pending |
| 82 | low | `packages/core/bonuses.py:122` | Bonus grant, convert and expire ledger transactions are never counted in ledger_transactions_total | Not yet verified |
| 83 | low | `packages/core/campaigns.py:93` | Notification Center audiences include simulated players | Not yet verified |
| 84 | low | `packages/core/keno_autoplay.py:146` | start_session surfaces expected races and validation errors as raw 500s | Not yet verified |
| 85 | low | `packages/core/keno_tier_automation.py:123` | No demotion when the reserve is below every tier's min_reserve (negative reserve) | Not yet verified |
| 86 | low | `packages/core/keno_tier_automation.py:221` | Circuit breaker demotes one tier every round while the 24 h window stays hot, and scans the whole ledger each round | Demotion half fixed with #50; the per-round 24h ledger scan remains |
| 87 | low | `packages/core/ledger.py:404` | publish_balance_update raises on a Redis error after the money has already committed, so callers lose the follow-up notification or abort their loop | Not yet verified |
| 88 | low | `packages/core/referrals.py:85` | Referral rewards are granted, and bonuses converted, regardless of the recipient's account status | Not yet verified |
| 89 | low | `packages/core/referrals.py:147` | The referral cap and welcome grant are check-then-act with no lock or constraint of their own, and bonuses.grant_txn_id is not UNIQUE (safe today only because of the provider_settlement lock) | Not yet verified |
| 90 | low | `packages/core/sms/messages.py:147` | SMS claim query ranks the tenant's entire message history on every fetch-job, while holding the node's row lock | Not yet verified |
| 91 | low | `services/admin/bonus_queries.py:142` | update_bonus_rule_admin fails on every numeric or date field edit (json.dumps of Decimal) | Not yet verified |
| 92 | low | `services/admin/keno_queries.py:408` | set_current_tier_admin records a stale from_tier and counts its metric before commit | Not yet verified |
| 93 | low | `services/admin/keno_queries.py:502` | Keno reserve deposit and withdrawal use a random uuid idempotency key, so a retried request moves money twice | Fixed (24d2649), deployed 2026-10-01 |
| 94 | low | `services/admin/queries.py:328` | Concurrent adjust_balance replays write two audit rows for one ledger transaction | Not yet verified |
| 95 | low | `services/admin/queries.py:581` | void_round_admin refunds silently and mislabels a voided zero-entrant round as unchanged | Not yet verified |
| 96 | low | `services/admin/queries.py:2239` | A Redis failure after commit turns committed money actions into HTTP 500s and drops the player notification | Not yet verified |
| 97 | low | `services/bot/notification_relay.py:92` | Money notifications with an unescaped admin-entered reason are silently dropped by Telegram's HTML parser | Not yet verified |
| 98 | low | `services/bot/notification_relay.py:132` | Transactional notifications are sent twice if the bot crashes between the Telegram send and XACK | Not yet verified |
| 99 | low | `services/engine/keno_round_engine.py:81` | Fire-and-forget publishes keep no reference and are never awaited; the try/except around the private ticket-settled publish cannot catch its failure | Not yet verified |
| 100 | low | `services/engine/keno_round_engine.py:179` | Gauge and tier-automation failures in _create_round abort the round cycle after the round row is committed | Not yet verified |
| 101 | low | `services/engine/keno_round_engine.py:257` | Betting timer starts after autoplay placement, and a resumed betting_open round gets a fresh full window, so client countdowns don't match the real close | Not yet verified |
| 102 | low | `services/engine/keno_round_engine.py:275` | _close_betting reads ticket ids before taking the round row lock, so a ticket committing at close is missing from ticket_ids_hash and ticket_count | Not yet verified |
| 103 | low | `services/engine/recovery.py:76` | Recovery has no per-round isolation, and it runs ahead of room claiming on every poll | Not yet verified |
| 104 | low | `services/engine/round_engine.py:407` | Bingo join reads users.status without a row lock, so a concurrent ban or self-exclusion can let one more stake through | Not yet verified |
| 105 | low | `services/engine/round_engine.py:462` | A publish failure after join or drop_card commits turns a real stake or refund into an 'internal_error' reply | Not yet verified |
| 106 | low | `services/engine/simulated_players_worker.py:223` | A simulated player's room assignment is lost when send_command raises partway through its joins | Not yet verified |
| 107 | low | `services/engine/worker.py:142` | Dead engine tasks are replaced without their exception ever being retrieved or logged | Not yet verified |
| 108 | low | `services/gateway/app.py:429` | Withdrawal endpoints take no client idempotency key, so a double-tap or retry creates two withdrawals | Not yet verified |
| 109 | low | `services/payments/app.py:149` | Ingest route crashes with a 500 on JSON bodies that are not objects or whose raw_sms is not a string | Not yet verified |
| 110 | low | `services/payments/bonus_sweep.py:43` | The sweep converts before it checks expiry, and counts stakes placed after expires_at | Not yet verified |
| 111 | low | `services/payments/deposits.py:334` | Every deposit on every rail serializes on the single provider_settlement balance row until commit | Not yet verified |
| 112 | low | `services/payments/deposits.py:374` | A Redis error after commit skips the deposit notification and turns a committed credit into an error | Not yet verified |
| 113 | low | `services/payments/ledger_reconcile_sweep.py:35` | The ledger reconciliation gauges are never updated when the check itself fails, so a broken check looks like 'no mismatch' | Not yet verified |
| 114 | low | `services/payments/payout_worker.py:162` | A Redis error after a refund commits skips the player's 'withdrawal failed' message for good | Not yet verified |
| 115 | low | `services/payments/telebirr_reconcile.py:50` | Hourly Telebirr reconciliation query is quadratic: correlated count(*) on the unindexed payment_evidence.payment_id | Not yet verified |

## Details

Trigger, impact and suggested fix as the finder agents wrote them.

### 1. A player-supplied Keno idempotency_key goes straight into ledger.post's global key namespace, so a player can pre-empt or reuse any other operation's ledger key

- **Severity** critical, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_tickets.py:365`
- **Status** Fixed, deployed (d24fc8a)
- **Trigger** Any player on the Keno allowlist POSTs /api/keno/tickets (services/gateway/app.py:491-529; the model is a bare `idempotency_key: str` with no prefix, pattern or user scoping) with an idempotency_key equal to another operation's ledger key. The keno_tickets lookup at keno_tickets.py:199 only searches keno_tickets. ledger.post(kind='keno_stake', idempotency_key=<raw>) then either (a) finds an existing key, e.g. 'settle-5' or 'DEP-2026-000123', and returns that foreign transaction with no entries and no InsufficientFunds check, or (b) takes a key that will exist later. Server-generated keys are easy to guess: 'settle-{round_id}' (round ids are broadcast), 'DEP-/WD-{year}-{payment_ref_seq}' (sequential, and a player sees their own refs), 'welcome-{user_id}-{rule_id}-0', 'referral-{referrer}-{referee}', 'bonus-convert-{bonus_id}', 'keno:settle:{round}:{ticket}', 'autoplay:{session}:{round}'.
- **Impact** (a) Free bets that create money. The ticket is inserted with stake_txn_id pointing at someone else's transaction and the player is never debited, so they need no balance at all. They can win from keno_reserve, or get a real refund if the round fails. There is one free ticket per existing ledger key, and there are thousands of keys. (b) Other players lose money or get blocked. Pre-empting 'settle-{next_round}' makes that Bingo round's settlement post a no-op: winners get round_winners rows but no cash. Pre-empting a deposit's our_ref marks it 'succeeded' without crediting user_cash. Pre-empting 'welcome-{uid}-{rule}-0' or 'referral-..' makes grant_bonus hit `assert existing is not None` (bonuses.py:78). maybe_grant_* only catch UniqueViolationError, so the victim's whole deposit transaction rolls back on every webhook retry, poll, admin approval or telebirr redemption. Because users.id is sequential, one attacker can do this to every future new user's first deposit. Pre-empting 'bonus-convert-{id}' flips the victim's bonus to 'converted' without moving the money, leaving it stranded in user_bonus. Pre-empting 'WD-..' skips the cash-to-locked move of a withdrawal that then still gets paid out. Pre-empting 'autoplay:{s}:{r}' makes another player's autoplay count a round it never bet.
- **Suggested fix** Never pass a client string raw as a ledger key. In _place_ticket use ledger_key = f"keno:stake:{user_id}:{client_key}", or better derive it from the ticket id. Also scope the keno_tickets idempotency lookup and unique index to (user_id, idempotency_key). Validate the client key's format and length (e.g. a UUID) at the gateway. Also add the ledger.post kind/shape check from the next finding.

### 2. Client-supplied idempotency_key is used verbatim as the global ledger idempotency key: free Keno tickets, and a way to silently cancel other players' payouts and deposits

- **Severity** critical, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_tickets.py:365`
- **Status** Fixed, deployed (d24fc8a)
- **Trigger** POST /api/keno/tickets (services/gateway/app.py:522-528 passes body.idempotency_key straight through; the only check is that it is non-empty) with idempotency_key set to a key that already exists, or will exist, in ledger_transactions but not in keno_tickets. Examples: 'settle-<bingo round id>' (Bingo round ids are broadcast to room clients), 'stake-<round>-<user>-<card>', 'DEP-2026-000123' or 'WD-2026-000124' (sequential refs from the shared payment_ref_seq, and our_ref is returned to the requester), 'keno:settle:<R>:<T>' (sequential ticket ids). Lines 202-205 find no keno_tickets row. ledger.post() hits ON CONFLICT (idempotency_key) DO NOTHING and returns the EXISTING transaction of whatever kind (ledger.py:192-205) before any balance check. place_ticket never checks stake_txn.kind or whether the transaction is new, and inserts the ticket with stake_txn_id pointing at someone else's transaction.
- **Impact** (a) Money creation: the ticket is pending and counted in keno_rounds.total_stake, but the player's user_cash is never debited and InsufficientFunds never runs. It settles normally: a win is paid from keno_reserve, and a failed round refunds the stake that was never taken. Every past Bingo round, Bingo card, deposit and won Keno ticket supplies one reusable key, so a player can place max_tickets_per_user_per_round free tickets every round (EV about 0.82 x stake each). (b) Cross-player theft or griefing: pre-claiming a FUTURE key makes the real operation a silent no-op. With 'settle-<next bingo round>', that round's winners get round_winners rows but no credit and the pot stays in pot_escrow. With 'DEP-2026-<next n>', other players' paid deposits are marked succeeded but never credited. With 'keno:settle:R:T' or 'keno:jackpot:R:T', another player's Keno win or jackpot is recorded as paid but never credited. With 'payout-reverse-WD-…', a failed withdrawal's funds stay locked forever. Pre-claiming one's own next 'WD-…' ref makes the withdrawal lock nothing (no funds check) before the payout worker sends real money out. Each attack costs the attacker one normal stake.
- **Suggested fix** Never use a client string as a ledger key. In place_ticket, build ledger_key = f"keno:stake:{user_id}:{idempotency_key}" and use it for both keno_tickets.idempotency_key and ledger.post; validate the client key's charset and length (e.g. [A-Za-z0-9_-]{1,64}) at the gateway. As a second line of defence, after post() raise if stake_txn.kind != 'keno_stake' (better: have post() report whether it created the row and refuse to attach a pre-existing transaction). Audit existing keno_tickets whose stake_txn_id points at a non-keno_stake transaction.

### 3. One Telebirr transfer can be credited twice: once by manual-deposit approval, once by SMS-evidence redemption

- **Severity** critical, **fix size** large, **finder confidence** medium
- **Where** `services/admin/queries.py:2206`
- **Status** Not yet verified; to add to the Telebirr design (rail is off)
- **Trigger** Precondition: both the 'manual' in and 'telebirr_sms' in rails are enabled, with an active telebirr manual_payment_destination. Telebirr ingestion checks the recipient against that same manual_payment_destinations table (telebirr_ingest._find_matching_recipient). So every real transfer to the destination becomes an 'available' payment_evidence row. The player pays X once. They redeem the SMS reference in the bot or Mini App (redeem_evidence credits X). They also file a manual deposit request with the same Telebirr transaction ID and the real receipt photo. The admin sees a genuine receipt and possible_duplicate_reference=false, because line 2066-2073 only compares against other provider='manual' rows, and redemption's payments row has no provider_ref. The admin approves and approve_manual_deposit_admin credits X again, keyed on its own our_ref. The reverse order also works and needs no admin mistake: the manual deposit is approved first, then the player redeems the still-'available' evidence. Neither path reads the other rail's record of the reference.
- **Impact** Money is created: 2X credited for one X transfer, then withdrawable. The player controls both steps. The only human check (admin review of the manual request) sees a real receipt. The Telebirr design doc in 6dbd492 does not cover this cross-rail case.
- **Suggested fix** In approve_manual_deposit_admin, SELECT payment_evidence WHERE external_reference = normalize_reference(provider_ref) FOR UPDATE. Refuse if it is 'redeemed'. If it is 'available', mark it 'redeemed' with this payment_id in the same transaction. In redeem_evidence, refuse a reference that a succeeded or in-review manual deposit already carries, after normalizing. Extend the list's duplicate flag to cover evidence. The durable fix is one UNIQUE 'consumed external reference' table that both rails insert into.

### 4. drop_card refunds a stake that the round's void already refunded (player-triggered double refund)

- **Severity** critical, **fix size** small, **finder confidence** high
- **Where** `services/engine/round_engine.py:479`
- **Status** Fixed, deployed (b583cf7)
- **Trigger** Case 1, no admin needed: a room with min_players=2 has a single player holding a card. The lobby deadline passes underfilled, so _run_lobby calls refunds.refund_round (line 725). The in-memory status stays 'lobby' and _entries stays populated through refund_round, the balance-publish gather and the round_voided publish, until _reset_to_idle at line 756. A drop_card command processed by the concurrent _serve_commands task in that window passes the in-memory checks (lines 467-471). Its ledger.post waits on the pot_escrow row lock that refund_round holds, then posts 'drop-{R}-{U}-{C}' after refund_round commits 'refund-{R}-{U}-{C}'. The two keys differ, so both refunds go through. The DELETE and the rounds UPDATE have no status guard. Case 2: void_round_admin or stop_room_admin (services/admin/queries.py:558/636) voids a round in 'lobby'. The engine is never told, so any drop_card for the rest of that lobby (up to 60s) double-refunds.
- **Impact** Money is created: the player gets their stake back twice and pot_escrow (not a user-balance kind, so it can go negative) absorbs it. A player can do this on purpose by spamming drop_card at the countdown end of an underfilled room (the gateway's drop_card has no rate-limit bucket, connection.py:274). It pays +stake per card, up to max_cards_per_player (3), in every underfilled round.
- **Suggested fix** Inside drop_card's transaction, first run `UPDATE rounds SET pot = pot - $1, player_count = player_count - 1 WHERE id = $2 AND status = 'lobby' RETURNING id`, or `SELECT status ... FOR UPDATE`. Do it BEFORE ledger.post and roll back with 'not_droppable' if no row comes back. Also `DELETE ... RETURNING` the entry and abort if it is already gone. In _run_lobby, flip the in-memory status off 'lobby' (for example to a 'voiding' state) before awaiting refund_round, so drop_card and join are refused in-process too.

### 5. _transition_to_running un-voids an admin-voided lobby round; settlement then pays out stakes that were already refunded

- **Severity** critical, **fix size** small, **finder confidence** high
- **Where** `services/engine/round_engine.py:769`
- **Status** Fixed, deployed (b583cf7)
- **Trigger** An admin runs void_round_admin or stop_room_admin (services/admin/queries.py:558, 636) on a room whose live engine is in 'lobby' with at least min_players. refund_round_in_transaction refunds every entrant and sets status='voided'. The engine does not subscribe to room:{id} and only re-reads rooms.is_active between rounds, so it keeps ticking the lobby. At the deadline, player_count() still counts the refunded entries and _transition_to_running runs `UPDATE rounds SET status='running' ... WHERE id=$1` with no status guard, flipping voided back to running. _call_next_number's `WHERE status='running'` guard now passes. When someone wins, _settle_with_winners' FOR UPDATE check sees 'running' (not terminal) and posts pot_escrow -self._pot with shares to the winners and the cut to house_revenue. self._pot is the in-memory pot and includes every already-refunded stake. The same path opens if recovery voids a live lobby after a lost lock and the engine has not noticed yet. test_stop_lobby_room_refunds_joined_players stops the engine before the lobby deadline, so this path is untested.
- **Impact** Money is created, equal to the whole pot. Example: 3 x 20 ETB stakes are refunded (+60 to players), then the winner gets the derash and house_revenue gets the cut, all from pot_escrow, which ends 60 lower with nothing behind it. The admin's void or emergency stop is silently reversed and a full round plays out in a room the operator stopped.
- **Suggested fix** Make the transition conditional: `UPDATE rounds SET status='running', ... WHERE id=$1 AND status='lobby' RETURNING id`. If no row comes back, log it and _reset_to_idle() without running. As defense in depth, have _settle_with_winners read `status, pot` in its FOR UPDATE select and settle from the DB pot, refusing if it differs from self._pot.

### 6. FanoutHub listener task dies permanently on any Redis error; nothing restarts it or reports it

- **Severity** critical, **fix size** small, **finder confidence** high
- **Where** `services/gateway/fanout.py:189`
- **Status** Fixed, deployed (63ea8ed)
- **Trigger** Redis becomes unreachable for longer than redis-py 8.1's built-in retry budget (10 retries with backoff capped at 1s, about 5s total; the reconnect inside the retry callback retries too and then raises). A Redis container restart, an OOM-kill or a host blip is enough. Any other unexpected exception in _listen has the same effect. `async for message in self._pubsub.listen()` raises ConnectionError and _listen exits. _listener_task (created at line 149) is never awaited until stop(), so nobody notices. /healthz pings a different pooled connection and still returns ok.
- **Impact** Every player connected to that gateway stops receiving every broadcast until the gateway process is restarted by hand: Bingo calls, round_start/round_end, card_taken, balance_update and all keno:live events. The sockets stay open and ping/pong still works (the reader handles it), so clients never reconnect. Commands still go through because each one uses its own pubsub, so players keep paying for cards in rounds they cannot see. Manual-mark players cannot claim and lose their stakes. Even a short blip that the retry does survive silently loses the messages published during the gap, and no state_sync is forced afterwards.
- **Suggested fix** Wrap _listen in a supervising loop: catch Exception (let CancelledError through), log it, sleep with backoff, re-create the pubsub and psubscribe again. After each (re)subscribe, set needs_state_sync and the wake event on every live ConnectionQueue. Add a done-callback on the task that logs and restarts it. Make /healthz fail when the listener task is done.

### 7. A payout already at 'processing' is sent to Chapa again on any redelivery, and a rejection of that repeat refunds a transfer that already went out

- **Severity** critical, **fix size** small, **finder confidence** medium
- **Where** `services/payments/payout_worker.py:108`
- **Status** Fixed, deployed (42f191a / f6b7b09)
- **Trigger** The worker commits approved->processing (line 134) and then calls create_payout. The same stream entry, or a copy of it, then comes back through any of these: (a) a deploy or SIGTERM during the Chapa call (main_async cancels consumer_task mid-await, CancelledError is not caught, the entry stays unacked, and the new container re-reads its pending list); (b) a Redis blip on xack at line 218, or a DB blip on the provider_ref UPDATE at line 211, so the entry stays pending and is re-read at once; (c) a duplicate entry from sweep_stuck_approved_payouts (next finding). On the second pass status='processing' is in _PENDING_STATUSES (line 69), so the code reaches create_payout(our_ref) at line 158 again. ChapaProvider.create_payout (chapa.py:238) raises RuntimeError for any response that is not a 200/201 'success', which includes a duplicate-reference rejection. That lands in the except branch, which calls _reverse (line 161).
- **Impact** _reverse moves user_locked->user_cash, marks the payment 'failed' and sends 'withdrawal failed', while the first transfer is already queued or delivered. The player receives the payout and also gets the stake back to spend or withdraw again. The house loses the full withdrawal amount. Nothing reconciles outbound payments, so the loss is invisible. If Chapa does not dedupe the reference, the transfer is paid twice instead. The code is only safe if Chapa returns 'success' for a repeated reference, and the codebase has never verified that (DECISIONS.md: 'trusting the provider').
- **Suggested fix** Stop re-calling create_payout for a row that is already 'processing'. On redelivery, ack, log and leave it for list_stuck_processing_payouts or manual resolution; later, query the transfer-status endpoint instead. Claim the row atomically with UPDATE payments SET status='processing' WHERE id=$1 AND status='approved' RETURNING and dispatch only if a row comes back. Make _reverse and _settle_success conditional on the status they expect (WHERE status='processing') under FOR UPDATE.

### 8. Any exception from create_payout, including a timeout after the request was sent, is treated as a definite failure and refunded

- **Severity** critical, **fix size** small, **finder confidence** high
- **Where** `services/payments/payout_worker.py:159`
- **Status** Fixed, deployed (42f191a / f6b7b09)
- **Trigger** Chapa accepts the POST /v1/transfers, but the response never arrives cleanly: an httpx ReadTimeout after 15s, a connection reset, an HTML 502 from an edge proxy (response.json() at chapa.py:237 raises JSONDecodeError), or a 5xx. All of these raise from create_payout. The except Exception at line 159 then calls _reverse, publish_balance_update, a 'withdrawal failed' notification and xack.
- **Impact** The refund moves the locked amount back to user_cash and the payment becomes 'failed', a terminal state, while Chapa may still complete the transfer. The player is paid and refunded: the house loses the full amount. There is no outbound reconciliation (run_provider_reconciliation only looks at direction='in'), so this is never detected.
- **Suggested fix** In chapa.py, raise separate exception types: a definite rejection (a 4xx with a parsed Chapa 'failed' envelope) versus an ambiguous outcome (timeout, transport error, 5xx, unparseable body). In process_one, reverse only on a definite rejection. On an ambiguous error, leave the row at 'processing', record the error and ack, so it surfaces in list_stuck_processing_payouts for manual verification.

### 9. Anyone can mint 'available' Telebirr evidence by texting a fake Telebirr SMS to the collection phone

- **Severity** critical, **fix size** large, **finder confidence** high
- **Where** `services/payments/telebirr_ingest.py:147`
- **Status** Confirmed; rail disabled in production 2026-10-01 09:13 UTC (audit row #8); fix designed in docs/payments/telebirr-evidence-and-redemption-design.md
- **Trigger** 1) A player calls GET /api/manual-payment-destinations (gateway/queries.py:60). It returns the telebirr destination's account_ref (the collection SIM's phone number) and account_name to any logged-in player. 2) From an ordinary phone, the player sends a plain SMS to that number: 'Dear <account_name> You have received ETB 5000.00 from X(2519****1234) on 26/09/2026 10:00:00. Your transaction number is ZZ12345678.' 3) MacroDroid's trigger is only 'Message Content contains Your transaction number is'. docs/TELEBIRR_SMS_OPERATIONS_GUIDE.md:209 explicitly says 'Do not filter on sender number', so the macro POSTs the text to /internal/telebirr/ingest. The payload is only raw_sms and device_id (app.py:70), so the server never learns who sent the SMS. 4) parse_telebirr_sms accepts it as the 'received' template. _find_matching_recipient accepts it on the name alone, because this template carries no recipient phone. The row is inserted with status='available'. 5) The player pastes the same text into the bot, and redeem_evidence credits 5000.
- **Impact** Money is created from nothing: user_cash is credited against provider_settlement with no real Telebirr transfer behind it. Any player can repeat it with a new fake reference each time, up to the daily deposit cap. Withdrawals under the auto-approve limit then pay out real ETB through Chapa. The 'transferred' template works too, since the name and the masked account_ref phone are both public. The same text can also reach ingestion through a Telegram payment agent who is tricked into forwarding it.
- **Suggested fix** Treat the SMS text as untrusted until something outside the text confirms it. Have MacroDroid send [sms_number] and accept only Telebirr's sender ID(s), and reject everything else server-side. Also add a second signal: the 'current E-Money balance' in each SMS should equal the previous balance plus the amount, or verify against Telebirr's receipt or transaction API, or require admin confirmation above a small threshold. Until then, consider disabling auto-'available' for the MacroDroid path.

### 10. Bonus wagering progress counts stakes that were refunded (dropped cards, voided rounds), so a bonus can be cleared at zero risk and withdrawn

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `packages/core/bonuses.py:221`
- **Status** Fixed, deployed (b2f1ce0)
- **Trigger** A player with an active bonus (welcome, referral or manual) takes a card in any Bingo lobby (a 'stake' txn, user_cash -stake) and drops it (drop_card posts kind 'refund', round_engine.py:479-484), then repeats on a different card. The TAKE_CARD bucket allows 10 per minute. wagering_progress_for_user_since sums only lt.kind='stake' on user_cash and never subtracts 'refund' entries. Voided-round refunds (refunds.py:90-97) count the same way.
- **Impact** Within a minute or two the player reaches wagering_required (5 x 3 = 15 ETB for the current welcome rule, 10 x 3 = 30 for referral) without risking anything. The next 60 s sweep converts the bonus into withdrawable user_cash. Combined with sock-puppet referrals (the only fraud check is a shared payout account), every referee's qualifying deposit becomes free withdrawable house money for the referrer. The daily loss cap already nets out refunds (today's fix), but this query does not. Separately, Keno stakes (kind 'keno_stake') never count, so Keno-only players can never clear a bonus.
- **Suggested fix** Compute net wagering: the sum of stake debits minus the refund credits for those same stakes (join refunds back to their round/card, or sum user_cash entries whose kind is in ('stake','keno_stake') minus ('refund','keno_refund') since the grant). Only count stakes whose round actually settled ('done'), not ones still in a lobby. Rounds still in the lobby could also be excluded by joining round_entries/rounds status.

### 11. ledger.post treats any existing transaction with the same key as success, without checking kind, round, payment or entries

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `packages/core/ledger.py:192`
- **Status** Fixed, deployed (d24fc8a)
- **Trigger** Any caller posts with a key that already belongs to a different operation: a player-chosen Keno key (above), an admin-chosen request_id in adjust_balance (services/admin/queries.py:327-345 uses the client string raw), or any future key-format overlap. The ON CONFLICT DO NOTHING branch returns the existing row as-is.
- **Impact** The caller's money movement is silently dropped while the caller carries on as if it happened: it flips payments/bonuses/rounds status and records the foreign txn id as ledger_txn_id, stake_txn_id or convert_txn_id. InsufficientFunds is skipped too. This is what turns any key collision into lost or created money rather than a loud error. ledger.reconcile() cannot detect it, because the cache and the entries still agree.
- **Suggested fix** In the txn_row-is-None branch, compare existing.kind with kind (and round_id/payment_id when given). Optionally compare the stored entries (account_id, amount) against the requested ones. On mismatch raise a new IdempotencyKeyConflict instead of returning. The adjust_balance pre-check at admin/queries.py:327 should do the same comparison.

### 12. Manual bonus grant idempotency key is a timestamp: double-submit or retry grants twice

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/admin/bonus_queries.py:178`
- **Status** Fixed, deployed (a7603c5)
- **Trigger** The key is f"manual-grant-{admin_id}-{user_id}-{now().timestamp()}", which is unique on every call. The same flaw was already fixed in adjust_balance. The bonuses.js manualGrantForm submit handler neither disables the button nor sends a request_id, so a double-click (two submit events) or a retried POST posts two bonus_grant transactions and two bonuses rows.
- **Impact** The player gets 2x the bonus. Each bonus's wagering progress is computed independently over the same stake history since its created_at (bonus_sweep), so one set of stakes clears both, and both convert to withdrawable cash with no extra wagering. The route also uses a bare .strip() check rather than _require_reason, so 'ok' passes as a reason.
- **Suggested fix** Require a client request_id (crypto.randomUUID() per click, as users.js does) and key on manual-grant-{admin_id}-{user_id}-{request_id}. Disable the submit button while the request is in flight. Use _require_reason on the grant and revoke routes.

### 13. Keno kill switch and config create silently reset reserve_withdrawal_floor, beta_restricted and the circuit-breaker multiple to defaults

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/admin/keno_queries.py:155`
- **Status** Fixed, deployed (f95ea22)
- **Trigger** set_keno_enabled_admin says it copies the active config's every other field, but its INSERT lists only 13 columns. It omits reserve_withdrawal_floor (default 0), beta_restricted (default true), daily_payout_circuit_breaker_multiple (default 3.0), number_pool_size and draw_count. create_config_admin (line 110) has the same gap, and the API models have no field for any of them, so they can only be set by SQL. Example: an operator sets floor=50000, a 1.5x breaker, or beta_restricted=false for general availability. Later someone presses 'Disable Keno now' or 'Enable Keno'.
- **Impact** The new active row has floor 0. withdraw_from_reserve_admin's floor check (line 538) then lets the entire prize reserve be withdrawn, and keno_reserve is not a guarded kind in ledger.post, so it can go negative. The circuit breaker loosens to 3x. A GA launch reverts to allowlist-only, locking every non-allowlisted player out after an emergency toggle. None of this shows in the audit row, which records only keno_enabled.
- **Suggested fix** Build the kill-switch row as INSERT INTO keno_configs SELECT ... FROM keno_configs WHERE id = current.id, overriding only version, keno_enabled, created_by_admin_id and effective_from. Add the missing fields to create_config_admin and CreateKenoConfigRequest, defaulting to the current row's values. Add a test asserting that every column except keno_enabled survives a toggle. Also serialize version (lock or UNIQUE): MAX(version)+1 has neither.

### 14. Emergency stop tells every player of the last finished round their stake was refunded when nothing was refunded

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/admin/queries.py:743`
- **Status** Fixed, deployed (0e4ce63)
- **Trigger** stop_room_admin picks the room's latest round whatever its status and reads its entrants before refund_round_in_transaction. That call returns 0 for a 'done' or 'voided' round. The notify block is gated on refunded_user_ids, not refunded_count. So an admin stopping a room between rounds, which rooms.js explicitly offers ('no active round right now -- nothing to refund'), or retrying or double-submitting a stop, sends notify.room_emergency_stopped. It also broadcasts round_voided for a finished round.
- **Impact** Up to max_players real players get a Telegram message reading 'Your stake of X ETB has been refunded to your wallet' for a refund that never happened. Players watching that round's result screen get round_voided, so winners see their win apparently voided. Even when a refund does happen, the amount is rooms.stake (the current config, which may have been edited since), not the per-player total, so a 3-card player is told a third of what came back. Expect support disputes and loss of trust in money messages.
- **Suggested fix** Notify and broadcast only when refunded_count > 0. Compute each user's refunded amount as rounds.stake multiplied by their card count, or from the refund ledger rows, and pass that as amount. Read the entrants after refund_round_in_transaction has taken the round lock.

### 15. Notification relay: one entry that always fails blocks all Telegram notifications, and the retry loop spins with no backoff

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/bot/notification_relay.py:224`
- **Status** Fixed (0528b20), deployed 2026-10-01
- **Trigger** run_forever always reads this consumer's pending list first (`xreadgroup(..., {STREAM: '0'}, count=10)`) and only reads new entries ('>') when nothing is pending. If process_one raises, _drain_one_user logs the error and does not XACK, so the entry stays pending. The next iteration returns the same entry, fails again, and never reaches '>'. A concrete deterministic failure: an admin saves a Bot Content override for notify.deposit_confirmed containing '{amount:,}' or a literal '{}'. bot_content_queries.py:82-83 accepts it because required_placeholders ignores format specs and unnamed fields. i18n.t()'s template.format() then raises ValueError or IndexError for every such entry. A deploy where payments sends a notify key the older bot doesn't have yet raises KeyError the same way.
- **Impact** Every player stops getting transactional Telegram messages: deposit confirmations, withdrawal succeeded/failed/rejected, emergency-stop refunds, and campaigns. Nothing reports it; the only signal is log spam. The bot process runs this loop hot with no sleep (Redis read, DB language lookup, exception trace every pass), which also slows webhook handling for everyone. Transient DB outages cause the same spin.
- **Suggested fix** Track failures per entry, from XPENDING's delivery count or an in-memory counter. After N attempts, XACK the entry, copy it to a dead-letter stream and bump a metric. Always read '>' as well as pending entries, or cap how many pending entries are retried per loop. Sleep with backoff after a batch that had failures. Make required_placeholders reject format specs, conversions and positional fields, and do a test render with dummy kwargs before saving an override.

### 16. An unvalidated room_id lets any player create unlimited permanent Redis streams (room:{id}:cmds)

- **Severity** high, **fix size** small, **finder confidence** medium
- **Where** `services/engine/commands.py:67`
- **Status** Fixed (bee89be), deployed 2026-10-01
- **Trigger** A player sends set_auto or drop_card frames with a fresh random integer room_id each time. connection.py:390 only checks isinstance(int). send_command XADDs to stream_key(room_id), which creates a new stream key. No engine ever reads or trims it, and it has no TTL. At about 30 frames/s per account (spread across sockets, since each socket waits 5s for a reply that never comes), that is roughly 2.6M new keys per account per day.
- **Impact** Redis memory grows without bound. deploy/docker-compose.prod.yml sets no maxmemory, and the host also runs Postgres. The same Redis holds room locks, Keno state, rate limits, dedup keys and the payout and notification streams, so eventual Redis OOM or host memory pressure takes the whole platform down for every player.
- **Suggested fix** Validate room_id against active rooms, from a DB-backed cache, before any XADD, as in the previous finding. As defense in depth, set maxmemory with a noeviction policy and alert on the Redis key count.

### 17. Next round's autoplay tickets are placed before the previous round's settlement updates net_position, so stop-on-loss/win and manual Stop are overshot by one bet

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/engine/keno_round_engine.py:248`
- **Status** Fixed (939a29b), deployed 2026-10-01
- **Trigger** _run_one_round spawns round N's settlement as a background task (line 155), then immediately creates round N+1 and calls place_for_active_sessions (line 248). That call snapshots status='active' sessions once (keno_autoplay.py:210) and places a ticket for each without re-checking status; place_ticket never looks at the session. N's record_settlement, which updates net_position and stops a session at stop_on_loss/stop_on_win, runs only after N's batch transaction commits and after the per-ticket publishes ahead of it in the post-commit loop. In practice that is after the snapshot. A player who taps Stop after the snapshot, while their placement is still waiting (it queues behind N's settlement lock), is also still charged.
- **Impact** A player whose round-N result reaches their configured stop-loss (or stop-win) is charged for one more real-money ticket in N+1. The module says the server-side stop exists because the client can't be trusted for real money, yet it lets one extra bet through per session end. A manual Stop can be followed by a charge.
- **Suggested fix** In _place_for_session, claim the session atomically before placing: UPDATE keno_autoplay_sessions ... WHERE id=$1 AND status='active' RETURNING, or lock the session row FOR UPDATE inside place_ticket's transaction and re-check status. For stop-on-win/loss, skip a session while its last_round_id ticket is still 'pending', or apply net_position inside the settlement transaction and run autoplay placement only after that.

### 18. Stuck-round recovery refunds rounds whose draw is already persisted and revealed (drawing/draw_complete), cancelling winners' payouts

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/engine/keno_round_engine.py:591`
- **Status** Fixed (be4f873), deployed 2026-10-01
- **Trigger** The engine process dies (OOM, SIGKILL, host reboot, or a Postgres outage that makes every run_forever retry fail in recover_on_startup) while round R is in 'drawing' (the roughly 12s reveal, about a third of every ~37s cycle) or 'draw_complete'. No run_forever start succeeds until more than 300s after R.scheduled_at, which is about 4.4 minutes after the crash. recover_on_startup exempts only status == 'settling' (line 586). For R, _round_age_seconds() > 300, so it calls _fail_and_refund_round(R).
- **Impact** R's drawn_numbers are persisted, immutable (trigger), and were partly or fully broadcast via keno.number.drawn / keno.draw.completed. Every pending ticket gets its stake refunded instead of being settled. Winners, including a 5/5 jackpot hit, lose their winnings. Losers get their stake back out of keno_reserve. The round is marked failed with a public draw. The code's own comment (lines 576-585) and the runbook argue that refunding a drawn round is wrong, but the rule is applied only to 'settling'.
- **Suggested fix** In recover_on_startup, add drawn_numbers to the stuck_rows SELECT and send every round with drawn_numbers IS NOT NULL (drawing, draw_complete, settling) to _resume_round regardless of age. Apply the age-based fail+refund only to scheduled/betting_open/betting_closed.

### 19. Per-cycle sweep only retries 'settling'; a settlement task that dies before setting 'settling' leaves the round orphaned in 'draw_complete' (then refunded on the next restart)

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/engine/keno_round_engine.py:627`
- **Status** Fixed (2e2e6a6), deployed 2026-10-01
- **Trigger** _spawn_settlement(R) starts _settle_and_complete. Its first fetchrow (line 353) or the 'settling' UPDATE transaction (lines 358-361) raises, for example on a stale or broken pooled connection, a 10s pool-acquire timeout, or a transient PG error on that connection only, while the main loop's own queries succeed. The except at line 391 logs and swallows the error. R stays 'draw_complete' and is no longer in _settling_round_ids. _recover_stuck_settling_rounds selects only status = 'settling', so R is never retried while the process keeps running.
- **Impact** Every winner in R stays unpaid indefinitely while later rounds run normally. KenoRoundStuck fires at 300s, and the runbook's response is to restart keno-worker. Any later run_forever restart (a DB blip, lock loss) also runs recover_on_startup. By then R is older than 300s and not 'settling', so it goes down the refund path (previous finding) and winners permanently lose their winnings.
- **Suggested fix** Have the sweep select non-terminal rounds with drawn_numbers set and status IN ('draw_complete','settling') that are not in _settling_round_ids, and spawn settlement for them. Alternatively, write 'settling' in the same transaction that sets 'draw_complete' in _run_draw, so no draw_complete-without-task window exists. Combine with the previous fix so such a round is never refunded.

### 20. _fail_and_refund_round selects pending tickets before locking the round row, so a ticket committing mid-refund is left 'pending' in a 'failed' round forever

- **Severity** high, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:697`
- **Status** Fixed (6b3899e), deployed 2026-10-01
- **Trigger** keno-worker is down or wedged for more than about 4.5 minutes while round R is 'betting_open' (about two thirds of each cycle). place_ticket only checks status='betting_open' with no deadline check, and keno.js enables Play on status alone, so players keep staking into R. On restart, recover_on_startup calls _fail_and_refund_round(R). Its SELECT ... status='pending' FOR UPDATE (READ COMMITTED snapshot) cannot see a place_ticket transaction T that has already done its ledger.post and holds R's keno_rounds row FOR UPDATE. The refund's first ledger.post waits on the keno_reserve row that T holds, or, with no other tickets, its UPDATE keno_rounds waits on R's row. T commits its 'pending' ticket, then the refund marks R 'failed' and commits without T's ticket.
- **Impact** The player behind T loses their full stake. It stays in keno_reserve/jackpot, the ticket shows 'pending' forever, and nothing sweeps pending tickets in terminal rounds (the spec's 'unsettled tickets in completed rounds' alert is not configured). Before that, every stake made during the outage is locked in a round that never draws.
- **Suggested fix** Lock the round first: SELECT ... FROM keno_rounds WHERE id=$1 FOR UPDATE, or do the UPDATE to 'failed' as the first statement, then select pending tickets. In-flight placements then commit before the ticket snapshot, and later ones fail place_ticket's status check. Separately, make place_ticket reject once now() > betting_opened_at + betting_seconds (+ grace), so a dead engine doesn't keep taking stakes.

### 21. join() can commit a stake into a round that has just been voided; the stake is never refunded

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/engine/round_engine.py:438`
- **Status** Fixed, deployed (b583cf7)
- **Trigger** join() checks only the in-memory `self._status == 'lobby'` (line 351), before its DB work. _run_lobby does not take _join_lock and does not change status before refunding (lines 719-725). Common case: a room is waiting for a second player and a new player takes a card in the last moment. The join passes the status check and is in its advisory-lock or check_stake_allowed phase when the deadline fires with player_count()==1 (the new entry is not in _entries yet). refund_round takes the rounds row FOR UPDATE and reads the entrants. The join's INSERT into round_entries (the FK takes FOR KEY SHARE on rounds) blocks until the refund commits, then succeeds. The stake posts and `UPDATE rounds SET pot = pot + ...` (no status guard) commits. The same happens for any join after an admin void or stop of a lobby round. A variant: if player_count() was 0 at the deadline, the late joiner lands in a 'running' round alone. The product forbids that, and the player auto-wins back their own stake minus the house cut.
- **Impact** The player is told ok and charged, but the round is already 'voided'. That status is terminal, so neither refund_round nor recovery will ever touch it again, and the stake stays stranded in pot_escrow. The player loses the stake.
- **Suggested fix** Guard inside the transaction: move the `UPDATE rounds SET pot = pot + $1 ... WHERE id = $2 AND status = 'lobby' RETURNING id` to before the round_entries INSERT, or add `SELECT status FROM rounds WHERE id=$1 FOR UPDATE`, and roll back with not_joinable if the round is not lobby. Also make _run_lobby acquire self._join_lock and set a non-joinable status before it decides between transition and refund, and re-check self._status inside join's _join_lock block.

### 22. Same-call auto-mark co-winners can miss the 50ms tie window because each claim awaits a DB insert before taking its timestamp

- **Severity** high, **fix size** small, **finder confidence** medium
- **Where** `services/engine/round_engine.py:590`
- **Status** Fixed (66fe7e5), deployed 2026-10-01
- **Trigger** When a called number completes several auto-mark cards at once, _call_next_number awaits self.claim() for each winner in turn. Each claim runs _record_claim_attempt, an autocommit INSERT through the shared 20-connection pool, in its finally block before `now = time.monotonic()` (line 592). The first winner sets deadline = now + 50ms and starts _finalize_after_window. Winner k measures `now` only after k-1 more round trips, each with WAL fsync and possible pool wait. If the combined time passes 50ms, or the finalize task fires while the loop is awaiting (it then sets _winner_window_deadline=None), later claims fall through to 'round_already_settled'.
- **Impact** A player whose card completed the winning pattern on exactly the same call is left out of settlement. Their whole share goes to the other winners. The code comment at lines 919-932 says same-call auto ties are meant to split, but this only holds when DB latency is low. It is worst under load, when many rooms share the pool.
- **Suggested fix** In _call_next_number, collect every auto-mark winner for the call synchronously, then register them all in _pending_winners under one _winner_lock acquisition before any await, and write the claim_attempts rows afterwards. Alternatively, in claim(), treat any valid claim whose call index equals the first pending winner's call_index as a tie, regardless of wall-clock time.

### 23. Any Redis or DB error in the round loop kills the room's engine and voids the in-flight round

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/engine/round_engine.py:1218`
- **Status** Fixed (b097979), deployed 2026-10-01
- **Trigger** _publish_room (bare redis.publish) is called unguarded from _run_lobby every second (line 690), from _call_next_number on every call (line 909), from _transition_to_running, and after settlement commits (lines 1121-1125). _call_next_number's pool.fetchrow (line 896) and _start_new_round/_room_is_still_active are also unguarded. A Redis connection error (0 client retries), a 10s pool-acquire timeout (worker pool max_size=20 shared by every room), or a Postgres connection error propagates up through _run_running, _run_lobby and run_forever. The finally block releases the lock and the task ends with an unobserved exception.
- **Impact** That room's engine dies mid-round. Up to 30s later run_active_rooms runs recovery, which voids and refunds the round. Stakes come back, but a player who was about to win, or had won with the publish failing after commit, loses the win. If the failure comes after the settlement commit, players never get round_end. A Redis blip hits every room at once, because all of them publish each second, so every in-flight Bingo round across the platform is voided together and rooms go dark for up to 30s.
- **Suggested fix** Make _publish_room best-effort: catch RedisError and log, since DB state is authoritative and state_sync recovers clients. Wrap the post-commit balance and round_end publishes the same way. Retry the per-call UPDATE with a short backoff before giving up. Keep a top-level except in run_forever that logs the exception.

### 24. A Redis error on the command reply publish silently kills the room's only command consumer for good

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/engine/round_engine.py:1325`
- **Status** Fixed (3feea9a), deployed 2026-10-01
- **Trigger** _handle_command's final `await self._redis.publish(commands.reply_channel(request_id), ...)` sits outside its try/except, and _serve_commands only catches RedisError around xread. In this client config redis-py 8.1 connections use Retry(0 retries), so a single ConnectionError or TimeoutError raises immediately. Any Redis hiccup while a command is being answered makes the exception escape _serve_commands and the commands_task finishes. The initial xrevrange (line 1241) is also unguarded. run_forever (line 238) never checks commands_task.done(), so the round loop keeps holding the lock and cycling rounds.
- **Impact** The room turns into a zombie. Lobby ticks and empty rounds keep running, but every take_card, drop_card, claim and set_auto from every player times out ('room_unavailable'). Manual-mode players in a live round cannot claim. The worker never reclaims the room because the engine task is still alive, and nothing monitors Bingo engines (the heartbeat alert is Keno-only). It lasts until a process restart, and one Redis blip can hit every room that is answering a command at that moment.
- **Suggested fix** Wrap the reply publish (and the initial xrevrange) in try/except RedisError with logging, and make _serve_commands catch Exception per entry. In run_forever, supervise commands_task: if it finishes with an exception, log it and restart it, or break out so the room is released and reclaimed.

### 25. Per-IP Keno ticket limit (20/min) is shared by every player behind the same carrier CGNAT address

- **Severity** high, **fix size** small, **finder confidence** medium
- **Where** `services/gateway/app.py:513`
- **Status** Confirmed (b1815fa, strict xfail); the limit is the operator's decision
- **Trigger** Players on the same mobile carrier egress IP (Ethio Telecom mobile data is heavily CGNAT'd; with Cloudflare in front, CF-Connecting-IP is that shared public IP) place Keno tickets by hand. The keno_ticket_ip bucket allows 20 per minute in total for that IP. For example, 8 players placing 3 tickets per round already exceed it.
- **Impact** Legitimate players get 429 rate_limited on ticket placement because of other people's traffic. They miss rounds or retry. One heavy player behind a shared IP can block everyone else on it. The code also trusts a client-sent CF-Connecting-IP if port 8000 is reachable without going through the tunnel.
- **Suggested fix** Drop the per-IP bucket or raise it sharply (for example hundreds per minute) and rely on the per-user bucket plus per-round caps. If a per-IP guard is still wanted, apply it only to new or unverified accounts. Only honor CF-Connecting-IP when the request comes from the tunnel.

### 26. Each engine command holds a dedicated Redis connection for up to 5s; exhausting the 200-connection pool makes the fail-closed rate limiter block every player on the gateway

- **Severity** high, **fix size** small, **finder confidence** medium
- **Where** `services/gateway/connection.py:390`
- **Status** Fixed (bee89be), deployed 2026-10-01
- **Trigger** send_command (services/engine/commands.py:64) opens a new pubsub, and so takes a pool connection, for every command and holds it until the reply or the 5s timeout. The pool is a plain ConnectionPool with max_connections=200, which raises MaxConnectionsError immediately when full. Non-malicious trigger: an engine-worker crash or restart leaves busy rooms without an owner, and ~200 players tapping take_card within 5s exhaust the pool. Malicious trigger: _run_action accepts any integer room_id without checking that the room exists or is active, and drop_card/set_auto have no per-action bucket, so one Telegram account with about 150 open sockets (there is no per-user socket cap) sending drop_card to room_id=999999 every 5s stays inside WS_MESSAGES and pins about 150 connections. Two accounts go past 200.
- **Impact** Once the pool is empty, rate_limit.allow_with_retry_after catches MaxConnectionsError and fails closed. Every player on that gateway gets 'Slow down.' for every WS frame and 429 rate_limited on /api/keno/tickets, and deposit and Telebirr rate checks also refuse. send_command's subscribe raises MaxConnectionsError, which is not a CommandTimeout, so affected sockets are torn down. A single room's outage or one or two abusive accounts takes the whole gateway down for everyone.
- **Suggested fix** Reject room_ids not in a cached set of active rooms before calling send_command. Add per-action buckets for drop_card and set_auto. Cap in-flight commands per user and per process with a semaphore that sits well below max_connections. Give rate limiting its own small Redis client so command traffic cannot starve it. Longer term, use one shared reply subscriber per gateway (psubscribe cmdreply:<gateway-id>:*) instead of a pubsub per command.

### 27. Writer task death is never noticed; _cleanup then re-raises it and skips every unsubscribe (frozen client plus a growing hub leak)

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/gateway/connection.py:501`
- **Status** Fixed (05c7309), deployed 2026-10-01
- **Trigger** Case 1: the writer task (created at line 92) raises. Examples: build_state_sync hits a DB error or pool-acquire timeout after a queue overflow; or send_text raises WebSocketDisconnect(1006) because uvicorn raised ClientDisconnected while the writer was blocked in drain for a slow or backgrounded mobile client. The reader loop keeps running and nothing observes the dead writer. Case 2: when the socket later closes, _cleanup calls cancel() on the already-finished task and then `await self._writer_task` re-raises the stored exception. Only CancelledError is suppressed, so unsubscribe_room/unsubscribe_user/unsubscribe_keno and the metric decrements at lines 503-509 never run.
- **Impact** A player whose writer died sees a frozen board: no calls, no round_end, no balance updates. Their pings still get pongs, so the client never reconnects, and they can keep buying cards. Each such connection leaves its ConnectionQueue in _room_subscribers, _user_subscribers and _keno_subscribers for the life of the process. Every keno:live message (about 50 per round) is offered to every leaked queue, and each leaked queue holds up to 100 messages. Gateway memory and listener CPU grow with ordinary mobile churn, and the gateway_connections and keno_ws_connections gauges only ever increase.
- **Suggested fix** In _writer_loop, catch Exception, log it and close the websocket (code 1011) so the client reconnects. In _cleanup, use `with contextlib.suppress(asyncio.CancelledError, Exception)` around the await, and put the unsubscribes and metric decrements in a try/finally so they always run.

### 28. Chapa webhook dedupe key is the transaction reference only, without the status, so a later 'success' event can be discarded as a duplicate

- **Severity** high, **fix size** small, **finder confidence** low
- **Where** `services/payments/deposits.py:298`
- **Status** Fixed (73573df), deployed 2026-10-01
- **Trigger** chapa.verify_webhook sets event_id=str(reference) (chapa.py). _apply_confirmed_status inserts payment_events(provider, event_id) before it looks at the status, and commits that row even for 'pending' and 'failed' outcomes. Suppose Chapa sends a 'pending' or 'failed'/'cancelled' webhook and then a 'success' webhook for the same reference, for example after a failed first attempt and a retry on the same checkout. The success event hits ON CONFLICT, and the function returns 'duplicate' without crediting. In the 'failed' case the row is already status 'failed', and poll_pending_deposits only scans 'processing', so the fallback never rescues it either. The poll path puts the status into its key (poll:{ref}:{status}), but the webhook path does not.
- **Impact** The player paid through Chapa but is never credited. Only run_provider_reconciliation's error log (status_disagreement, within 2h) would surface it, and that needs manual admin action.
- **Suggested fix** Include the status in the webhook event_id (for example f"{reference}:{status}"), or record payment_events only for events that change state. Also let the poll or reconciliation path re-verify recently 'failed' Chapa deposits.

### 29. Deposit polling has no per-item error isolation: one deposit that Chapa rejects aborts the fallback for every other player

- **Severity** high, **fix size** small, **finder confidence** medium
- **Where** `services/payments/deposits.py:423`
- **Status** Fixed (36ba6f5), deployed 2026-10-01
- **Trigger** poll_pending_deposits loops over every 'processing' Chapa deposit with no try/except. ChapaProvider.fetch_status (chapa.py:208-214) raises when Chapa returns a non-'success' envelope for a tx_ref (for example an abandoned or invalid checkout), when the status is not recognised (_map_status raises ValueError), when a 404 or 5xx body is not JSON (response.json() is called before the 404 check), or when the amount is malformed. The query has no ORDER BY, and 'processing' deposits never expire, so the same bad row can abort every 30-second pass. run_provider_reconciliation (deposits.py:566-567) has the same pattern.
- **Impact** Players whose Chapa webhook was lost are never credited by the polling fallback, and their paid deposits stay uncredited indefinitely because another player's deposit sits ahead of theirs. The hourly reconciliation can also abort and stop surfacing mismatches.
- **Suggested fix** Wrap each row's fetch_status and _apply_confirmed_status in try/except and log per our_ref. Add ORDER BY updated_at. In chapa.fetch_status, check the status code before calling response.json() and handle non-JSON bodies. Consider expiring old abandoned checkouts.

### 30. poll_pending_deposits has no per-row isolation, and 'processing' deposits never expire, so one bad row stops the webhook fallback for everyone

- **Severity** high, **fix size** small, **finder confidence** medium
- **Where** `services/payments/deposits.py:423`
- **Status** Fixed (36ba6f5), deployed 2026-10-01; expiring abandoned checkouts is a policy decision (strict xfail)
- **Trigger** Any Chapa deposit row in status 'processing' where provider.fetch_status() raises every time. Examples: _map_status raises ValueError for a Chapa status outside its 5-entry map (such as 'refunded' or 'reversed'); Chapa returns a non-'success' envelope, which may include an abandoned or unpaid checkout; data.amount is null. The loop has no try/except, so the exception leaves poll_pending_deposits. _run_periodic_sweep logs it and sleeps 30s. The next pass selects the same rows (no ORDER BY, so in practice the same order) and fails at the same row again. Nothing ever moves such a row out of 'processing', so this repeats indefinitely. Even when nothing raises, every abandoned checkout is re-polled every 30s forever: one serial HTTP call each, with a 15s timeout.
- **Impact** Every deposit that sorts after the poisoned row is never credited by the fallback. A player whose Chapa webhook was lost stays uncredited indefinitely, with only a log line and an hourly reconciliation log as signals. Money is not lost, but players lose it from their view and support load grows. Abandoned checkouts also pile up the Chapa calls made each pass, and they keep counting toward the player's daily deposit cap because 'processing' is in the cap's status list (deposits.py:155).
- **Suggested fix** Wrap each row's fetch_status and _apply_confirmed_status in try/except Exception: log it and continue, while letting CancelledError through. Add ORDER BY updated_at and a LIMIT. Age out 'processing' rows older than Chapa's checkout lifetime, for example by marking them 'cancelled' after a final verify, so they stop being polled and stop counting toward the cap.

### 31. A payout entry without 'our_ref' crashes the except handler, and the consumer task dies silently while the process looks healthy

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/payments/payout_worker.py:407`
- **Status** Fixed (08341cd), deployed 2026-10-01
- **Trigger** Any entry in the 'payouts' stream that lacks an our_ref field, for example an operator re-enqueueing by hand with only payment_id, or a future producer. Line 405 raises KeyError while building the arguments. The except handler at line 407 then evaluates fields['our_ref'] again, raising KeyError inside the handler, which escapes the for loop and the while loop and ends run_forever.
- **Impact** consumer_task (line 488) is never supervised: main_async only awaits stop_event. The process keeps running its sweeps and the metrics server, and payout-worker has no healthcheck, so Docker never restarts it. All automatic payouts stop for every player. Meanwhile sweep_stuck_approved_payouts keeps adding duplicates for every approved row, which later feeds the re-dispatch bug. The bad entry is never acked, so after a manual restart the first read of the pending list returns it and kills the consumer again.
- **Suggested fix** Use fields.get('our_ref'). If it is missing, log and xack the entry, or move it to a dead-letter stream. Add a done-callback on consumer_task that logs the exception and sets stop_event, so the container exits and restart: unless-stopped brings it back.

### 32. Parser amount regex silently truncates thousands-separated amounts (ETB 1,500.00 is read as 1)

- **Severity** high, **fix size** small, **finder confidence** low
- **Where** `services/payments/telebirr_parser.py:83`
- **Status** In the Telebirr design (parser fixes)
- **Trigger** An SMS whose amount is formatted with a comma, such as 'You have received ETB 1,500.00 from ...'. _RECEIVED_AMOUNT_RE and _TRANSFERRED_AMOUNT_RE (`([0-9]+(?:\.[0-9]{1,2})?)`) have no trailing boundary, so they capture '1' and ignore ',500.00'. The row is stored as available with amount=1, and redemption credits exactly that amount.
- **Impact** The player pays 1,500 and is credited 1. The evidence becomes 'redeemed' and cannot be redeemed again, so the player needs a manual admin adjustment. The parser claims to fail closed, but here it fails open on the amount. This applies only if Telebirr uses thousands separators; the three samples on file are all under 1,000 ETB.
- **Suggested fix** Anchor the capture, for example `ETB\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\.[0-9]{1,2})?(?=\s|$|\.\s)`, strip the commas before Decimal, and return ParseFailure when a digit or comma immediately follows the match. Add a test with an amount of 1,000 or more.

### 33. Telebirr redemption trusts only knowledge of the reference; whoever submits it first gets another player's deposit

- **Severity** high, **fix size** large, **finder confidence** medium
- **Where** `services/payments/telebirr_redemption.py:152`
- **Status** Confirmed; in the Telebirr design
- **Trigger** Player A pays Zemen through Telebirr. Before A redeems, anyone who learns the 10-char reference submits it first through the bot paste handler or /api/wallet/deposits/telebirr/redeem. People who can see references include: someone shown A's SMS or screenshot, staff reading the collection phone's inbox, and a payment agent whose /agent-portal/submissions page (app.py:246) lists reference, amount and status 'available' for every row they forwarded. redeem_evidence locks the row and credits whoever asked first. A then gets PAYMENT_ALREADY_REDEEMED, because ownership never transfers. The same applies while A is blocked by DAILY_CAP_EXCEEDED or cooling-off: the evidence stays 'available' for anyone else to claim.
- **Impact** One player's deposit is credited to another player's wallet. The rightful payer loses the money until an admin investigates. The evidence row stores payer_phone (masked, received template) and payer_name, but neither is ever compared with the redeeming user.
- **Suggested fix** Bind redemption to the payer. For the received template, compare the masked payer_phone with the redeemer's decrypted users.phone_e164 masked the same way (_mask_ethiopian_phone). On a mismatch, route to admin review rather than crediting (this is a product decision for players who pay from a relative's phone). Stop exposing unredeemed references and amounts in the agent portal.

### 34. Seven-digit reference numbers truncate to six digits, so consecutive payment refs collide once payment_ref_seq reaches 1,000,000

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/payments/withdrawals.py:180`
- **Status** Fixed (797fe74), deployed 2026-10-01
- **Trigger** lpad(nextval('payment_ref_seq')::text, 6, '0') truncates longer strings. Verified in this Postgres: lpad('1234567',6,'0') and lpad('1234568',6,'0') both return '123456'. The sequence is shared by withdrawals (withdrawals.py:180), manual deposits (manual.py:94), Chapa deposits (deposits.py:189) and Telebirr redemptions (telebirr_redemption.py:209), and every checkout attempt uses a value, including abandoned ones. Once the value passes 999,999, the ten values 1234560..1234569 all produce WD-/DEP-YYYY-123456.
- **Impact** Most new deposits and withdrawals fail with a UniqueViolation on payments_our_ref_key, which is a 500 for every player. On the withdrawal path, ledger.post with idempotency_key=our_ref first returns the earlier withdrawal's transaction without moving any money; only the payments UNIQUE constraint and the resulting rollback prevent an approved payout with nothing locked.
- **Suggested fix** Stop truncating: use nextval(...)::text with a zero-pad that is only a minimum width, for example CASE or to_char(nextval, 'FM000000') (which widens past 6 digits), or simply lpad(...,10,'0'). Apply it to all four call sites.

### 35. sweep_stuck_approved_payouts re-enqueues payouts that are only waiting in the queue, not lost, and adds a new duplicate every tick

- **Severity** high, **fix size** small, **finder confidence** high
- **Where** `services/payments/withdrawals.py:361`
- **Status** Fixed (c1e3077), deployed 2026-10-01
- **Trigger** The payout worker handles entries one at a time, each Chapa call can take up to 15s per httpx phase, and batches are 10 entries. Any backlog that keeps a row at status='approved' for more than 60s after its insert or approval (for example a payday burst, a slow or unreachable Chapa, or a dead consumer task while the sweeps keep running in the same process) makes the sweep XADD another entry for that row. It adds one more on every 60s tick while the row stays 'approved'. A narrow race also exists: the sweep can SELECT the row just before process_one's first transaction commits 'processing'.
- **Impact** Once the first entry moves the row to 'processing', every duplicate reaches create_payout again (previous finding), so ordinary backlog becomes a double payout or a refund of a transfer that was already sent. The stream also grows without bound. This is the most likely everyday trigger of the money loss.
- **Suggested fix** Record when the row was enqueued or dispatched (for example an enqueued_at column, re-enqueued only when it is older than a threshold well above the worst-case backlog), or check XPENDING or the stream for an existing entry for this our_ref. Together with the atomic approved->processing claim in process_one, duplicates then become harmless.

### 36. Concurrent welcome-bonus grants create two bonuses rows backed by one ledger credit, which poisons the bonus sweep for all players

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `packages/core/bonuses.py:90`
- **Status** Fixed (fc82a5f), deploy pending
- **Trigger** Two deposit confirmations for one user overlap. Examples: approve_manual_deposit_admin (queries.py 2231) runs while the same user's Telebirr redemption or Chapa confirmation commits; or two admins approve two of that user's manual deposits. Both maybe_grant_welcome_bonus calls count grants_so_far=0 and use the same key welcome-{u}-{rule}-0. In T2, grant_bonus's pre-check SELECT runs before T1 commits. ledger.post then blocks on the unique key and returns T1's transaction as a replay. T2 then INSERTs a second bonuses row with the same grant_txn_id, since bonuses has no unique index on grant_txn_id. The referral path is saved by ux_bonuses_referral_once; welcome is not.
- **Impact** Two 'active' bonuses exist but user_bonus holds one amount. Both clear wagering on the same tick. The second convert_bonus_to_cash raises InsufficientFunds, or, if the user holds another bonus, drains it. sweep_bonus_wagering has no per-row try/except, so every tick aborts at that row, and every active bonus after it in scan order, belonging to other players, never converts or expires.
- **Suggested fix** Add UNIQUE(bonuses.grant_txn_id) (migration) and INSERT ... ON CONFLICT (grant_txn_id) DO NOTHING RETURNING, falling back to the existing row. Alternatively, take pg_advisory_xact_lock(user_id) at the top of maybe_grant_*. Separately, isolate each row in sweep_bonus_wagering.

### 37. Autoplay places a ticket after the player pressed Stop: stale session snapshot and no status re-check in the placement transaction

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_autoplay.py:210`
- **Status** Already fixed (verified): place_ticket re-checks the session under a row lock
- **Trigger** Betting opens, and place_for_active_sessions reads every active session once (line 210), then places tickets one at a time. The player taps Stop: DELETE /api/keno/autoplay commits status='stopped' and returns {"stopped": true}. This happens after the snapshot but before the loop reaches their session. That takes seconds with many sessions, or while round N's settlement holds the reserve lock (see the settlement-lock finding). _place_for_session calls place_ticket, which never looks at keno_autoplay_sessions.status. The rounds_placed UPDATE at 237-241 has no status filter either.
- **Impact** A real-money stake is taken for a round after the server has told the player the session is stopped: one unwanted bet per stop, affecting any autoplay user who stops while a placement pass is running.
- **Suggested fix** When autoplay_session_id is given, run SELECT status FROM keno_autoplay_sessions WHERE id=$1 FOR UPDATE inside place_ticket's transaction and raise a TicketRejected subclass if it is not 'active'. Increment rounds_placed in that same transaction. stop_session then serializes against placement.

### 38. stop_on_loss / stop_on_win routinely overshoot by one round because round N+1's autoplay tickets are placed before round N's result is recorded

- **Severity** medium, **fix size** large, **finder confidence** medium
- **Where** `packages/core/keno_autoplay.py:221`
- **Status** Fixed (939a29b, same as #17), deployed 2026-10-01
- **Trigger** Round N's draw finishes, then _spawn_settlement(N) runs as a background task, and the main loop immediately creates round N+1 and calls place_for_active_sessions (keno_round_engine.py:150-151, 245). record_settlement for N's tickets runs only in settlement's post-commit loop (keno_round_engine.py:478). With a large round N, that loop has usually not reached a given session when N+1's placement pass runs. _place_for_session never compares net_position (or the session's still-pending tickets) against the thresholds before placing.
- **Impact** A player whose loss in round N crosses stop_on_loss_amount is still charged for round N+1, so they lose up to one extra stake (up to 200 ETB at Tier 4) beyond the limit they chose. The same happens after a stop_on_win. The outcome depends on timing, and it happens more often as rounds get bigger.
- **Suggested fix** Before placing, treat the session's unsettled tickets as worst-case losses: if net_position - SUM(stake of this session's pending tickets) - stake <= -stop_on_loss_amount, skip or stop. Alternatively, run the autoplay placement pass only after the previous round's record_settlement pass has completed.

### 39. A round filled to capacity by other players' bets permanently stops everyone else's autoplay sessions

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `packages/core/keno_autoplay.py:231`
- **Status** Confirmed; skipping vs stopping on a round-level rejection is the operator's decision
- **Trigger** _open_betting publishes keno.betting.open (engine line 232) before running autoplay placement (line 248). Manual bets, for example one large bet, can fill the round's exposure ceiling (reserve x max_round_exposure_pct, small at launch) first. Each later autoplay placement then raises RoundCapacityReached, or UserRoundShareExceeded, whose ceiling is derived from the round. _place_for_session treats any TicketRejected as terminal and sets status='stopped' with reason ticket_rejected:round_capacity_reached.
- **Impact** Other players' autoplay and multi-race sessions end for good because of someone else's bet in a single round, instead of skipping that round. They must notice and restart.
- **Suggested fix** Treat round-level, transient rejections (RoundCapacityReached, RoundNotAcceptingBets) as 'skip this round': log it, keep the session active, and optionally cap consecutive skips. Stop only on player-level rejections such as insufficient balance, a responsible-gaming block, or a simulated player.

### 40. rounds_placed and exhaustion are updated in separate transactions from the ticket placement, so a crash can buy one extra round

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_autoplay.py:236`
- **Status** Fixed (50f5753), deployed 2026-10-01
- **Trigger** place_ticket commits (transaction 1), then the process is hard-killed before the rounds_placed UPDATE (transaction 2, line 237) or before the exhaustion _stop_internal (line 248). On the next round, the session is still active with a stale rounds_placed, and nothing checks rounds_placed >= rounds_total before placing.
- **Impact** A player who bought N rounds is charged for N+1 tickets. The trigger is rare (a hard crash in a window of milliseconds), but the extra real-money bet is not refunded.
- **Suggested fix** Increment rounds_placed and set status='exhausted' inside place_ticket's transaction (keyed by autoplay_session_id), or derive rounds_placed from COUNT(keno_tickets WHERE autoplay_session_id=S). Add a pre-placement guard: if rounds_total is not None and rounds_placed >= rounds_total, mark the session exhausted and skip.

### 41. record_settlement applies an incremental delta after the money commits and is never replayed, so a crash leaves net_position (and the stop thresholds) permanently wrong

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `packages/core/keno_autoplay.py:273`
- **Status** Partly fixed by 939a29b (stop-loss enforced from tickets at placement); stop_on_win and the session summary can still miss a result lost to a hard crash
- **Trigger** The engine process is hard-killed (OOM, SIGKILL, host crash) after _settle_tickets' batch transaction commits but before the post-commit loop calls record_settlement_safely for every ticket. On recovery, the retried settlement skips those tickets (status is no longer 'pending'), so their delta is never added. Separately, WHERE status='active' drops the result of the final ticket of any session that was exhausted or stopped at placement time.
- **Impact** The session's net_position misses the lost results, so stop_on_loss fires late by the missed amount and the player loses more than the threshold they set. For multi-race sessions, the final summary (keno.js announceAutoplayEnded 'won' flag) always excludes the last round.
- **Suggested fix** Make it idempotent: recompute net_position = SUM(COALESCE(payout,0)+COALESCE(jackpot_payout,0)-stake) FROM keno_tickets WHERE autoplay_session_id=$1 AND status IN ('won','lost'), set it, and check the thresholds. Call this for active sessions from recovery as well.

### 42. Business-metrics refresh loads the whole 24 h ticket set into the engine process and crunches it in pure Python on the round engine's event loop every 60 s

- **Severity** medium, **fix size** large, **finder confidence** low
- **Where** `packages/core/keno_business_metrics.py:137`
- **Status** Not yet verified
- **Trigger** keno_worker runs Publisher.publish every 60 s in the same event loop as KenoRoundEngine (keno_worker.py:99-110), on every replica. compute() fetches every settled ticket from the last 24 h. Then Decimal sums, set comprehensions and group_sessions (a per-user sort) run synchronously, and three retention queries plus an LTV query scan all of keno_tickets history.
- **Impact** At volume (hundreds of thousands to millions of tickets a day), each refresh blocks the loop for seconds. That stalls the ball-reveal pacing, publishes and settlement for all players. A block of more than about 10 s stops KenoRoundLock's refresh (TTL 15 s, refresh every 5 s), so a standby replica can take over mid-round while the old owner is still running. The impact is scale-dependent, so it is not an immediate outage.
- **Suggested fix** Compute the aggregates in SQL (SUM, COUNT(DISTINCT user_id), COUNT(DISTINCT (user_id, round_id)), and sessionization via LAG() window functions) so only a few numbers come back. Alternatively, run the publisher in a separate process, or off-loop via a thread executor. Cache or index the retention and LTV scans.

### 43. Replay short-circuit is not scoped to the user and runs before the per-user lock: cross-user ticket hijack, and a raw 500 on a concurrent retry

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_tickets.py:202`
- **Status** Already fixed by d24fc8a (verified); concurrent-retry test added (3ff3d57)
- **Trigger** (a) Player B sends idempotency_key 'autoplay:<S>:<R+1>', where S is player A's autoplay session id (sequential; B sees their own) and R+1 is the next round id, during round R. B's ticket is stored under that key. When round R+1 opens, place_for_active_sessions calls place_ticket for A's session, and line 202 (no user_id filter) returns B's ticket as if it were A's. (b) The same user sends the same key twice concurrently (a retry while the first request is in flight). Both pass the SELECT at 202 before pg_advisory_xact_lock at 234. The second then re-validates after the first commits: it either raises TooManyTicketsThisRound or RoundCapacityReached, or ledger.post returns the first transaction and the INSERT hits keno_tickets_idempotency_key_key, an asyncpg.UniqueViolationError that the gateway does not catch (it only catches TicketRejected).
- **Impact** (a) A's session counts a round (rounds_placed +1, and early exhaustion for multi-race) without A having any ticket. B also learns A's ticket stake and status. The replayed PlacedTicket carries the current request's picks, not the stored ones. (b) The player gets a 500 or a rejection for a ticket that was actually placed and charged, and may tap again with a fresh key and bet twice without meaning to. No double debit by itself.
- **Suggested fix** Move the idempotency SELECT to after pg_advisory_xact_lock(user_id), filter it by user_id (or use the namespaced key from the critical finding), and return the stored picks. Build autoplay keys in a server-only namespace that a client key can never produce.

### 44. Every ledger.post locks the single global system-account balance row, serializing all players on pot_escrow, provider_settlement, keno_reserve and promo_expense

- **Severity** medium, **fix size** large, **finder confidence** medium
- **Where** `packages/core/ledger.py:215`
- **Status** Not yet verified
- **Trigger** post() takes SELECT ... FOR UPDATE on every touched account_balances row, including system accounts that are one row per currency (ux_accounts_system_kind_currency), and holds it until the caller's outer transaction commits. Every Bingo join, drop and settlement in every room locks pot_escrow. Every deposit confirmation locks provider_settlement and keeps it through maybe_grant_referral/welcome, as do payout settle and reverse. Keno settlement posts all of a round's payouts in one transaction (keno_round_engine.py:441-464) holding keno_reserve, and _mark_failed refunds every ticket in one transaction. The DB runs with lock_timeout=0 and statement_timeout=0.
- **Impact** Money-moving throughput across the platform is capped by one row lock per system account. A slow or stalled holder (a large voided-round refund, a big Keno settlement, an admin transaction left open) makes every other player's stake, deposit or ticket wait with no timeout. The balance stays correct. The cost is latency and availability for everyone. (This same serialization is currently what makes the referral/welcome checks safe; see the next finding.)
- **Suggested fix** Do not keep a locked running balance for system accounts: skip FOR UPDATE and the negative check for non-user kinds and apply the delta with a single UPDATE, or shard pot_escrow per room/round and keno_reserve per round. Alternatively keep system balances as append-only sums. At minimum set a lock_timeout on money paths so a stalled holder fails fast instead of hanging everyone.

### 45. Admin manual bonus grant is not idempotent: the key embeds the server timestamp, so a double-click or retry grants twice

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/admin/bonus_queries.py:178`
- **Status** Fixed, deployed (a7603c5)
- **Trigger** An admin double-clicks Grant, the browser retries the POST, or a proxy replays it. web/admin/js/screens/bonuses.js:268-289 does not disable the button, and GrantManualBonusRequest has no request_id. Each request builds 'manual-grant-{admin}-{user}-{now().timestamp()}', which is unique every time.
- **Impact** The player receives two (or more) bonus grants funded from promo_expense. Combined with the wagering-by-drop issue, these convert to withdrawable cash within a minute. They are recoverable only if an admin notices and revokes them while they are still active.
- **Suggested fix** Add a required client-generated request_id to GrantManualBonusRequest (as AdjustBalanceRequest already has), build the key as f"manual-grant-{admin_id}-{request_id}", and disable the submit button while the request is in flight.

### 46. Reserve withdrawal floor check is released before the debit (TOCTOU across three transactions)

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/admin/keno_queries.py:580`
- **Status** Not yet verified
- **Trigger** Pass 2 re-checks the floor under FOR UPDATE on the reserve balance, then commits, which releases the lock. Pass 3 posts the withdrawal in a new transaction with no check. Two superadmins, or two tabs, each withdrawing X both pass pass 2 before either reaches pass 3, and both then post. A Keno settlement payout landing between pass 2 and pass 3 does the same.
- **Impact** The prize reserve ends below the configured floor. Because keno_reserve is not in USER_BALANCE_KINDS, it can go negative. The docstring's claim that the re-check makes this safe is false. The audit 'after' balance is the pre-post estimate, not the real result. deposit_to_reserve_admin's 'after' is also computed from an unlocked read.
- **Suggested fix** Do the locked floor check and ledger.post in one transaction: merge pass 2 and pass 3 and keep the FOR UPDATE held until commit. Keep pass 1 only for auditing a rejection. Record the actual post-balance.

### 47. The campaign worker loads a whole campaign into the shared notification stream, so every transactional notification waits behind it

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/bot/campaign_worker.py:171`
- **Status** Not yet verified
- **Trigger** An admin sends a campaign to N players. _dispatch_pending_deliveries XADDs 200 deliveries per tick, and run_forever skips its sleep whenever did_work is true, so all N entries go into bot_notifications within seconds. The relay drains that stream in FIFO order, 10 entries at a time, at about 25 msg/s. Notifier's high/low priority lanes only reorder the 10 entries already read, not the backlog. Any notify_user entry (deposit confirmed, withdrawal failed or rejected) added after the campaign lands behind all N campaign entries. Once a backlog is older than RECLAIM_STUCK_AFTER_SECONDS (900s), deliveries are reclaimed and enqueued again, which lengthens the stream further.
- **Impact** During every large campaign, all players' money notifications are delayed by about N/25 seconds: roughly 7 minutes for 10k recipients, over 30 minutes for 50k. That invites support tickets and repeated deposit attempts.
- **Suggested fix** Throttle dispatch to relay capacity: only enqueue when fewer than about 100 deliveries are in 'processing' for all campaigns combined, and always sleep between ticks. Better, give campaigns their own stream and consumer so transactional entries never queue behind them.

### 48. The relay waits for the slowest recipient in each batch, so one player's Telegram backoff or starved campaign messages stall everyone

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/bot/notification_relay.py:207`
- **Status** Not yet verified
- **Trigger** _process_batch gathers every user's _drain_one_user, and each process_one awaits Notifier's `done` future until a final outcome. The next batch is only read after the slowest user finishes. Example 1: one recipient hits a per-chat TelegramRetryAfter. Notifier retries up to 5 times, waiting retry_after each time, so the whole relay is stuck for up to 5 x retry_after. Example 2: a batch contains low-priority campaign messages while the high lane is busy (for example, the burst of /start replies a campaign itself triggers; each /start sends 3 messages). _get_next always serves high first, the low futures do not resolve, and the batch cannot finish.
- **Impact** Every other player's deposit, withdrawal and refund notifications stop until that one chat's backoff ends or the interactive burst dies down. One recipient's state delays everyone.
- **Suggested fix** Stop gathering on batch completion. Run a fixed pool of per-user worker tasks, or process each user's entries as independent tasks and keep reading the stream, preserving per-user ordering with a per-telegram_id queue or lock. Put a bounded wait on `done` before leaving the entry pending.

### 49. send_command leaks a pooled Redis connection whenever unsubscribe raises in its finally block

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/commands.py:89`
- **Status** Not yet verified
- **Trigger** The finally block runs `await pubsub.unsubscribe(...)` and then `await pubsub.aclose()`. With 0 client retries, a Redis ConnectionError or TimeoutError during unsubscribe (for example a Redis restart while commands are in flight, which also turns the CommandTimeout into ConnectionError) skips aclose(). redis-py 8.1's PubSub.__del__ does not return the connection, and ConnectionPool keeps it in _in_use_connections.
- **Impact** Each failure permanently uses up one of the process's 200 Redis connections. After an outage with many in-flight commands, the gateway (or the simulated-players worker) hits MaxConnectionsError on every Redis call for every player, including rate limits, fanout and commands, until the process restarts, even though Redis is back.
- **Suggested fix** Nest the calls: `try: await pubsub.unsubscribe(...) finally: await pubsub.aclose()`, or just call aclose(), which drops the subscriptions and returns the connection. Longer term, use one shared reply subscriber per gateway process instead of one dedicated connection per command.

### 50. Circuit breaker re-trips every round within the same 24h window, demoting one tier per round down to the floor

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:187`
- **Status** Fixed (c32384e), deployed 2026-10-01
- **Trigger** Trailing-24h keno_payout plus keno_jackpot_payout credits exceed daily_payout_circuit_breaker_multiple (default 3.0) times the expected payout. Jackpot payouts count toward actual, but expected_payout_contribution excludes jackpot EV. The first _create_round demotes one tier. check_circuit_breaker (packages/core/keno_tier_automation.py:243) keeps no memory of having tripped, and the window still exceeds the multiple, so each later _create_round (about every 37s) demotes again.
- **Impact** One hot 24h window, such as a single large win or jackpot on a low-volume day, pushes every player to Tier 1's stake, pick and max-win limits within a few rounds instead of a single step. Promotion back then needs a 7-day hold. Spec 7.3 says 'demote a tier'.
- **Suggested fix** Skip the breaker when a trigger='circuit_breaker' keno_tier_changes row already exists in the trailing 24h, or store a trip timestamp in keno_tier_state. Consider excluding keno_jackpot_payout from actual, or adding jackpot EV to expected.

### 51. Ticket-id hash snapshot at betting close can miss tickets committed by in-flight placements

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:270`
- **Status** Not yet verified
- **Trigger** _close_betting reads ticket ids with a plain SELECT (READ COMMITTED snapshot) BEFORE it touches the keno_rounds row. A place_ticket that already holds the round row FOR UPDATE commits its ticket after that SELECT. The close UPDATE then waits for it and proceeds, so the ticket is in the round and gets settled, but it is absent from ticket_ids_hash, the public_seed and the broadcast ticket_count.
- **Impact** No money impact (tickets are settled by round_id), but the provably-fair commitment does not match the round's real ticket set. Any verification of the hash against the ticket list fails for rounds with last-second bets.
- **Suggested fix** In _close_betting, run SELECT … FROM keno_rounds WHERE id=$1 FOR UPDATE (or run the status UPDATE first) before reading ticket ids, so every committed placement is visible and no new one can start.

### 52. Round transitions have no Postgres fence (no WHERE status = expected), and a worker that lost the lock mid-reveal still completes the draw and settles

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:281`
- **Status** Not yet verified
- **Trigger** Spec 5.2 requires 'optimistic UPDATE ... WHERE state = expected', but every transition (lines 229, 280-289, 311, 324, 360, 369, 703) is an unconditional UPDATE ... WHERE id=$1. The only guard is the Redis lock's local is_held(). _reveal_numbers returns on lock loss, but _run_draw still marks draw_complete and publishes all numbers, and _run_one_round spawns settlement without the lock. Scenario: two keno-worker processes (the compose comment says multiple replicas are safe) and the lock key vanishes (Redis restart or failover without persistence), so both believe they own the lock for up to one refresh interval. B's recover_on_startup resumes R while A keeps driving it. If B resumed R from betting_open after A closed it, B's _close_betting 25s later overwrites betting_closed_at, ticket_ids_hash and public_seed (not covered by the drawn_numbers trigger) and moves status back from completed to betting_closed, then on to completed again.
- **Impact** The stored public_seed no longer matches the immutable drawn_numbers, so /api/keno/rounds/{id} reports verified=false permanently, a visible fairness failure. Players get duplicated or interleaved reveals, and results and balance pushes before the reveal ends. Audit events are duplicated. Money stays safe only through the per-ticket idempotency keys (see the next finding for where that breaks). Prod currently runs one replica, which limits exposure.
- **Suggested fix** Add AND status = '<expected>' to every transition UPDATE, plus AND public_seed IS NULL for the seed write. Check the row count and stop driving the round on 0. In _run_draw, return without marking draw_complete when _reveal_numbers exited because of lock loss or stop.

### 53. Round N's single-transaction settlement holds the keno_reserve balance-row lock while every round N+1 bet waits on it, holding the global round lock and a pool connection

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:432`
- **Status** Not yet verified
- **Trigger** By design, settlement of round N overlaps betting for N+1. _settle_tickets posts every winning ticket's payout in ONE transaction, so the keno_reserve (and jackpot) account_balances row is locked FOR UPDATE from the first winner until the whole batch commits. Meanwhile each place_ticket for N+1 takes the keno_rounds row FOR UPDATE (keno_tickets.py:263) and then blocks in ledger.post on that same reserve balance row (keno_tickets.py:357). Every other bettor queues on the round row behind it, and the engine's own place_for_active_sessions blocks too. No lock_timeout or statement_timeout is configured.
- **Impact** All Keno bets stall for the full duration of the previous round's settlement, which grows linearly with its ticket count (seconds for a round of 1000 tickets). With 50 or more concurrent waiting requests, the gateway pool (max_size=50) is exhausted, and unrelated gateway endpoints (wallet, state, other games) fail on the 10 s acquire timeout. Every player is affected.
- **Suggested fix** Settle in bounded chunks (e.g. 50-100 tickets per transaction). Per-ticket idempotency keys and the status='pending' filter already make chunking safe, and chunking caps how long the reserve lock is held. Optionally set a lock_timeout in place_ticket so a waiting bet fails fast with a typed error.

### 54. Whole-round settlement in one transaction holds the keno_reserve (and jackpot) balance-row lock, stalling every next-round bet until it commits

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:442`
- **Status** Not yet verified
- **Trigger** Round N's settlement runs while round N+1's betting is open. From N's first winning ticket, ledger.post locks keno_reserve's account_balances row (and after a jackpot, the keno_jackpot_pool row and pool balance row). The lock is held until the whole batch commits: about 12 statements per winner plus 1 per loser. Every place_ticket for N+1 needs the same reserve and jackpot balance rows for its stake split. While it waits it holds N+1's keno_rounds row FOR UPDATE and the user's advisory lock, so all other bets queue behind it. The engine's autoplay placement for N+1 (line 248) also waits, and the betting timer starts only after it.
- **Impact** In a busy round, every player's bet (manual and autoplay) hangs for the length of the previous round's settlement at the start of each betting window. statement_timeout and lock_timeout are both 0, so nothing fails fast. N+1's real close moves past the betting_seconds advertised in keno.betting.open. A heavy round degrades every player's next round.
- **Suggested fix** Settle in bounded chunks, e.g. 100 tickets per transaction. The per-ticket idempotency keys and the WHERE status='pending' guard already make partial commits safe. Alternatively, aggregate the reserve debit into one ledger.post per chunk.

### 55. Autoplay net_position is applied outside the settlement transaction, so a crash after commit skips it permanently

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:481`
- **Status** Partly fixed by 939a29b (as #41)
- **Trigger** The worker is SIGKILLed or OOM-killed, or docker's default 10s stop timeout expires while run_forever's drain is still waiting on settlement. This happens after _settle_tickets' batch transaction commits (line 467) but before the post-commit loop reaches a ticket's record_settlement_safely. The retry pass never sees the ticket again because it is no longer 'pending'. record_settlement_safely's settlement_error stop runs only on an in-process exception, so the session is not stopped either.
- **Impact** The autoplay session keeps running with a net_position missing one round's result. stop_on_loss fires late (or stop_on_win never fires), and the player is charged beyond their chosen limit. The keno.ticket.settled push for those tickets is also lost.
- **Suggested fix** Apply UPDATE keno_autoplay_sessions SET net_position = net_position + $delta inside the batch transaction, next to the ticket status change. Keep only the threshold check/stop and the publishes post-commit, and make the threshold check re-read net_position so it is safe to re-run.

### 56. _settle_one_ticket posts the payout before claiming the ticket, and _pay_jackpot runs even when the claim failed

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:523`
- **Status** Fixed (9c06c90), deployed 2026-10-01
- **Trigger** ledger.post(keno_payout, key keno:settle:R:T) runs first. UPDATE ... WHERE status='pending' runs after it, and a False result only suppresses the publish; the payout stays in the committed transaction. If T left 'pending' under a different key, for example a refund (keno:refund:R:T) from another worker's recover_on_startup during split-brain, the payout still commits. In addition, _pay_jackpot (lines 457-460) is called whether or not settled is True. On a second concurrent settlement pass, its ledger.post dedupes, but line 561 overwrites keno_tickets.jackpot_payout with the pool's current re-accumulated balance.
- **Impact** Latent double credit (refund plus win) whenever a refund and a settlement overlap on one ticket. keno_tickets.jackpot_payout, and the round total_payout recomputed from it, can be rewritten to a wrong amount, so the player's history shows a jackpot different from what was paid. Not reachable with a single worker and no concurrent refunder.
- **Suggested fix** First run UPDATE keno_tickets SET status=... WHERE id=$1 AND status='pending' RETURNING id (this row-locks the ticket). Only on success, post the payout and then set payout_txn_id. Call _pay_jackpot only when the claim succeeded, and write jackpot_payout from the posted transaction's amount.

### 57. Several 5/5 jackpot tickets in one round: the first in unordered fetch order takes the whole pool, the rest get nothing

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/keno_round_engine.py:550`
- **Status** Confirmed (strict xfail); the multi-winner rule is the operator's decision
- **Trigger** Two or more 5-spot tickets hit 5/5 in the same round. This is realistic with correlated picks: players choosing the same popular set, or one player holding several identical tickets. _settle_tickets loops over tickets fetched with no ORDER BY (line 407). The first winner's _pay_jackpot posts the entire pool balance. For each later winner, ledger.balance in the same transaction returns 0 and _pay_jackpot returns Decimal(0).
- **Impact** The later winner sees a 5/5 hit, but keno.ticket.settled carries jackpot_payout=null. Heap/scan order, not any stated rule, decides which player gets the jackpot, so one player's ticket takes another's.
- **Suggested fix** Collect every jackpot-qualifying ticket in the round first, then split the locked pool balance equally, rounding down to the cent with the remainder left in the pool. Post each share under its own keno:jackpot:R:T key and document the split rule.

### 58. The single global pot_escrow balance row serializes every Bingo money move in every room, and refunds hold it across all entrants

- **Severity** medium, **fix size** large, **finder confidence** medium
- **Where** `services/engine/refunds.py:80`
- **Status** Not yet verified
- **Trigger** All Bingo rooms share one pot_escrow account (id 241, user_id NULL). Every join, drop, refund and settlement locks its account_balances row FOR UPDATE inside ledger.post and holds it until the caller commits. refund_round_in_transaction posts one ledger transaction per card in a loop, about 12 round trips each, inside a single transaction. Refunding a full room (100 players x 3 cards = 300 posts), or recovery refunding several rounds at startup, holds pot_escrow for roughly 1-4s.
- **Impact** While one room's round is being refunded, every other room's joins, drops and settlements block. Each room has a single sequential command loop, so the whole room stalls. Players elsewhere see 'room_unavailable' timeouts after 5s, while their commands still run later (see the stale-command finding).
- **Suggested fix** Use per-room or per-round escrow accounts, or batch a round's refund into a single ledger transaction with one entry per card. The per-card refund keys must still be recoverable for today_net_loss matching.

### 59. Emergency stop does not stop new stakes: the engine's join() idle fallback starts a round without checking rooms.is_active

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/round_engine.py:348`
- **Status** Not yet verified
- **Trigger** Admin stop_room_admin commits is_active=false while the engine is idle, which covers the whole _wait_before_next_round result/idle window. A player still connected to the room's WebSocket taps a card. join() sees status 'idle' and calls _start_new_round() with no is_active check, then takes the stake. run_forever next sees _room_is_still_active() false and breaks, releasing the lock with that lobby round and its stakes stranded. A second path: the engine's own is_active check (line 276) passes just before the stop commits, its INSERT INTO rounds waits on stop's rooms FOR UPDATE, then proceeds, and a full round plays and settles in the 'stopped' room.
- **Impact** The emergency lever doesn't stop money entering. Stakes sit in pot_escrow in a lobby that never starts until a later recover_orphaned_rounds pass refunds it. In the second path, a whole round runs after the operator stopped the room.
- **Suggested fix** In _start_new_round, read rooms.is_active FOR SHARE in the same transaction as the INSERT INTO rounds and refuse when inactive. Have join()'s idle fallback return not_joinable instead of creating a round when the room is inactive.

### 60. Exhausted-round refund leaves the status at 'running', so a late claim is acknowledged and then the round is voided; the orphaned settlement task can crash the engine

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/round_engine.py:843`
- **Status** Not yet verified
- **Trigger** After the 75th call with no winner, _run_running awaits refund_round, then the balance gather, then the server_seed UPDATE, then the round_end publish, all with self._status still 'running'. A manual claim processed by the command task in that window passes every check, because all 75 numbers are called and every card is complete. It flips the status to 'settling', creates a _finalize_after_window task and replies ok. The refund commits anyway. If that task fires during the gather, _settle_with_winners sees 'voided', aborts and calls _reset_to_idle(). _run_running then writes `server_seed = self._server_seed` (now None) at line 855 and dereferences `self._server_seed.hex()` at line 863, raising AttributeError. If the task fires after the reset instead, it fails an assert or split_derash(0) as an unobserved task exception.
- **Impact** The player is told their BINGO was accepted, then gets round_end with no winners and only a refund. The engine can die (the room goes dark until the next poll), and the round's server_seed can be written as NULL, so the provably-fair reveal is lost for that round. No money is created, because the refund and the FOR UPDATE check hold.
- **Suggested fix** Before awaiting refund_round in the exhausted branch, set a non-claimable status (for example settling with no deadline, or a dedicated 'voiding'). Capture server_seed in a local variable before the awaits. Cancel any _settlement_task inside _reset_to_idle.

### 61. Commands whose gateway call already timed out still run later, charging players who were told the action failed

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/engine/round_engine.py:1280`
- **Status** Not yet verified
- **Trigger** send_command waits 5s, then raises CommandTimeout, and the gateway shows 'room_unavailable' (connection.py:420). The stream entry is not removed and carries no deadline, and _serve_commands runs every entry in order no matter how old it is. When a room's command loop is backed up past 5s (pot_escrow contention, pool exhaustion, a slow DB), the timed-out take_card runs later: the player is charged and holds the card.
- **Impact** The player is charged for a card they were told they could not take. The card_taken broadcast does not identify them, so the UI may show it as someone else's card. A player who retries with a different card ends up holding and paying for both.
- **Suggested fix** In _serve_commands, read the millisecond timestamp from entry_id. For entries older than COMMAND_TIMEOUT_SECONDS, skip join/drop_card and reply 'expired'; late claims can still be allowed. Or have the gateway send a state_sync after a CommandTimeout.

### 62. The engine ignores the claim's round_id, so a stale claim is judged against the current round and can lock out a paid card

- **Severity** medium, **fix size** small, **finder confidence** low
- **Where** `services/engine/round_engine.py:1303`
- **Status** Not yet verified
- **Trigger** The gateway sends round_id in the claim payload, but _handle_command passes only card_no, so the payload's round_id is ignored. Suppose a client missed the round transition (hub backpressure drops or a reconnect) and the player taps BINGO for the previous round while holding the same card number in the new running round. The claim is checked against the new round's calls. With zero complete lines and source='manual', claim() adds (user, card) to _locked_out (line 586).
- **Impact** The player's paid card in the current round is locked out: auto-scan skips it and manual claims are refused, so it cannot win for the rest of the round.
- **Suggested fix** In _handle_command, reject a claim whose payload round_id differs from self._round_id with 'stale_round', and do not lock the card out.

### 63. Keno ticket per-IP rate-limit bucket (20/min) is shared by every player behind the same carrier NAT

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/gateway/app.py:514`
- **Status** Not yet verified
- **Trigger** Players on the same mobile carrier CGNAT egress IP (the Mini App calls come from the device, and CF-Connecting-IP is that public IP) together exceed 20 tickets per minute. For example, three players each placing three tickets per 37 s round come to about 15/min, and a fourth pushes the bucket over.
- **Impact** Innocent players get 429 'rate_limited' on bets because of other people's activity. One heavy player on a shared IP can block everyone else on that IP from betting.
- **Suggested fix** For authenticated requests, rely on the per-user bucket. Keep the IP bucket only as a much looser ceiling (e.g. 10-50x the per-user capacity), or key it on user+IP.

### 64. hot-cold endpoint's lookback_rounds is not clamped; one request can load all Keno history and block the gateway event loop

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/gateway/app.py:657`
- **Status** Fixed (f732569), deployed 2026-10-01
- **Trigger** Any authenticated player calls GET /api/keno/rounds/hot-cold?lookback_rounds=100000000, repeatedly (this endpoint has no rate limit). keno_queries.hot_cold_numbers (packages/core/keno_queries.py:236) runs `LIMIT $1` with no cap, fetches every completed round's drawn_numbers, then counts them in a pure-Python loop on the event loop. A negative value produces a 500.
- **Impact** Grows with history: about 1,440 rounds per day, so about 10M numbers after a year. Each call blocks the single gateway event loop for seconds, stalling WS fan-out, command acks and every other player's REST call on that replica, and puts heavy reads on Postgres.
- **Suggested fix** Clamp lookback_rounds with `min(max(lookback_rounds, 1), 500)`, the way my_tickets and recent_results already do. Optionally cache the result per completed round.

### 65. When a ConnectionQueue overflows with a non-droppable message, queued round_end/balance_update messages are discarded without triggering a resync

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/gateway/fanout.py:80`
- **Status** Not yet verified
- **Trigger** A client stalls briefly (backgrounded Telegram WebView, weak mobile link) and its 100-slot queue fills. Keno publishes about 50 non-droppable keno.* messages per round to every connection (DROPPABLE_TYPES only covers lobby_tick and call), so this happens within a couple of minutes of stalling. The next non-droppable arrival makes _handle_full empty the whole queue, including a queued Bingo round_end, the player's own balance_update or keno.ticket.settled, then enqueue only the new message. needs_state_sync is never set on this path.
- **Impact** When the client resumes it never receives the round result or balance change. It shows a stale balance and a board stuck in the old round until some unrelated event arrives. Players believe they were not paid, which leads to support load and repeat actions. Money in the ledger is correct.
- **Suggested fix** On the non-droppable overflow path, also set needs_state_sync and the wake event, and have the writer push a fresh balance snapshot along with the state_sync. Add keno.betting.closing and keno.number.drawn to the droppable types, with Keno resync done over REST.

### 66. payout_queue_depth uses XLEN on a stream that is never trimmed, so the depth alert is always on and cannot reveal a stalled consumer

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/app.py:283`
- **Status** Not yet verified
- **Trigger** enqueue_payout (withdrawals.py:320) XADDs with no MAXLEN, and nothing ever XDELs or XTRIMs 'payouts'. XACK does not remove entries. XLEN is therefore the lifetime count of enqueues, sweep duplicates included.
- **Impact** PayoutQueueDepthHigh (> 50) fires permanently once there have been 50 payouts in total, so a real backlog or a silently dead consumer_task (the missing-our_ref finding) looks the same as normal operation. The one queue alert carries no signal.
- **Suggested fix** Base the gauge on the consumer group's pending count plus lag (XPENDING, or XINFO GROUPS 'pending'/'lag') and alert on that. XADD with an approximate MAXLEN, or XDEL after ack.

### 67. The bonus sweep has no per-item isolation: one failing bonus, or a Redis publish error, aborts the rest of the tick for every other player

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/bonus_sweep.py:32`
- **Status** Fixed (fc82a5f), deploy pending
- **Trigger** Inside the for-loop, any exception from wagering_progress_for_user_since, the progress UPDATE, convert_bonus_to_cash/expire_bonus (BonusNotFound, InsufficientFunds, a DB error or deadlock abort) or publish_balance_update propagates straight out. A concrete case: redis.publish raises during a Redis blip after a conversion has already committed. _run_periodic_sweep (payout_worker.py:434-446) only catches at the tick level, and the candidate query has no ORDER BY.
- **Impact** Every bonus after the failing row is skipped for that tick. During a sustained Redis outage each tick commits at most one conversion or expiry and then aborts, so all players' conversions and expiries trickle through at one per minute. If a row ever fails the same way every time (e.g. a bonuses row whose amount exceeds user_bonus, which the schema does not prevent because grant_txn_id has no UNIQUE), the sweep never gets past it. Every player behind that row is stuck, with only a log line to show for it.
- **Suggested fix** Wrap each row's processing in try/except Exception that logs the bonus_id and continues. Make the post-commit publish best-effort (its own try/except). Add ORDER BY id and a metric for per-row failures.

### 68. The same wagering counts in full toward every active bonus a user holds at once

- **Severity** medium, **fix size** large, **finder confidence** medium
- **Where** `services/payments/bonus_sweep.py:34`
- **Status** Not yet verified
- **Trigger** A user holds several active bonuses, e.g. a referrer with several referral rewards (max_grants_per_user can be 5 or 10), or a welcome bonus plus a manual grant. The sweep computes progress for each bonus independently as all stakes since that bonus's own created_at.
- **Impact** One stake counts toward all of them, so N bonuses clear with the wagering of the largest single requirement rather than the sum. For example, 5 referral bonuses of 10 ETB (30 ETB wagering each) all convert after 30 ETB of stakes instead of 150. The house pays out more bonus as cash than the rules intend. The loss is bounded by the number of grants.
- **Suggested fix** Allocate wagering to one bonus at a time: process a user's active bonuses oldest first and subtract the wagering already used by earlier conversions, or track consumed wagering per bonus. Alternatively require the combined wagering_required of all overlapping bonuses.

### 69. The daily deposit cap is check-then-act with no per-user lock; concurrent intents or redemptions exceed it

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/deposits.py:151`
- **Status** Fixed (a31824d), deploy pending
- **Trigger** Chapa: create_deposit_intent runs _check_deposit_eligibility on a bare pooled connection with no transaction (line 184), then INSERTs the pending row. Five concurrent taps pass the 5-token DEPOSIT bucket, all compute today_total before any of the INSERTs are visible, and all pass. Telebirr: redeem_evidence runs the same check after locking only its own evidence row, and before the ledger.post that serializes on provider_settlement. Two redemptions of different references by the same user, sent at the same moment (for example two bot pastes, since aiogram handles updates concurrently, or bot plus Mini App), both pass. The payments INSERT and credit then go through without the cap being checked again.
- **Impact** A player's own responsible-gaming daily deposit cap, or the platform's daily_deposit_cap_etb, is bypassed by several times the remaining headroom. The overshoot is bounded by the rate-limit buckets and, for Telebirr, by how many real payments the player has.
- **Suggested fix** Serialize the cap check per user. Take pg_advisory_xact_lock(<deposit-cap namespace>, user_id) as the first statement, and in create_deposit_intent run the check and the INSERT in one transaction. In redeem_evidence, take the same advisory lock before the SUM.

### 70. The deposit webhook handler looks up the payment by our_ref without filtering on direction, so it can change a withdrawal's status

- **Severity** medium, **fix size** small, **finder confidence** low
- **Where** `services/payments/deposits.py:278`
- **Status** Fixed (b07aedd), deployed 2026-10-01
- **Trigger** _apply_confirmed_status selects the payments row by our_ref alone. If Chapa's signed webhook for a transfer event ever carries tx_ref equal to the withdrawal's our_ref (WD-...), unverified: a failed or cancelled status sets the withdrawal to 'failed' with no refund, and an amount mismatch sets it back to 'review'. A credit is blocked by the ledger's IdempotencyKeyConflict (the key our_ref already belongs to a 'withdrawal' transaction).
- **Impact** A withdrawal set to 'failed' this way has its funds stuck in user_locked with no path back. A 'processing' payout that was already sent reappears in the admin approve/reject queue: approving it dispatches it again, and rejecting it refunds money that was already paid out.
- **Suggested fix** Add AND direction = 'in' AND provider = $provider to the SELECT ... FOR UPDATE in _apply_confirmed_status, and return not_found otherwise.

### 71. _apply_confirmed_status never checks direction='in' or the provider on the payments row it locks

- **Severity** medium, **fix size** small, **finder confidence** low
- **Where** `services/payments/deposits.py:278`
- **Status** Fixed (b07aedd), deployed 2026-10-01
- **Trigger** A correctly signed Chapa event whose tx_ref names a WD- payout row. The SELECT is only `WHERE our_ref = $1`. A 'failed'/'cancelled' status then runs UPDATE payments SET status='failed' on the withdrawal without the payout_worker _reverse ledger move. A 'succeeded' status is stopped only incidentally, by ledger.post raising IdempotencyKeyConflict against the withdrawal txn that owns key our_ref. poll_pending_deposits filters direction='in', but the webhook path does not.
- **Impact** The player's withdrawal would be marked 'failed' while the amount stays in user_locked, and it would drop off the admin stuck-'processing' payout list, leaving the funds frozen. Whether Chapa ever sends tx_ref for transfer events is unverified.
- **Suggested fix** Add `AND direction = 'in' AND provider = $2` to the FOR UPDATE select, passing provider_name, and return 'not_found' otherwise.

### 72. run_provider_reconciliation aborts the whole report on one failing fetch_status

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/deposits.py:567`
- **Status** Not yet verified
- **Trigger** Any Chapa deposit updated in the last 2h whose verify call raises: an unmapped status, a non-success envelope such as an abandoned checkout, a timeout, or an HTML 5xx that makes response.json() raise. The per-row loop has no isolation, so the exception reaches _run_periodic_sweep and the whole hourly run is dropped.
- **Impact** No mismatch is detected or logged for that hour, and payment_reconciliation_mismatch_count keeps its old value, so dashboards look healthy. This is the safety net for the poll and webhook gaps above, so those gaps can stay invisible.
- **Suggested fix** Isolate each row with try/except and count errored rows as their own mismatch reason ('verify_failed'), so the gauge reflects them. Also set a separate 'last successful run' timestamp gauge.

### 73. The manual (and automatic) daily deposit cap is checked and then inserted without a lock, so parallel requests exceed it

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/manual.py:79`
- **Status** Fixed (a31824d), deploy pending
- **Trigger** _check_deposit_eligibility (deposits.py:147-157) sums today's deposits without locking the user row or taking an advisory lock. Several /deposit manual submissions fired in parallel by the same player, up to the 5 per hour Redis rate limit, each read today_total before the others' INSERTs commit, so all pass the check and all insert. create_deposit_intent has the same race, and there it is not even inside a transaction.
- **Impact** A player can go past the platform daily cap, or their own responsible-gaming deposit limit, by up to 5 times per hour. Admins then approve deposits that should never have been accepted.
- **Suggested fix** At the start of the transaction in _check_deposit_eligibility, take SELECT ... FROM users WHERE id=$1 FOR NO KEY UPDATE (or pg_advisory_xact_lock on the user_id), and wrap create_deposit_intent's check and insert in a transaction too.

### 74. The payout loop retries a failing entry with no backoff, and that entry blocks every new payout

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/payout_worker.py:403`
- **Status** Not yet verified
- **Trigger** process_one raises for an entry that is still pending (DB down or connection refused, a lock or statement timeout, _reverse failing). The next iteration's first read (pending list from '0', line 387) returns the same entry immediately with no sleep, and fresh entries ('>') are only read when this consumer's pending list is empty. Delivery counts are never checked and nothing is dead-lettered.
- **Impact** The loop runs as fast as it can and floods logs and the DB during an outage. While any entry keeps failing, every other player's new withdrawal waits behind it. Combined with the re-dispatch bug, each retry that fails after the provider call calls Chapa again.
- **Suggested fix** Back off (for example an exponential sleep) after process_one fails. Use XPENDING delivery counts to dead-letter an entry after N attempts. Read fresh entries even while entries that keep failing remain pending.

### 75. evidence_hash is computed over the raw bytes, so a re-delivery of the same SMS with only formatting differences flips live evidence to 'disputed'

- **Severity** medium, **fix size** small, **finder confidence** medium
- **Where** `services/payments/telebirr_ingest.py:186`
- **Status** Not yet verified
- **Trigger** The same real Telebirr SMS reaches ingestion twice with any byte difference: MacroDroid plus the Telegram-agent fallback, a CRLF vs LF difference, a trailing space, Telegram's own whitespace trimming, or an agent re-pasting it. Another trigger: MacroDroid substitutes a multi-line [sms_message] unescaped into its JSON body template. json.loads then fails and app.py:152 falls back to storing the whole '{"raw_sms": ... "device_id": ...}' text as the SMS. The parsed fields are identical, but sha256(raw) differs, so lines 314-325 set the existing 'available' row to 'disputed'.
- **Impact** The player who genuinely paid gets PAYMENT_DISPUTED on redemption until an admin manually resolves the row, even though nothing actually conflicts.
- **Suggested fix** Compute the dedupe hash over _normalize_whitespace(raw), or compare the parsed fields (amount, date, parties, direction). Treat identical parsed content as a DUPLICATE and dispute only when a financial field differs. In app.py, reject a body that fails to parse as JSON when its Content-Type is application/json, instead of ingesting the wrapper text.

### 76. Redeeming a 'rejected' evidence row hits an AssertionError instead of returning a code

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/telebirr_redemption.py:196`
- **Status** Not yet verified
- **Trigger** The evidence was ingested with status='rejected' (recipient_not_recognized). This happens, for example, when a destination name or phone mismatch occurs like the 2026-09-14 incident, when an SMS arrives before the destination is configured, or when a player forwards a transfer to the wrong person. The player then pastes the SMS or enters the reference. _STATUS_TO_CODE only maps blocked, disputed and expired, and the redeemed branch doesn't match, so `assert status == "available"` raises inside the transaction.
- **Impact** The gateway returns an unhandled 500. In the bot, aiogram logs the exception and the player gets no reply at all. Each attempt uses up a TELEBIRR_REDEEM rate-limit token. A player who genuinely paid gets no explanation or next step. Money is not moved.
- **Suggested fix** Add 'rejected' to _STATUS_TO_CODE with its own code (for example PAYMENT_REJECTED) plus bot and gateway messages. Replace the assert with an explicit fallthrough that returns a safe code for any unexpected status.

### 77. Withdrawal amounts are not rounded to cents, which creates a cent per withdrawal and a ledger-versus-balance mismatch

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/withdrawals.py:118`
- **Status** Not yet verified
- **Trigger** A player POSTs /api/withdraw with amount '99.995' while holding 100.00 cash. The gateway and bot only check amount > 0, and request_withdrawal never rounds. ledger.post's Python check passes (100.00 - 99.995 >= 0). ledger_entries.amount is numeric(18,2), so the entries are stored as -100.00 and +100.00. The account_balances UPDATE computes balance + (-99.995) = 0.005 and stores 0.01. Verified with a SELECT: cached cash 0.01, entry -100.00, locked 100.00.
- **Impact** The player withdraws 100.00 (payments.amount is rounded to 100.00) and keeps 0.01 of cached cash that has no ledger entries behind it, repeatable on every withdrawal. Any player can at will open a gap between cached balances and the ledger, which sweep_ledger_reconciliation reports; the alert comments call ledger mismatches page-immediately.
- **Suggested fix** Reject amounts that are not already at 2 decimal places (amount != amount.quantize(Decimal('0.01'))) in request_withdrawal and in the gateway and bot parsing. Ideally ledger.post should also assert that every entry amount has at most 2 decimal places.

### 78. Banned players can still withdraw, and small amounts auto-approve straight to Chapa

- **Severity** medium, **fix size** small, **finder confidence** low
- **Where** `services/payments/withdrawals.py:131`
- **Status** Fixed (f18bdda), deployed 2026-10-01: banned or limited accounts go to review
- **Trigger** request_withdrawal reads kyc_level, created_at and is_simulated but never users.status. Deposits refuse banned users (deposits.py:122) and play is blocked, but a player banned for fraud can still call /api/withdraw, and an amount at or below 2000 ETB that passes the other checks goes straight to the payout stream.
- **Impact** Funds of an account frozen for fraud, collusion or bonus abuse can leave the platform before anyone reviews it. Whether banned players should be allowed to cash out is a product decision, but they bypass review entirely.
- **Suggested fix** If status is 'banned' (and possibly 'limited'), force review (add a failed_checks entry) rather than auto-approving, or reject, according to policy.

### 79. The chargeback window is measured from when the deposit was created, not when it was credited, so a player can easily get around it

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/withdrawals.py:151`
- **Status** Fixed (1b5c2cc), deployed 2026-10-01
- **Trigger** The RecentReversibleDeposit check filters on payments.created_at. A Chapa deposit's created_at is the time the checkout was made, and a manual deposit's is the submission time. A player creates a Chapa checkout, waits 30 minutes, pays, is credited, and withdraws at once. Any manual deposit an admin approves more than 30 minutes after submission can also be withdrawn at once.
- **Impact** Freshly credited money that could still be reversed can be withdrawn immediately, which is exactly what the rule exists to block.
- **Suggested fix** Key the window on the time the deposit was credited, for example updated_at for status='succeeded' rows, a new succeeded_at column, or the created_at of the deposit's ledger transaction.

### 80. The 'withdrawals exceed deposits' review rule never fires for Chapa, because Chapa payouts never reach 'succeeded'

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/withdrawals.py:250`
- **Status** Not yet verified
- **Trigger** lifetime_out sums only direction='out' AND status='succeeded' (line 222). ChapaProvider.create_payout always returns status='processing' (chapa.py:242), and payout_worker leaves those rows at 'processing' for good, so on the Chapa rail lifetime_out only ever counts manually settled withdrawals. Approved, processing and review withdrawals that are still in flight are not counted either.
- **Impact** A net winner (for example 100 deposited, 10,000 won) keeps auto-approving withdrawals straight to Chapa, up to 3 per day each at or below the auto-approve limit. The risk rule meant to send these to human review is disabled in practice.
- **Suggested fix** Count out-payments with status IN ('review','approved','processing','succeeded'), and compare lifetime_in against lifetime_out plus the current amount.

### 81. A Redis error after the withdrawal commits reports failure for a withdrawal that exists, and a retry creates a second one

- **Severity** medium, **fix size** small, **finder confidence** high
- **Where** `services/payments/withdrawals.py:312`
- **Status** Fixed (ac047af), deploy pending
- **Trigger** The transaction commits, then publish_balance_update (a pool.fetch and redis.publish) raises on a Redis blip. The exception reaches the gateway, which returns a 500, or cmd_withdraw, which has no generic handler and sends no reply. enqueue_payout is skipped; the sweep picks the row up after 60-120s. Neither /api/withdraw nor /withdraw takes an idempotency key.
- **Impact** The player sees an error or nothing, although their cash is already locked and the payout will go out. A natural retry creates a second withdrawal and locks more cash. No money is created, but the player withdraws more than intended and is confused.
- **Suggested fix** Wrap publish_balance_update and enqueue_payout in try/except after the commit (log, and let the sweep recover), and always return the intent. Optionally accept a client-supplied request id stored uniquely on payments.

### 82. Bonus grant, convert and expire ledger transactions are never counted in ledger_transactions_total

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `packages/core/bonuses.py:122`
- **Status** Not yet verified
- **Trigger** convert_bonus_to_cash, expire_bonus, revoke_bonus and grant_bonus each open their own transaction, so the nested post() sees is_in_transaction() and skips the metric. None of these functions or their callers (the sweep, admin, and the referral/welcome paths inside deposit transactions) increment it after commit. Expire and revoke also reuse kind 'bonus_grant' for reversals.
- **Impact** Metrics and dashboards undercount bonus money movement, and grants cannot be told apart from reversals by kind. Hygiene only.
- **Suggested fix** Increment metrics.ledger_transactions_total after these functions' own top-level commit (or have them return the txn so callers can). Add a 'bonus_reverse' kind to the ledger_transactions_kind_check constraint for expire and revoke.

### 83. Notification Center audiences include simulated players

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `packages/core/campaigns.py:93`
- **Status** Not yet verified
- **Trigger** _build_where only excludes self_excluded, banned and cooling-off users, never is_simulated. Simulated players get negative telegram_ids (the Telegram group-chat id range) when created through simulated_players_queries. The dev DB also holds is_simulated rows with positive telegram_ids up to 1887826338.
- **Impact** Campaigns spend the shared 25 msg/s Notifier budget on sends that cannot succeed, and those count as failures. Any simulated row with a real-looking positive id would send promotional text to a real stranger.
- **Suggested fix** Always add `AND NOT is_simulated` to _build_where.

### 84. start_session surfaces expected races and validation errors as raw 500s

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_autoplay.py:146`
- **Status** Not yet verified
- **Trigger** A double-tap on Start: both requests pass the SELECT at 146, and the second INSERT violates ux_keno_autoplay_one_active_per_user (asyncpg.UniqueViolationError). Invalid picks raise keno.KenoError at line 117, and a NaN stake makes `stake <= 0` raise decimal.InvalidOperation. None of these is an AutoplayError, which is the only exception the gateway (app.py:603) catches.
- **Impact** The player sees a generic 500 even though the first session was created (double-tap) or instead of a translated validation message. No money impact.
- **Suggested fix** Catch UniqueViolationError and raise AutoplaySessionAlreadyActive. Wrap KenoError in InvalidAutoplayConfig. Reject non-finite Decimals (stake, stop amounts) before comparing them.

### 85. No demotion when the reserve is below every tier's min_reserve (negative reserve)

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_tier_automation.py:123`
- **Status** Not yet verified
- **Trigger** keno_reserve is a system account, so it can go negative (payouts, or an admin reserve withdrawal) while the current tier is 2 or higher. Tier 1's min_reserve is 0, so no tier qualifies, and max(..., default=current_tier) picks the current tier.
- **Impact** The engine keeps the higher-risk tier instead of demoting to Tier 1. Bets are effectively halted anyway by the negative exposure ceiling, so the effect is bounded, but the tier state is wrong until an admin intervenes.
- **Suggested fix** Default to the lowest tier_number in all_tiers, not current_tier.

### 86. Circuit breaker demotes one tier every round while the 24 h window stays hot, and scans the whole ledger each round

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `packages/core/keno_tier_automation.py:221`
- **Status** Demotion half fixed with #50; the per-round 24h ledger scan remains
- **Trigger** Trailing-24h payouts exceed the configured multiple. check_circuit_breaker runs on every _create_round (about every 37 s) with no check for a breaker demotion already recorded in the window, so it demotes again each round until it reaches the floor tier. At the floor it increments keno_tier_changes_total{trigger='circuit_breaker'} every round even though nothing changed. The actual_payout aggregate filters ledger_transactions by kind and created_at, and the table has only pkey and idempotency_key indexes.
- **Impact** One hot hour drops Tier 4 to Tier 1 within about 2 minutes, instead of the single demotion the spec describes. Promotion back then needs a 7-day hold, which changes limits for every player. The metric counts false changes. A full ledger seq scan (all games' history) runs on the engine's round-creation path while keno_tier_state is held FOR UPDATE, and it slows every round as the ledger grows.
- **Suggested fix** Skip the breaker if keno_tier_changes has a trigger='circuit_breaker' row within the last 24 h, and do not count a change at the floor. Add an index on ledger_transactions(kind, created_at), or aggregate from keno_tickets.payout/jackpot_payout instead.

### 87. publish_balance_update raises on a Redis error after the money has already committed, so callers lose the follow-up notification or abort their loop

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `packages/core/ledger.py:404`
- **Status** Not yet verified
- **Trigger** redis.publish raises (timeout or connection error) in any post-commit caller. In deposits._apply_confirmed_status the exception skips notify_user and the webhook returns 500. The provider retries, but payment_events and status='succeeded' are already committed, so the retry returns 'duplicate' and never sends the notification. In bonus_sweep it aborts the rest of the tick.
- **Impact** A player's 'deposit confirmed' Telegram message, and similar messages, are permanently lost after a Redis blip. The provider sees 500s for a deposit that was actually credited. Balances are correct.
- **Suggested fix** Make publish_balance_update best-effort: catch Exception around redis.publish, log it and return the snapshot. The UI already re-fetches on reconnect.

### 88. Referral rewards are granted, and bonuses converted, regardless of the recipient's account status

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `packages/core/referrals.py:85`
- **Status** Not yet verified
- **Trigger** A referee deposits while their referrer is banned or self_excluded. maybe_grant_referral_bonus never reads the referrer's users.status, and sweep_bonus_wagering converts active bonuses for any user.
- **Impact** A banned fraud account keeps accruing promo money, and a self-excluded player keeps receiving and converting promotional credit. This is a responsible-gaming and compliance problem, bounded by the rule amounts.
- **Suggested fix** Skip the grant when the referrer's status is not 'active', and skip or hold conversion in the sweep for users who are banned or self_excluded.

### 89. The referral cap and welcome grant are check-then-act with no lock or constraint of their own, and bonuses.grant_txn_id is not UNIQUE (safe today only because of the provider_settlement lock)

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `packages/core/referrals.py:147`
- **Status** Not yet verified
- **Trigger** Two deposits for the same user (or two referees of one referrer) confirm concurrently. Both read count(*) or already_rewarded before either commits. For welcome, both compute the same key 'welcome-U-R-0'. The second grant_bonus's post() waits on the first's key and then returns the existing txn, and grant_bonus goes on to INSERT a second bonuses row for the same grant_txn_id (nothing prevents it). For referral, two different referees both pass `grants_to_referrer < max_grants_per_user`. This cannot currently happen through deposits.py, admin approve_manual_deposit_admin or telebirr_redemption, only because all three post to provider_settlement (a global FOR UPDATE row) before calling maybe_grant_*.
- **Impact** This is a latent defect. If the hot-row lock is ever removed, or a new trigger path is added that does not post to provider_settlement, one ledger credit ends up with two active bonuses rows. The second conversion or expiry then raises InsufficientFunds (and jams the sweep, see above) or drains another bonus's funds, and a referrer can exceed max_grants_per_user.
- **Suggested fix** Add UNIQUE(grant_txn_id) on bonuses. In maybe_grant_* take pg_advisory_xact_lock(user_id) or lock the users row before the count and already_rewarded checks, so correctness does not depend on an unrelated hot row. Catch the duplicate in grant_bonus by returning the existing row.

### 90. SMS claim query ranks the tenant's entire message history on every fetch-job, while holding the node's row lock

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `packages/core/sms/messages.py:147`
- **Status** Not yet verified
- **Trigger** Every /v1/nodes/fetch-job call runs ROW_NUMBER() over every sms_messages row for the tenant, delivered and dead-lettered included, because status='queued' is only applied after the window function. That prevents the ix_sms_messages_queue partial index from being used, so the whole table is scanned and sorted while the node's sms_delivery_nodes row is held FOR UPDATE.
- **Impact** Each poll costs more as history grows, heartbeats from the same node queue behind the lock, and many polling nodes add steady DB load that competes with game traffic on the shared Postgres.
- **Suggested fix** Apply status='queued' inside the CTE, since fairness only needs the position among queued messages, so the partial index is used.

### 91. update_bonus_rule_admin fails on every numeric or date field edit (json.dumps of Decimal)

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/admin/bonus_queries.py:142`
- **Status** Not yet verified
- **Trigger** before={k: before[k]} passes asyncpg Decimal and datetime values into audit.record, which calls plain json.dumps and raises TypeError. That rolls back the update. Only the is_active path is tested.
- **Impact** An admin cannot lower reward_amount, reward_percentage, reward_cap, wagering_multiplier or the dates on a live rule, for example during a bonus-farming incident. The only lever is deactivating the rule.
- **Suggested fix** Serialize the before and after values with str() or keno_queries._json_safe, and coerce incoming numeric strings to Decimal before binding.

### 92. set_current_tier_admin records a stale from_tier and counts its metric before commit

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/admin/keno_queries.py:408`
- **Status** Not yet verified
- **Trigger** 'before' is read without FOR UPDATE, while keno_tier_automation holds keno_tier_state FOR UPDATE and may be changing it. The upsert then waits and overwrites. metrics.keno_tier_changes_total is incremented inside the transaction (line 428).
- **Impact** keno_tier_changes and the audit log can record the wrong from_tier_id. The metric counts an override whose audit insert may still roll back. Audit accuracy only.
- **Suggested fix** SELECT ... FROM keno_tier_state WHERE id=1 FOR UPDATE for 'before', and move the metric increment after the transaction commits.

### 93. Keno reserve deposit and withdrawal use a random uuid idempotency key, so a retried request moves money twice

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/admin/keno_queries.py:502`
- **Status** Fixed (24d2649), deployed 2026-10-01
- **Trigger** idempotency_key=f"admin-reserve-deposit-{uuid4()}" (and admin-reserve-withdrawal at line 587) is new on every call. A browser or proxy retry, or a resubmit after a timeout, posts a second keno_reserve_deposit or withdrawal. The confirm() dialog in overview.js blocks only a literal double-click.
- **Impact** The reserve ledger balance drifts from what the operator actually funded. The reserve drives tier promotion and the 10%-of-reserve round exposure cap, so an overstated reserve allows exposure that isn't backed. A duplicated withdrawal understates it.
- **Suggested fix** Take a client request_id as adjust_balance does and key on admin-reserve-{direction}-{admin_id}-{request_id}.

### 94. Concurrent adjust_balance replays write two audit rows for one ledger transaction

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/admin/queries.py:328`
- **Status** Not yet verified
- **Trigger** Two in-flight requests with the same request_id both pass the pre-check SELECT before either commits. ledger.post dedups the second as a replay, but both still write audit.record and increment the metric.
- **Impact** The ledger is correct, but the audit log shows two balance adjustments, with before and after balances, where only one happened.
- **Suggested fix** Take pg_advisory_xact_lock(hashtext(idempotency_key)) before the pre-check, or compare the returned txn against a fresh insert and skip the audit on a replay.

### 95. void_round_admin refunds silently and mislabels a voided zero-entrant round as unchanged

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/admin/queries.py:581`
- **Status** Not yet verified
- **Trigger** An admin voids a running round: no balance_update, no notification, and no round_voided broadcast. The engine only stops calling numbers (_call_next_number returns False) and resets without announcing anything. An admin voids an empty lobby round: refund_round_in_transaction sets it 'voided' but returns 0.
- **Impact** Players watch numbers stop with a stale balance and no explanation. For the empty round, the audit row says 'unchanged (already terminal)' and the API returns refunded:false for a round that was in fact voided.
- **Suggested fix** Mirror stop_room_admin's post-commit steps (balance updates, a notify gated on refunded_count > 0, a room broadcast). Derive the audit 'after' from the round's real status after the call.

### 96. A Redis failure after commit turns committed money actions into HTTP 500s and drops the player notification

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/admin/queries.py:2239`
- **Status** Not yet verified
- **Trigger** approve_manual_deposit_admin (2239), settle_manual_withdrawal_admin (2463), fail_manual_withdrawal_admin (2524) and stop_room_admin's asyncio.gather at 745 all call ledger.publish_balance_update after commit, and it does not swallow errors, unlike notify_user. A Redis blip at that moment raises out of the handler.
- **Impact** The ledger is correct, but the admin sees a 500 for a deposit that was credited, and a retry returns no_op/false, so the UI says it failed. The player never gets the deposit_confirmed, withdrawal_succeeded or withdrawal_failed message. For stop_room, the round_voided broadcast is also skipped.
- **Suggested fix** Wrap the post-commit publish_balance_update calls in try/except with logging, as notify_user does, or use gather(..., return_exceptions=True).

### 97. Money notifications with an unescaped admin-entered reason are silently dropped by Telegram's HTML parser

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/bot/notification_relay.py:92`
- **Status** Not yet verified
- **Trigger** An admin rejects a withdrawal or manual deposit with a reason such as 'amount < minimum'. That reason is passed through notify_user kwargs and interpolated by t() without escaping. The bot's default parse_mode is HTML, so Telegram returns TelegramBadRequest (can't parse entities). Notifier catches it, marks the message 'failed' and drops it, and the relay XACKs.
- **Impact** The player never hears that their withdrawal was rejected or their deposit refused, a money-meaning message lost for good. It only shows up as a notifier_send_failed log line.
- **Suggested fix** html.escape every kwarg value before formatting in the relay (or in t() when HTML mode is on), or send notify.* messages with parse_mode=None.

### 98. Transactional notifications are sent twice if the bot crashes between the Telegram send and XACK

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/bot/notification_relay.py:132`
- **Status** Not yet verified
- **Trigger** Notifier delivers a notify_user message (for example 'deposit confirmed 500 ETB') and the bot process is killed (deploy, OOM) before xack at line 132. Only campaign entries are checked against a status first. On restart the pending read replays the entry and it is sent again. Campaign entries have the same window between the send and mark_delivery_outcome.
- **Impact** The player gets a duplicate money-meaning message, such as a second 'deposit confirmed', and may think they were credited twice. The ledger is not affected.
- **Suggested fix** After a successful send, record a short-TTL 'sent' marker keyed by the stream msg_id (SET NX) before XACK, and check it before sending. This narrows the duplicate window to the send itself.

### 99. Fire-and-forget publishes keep no reference and are never awaited; the try/except around the private ticket-settled publish cannot catch its failure

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/engine/keno_round_engine.py:81`
- **Status** Not yet verified
- **Trigger** Redis is down or slow while _publish (line 81) and _publish_private_ticket_settled (line 749) schedule redis.publish with asyncio.ensure_future and drop the returned task.
- **Impact** Failures appear only as asyncio 'Task exception was never retrieved' at GC time, with no structured log or metric. The loop keeps only weak references to the tasks. The per-ticket isolation at lines 475-480 covers only the awaited balance update. Separate tasks also give no ordering guarantee, for example between keno.ticket.settled and balance_update, or between round.completed for N and betting.open for N+1. No money impact.
- **Suggested fix** Keep publish tasks in a set, with a done-callback that logs and counts exceptions and then discards the task.

### 100. Gauge and tier-automation failures in _create_round abort the round cycle after the round row is committed

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/engine/keno_round_engine.py:179`
- **Status** Not yet verified
- **Trigger** An exception in _update_solvency_gauges (full SUM over account_balances), check_circuit_breaker or evaluate_tier_transition (24h aggregates, keno_tier_state FOR UPDATE), _refresh_tier_gauge, or _update_oldest_nonterminal_round_gauge (line 147) propagates out of _run_one_round.
- **Impact** run_forever unwinds, drains, releases the lock, and the worker sleeps 5s before re-acquiring. recover_on_startup then resumes the already-committed 'scheduled' round, so every player sees a delayed round. If the failure is persistent, every round goes through the recovery path. The worker survives, so the impact is bounded.
- **Suggested fix** Wrap the metrics-only updates, and optionally the tier automation, in try/except that logs and increments a metric, so they cannot fail round creation.

### 101. Betting timer starts after autoplay placement, and a resumed betting_open round gets a fresh full window, so client countdowns don't match the real close

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/engine/keno_round_engine.py:257`
- **Status** Not yet verified
- **Trigger** _open_betting publishes betting.open (with betting_seconds) and then awaits place_for_active_sessions, which is sequential per session and can queue behind the settlement lock. Only after that does _run_betting_phase set deadline = monotonic() + betting_seconds. On recovery, _resume_round (lines 678-679) restarts a full window instead of spec 5.3's 'remaining time from betting_closes_at', and publishes no new betting.open.
- **Impact** keno.js computes the countdown from betting_opened_at + betting_seconds, so every player's countdown hits 0 while betting is still open. The gap is the autoplay placement time, which grows with the number of active sessions, or a whole extra window after recovery. Round cadence slows for everyone as autoplay use grows. No money impact.
- **Suggested fix** Derive the deadline from the persisted betting_opened_at, and store and publish betting_closes_at. On resume, use the remaining time and close immediately if it has elapsed. Bound autoplay placement time, or do it before the countdown starts.

### 102. _close_betting reads ticket ids before taking the round row lock, so a ticket committing at close is missing from ticket_ids_hash and ticket_count

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/engine/keno_round_engine.py:275`
- **Status** Not yet verified
- **Trigger** When betting closes, a place_ticket transaction holds R's keno_rounds row FOR UPDATE, with the status check passed and the ticket inserted but not committed. _close_betting's SELECT id FROM keno_tickets snapshot excludes that ticket. The next UPDATE keno_rounds waits for the ticket to commit, then writes betting_closed with a hash computed without it.
- **Impact** The ticket is still settled, so money is correct. However, the published fairness commitment (hash of every accepted ticket) and keno.betting.closed ticket_count leave it out, so recomputing ticket_ids_hash from keno_tickets gives a mismatch for that round.
- **Suggested fix** Run UPDATE keno_rounds SET status='betting_closed', betting_closed_at=now() first (or lock the row with SELECT ... FOR UPDATE). Then select ticket ids in the same transaction, which now sees the committed tickets, and write ticket_ids_hash and public_seed.

### 103. Recovery has no per-round isolation, and it runs ahead of room claiming on every poll

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/engine/recovery.py:76`
- **Status** Not yet verified
- **Trigger** recover_orphaned_rounds refunds stuck rounds one after another with no try/except. run_active_rooms calls it before claiming rooms, and start() calls it outside any try. A refund_round failure for one round (a deadlock against a concurrent join or drop, a pool-acquire timeout, a DB error) aborts recovery for all later rounds and skips the claim pass for every room in that poll. At startup it aborts the whole process.
- **Impact** Normally bounded to one skipped 30s poll: dead rooms stay unclaimed and newly activated rooms get no engine for that period. A failure that repeats on the same round would block every room reclaim platform-wide, or crash-loop the worker at startup.
- **Suggested fix** Wrap each refund_round call in try/except, log, and continue. In run_active_rooms, run recovery in its own try so that claiming still happens.

### 104. Bingo join reads users.status without a row lock, so a concurrent ban or self-exclusion can let one more stake through

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/engine/round_engine.py:407`
- **Status** Not yet verified
- **Trigger** join takes pg_advisory_xact_lock(user_id), then check_stake_allowed reads users.status with a plain SELECT. Admin set_user_status (today's fix) and self_exclude update the users row under a row lock, but a plain SELECT does not wait for that lock and reads the last committed 'active' status. Keno place_ticket takes users FOR NO KEY UPDATE for exactly this reason; Bingo join does not.
- **Impact** A player being banned or self-excluding at that instant can still stake one more Bingo card. The window is milliseconds and the stake is ordinary play money, so this is a responsible-gaming parity gap rather than money loss.
- **Suggested fix** After the advisory lock in join(), run `SELECT status FROM users WHERE id=$1 FOR NO KEY UPDATE` before check_stake_allowed, matching keno_tickets.place_ticket's lock order.

### 105. A publish failure after join or drop_card commits turns a real stake or refund into an 'internal_error' reply

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/engine/round_engine.py:462`
- **Status** Not yet verified
- **Trigger** join() commits the stake and updates _entries and _pot, then awaits publish_balance_update (a DB read plus a Redis publish) and the card_taken publish. If either raises (pool timeout or Redis error), _handle_command's except returns JoinResult(False,'internal_error'). drop_card has the same shape at lines 511-512.
- **Impact** The player is told the take failed even though they were charged and hold the card. Other players never get the card_taken broadcast and hit 'card_taken' when they try that card. It can be recovered through state_sync, but it misleads the player and invites duplicate buys.
- **Suggested fix** Wrap the post-commit balance and room publishes in try/except and log, then return ok. The money move and the in-memory state are already consistent at that point.

### 106. A simulated player's room assignment is lost when send_command raises partway through its joins

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/engine/simulated_players_worker.py:223`
- **Status** Not yet verified
- **Trigger** _join_room sets status='joining', then loops over send_command calls. If one raises (CommandTimeout, or a Redis error) after an earlier card has already joined, the final UPDATE that records current_room_id and 'playing' never runs. Timed-out joins that run later (see the stale-command finding) leave the bot holding cards the DB does not know about.
- **Impact** The bot really holds staked cards in room X, but its row says it is in no room. On the next tick it can join a different room, so one bot sits in two rooms at once and active_count undercounts, which breaks the max_concurrent_bots cap. Bots are house-funded, so no real player's balance is wrong.
- **Suggested fix** Wrap the join loop in try/finally so the final status and current_room_id UPDATE always runs, using joined_any.

### 107. Dead engine tasks are replaced without their exception ever being retrieved or logged

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/engine/worker.py:142`
- **Status** Not yet verified
- **Trigger** When a RoundEngine.run_forever task ends with an exception (see the round-loop crash finding), run_active_rooms only checks existing_task.done() and overwrites the task through claim_room. Nothing calls task.exception() or logs it, and run_forever has no except clause.
- **Impact** Engine crashes are silent, apart from asyncio's 'Task exception was never retrieved' at garbage collection, and there is no metric or structured log. Rounds get voided by recovery with no visible cause, which hides every other engine-crash bug.
- **Suggested fix** Before reclaiming, if task.done() and not task.cancelled() and task.exception() is set, log it with logger.exception and increment a metric. Or add a done-callback in claim_room.

### 108. Withdrawal endpoints take no client idempotency key, so a double-tap or retry creates two withdrawals

- **Severity** low, **fix size** small, **finder confidence** medium
- **Where** `services/gateway/app.py:429`
- **Status** Not yet verified
- **Trigger** A player double-taps Withdraw in the Mini App, or the client retries after a slow response, or the bot /withdraw command is sent twice. request_withdrawal creates a new our_ref each time and uses it as the ledger idempotency key, so both requests lock funds and both can be auto-approved under auto_approve_withdraw_etb.
- **Impact** Two payouts of the player's own money, using up 2 of their 3 daily withdrawals. No money is created, but the result is unexpected and may cost double provider fees or need admin cleanup.
- **Suggested fix** Accept a client idempotency_key on /api/withdraw (and derive one from the Telegram update_id for the bot), namespace it per user, and store it with a UNIQUE constraint on the payments row, returning the existing intent on conflict.

### 109. Ingest route crashes with a 500 on JSON bodies that are not objects or whose raw_sms is not a string

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/payments/app.py:149`
- **Status** Not yet verified
- **Trigger** An authenticated device posts a JSON body that is a list, number or string: data.get raises AttributeError. Or it posts {"raw_sms": null} or a number: raw_sms.strip() raises AttributeError. Separately, if the JSON is invalid, the whole wrapper text is silently treated as the SMS (see the evidence_hash finding).
- **Impact** The request gets an unhandled 500. record_ingestion_outcome is not updated, so device health counters miss the failure. This is limited to token holders.
- **Suggested fix** Validate that data is a dict and raw_sms is a str, returning 422 otherwise. Honor Content-Type rather than guessing.

### 110. The sweep converts before it checks expiry, and counts stakes placed after expires_at

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/payments/bonus_sweep.py:43`
- **Status** Not yet verified
- **Trigger** A bonus passes its expires_at. Before the next sweep tick (60 s, or much longer if the sweep is failing), the player stakes enough, including stakes placed after expiry. The sweep sees progress >= required, converts, and never reaches the expiry branch. wagering_progress_for_user_since has no upper time bound.
- **Impact** Expired bonuses can still become cash. The window is short when the sweep is healthy and unbounded when it is stuck.
- **Suggested fix** Bound the wagering query to created_at <= le.created_at < COALESCE(expires_at, 'infinity'), or check expiry first unless the requirement was met before expires_at.

### 111. Every deposit on every rail serializes on the single provider_settlement balance row until commit

- **Severity** low, **fix size** large, **finder confidence** medium
- **Where** `services/payments/deposits.py:334`
- **Status** Not yet verified
- **Trigger** _apply_confirmed_status and redeem_evidence (telebirr_redemption.py:229) both call ledger.post, which takes FOR UPDATE on the global provider_settlement account_balances row. That lock is held through the rest of the transaction, including the payments UPDATE and the several queries in maybe_grant_referral_bonus and maybe_grant_welcome_bonus (plus the global promo_expense row when a bonus is granted). Payout settlement locks the same row.
- **Impact** All players' deposit credits and payout settlements queue on one row. At bursts, such as many redemptions after a promo, deposit latency grows linearly for everyone. It is correct but a throughput ceiling. The one upside is that it accidentally serializes the welcome-bonus count check.
- **Suggested fix** Don't keep a locked cached balance for system accounts, updating it asynchronously or deriving it from entries, or shard provider_settlement. At minimum, keep post-lock work in these transactions short.

### 112. A Redis error after commit skips the deposit notification and turns a committed credit into an error

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/payments/deposits.py:374`
- **Status** Not yet verified
- **Trigger** The credit transaction commits, then ledger.publish_balance_update fails on a Redis blip. Unlike notify_user, it does not catch exceptions. Webhook path: Chapa gets a 500 and retries, the retry returns 'duplicate', and notify_user never runs. Poll path: the exception aborts the rest of that pass. Telebirr path (telebirr_redemption.py:263): the bot handler raises and the player gets no 'redeemed' message, or the Mini App gets a 500, even though the wallet was credited.
- **Impact** The player never receives the deposit-confirmed Telegram message and may see an error after a successful credit. Retrying shows success, so money is correct. The loss is bounded to that one notification.
- **Suggested fix** Wrap the post-commit publish_balance_update and notify_user calls in try/except Exception with logging, in _apply_confirmed_status and redeem_evidence, so they cannot fail a committed credit.

### 113. The ledger reconciliation gauges are never updated when the check itself fails, so a broken check looks like 'no mismatch'

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/payments/ledger_reconcile_sweep.py:35`
- **Status** Not yet verified
- **Trigger** reconcile_all raises (DB error, pool acquire timeout, or the full-table aggregate being cancelled). _run_periodic_sweep only logs it. In reconcile_job.main, asyncio.run raises before the Pushgateway push.
- **Impact** ledger_reconciliation_sweep_mismatch_count and the pushed ledger_reconciliation_mismatch_count keep their last value (typically 0). The paging alert in deploy/prometheus/alerts.yml can then stay silent indefinitely while the integrity check is not running at all.
- **Suggested fix** Set a last-success timestamp gauge on each successful run and alert on staleness, or set the mismatch gauge to -1 / increment a failure counter in an except around reconcile_all.

### 114. A Redis error after a refund commits skips the player's 'withdrawal failed' message for good

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/payments/payout_worker.py:162`
- **Status** Not yet verified
- **Trigger** _reverse commits, then publish_balance_update raises on a Redis or DB blip, so notify_user and xack never run. On redelivery the status is 'failed', so process_one takes the skip branch and acks without notifying.
- **Impact** The player's withdrawal failed and the money is back in cash, but they are never told. They see a withdrawal that silently didn't arrive.
- **Suggested fix** Wrap publish_balance_update in try/except (log) after _reverse and _settle_success, so the notification and ack always run.

### 115. Hourly Telebirr reconciliation query is quadratic: correlated count(*) on the unindexed payment_evidence.payment_id

- **Severity** low, **fix size** small, **finder confidence** high
- **Where** `services/payments/telebirr_reconcile.py:50`
- **Status** Not yet verified
- **Trigger** find_evidence_source_mismatches runs two correlated `SELECT count(*) FROM payment_evidence e WHERE e.payment_id = p.id` subqueries for each telebirr_sms payment. There is no index on payment_evidence.payment_id (checked with pg_indexes), so each subquery is a sequential scan. The cost grows as payments × evidence every hour.
- **Impact** As Telebirr volume grows, the hourly sweep becomes a long, CPU-heavy query on the shared primary. It slows every player's transactions, and its failure is only logged.
- **Suggested fix** Add an index on payment_evidence(payment_id), or rewrite as one LEFT JOIN ... GROUP BY p.id HAVING count(e.id) <> 1.
