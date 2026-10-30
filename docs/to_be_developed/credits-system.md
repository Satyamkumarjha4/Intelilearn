# Feature Spec: Credits System

**Product:** Socra
**Status:** Finalized design, ready for implementation (open items in §12)
**Last updated:** 2026-10-29
**Related:** `modular-lessons.md`

---

## 1. Overview

Every generating action in Socra costs credits.

- Users **earn** free credits by signing up and staying active (daily activity, weekly and monthly streaks).
- Users **buy** credits as one-time top-ups or prepaid plans.

All credits live in a wallet made of **buckets with expiry dates**. Every change to a wallet is recorded in an append-only **ledger**.

Design principles:

- **Credits only.** There are no daily usage limits.
- **Users never pay for our failures.** Backend generation failures are refunded automatically.
- **Prices live in the database, not the code.** Admins can edit them.
- **Everything is prepaid.** No auto-renewal, no upgrades or downgrades.
- **No model tiers for now.** If tiers come later, the system will be extended then.

---

## 2. Spending Credits

### 2.1 Full lesson: 10 credits

The 10 credits break down as follows (shown to users in a "What's in your 10 credits" tooltip):

| Part | Credits | Reasoning |
|---|---|---|
| Level check (diagnostic quiz or self-rating) | 1 | Same as a 5-question quiz |
| Lesson (3 pages × 2) | 6 | 1 page = 1 sheet = 2 credits |
| Final test (10 questions, lesson-based) | 3 | Same as a 10-question lesson-based quiz |
| **Total** | **10** | |

#### Staged charging (diagnostic quiz path)

| Stage | Charged | Running total |
|---|---|---|
| User starts the lesson; diagnostic quiz is generated | 3 | 3 |
| User completes the diagnostic quiz | 7 | 10 |

- If the user **abandons before completing the quiz**, only the 3 credits are kept.
- Once the quiz is completed, the remaining 7 are charged **even if the user never opens the lesson or takes the test**.

#### Self-rating path

There is no quiz stage. The full **10 credits** are charged when lesson generation starts.

#### Perfect diagnostic (half-price path)

If the user scores **full marks on the diagnostic quiz**, they are offered a choice:

| Choice | Second-stage charge | Total paid |
|---|---|---|
| Continue with the full lesson | 7 | 10 |
| Skip the lesson and get the cheat sheet + revision sheet only | 2 | **5** (half price) |

The half price is applied by charging less at stage two. No refund transaction is needed. In the UI it is presented as "You already know this. Here's half your credits back."

There is never a 100% refund.

### 2.2 Quick quiz

| Questions | Base | From existing lesson(s) or with calibration quiz |
|---|---|---|
| 5 | 1 | 2 |
| 10 – 15 | 2 | 3 |
| 20 – 30 | 3 | 4 |

- The +1 is charged **once**, even if both modifiers apply (it does not stack).
- **Short and long answers are only available for quizzes of 10 or more questions.** 5-question quizzes are restricted to MCQ, MSQ and numerical.
- Questions are generated in batches. The **batch size is configurable in admin** (default 5).
- Grading runs once, after all questions are answered (it is not batched).

### 2.3 Other actions

| Action | Credits |
|---|---|
| Retest (lesson final test) | 2 |
| Cheat sheet | 2 (+1 from a lesson, or +1 with a quiz first) |
| Revision sheet | 2 (+1 from a lesson, or +1 with a quiz first) |
| Both sheets together | 2 + 2 + 1 (the +1 is charged once) |
| Foundation follow-up lesson | 5 (no quiz needed; level comes from the test score) |
| Advanced follow-up lesson | 7 |
| Lesson picked from recommendations | 9 (10 − 1 discount) |

- The recommendation discount does **not** stack with follow-up pricing. A recommended Foundation lesson is still 5.
- **Sheets cannot be regenerated** for now.
- Retests and other actions require enough credits. Socra **never absorbs costs**. If the user can't afford an action, it can't be generated.

### 2.4 Insufficient credits

