# Working on this repository

Start with [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md). It has:
- the current production state;
- the operator's standing rules;
- the decisions waiting on the operator;
- the recommended next work;
- a map of every other document.

Keep it true. Update it in the same commit when you:
- deploy;
- record a decision;
- add a migration or a service;
- change an audit finding's status;
- start or finish a piece of work.

Its first section says which parts to touch. `tests/unit/test_project_state_doc.py` fails when the facts it checks drift.

## Standing rules (the operator's; hard gates)

- **Real money:** no real money moves (reserve transfers, adjustments, grants) until the operator has confirmed the exact transaction. Then post it, then verify it.
- **The Keno switch:** only the operator flips `keno_enabled`.
- **Shared databases:** no manual SQL against a shared database without first showing the exact statement and its target.
- **Bugs:** reproduce first, then fix, with a test that fails on the old code and passes on the new.
- **Policy:** limits, game rules and player-facing wording are the operator's call. Record a strict `xfail` test and ask.
- **Results:** never fabricate them. Quote real output, and say when something was skipped or failed.
- **Commits:** small, with a message explaining why, pushed to `origin` (github.com/Nebiyu-Dejenie/game). Confirm with the operator before pushing to any other remote.
- **Deploys:** present the plan, get approval, deploy between Bingo rounds, verify, then record it in `docs/ops/hotfix-2026-09-26-live-bingo.md`.

## Tests

Run tests against a throwaway Postgres 15 and Redis 7 migrated to head, never the dev database on port 5433. The recipe is in [docs/PROJECT_STATE.md#testing-status](docs/PROJECT_STATE.md#testing-status). The tests don't run migrations themselves.
