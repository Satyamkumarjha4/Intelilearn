"""Earning credits: the learner's day, streaks and their bonuses, repairs, and the signup grant
(docs/to_be_developed/credits-implementation-plan.md §5.6, §6.3). The rules are pure classes with no database and no
clock,
so each is a table of cases; the classes that write (`DailyCredit`, `StreakRepairService`, `SignupGrant`) go through the
`Ledger`."""