- Every action button shows its credit cost before the user clicks.
- If the balance is too low, show an "Inadequate credits" message and send the user to the **pricing / buy page**.
- An action is never started and then failed midway for lack of credits. The full cost (or the stage cost) is checked up front.

---

## 3. Generation Failures

| Failure type | Handling |
|---|---|
| **Frontend / network** (connection drop, timeout on the client) | Ask the user to **reload, not retry**. Reloading fetches the already-generated data. No refund, no second charge. |
| **Backend** (generation failed, incomplete or corrupt data) | **Full automatic refund** of the credits charged for that action. |

**Implementation requirements:**

- Generation must run **server-side, independent of the client connection** (a background job or task). A dropped client connection must not kill or duplicate the generation. This is what makes "reload" safe.
- Charges use **hold → commit → release**:
  1. The stage cost is held when the action starts.
  2. It is committed on success.
  3. It is released on a backend failure.
- Every charge carries an **idempotency key**, so a reload or double-click never charges twice.

---

## 4. Earning Free Credits

### 4.1 Signup

- **30 credits** on registration.
- Sign-in methods:
  - Google
  - Apple
  - Microsoft
  - email + OTP verification
- Disposable email domains are blocked (use a public blocklist).

### 4.2 Daily activity: 1 credit per day

The user must perform **at least one meaningful action** that day. Visiting a page does not count. Qualifying actions:

- generating a lesson, quiz or sheet
- attempting or completing a test or quiz (including one generated earlier)

The action does **not** need to cost credits. For example, generating a lesson on day 1 and taking its included test on day 2 counts as two active days.

The day boundary is the **user's local midnight**.

### 4.3 Streak bonuses

| Milestone | Bonus |
|---|---|
| Each completed 7-day streak (day 7, 14, 21, 28) | +10 (one free lesson) |
| Completed 28-day "month" (on day 28) | +10 extra |

So on day 28 the user receives 10 (week) + 10 (month) = 20.

A **month is 28 days** throughout the system.

**Maximum free credits per 28-day cycle:** 28 (daily) + 40 (weekly) + 10 (monthly) = **78**, plus 30 at signup in the first cycle.

### 4.4 Streak repair

When a user misses a day, they can repair it for **1 credit**.

- The repaired day **does not award** the daily credit.
- Limits:
  - **1 repair per week**
  - **3 repairs per 28-day month**
- These limits stop the "skip every other day and repair" loop.

---

## 5. Buying Credits

All purchases are **prepaid**. There is no auto-renewal.

### 5.1 Plans

| Plan | Credits | Validity | Price | ₹ / credit |
|---|---|---|---|---|
| One-time credits | any amount, **minimum 10** | 1 year | ₹1 per credit (min ₹10) | 1.00 |
| Weekly Pro | 100 per week | 1 week | ₹49 per week | 0.49 |
| Monthly Pro | 500 | 28 days | ₹199* | 0.40 |
| Pro Plus | 750 | 28 days | ₹279* | 0.37 |

\*Proposed prices. Not yet confirmed (§12).

- One-time credits have **no volume discount**. This is deliberate, to promote plans.
- One-time credits can be bought on top of any plan.

### 5.2 Buying multiple weeks

Buying several Weekly Pro plans at once **drips** the credits week by week. For example, 3 × ₹49 = ₹147 gives:

- Week 1: 100 credits, valid 1 week
- Week 2: 100 credits, valid 1 week
- Week 3: 100 credits, valid 1 week

Credits are never granted all at once.

### 5.3 Changing plans

- **No upgrades or downgrades.** Only one plan is active at a time.
- Buying a different plan while one is active **queues** it. It starts when the current cycle ends.
- Example: a user on Weekly Pro buys Monthly Pro. The monthly plan starts after the current week ends.

### 5.4 Payments

- **Stripe in test mode** for now.
- Before going live in India, re-check Stripe's onboarding status for Indian businesses and the RBI rules for card payments. Razorpay is the fallback.

---

## 6. Expiry & Spend Order

