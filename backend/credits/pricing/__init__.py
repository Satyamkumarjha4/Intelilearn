"""Prices: the table (`PriceBook`), the rule for each action (`PriceRule`), and what a learner is quoted.

One `PriceQuoter` answers both the gate, which charges, and the quote endpoint, which only tells, so a screen never
repeats
a rule and a learner is never shown one price and charged another.
"""
