"""Plans and periods (docs/to_be_developed/credits-implementation-plan.md §5.7, T19, T20).

A purchase becomes credits in one place, `PlanFulfilment`. One-time credits are a bucket that lasts a year; a plan is
a chain of
periods, each granting its credits when it starts and not before. `PeriodActivator` starts them, inside every
movement of the
wallet (so the credits are spendable the moment a period begins) and from the hourly job.
"""