| Credit source | Expiry |
|---|---|
| Purchased (one-time) | 1 year from purchase |
| Subscription (weekly / monthly / Pro Plus) | End of that plan period |
| Bonus (daily, weekly streak, monthly streak) | 90 days from grant |
| Signup | 90 days *(proposed, see §12)* |

**Spend order: earliest expiry first.** In practice this means subscription → bonus → purchased, so the credits the user paid for directly last longest.

---

## 7. Notifications

A notification area at the top of the page warns about expiring credits.

| Credit type | Warnings start |
|---|---|
| Weekly subscription | 2 days before expiry; repeats daily until the last day |
| Monthly / Pro Plus subscription | During the last 7 days of the period |
| Bonus / purchased | *(proposed: last 7 days, see §12)* |

Example message: "This is your last day to use 40 credits."

---

## 8. User-Facing Pages

- **Wallet:** current balance, broken down by bucket, with expiry dates.
- **Transaction history:**
  - credits used (by action)
  - credits bought
  - credits earned (signup, daily, streaks)
  - refunds
  - repairs
- **Pricing / buy page:** plans and one-time credits. This is also the target of the "inadequate credits" redirect.
- **Streak display:** current streak, repairs remaining this week and this month.

---

## 9. Admin

- **Edit prices** for every action. Prices are stored in an `ActionPrice` table; nothing is hardcoded.
- **Configure quiz generation batch size.**
- **Grant or revoke** credits manually for any user, with a required reason. This creates a ledger entry.
- **View any user's ledger** and wallet.
- **Revenue vs model cost** dashboard.

---

## 10. Legal

- **Terms & Conditions:**
  - credits are **non-refundable once used**
  - expiry rules
  - prepaid, no auto-renewal
  - the half-price perfect-diagnostic rule
- **Privacy Policy:** cover the payment and usage data stored.

---

## 11. Proposed Data Model (sketch)

```
CreditBucket
  user, source (signup | daily | weekly_streak | monthly_streak | purchase | subscription | admin_grant | refund)
  amount_granted, amount_remaining, expires_at, created_at

CreditTransaction   (append-only ledger)
  user, amount (+/-), type (grant | debit | hold | commit | release | refund | repair | admin_adjust | expire)
  action (nullable: lesson_stage1 | lesson_stage2 | quick_quiz | retest | sheet | followup | ...)
  related_object (generic FK), bucket_allocations (json), idempotency_key (unique), created_at

CreditHold
  user, amount, action, related_object, status (held | committed | released), expires_at

ActionPrice
  action_key, credits, active, updated_by, updated_at

Plan
  key (one_time | weekly_pro | monthly_pro | pro_plus), credits, period_days, price_inr

PlanPurchase
  user, plan, quantity, amount_paid, stripe_payment_id, status

PlanPeriod          (one row per drip or period; supports queueing)
  user, plan_purchase, starts_at, ends_at, credits, bucket (FK), status (queued | active | ended)

StreakState
  user, current_streak, last_active_date (user-local), repairs_used_week, repairs_used_month, cycle_start_date
```

**Implementation notes:**

- **Wallet updates must be atomic.** Use `select_for_update` on the user's buckets inside a transaction.
- **Debits allocate across buckets** in earliest-expiry order. Record the allocation on the transaction so refunds return credits to the same buckets.
- **Run a scheduled job daily** that:
  - expires buckets
  - activates queued plan periods
  - drips weekly credits
  - evaluates streaks
  - sends expiry notifications

---

## 12. Open Items

- [ ] **Lesson stage-1 charge:** 3 is assumed (2 or 3 was discussed; 3 keeps 3 + 7 = 10).
- [ ] **Monthly Pro / Pro Plus prices:** ₹199 / ₹279 proposed.
- [ ] **Short/long answer cap per batch:** proposed max 1 long + 2 short per batch, so a quiz can't be all subjective.
- [ ] **Streak repair window:** previous day only (within 48 h), or any missed day in the current week?
- [ ] **Signup credit expiry:** 90 days, like bonus credits?
- [ ] **Expiry notifications for bonus and purchased credits:** last 7 days?