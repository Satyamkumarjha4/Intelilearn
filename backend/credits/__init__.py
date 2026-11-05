"""Credits: the wallet, the ledger, prices, earning and plans (docs/to_be_developed/credits-implementation-plan.md).

Phase 10.1 is the ledger only: wallets, buckets, an append-only ledger, holds, and `Ledger`, the one class that moves
credits. Nothing calls it yet. `lessons` and `quizzes` never import this app: the gate and the activity sink reach it
through the `ACTION_GATE` and `ACTIVITY_SINK` settings.
"""
